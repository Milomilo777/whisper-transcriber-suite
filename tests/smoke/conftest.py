"""Shared fixtures + skip-guards for the smoke suite.

Smoke tests need real local resources (the Whisper model, a video file,
optionally the compiled exe). On any machine missing those, the test
politely skips instead of failing — so the unit suite can still run
hermetically.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_VIDEO = Path(
    "E:\\3224 NWN Master\u2019s Inner Peace Talks, July 29, 2026 e2 (720p)_0002.mp4"
)
DEFAULT_MODEL_PARENT = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    / "WhisperTranscriberSuite" / "Cache" / "models"
)
DEFAULT_MODEL_DIR = DEFAULT_MODEL_PARENT / "models--Systran--faster-whisper-large-v3"
DEFAULT_EXE = REPO_ROOT / "dist" / "WhisperTranscriberSuite.exe"


@pytest.fixture(scope="session")
def test_video() -> Path:
    """Path to a real audio/video file. Override via $WHISPER_SMOKE_VIDEO."""
    p = Path(os.environ.get("WHISPER_SMOKE_VIDEO", str(DEFAULT_VIDEO)))
    if not p.exists():
        pytest.skip(f"test video not present: {p}")
    return p


@pytest.fixture(scope="session")
def model_dir() -> Path:
    """Local faster-whisper model folder."""
    p = Path(os.environ.get("WHISPER_SMOKE_MODEL", str(DEFAULT_MODEL_DIR)))
    if not p.exists() or not (p / "model.bin").exists():
        pytest.skip(f"local model not present: {p}")
    return p


@pytest.fixture(scope="session")
def exe_path() -> Path:
    """Worker launcher under test.

    Two flavours, picked by environment variable:

      * Methods A and B ship a frozen PyInstaller exe. The fixture
        returns the exe path; the e2e test then spawns
        ``[exe, "--worker"]``.

      * Method C ships an embeddable Python interpreter plus a
        gui.py entry. Set both ``$WHISPER_SMOKE_EXE`` (to the
        pythonw.exe path) and ``$WHISPER_SMOKE_GUI`` (to the gui.py
        path). The e2e test detects the GUI env var and spawns
        ``[pythonw, gui.py, "--worker"]`` instead.

    Override the default with ``$WHISPER_SMOKE_EXE``.
    """
    p = Path(os.environ.get("WHISPER_SMOKE_EXE", str(DEFAULT_EXE)))
    if not p.exists():
        pytest.skip(f"worker launcher not present: {p}  (run build.bat / installer)")
    return p


@pytest.fixture(scope="session")
def gui_script() -> Path | None:
    """Optional ``gui.py`` companion for Method C builds.

    Returns the path when ``$WHISPER_SMOKE_GUI`` is set and the file
    exists; otherwise ``None``. The frozen-exe flow ignores this.
    """
    raw = os.environ.get("WHISPER_SMOKE_GUI", "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.exists():
        pytest.skip(f"gui.py launcher not present: {p}")
    return p


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
