"""Diagnostic records for failures nobody has classified yet (the person decides whether one is sent).

``core.failure_clue`` sends closed codes only. That says "ValueError at worker.segments" but never why. This module
builds a richer record for the same failure WITHOUT ever placing free text from the person's computer in it:

* the exception class and the OS error number;
* the last frames of the traceback as ``module:function:line``, only for this app's own modules and for a short
  allow-list of bundled open-source libraries (their file and function names are public code, not personal data);
* the exception message reduced to its shape: only words from a fixed technical vocabulary
  (:mod:`core.diagnostic_vocab`) survive, short numbers survive, EVERYTHING else (names, paths, URLs, e-mail
  addresses, quoted text, long numbers) becomes ``*``. An allow-list cannot leak what it does not contain;
* a short hash of the shape, so identical failures group together.

Nothing here touches the network. :func:`compose` turns a record into the one-line text that the person sees in the
dialog and that :mod:`core.problem_report` would send; :func:`remember` keeps the last records in a local file the
person can attach to a GitHub issue.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

from core.diagnostic_vocab import VOCABULARY

logger = logging.getLogger(__name__)

#: Frames are kept only for this app's own packages and for these bundled libraries.
APP_PACKAGES = ("core", "app")
LIBRARY_PACKAGES = (
    "faster_whisper", "ctranslate2", "yt_dlp", "av", "numpy", "docx", "tkinter", "torch", "onnxruntime",
    "tokenizers", "huggingface_hub", "sounddevice", "soundfile", "pyannote", "mlx", "mlx_whisper", "psutil",
    "urllib", "http", "json", "subprocess", "multiprocessing", "threading", "queue", "pathlib", "zipfile",
    "sqlite3", "shutil", "tempfile", "concurrent",
)
MAX_FRAMES = 5
MAX_SHAPE_CHARS = 160
KEEP_RECORDS = 30

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
_MAX_NUMBER_DIGITS = 4


def _top_package(module: str) -> str:
    return module.split(".", 1)[0]


def frames_text(tb: TracebackType | None, limit: int = MAX_FRAMES) -> str:
    """The last *limit* allow-listed frames, oldest first, as ``module:function:line`` joined by ``>``."""
    kept: list[str] = []
    while tb is not None:
        module = str(tb.tb_frame.f_globals.get("__name__", ""))
        if _top_package(module) in APP_PACKAGES + LIBRARY_PACKAGES:
            kept.append(f"{module}:{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next
    return ">".join(kept[-limit:])


#: A number survives only when it stands alone next to one of these words: an OS or HTTP code, a size. Numbers in a
#: row ("192 168 1 1", "415 555 0123") are never kept, because a run of short numbers is an address or a phone number.
_NUMBER_CONTEXT = frozenset({"winerror", "errno", "error", "code", "status", "exit", "returned", "signal",
                             "bytes", "byte", "http", "channels", "dimension", "axis", "index", "line"})


def message_shape(text: object) -> str:
    """*text* with every token outside the technical vocabulary replaced by ``*`` (see the module docstring).

    Only letters and digits are ever looked at, so path separators, quotes, brackets and URL punctuation vanish
    with the tokens they belonged to. Numbers become ``#`` unless one stands alone beside a context word (an error
    code or a size). Consecutive ``*`` and ``#`` collapse. The result is lower case ASCII.
    """
    tokens = _TOKEN.findall(str(text or ""))
    kinds = ["n" if t.isdigit() else "w" for t in tokens]
    out: list[str] = []
    for i, token in enumerate(tokens):
        if kinds[i] == "n":
            alone = (i == 0 or kinds[i - 1] != "n") and (i + 1 >= len(tokens) or kinds[i + 1] != "n")
            near = (i > 0 and tokens[i - 1].lower() in _NUMBER_CONTEXT) or (
                i + 1 < len(tokens) and tokens[i + 1].lower() in _NUMBER_CONTEXT)
            piece = token if alone and near and len(token) <= _MAX_NUMBER_DIGITS else "#"
        else:
            lowered = token.lower()
            piece = lowered if lowered in VOCABULARY else "*"
        if piece in ("*", "#") and out and out[-1] == piece:
            continue
        out.append(piece)
    return " ".join(out)[:MAX_SHAPE_CHARS].strip()


def _revalidate_shape(text: object) -> str:
    """A shape that arrived from the worker: keep only vocabulary words, digits, ``*`` and ``#``."""
    kept = [t for t in str(text or "").split()
            if t in ("*", "#") or t.isdigit() or t in VOCABULARY]
    return " ".join(kept)[:MAX_SHAPE_CHARS]


def _os_error(exc: BaseException) -> int:
    if not isinstance(exc, OSError):
        return 0
    value = getattr(exc, "winerror", None) or exc.errno or 0
    return value if isinstance(value, int) and 0 <= value <= 0xFFFFFFFF else 0


def build(exc: BaseException) -> dict[str, str]:
    """The record for *exc*: only short ASCII strings, safe to put in a worker event."""
    cls = type(exc).__qualname__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,60}", cls) or _top_package(type(exc).__module__) not in (
        "builtins", *APP_PACKAGES, *LIBRARY_PACKAGES
    ):
        # An exception class from an unknown package could carry a private name: keep only its base class.
        base = next((b.__name__ for b in type(exc).__mro__ if b.__module__ == "builtins"), "Exception")
        cls = base
    try:
        shape = message_shape(exc)
    except Exception:  # a broken __str__ must not hide the exception class
        shape = ""
    digest = hashlib.blake2b(f"{cls}|{shape}".encode("ascii", "replace"), digest_size=4).hexdigest()
    return {
        "cls": cls,
        "os": str(_os_error(exc)),
        "frames": frames_text(exc.__traceback__),
        "shape": shape,
        "hash": digest,
    }


def sanitise(record: Mapping[str, Any] | None) -> dict[str, str]:
    """A record received from a worker, re-checked: wrong types or characters become empty, nothing else passes."""
    src = record if isinstance(record, Mapping) else {}
    out = {"cls": "", "os": "0", "frames": "", "shape": "", "hash": ""}
    cls = str(src.get("cls", ""))
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,60}", cls):
        out["cls"] = cls
    os_text = str(src.get("os", "0"))
    out["os"] = os_text if os_text.isdigit() and len(os_text) <= 10 else "0"
    frames = str(src.get("frames", ""))
    if re.fullmatch(r"[A-Za-z0-9_.:<>\-]{0,400}", frames) and all(
        _top_package(f.split(":", 1)[0]) in APP_PACKAGES + LIBRARY_PACKAGES for f in frames.split(">") if f
    ):
        out["frames"] = frames
    out["shape"] = _revalidate_shape(src.get("shape", ""))  # the parent never trusts the worker
    digest = str(src.get("hash", ""))
    if re.fullmatch(r"[0-9a-f]{8}", digest):
        out["hash"] = digest
    return out


def fingerprint(record: Mapping[str, str]) -> str:
    """Groups the same failure: class, the innermost frame and the shape hash."""
    last = (record.get("frames") or "").rsplit(">", 1)[-1]
    return f"{record.get('cls', '')}|{last}|{record.get('hash', '')}"


def duration_bucket(seconds: float | int | None) -> str:
    """Length of the media as a coarse bucket (never the exact length)."""
    try:
        s = float(seconds or 0)
    except (TypeError, ValueError):
        return "0"
    if s <= 0:
        return "0"
    for limit, name in ((300, "<5m"), (1800, "5-30m"), (3600, "30-60m"), (3 * 3600, "1-3h")):
        if s < limit:
            return name
    return ">3h"


def compose(record: Mapping[str, str], *, site: str = "", device: str = "", duration: str = "") -> str:
    """The one line the person sees and a report would carry; the most useful parts come first.

    The reader of a clipped report loses the END, so the order is: class, site, hash (grouping), frames, device,
    media length, OS error, message shape.
    """
    parts = [
        f"E={record.get('cls', '')}", f"site={site}", f"h={record.get('hash', '')}",
        f"F={record.get('frames', '')}", f"dev={device}", f"dur={duration}",
    ]
    if record.get("os") not in (None, "", "0"):
        parts.append(f"os={record['os']}")
    parts.append(f"M={record.get('shape', '')}")
    return " ".join(p for p in parts if not p.endswith("="))


def log_path() -> Path:
    from core.config import user_log_dir
    return Path(user_log_dir()) / "diagnostics.jsonl"


def remember(line: str, *, path: Path | None = None, keep: int = KEEP_RECORDS) -> None:
    """Append *line* (already composed, so already filtered) to the local diagnostics file; keeps the last *keep*.

    Never raises: a full disk must not turn one failure into two.
    """
    try:
        target = path or log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        rows: list[str] = []
        if target.is_file():
            rows = [r for r in target.read_text(encoding="utf-8", errors="replace").splitlines() if r.strip()]
        rows.append(json.dumps({"t": int(time.time()), "d": line}, ensure_ascii=True))
        tmp = target.with_suffix(".tmp")
        tmp.write_text("\n".join(rows[-keep:]) + "\n", encoding="utf-8")
        tmp.replace(target)
    except OSError:
        logger.debug("Could not keep the diagnostic record", exc_info=True)
