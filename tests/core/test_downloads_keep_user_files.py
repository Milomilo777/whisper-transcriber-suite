"""A desktop download never takes, resumes, converts or deletes a file it did not create (ADR 0019).

The output name is the title only, so the file a job plans to write can already belong to the user
or to another job. These tests run the real ``DownloadService._run_media_process`` against a stand-in
for yt-dlp (``_fake_ytdlp.py``) that writes into a real folder, and check the folder afterwards.
No Tk, no network.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from app.domain.tasks import VideoDownloadTask
from app.services import download_service as ds
from core._proc import kill_download_tree
from core.download_guard import DownloadRefused

FAKE = Path(__file__).with_name("_fake_ytdlp.py")
URL_A = "https://x.test/v/Title%20A"
URL_B = "https://x.test/v/Title%20B"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """(service, folder, log): a service whose yt-dlp is the stand-in; ``log`` lists its runs."""
    monkeypatch.setattr(ds, "yt_dlp_js_args", lambda *_a, **_k: [])
    log = tmp_path / "runs.log"
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    for var in ("FAKE_YTDLP_PLAN_FAIL", "FAKE_YTDLP_FAIL_CONVERT", "FAKE_YTDLP_SLOW"):
        monkeypatch.delenv(var, raising=False)
    folder = tmp_path / "dl"
    folder.mkdir()
    app = types.SimpleNamespace(
        download_events=queue.Queue(), app_config={}, entry_file=str(tmp_path / "app.py"),
        yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "",
    )
    return ds.DownloadService(app), folder, log  # type: ignore[arg-type]


def _task(folder: Path, url: str = URL_A, mode: str = "Audio", output: str = "mp3") -> VideoDownloadTask:
    info = {"mode": mode, "output": output, "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"}}
    return VideoDownloadTask(url=url, folder=str(folder), format_label="x", format_info=info)


def _run(svc: ds.DownloadService, task: VideoDownloadTask):
    command = svc.build_download_command(task)
    command[:1] = [sys.executable, str(FAKE)]
    return svc._run_media_process(task, command)


def _runs(log: Path) -> list[str]:
    return [line.split()[0] for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_older_video_file_is_never_the_result(env):
    svc, folder, log = env
    old = folder / "Title A.mp4"
    old.write_bytes(b"the user's older download")
    task = _task(folder, mode="Audio and video", output="mp4")
    with pytest.raises(DownloadRefused, match="Title A.mp4"):
        _run(svc, task)
    assert old.read_bytes() == b"the user's older download"
    assert "real" not in _runs(log)               # yt-dlp never started the real download


def test_older_source_file_is_not_converted_or_deleted_in_audio_mode(env):
    svc, folder, log = env
    old = folder / "Title A.webm"                 # a video the user kept; audio mode would use it
    old.write_bytes(b"the user's webm")
    with pytest.raises(DownloadRefused, match="Title A.webm"):
        _run(svc, _task(folder))
    assert _names(folder) == ["Title A.webm"] and old.read_bytes() == b"the user's webm"
    assert "real" not in _runs(log)


def test_another_urls_partial_is_not_resumed(env):
    svc, folder, log = env
    part = folder / "Title A.mp4.part"
    part.write_bytes(b"bytes of another video")
    with pytest.raises(DownloadRefused, match="Title A.mp4.part"):
        _run(svc, _task(folder, mode="Audio and video", output="mp4"))
    assert part.read_bytes() == b"bytes of another video" and _names(folder) == ["Title A.mp4.part"]


def test_audio_command_keeps_the_source_so_yt_dlp_deletes_nothing(env):
    svc, folder, _ = env
    command = svc.build_download_command(_task(folder))
    assert "-k" in command and command.index("-k") < command.index("--")


def test_audio_run_removes_only_its_own_source(env):
    svc, folder, _ = env
    task = _task(folder)
    rc, _err, _last, saved, _final = _run(svc, task)
    assert rc == 0
    assert saved == str(folder / "Title A.mp3")
    assert _names(folder) == ["Title A.mp3"]      # the job's own webm is gone, the audio stays
    assert (folder / "Title A.mp3").read_bytes().startswith(b"audio:")


def test_failed_conversion_leaves_no_truncated_audio_and_a_retry_works(env, monkeypatch):
    svc, folder, _ = env
    task = _task(folder)
    monkeypatch.setenv("FAKE_YTDLP_FAIL_CONVERT", "Title A")
    rc, *_ = _run(svc, task)
    assert rc == 1
    assert "Title A.mp3" not in _names(folder)    # the truncated audio would be taken as finished
    monkeypatch.delenv("FAKE_YTDLP_FAIL_CONVERT")
    rc, _e, _l, saved, _f = _run(svc, task)       # the job's own source is accepted again
    assert rc == 0 and saved == str(folder / "Title A.mp3")
    assert (folder / "Title A.mp3").read_bytes().startswith(b"audio:")


def test_pause_during_conversion_removes_the_truncated_audio(env, monkeypatch):
    svc, folder, _ = env
    task = _task(folder)
    monkeypatch.setenv("FAKE_YTDLP_HANG_CONVERT", "Title A")

    def pause_when_converting() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (folder / "Title A.mp3").exists():
            time.sleep(0.05)
        task.paused = True                        # what pause_download does, then it kills yt-dlp
        kill_download_tree(task.process)

    threading.Thread(target=pause_when_converting, daemon=True).start()
    rc, *_ = _run(svc, task)
    assert rc != 0
    assert "Title A.mp3" not in _names(folder)
    assert "Title A.webm" in _names(folder)       # the downloaded source stays for the resume


def test_playlist_failure_removes_only_the_failing_item(env, monkeypatch):
    svc, folder, _ = env
    task = _task(folder, url="https://x.test/playlist/One,Two")
    monkeypatch.setenv("FAKE_YTDLP_FAIL_CONVERT", "Two")
    rc, *_ = _run(svc, task)
    assert rc == 1
    names = _names(folder)
    assert "One.mp3" in names                     # the finished first item survives
    assert "Two.mp3" not in names
    assert "One.webm" not in names                # its own source was removed after conversion


def test_resume_accepts_the_jobs_own_leftovers(env):
    svc, folder, _ = env
    task = _task(folder, mode="Audio and video", output="mp4")
    (folder / "Title A.mp4.part").write_bytes(b"first half")
    task.created_paths = [str(folder / "Title A.mp4")]   # announced by the paused run
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved == str(folder / "Title A.mp4")
    assert (folder / "Title A.mp4").read_bytes().startswith(b"first half|video:")


def test_a_stop_during_the_plan_pass_starts_nothing(env):
    svc, folder, log = env
    task = _task(folder)
    plain = svc._plan_pass

    def plan_then_cancel(t, command):
        result = plain(t, command)
        t.cancelled = True                          # Cancel landed while the plan pass ran
        return result

    svc._plan_pass = plan_then_cancel               # type: ignore[method-assign]
    rc, *_ = _run(svc, task)
    assert rc != 0 and "real" not in _runs(log) and _names(folder) == []


def test_resume_in_audio_mode_converts_the_jobs_own_source_and_removes_it(env):
    svc, folder, _ = env
    task = _task(folder)
    src = folder / "Title A.webm"
    src.write_bytes(b"video:first run")             # the paused run finished this download
    task.created_paths = [str(src)]
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved == str(folder / "Title A.mp3")
    assert _names(folder) == ["Title A.mp3"]


def test_without_a_plan_an_already_downloaded_older_file_stops_the_run(env, monkeypatch):
    svc, folder, log = env
    monkeypatch.setenv("FAKE_YTDLP_PLAN_FAIL", "1")
    monkeypatch.setenv("FAKE_YTDLP_SLOW", "40")
    old = folder / "Title A.mp4"
    old.write_bytes(b"the user's older download")
    started = time.monotonic()
    with pytest.raises(DownloadRefused, match="Title A.mp4"):
        _run(svc, _task(folder, mode="Audio and video", output="mp4"))
    assert time.monotonic() - started < 30         # stopped at the announcement, not after the sleep
    assert old.read_bytes() == b"the user's older download"


def test_without_a_plan_a_foreign_partial_is_not_resumed_and_cancel_keeps_it(env, monkeypatch):
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_PLAN_FAIL", "1")
    monkeypatch.setenv("FAKE_YTDLP_SLOW", "40")
    part = folder / "Title A.mp4.part"
    part.write_bytes(b"bytes of another video")
    task = _task(folder, mode="Audio and video", output="mp4")
    with pytest.raises(DownloadRefused):
        _run(svc, task)
    task.cancelled = True
    task.partial_paths = [str(folder / "Title A.mp4")]   # the name yt-dlp announced for this job
    svc.remove_partial_files(task)                 # what Cancel runs afterwards
    assert part.read_bytes() == b"bytes of another video"


def test_cancel_removes_the_partial_the_job_itself_wrote(env):
    svc, folder, _ = env
    task = _task(folder, mode="Audio and video", output="mp4")
    mine = folder / "Title A.mp4.part"
    task.partial_paths = [str(folder / "Title A.mp4")]
    task.created_paths = [str(folder / "Title A.mp4")]
    mine.write_bytes(b"mine")
    svc.remove_partial_files(task)
    assert not mine.exists()


def test_a_run_waits_until_the_previous_run_has_finished_stopping(env):
    svc, folder, log = env
    task = _task(folder)
    lock = ds._media_lock(task)
    lock.acquire()                                  # the old run, still cleaning up after a pause
    done = threading.Event()
    result: list = []

    def resumed() -> None:
        result.append(_run(svc, task))
        done.set()

    threading.Thread(target=resumed, daemon=True).start()
    time.sleep(0.8)
    assert not done.is_set() and _runs(log) == []   # nothing started while the old run holds the lock
    lock.release()
    assert done.wait(80)
    assert result[0][0] == 0


def test_the_youtube_copy_of_a_site_download_refuses_an_older_file_too(env):
    svc, folder, _ = env
    from core.integrations import smtv as smtv_mod

    old = folder / "watch.mp3"
    old.write_bytes(b"the user's older audio")
    episode = smtv_mod.SmtvEpisode(vid="1", title="Some Episode", page_url="https://example.test/1.html",
                                   lang_prefix="en", transcript_text="t", youtube_id="AbCdEf01234")
    task = _task(folder, url="https://example.test/1.html")
    task.format_info = {"mode": "Audio", "output": "mp3", "audio": None, "video": None, "episode": episode}
    plain = svc.build_download_command

    def fake_command(t, **kw):
        command = plain(t, **kw)
        command[:1] = [sys.executable, str(FAKE)]
        return command

    svc.build_download_command = fake_command      # type: ignore[method-assign]
    svc.maybe_update_yt_dlp = lambda t: None       # type: ignore[method-assign]
    task._run_generation = 1                       # type: ignore[attr-defined]
    def site_down(t, *, run_generation=None):
        raise RuntimeError("site down")

    svc._run_smtv_task = site_down                 # type: ignore[method-assign]
    svc._run_smtv_with_fallback(task, 1, object())
    assert old.read_bytes() == b"the user's older audio"
    events = []
    while not svc.app.download_events.empty():     # type: ignore[attr-defined]
        events.append(svc.app.download_events.get_nowait())  # type: ignore[attr-defined]
    kinds = [e[0] for e in events]
    assert "error" in kinds and "done_full" not in kinds
    assert any("watch.mp3" in str(e[2]) for e in events if e[0] == "error")


def test_rerun_of_a_failed_download_continues_its_own_partial(env):
    import sys as _sys
    if "faster_whisper" not in _sys.modules:        # App imports it; the suite stubs it elsewhere too
        _fw = types.ModuleType("faster_whisper")
        _fw.WhisperModel = object  # type: ignore[attr-defined]
        _sys.modules["faster_whisper"] = _fw
    from app.app import App

    svc, folder, _ = env
    failed = _task(folder, mode="Audio and video", output="mp4")
    failed.status = "error"
    failed.created_paths = [str(folder / "Title A.mp4")]
    failed.partial_paths = [str(folder / "Title A.mp4")]
    (folder / "Title A.mp4.part").write_bytes(b"first half")
    app = types.SimpleNamespace(
        download_queue=[], refresh_download_queue=lambda: None,
        download_service=types.SimpleNamespace(process_queue=lambda: None),
    )
    App._rerun_download(app, failed)                # type: ignore[arg-type]
    (copy,) = app.download_queue
    rc, _e, _l, saved, _f = _run(svc, copy)
    assert rc == 0 and saved == str(folder / "Title A.mp4")
    assert (folder / "Title A.mp4").read_bytes().startswith(b"first half|video:")
