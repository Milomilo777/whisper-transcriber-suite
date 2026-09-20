"""Model Hub folder — where Whisper / Parakeet model files live.

A "hub" is just the parent directory that holds one or more
``models--Vendor--name/`` subdirectories. We split this concept out
from ``model_path`` so:

  * The user picks the location ONCE at first launch (or via the
    Advanced dialog later) and every supported model lands under
    the same root, just like a HuggingFace cache.
  * Multi-model picker (v0.8 Phase 1) can compute each variant's
    folder from ``hub_folder / models--Systran--<name>`` without
    asking the user again.
  * The installer can detect "is the hub inside the install dir?"
    and prompt the user about deleting it on uninstall.

Resolution order used by the rest of the codebase (in ``model_manager``
+ ``transcriber``):

  1. ``config["model_path"]`` if set AND the folder exists — explicit
     per-model override wins (preserves legacy user configs).
  2. ``config["hub_folder"]`` + the current model's directory name.
  3. Last-resort fallback: ``user_cache_dir() / "models" / …``
     (this is the pre-v0.8 behaviour; only hit when neither the
     hub nor an explicit model_path is configured, e.g. running
     headless from the CLI with a fresh profile).

The first-run UI dialog (``app/dialogs/hub_setup``) shows
:func:`default_hub_folder` as its initial value, which is a writable
per-user cache directory (``%LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\models``
on Windows). The user can pick a different folder (e.g. a big external
drive) and we persist that choice to ``config["hub_folder"]``.

The default deliberately lives under the per-user cache, NEVER under
the install directory. The installers put the app in Program Files
(admin-only, non-writable for a standard user), so an ``<app_dir>/hub``
default made the very first model download fail with "Access is denied"
for non-admin accounts.

This module is Tk-free so it can be called from worker subprocesses
and the installer-side Pascal Script (via reading the JSON file
directly).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# The default hub is the per-user model cache root. It MUST equal the
# empty-hub fallback used by ``model_folder_for`` (``user_cache_dir() /
# "models"``) so that a profile with no explicit ``hub_folder`` resolves
# the SAME folder whether the path comes from ``default_hub_folder()``
# (e.g. the first-run dialog / ``_apply_runtime_fallbacks``) or from the
# bare fallback. If these diverged, an existing model already sitting in
# ``Cache/models`` would be ignored and silently re-downloaded (~3 GB)
# into a different folder. Keep the two in lock-step.
HUB_SUBFOLDER_NAME = "models"


def resolve_app_dir() -> Path:
    """Return the directory the user thinks of as "the app folder".

    NOTE: this no longer backs the model hub (see
    :func:`default_hub_folder`). It is kept only for installer-side
    "is the hub inside the install dir?" detection and uninstall
    prompts — never use it to derive a writable data location, because
    a Program Files install dir is not writable for a standard user.

    Three runtime contexts:

      * **Onefile frozen exe** — the exe extracts its bundled assets
        to ``sys._MEIPASS`` but the exe itself lives in a stable
        directory next to a Desktop shortcut etc. We use the
        ``sys.executable`` directory, NOT the extract dir, because
        the extract dir is recreated each launch and is the wrong
        place for a persistent hub.
      * **Onedir frozen exe** (Inno Setup install) — same:
        ``dirname(sys.executable)`` is the ``{app}`` directory the
        installer wrote files to.
      * **Source / dev** — the repo root (two parents up from this
        file's directory).
    """
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(os.path.abspath(sys.executable)))
    # core/hub.py → core → repo_root
    return Path(__file__).resolve().parent.parent


# Marker file the Standard installer drops into the {app} directory
# unless the user ticks "Install the Video Tiling (video wall) feature"
# at install time (opt-in, off by default since 2026-08-15). Its mere
# presence disables the in-app Video Tiling tab; it is never written by
# the app itself. In a source / dev checkout the repo root won't contain
# it, so tiling stays on for developers.
NO_TILING_MARKER = "no_tiling.flag"


def tiling_tab_enabled() -> bool:
    """Whether the Video Tiling tab should be shown.

    Returns ``True`` unless a ``no_tiling.flag`` marker file sits in the
    install ``{app}`` directory (see :func:`resolve_app_dir`). The installer
    creates that marker unless the user opts in to the "Video Tiling"
    task (excluded by default since 2026-08-15).

    Any filesystem error is swallowed and treated as "enabled" so a quirky
    path / permission problem can never block app startup — the feature
    simply stays on, which is the safe default.
    """
    try:
        return not (resolve_app_dir() / NO_TILING_MARKER).exists()
    except OSError:
        return True



# Marker file the Standard installer drops into the {app} directory
# unless the user ticks "Install the Clone Your Voice / Text to Voice
# feature" at install time (opt-in, off by default). Its mere presence
# disables the in-app Clone Your Voice tab; it is never written by the
# app itself. In a source / dev checkout the repo root won't contain
# it, so the tab stays on for developers. Independent of
# NO_TILING_MARKER above — the two features are unrelated and toggled
# separately.
NO_VOICE_CLONE_MARKER = "no_voice_clone.flag"


def voice_clone_tab_enabled() -> bool:
    """Whether the Clone Your Voice tab should be shown.

    Returns ``True`` unless a ``no_voice_clone.flag`` marker file sits in
    the install ``{app}`` directory (see :func:`resolve_app_dir`). The
    installer creates that marker unless the user opts in to the
    "Clone Your Voice" task at install time. The feature itself stays
    fully optional even when the tab is shown: it downloads its speech
    model on demand (see ``core.optional_deps``, feature "voice_clone")
    the first time it is actually used, not at install or tab-build time.

    Any filesystem error is swallowed and treated as "enabled" so a quirky
    path / permission problem can never block app startup — the feature
    simply stays on, which is the safe default (mirrors
    :func:`tiling_tab_enabled`).
    """
    try:
        return not (resolve_app_dir() / NO_VOICE_CLONE_MARKER).exists()
    except OSError:
        return True


def default_hub_folder() -> Path:
    """The pre-filled value the first-run dialog shows.

    Returns ``user_cache_dir() / "models"`` —
    ``%LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\models`` on Windows. This is
    always writable by the current user, so the first-run model
    download cannot fail with "Access is denied" the way an
    ``<app_dir>/hub`` default did under a Program Files install. It is
    also the SAME folder ``model_folder_for`` falls back to when no hub
    is configured, so an existing ``Cache/models`` model is reused rather
    than re-downloaded.

    We reuse ``core.config.user_cache_dir`` (the single platformdirs
    wrapper, ``appname=WhisperTranscriberSuite`` / ``appauthor=False``) so the
    hub stays consistent with every other cache path in the app.
    """
    from .config import user_cache_dir  # local import avoids a cycle
    return user_cache_dir() / HUB_SUBFOLDER_NAME


def is_hub_configured(config: dict[str, Any]) -> bool:
    """True iff the user has picked (or migrated to) a real hub folder.

    "Configured" is intentionally permissive: as long as ``hub_folder``
    is a non-empty string, we treat the choice as made. The folder
    itself can be missing — the model-download flow creates it lazily.
    Empty-string / missing key → False (first-run dialog should fire).
    """
    value = (config.get("hub_folder") or "").strip()
    return bool(value)


def normalise_hub_path(raw: str | Path) -> str:
    """Trim + absolutize a user-typed path string.

    Empty input maps to the default. We return the user-facing string
    representation rather than a Path so the caller can write it back
    to JSON without a custom serialiser.
    """
    if not raw:
        return str(default_hub_folder())
    return str(Path(str(raw).strip()).expanduser().resolve())


def is_safe_model_folder_name(name: object) -> bool:
    """True when ``name`` is usable as a single model-folder component.

    ``model_name`` values reach :func:`model_folder_for` from the local
    config AND from the online-augmentable model catalog
    (``config["model_catalog"]``, see ``core.model_manager``). A name is
    only ever a folder slug (``faster-whisper-large-v3``,
    ``models--Systran--x``, ...), so anything that could steer the
    composed path outside the hub — separators, ``.``/``..`` components,
    a drive-relative form on Windows like ``C:evil``, NUL — is rejected.
    Without this, a compromised / MITM'd online catalog entry could set
    ``name`` to e.g. ``../../Documents`` and make the model download flow
    delete/overwrite that folder (the zip-slip guard only protects the
    archive's *members*, not the destination path).

    Spaces and other plain characters stay valid: only path structure is
    checked, never content.
    """
    if not isinstance(name, str):
        return False
    stripped = name.strip()
    if not stripped or stripped in (".", ".."):
        return False
    if "/" in stripped or "\\" in stripped or "\x00" in stripped:
        return False
    # On Windows, ``Path("C:evil").name`` is "evil" and ``Path("a:b")``
    # is a drive-relative / alternate-data-stream form; on POSIX those
    # are ordinary file names, so compare with the running platform's
    # own parser (same one used to compose the path below).
    return Path(stripped).name == stripped


def model_folder_for(
    hub_folder: str | Path | None,
    model_name: str,
) -> Path:
    """Compose the per-model directory inside a hub.

    ``model_name`` is the ``models--Vendor--name`` slug used by the
    existing cache layout — see ``DEFAULT_CONFIG["model"]["name"]``
    and ``MODEL_REGISTRY`` entries. When the slug already starts with
    ``models--``, it's used verbatim; otherwise we prepend
    ``models--Systran--`` to keep parity with the original cache
    convention.

    Raises ``ValueError`` for a non-string / empty name, and also for a
    name that is not a single safe folder component (see
    :func:`is_safe_model_folder_name`) — callers guard against
    ``ValueError`` and fall back to a clean default.
    """
    if not hub_folder:
        from .config import user_cache_dir
        hub = user_cache_dir() / "models"
    else:
        hub = Path(str(hub_folder))
    # ``model_name`` is typed ``str``, but a None / non-string can still
    # reach here from a hand-edited or externally-produced config (e.g.
    # ``{"model": {"name": null}}`` on macOS), and the online model
    # catalog can supply an arbitrary string. ``None.strip()`` would
    # raise an uncaught AttributeError and crash launch; a traversal
    # name (``../../x``) would resolve outside the hub. Coerce both bad
    # cases into the same clean ValueError the callers already handle.
    if not is_safe_model_folder_name(model_name):
        raise ValueError(
            "model_name must be a non-empty, single-folder name"
        )
    name = model_name.strip()
    if not name.startswith("models--"):
        name = f"models--Systran--{name}"
    return hub / name


def is_path_inside(child: str | Path, parent: str | Path) -> bool:
    """True when ``child`` is at or below ``parent`` in the filesystem.

    Used by both the installer-side Pascal Script (via mirroring the
    same logic in NSI / Inno) AND by tests. Returns False on any
    filesystem error so an unreadable path never tricks the
    uninstaller into thinking it's "inside" and skip the prompt.
    """
    try:
        c = Path(str(child)).resolve()
        p = Path(str(parent)).resolve()
    except (OSError, ValueError):
        return False
    try:
        c.relative_to(p)
        return True
    except ValueError:
        return False


def derive_hub_from_model_path(model_path: str) -> str:
    """Reverse-derive the hub folder from a legacy ``model_path``.

    The legacy layout is ``<hub>/models--Systran--<name>/``. Walking
    one parent up gives us the hub. We return the directory as a
    string for JSON serialisation; callers that need it as a Path
    can wrap it themselves.

    Returns an empty string when the input doesn't look like a
    model directory (no parent, blank, etc.) so the caller can fall
    back to the default cleanly.
    """
    raw = (model_path or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if not p.name.startswith("models--"):
        # Looks like a hub already — don't double-strip.
        return str(p)
    parent = p.parent
    if str(parent) in (".", ""):
        return ""
    return str(parent)
