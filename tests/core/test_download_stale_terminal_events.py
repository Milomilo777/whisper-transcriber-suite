"""A terminal download event belongs to the run that posted it.

A run posts ``done`` / ``done_full`` / ``error`` into ``download_events`` and
the Tk poll drains it up to 300 ms later. A pause + resume in that gap
re-dispatches the SAME task object (a newer ``_run_generation``), so the old
event must not finish, fail or release the slot of the resumed run.

Hermetic: the real ``_run_task`` / ``_media_phase`` / ``poll`` / ``_finish``
run; only the yt-dlp process is faked.
"""
from __future__ import annotations

import threading
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

from app.app import App
from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService


def _task(folder: str) -> VideoDownloadTask:
    t = VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc", folder=folder, format_label="x",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"},
        },
    )
    t.status = "waiting"
    return t


def _app(task: VideoDownloadTask) -> SimpleNamespace:
    app = SimpleNamespace(
        download_events=Queue(), app_config={}, history=None, _closing=False,
        download_current=None, download_queue=[task],
        log=lambda _m: None, refresh_download_queue=lambda: None,
        after=lambda *_a, **_k: None, entry_file=__file__,
        subtitle_status_var=SimpleNamespace(set=lambda _v: None),
    )
    app.download_service = DownloadService(app)  # type: ignore[arg-type]
    return app


def _hermetic(monkeypatch, svc: DownloadService) -> list[threading.Thread]:
    """No updater, no offline switch, no real thread pool; the download
    threads are collected so the test can join them."""
    threads: list[threading.Thread] = []

    def _thread(target, args=(), name=None, **_k):
        th = threading.Thread(target=target, args=args, name=name, daemon=True)
        threads.append(th)
        th.start()
        return th

    import core._threads
    monkeypatch.setattr(core._threads, "safe_thread", _thread)
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", lambda _t: None)
    monkeypatch.setattr(svc, "_refused_offline", lambda _t: False)
    monkeypatch.setattr(svc, "build_download_command", lambda _t, **_k: ["yt-dlp"])
    return threads


def _wait_for(cond, timeout: float = 5.0) -> None:
    done = threading.Event()

    def _spin():
        while not cond():
            done.wait(0.01)

    th = threading.Thread(target=_spin, daemon=True)
    th.start()
    th.join(timeout)
    assert cond(), "condition not met in time"


@pytest.mark.parametrize("ending", ["error", "done_full"])
def test_stale_terminal_event_does_not_end_the_resumed_run(tmp_path, monkeypatch, ending):
    saved = Path(tmp_path) / "v.mp4"
    saved.write_bytes(b"x" * 10)
    task = _task(str(tmp_path))
    app = _app(task)
    svc = app.download_service
    threads = _hermetic(monkeypatch, svc)
    second_run_started = threading.Event()
    release_second_run = threading.Event()

    def _process(t, _command):
        if t._run_generation == 1:
            if ending == "error":
                raise RuntimeError("run 1 failed")
            return 0, "", "", str(saved), True
        second_run_started.set()
        release_second_run.wait(5)
        return 1, "", "", None, False

    monkeypatch.setattr(svc, "_run_media_process", _process)

    # Run 1 ends (error or success) and its terminal event waits for the poll.
    svc.process_queue()
    _wait_for(lambda: not threads[0].is_alive())
    assert app.download_events.qsize() >= 1

    # Pause + resume before the poll tick: run 2 of the same task starts.
    App.pause_download(app, task)  # type: ignore[arg-type]
    App.resume_download(app, task)  # type: ignore[arg-type]
    _wait_for(second_run_started.is_set)
    assert task._run_generation == 2
    assert task.status == "running" and app.download_current is task

    # The poll drains run 1's event: it must not touch run 2.
    svc.poll()
    try:
        assert task.status == "running"
        assert app.download_current is task
        assert getattr(task, "saved_path", None) in (None, "")
    finally:
        release_second_run.set()
        threads[-1].join(5)


@pytest.mark.parametrize("ending", ["error", "done_full"])
def test_a_current_terminal_event_still_ends_the_run(tmp_path, monkeypatch, ending):
    saved = Path(tmp_path) / "v.mp4"
    saved.write_bytes(b"x" * 10)
    task = _task(str(tmp_path))
    app = _app(task)
    svc = app.download_service
    threads = _hermetic(monkeypatch, svc)

    def _process(_t, _command):
        if ending == "error":
            raise RuntimeError("boom")
        return 0, "", "", str(saved), True

    monkeypatch.setattr(svc, "_run_media_process", _process)
    svc.process_queue()
    threads[0].join(5)
    svc.poll()
    assert task.status == ("error" if ending == "error" else "finished")
    assert app.download_current is None
    if ending == "done_full":
        assert task.saved_path == str(saved)


def test_an_unstamped_terminal_event_is_still_honoured(tmp_path):
    """Events posted without a run generation (older code paths, tests) are
    never dropped."""
    task = _task(str(tmp_path))
    task.status = "running"
    task._run_generation = 3  # type: ignore[attr-defined]
    app = _app(task)
    app.download_current = task
    app.download_events.put(("error", task, "plain event"))
    app.download_service.poll()
    assert task.status == "error"
    assert app.download_current is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
