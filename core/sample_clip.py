"""The bundled "Try it now" sample clip.

A short public-domain spoken clip (``assets/sample_clip.mp3``, credit in
``docs/SAMPLE_CLIP.md``) that a new user can transcribe with one click before they have a
file of their own. The install folder can be read-only (Program Files), and a transcript is
written next to its source file, so the clip is copied to the user data folder first.
"""
from __future__ import annotations

import logging
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from core.config import user_data_dir

logger = logging.getLogger(__name__)

SAMPLE_CLIP_NAME = "sample_clip.mp3"
# The clip is a recording of English speech; naming the language skips detection.
SAMPLE_CLIP_LANGUAGE = "en"


def _candidate_dirs() -> list[Path]:
    """Folders that may hold ``assets/``: next to the frozen exe, the PyInstaller data
    folder, then the source tree."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(os.path.abspath(sys.executable)).parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            dirs.append(Path(meipass))
    dirs.append(Path(__file__).resolve().parent.parent)
    return dirs


def bundled_clip_path() -> str | None:
    """Path of the clip shipped with the app, or None when this install lacks it."""
    for base in _candidate_dirs():
        candidate = base / "assets" / SAMPLE_CLIP_NAME
        if candidate.is_file():
            return str(candidate)
    return None


def samples_dir() -> Path:
    return user_data_dir() / "samples"


def prepare_working_copy() -> str | None:
    """Copy the clip into the user data folder and return that path.

    Returns None when the clip is missing from the install; raises ``OSError`` when the
    copy cannot be written. An up-to-date copy (same contents) is reused, so the transcripts
    next to it survive from one run to the next.
    """
    source = bundled_clip_path()
    if source is None:
        logger.warning("Sample clip %s is not in this install", SAMPLE_CLIP_NAME)
        return None
    folder = samples_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / SAMPLE_CLIP_NAME
    matches = False
    if target.is_file() and target.stat().st_size == os.path.getsize(source):
        with open(source, "rb") as bundled, target.open("rb") as existing:
            matches = (hashlib.file_digest(bundled, "sha256").digest()
                       == hashlib.file_digest(existing, "sha256").digest())
    if not matches:
        from core._checkpoint import _strict_sync

        fd, staging = tempfile.mkstemp(prefix=".sample-", suffix=".part", dir=folder)
        try:
            with os.fdopen(fd, "r+b") as copied:
                shutil.copyfile(source, staging)
                _strict_sync(copied)
            os.replace(staging, target)
            staging = None
        finally:
            if staging is not None:
                try:
                    os.unlink(staging)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.exception("Could not remove staged sample clip")
    return str(target)
