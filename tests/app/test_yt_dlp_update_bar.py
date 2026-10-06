"""The "video downloader may be out of date" bar and what triggers it.

The App methods run on a small Tk host (a real root with a notebook), like
tests/app/test_update_bar.py. The update itself (core.yt_dlp_update) is
replaced here; it is tested in tests/core/test_yt_dlp_update.py.
"""
from __future__ import annotations

import time
import tkinter as tk
import types
from queue import Queue
from tkinter import ttk

import pytest

from app.app import App
from app.services.download_service import DownloadService
from app.services.format_service import FormatService
from core import yt_dlp_update as ytu

_BORROWED = (
    "offer_yt_dlp_update", "_ensure_yt_dlp_bar", "_yt_dlp_bar_dismiss",
    "_yt_dlp_update_now", "_yt_dlp_update_done", "ensure_online",
)
_FAILURE = "ERROR: unable to download video data: HTTP Error 403: Forbidden"


class _Host(tk.Tk):
    """A Tk root that runs the App's yt-dlp update-bar methods."""


for _name in _BORROWED:
    setattr(_Host, _name, getattr(App, _name))


@pytest.fixture(autouse=True)
def _clean_gate():
    ytu._running.clear()
    ytu._updating = False
    yield
    ytu._running.clear()
    ytu._updating = False


@pytest.fixture
def updater(monkeypatch):
    """Replace the real update; the worker thread runs synchronously."""
    calls: list[dict] = []
    state = types.SimpleNamespace(
        calls=calls,
        result=ytu.UpdateResult("updated", before=(2026, 8, 19), after=(2026, 9, 27), completed=True),
    )

    def _update(**kwargs):
        calls.append(kwargs)
        return state.result

    monkeypatch.setattr(ytu, "update_cached_copy", _update)
    monkeypatch.setattr(ytu, "can_self_update", lambda bundled=None: True)
    import core._threads as threads
    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="", **_k: fn())
    return state


@pytest.fixture
def host(updater):
    root = _Host()
    root.withdraw()
    root.app_config = {"yt_dlp_update_mode": "ask"}  # type: ignore[attr-defined]
    root._closing = False  # type: ignore[attr-defined]
    root._yt_dlp_bar = None  # type: ignore[attr-defined]
    root._yt_dlp_bar_dismissed = False  # type: ignore[attr-defined]
    root._yt_dlp_updating = False  # type: ignore[attr-defined]
    root.logs = []  # type: ignore[attr-defined]
    root.log = root.logs.append  # type: ignore[attr-defined]
    root.posted = []  # type: ignore[attr-defined]
    root.post_to_main = root.posted.append  # type: ignore[attr-defined]
    root.nb = ttk.Notebook(root)  # type: ignore[attr-defined]
    root.nb.pack(fill="both", expand=True)  # type: ignore[attr-defined]
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _visible(host) -> bool:
    return host._yt_dlp_bar is not None and host._yt_dlp_bar.visible


def _run_posted(host) -> None:
    while host.posted:
        host.posted.pop(0)()


def test_a_failure_offers_the_update_above_the_tabs(host):
    host.offer_yt_dlp_update(_FAILURE)
    assert _visible(host)
    bar = host._yt_dlp_bar
    assert bar.text_var.get().startswith("The video downloader may be out of date.")
    assert f"about {ytu.DOWNLOAD_MB} MB" in bar.text_var.get()
    assert bar.update_button.instate(["!disabled"])
    assert str(bar.update_button.cget("text")) == "Update it"
    assert str(bar.dismiss_button.cget("text")) == "Not now"
    slaves = host.pack_slaves()
    assert slaves.index(bar) < slaves.index(host.nb)
    assert host.focus_get() is None or host.focus_get() not in (bar.update_button, bar.dismiss_button)


def test_automatic_mode_also_offers_it(host):
    host.app_config["yt_dlp_update_mode"] = "auto"
    host.offer_yt_dlp_update(_FAILURE)
    assert _visible(host)


def test_never_mode_offers_nothing(host):
    host.app_config["yt_dlp_update_mode"] = "never"
    host.offer_yt_dlp_update(_FAILURE)
    assert not _visible(host)


def test_no_offer_when_this_copy_cannot_update_yt_dlp(host, monkeypatch):
    monkeypatch.setattr(ytu, "can_self_update", lambda bundled=None: False)
    host.offer_yt_dlp_update(_FAILURE)
    assert not _visible(host)


def test_not_now_hides_it_for_the_rest_of_the_launch(host, updater):
    host.offer_yt_dlp_update(_FAILURE)
    host._yt_dlp_bar.dismiss_button.invoke()
    assert not _visible(host)
    host.offer_yt_dlp_update(_FAILURE)
    assert not _visible(host)
    assert updater.calls == []


def test_update_it_updates_and_reports_the_new_version(host, updater):
    host.offer_yt_dlp_update(_FAILURE)
    bar = host._yt_dlp_bar
    bar.update_button.invoke()
    # While it runs: both buttons off, a progress line.
    assert bar.text_var.get() == "Updating the video downloader…"
    assert bar.update_button.instate(["disabled"])
    assert bar.dismiss_button.instate(["disabled"])
    assert len(updater.calls) == 1
    _run_posted(host)
    assert "updated to 2026.09.27" in bar.text_var.get()
    assert not bar.update_button.winfo_manager()  # nothing left to retry
    assert str(bar.dismiss_button.cget("text")) == "Close"
    assert any("2026.09.27" in line for line in host.logs)
    bar.dismiss_button.invoke()
    assert not _visible(host)


def test_a_failed_update_can_be_tried_again(host, updater):
    updater.result = ytu.UpdateResult("failed", message="network down.", completed=False)
    host.offer_yt_dlp_update(_FAILURE)
    host._yt_dlp_bar.update_button.invoke()
    _run_posted(host)
    bar = host._yt_dlp_bar
    assert bar.text_var.get().startswith("Could not update the video downloader: network down.")
    assert bar.update_button.winfo_manager()
    assert bar.update_button.instate(["!disabled"])
    bar.update_button.invoke()
    assert len(updater.calls) == 2


def test_update_it_during_a_download_does_not_update(host, updater):
    host.offer_yt_dlp_update(_FAILURE)
    ytu.begin_download("running-download")
    host._yt_dlp_bar.update_button.invoke()
    assert updater.calls == []
    bar = host._yt_dlp_bar
    assert bar.text_var.get().startswith("A download is running.")
    assert bar.update_button.instate(["!disabled"])
    ytu.end_download("running-download")
    bar.update_button.invoke()
    assert len(updater.calls) == 1


def test_no_new_offer_while_an_update_runs(host, updater):
    host.offer_yt_dlp_update(_FAILURE)
    host._yt_dlp_bar.update_button.invoke()  # posted result not drained yet
    host.offer_yt_dlp_update(_FAILURE)
    assert host._yt_dlp_bar.text_var.get() == "Updating the video downloader…"
    host._yt_dlp_bar.update_button.invoke()
    assert len(updater.calls) == 1


# ------------------------------------------------------------ the triggers


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FormatApp:
    def __init__(self):
        self.download_url_var = _Var("https://www.youtube.com/watch?v=abc")
        self.format_status_var = _Var()
        self.format_events: Queue = Queue()
        self.app_config = {"cookies_from_browser": ""}
        self._closing = False
        self.offers: list[str] = []

    def offer_yt_dlp_update(self, reason: str) -> None:
        self.offers.append(reason)

    def yt_dlp_path(self) -> str:
        return "yt-dlp"


def test_a_format_lookup_failure_of_an_old_yt_dlp_offers_the_update():
    app = _FormatApp()
    FormatService(app)._handle_event("error", app.download_url_var.get(), _FAILURE)  # type: ignore[arg-type]
    assert app.offers == [_FAILURE]


def test_a_format_lookup_failure_for_another_reason_offers_nothing():
    app = _FormatApp()
    FormatService(app)._handle_event(  # type: ignore[arg-type]
        "error", app.download_url_var.get(), "ERROR: [youtube] abc: Private video",
    )
    assert app.offers == []


def test_the_format_lookup_waits_for_a_running_update(monkeypatch):
    import subprocess

    import app.services.format_service as fs

    waited: list[bool] = []
    monkeypatch.setattr(ytu, "wait_while_updating", lambda timeout=0: waited.append(True) or True)
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **_k: types.SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    )
    import core._threads as threads
    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())
    monkeypatch.setattr(fs.smtv_mod, "parse_episode_id", lambda _u: None)
    app = _FormatApp()
    app.format_lookup_after = None  # type: ignore[attr-defined]
    app.entry_file = __file__  # type: ignore[attr-defined]
    app.bin_path = lambda: ""  # type: ignore[attr-defined]
    app.audio_format_combo = {}  # type: ignore[attr-defined]
    app.video_format_combo = {}  # type: ignore[attr-defined]
    app.audio_format_var = _Var()  # type: ignore[attr-defined]
    app.video_format_var = _Var()  # type: ignore[attr-defined]
    FormatService(app).lookup_formats()  # type: ignore[arg-type]
    assert waited == [True]
    assert app.format_events.get_nowait()[0] == "formats"


class _DownloadApp:
    def __init__(self):
        self.download_events: Queue = Queue()
        self.offers: list[str] = []
        self.posted: list = []

    def offer_yt_dlp_update(self, reason: str) -> None:
        self.offers.append(reason)

    def post_to_main(self, fn) -> None:
        self.posted.append(fn)


def test_a_download_failure_posts_the_offer_to_the_ui_thread():
    app = _DownloadApp()
    DownloadService(app)._offer_yt_dlp_update(_FAILURE)  # type: ignore[arg-type]
    assert app.offers == []  # not called from the download thread itself
    app.posted.pop()()
    assert app.offers == [_FAILURE]


def test_the_media_phase_offers_the_update_on_a_403(monkeypatch):
    """The real failure branch of _media_phase: yt-dlp exits 1 with a 403."""
    app = _DownloadApp()
    app.app_config = {"cookies_from_browser": ""}  # type: ignore[attr-defined]
    svc = DownloadService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "build_download_command", lambda task, **_k: ["yt-dlp"])
    monkeypatch.setattr(
        svc, "_run_media_process",
        lambda task, cmd: (1, _FAILURE, _FAILURE, None, None),
    )
    task = types.SimpleNamespace(cancelled=False, paused=False, url="https://youtu.be/abc")
    svc._media_phase(task)  # type: ignore[arg-type]
    events = []
    while not app.download_events.empty():
        events.append(app.download_events.get_nowait())
    assert any(e[0] == "error" and "HTTP Error 403" in e[2] for e in events)
    assert len(app.posted) == 1
    app.posted.pop()()
    assert app.offers == [_FAILURE]


# ------------------------------------------- a download and an update never overlap


def _task(*, caption_only: bool = False):
    from app.domain.tasks import VideoDownloadTask

    task = VideoDownloadTask(
        url="https://youtu.be/abc", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"}},
    )
    task.caption_only = caption_only  # type: ignore[attr-defined]
    return task


def _run_task_service(events: list):
    svc = DownloadService.__new__(DownloadService)
    svc.app = types.SimpleNamespace(  # type: ignore[attr-defined]
        download_events=types.SimpleNamespace(put=events.append), history=None,
    )
    svc.maybe_update_yt_dlp = lambda _t: None  # type: ignore[attr-defined]
    return svc


@pytest.mark.parametrize("caption_only", [False, True])
def test_a_download_is_registered_while_its_yt_dlp_runs(caption_only):
    events: list = []
    svc = _run_task_service(events)
    seen: list[int] = []

    def _phase(_t, run_generation=None):
        seen.append(ytu.downloads_running())

    svc._media_phase = _phase  # type: ignore[attr-defined]
    svc._run_caption_only_task = _phase  # type: ignore[attr-defined]
    DownloadService._run_task(svc, _task(caption_only=caption_only))
    assert seen == [1]
    assert ytu.downloads_running() == 0


@pytest.mark.parametrize("caption_only", [False, True])
@pytest.mark.parametrize("stop", ["cancelled", "paused"])
def test_a_stop_during_the_wait_for_an_update_launches_nothing(caption_only, stop):
    """Found by the review: the run waits at the registration while an update
    runs. A cancel or pause landing during that wait must still keep yt-dlp
    from starting (the pre-start guards come after the registration)."""
    import threading

    events: list = []
    svc = _run_task_service(events)
    entered: list[str] = []
    svc._media_phase = lambda _t, run_generation=None: entered.append("media")  # type: ignore[attr-defined]
    svc._run_caption_only_task = (  # type: ignore[attr-defined]
        lambda _t, run_generation=None: entered.append("captions"))
    task = _task(caption_only=caption_only)
    ytu._updating = True  # an update is running
    runner = threading.Thread(target=DownloadService._run_task, args=(svc, task))
    runner.start()
    time.sleep(0.3)
    assert runner.is_alive()  # waiting for the update
    setattr(task, stop, True)
    with ytu._cond:
        ytu._updating = False
        ytu._cond.notify_all()
    runner.join(5)
    assert not runner.is_alive()
    assert entered == []
    if stop == "cancelled":
        assert any(e[0] == "done" and e[2] == "cancelled" for e in events)
    assert ytu.downloads_running() == 0


def test_an_auto_update_runs_before_the_download_registers():
    """maybe_update_yt_dlp runs unregistered: registered first, the automatic
    update would always see its own download and refuse as "busy"."""
    events: list = []
    svc = _run_task_service(events)
    during_update: list[int] = []
    svc.maybe_update_yt_dlp = lambda _t: during_update.append(ytu.downloads_running())  # type: ignore[attr-defined]
    svc._media_phase = lambda _t, run_generation=None: None  # type: ignore[attr-defined]
    DownloadService._run_task(svc, _task())
    assert during_update == [0]
