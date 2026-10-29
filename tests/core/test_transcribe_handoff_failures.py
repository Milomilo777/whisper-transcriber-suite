"""The hand-off from a finished download to its transcription, when it fails.

* The transcription cannot be registered (an exception in the enqueue step): the download row ends
  as an error with the reason, the file is kept, and it does not read as plain success.
* The worker dies while it loads the model: the waiting caller gives up at once, and the log says
  the engine stopped, not that the load "timed out".

No Tk root, no network.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("tkinter")

from app.app import App  # noqa: E402
from app.services import download_service as ds  # noqa: E402
from app.services.download_service import DownloadService  # noqa: E402


class _Download:
    def __init__(self):
        self.id = 1
        self.url = "https://example.invalid/v"
        self.status = "downloading"
        self.make_subbed_video = False
        self.caption_only = False
        self.detected_language = "fr"
        self.saved_path = None
        self.cancelled = False
        self.retries = 0


def test_a_failed_transcription_hand_off_ends_the_row_as_an_error(monkeypatch, tmp_path):
    saved = tmp_path / "talk.mp4"
    saved.write_bytes(b"media")
    logs: list[str] = []
    history: list[tuple] = []
    banners: list[str] = []

    def enqueue(_path, _lang, source_download=None):
        raise RuntimeError("queue is closed")

    app = types.SimpleNamespace(
        app_config={"auto_transcribe_after_download": True}, download_current=None,
        chime_on_complete_var=None, log=logs.append, enqueue_transcription_from_download=enqueue,
    )
    svc = DownloadService(app)
    svc.process_queue = lambda: None
    svc._finish_history = lambda task, status, paths, error="": history.append((status, paths, error))
    monkeypatch.setattr(ds, "desktop_alert", types.SimpleNamespace(download_done=lambda _a, p: banners.append(p)))

    task = _Download()
    svc._finish(task, "finished", str(saved))

    assert task.status == "error"
    status, paths, error = history[-1]
    assert status == "error" and paths == [str(saved)]
    assert "could not be started" in error and "queue is closed" in error
    assert any("could not be started" in m for m in logs)
    assert saved.exists()  # the downloaded file is never removed for this


class _Svc:
    def __init__(self):
        self.workers: list[dict] = []

    def ready_workers(self):
        return []

    def active_workers(self):
        return self.workers

    def start_worker(self, temporary=False):
        self.workers.append({"id": 1})


class _AppStandIn:
    _when_worker_ready = App._when_worker_ready

    def __init__(self):
        self.transcription_service = _Svc()
        self.logs: list[str] = []
        self.ticks = 0

    def log(self, msg):
        self.logs.append(msg)

    def after(self, _ms, cb):
        self.ticks += 1
        assert self.ticks <= 3, "kept polling after the worker died"
        self.transcription_service.workers = []  # the worker process died while loading
        cb()


def test_a_worker_that_dies_while_loading_is_reported_at_once_without_timed_out():
    app = _AppStandIn()
    gave_up: list[bool] = []
    app._when_worker_ready(lambda: pytest.fail("not ready"), on_timeout=lambda: gave_up.append(True),
                           loading_label="will transcribe talk.mp4 when ready.")
    assert gave_up == [True]
    assert app.ticks == 1
    assert any("stopped while loading" in m for m in app.logs)
    assert not any("timed out" in m for m in app.logs)
