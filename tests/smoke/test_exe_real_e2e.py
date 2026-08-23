"""Real end-to-end test of the COMPILED exe.

Spawns ``WhisperProject.exe --worker``, sends the actual JSON
``transcribe`` command, and asserts an SRT + JSON land next to the input.
This is the only way to catch PyInstaller packaging bugs (missing data
files, hidden imports). Cf. tests/smoke/README.md for the Session 8
silero_vad_v6.onnx incident that motivated this test.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _ready_or_error(proc: subprocess.Popen[str], deadline_s: float = 180.0) -> None:
    """Drain stdout until a 'ready' event or fail."""
    start = time.time()
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            raise RuntimeError(f"worker died before ready, rc={proc.poll()}")
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        evt = ev.get("event")
        if evt == "ready":
            return
        if evt == "startup_error":
            raise RuntimeError(f"startup_error: {ev.get('message','')}")
        if time.time() - start > deadline_s:
            raise TimeoutError(f"ready event not seen in {deadline_s}s")


def _drain_until_done(
    proc: subprocess.Popen[str], deadline_s: float = 600.0
) -> tuple[bool, str | None, dict | None]:
    """Drain stdout until 'done' or 'error', returning (done, err, summary)."""
    start = time.time()
    summary = {"language": None, "progress_max": 0}
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            return False, f"worker died before done, rc={proc.poll()}", summary
        try:
            ev = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        evt = ev.get("event")
        if evt == "done":
            return True, None, summary
        if evt == "error":
            return False, ev.get("message", "worker error"), summary
        if evt == "language_detected":
            summary["language"] = ev.get("language")
        if evt == "progress":
            summary["progress_max"] = max(summary["progress_max"], ev.get("percent", 0))
        if time.time() - start > deadline_s:
            return False, f"transcription did not finish in {deadline_s}s", summary


def _build_worker_argv(exe_path: Path, gui_script: Path | None) -> list[str]:
    """Two flavours of worker launch:

      * Methods A and B — ``[exe, "--worker"]`` against the frozen exe.
      * Method C       — ``[pythonw, gui.py, "--worker"]`` against the
        embeddable Python interpreter shipped by installer_embed.iss.
    """
    if gui_script is not None:
        return [str(exe_path), str(gui_script), "--worker"]
    return [str(exe_path), "--worker"]


def _worker_cwd(exe_path: Path, gui_script: Path | None) -> str:
    """Worker spawns relative imports from cwd. Method C needs the
    install root (where gui.py / app / core sit); the frozen exes are
    self-contained so the cwd is just the exe's directory."""
    if gui_script is not None:
        return str(gui_script.parent)
    return str(exe_path.parent)


def test_exe_worker_transcribes_real_video(
    exe_path: Path, model_dir: Path, test_video: Path, gui_script: Path | None
) -> None:
    """The compiled exe's worker mode transcribes a real file end-to-end.

    Failure mode this guards against: PyInstaller drops a runtime-loaded
    asset (Silero VAD ONNX, ctranslate2 DLL, tokenizer vocab) and the exe
    crashes when the user hits 'Transcribe'. Source-side tests don't see
    this because they read the asset from site-packages, not the bundle.

    When ``gui_script`` is set (Method C — embeddable Python install),
    the worker is invoked as ``[pythonw, gui.py, "--worker"]`` instead.
    """
    srt = test_video.with_suffix(".srt")
    js = test_video.with_suffix(".json")
    for p in (srt, js):
        if p.exists():
            p.unlink()

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        _build_worker_argv(exe_path, gui_script),
        cwd=_worker_cwd(exe_path, gui_script),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags,
        bufsize=1,
    )

    try:
        _ready_or_error(proc)

        assert proc.stdin is not None
        # Explicit output_formats -- otherwise the worker falls back to
        # whatever this machine's REAL config.json has configured (a
        # real run on a real dev machine can easily have that set to
        # docx/txt instead of srt/json), and the asserts below would fail
        # on a perfectly healthy build for a reason unrelated to packaging.
        proc.stdin.write(json.dumps({
            "action": "transcribe",
            "file_path": str(test_video),
            "output_formats": ["srt", "json"],
        }) + "\n")
        proc.stdin.flush()

        done, err, summary = _drain_until_done(proc)
        assert done, f"transcription failed: {err}  (summary={summary})"

        assert srt.exists() and srt.stat().st_size > 0, f"SRT missing/empty: {srt}"
        assert js.exists() and js.stat().st_size > 0, f"JSON missing/empty: {js}"
        # Spot-check SRT structure
        text = srt.read_text(encoding="utf-8")
        assert "-->" in text, "SRT does not contain timestamp arrows"
        assert summary["progress_max"] >= 90, f"progress capped at {summary['progress_max']}%"
    finally:
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()


def test_exe_size_within_expected_range(exe_path: Path, gui_script: Path | None) -> None:
    """The onefile exe carries ffmpeg + ffprobe + yt-dlp + faster_whisper
    deps + Python runtime + Tk + Silero VAD onnx. Anything under 150 MB
    is missing something major; over 400 MB means upstream wheels
    got fat and we should investigate before shipping.

    Skipped for Method B (onedir layout — exe is a thin launcher with
    sibling DLLs and bin/) and Method C (exe_path is pythonw.exe).
    Both modes have their own bundle-size verifications via the
    installer's [Files] block and the release-notes table.
    """
    if gui_script is not None:
        pytest.skip("size check is meaningful only for the onefile exe (Method A)")
    if (exe_path.parent / "bin").is_dir():
        pytest.skip("onedir layout — sibling bin/ present; size check applies to Method A only")
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    assert 150 <= size_mb <= 400, f"unexpected exe size: {size_mb:.1f} MB"


def test_exe_boots_and_loads_bundle(
    exe_path: Path, model_dir: Path, gui_script: Path | None
) -> None:
    """Spawn the worker and wait for the 'ready' event.

    Reaching 'ready' means PyInstaller successfully extracted every
    bundled asset (Silero VAD onnx, ffmpeg/ffprobe in bin/, Tk, the
    ctranslate2 DLLs) **and** the worker imported every module and
    loaded the Whisper model. The Method C variant verifies the
    embeddable Python tree has every dependency on disk under
    ``Lib\\site-packages\\``.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        _build_worker_argv(exe_path, gui_script),
        cwd=_worker_cwd(exe_path, gui_script),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags,
        bufsize=1,
    )
    try:
        _ready_or_error(proc, deadline_s=300.0)
    finally:
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()
