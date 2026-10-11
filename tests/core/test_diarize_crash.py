"""Issue #7: a native diarisation crash must not lose the finished transcript.

sherpa-onnx crashed the process when an older onnxruntime.dll (a foreign
1.17.1) was already loaded. Diarisation now runs in its own worker process
(core/diarization_worker.py) and the transcript is saved as a completed
checkpoint before the post steps. The worker tests below start a REAL child
process (a small stand-in script) so pipes, exit codes, timeouts and kills are
exercised for real; only the speaker model itself is left out.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from typing import Any

import pytest

from core import diarization
from tests.core.test_loop_guard_transcriber import (  # noqa: F401 - `t` is a fixture
    Engine,
    Seg,
    _wire,
    _write_prior_checkpoint,
    t,
)


@pytest.fixture
def fake_worker(monkeypatch, tmp_path):
    """Make diarize() start a stand-in worker that runs ``body`` (Python code)."""
    started: list[Any] = []
    real_popen = diarization.subprocess.Popen

    def spy_popen(*a, **k):
        p = real_popen(*a, **k)
        started.append(p)
        return p

    monkeypatch.setattr(diarization, "availability_reason", lambda: "")
    monkeypatch.setattr("core.transcriber.get_duration", lambda p: 10.0)
    monkeypatch.setattr(diarization.subprocess, "Popen", spy_popen)

    def use(body: str) -> list[Any]:
        script = tmp_path / "worker_stub.py"
        script.write_text(
            "import json, os, sys, time\n"
            "def emit(ev):\n"
            "    sys.stdout.write(json.dumps(ev) + '\\n'); sys.stdout.flush()\n"
            "request = json.loads(sys.stdin.readline())\n"
            + textwrap.dedent(body),
            encoding="utf-8",
        )
        monkeypatch.setattr(diarization, "_worker_command", lambda: [sys.executable, "-u", str(script)])
        return started

    return use


def _dead(proc: Any, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


def test_worker_result_and_progress_reach_the_caller(fake_worker):
    fake_worker("""
        emit({"event": "progress", "fraction": 0.5})
        print("native library chatter on stdout")
        emit({"event": "progress", "fraction": 1.0})
        emit({"event": "done", "segments": [
            {"start": 0.0, "end": 1.5, "speaker": "Speaker 00"},
            {"start": 1.5, "end": 3.0, "speaker": "گوینده 01 / 話者"}]})
    """)
    seen: list[float] = []

    segs = diarization.diarize("talk.wav", progress_cb=seen.append)

    assert [(s.start, s.end, s.speaker) for s in segs] == [
        (0.0, 1.5, "Speaker 00"), (1.5, 3.0, "گوینده 01 / 話者")]
    assert seen == [0.5, 1.0]


def test_request_reaches_the_worker(fake_worker, tmp_path):
    echo = tmp_path / "request.json"
    fake_worker(f"""
        open({str(echo)!r}, "w", encoding="utf-8").write(json.dumps(request))
        emit({{"event": "done", "segments": []}})
    """)

    assert diarization.diarize("ü ö/talk.wav", num_speakers=3, cluster_threshold=0.7) == []
    assert json.loads(echo.read_text(encoding="utf-8")) == {
        "audio_path": "ü ö/talk.wav", "num_speakers": 3, "cluster_threshold": 0.7}


def test_native_crash_becomes_a_readable_error(fake_worker):
    fake_worker("""
        sys.stderr.write("The requested API version [24] is not available, only API "
                         "versions [1, 17] are supported in this build.\\n")
        sys.stderr.flush()
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.ExitProcess(0xC0000005)  # access violation
        os.abort()
    """)

    with pytest.raises(diarization.DiarizationUnavailable) as exc:
        diarization.diarize("talk.wav")

    assert "crashed" in str(exc.value)
    assert "older onnxruntime.dll" in str(exc.value)


def test_plain_failure_exit_reports_stderr(fake_worker):
    fake_worker("""
        sys.stderr.write("model file is corrupt\\n")
        sys.exit(1)
    """)

    with pytest.raises(diarization.DiarizationUnavailable, match="exited with code 1: model file is corrupt"):
        diarization.diarize("talk.wav")


def test_error_event_is_raised_and_the_worker_stopped(fake_worker):
    started = fake_worker("""
        emit({"event": "error", "error": "decoded audio is empty"})
        time.sleep(30)
    """)

    with pytest.raises(diarization.DiarizationUnavailable, match="decoded audio is empty"):
        diarization.diarize("talk.wav")

    assert _dead(started[-1])


def test_stalled_worker_is_killed(fake_worker, monkeypatch):
    started = fake_worker("""
        emit({"event": "progress", "fraction": 0.1})
        time.sleep(60)
    """)
    monkeypatch.setattr(diarization, "WORKER_STALL_TIMEOUT_S", 1.0)

    t0 = time.monotonic()
    with pytest.raises(diarization.DiarizationUnavailable, match="no progress"):
        diarization.diarize("talk.wav")

    assert time.monotonic() - t0 < 20
    assert _dead(started[-1])


def test_overall_limit_stops_a_worker_that_keeps_talking(fake_worker, monkeypatch):
    started = fake_worker("""
        while True:
            emit({"event": "progress", "fraction": 0.2})
            time.sleep(0.05)
    """)
    monkeypatch.setattr(diarization, "WORKER_MIN_TIMEOUT_S", 1.0)
    monkeypatch.setattr("core.transcriber.get_duration", lambda p: 0.1)

    with pytest.raises(diarization.DiarizationUnavailable, match="took longer than"):
        diarization.diarize("talk.wav")

    assert _dead(started[-1])


def test_overall_limit_grows_with_the_audio_length(fake_worker, monkeypatch):
    fake_worker("""
        for _ in range(30):
            emit({"event": "progress", "fraction": 0.2})
            time.sleep(0.05)
        emit({"event": "done", "segments": []})
    """)
    monkeypatch.setattr(diarization, "WORKER_MIN_TIMEOUT_S", 0.5)
    monkeypatch.setattr("core.transcriber.get_duration", lambda p: 3600.0)

    assert diarization.diarize("talk.wav") == []


def test_unreadable_duration_still_runs(fake_worker, monkeypatch):
    fake_worker("""
        emit({"event": "done", "segments": []})
    """)

    def broken(_path):
        raise RuntimeError("ffprobe failed")

    monkeypatch.setattr("core.transcriber.get_duration", broken)

    assert diarization.diarize("talk.wav") == []


def test_cancel_stops_the_worker(fake_worker):
    started = fake_worker("""
        emit({"event": "progress", "fraction": 0.1})
        time.sleep(60)
    """)
    t0 = time.monotonic()

    assert diarization.diarize("talk.wav", cancelled=lambda: time.monotonic() - t0 > 0.5) == []

    assert time.monotonic() - t0 < 15
    assert _dead(started[-1])


def test_worker_command_matches_the_build_kind(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert diarization._worker_command() == [sys.executable, "--diarize-worker"]
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert diarization._worker_command() == [sys.executable, "-u", "-m", "core.diarization_worker"]


def test_gui_hands_the_flag_to_the_worker():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "gui.py"), encoding="utf-8") as f:
        gui = f.read()
    assert '"--diarize-worker" in sys.argv' in gui
    for spec in ("whisper_project_onedir.spec", "whisper_project_onefile.spec",
                 os.path.join("platform", "macos", "pyinstaller", "whisper_project_mac.spec")):
        with open(os.path.join(root, spec), encoding="utf-8") as f:
            assert "'core.diarization_worker'" in f.read(), spec


# --- the worker module itself -------------------------------------------------

def _run_worker_main(monkeypatch, capsys, request: str) -> tuple[int, list[dict[str, Any]]]:
    import io

    from core import diarization_worker

    monkeypatch.setattr(sys, "stdin", io.StringIO(request))
    rc = diarization_worker.main()
    out = capsys.readouterr().out
    return rc, [json.loads(line) for line in out.splitlines() if line.strip()]


def test_worker_main_reports_segments(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", object())

    def fake_impl(path, *, num_speakers, cluster_threshold, progress_cb):
        assert (path, num_speakers, cluster_threshold) == ("a.wav", 2, 0.4)
        progress_cb(0.5)
        return [diarization.DiarSegment(0.0, 1.0, "Speaker 00")]

    monkeypatch.setattr(diarization, "_diarize_impl", fake_impl)

    rc, events = _run_worker_main(
        monkeypatch, capsys, '{"audio_path": "a.wav", "num_speakers": 2, "cluster_threshold": 0.4}\n')

    assert rc == 0
    assert events == [{"event": "progress", "fraction": 0.5},
                      {"event": "done", "segments": [{"start": 0.0, "end": 1.0, "speaker": "Speaker 00"}]}]


def test_worker_main_reports_a_missing_package(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)  # makes the import fail

    rc, events = _run_worker_main(monkeypatch, capsys, '{"audio_path": "a.wav"}\n')

    assert rc == 1
    assert events[0]["event"] == "error" and "sherpa-onnx" in events[0]["error"]


def test_worker_main_reports_a_failed_run(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", object())

    def broken(*a, **k):
        raise diarization.DiarizationUnavailable("decoded audio is empty")

    monkeypatch.setattr(diarization, "_diarize_impl", broken)

    rc, events = _run_worker_main(monkeypatch, capsys, '{"audio_path": "a.wav"}\n')

    assert rc == 1
    assert events == [{"event": "error", "error": "decoded audio is empty"}]


# --- transcriber: save first, resume the post steps ------------------------------

def test_transcript_is_saved_as_complete_before_the_post_steps(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    _slices, written = _wire(t, monkeypatch, tmp_path, Engine([Seg(0, 2, "one"), Seg(2, 4, "two")]))
    at_post: list[Any] = []

    def post(task, segs, lang, log_cb, progress_cb):
        at_post.append(_checkpoint.load_checkpoint(str(audio)))
        return 0

    monkeypatch.setattr(t, "_run_post_pipeline", post)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    saved = at_post[0]
    assert saved is not None and saved["transcription_completed"] is True
    assert [s["text"] for s in saved["segments"]] == ["one", "two"]
    assert [s["text"] for s in written["segs"]] == ["one", "two"]
    assert _checkpoint.load_checkpoint(str(audio)) is None  # outputs written -> checkpoint dropped


def test_cancel_in_the_post_steps_keeps_the_checkpoint_complete(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    _slices, written = _wire(t, monkeypatch, tmp_path, Engine([Seg(0, 2, "one")]))
    task = TranscriptionTask(str(audio))

    def post(task_, *a, **k):
        task_.cancelled = True
        return 0

    monkeypatch.setattr(t, "_run_post_pipeline", post)

    t.transcribe(task, lambda p: None, lambda m: None)

    data = _checkpoint.load_checkpoint(str(audio))
    assert written == {}
    assert data is not None and data["transcription_completed"] is True


def test_resume_of_a_complete_transcript_only_redoes_the_post_steps(t, monkeypatch, tmp_path):
    from core import _checkpoint

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    done = [{"start": 0.0, "end": 2.0, "text": "one"}, {"start": 2.0, "end": 4.0, "text": "two"}]
    task = _write_prior_checkpoint(t, audio, done, 4.0)
    data = _checkpoint.load_checkpoint(str(audio))
    assert data is not None
    data["transcription_completed"] = True
    _checkpoint.checkpoint_path(str(audio)).write_text(json.dumps(data), encoding="utf-8")
    engine = Engine()  # any decode call would pop from an empty list and fail
    _slices, written = _wire(t, monkeypatch, tmp_path, engine)
    post: list[list[str]] = []
    monkeypatch.setattr(t, "_run_post_pipeline",
                        lambda task_, segs, *a, **k: post.append([s["text"] for s in segs]) or 2)
    logs: list[str] = []

    assert t.resume_transcription(task, lambda p: None, logs.append) is True

    assert engine.calls == []
    assert post == [["one", "two"]]
    assert [s["text"] for s in written["segs"]] == ["one", "two"]
    assert _checkpoint.load_checkpoint(str(audio)) is None
    assert any("already complete" in m for m in logs)


def test_resumed_tail_is_saved_as_complete_and_cancel_keeps_it(t, monkeypatch, tmp_path):
    from core import _checkpoint

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    task = _write_prior_checkpoint(t, audio, [{"start": 0.0, "end": 100.0, "text": "first"}], 100.0)
    _slices, written = _wire(t, monkeypatch, tmp_path, Engine([Seg(0, 5, "second")]))

    def post(task_, *a, **k):
        task_.cancelled = True
        return 0

    monkeypatch.setattr(t, "_run_post_pipeline", post)

    assert t.resume_transcription(task, lambda p: None, lambda m: None) is True

    data = _checkpoint.load_checkpoint(str(audio))
    assert written == {}
    assert data is not None and data["transcription_completed"] is True
    assert [s["text"] for s in data["segments"]] == ["first", "second"]


def test_post_pipeline_passes_cancel_and_survives_a_failure(monkeypatch):
    from core import transcriber
    from core.task import TranscriptionTask

    task = TranscriptionTask("talk.wav")
    seen: dict[str, Any] = {}

    def failing(path, **kwargs):
        seen.update(kwargs)
        raise diarization.DiarizationUnavailable("Speaker detection crashed (exit code 3221225477)")

    monkeypatch.setitem(transcriber.config, "diarization_enabled", True)
    monkeypatch.setitem(transcriber.config, "alignment_enabled", False)
    monkeypatch.setattr(diarization, "is_available", lambda: True)
    monkeypatch.setattr(diarization, "diarize", failing)
    logs: list[str] = []

    speakers = transcriber._run_post_pipeline(task, [{"start": 0.0, "end": 1.0, "text": "x"}], "en", logs.append)

    assert speakers == 0
    assert seen["cancelled"]() is False
    task.cancelled = True
    assert seen["cancelled"]() is True
    assert any("Speaker detection failed" in m and "without speaker labels" in m for m in logs)


# --- diagnostics -------------------------------------------------------------------

def test_diagnostics_have_an_onnx_runtime_section():
    from core import hardware

    report = hardware.diagnostics_report()

    assert "-- ONNX Runtime --" in report
    assert "onnxruntime package:" in report


@pytest.mark.skipif(sys.platform != "win32", reason="module listing is Windows-only")
def test_diagnostics_list_the_loaded_onnx_runtime_modules_on_windows():
    import onnxruntime  # noqa: F401 - loads the package's native module

    from core import hardware

    report = hardware.diagnostics_report()

    assert "Loaded ONNX Runtime modules in this process:" in report
    assert "System32 onnxruntime.dll:" in report
