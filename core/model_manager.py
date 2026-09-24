from __future__ import annotations

import errno
import hashlib
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

import requests


class DownloadCancelled(RuntimeError):
    pass


class ModelDestinationNotWritable(RuntimeError):
    """The model destination directory cannot be created or written.

    Raised when creating / extracting into the model folder fails with
    a permission error (Windows ``WinError 5`` "Access is denied" /
    POSIX ``EACCES``). The most common cause is an ``<app_dir>/hub``
    location under Program Files for a standard (non-admin) user. The
    UI catches this to offer a writable folder instead of showing the
    raw OS error string.

    ``directory`` carries the offending path for the UI message.
    """

    def __init__(self, directory: str | Path, message: str | None = None) -> None:
        self.directory = str(directory)
        super().__init__(
            message
            or f"Cannot write to the model folder: {self.directory}"
        )


# OSError.errno values that mean "you don't have permission here".
# EACCES is the POSIX form; on Windows, "Access is denied" (WinError 5)
# surfaces as a PermissionError whose .errno is EACCES, and rarer cases
# raise EPERM. We treat both as the not-writable signal.
_PERMISSION_ERRNOS = {errno.EACCES, errno.EPERM}


def _is_permission_error(exc: OSError) -> bool:
    """True when ``exc`` indicates a lack of write permission."""
    if isinstance(exc, PermissionError):
        return True
    return exc.errno in _PERMISSION_ERRNOS


# Bound the download/verify retry loop. A permanently-bad mirror or a
# captive-portal MD5 body would otherwise re-download the whole ~3 GB
# archive forever (the only escape was the modal Cancel button — useless
# on an unattended / auto-transcribe run). After this many failed
# attempts we raise so the UI reports a real, terminal error.
MAX_DOWNLOAD_ATTEMPTS = 3

# A valid md5sum line begins with a 32-hex-char digest. Rejecting
# anything else stops an HTML error page (captive portal / proxy) from
# being mis-parsed as a manifest and driving an endless re-download.
_MD5_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------- model picker
#
# v0.8 — pick one of several pre-bundled faster-whisper variants from
# the Advanced dialog. Each entry resolves to the ``model`` sub-dict
# (name + url + md5) the rest of this module already consumes.
#
# Mirror URLs follow the existing smch.ir convention so adding a new
# entry is a one-line change. ``approx_size_gb`` is shown in the
# Advanced dropdown so the user knows the install cost up front.

# This is the BUILT-IN default catalog. It is the lowest-priority source —
# the online config (see core.config) may ADD or OVERRIDE entries under its
# ``model_catalog`` key, so new models can ship without an app update. Use
# ``catalog_models(config)`` / ``catalog_resolve_entry(config, slug)`` to read
# the merged effective catalog; the bare ``MODEL_REGISTRY`` / ``list_models``
# / ``resolve_model_entry`` helpers keep returning the built-ins only (still
# used as the offline fallback and by existing tests).
#
# Every entry carries an explicit ``"hf_repo"`` — the exact HuggingFace
# ``Org/Repo`` id this model downloads from when the smch.ir mirror is
# unavailable (or, for entries with no mirror at all, ALWAYS). This makes
# the HuggingFace fallback deterministic: ``_hf_model_ref`` prefers
# ``hf_repo`` over the name-based guesses (``_short_model_id`` /
# ``_repo_id_from_url``), which can resolve to the wrong upstream org for
# models that share a faster-whisper "short id" with a different repo
# (e.g. ``deepdml-large-v3-turbo`` vs. the mobiuslabsgmbh turbo, both of
# which faster-whisper's own map would resolve to the SAME
# ``large-v3-turbo`` short id).
#
# Only the four original entries (large-v3, large-v3-turbo,
# distil-large-v3.5, medium) have a real smch.ir mirror ``url``/``md5``.
# Every other entry has ``url=""``/``md5=""``: ``ensure_model`` skips the
# mirror attempt entirely for those and downloads straight from
# ``hf_repo`` via ``_download_via_huggingface``.
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "tiny.en": {
        "label": "Tiny (English) — fastest, lowest accuracy (~0.075 GB)",
        "name": "faster-whisper-tiny.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-tiny.en",
        "approx_size_gb": 0.075,
        "info": (
            "~75 MB, English-only. The fastest and least accurate model — "
            "useful for quick drafts or very low-power hardware."
        ),
    },
    "tiny": {
        "label": "Tiny — fastest, lowest accuracy, multilingual (~0.075 GB)",
        "name": "faster-whisper-tiny",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-tiny",
        "approx_size_gb": 0.075,
        "info": (
            "~75 MB, multilingual. The fastest and least accurate model — "
            "useful for quick drafts or very low-power hardware."
        ),
    },
    "base.en": {
        "label": "Base (English) — very fast, low accuracy (~0.145 GB)",
        "name": "faster-whisper-base.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-base.en",
        "approx_size_gb": 0.145,
        "info": (
            "~145 MB, English-only. Very fast with modest accuracy — a step "
            "up from Tiny for short, low-stakes clips."
        ),
    },
    "base": {
        "label": "Base — very fast, low accuracy, multilingual (~0.145 GB)",
        "name": "faster-whisper-base",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-base",
        "approx_size_gb": 0.145,
        "info": (
            "~145 MB, multilingual. Very fast with modest accuracy — a step "
            "up from Tiny for short, low-stakes clips."
        ),
    },
    "small.en": {
        "label": "Small (English) — fast, moderate accuracy (~0.5 GB)",
        "name": "faster-whisper-small.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-small.en",
        "approx_size_gb": 0.5,
        "info": (
            "~500 MB, English-only. Good speed/accuracy balance for everyday "
            "English transcripts on modest hardware."
        ),
    },
    "small": {
        "label": "Small — fast, moderate accuracy, multilingual (~0.5 GB)",
        "name": "faster-whisper-small",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-small",
        "approx_size_gb": 0.5,
        "info": (
            "~500 MB, multilingual. Good speed/accuracy balance for everyday "
            "transcripts on modest hardware."
        ),
    },
    "medium.en": {
        "label": "Medium (English) — slower, good accuracy (~1.5 GB)",
        "name": "faster-whisper-medium.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-medium.en",
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Noticeably more accurate than Small at "
            "roughly half the speed."
        ),
    },
    # NOTE: this artifact may not exist on smch.ir yet — the URL/MD5
    # below follow the same naming convention as the entries below
    # (Systran's faster-whisper-large-v3). If the mirror 404s (or any
    # other download/verification failure occurs), ``ensure_model``
    # automatically falls back to fetching the same model straight
    # from the HuggingFace Hub via ``hf_repo`` / ``_download_via_huggingface``,
    # so this entry works either way. ~1.5 GB.
    "medium": {
        "label": "Medium — slower, good accuracy, multilingual (~1.5 GB)",
        "name": "faster-whisper-medium",
        "url": "https://smch.ir/models/models--Systran--faster-whisper-medium.zip",
        "md5": "https://smch.ir/models/models--Systran--faster-whisper-medium.zip.md5",
        "hf_repo": "Systran/faster-whisper-medium",
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, multilingual. Noticeably more accurate than Small at "
            "roughly half the speed."
        ),
    },
    "large-v1": {
        "label": "Large v1 — older large model, multilingual (~3 GB)",
        "name": "faster-whisper-large-v1",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-large-v1",
        "approx_size_gb": 3.0,
        "info": (
            "~3 GB, multilingual. The original large model — kept for "
            "compatibility; Large v2/v3 are generally more accurate."
        ),
    },
    "large-v2": {
        "label": "Large v2 — high accuracy, multilingual (~3 GB)",
        "name": "faster-whisper-large-v2",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-whisper-large-v2",
        "approx_size_gb": 3.0,
        "info": (
            "~3 GB, multilingual. High accuracy, slower than the Turbo "
            "models — superseded by Large v3 for most languages."
        ),
    },
    "large-v3": {
        "label": "Large v3 — best accuracy (default, ~3 GB)",
        "name": "faster-whisper-large-v3",
        "url": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip",
        "md5": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip.md5",
        "hf_repo": "Systran/faster-whisper-large-v3",
        "approx_size_gb": 3.0,
        "info": (
            "~3 GB, multilingual. The most accurate general-purpose model — "
            "slowest of the large models. Default choice."
        ),
    },
    "distil-small.en": {
        "label": "Distil Small (English) — fast, English-only (~0.4 GB)",
        "name": "faster-distil-whisper-small.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-distil-whisper-small.en",
        "approx_size_gb": 0.4,
        "info": (
            "~400 MB, English-only. Distilled for speed — faster than Small "
            "with similar English accuracy."
        ),
    },
    "distil-medium.en": {
        "label": "Distil Medium (English) — fast, English-only (~0.8 GB)",
        "name": "faster-distil-whisper-medium.en",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-distil-whisper-medium.en",
        "approx_size_gb": 0.8,
        "info": (
            "~800 MB, English-only. Distilled for speed — faster than "
            "Medium with similar English accuracy."
        ),
    },
    "distil-large-v2": {
        "label": "Distil Large v2 — fast, English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v2",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-distil-whisper-large-v2",
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Distilled from Large v2 for ~5x speed "
            "with close to its English accuracy."
        ),
    },
    "distil-large-v3": {
        "label": "Distil Large v3 — fast, English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v3",
        "url": "",
        "md5": "",
        "hf_repo": "Systran/faster-distil-whisper-large-v3",
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Distilled from Large v3 for ~5x speed "
            "with close to its English accuracy."
        ),
    },
    "distil-large-v3.5": {
        "label": "Distil Large v3.5 — fastest English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v3.5",
        "url": "https://smch.ir/models/models--Systran--faster-distil-whisper-large-v3.5.zip",
        "md5": "https://smch.ir/models/models--Systran--faster-distil-whisper-large-v3.5.zip.md5",
        "hf_repo": "distil-whisper/distil-large-v3.5-ct2",
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. The newest distilled large model — "
            "fastest English-only option with accuracy close to Large v3."
        ),
    },
    "large-v3-turbo": {
        "label": "Large v3 Turbo — ~5x faster, similar accuracy (~1.6 GB)",
        "name": "faster-whisper-large-v3-turbo",
        "url": "https://smch.ir/models/models--Systran--faster-whisper-large-v3-turbo.zip",
        "md5": "https://smch.ir/models/models--Systran--faster-whisper-large-v3-turbo.zip.md5",
        "hf_repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "approx_size_gb": 1.6,
        "info": (
            "~1.6 GB, multilingual. ~5x faster than Large v3 with similar "
            "accuracy — a strong general-purpose default."
        ),
    },
    "deepdml-large-v3-turbo": {
        "label": "Large v3 Turbo (deepdml) — ~5x faster, multilingual (~1.6 GB)",
        "name": "faster-whisper-large-v3-turbo-deepdml",
        "url": "",
        "md5": "",
        "hf_repo": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "approx_size_gb": 1.6,
        "info": (
            "~1.6 GB, multilingual. Community CT2 conversion of the Large "
            "v3 Turbo weights — ~5x faster than Large v3 with similar "
            "accuracy."
        ),
    },
}


DEFAULT_MODEL_SLUG = "large-v3"


def list_models() -> list[tuple[str, str]]:
    """Return ``[(slug, label), ...]`` for the UI dropdown (built-ins only)."""
    return [(slug, entry["label"]) for slug, entry in MODEL_REGISTRY.items()]


def resolve_model_entry(slug: str) -> dict[str, Any] | None:
    """Return ``{name, url, md5, hf_repo}`` for a built-in registry slug, or
    ``None``.

    The returned dict shape is a superset of ``DEFAULT_CONFIG["model"]`` (it
    adds ``hf_repo``) so the caller can assign it directly to
    ``config["model"]`` and the rest of the codebase (``ensure_model``, the
    cache-dir fallback) keeps working without changes — ``ensure_model``
    reads ``hf_repo`` to resolve the HuggingFace fallback deterministically.
    """
    entry = MODEL_REGISTRY.get(slug)
    if entry is None:
        return None
    return {
        "name": entry["name"],
        "url": entry["url"],
        "md5": entry["md5"],
        "hf_repo": entry.get("hf_repo", ""),
    }


def _merged_catalog(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Built-in MODEL_REGISTRY overlaid with ``config['model_catalog']``.

    The online/local config may carry a ``model_catalog`` dict in the SAME
    shape as MODEL_REGISTRY (slug → {label, name, url, md5, hf_repo,
    approx_size_gb, info}). Each online slug is overlaid onto the built-in
    entry (or added new), so the catalog can grow / be re-pointed without an
    app update. A malformed catalog (not a dict, or non-dict entries) is
    ignored entry-by-entry so a bad online payload never breaks the picker —
    the built-ins still show.

    ``url``/``md5`` may be empty strings — those entries (and any new ones
    added online) download straight from ``hf_repo`` via
    ``_download_via_huggingface``, skipping the mirror entirely (see
    ``ensure_model``). At least one of ``url`` or ``hf_repo`` must be a
    non-empty string, or ``ensure_model`` would have no source to fetch
    from.
    """
    merged: dict[str, dict[str, Any]] = {
        slug: dict(entry) for slug, entry in MODEL_REGISTRY.items()
    }
    extra = (config or {}).get("model_catalog")
    if not isinstance(extra, dict):
        return merged
    from core.hub import is_safe_model_folder_name

    for slug, entry in extra.items():
        if not isinstance(slug, str) or not isinstance(entry, dict):
            continue
        # ``name`` is always required AND must be a safe single folder
        # component: it becomes the model directory under the hub, so a
        # separator / ``..`` name from a compromised or MITM'd online
        # catalog must never be merged in (it would otherwise be handed
        # to ``hub.model_folder_for`` and resolve outside the hub).
        # ``url``/``md5`` must be strings (may be empty) and ``hf_repo``
        # (if present) must be a string.
        if not is_safe_model_folder_name(entry.get("name")):
            continue
        if not all(isinstance(entry.get(k, ""), str) for k in ("url", "md5", "hf_repo")):
            continue
        # Need a download source: a non-empty mirror url or hf_repo.
        if not (entry.get("url") or entry.get("hf_repo")):
            continue
        base = dict(merged.get(slug) or {})
        base.update(entry)
        base.setdefault("url", "")
        base.setdefault("md5", "")
        base.setdefault("hf_repo", "")
        base.setdefault("label", slug)
        base.setdefault("approx_size_gb", 0.0)
        base.setdefault("info", "")
        # Display fields also arrive from the (untrusted) online entry, so
        # coerce wrong types back to safe defaults: a truthy non-numeric
        # ``approx_size_gb`` (e.g. ``"huge"``) would otherwise crash the
        # Advanced dialog's info popup at ``f"{size_gb:g}"`` with
        # ``ValueError: Unknown format code 'g'``.
        if not isinstance(base.get("label"), str):
            base["label"] = slug
        if not isinstance(base.get("info"), str):
            base["info"] = ""
        _gb = base.get("approx_size_gb")
        if isinstance(_gb, bool) or not isinstance(_gb, (int, float)):
            base["approx_size_gb"] = 0.0
        merged[slug] = base
    return merged


def catalog_models(config: dict[str, Any] | None) -> list[tuple[str, str]]:
    """``[(slug, label), ...]`` from the MERGED catalog (built-ins + online).

    This is what the Advanced model picker should call so an online-added
    model appears without an app update.
    """
    return [(slug, entry.get("label") or slug)
            for slug, entry in _merged_catalog(config).items()]


def catalog_resolve_entry(
    config: dict[str, Any] | None, slug: str
) -> dict[str, Any] | None:
    """``{name, url, md5, hf_repo}`` for ``slug`` from the merged catalog, or
    ``None``.

    ``hf_repo`` is included so the caller can assign the result straight to
    ``config["model"]`` and ``ensure_model`` resolves the HuggingFace
    fallback deterministically from it.
    """
    entry = _merged_catalog(config).get(slug)
    if entry is None:
        return None
    return {
        "name": entry["name"],
        "url": entry["url"],
        "md5": entry["md5"],
        "hf_repo": entry.get("hf_repo", ""),
    }


def catalog_entry_info(config: dict[str, Any] | None, slug: str) -> dict[str, Any] | None:
    """``{label, info, approx_size_gb}`` for ``slug`` from the merged catalog.

    Used by the Advanced dialog's "?" button to show a short description of
    the selected model. Returns ``None`` when ``slug`` isn't in the merged
    catalog.
    """
    entry = _merged_catalog(config).get(slug)
    if entry is None:
        return None
    return {
        "label": entry.get("label") or slug,
        "info": entry.get("info") or "",
        "approx_size_gb": entry.get("approx_size_gb") or 0.0,
    }


def approx_download_size_text(config: dict[str, Any] | None, slug: str) -> str:
    """Human download size for ``slug``, e.g. "about 500 MB" / "about 1.5 GB".

    "" when the catalog has no size for it, so a caller can leave the size
    out instead of guessing -- the first-download prompt used to say "about
    3 GB" for every model, including the ~0.5 GB Small.
    """
    info = catalog_entry_info(config, slug)
    try:
        gb = float((info or {}).get("approx_size_gb") or 0.0)
    except (TypeError, ValueError):
        gb = 0.0
    if gb <= 0:
        return ""
    if gb < 1:
        return f"about {max(10, int(round(gb * 1000, -1)))} MB"
    return f"about {gb:g} GB"


def model_downloaded(config: dict[str, Any] | None, slug: str) -> bool:
    """True when ``slug``'s weights already exist on disk under the
    configured hub folder.

    Shared by the Advanced dialog's model picker and the Transcribe tab's
    quick model picker so "already downloaded" status can never drift
    between the two -- moved here (from a previously
    ``AdvancedDialog``-private method) specifically so a second UI surface
    could reuse it without duplicating the hub-folder lookup.
    """
    entry = catalog_resolve_entry(config, slug)
    if not entry:
        return False
    try:
        from core.hub import default_hub_folder, model_folder_for

        cfg = config or {}
        hub_folder = (cfg.get("hub_folder") or "").strip() or str(
            default_hub_folder()
        )
        return (model_folder_for(hub_folder, entry["name"]) / "model.bin").exists()
    except Exception:  # noqa: BLE001
        return False

def md5_file(path: str | Path, cancel_event: threading.Event | None = None) -> str:
    h=hashlib.md5()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Model download cancelled")
            h.update(chunk)
    return h.hexdigest()

def _remove_path(path: str | Path) -> None:
    path=Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

def _fmt_bytes(value: float | int | None) -> str:
    value=float(value or 0)
    for unit in ("B","KB","MB","GB","TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value/=1024
    return f"{value:.1f} TB"

def _fmt_time(seconds: float | int | None) -> str:
    if seconds is None:
        return "--:--"
    seconds=max(0,int(seconds))
    h=seconds//3600
    m=(seconds%3600)//60
    s=seconds%60
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

def _notify(progress_cb: Callable[[dict[str, Any]], None] | None, **payload: Any) -> None:
    if progress_cb:
        progress_cb(payload)

def _zip_name_from_url(zip_url: str) -> str:
    name=Path(unquote(urlparse(zip_url).path)).name
    return name or "model.zip"

def _parse_md5_manifest(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        line=line.strip()
        if not line:
            continue

        parts=line.split(None,1)
        if len(parts)!=2:
            continue

        checksum,path=parts
        checksum=checksum.lower()
        # Skip lines whose first token isn't a 32-hex md5 digest — an
        # HTML/captive-portal body otherwise yields bogus "entries" that
        # always mismatch and drive the (now-bounded) re-download loop.
        if not _MD5_HEX_RE.match(checksum):
            continue
        path=path.lstrip("*").replace("\\","/")
        if path.startswith("./"):
            path=path[2:]
        entries.append((checksum,path))
    return entries

def _download_zip(
    zip_url: str,
    zip_path: Path,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    existing=zip_path.stat().st_size if zip_path.exists() else 0
    headers={}
    mode="wb"
    if existing:
        headers["Range"]=f"bytes={existing}-"
        mode="ab"

    started=time.time()
    downloaded=existing
    with requests.get(zip_url, stream=True, headers=headers, timeout=(10, 30)) as r:
        if existing and r.status_code == 416:
            _notify(
                progress_cb,
                phase="download",
                status="Existing model archive found",
                downloaded=existing,
                total=existing,
                speed=0,
                remaining=0,
                percent=100,
                detail=f"{_fmt_bytes(existing)} already downloaded",
            )
            return zip_path

        r.raise_for_status()

        if existing and r.status_code != 206:
            existing=0
            downloaded=0
            mode="wb"

        content_length=int(r.headers.get("content-length") or 0)
        total=existing + content_length if content_length else 0

        try:
            zip_file=open(zip_path,mode)
        except OSError as e:
            if _is_permission_error(e):
                raise ModelDestinationNotWritable(zip_path.parent) from e
            raise
        with zip_file as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if cancel_event and cancel_event.is_set():
                    raise DownloadCancelled("Model download cancelled")
                if not chunk:
                    continue

                try:
                    f.write(chunk)
                except OSError as e:
                    if _is_permission_error(e):
                        raise ModelDestinationNotWritable(zip_path.parent) from e
                    raise
                downloaded += len(chunk)
                elapsed=max(0.001,time.time()-started)
                speed=(downloaded-existing)/elapsed
                remaining=(total-downloaded)/speed if total and speed else None
                percent=int((downloaded/total)*100) if total else 0

                _notify(
                    progress_cb,
                    phase="download",
                    status="Downloading model...",
                    downloaded=downloaded,
                    total=total,
                    speed=speed,
                    remaining=remaining,
                    percent=percent,
                    detail=f"{_fmt_bytes(downloaded)} / {_fmt_bytes(total) if total else 'unknown'} at {_fmt_bytes(speed)}/s, ETA {_fmt_time(remaining)}",
                )

    return zip_path

def _verify_extracted_files(
    cache_dir: Path,
    md5_url: str,
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[tuple[str, str, str]]:
    response=requests.get(md5_url, timeout=(10, 30))
    response.raise_for_status()
    entries=_parse_md5_manifest(response.text)
    if not entries:
        raise RuntimeError("MD5 manifest does not contain any files")

    cache_root=cache_dir.resolve()
    mismatches: list[tuple[str, str, str]] = []

    for index,(expected,relative_path) in enumerate(entries,1):
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelled("Model download cancelled")

        file_path=(cache_dir / relative_path).resolve()
        try:
            file_path.relative_to(cache_root)
        except ValueError:
            raise RuntimeError(f"Unsafe MD5 manifest path: {relative_path}")

        if status_cb: status_cb(f"Checking MD5 {index}/{len(entries)}: {relative_path}")
        _notify(
            progress_cb,
            phase="verify",
            status=f"Checking MD5 {index}/{len(entries)}",
            percent=int((index-1)/len(entries)*100),
            detail=relative_path,
        )

        if not file_path.exists():
            actual="missing"
            mismatches.append((relative_path,expected,actual))
            if status_cb:
                status_cb(f"MD5 CHECK: {relative_path} expected={expected} actual={actual}")
                status_cb(f"Checksum difference: {relative_path} expected={expected} actual={actual}")
            continue

        actual=md5_file(file_path, cancel_event).lower()
        if status_cb: status_cb(f"MD5 CHECK: {relative_path} expected={expected} actual={actual}")
        if actual == expected:
            if status_cb: status_cb(f"MD5 OK: {relative_path}")
        else:
            mismatches.append((relative_path,expected,actual))
            if status_cb: status_cb(f"Checksum difference: {relative_path} expected={expected} actual={actual}")

    _notify(
        progress_cb,
        phase="verify",
        status="MD5 verification complete",
        percent=100,
        detail=f"{len(entries)-len(mismatches)} / {len(entries)} files passed",
    )
    return mismatches

_MODEL_TOKEN_RE = re.compile(r"^models--(.+)$")


def _repo_id_from_url(zip_url: str) -> str | None:
    """Map a smch.ir zip URL/name to its HuggingFace ``Org/Repo`` id.

    The mirror zips are named ``models--<Org>--<Repo>.zip`` and that
    token encodes the exact HuggingFace ``repo_id`` whose
    ``snapshot_download`` cache layout the zip mirrors byte-for-byte
    (``cache_dir/models--<Org>--<Repo>/snapshots/<hash>/...``). This
    lets the fallback path target the correct upstream repo from the
    same registry entry, with no extra config. Returns ``None`` when
    the URL/name doesn't match the expected ``models--Org--Repo`` shape.

    Note: repo names can themselves contain dots (e.g.
    ``faster-distil-whisper-large-v3.5``), so the ``.zip`` suffix is
    stripped by name rather than by splitting on the first dot.
    """
    name = _zip_name_from_url(zip_url)
    if name.lower().endswith(".zip"):
        name = name[: -len(".zip")]

    match = _MODEL_TOKEN_RE.match(name)
    if not match:
        return None

    parts = match.group(1).split("--")
    if len(parts) < 2:
        return None

    org = parts[0]
    repo = "-".join(parts[1:])
    if not org or not repo:
        return None
    return f"{org}/{repo}"


def _short_model_id(model_name: str) -> str | None:
    """Map a registry model ``name`` to faster-whisper's short model id.

    The registry names follow ``faster-whisper-<id>`` /
    ``faster-distil-whisper-<id>``; faster-whisper's own download map keys
    off the short ``<id>`` (``large-v3``, ``large-v3-turbo``,
    ``distil-large-v3.5``, ``medium``, ...). Returns ``None`` for an
    unrecognised shape.
    """
    n = (model_name or "").strip()
    if not n:
        return None
    if n.startswith("faster-distil-whisper-"):
        return "distil-" + n[len("faster-distil-whisper-"):]
    if n.startswith("faster-whisper-"):
        return n[len("faster-whisper-"):]
    return None


def _hf_model_ref(model_name: str, zip_url: str, hf_repo: str | None = None) -> str | None:
    """Resolve a HuggingFace download reference for a registry model.

    Resolution order:

    1. ``hf_repo`` — the EXPLICIT ``Org/Repo`` id from the registry/catalog
       entry, when given. This is deterministic and the source of truth for
       every registry entry; it correctly disambiguates models that share a
       faster-whisper "short id" with a DIFFERENT upstream repo (e.g.
       ``deepdml-large-v3-turbo`` vs. the mobiuslabsgmbh turbo — both would
       otherwise resolve to the same ``large-v3-turbo`` short id below).
    2. faster-whisper's own short id (``_short_model_id``): it maps to the
       CORRECT upstream repo, which a naive ``models--Systran--<repo>`` guess
       gets wrong (e.g. ``large-v3-turbo`` lives under ``mobiuslabsgmbh`` and
       ``distil-large-v3.5`` under ``distil-whisper`` — not Systran, which
       404s/401s).
    3. The ``Org/Repo`` parsed from the mirror zip name — only when neither
       of the above resolved anything.
    """
    if hf_repo:
        return hf_repo
    short = _short_model_id(model_name)
    try:
        from faster_whisper.utils import _MODELS  # type: ignore[attr-defined]

        if short and short in _MODELS:
            return short
    except Exception:  # noqa: BLE001 — faster-whisper internals may move
        if short:
            return short
    return _repo_id_from_url(zip_url)


def _download_via_huggingface(
    model_name: str,
    zip_url: str,
    model_path: Path,
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
    hf_repo: str | None = None,
) -> bool:
    """Fetch the model straight from the HuggingFace Hub as a fallback.

    Used either as the SOLE download source (registry entries with no
    smch.ir mirror, ``url == ""``) or as a fallback when the smch.ir mirror
    is unavailable / its archive fails verification. Delegates to
    ``faster_whisper.download_model`` because it already knows each short
    id's correct upstream repo (when ``hf_repo`` isn't given). ``output_dir``
    is the resolved ``model_path``, so the files land directly in the same
    flat folder (``model.bin`` + ``config.json`` ...) the mirror zip
    produced — the rest of the app keeps resolving the model unchanged.
    Returns ``True`` on success, ``False`` on any failure (import error,
    network/repo error, cancellation).
    """
    if cancel_event and cancel_event.is_set():
        return False

    ref = _hf_model_ref(model_name, zip_url, hf_repo)
    if not ref:
        if status_cb:
            status_cb("HuggingFace fallback: could not resolve the model repo.")
        return False

    try:
        from faster_whisper.utils import download_model
    except Exception as e:  # noqa: BLE001
        if status_cb:
            status_cb(f"HuggingFace fallback unavailable: {e}")
        return False

    if status_cb:
        status_cb(
            f"Mirror unavailable — downloading '{ref}' from huggingface.co ..."
        )
    _notify(
        progress_cb,
        phase="download",
        status=f"Downloading {ref} from HuggingFace...",
        percent=0,
        detail="Mirror unavailable — using huggingface.co",
    )

    try:
        download_model(ref, output_dir=str(model_path))
    except Exception as e:  # noqa: BLE001
        if status_cb:
            status_cb(f"HuggingFace download failed: {e}")
        return False

    if cancel_event and cancel_event.is_set():
        return False

    if status_cb:
        status_cb("Model downloaded from HuggingFace.")
    _notify(
        progress_cb,
        phase="download",
        status="Model downloaded from HuggingFace.",
        percent=100,
        detail=ref,
    )
    return True


def ensure_model(
    config: dict[str, Any],
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    model=config["model"]
    model_path=Path(config["model_path"])
    zip_url=model["url"]
    md5_url=model["md5"]
    hf_repo=model.get("hf_repo") or None

    cache_dir=model_path.parent
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if _is_permission_error(e):
            raise ModelDestinationNotWritable(cache_dir) from e
        raise

    # Registry entries with NO smch.ir mirror have ``url == ""`` — there is
    # no zip / .md5 manifest to download or verify against, so go straight
    # to the HuggingFace fallback (deterministic via ``hf_repo``). A simple
    # on-disk check covers "already installed" since there's no manifest to
    # verify against.
    if not zip_url:
        # There is no manifest to verify against, but a download that was
        # killed mid-transfer can leave the folder holding only SOME of
        # the files: huggingface_hub stores completed files straight in
        # ``model_path`` and parks in-progress blobs under its own
        # ``.cache`` next to them. The old ``any(iterdir())`` check
        # treated such a partial folder as a finished install, so the
        # next model load failed on the missing ``model.bin`` with no
        # in-app way to recover. CT2 repos always carry a top-level
        # ``model.bin`` (and ``model_downloaded()`` already keys off
        # exactly that file), so require it and re-download otherwise.
        if (model_path / "model.bin").exists():
            if status_cb: status_cb("Model already installed")
            _notify(progress_cb, phase="installed", status="Model already installed", percent=100)
            return str(model_path)

        _remove_path(model_path)
        if not _download_via_huggingface(
            model.get("name", ""), zip_url, model_path,
            status_cb, progress_cb, cancel_event,
            hf_repo=hf_repo,
        ):
            if cancel_event and cancel_event.is_set():
                # huggingface_hub's own download cannot be interrupted,
                # so a cancellation is only observable here, after it has
                # returned. Report a clean cancellation rather than a
                # scary "download failed" error for a download that may
                # have completed.
                raise DownloadCancelled("Model download cancelled")
            ref = _hf_model_ref(model.get("name", ""), zip_url, hf_repo) or "unknown"
            raise RuntimeError(
                f"Model download failed: the HuggingFace fallback ({ref}) "
                "was unable to provide the model (no mirror is configured "
                "for this model)."
            )

        if not model_path.exists():
            raise RuntimeError(
                "Model download failed: the HuggingFace fallback reported "
                f"success but the expected model folder is missing: {model_path}"
            )

        if status_cb: status_cb("Model ready")
        _notify(progress_cb, phase="ready", status="Model ready", percent=100, detail="Download complete (HuggingFace)")
        return str(model_path)

    zip_path=cache_dir / _zip_name_from_url(zip_url)

    if model_path.exists():
        if status_cb: status_cb("Model already installed. Verifying MD5...")
        try:
            mismatches=_verify_extracted_files(cache_dir, md5_url, status_cb, progress_cb, cancel_event)
        except requests.RequestException as e:
            # The .md5 manifest could not be fetched (offline, mirror
            # down, 404, ...). The model bytes are already on disk, and
            # refusing to use them here would break the app's documented
            # "fully offline after the first download" behaviour on
            # every relaunch without a network. Treat verification as
            # best-effort in that case; a genuinely corrupt model still
            # fails loudly when the backend tries to load it.
            if status_cb:
                status_cb(f"Could not verify the installed model ({e}); using it as-is.")
            _remove_path(zip_path)
            _notify(progress_cb, phase="installed", status="Model already installed", percent=100)
            return str(model_path)

        if not mismatches:
            _remove_path(zip_path)
            if status_cb: status_cb("Model already installed")
            _notify(progress_cb, phase="installed", status="Model already installed", percent=100)
            return str(model_path)

        if status_cb: status_cb("Installed model MD5 mismatch. Restarting download from zero...")
        _remove_path(zip_path)
        _remove_path(model_path)

    mirror_error: BaseException | None = None
    try:
        last_mismatches: list[tuple[str, str, str]] = []
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Model download cancelled")

            if status_cb: status_cb("Downloading model...")
            try:
                _download_zip(zip_url, zip_path, progress_cb, cancel_event)
            except requests.RequestException as e:
                # A transient network error (connection reset, read
                # timeout, chunked-encoding break) used to abandon the
                # mirror at once: the partial archive was then deleted
                # and the whole model restarted from zero against
                # HuggingFace. When bytes are already on disk the retry
                # below resumes with an HTTP Range request — cheap, and
                # it keeps mirror-only networks (where huggingface.co is
                # blocked) working through a blip. With NOTHING
                # downloaded there is nothing to resume, so fall through
                # to the HuggingFace fallback immediately, as before.
                # Bounded by MAX_DOWNLOAD_ATTEMPTS, shared with the MD5
                # mismatch retries below.
                partial = zip_path.exists() and zip_path.stat().st_size > 0
                if (not partial or attempt >= MAX_DOWNLOAD_ATTEMPTS
                        or (cancel_event and cancel_event.is_set())):
                    raise
                if status_cb:
                    status_cb(
                        f"Download interrupted ({e}). "
                        f"Resuming (attempt {attempt + 1}/{MAX_DOWNLOAD_ATTEMPTS})..."
                    )
                _notify(
                    progress_cb,
                    phase="download",
                    status=(
                        "Download interrupted. Resuming "
                        f"({attempt + 1}/{MAX_DOWNLOAD_ATTEMPTS})..."
                    ),
                    percent=0,
                    detail=str(e),
                )
                continue

            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Model download cancelled")

            if status_cb: status_cb("Extracting model...")
            _notify(progress_cb, phase="extract", status="Extracting model...", percent=100, detail="Unpacking downloaded archive")
            _remove_path(model_path)
            with zipfile.ZipFile(zip_path,'r') as z:
                # Zip-slip guard: reject any member that would resolve OUTSIDE
                # cache_dir (e.g. a tampered archive with "..\\.." entries)
                # before extracting anything.
                _cache_resolved = Path(cache_dir).resolve()
                for _member in z.namelist():
                    _target = (_cache_resolved / _member).resolve()
                    if _target != _cache_resolved and _cache_resolved not in _target.parents:
                        raise RuntimeError(f"Unsafe path in model archive: {_member!r}")
                try:
                    z.extractall(cache_dir)
                except OSError as e:
                    if _is_permission_error(e):
                        raise ModelDestinationNotWritable(cache_dir) from e
                    raise

            if not model_path.exists():
                raise RuntimeError(f"Extracted model folder missing: {model_path}")

            if status_cb: status_cb("Verifying extracted model files...")
            mismatches=_verify_extracted_files(cache_dir, md5_url, status_cb, progress_cb, cancel_event)
            if not mismatches:
                # Clear any earlier attempt's mismatches, or a SUCCESSFUL
                # retry would still trip the terminal "still mismatched"
                # raise below and fall through to an unnecessary (and
                # possibly failing) HuggingFace re-download of a model
                # that is already extracted and verified on disk.
                last_mismatches = []
                _remove_path(zip_path)
                break

            last_mismatches = mismatches
            _remove_path(zip_path)
            _remove_path(model_path)

            if attempt >= MAX_DOWNLOAD_ATTEMPTS:
                # Don't loop forever on a bad mirror / corrupt archive.
                break

            if status_cb:
                status_cb(
                    f"MD5 mismatch (attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}). "
                    "Deleting model archive and folder, then restarting from zero..."
                )
            _notify(
                progress_cb,
                phase="restart",
                status=f"MD5 mismatch. Retrying ({attempt}/{MAX_DOWNLOAD_ATTEMPTS})...",
                percent=0,
                detail=f"{len(mismatches)} file checksum(s) failed",
            )

        if last_mismatches:
            sample = ", ".join(rel for _exp, _got, rel in last_mismatches[:5])
            more = "" if len(last_mismatches) <= 5 else f" (+{len(last_mismatches) - 5} more)"
            raise RuntimeError(
                f"Model download failed after {MAX_DOWNLOAD_ATTEMPTS} attempts: "
                f"{len(last_mismatches)} file checksum(s) still mismatched "
                f"[{sample}{more}]. The mirror may be serving a corrupt archive."
            )
    except (DownloadCancelled, ModelDestinationNotWritable):
        raise
    except Exception as e:
        # The smch.ir mirror failed for ANY reason — missing zip (404),
        # network error, or persistent MD5 mismatch. Before giving up, try
        # the same model straight from the HuggingFace Hub: faster-whisper's
        # own download map resolves the correct upstream repo (Systran for
        # most, but mobiuslabsgmbh/turbo and distil-whisper/distil) and
        # writes the files straight into model_path.
        mirror_error = e
        model_ref = _hf_model_ref(model.get("name", ""), zip_url, hf_repo)
        if model_ref is None:
            raise

        if status_cb:
            status_cb(f"Mirror download failed ({e}). Trying HuggingFace fallback...")
        _remove_path(zip_path)
        _remove_path(model_path)

        if not _download_via_huggingface(
            model.get("name", ""), zip_url, model_path,
            status_cb, progress_cb, cancel_event,
            hf_repo=hf_repo,
        ):
            if cancel_event and cancel_event.is_set():
                # See the no-mirror branch above: hf_hub downloads are not
                # interruptible, so a cancellation surfaces here only after
                # the call returns. Report it as a cancellation, not as a
                # failure of both sources.
                raise DownloadCancelled("Model download cancelled") from mirror_error
            raise RuntimeError(
                "Model download failed: both the smch.ir mirror "
                f"({mirror_error}) and the HuggingFace fallback "
                f"({model_ref}) were unable to provide the model."
            ) from mirror_error

        if not model_path.exists():
            raise RuntimeError(
                "Model download failed: the HuggingFace fallback reported "
                f"success for {model_ref!r} but the expected model folder is "
                f"missing: {model_path}"
            ) from mirror_error

        # HuggingFace's own download verifies blob hashes; the smch.ir
        # .md5 manifest describes a different (zip-mirror) layout and
        # would always mismatch here, so skip _verify_extracted_files.
        if status_cb: status_cb("Model ready")
        _notify(progress_cb, phase="ready", status="Model ready", percent=100, detail="Download complete (HuggingFace fallback)")
        return str(model_path)

    if status_cb: status_cb("Model ready")
    _notify(progress_cb, phase="ready", status="Model ready", percent=100, detail="Download complete")
    return str(model_path)
