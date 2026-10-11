import pytest
import os
from pathlib import Path
from types import SimpleNamespace

from app.services.transcription_service import TranscriptionService
from app.services.download_service import DownloadService
from app.domain.tasks import VideoDownloadTask
from core.server.jobs import JobManager, Job
from core.transcriber import _write_outputs
from core.task import TranscriptionTask
from core.backends.base import LanguageInfo

def test_download_ui_worker_db_error_swallowed(tmp_path):
    class DummyHistory:
        def finish_download(self, *args, **kwargs):
            raise Exception("DB error!")

    app = SimpleNamespace(
        history=DummyHistory(),
        app_config={},
        download_queue=[],
        download_current=None,
        log_threadsafe=lambda *args: None,
        log=lambda *args: None,
    )
    svc = DownloadService(app)
    task = VideoDownloadTask("url", "folder", "format", {})
    task.status = "running"
    task.history_id = 1

    svc._finish_history(task, "finished", [])
    # Reaches here safely
    assert task.status == "running" # We don't mutate status in _finish_history

def test_http_server_job_completion_db_error(tmp_path):
    class DummyHistory:
        def finish_transcription(self, *args, **kwargs):
            raise Exception("DB error!")
        def close(self):
            pass

    mgr = JobManager(lambda *args: None, jobs_root=str(tmp_path / "jobs"), outputs_root=str(tmp_path / "outputs"), max_jobs=2, record_history=True)
    job = Job(job_id="test_job", kind="upload", formats=["txt"])
    job.language = "en"
    job.work_dir = str(tmp_path / "jobs" / "test_job")
    os.makedirs(job.work_dir, exist_ok=True)
    job.media_path = str(Path(job.work_dir) / "media.mp4")

    # Create media file
    Path(job.media_path).touch()

    # Create a dummy output file in work_dir
    out_file = Path(job.work_dir) / "output.txt"
    out_file.touch()
    job.outputs = [("txt", str(out_file))]

    mgr._settle(job, "finished", DummyHistory(), 1, 0.0, "en")

    assert job.status == "finished"
    assert not Path(job.media_path).exists(), "Input media should be removed"
    # Output is COPIED, not moved from work_dir, until eviction!
    assert out_file.exists(), "Output is copied, not moved"
    assert os.path.exists(os.path.join(mgr._outputs_root, job.job_id[:12], "output.txt")), "Output should be copied to outputs_root"

def test_writer_crash_disk_full(tmp_path, monkeypatch):
    base = str(tmp_path / "base")
    def mock_replace(src, dst):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr("core.transcriber.os.replace", mock_replace)

    with pytest.raises(RuntimeError) as exc_info:
        _write_outputs(base, [], "dummy.mp4", formats=["srt"])

    assert "srt: [Errno 28] No space left on device" in str(exc_info.value)
    # Check that .part file was removed
    assert not os.path.exists(f"{base}.srt.part")
    # Actually, the part file name has pid and thread id, let's just check no part files exist
    assert not list(tmp_path.glob("*.part"))

def test_worker_crash_after_last_segment(tmp_path, monkeypatch):
    import core.transcriber
    from core import _checkpoint
    class FakeBackend:
        def transcribe_to_segments(self, *args, **kwargs):
            return [{"start": 0.0, "end": 1.0, "text": "Hello"}], LanguageInfo("en")

    monkeypatch.setattr(core.transcriber, "_get_alt_backend", lambda *a: FakeBackend())
    monkeypatch.setattr(core.transcriber, "_maybe_denoise", lambda a, **k: (a, None))
    monkeypatch.setattr(core.transcriber, "get_duration", lambda a: 10.0)
    monkeypatch.setattr(core.transcriber, "require_audio_stream", lambda a: None)

    def mock_post_pipeline(*args, **kwargs):
        raise RuntimeError("Crash during diarisation")

    monkeypatch.setattr(core.transcriber, "_run_post_pipeline", mock_post_pipeline)

    file_path = tmp_path / "test.mp4"
    file_path.touch()
    task = TranscriptionTask(str(file_path))
    task.output_formats = []

    with pytest.raises(RuntimeError, match="Crash during diarisation"):
        core.transcriber._transcribe_via_alt_backend("faster_whisper", task, None, None, None)

    cp = _checkpoint.load_checkpoint(str(file_path))
    assert cp is not None

def test_are_outputs_complete_handles_windows_permission_error(tmp_path, monkeypatch):
    app = SimpleNamespace(app_config={"output_formats": ["srt"]})
    svc = TranscriptionService(app)

    file_path = tmp_path / "clip.mp4"
    file_path.touch()
    out_path = tmp_path / "clip.srt"
    out_path.write_text("hello")
    task = SimpleNamespace(
        file_path=str(file_path),
        start_time=0.0
    )

    def mock_getsize(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os.path, "getsize", mock_getsize)

    assert svc._are_outputs_complete(task) is False

def test_are_outputs_complete_handles_macos_nfd(tmp_path):
    import unicodedata

    # NFD string: e + acute accent
    nfd_name = "cl" + "é" + "p.srt"
    nfc_name = unicodedata.normalize('NFC', "cl" + "é" + "p.mp4")

    # Create the output with the NFD spelling
    out_path = tmp_path / nfd_name
    out_path.write_text("hello")

    # Skip if filesystem auto-normalizes
    if (tmp_path / nfc_name.replace('.mp4', '.srt')).exists():
        pytest.skip("Filesystem does not preserve NFD distinctions (skip on non-macOS/APFS)")

    app = SimpleNamespace(app_config={"output_formats": ["srt"]})
    svc = TranscriptionService(app)

    task = SimpleNamespace(
        file_path=str(tmp_path / nfc_name),
        start_time=0.0
    )

    assert svc._are_outputs_complete(task) is True

def test_are_outputs_complete_format_list_fallback(tmp_path):
    app = SimpleNamespace(app_config={"output_formats": ["srt"]})
    svc = TranscriptionService(app)

    file_path = tmp_path / "clip.mp4"
    file_path.touch()
    out_path = tmp_path / "clip.srt"
    out_path.write_text("hello")

    # Task has explicit output_formats that include json, but json is missing
    task = SimpleNamespace(
        file_path=str(file_path),
        output_formats=["srt", "json"],
        start_time=0.0
    )
    assert svc._are_outputs_complete(task) is False

def test_are_outputs_complete_stale_files(tmp_path):
    import time
    app = SimpleNamespace(app_config={"output_formats": ["srt"]})
    svc = TranscriptionService(app)

    file_path = tmp_path / "clip.mp4"
    file_path.touch()
    out_path = tmp_path / "clip.srt"
    out_path.write_text("hello")

    start_time = time.time()
    task = SimpleNamespace(
        file_path=str(file_path),
        start_time=start_time
    )

    # Older by 60s is rejected
    os.utime(out_path, (start_time - 60.0, start_time - 60.0))
    assert svc._are_outputs_complete(task) is False

    # Older by 1s is accepted
    os.utime(out_path, (start_time - 1.0, start_time - 1.0))
    assert svc._are_outputs_complete(task) is True

def test_worker_exit_recovery_logic(tmp_path, monkeypatch):
    import queue
    import time
    app = SimpleNamespace(
        app_config={"output_formats": ["srt"]},
        update_overall_progress=lambda: None,
        show_last_result=lambda task: None,
        queue=[],
        log=lambda m: None,
        note_job_success=lambda: None,
        workers=[],
        history=SimpleNamespace(finish_transcription=lambda *a, **k: True),
        worker_events=queue.Queue(),
        model_status=lambda *a: None,
    )
    svc = TranscriptionService(app)
    svc._post_usage_stats = lambda *a, **k: None
    monkeypatch.setattr(svc, "_ensure_poll_scheduled", lambda: None)

    file_path = tmp_path / "clip.mp4"
    file_path.touch()
    out_file = tmp_path / "clip.srt"
    out_file.write_text("hello")

    class FakeProc:
        pid = 111
        def poll(self): return 0

    # Return code 0 logic
    task = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        file_path=str(file_path), history_id=7, source_download=None,
    )

    saved_error = {}
    app.history.finish_transcription = lambda rid, status, error="", **k: saved_error.update({"error": error}) or True
    worker = {"task": task, "temporary": False, "id": "w1", "process": FakeProc(), "ready": True}
    app.workers.append(worker)
    app.worker_events.put({"event": "worker_exit", "return_code": 0, "_pid": 111, "_worker_id": "w1"})

    svc.poll()
    assert task.status == "finished"
    assert task.output_paths == [str(out_file)]  # the derived files reach history
    assert "Worker exited with code 0 after writing all outputs" in saved_error.get("error", "")

    # Status == paused stays error
    task2 = SimpleNamespace(
        status="paused", cancelled=False, end_time=None, start_time=time.time(),
        file_path=str(file_path), history_id=8, source_download=None,
    )
    worker2 = {"task": task2, "temporary": False, "id": "w2", "process": FakeProc(), "ready": True}
    app.workers.append(worker2)
    app.worker_events.put({"event": "worker_exit", "return_code": 0, "_pid": 111, "_worker_id": "w2"})

    svc.poll()
    assert task2.status == "error"

    # Status == cancelled stays cancelled
    task3 = SimpleNamespace(
        status="cancelled", cancelled=True, end_time=None, start_time=time.time(),
        file_path=str(file_path), history_id=9, source_download=None,
    )
    worker3 = {"task": task3, "temporary": False, "id": "w3", "process": FakeProc(), "ready": True}
    app.workers.append(worker3)
    app.worker_events.put({"event": "worker_exit", "return_code": 0, "_pid": 111, "_worker_id": "w3"})

    svc.poll()
    assert task3.status == "cancelled"


def test_output_check_never_breaks_worker_exit_handling(caplog):
    # The salvage check runs inside the worker_exit handler; an exception there used to abort the
    # handler and leave the task "running" (tests/core/test_worker_lifecycle_c251b.py caught it).
    svc = TranscriptionService.__new__(TranscriptionService)
    svc.app = SimpleNamespace(app_config={"output_formats": ["srt"]})

    assert svc._are_outputs_complete(SimpleNamespace(status="running")) is False  # no file_path

    class Broken:
        status = "running"

        @property
        def output_paths(self):
            raise RuntimeError("unexpected task state")

    with caplog.at_level("WARNING"):
        assert svc._are_outputs_complete(Broken()) is False
    assert "Output check after a worker exit failed" in caplog.text
