"""Burn an SRT into a video via ffmpeg.

``burn(video_path, srt_path, out_path)`` uses ffmpeg's ``subtitles``
filter, which renders the SRT as a vector overlay on top of the video
stream. It blocks until ffmpeg ends; on large videos that takes a while,
so callers run it on a background thread. Optional hooks report a real
percent (ffmpeg ``-progress pipe:1`` against the probed duration), let the
caller cancel, and hand over the ffmpeg process so an existing cancel path
can tree-kill it.

Video is encoded with ffmpeg's defaults (H.264) and the audio stream is
copied when the output container accepts the source codec, falling back to
an AAC re-encode when it does not (e.g. an Opus track from a downloaded
``.webm``/``.mkv``). Adjust by passing ``extra_args``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
from typing import Any, Callable, NamedTuple

from ._proc import kill_process_tree, new_session_kwargs
from .paths import bundled_binary

logger = logging.getLogger(__name__)

# ffmpeg's muxers reject an audio codec the target CONTAINER cannot carry
# (the common real case: an Opus/Vorbis track copied out of a downloaded
# .webm/.mkv into the .mp4 the Save dialog suggests). ffmpeg reports it as
# one of these two phrases; matching them lets burn() retry once with AAC
# instead of failing outright, without retrying on unrelated errors.
_CONTAINER_AUDIO_HINTS = (
    "not currently supported in container",
    "could not find tag for codec",
)


def _stderr_tail(exc: subprocess.CalledProcessError) -> str:
    return (exc.stderr or b"").decode("utf-8", "replace")[-1000:]


def _container_rejected_audio(stderr_text: str) -> bool:
    """True when ffmpeg's stderr is the container/codec-incompatibility error."""
    s = (stderr_text or "").lower()
    return any(hint in s for hint in _CONTAINER_AUDIO_HINTS)


# Audio codecs an MP4 carries that common players (phones, TVs, QuickTime)
# play; anything else is re-encoded to AAC.
_MP4_PLAYABLE_AUDIO = frozenset({"aac", "mp3", "ac3", "eac3", "alac"})


def _extra_args_set_audio_codec(extra_args: list[str] | None) -> bool:
    """True when the caller already chose an audio codec via extra_args."""
    if not extra_args:
        return False
    prefixes = ("-c:a", "-codec:a", "-acodec")
    return any(arg.startswith(prefixes) for arg in extra_args)


_RLM = chr(0x200F)  # RIGHT-TO-LEFT MARK
_RLE = chr(0x202B)  # RIGHT-TO-LEFT EMBEDDING
_PDF = chr(0x202C)  # POP DIRECTIONAL FORMATTING

# Strong right-to-left letters: Hebrew, Arabic (+ Supplement / Extended-A),
# Syriac, Thaana, NKo and the Arabic/Hebrew presentation forms.
_RTL_RANGES = (
    (0x0590, 0x08FF),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFF),
)
# Letters of the Arabic script only (the font choice below is per script).
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
_HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
_KANA_RANGES = ((0x3040, 0x30FF), (0x31F0, 0x31FF))

# Windows font per script for the burned subtitles. libass falls back to
# Arial, which on Windows 10 draws a missing-glyph box inside common Persian
# words and mixes glyph weights in Chinese; Tahoma and Microsoft YaHei ship
# with every Windows install and render both cleanly. Other systems keep
# libass's own font fallback (fontconfig / CoreText).
_WINDOWS_SCRIPT_FONTS = {
    "arabic": "Tahoma",
    "han": "Microsoft YaHei",
}


def _in_ranges(ch: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def _has_rtl(line: str) -> bool:
    return any(_in_ranges(ch, _RTL_RANGES) for ch in line)


def wrap_rtl_lines(text: str) -> str:
    """Give every line holding right-to-left letters an RTL base direction.

    libass lays out each subtitle line with a left-to-right base direction.
    A Persian line that mixes Latin words and digits ("... 1.9.3 ... macOS
    ...") then came out with its clauses in the wrong order, and a final "."
    "!" or "»" (neutral characters) at the wrong end. The line is wrapped in
    RIGHT-TO-LEFT EMBEDDING ... POP DIRECTIONAL FORMATTING (U+202B / U+202C,
    which libass's fribidi honours, rendered and checked), with a RIGHT-TO-LEFT
    MARK just inside each end. The marks are invisible: removing them gives
    back the input, and wrapping twice changes nothing. SRT index and timing
    lines hold no RTL letters, so they pass through untouched.
    """
    out: list[str] = []
    for line in text.split("\n"):
        # Keep a CR of a CRLF file outside the marks.
        body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        if _has_rtl(body) and not (body.startswith(_RLE) and body.endswith(_PDF)):
            if not body.startswith(_RLM):
                body = _RLM + body
            if not body.endswith(_RLM):
                body = body + _RLM
            body = _RLE + body + _PDF
        out.append(body + cr)
    return "\n".join(out)


def _dominant_script(text: str) -> str:
    """``"arabic"``, ``"han"`` or ``""`` for the script most letters use."""
    arabic = han = kana = 0
    for ch in text:
        if _in_ranges(ch, _ARABIC_RANGES):
            arabic += 1
        elif _in_ranges(ch, _HAN_RANGES):
            han += 1
        elif _in_ranges(ch, _KANA_RANGES):
            kana += 1
    # Japanese mixes Han with kana; it rendered well with the default font,
    # and a Chinese font would draw its Han in Chinese glyph shapes.
    if kana:
        return ""
    if arabic and arabic >= han:
        return "arabic"
    if han:
        return "han"
    return ""


def subtitle_font_for(text: str, *, platform: str | None = None) -> str:
    """The font name to force for *text*, or ``""`` to keep libass's choice."""
    if (platform or os.name) != "nt":
        return ""
    return _WINDOWS_SCRIPT_FONTS.get(_dominant_script(text), "")


class BurnCancelled(RuntimeError):
    """The caller cancelled the burn; ffmpeg was stopped and nothing written."""


# A 1080p re-encode measured 2.2x real time on an 8-thread PC; slower CPUs
# need more, so the limit grows with the video and never drops below 1 h.
_MIN_TIMEOUT_S = 3600.0
_TIMEOUT_PER_MEDIA_SECOND = 3.0


def burn_timeout(duration_s: float) -> float:
    """The ffmpeg time limit for a video of *duration_s* seconds."""
    return max(_MIN_TIMEOUT_S, _TIMEOUT_PER_MEDIA_SECOND * max(0.0, duration_s))


class MediaInfo(NamedTuple):
    """What ffprobe reported: ``has_video`` is None when the probe failed."""

    duration: float
    has_video: bool | None
    audio_codec: str


def probe_media(path: str, timeout: float = 60.0) -> MediaInfo:
    """Duration, video presence and first audio codec of *path* (one ffprobe).

    A probe that takes longer than *timeout* seconds counts as failed
    (``has_video`` None), like any other probe error."""
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "timeout": timeout,
    }
    kwargs.update(new_session_kwargs())
    try:
        r = subprocess.run(
            [bundled_binary("ffprobe"), "-v", "error",
             "-show_entries", "format=duration:stream=codec_type,codec_name",
             "-of", "json", path],
            **kwargs,
        )
        if r.returncode != 0:
            raise ValueError(f"ffprobe exit {r.returncode}")
        data = json.loads((r.stdout or b"").decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        logger.warning("Subtitle burn: could not probe %s (%s)", path, e)
        return MediaInfo(0.0, None, "")
    streams = data.get("streams") or []
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    audio = next(
        (str(st.get("codec_name") or "") for st in streams if st.get("codec_type") == "audio"),
        "",
    )
    return MediaInfo(
        duration if duration > 0 else 0.0,
        any(st.get("codec_type") == "video" for st in streams),
        audio,
    )


def probe_duration(path: str) -> float:
    """The media duration in seconds from ffprobe, or 0.0 when unknown."""
    return probe_media(path).duration


def free_output_path(path: str) -> str:
    """*path* when nothing is there, else the first free ``name (N).ext``.

    An earlier result of the same video is never replaced silently.
    """
    if not os.path.lexists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.lexists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


# Placeholders this run of the app reserved and has not yet released or
# replaced. The set is filled BEFORE the file exists, so the watched folder's
# create event (and a download's file recovery) can always tell the app's own
# placeholder from a file the user put there, whatever its name or size.
_reserved: set[str] = set()
_reserved_lock = threading.Lock()


def is_reserved(path: str) -> bool:
    """True while *path* is a placeholder this run reserved for a burn."""
    with _reserved_lock:
        return _output_key(path) in _reserved


def reserve_output_path(path: str) -> str:
    """Like ``free_output_path`` but creates the file empty (exclusive create),
    so two jobs started at once never pick the same name. ``burn()`` then
    replaces this placeholder; ``release_reserved_path`` removes it when no
    video was made. The name is listed in ``is_reserved`` until then."""
    stem, ext = os.path.splitext(path)
    candidate, n = path, 2
    while True:
        key = _output_key(candidate)
        with _reserved_lock:
            held_by_another_job = key in _reserved
            _reserved.add(key)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            if not held_by_another_job:
                with _reserved_lock:
                    _reserved.discard(key)
            candidate = f"{stem} ({n}){ext}"
            n += 1
            continue
        except BaseException:
            if not held_by_another_job:
                with _reserved_lock:
                    _reserved.discard(key)
            raise
        os.close(fd)
        return candidate


def release_reserved_path(path: str) -> None:
    """Remove a placeholder from ``reserve_output_path`` if it is still empty,
    and stop listing it as reserved."""
    with _reserved_lock:
        _reserved.discard(_output_key(path))
    try:
        if os.path.isfile(path) and os.path.getsize(path) == 0:
            os.unlink(path)
    except OSError:
        logger.warning("Could not remove the empty placeholder %s", path)


# -- burns that are running: stop and clean up when the app closes ----------------
#
# A burn writes a hidden ".burn-*" partial next to its output, a "burnsubs_*"
# work folder in the system temp and, for a chained download, an empty
# "<title>-subbed.mp4" placeholder. The thread that cleans them up is a daemon
# thread, so closing the app (or a crash) used to leave all three behind and
# let ffmpeg run on. Every running burn is listed here so the app's exit can
# stop it and remove exactly these files, and each one is also written to a
# small journal file so the next start can remove what a crash left.

_BURN_TEMP_PREFIX = ".burn-"
_BURN_DIR_PREFIX = "burnsubs_"
_BURN_TEMP_NAME_RE = re.compile(r"^\.burn-[a-z0-9_]{8}(\.[A-Za-z0-9]{1,8})?$")
_BURN_TEMP_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")
_BURN_TEMP_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"
# The only file a burn puts into its work folder.
_WORK_FOLDER_FILES = frozenset({"subs.srt"})
# The stem of a chained download's result or placeholder: "<title>-subbed" or
# "<title>-subbed (2)" (app/services/subbed_video.py).
SUBBED_STEM_RE = re.compile(r"-subbed(?: \(\d+\))?$")
_PLACEHOLDER_EXTS = (".mp4", ".m4v", ".mov", ".mkv", ".webm")


class _ActiveBurn:
    """The files and process of one running ``burn()``."""

    def __init__(self, tmp_dir: str, placeholder: str) -> None:
        self.tmp_dir = tmp_dir
        self.tmp_out = ""
        self.placeholder = placeholder
        self.proc: Any = None
        self.abandoned = threading.Event()
        self.journal = ""


_active: list[_ActiveBurn] = []
_active_lock = threading.Lock()
# Set when the app closes: from then on no burn starts ffmpeg.
_closing = threading.Event()
# Outputs this run of the app wrote (see is_own_output).
_produced: set[str] = set()


def _output_key(path: str) -> str:
    """One key per file, whatever the case rules and Unicode form of its name
    (macOS HFS+ stores names decomposed: a Persian "U+0622" may come back as
    U+0627 U+0653 where the app wrote U+0622)."""
    return unicodedata.normalize("NFC", os.path.normcase(os.path.realpath(path)))


def is_burn_temp(path: str) -> bool:
    """True for the hidden temp file a running burn encodes into."""
    return os.path.basename(path).startswith(_BURN_TEMP_PREFIX)


def is_own_output(path: str) -> bool:
    """True when a burn of this run of the app wrote *path*."""
    return _output_key(path) in _produced


def _create_burn_temp(folder: str, ext: str) -> str:
    """Create the hidden ``.burn-<8 chars><ext>`` file the encode goes into.

    Created with the normal new-file permissions (the umask applies);
    ``tempfile.mkstemp`` would make it 0600 and the finished video would
    keep that mode, unlike every other output of the app.

    *ext* is kept only when it is a plain ``.abc`` extension (the shape the
    cleanup recognises); ffmpeg could not pick a muxer from any other anyway.
    """
    if not _BURN_TEMP_EXT_RE.match(ext):
        ext = ""
    while True:
        name = _BURN_TEMP_PREFIX + "".join(secrets.choice(_BURN_TEMP_CHARS) for _ in range(8)) + ext
        path = os.path.join(folder, name)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return path


def _journal_dir() -> str:
    from .config import user_data_dir

    return os.path.join(str(user_data_dir()), "burn-journal")


def _own_start_time() -> float:
    try:
        import psutil  # type: ignore[import-not-found]

        return float(psutil.Process().create_time())
    except Exception:  # noqa: BLE001 - psutil missing or refused: no start time
        return 0.0


def _journal_write(entry: _ActiveBurn) -> None:
    """Record the burn's files; best effort (a burn never fails over this)."""
    try:
        if not entry.journal:
            folder = _journal_dir()
            os.makedirs(folder, exist_ok=True)
            entry.journal = os.path.join(folder, f"{os.getpid()}-{uuid.uuid4().hex}.json")
        record = {
            "pid": os.getpid(), "pid_started": _own_start_time(),
            "tmp_dir": entry.tmp_dir, "tmp_out": entry.tmp_out,
            "placeholder": entry.placeholder,
        }
        part = entry.journal + ".tmp"
        with open(part, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.replace(part, entry.journal)
    except Exception:  # noqa: BLE001 - logged; the burn itself must go on
        logger.warning("Could not write the burn journal", exc_info=True)


def _journal_remove(entry: _ActiveBurn) -> None:
    if not entry.journal:
        return
    try:
        os.unlink(entry.journal)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove the burn journal %s", entry.journal)
    entry.journal = ""


def _entry_clean(entry: _ActiveBurn) -> bool:
    """True when the burn's partial file and work folder are gone."""
    return not (
        (entry.tmp_out and os.path.lexists(entry.tmp_out))
        or (entry.tmp_dir and os.path.lexists(entry.tmp_dir))
    )


def _journal_remove_if_clean(entry: _ActiveBurn) -> None:
    """Drop the journal only when nothing it names is left to sweep later."""
    if _entry_clean(entry):
        _journal_remove(entry)


def _retry_for(patience: float, attempt: Callable[[], bool]) -> None:
    """Call *attempt* until it returns True or *patience* seconds pass (a just
    killed ffmpeg on Windows still holds its output file for a moment)."""
    deadline = time.monotonic() + patience
    while not attempt() and time.monotonic() < deadline:
        time.sleep(0.1)


def _is_link(path: str) -> bool:
    """A symlink, or a Windows junction (rmtree/unlink would act on its target's name)."""
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda p: False)(path))


def _same_folder(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_burn_partial(path: str) -> bool:
    """A file this module's ``_create_burn_temp`` could have made, nothing else."""
    return (
        bool(path) and os.path.isabs(path) and bool(_BURN_TEMP_NAME_RE.match(os.path.basename(path)))
        and not _is_link(path) and os.path.isfile(path)
    )


def _is_burn_work_folder(path: str, *, strict_content: bool) -> bool:
    """A ``burnsubs_*`` folder directly in the system temp folder; with
    *strict_content* it must also hold nothing but the burn's own SRT copy."""
    if not path or not os.path.isabs(path):
        return False
    if not os.path.basename(path).startswith(_BURN_DIR_PREFIX):
        return False
    if _is_link(path) or not os.path.isdir(path):
        return False
    if not _same_folder(os.path.dirname(path), tempfile.gettempdir()):
        return False
    if strict_content:
        try:
            return set(os.listdir(path)) <= _WORK_FOLDER_FILES
        except OSError:
            return False
    return True


def _is_empty_reserved_name(path: str) -> bool:
    """An empty ``<title>-subbed[ (N)].<video ext>`` file: what a chain reserves."""
    if not path or not os.path.isabs(path) or _is_link(path) or not os.path.isfile(path):
        return False
    stem, ext = os.path.splitext(os.path.basename(path))
    if ext.lower() not in _PLACEHOLDER_EXTS or not SUBBED_STEM_RE.search(stem):
        return False
    try:
        return os.path.getsize(path) == 0
    except OSError:
        return False


def _remove_leftovers(
    tmp_dir: str, tmp_out: str, placeholder: str, *,
    patience: float = 0.0, strict_content: bool = True,
) -> list[str]:
    """Remove a burn's own temp file, work folder and empty placeholder.

    Every path is vetted first (see the ``_is_*`` helpers: the exact name
    shape this module creates, an absolute path, not a link, the work folder
    directly inside the system temp folder, the placeholder still empty), so
    a path that is not provably this module's is never touched, whatever a
    journal file claims. Returns what was removed.
    """
    removed: list[str] = []
    if _is_burn_partial(tmp_out):
        def _unlink() -> bool:
            try:
                os.unlink(tmp_out)
            except FileNotFoundError:
                return True
            except OSError:
                return False
            return True

        _retry_for(patience, _unlink)
        if not os.path.exists(tmp_out):
            removed.append(tmp_out)
        else:
            logger.warning("Could not remove the burn partial %s", tmp_out)
    if _is_burn_work_folder(tmp_dir, strict_content=strict_content):
        def _rmtree() -> bool:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return not os.path.exists(tmp_dir)

        _retry_for(patience, _rmtree)
        if not os.path.exists(tmp_dir):
            removed.append(tmp_dir)
    if _is_empty_reserved_name(placeholder):
        release_reserved_path(placeholder)
        if not os.path.exists(placeholder):
            removed.append(placeholder)
    return removed


def _vetted_leftovers(
    tmp_dir: str, tmp_out: str, placeholder: str, *, strict_content: bool = True
) -> list[str]:
    """The paths ``_remove_leftovers`` would remove that still exist."""
    found: list[str] = []
    if _is_burn_partial(tmp_out):
        found.append(tmp_out)
    if _is_burn_work_folder(tmp_dir, strict_content=strict_content):
        found.append(tmp_dir)
    if _is_empty_reserved_name(placeholder):
        found.append(placeholder)
    return found


def abandon_active_burns(patience: float = 5.0) -> int:
    """Stop every running burn and remove its leftovers (the app is closing).

    No burn starts ffmpeg after this call. Every ffmpeg tree is killed first,
    then all are awaited together (one shared *patience*), and only the files
    each burn created are removed (see ``_remove_leftovers``); a finished
    output is never touched. A burn's journal stays while anything it names
    still exists, or while its ffmpeg had not started yet (that burn's own
    thread then stops and cleans up; if the process ends first, the next
    start sweeps it). Returns how many burns were stopped.
    """
    _closing.set()
    with _active_lock:
        entries = list(_active)
    for entry in entries:
        entry.abandoned.set()
        if entry.proc is not None:
            kill_process_tree(entry.proc, force=True)
    deadline = time.monotonic() + patience
    for entry in entries:
        proc = entry.proc  # read after abandoned was set: a late start kills itself
        if proc is not None:
            kill_process_tree(proc, force=True)
            try:
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except Exception:  # noqa: BLE001 - already gone, or stuck: clean up anyway
                pass
        _remove_leftovers(
            entry.tmp_dir, entry.tmp_out, entry.placeholder,
            patience=max(0.5, deadline - time.monotonic()), strict_content=False,
        )
        if proc is not None:
            _journal_remove_if_clean(entry)
    return len(entries)


def _record_owner_running(record: dict[str, Any]) -> bool:
    """True when the process that wrote a journal record may still be running.

    Unknown counts as running: a record is only acted on when its writer is
    provably gone (no such process, or a different one reusing the pid).
    """
    try:
        pid = int(record.get("pid") or 0)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if pid == os.getpid():
        return False  # a record of an earlier run that had this pid
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return True
    try:
        proc = psutil.Process(pid)
        started = float(record.get("pid_started") or 0.0)
        return started <= 0 or abs(proc.create_time() - started) < 2.0
    except psutil.NoSuchProcess:
        return False
    except Exception:  # noqa: BLE001 - cannot tell: keep the files
        return True


def sweep_stale_burns() -> list[str]:
    """At start: remove what a crashed or killed run left of its burns.

    Works only from the journal the burns wrote, and trusts nothing in it:
    ``_remove_leftovers`` re-checks every path (name shape, location, link,
    contents, emptiness) before touching it, and a record is acted on only
    when its writer is provably gone. Returns what was removed.
    """
    try:
        folder = _journal_dir()
        names = sorted(os.listdir(folder))
    except (OSError, ImportError):
        return []
    with _active_lock:
        mine = {e.journal for e in _active}
    removed: list[str] = []
    for name in names:
        path = os.path.join(folder, name)
        if not name.endswith(".json") or path in mine:
            continue
        record: dict[str, Any] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("not a record")
            record = loaded
        except (OSError, ValueError):
            logger.warning("Dropping the unreadable burn journal %s", path)
        else:
            if _record_owner_running(record):
                continue

        def _text(key: str) -> str:
            value = record.get(key)
            return value if isinstance(value, str) else ""

        paths = (_text("tmp_dir"), _text("tmp_out"), _text("placeholder"))
        removed += _remove_leftovers(*paths)
        if _vetted_leftovers(*paths):
            # Held open, or no permission: the record stays so the next start retries.
            logger.warning("Burn leftovers of %s could not all be removed; keeping the journal", path)
            continue
        try:
            os.unlink(path)
        except OSError:
            logger.warning("Could not remove the burn journal %s", path)
    if removed:
        logger.info("Removed %d leftover file(s) of an interrupted subtitle burn.", len(removed))
    return removed


def parse_progress_seconds(line: str) -> float | None:
    """Seconds encoded so far from one ffmpeg ``-progress`` line, else None.

    ``out_time_us`` and (despite its name) ``out_time_ms`` both count
    MICROseconds; ``N/A`` appears before the first frame.
    """
    key, sep, value = line.strip().partition("=")
    if not sep or key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(0, int(value)) / 1_000_000
    except ValueError:
        return None


def _run_ffmpeg(
    cmd: list[str],
    *,
    timeout: float,
    duration_s: float = 0.0,
    progress_cb: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[Any], None] | None = None,
    **popen_kwargs: Any,
) -> None:
    """Run ffmpeg like ``subprocess.run(check=True)``, with progress and cancel.

    stdout carries the ``-progress`` lines; stderr is drained on its own
    thread (an unread pipe stalls a long encode) and its tail goes into the
    ``CalledProcessError`` on failure. A cancel or the time limit tree-kills
    ffmpeg; a cancel raises ``BurnCancelled``.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, **popen_kwargs,
    )
    if on_process is not None:
        on_process(proc)
    stderr_tail = bytearray()

    err_stream = proc.stderr
    out_stream = proc.stdout
    assert err_stream is not None and out_stream is not None

    def _drain_stderr() -> None:
        while True:
            chunk = err_stream.read(4096)
            if not chunk:
                return
            stderr_tail.extend(chunk)
            del stderr_tail[:-8192]

    def _read_progress() -> None:
        last = -1.0
        for raw in out_stream:
            line = raw.decode("ascii", "replace")
            if progress_cb is None:
                continue
            # "progress=end" also ends a FAILED run, so 100 is only reported
            # after a zero exit (below).
            secs = parse_progress_seconds(line)
            if secs is None or duration_s <= 0:
                continue
            pct = min(99.0, 100.0 * secs / duration_s)
            if pct > last:
                last = pct
                progress_cb(pct)

    readers = [
        threading.Thread(target=_drain_stderr, name="burn-stderr", daemon=True),
        threading.Thread(target=_read_progress, name="burn-progress", daemon=True),
    ]
    for t in readers:
        t.start()
    deadline = time.monotonic() + timeout
    cancelled = timed_out = False
    while proc.poll() is None:
        if cancel_check is not None and cancel_check():
            cancelled = True
        elif time.monotonic() >= deadline:
            timed_out = True
        if cancelled or timed_out:
            kill_process_tree(proc, force=True)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            break
        time.sleep(0.1)
    for t in readers:
        t.join(timeout=10)
    # An outside kill (the queue's own Cancel) ends ffmpeg before this loop
    # sees the flag, so ask once more.
    if cancelled or (cancel_check is not None and cancel_check()):
        raise BurnCancelled("Subtitle burn cancelled")
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, b"", bytes(stderr_tail)
        )
    if progress_cb is not None:
        progress_cb(100.0)


def _same_path(a: str, b: str) -> bool:
    """True when *a* and *b* name the same file (works when *b* is not there yet)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


_WJ = chr(0x2060)  # WORD JOINER: invisible, breaks a libass "\N"-style code
_BACKSLASH = chr(92)
_SRT_TIMING_ARROW = "-->"


def escape_cue_text(line: str) -> str:
    """Make one SRT cue line render as written, not as libass/ffmpeg markup.

    ffmpeg turns SRT into ASS, so ``{...}`` is an override block (``{\\an8}``
    moved a cue to the top, ``{x}`` vanished), ``\\N`` / ``\\n`` / ``\\h``
    are a line break or a space, and ``<i>``/``<b>``/``<font>`` are HTML-like
    tags. Braces get a backslash escape; a backslash and a ``<`` before a
    letter or ``/`` get an invisible WORD JOINER after them. Undo: drop
    ``\\`` before ``{``/``}`` first, then every U+2060.
    """
    out: list[str] = []
    for i, ch in enumerate(line):
        if ch in "{}":
            out.append(_BACKSLASH + ch)
        elif ch == _BACKSLASH:
            out.append(ch + _WJ)
        elif ch == "<" and (line[i + 1:i + 2].isalpha() or line[i + 1:i + 2] == "/"):
            out.append(ch + _WJ)
        else:
            out.append(ch)
    return "".join(out)


def escape_srt_markup(text: str) -> str:
    """``escape_cue_text`` on every cue line; index and timing lines unchanged."""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if _SRT_TIMING_ARROW in line or line.strip().isdigit():
            continue
        lines[n] = escape_cue_text(line)
    return "\n".join(lines)


def _prepare_srt(srt_path: str, safe_srt_file: str) -> str:
    """Copy the SRT for ffmpeg with markup escaped and RTL lines wrapped;
    return its forced font.

    A file that is not UTF-8 is copied byte for byte (ffmpeg reads it as
    before) with no wrap and no forced font.
    """
    try:
        with open(srt_path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except UnicodeDecodeError:
        logger.warning(
            "Subtitle burn: %s is not UTF-8; burning it without the RTL/font fix",
            srt_path,
        )
        shutil.copyfile(srt_path, safe_srt_file)
        return ""
    with open(safe_srt_file, "w", encoding="utf-8", newline="") as f:
        f.write(wrap_rtl_lines(escape_srt_markup(text)))
    return subtitle_font_for(text)


def burn(
    video_path: str,
    srt_path: str,
    out_path: str,
    *,
    extra_args: list[str] | None = None,
    timeout: float | None = None,
    progress_cb: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[Any], None] | None = None,
    placeholder: str = "",
) -> None:
    """Write ``out_path`` with the SRT subtitles burned into the video.

    ``timeout`` defaults to ``burn_timeout`` of the probed duration.
    ``progress_cb(percent)`` runs on a reader thread, rising to 100.
    ``cancel_check()`` is polled about ten times a second; True stops
    ffmpeg. ``on_process(popen)`` receives each ffmpeg process as it starts.
    ``placeholder`` names an empty file the caller reserved for the output
    (``reserve_output_path``): if the app is closed during the burn, it is
    removed with the burn's other leftovers. While it runs the burn is listed
    for ``abandon_active_burns``, after which it stops and starts no ffmpeg.

    Raises:
        FileNotFoundError if the video or srt is missing.
        ValueError        if ``out_path`` is the video or the srt itself.
        BurnCancelled     if ``cancel_check`` asked to stop.
        RuntimeError      if ffmpeg returns non-zero or runs out of time.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if not os.path.isfile(srt_path):
        raise FileNotFoundError(f"srt not found: {srt_path}")
    # The final os.replace would put the encode over the source (the
    # original video was lost this way when the Save dialog's name was
    # changed to the source's own name).
    for src in (video_path, srt_path):
        if _same_path(src, out_path):
            raise ValueError(
                f"The output file must differ from the source: {out_path}"
            )
    if _closing.is_set():
        raise BurnCancelled("The app is closing")
    video_path = os.path.abspath(video_path)
    info = probe_media(video_path)
    if info.has_video is False:
        raise ValueError(
            "This file has no video picture to burn the subtitles into: "
            f"{video_path}"
        )
    duration_s = info.duration
    if timeout is None:
        timeout = burn_timeout(duration_s)

    ffmpeg = bundled_binary("ffmpeg")
    # ffmpeg's `subtitles=` value is parsed as a libavfilter *filter graph*,
    # where ' , ; [ ] : \ are metacharacters. The SRT path is derived from
    # the media filename, and for a downloaded video that name comes
    # straight from the (attacker-influenced) yt-dlp title — which keeps
    # ' [ ] , by default. Interpolating such a name into the graph string
    # both breaks burning for legitimately-punctuated titles AND is a
    # filter-injection vector. Rather than juggle ffmpeg's brittle
    # multi-level escaping, copy the SRT into a temp dir as "subs.srt" and
    # run ffmpeg IN that dir, so the graph only ever holds the bare
    # relative name (the temp dir's own path can hold a drive colon, an
    # apostrophe or brackets of the user name).
    tmp_dir = tempfile.mkdtemp(prefix=_BURN_DIR_PREFIX)
    entry = _ActiveBurn(tmp_dir, placeholder)
    with _active_lock:
        _active.append(entry)
    safe_srt_file = os.path.join(tmp_dir, "subs.srt")
    # Encode into a temp sibling of out_path instead of writing the final
    # path directly: ffmpeg `-y` truncates its output the moment it starts,
    # so a mid-way failure (bad source, disk full, the 1 h timeout) used to
    # leave a corrupt partial file under the user's chosen name — and could
    # destroy an existing file the user picked by mistake. The temp lives
    # in the same directory (same filesystem) so os.replace below is atomic.
    out_dir = os.path.dirname(os.path.abspath(out_path))
    tmp_out = ""
    try:
        font = _prepare_srt(srt_path, safe_srt_file)
        if entry.abandoned.is_set() or _closing.is_set():
            raise BurnCancelled("Subtitle burn cancelled")
        subtitle_filter = "subtitles=subs.srt"
        if font:
            subtitle_filter += f":force_style='FontName={font}'"
        tmp_out = _create_burn_temp(out_dir, os.path.splitext(out_path)[1])
        entry.tmp_out = tmp_out
        _journal_write(entry)

        def _closing_now() -> bool:
            return entry.abandoned.is_set() or _closing.is_set()

        def _on_process(proc: Any) -> None:
            entry.proc = proc
            # abandon_active_burns sets the flag, then reads entry.proc: one
            # of the two sides always sees the other, so an ffmpeg that starts
            # while the app closes is killed here and never runs on.
            if _closing_now():
                kill_process_tree(proc, force=True)
            if on_process is not None:
                on_process(proc)

        def _stop_requested() -> bool:
            return _closing_now() or bool(cancel_check is not None and cancel_check())
        is_mp4 = os.path.splitext(out_path)[1].lower() in (".mp4", ".m4v", ".mov")

        def _cmd(audio_codec: str) -> list[str]:
            # -c:a first so caller-supplied extra_args keep their original
            # ability to override it (ffmpeg lets later options win).
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-vf", subtitle_filter,
                "-c:a", audio_codec,
                # 8-bit 4:2:0 H.264 plays everywhere (a 10-bit or 4:4:4
                # source otherwise gives a profile phones and TVs refuse).
                "-pix_fmt", "yuv420p",
                "-progress", "pipe:1",
                "-nostats",
            ]
            if is_mp4:
                cmd += ["-movflags", "+faststart"]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(tmp_out)
            return cmd

        best = [-1.0]

        def _rising(pct: float) -> None:
            # The AAC retry is a second ffmpeg run starting at 0 again.
            if progress_cb is not None and pct > best[0]:
                best[0] = pct
                progress_cb(pct)

        kwargs: dict[str, Any] = {
            "cwd": tmp_dir,
            "duration_s": duration_s,
            "progress_cb": _rising if progress_cb is not None else None,
            "cancel_check": _stop_requested,
            "on_process": _on_process,
        }
        # CREATE_NO_WINDOW on Windows; start_new_session=True on POSIX so
        # kill_process_tree can killpg this ffmpeg's OWN group if needed.
        kwargs.update(new_session_kwargs())

        # Try the audio stream-copy first (lossless + fast); if the output
        # container rejects the source codec, retry ONCE with AAC. Skipped
        # when the caller set its own audio codec, which we must not override.
        codecs = ["copy"]
        if not _extra_args_set_audio_codec(extra_args):
            if is_mp4 and info.audio_codec and info.audio_codec not in _MP4_PLAYABLE_AUDIO:
                # ffmpeg accepts Opus/Vorbis/FLAC/PCM in MP4, but most
                # players do not play them there.
                codecs = ["aac"]
            else:
                codecs.append("aac")
        for codec in codecs:
            if _stop_requested():
                raise BurnCancelled("Subtitle burn cancelled")
            try:
                _run_ffmpeg(_cmd(codec), timeout=timeout, **kwargs)
                break
            except subprocess.CalledProcessError as e:
                msg = _stderr_tail(e)
                if codec == codecs[-1] or not _container_rejected_audio(msg):
                    raise RuntimeError(
                        f"ffmpeg failed to burn subtitles: {msg}"
                    ) from e
                logger.warning(
                    "Subtitle burn: output container rejected the copied "
                    "audio (%s); retrying with AAC",
                    msg.splitlines()[-1] if msg else "unknown ffmpeg error",
                )
                continue
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"ffmpeg timed out burning subtitles after {timeout}s"
                ) from e
            except OSError:
                # The app closing removed the work folder ffmpeg was about to start in.
                if _closing_now():
                    raise BurnCancelled("Subtitle burn cancelled")
                raise
        # (Only the app closing stops here: a Cancel that lands after the
        # encode finished keeps the finished file, as the chain row expects.)
        if _closing_now():
            raise BurnCancelled("Subtitle burn cancelled")
        # Known as the app's own output BEFORE it appears: the watched
        # folder's event for this rename must not outrun the record.
        key = _output_key(out_path)
        _produced.add(key)
        try:
            os.replace(tmp_out, out_path)
        except BaseException:
            _produced.discard(key)
            raise
        with _reserved_lock:
            _reserved.discard(key)  # the placeholder now holds the video
    finally:
        with _active_lock:
            if entry in _active:
                _active.remove(entry)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_out:
            try:
                os.unlink(tmp_out)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Could not remove the burn partial %s", tmp_out)
        # A partial that could not be removed stays in the journal for the next start.
        _journal_remove_if_clean(entry)
