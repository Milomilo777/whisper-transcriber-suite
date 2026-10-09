from __future__ import annotations

import contextlib
import errno
import math
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Generator, Iterable

from core import offline
from core.logging_setup import redact_urls
from core.hub import model_weights_present


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
    ``reason`` is ``"permission"`` (no write access) or ``"missing"`` (the
    folder's drive is not there: an unplugged USB disk, a disconnected
    network share), so the UI can say which one it is.
    """

    def __init__(
        self,
        directory: str | Path,
        message: str | None = None,
        reason: str = "permission",
    ) -> None:
        self.directory = str(directory)
        self.reason = reason
        super().__init__(
            message
            or f"Cannot write to the model folder: {self.directory}"
        )


class InsufficientDiskSpace(RuntimeError):
    """The model folder's disk has too little free space for the download.

    Raised before a byte is written (and before unpacking a finished
    archive, which is kept so the next try resumes from it), instead of a
    raw "No space left on device" halfway through a multi-GB download.
    """


class HuggingFaceDownloadError(RuntimeError):
    """The huggingface.co download failed; the text says why for the user."""


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


# ERROR_HANDLE_DISK_FULL (39) and ERROR_DISK_FULL (112): what Windows
# reports when a write runs out of space, sometimes without errno ENOSPC.
_DISK_FULL_WINERRORS = {39, 112}
# ERROR_SHARING_VIOLATION (32) and ERROR_LOCK_VIOLATION (33): another
# program holds the file. Python raises them as PermissionError, but the
# folder itself is writable, so they must not trigger "pick another folder".
_FILE_IN_USE_WINERRORS = {32, 33}

# Margin kept free on top of the bytes a download or unpacking needs.
_FREE_SPACE_MARGIN = 64 * 1024 * 1024


def _is_disk_full(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and (
        exc.errno == errno.ENOSPC
        or getattr(exc, "winerror", None) in _DISK_FULL_WINERRORS
    )


def _require_free_space(directory: Path, needed: int, what: str) -> None:
    """Raise :class:`InsufficientDiskSpace` when ``directory``'s disk has
    less than ``needed`` bytes (plus a margin) free.

    A disk whose usage cannot be read skips the check: the write itself
    still fails loudly if space really runs out.
    """
    try:
        free = shutil.disk_usage(directory).free
    except (OSError, ValueError):
        return
    if free >= needed + _FREE_SPACE_MARGIN:
        return
    raise InsufficientDiskSpace(
        f"Not enough free disk space for {what} in {directory}: about "
        f"{_fmt_bytes(needed + _FREE_SPACE_MARGIN)} is needed, "
        f"{_fmt_bytes(free)} is free. Free up space on that drive, or choose "
        "another model folder (Advanced settings > Model folder), then try again."
    )


def _cause_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


# Exception class names (matched along the MRO so subclasses count) that
# mean "huggingface.co could not be reached". By name, because the
# classes live in httpx / requests / huggingface_hub, which this module
# does not import.
_NETWORK_ERROR_NAMES = {
    "ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError",
    "WriteError", "RemoteProtocolError", "ProxyError", "NetworkError",
    "TimeoutException", "ConnectionError", "Timeout", "SSLError",
    "LocalEntryNotFoundError", "OfflineModeIsEnabled", "TimeoutError",
}
# huggingface_hub errors for a repo the Hub refuses or does not have.
_REPO_ERROR_NAMES = {
    "RepositoryNotFoundError", "GatedRepoError", "RevisionNotFoundError",
    "RemoteEntryNotFoundError", "DisabledRepoError",
}


def _class_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _describe_download_error(exc: BaseException, folder: Path, source: str) -> str:
    """One user-facing sentence for a failed download, with the raw error.

    The download dialog shows this text, so it says what went wrong in
    plain words and what to do; the raw exception follows in brackets for
    a bug report.
    """
    # A signed download link in the error text must not reach the dialog or logs.
    raw = redact_urls(f"{type(exc).__name__}: {exc}".strip())
    if len(raw) > 300:
        raw = raw[:297] + "..."
    chain = list(_cause_chain(exc))
    if any(_is_disk_full(e) for e in chain):
        return (
            f"Not enough free disk space in {folder}. Free up space on that "
            "drive, or choose another model folder (Advanced settings > Model folder), "
            f"then try again. [{raw}]"
        )
    names: set[str] = set()
    for e in chain:
        names |= _class_names(e)
    if names & _REPO_ERROR_NAMES:
        return f"{source} does not offer this model to the app. [{raw}]"
    if names & _NETWORK_ERROR_NAMES:
        return (
            f"Could not reach {source}: this computer is offline, or the site "
            "is blocked on this network. Check the internet connection, "
            f"proxy or VPN, then try again. [{raw}]"
        )
    return raw


# ---------------------------------------------------------------- model picker
#
# v0.8 — pick one of several pre-bundled faster-whisper variants from
# the Advanced dialog. Each entry resolves to the ``model`` sub-dict
# (name + hf_repo) the rest of this module already consumes.
#
# Models download only from the Hugging Face Hub. The zip mirror the app
# used before (``url`` + ``md5`` keys) is retired: those keys are dropped
# from every catalog entry and ignored when an older config.json or a
# hand-edited ``model_catalog`` still carries them. ``approx_size_gb`` is
# shown in the Advanced dropdown so the user knows the install cost up front.

# This is the BUILT-IN default catalog. It is the lowest-priority source —
# the online config (see core.config) may ADD or OVERRIDE entries under its
# ``model_catalog`` key, so new models can ship without an app update. Use
# ``catalog_models(config)`` / ``catalog_resolve_entry(config, slug)`` to read
# the merged effective catalog; the bare ``MODEL_REGISTRY`` / ``list_models``
# / ``resolve_model_entry`` helpers keep returning the built-ins only (still
# used as the offline fallback and by existing tests).
#
# Every entry carries an explicit ``"hf_repo"`` — the exact HuggingFace
# ``Org/Repo`` id this model downloads from. This makes the download
# deterministic: ``_hf_model_ref`` prefers ``hf_repo`` over the name-based
# guess (``_short_model_id``), which can resolve to the wrong upstream org
# for models that share a faster-whisper "short id" with a different repo
# (e.g. ``deepdml-large-v3-turbo`` vs. the mobiuslabsgmbh turbo, both of
# which faster-whisper's own map would resolve to the SAME
# ``large-v3-turbo`` short id).
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "tiny.en": {
        "label": "Tiny (English) — fastest, lowest accuracy (~0.075 GB)",
        "name": "faster-whisper-tiny.en",
        "hf_repo": "Systran/faster-whisper-tiny.en",
        "english_only": True,
        "approx_size_gb": 0.075,
        "info": (
            "~75 MB, English-only. The fastest and least accurate model — "
            "useful for quick drafts or very low-power hardware."
        ),
    },
    "tiny": {
        "label": "Tiny — fastest, lowest accuracy, multilingual (~0.075 GB)",
        "name": "faster-whisper-tiny",
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
        "hf_repo": "Systran/faster-whisper-base.en",
        "english_only": True,
        "approx_size_gb": 0.145,
        "info": (
            "~145 MB, English-only. Very fast with modest accuracy — a step "
            "up from Tiny for short, low-stakes clips."
        ),
    },
    "base": {
        "label": "Base — very fast, low accuracy, multilingual (~0.145 GB)",
        "name": "faster-whisper-base",
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
        "hf_repo": "Systran/faster-whisper-small.en",
        "english_only": True,
        "approx_size_gb": 0.5,
        "info": (
            "~500 MB, English-only. Good speed/accuracy balance for everyday "
            "English transcripts on modest hardware."
        ),
    },
    "small": {
        "label": "Small — fast, moderate accuracy, multilingual (~0.5 GB)",
        "name": "faster-whisper-small",
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
        "hf_repo": "Systran/faster-whisper-medium.en",
        "english_only": True,
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Noticeably more accurate than Small at "
            "roughly half the speed."
        ),
    },
    "medium": {
        "label": "Medium — slower, good accuracy, multilingual (~1.5 GB)",
        "name": "faster-whisper-medium",
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
        "hf_repo": "Systran/faster-distil-whisper-small.en",
        "english_only": True,
        "approx_size_gb": 0.4,
        "info": (
            "~400 MB, English-only. Distilled for speed — faster than Small "
            "with similar English accuracy."
        ),
    },
    "distil-medium.en": {
        "label": "Distil Medium (English) — fast, English-only (~0.8 GB)",
        "name": "faster-distil-whisper-medium.en",
        "hf_repo": "Systran/faster-distil-whisper-medium.en",
        "english_only": True,
        "approx_size_gb": 0.8,
        "info": (
            "~800 MB, English-only. Distilled for speed — faster than "
            "Medium with similar English accuracy."
        ),
    },
    "distil-large-v2": {
        "label": "Distil Large v2 — fast, English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v2",
        "hf_repo": "Systran/faster-distil-whisper-large-v2",
        "english_only": True,
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Distilled from Large v2 for ~5x speed "
            "with close to its English accuracy."
        ),
    },
    "distil-large-v3": {
        "label": "Distil Large v3 — fast, English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v3",
        "hf_repo": "Systran/faster-distil-whisper-large-v3",
        "english_only": True,
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. Distilled from Large v3 for ~5x speed "
            "with close to its English accuracy."
        ),
    },
    "distil-large-v3.5": {
        "label": "Distil Large v3.5 — fastest English-only (~1.5 GB)",
        "name": "faster-distil-whisper-large-v3.5",
        "hf_repo": "distil-whisper/distil-large-v3.5-ct2",
        "english_only": True,
        "approx_size_gb": 1.5,
        "info": (
            "~1.5 GB, English-only. The newest distilled large model — "
            "fastest English-only option with accuracy close to Large v3."
        ),
    },
    "large-v3-turbo": {
        "label": "Large v3 Turbo — ~5x faster, similar accuracy (~1.6 GB)",
        "name": "faster-whisper-large-v3-turbo",
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
    """Return ``{name, hf_repo}`` for a built-in registry slug, or ``None``.

    The returned dict has the shape of ``DEFAULT_CONFIG["model"]`` so the
    caller can assign it directly to ``config["model"]``; ``ensure_model``
    reads ``hf_repo`` to pick the Hugging Face repo deterministically.
    """
    entry = MODEL_REGISTRY.get(slug)
    if entry is None:
        return None
    return {
        "name": entry["name"],
        "hf_repo": entry.get("hf_repo", ""),
    }


# Keys of the retired zip mirror. Never read: an old config.json or a
# hand-edited ``model_catalog`` pin that still holds them cannot make the
# app download from anywhere but the Hugging Face Hub.
_RETIRED_MIRROR_KEYS = frozenset({"url", "md5"})


def _merged_catalog(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Built-in MODEL_REGISTRY overlaid with ``config['model_catalog']``.

    The online/local config may carry a ``model_catalog`` dict in the SAME
    shape as MODEL_REGISTRY (slug → {label, name, hf_repo, approx_size_gb,
    info, optional english_only}). Each online slug is overlaid onto the built-in entry (or added
    new), so the catalog can grow / be re-pointed without an app update. A
    malformed catalog (not a dict, or non-dict entries) is ignored
    entry-by-entry so a bad online payload never breaks the picker — the
    built-ins still show.

    Models come only from the Hugging Face Hub, so an entry needs a
    non-empty ``hf_repo`` (its own or the built-in one it overlays). The
    retired mirror keys ``url``/``md5`` are dropped from every entry, so a
    hand-edited pin in an old config.json cannot point a download at
    another server.
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
        # ``hf_repo`` (if present) must be a string.
        if not is_safe_model_folder_name(entry.get("name")):
            continue
        if not isinstance(entry.get("hf_repo", ""), str):
            continue
        base = dict(merged.get(slug) or {})
        renamed = entry.get("name") != base.get("name")
        base.update({k: v for k, v in entry.items() if k not in _RETIRED_MIRROR_KEYS})
        if renamed and not entry.get("hf_repo"):
            # The built-in repo belongs to the built-in name: a pin that
            # renames the model must not download that repo into its folder.
            base["hf_repo"] = ""
        # Need a download source on the Hub.
        if not (str(base.get("hf_repo") or "").strip()
                or _hf_model_ref(str(base.get("name") or ""))):
            continue
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
        try:
            # JSON "Infinity" / "NaN" parse as floats; a huge JSON integer
            # makes isfinite() raise OverflowError. A size below zero is
            # as meaningless as a non-finite one ("~-5 GB" in the popup).
            usable = (not isinstance(_gb, bool) and isinstance(_gb, (int, float))
                      and math.isfinite(_gb) and _gb > 0)
        except OverflowError:
            usable = False
        if not usable:
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
    """``{name, hf_repo}`` for ``slug`` from the merged catalog, or ``None``.

    The caller can assign the result straight to ``config["model"]``;
    ``ensure_model`` downloads from ``hf_repo``.
    """
    entry = _merged_catalog(config).get(slug)
    if entry is None:
        return None
    return {
        "name": entry["name"],
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
    except (TypeError, ValueError, OverflowError):
        gb = 0.0
    # not finite: an "Infinity" / NaN in a hand-edited or online catalog
    if not math.isfinite(gb) or gb <= 0:
        return ""
    if gb < 1:
        return f"about {max(10, int(round(gb * 1000, -1)))} MB"
    return f"about {gb:g} GB"


def is_english_only(config: dict[str, Any] | None, slug: str) -> bool | None:
    """True for an English-only catalog model, False for a multilingual one.

    None when ``slug`` is not in the merged catalog (a custom model): the
    app cannot know what such a model understands, so callers stay silent.
    The catalog's ``english_only`` flag decides; an entry without the flag
    (an online catalog addition) counts as English-only when its slug ends
    in ``.en``, Whisper's naming for the English-only checkpoints.
    """
    key = str(slug or "").strip()
    entry = _merged_catalog(config).get(key)
    if entry is None:
        return None
    flag = entry.get("english_only")
    if isinstance(flag, bool):
        return flag
    return key.endswith(".en")


def english_only_mismatch(
    config: dict[str, Any], slug: str, language: str | None
) -> bool:
    """True when English-only ``slug`` meets speech that may not be English.

    ``language`` None is auto-detect: an English-only model cannot detect
    anything, so non-English speech still comes out as wrong English text.
    Custom models (not in the catalog) never match: their languages are
    unknown.
    """
    if (language or "").strip().lower() == "en":
        return False
    return is_english_only(config, slug) is True


def multilingual_counterpart(config: dict[str, Any] | None, slug: str) -> str:
    """The multilingual catalog model closest to English-only ``slug``.

    ``tiny.en`` -> ``tiny``, ``distil-small.en`` -> ``small``: the same size
    and roughly the same speed. The distilled large models are picked for
    speed, so they map to ``large-v3-turbo``, the fast multilingual large
    model. Anything without a multilingual twin in the catalog gets
    ``small``, the smallest model that is useful for languages other than
    English (see ``core.live_model.recommended_cpu_slug``).
    """
    key = str(slug or "").strip()
    candidates: list[str] = []
    if key.startswith("distil-large"):
        candidates.append("large-v3-turbo")
    base = key[: -len(".en")] if key.endswith(".en") else key
    if base.startswith("distil-"):
        base = base[len("distil-"):]
    candidates += [base, "small"]
    for candidate in candidates:
        if candidate != key and is_english_only(config, candidate) is False:
            return candidate
    return "small"


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
        return model_weights_present(model_folder_for(hub_folder, entry["name"]))
    except Exception:  # noqa: BLE001
        return False

def _tree_size(path: Path) -> int:
    """Bytes in the files under ``path`` (0 when it does not exist)."""
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _fmt_bytes(value: float | int | None) -> str:
    value=float(value or 0)
    for unit in ("B","KB","MB","GB","TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value/=1024
    return f"{value:.1f} TB"

def _notify(progress_cb: Callable[[dict[str, Any]], None] | None, **payload: Any) -> None:
    if progress_cb:
        progress_cb(payload)


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


def _hf_model_ref(model_name: str, hf_repo: str | None = None) -> str | None:
    """Resolve the Hugging Face download reference for a model.

    Resolution order:

    1. ``hf_repo`` — the EXPLICIT ``Org/Repo`` id from the registry/catalog
       entry, when given. This is deterministic and the source of truth for
       every registry entry; it correctly disambiguates models that share a
       faster-whisper "short id" with a DIFFERENT upstream repo (e.g.
       ``deepdml-large-v3-turbo`` vs. the mobiuslabsgmbh turbo — both would
       otherwise resolve to the same ``large-v3-turbo`` short id below).
    2. faster-whisper's own short id (``_short_model_id``): it maps to the
       CORRECT upstream repo, which a naive ``Systran/<repo>`` guess gets
       wrong (e.g. ``large-v3-turbo`` lives under ``mobiuslabsgmbh`` and
       ``distil-large-v3.5`` under ``distil-whisper``).
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
    return None


def _hf_repo_for(config: dict[str, Any], model: dict[str, Any]) -> str | None:
    """The ``hf_repo`` to download ``model`` from.

    The catalog entry with the same ``name`` wins over ``model["hf_repo"]``:
    ``config["model"]`` is deep-merged over the defaults, so a config.json
    saved before ``hf_repo`` existed carries its own ``name`` next to the
    DEFAULT model's ``hf_repo`` and would otherwise download another model
    into this model's folder.
    """
    name = str(model.get("name") or "")
    if name:
        for entry in _merged_catalog(config).values():
            if entry.get("name") == name and entry.get("hf_repo"):
                return str(entry["hf_repo"])
    return model.get("hf_repo") or None


def _approx_model_bytes(config: dict[str, Any], name: str) -> int:
    """Catalog download size of the model called ``name`` (0 = unknown)."""
    for entry in _merged_catalog(config).values():
        if entry.get("name") == name:
            gb = entry.get("approx_size_gb") or 0.0
            if isinstance(gb, (int, float)) and not isinstance(gb, bool):
                try:
                    # OverflowError: an integer too large for a float, or a
                    # finite size like 1e308 whose byte count is not finite.
                    if math.isfinite(gb) and gb > 0:
                        return int(gb * 1024 ** 3)
                except OverflowError:
                    pass
    return 0


def _download_via_huggingface(
    model_name: str,
    model_path: Path,
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
    hf_repo: str | None = None,
) -> bool:
    """Fetch the model from the Hugging Face Hub into ``model_path``.

    Delegates to ``faster_whisper.download_model`` because it already knows
    each short id's correct upstream repo (when ``hf_repo`` isn't given).
    ``output_dir`` is the resolved ``model_path``, so the files land in the
    flat folder (``model.bin`` + ``config.json`` ...) the rest of the app
    loads from.

    Files already in ``model_path`` are kept: huggingface_hub resumes its
    unfinished ``.incomplete`` blobs under ``model_path/.cache`` and, while
    the Hub is reachable, re-checks every finished file against it, so a
    retry continues a killed multi-GB download instead of starting from
    zero. When the Hub is unreachable it hands back the local files without
    an error, so callers check the folder afterwards.

    Returns ``True`` on success and ``False`` when cancelled. A failure
    raises :class:`HuggingFaceDownloadError` whose text tells the user what
    went wrong (disk full, site unreachable, ...), or
    :class:`ModelDestinationNotWritable` for a folder without write access.
    """
    if cancel_event and cancel_event.is_set():
        return False

    ref = _hf_model_ref(model_name, hf_repo)
    if not ref:
        if status_cb:
            status_cb("Hugging Face download: could not resolve the model repo.")
        raise HuggingFaceDownloadError(
            "the app could not work out which huggingface.co repo holds this model"
        )

    try:
        from faster_whisper.utils import download_model
    except Exception as e:  # noqa: BLE001
        if status_cb:
            status_cb(f"Hugging Face download unavailable: {e}")
        raise HuggingFaceDownloadError(
            f"the downloader is missing from this installation [{type(e).__name__}: {e}]"
        ) from e

    if status_cb:
        status_cb(f"Downloading '{ref}' from huggingface.co ...")
    _notify(
        progress_cb,
        phase="download",
        status=f"Downloading {ref} from Hugging Face...",
        percent=0,
        detail="huggingface.co",
    )

    try:
        download_model(ref, output_dir=str(model_path))
    except Exception as e:  # noqa: BLE001
        if status_cb:
            status_cb(f"Hugging Face download failed: {e}")
        if cancel_event and cancel_event.is_set():
            return False
        if getattr(e, "winerror", None) in _FILE_IN_USE_WINERRORS:
            raise HuggingFaceDownloadError(
                "a file in the model folder is in use by another program "
                "(often an antivirus scan). Wait a moment, then try again. "
                f"[{type(e).__name__}: {e}]"
            ) from e
        if isinstance(e, OSError) and _is_permission_error(e) and not _is_disk_full(e):
            raise ModelDestinationNotWritable(model_path) from e
        raise HuggingFaceDownloadError(
            _describe_download_error(e, model_path.parent, "huggingface.co")
        ) from e

    if cancel_event and cancel_event.is_set():
        return False

    if status_cb:
        status_cb("Model downloaded from Hugging Face.")
    _notify(
        progress_cb,
        phase="download",
        status="Model downloaded from Hugging Face.",
        percent=100,
        detail=ref,
    )
    return True


@contextlib.contextmanager
def _progress_feed(
    model_path: Path,
    approx_bytes: int,
    progress_cb: Callable[[dict[str, Any]], None] | None,
    interval: float = 1.0,
) -> Generator[None, None, None]:
    """Report download progress while huggingface_hub runs.

    ``faster_whisper.download_model`` has no progress hook, so a helper
    thread measures the bytes in ``model_path`` (finished files plus the
    ``.incomplete`` blobs under ``.cache``) against the catalog size.
    """
    if progress_cb is None or approx_bytes <= 0:
        yield
        return
    stop = threading.Event()
    start_bytes = _tree_size(model_path)
    started = time.monotonic()

    def _feed() -> None:
        while not stop.wait(interval):
            done = _tree_size(model_path)
            elapsed = max(0.001, time.monotonic() - started)
            speed = max(0.0, (done - start_bytes) / elapsed)
            left = max(0, approx_bytes - done)
            _notify(
                progress_cb,
                phase="download",
                status="Downloading model from Hugging Face...",
                downloaded=done,
                total=approx_bytes,
                speed=speed,
                remaining=(left / speed) if speed else None,
                # The catalog size is approximate: stay below 100 until done.
                percent=min(99, int(done * 100 / approx_bytes)),
                detail=f"about {_fmt_bytes(done)} of {_fmt_bytes(approx_bytes)}",
            )

    feeder = threading.Thread(target=_feed, name="model-download-progress", daemon=True)
    feeder.start()
    try:
        yield
    finally:
        stop.set()
        feeder.join(timeout=interval + 1)


def _offline_download_text(model: dict[str, Any]) -> str:
    name = str(model.get("name") or "").strip()
    return f"downloading the model {name}" if name else "downloading this model"


def _hf_download_unfinished(model_path: Path) -> bool:
    """True when a Hugging Face download into ``model_path`` was cut off.

    huggingface_hub writes each file as ``<hash>.<etag>.incomplete`` under
    ``.cache/huggingface/download`` and renames it into place when it is
    complete, so a leftover ``.incomplete`` means a file of the model
    (``model.bin`` or a tokenizer / vocabulary file) is still missing.
    """
    download_dir = model_path / ".cache" / "huggingface" / "download"
    try:
        return any(download_dir.rglob("*.incomplete"))
    except OSError:
        return False


def _huggingface_failure(
    model: dict[str, Any],
    model_path: Path,
    status_cb: Callable[[str], None] | None,
    progress_cb: Callable[[dict[str, Any]], None] | None,
    cancel_event: threading.Event | None,
    hf_repo: str | None,
) -> str | None:
    """Run the huggingface.co download; ``None`` on success, else the
    user-facing reason it failed. A cancellation raises
    :class:`DownloadCancelled` (huggingface_hub cannot be interrupted, so
    it is only observable once the call has returned)."""
    try:
        ok = _download_via_huggingface(
            model.get("name", ""), model_path,
            status_cb, progress_cb, cancel_event,
            hf_repo=hf_repo,
        )
    except HuggingFaceDownloadError as e:
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelled("Model download cancelled") from e
        return str(e)
    if cancel_event and cancel_event.is_set():
        raise DownloadCancelled("Model download cancelled")
    if not ok:
        return "the download did not finish"
    if not model_weights_present(model_path) or _hf_download_unfinished(model_path):
        # huggingface_hub returns without an error when the Hub cannot be
        # reached but some files are already on disk.
        return (
            f"the download did not complete (model files are missing in "
            f"{model_path}); huggingface.co may be unreachable. Check the "
            "internet connection, proxy or VPN, then try again."
        )
    return None


def ensure_model(
    config: dict[str, Any],
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Make sure the configured model is on disk; return its folder.

    Models download only from the Hugging Face Hub. A ``url``/``md5`` pair
    left in an older ``config["model"]`` (the retired zip mirror) is
    ignored. A model already on disk is never deleted here: an unfinished
    download is resumed in place, and an installed model whose resume
    attempt fails is used as it is.
    """
    model=config["model"]
    model_path=Path(config["model_path"])
    hf_repo=_hf_repo_for(config, model)

    cache_dir=model_path.parent
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if _is_permission_error(e):
            raise ModelDestinationNotWritable(cache_dir) from e
        if isinstance(e, FileNotFoundError):
            # The folder's drive is not there (an unplugged USB disk, a
            # disconnected network share): offer another folder rather
            # than the raw "[WinError 3] The system cannot find the path".
            raise ModelDestinationNotWritable(
                cache_dir,
                f"The model folder is not available: {cache_dir}. Its drive "
                "may be unplugged or disconnected.",
                reason="missing",
            ) from e
        if _is_disk_full(e):
            raise InsufficientDiskSpace(
                f"Not enough free disk space to create the model folder {cache_dir}. "
                "Free up space on that drive, or choose another model folder "
                "(Advanced settings > Model folder), then try again."
            ) from e
        raise

    # A download that was killed mid-transfer can leave the folder holding
    # only SOME of the files: huggingface_hub stores completed files
    # straight in ``model_path`` and parks in-progress blobs under its own
    # ``.cache`` next to them. Only a folder with ``model.bin`` and no
    # unfinished blob counts as installed; anything else resumes.
    weights_present = model_weights_present(model_path)
    unfinished = weights_present and _hf_download_unfinished(model_path)
    if weights_present and (not unfinished or offline.is_offline()):
        if status_cb:
            status_cb(
                "Model already installed (offline mode: not checked)."
                if unfinished else "Model already installed"
            )
        _notify(progress_cb, phase="installed", status="Model already installed", percent=100)
        return str(model_path)

    offline.require_online(_offline_download_text(model))
    approx_bytes = _approx_model_bytes(config, str(model.get("name") or ""))
    if not weights_present:
        # An installed model with a leftover blob is used as it is if the
        # resume fails, so a full disk must not refuse it here.
        _require_free_space(
            cache_dir,
            max(0, approx_bytes - _tree_size(model_path)),
            "the model download",
        )
    # The partial folder is kept: the download resumes from it.
    with _progress_feed(model_path, approx_bytes, progress_cb):
        reason = _huggingface_failure(
            model, model_path, status_cb, progress_cb, cancel_event, hf_repo
        )
    if reason is not None:
        if weights_present:
            # An installed model with a leftover blob from an older cut-off
            # download: the resume failed, but the model itself is there.
            if status_cb:
                status_cb(f"Could not finish the model download ({reason}); using the installed model.")
            _notify(progress_cb, phase="installed", status="Model already installed", percent=100)
            return str(model_path)
        ref = _hf_model_ref(model.get("name", ""), hf_repo) or "unknown"
        raise RuntimeError(
            f"Model download from huggingface.co ({ref}) failed: {reason}"
        )

    if status_cb: status_cb("Model ready")
    _notify(progress_cb, phase="ready", status="Model ready", percent=100, detail="Download complete (Hugging Face)")
    return str(model_path)
