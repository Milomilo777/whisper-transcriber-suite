"""Fixpack backlog regressions for app.services.download_service — downloadsvc.

Three medium/low defects from the backlog triage, all proven hermetically
(no Tk root, no network, no model, no subprocess):

1. enqueue_from_form reused a STALE ``_smtv_episode`` for a DIFFERENT SMTV url.
   The 800ms format-lookup is debounced, so pasting SMTV url A, replacing it
   with SMTV url B, and clicking Download before B's lookup fired reused
   episode A's CDN urls/transcript for B. Fixed by matching ``page_url == url``.

2. A typed time-range bound at/beyond the probed video length was accepted and
   shipped to yt-dlp; a start past the end builds a "*<dur>-" arg that
   downloads nothing. Fixed by dropping bounds >= duration when duration > 0.

3. DownloadService.poll() did ``int(payload)`` with no guard; a NaN / inf /
   non-numeric progress percent raised and — poll() having no try/except —
   skipped the after(300) re-arm, WEDGING the pump for every task. Fixed by a
   defensive finite-coercion.
"""
from __future__ import annotations

import sys
import types

import pytest

from app.services.download_service import DownloadService
from core.integrations import smtv as smtv_mod


SMTV_A = "https://www.suprememastertv.com/en1/v/111111.html"
SMTV_B = "https://www.suprememastertv.com/en1/v/222222.html"


# --------------------------------------------------------------------------
# Shared bare-app harness (App.__new__ + stubbed attrs, no Tk root)
# --------------------------------------------------------------------------


def _episode(page_url: str) -> smtv_mod.SmtvEpisode:
    return smtv_mod.SmtvEpisode(
        vid=page_url.rsplit("/", 1)[-1].split(".")[0],
        title="Episode",
        page_url=page_url,
        lang_prefix="en",
        files=[
            smtv_mod.SmtvFile(
                quality="396p",
                relative_path="clip.mp4",
                download_url=f"https://cdn.example/{page_url[-12:]}?file=clip.mp4",
            )
        ],
    )


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


def _bare_app(monkeypatch, tmp_path, *, url: str, episode):
    """A stub App carrying exactly what enqueue_from_form touches."""
    # Stub the App import lazily so faster_whisper isn't needed.
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App

    # Don't let save_config touch the real config file.
    import app.services.download_service as ds
    monkeypatch.setattr(ds, "save_config", lambda *a, **k: None)
    # enqueue_from_form imports tkinter.messagebox lazily; a warning path
    # would otherwise try to spin up a Tk root. Neutralise it so a validation
    # warning is observable (recorded) without any Tk.
    import tkinter.messagebox as _mb
    warnings: list = []
    monkeypatch.setattr(_mb, "showwarning", lambda *a, **k: warnings.append(a))

    app = App.__new__(App)
    app.download_url_var = _Var(url)
    app.download_folder_var = _Var(str(tmp_path))
    app.download_mode_var = _Var("Audio and video")
    app.audio_format_var = _Var("")
    app.video_format_var = _Var("SD 396p")
    app.output_format_var = _Var("mp4")
    app.audio_format_map = {}
    app.video_format_map = {"SD 396p": {"kind": "smtv", "mode": "video-396",
                                        "quality": "396p", "url": "x"}}
    app._smtv_episode = episode
    app.app_config = {}
    app.current_video_title = "Episode"
    app.current_video_language = "en"
    app.download_subtitles_var = _Var("")
    app.auto_transcribe_var = _Var(False)
    app.subtitle_lang_var = _Var("")
    app.download_start_time_var = _Var("")
    app.download_end_time_var = _Var("")
    app._download_duration = 0.0
    app.smtv_download_all_parts_var = None
    app.download_queue = []
    app.refresh_download_queue = lambda *a, **k: None

    captured: dict = {}

    class _Events:
        def put(self, item) -> None:  # noqa: ANN001
            captured.setdefault("events", []).append(item)

    app.download_events = _Events()

    svc = DownloadService(app)
    svc.process_queue = lambda *a, **k: None  # don't spawn a worker thread
    return app, svc, captured


# --------------------------------------------------------------------------
# 1. Stale _smtv_episode must NOT be reused for a different SMTV url
# --------------------------------------------------------------------------


def test_stale_smtv_episode_not_reused_for_different_url(monkeypatch, tmp_path):
    """Episode A stashed, url is B -> the task must NOT be an SMTV task."""
    app, svc, _ = _bare_app(monkeypatch, tmp_path, url=SMTV_B, episode=_episode(SMTV_A))
    # With the episode rejected, this becomes a normal (non-SMTV) download, so
    # an audio format is required — supply one so we exercise the enqueue, not
    # the missing-format warning.
    app.audio_format_var = _Var("Best audio")
    app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
    app.video_format_map = {"SD 396p": {"kind": "format_id", "format_id": "18"}}
    svc.enqueue_from_form()
    assert len(app.download_queue) == 1
    task = app.download_queue[0]
    # The mismatched episode was dropped: no SMTV episode pinned onto the task,
    # and subtitles/lang are NOT force-blanked as they are for an SMTV task.
    assert "episode" not in (task.format_info or {})


def test_matching_smtv_episode_is_reused(monkeypatch, tmp_path):
    """Episode B stashed, url is B -> reused as an SMTV task (episode pinned)."""
    ep = _episode(SMTV_B)
    app, svc, _ = _bare_app(monkeypatch, tmp_path, url=SMTV_B, episode=ep)
    svc.enqueue_from_form()
    assert len(app.download_queue) == 1
    task = app.download_queue[0]
    assert task.format_info.get("episode") is ep


# --------------------------------------------------------------------------
# 2. Time-range bounds at/beyond the probed duration are dropped
# --------------------------------------------------------------------------


def _enqueue_with_range(monkeypatch, tmp_path, *, duration, start, end):
    # A plain (non-SMTV) youtube-ish url so the duration guard is active.
    app, svc, _ = _bare_app(
        monkeypatch, tmp_path, url="https://youtu.be/abc", episode=None
    )
    # Plain url needs a real audio format selected (audio_required True).
    app.audio_format_var = _Var("Best audio")
    app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
    app.video_format_map = {"SD 396p": {"kind": "format_id", "format_id": "18"}}
    app._download_duration = duration
    app.download_start_time_var = _Var(start)
    app.download_end_time_var = _Var(end)
    svc.enqueue_from_form()
    assert len(app.download_queue) == 1
    return app.download_queue[0]


def test_end_beyond_duration_is_dropped(monkeypatch, tmp_path):
    # 2-minute video, end typed at 5:00 -> dropped (equivalent to "to the end").
    task = _enqueue_with_range(
        monkeypatch, tmp_path, duration=120.0, start="0:30", end="5:00"
    )
    assert task.section_start == 30.0
    assert task.section_end is None


def test_start_beyond_duration_is_dropped(monkeypatch, tmp_path):
    # start past the end is an empty slice -> dropped (not a broken "*300-").
    task = _enqueue_with_range(
        monkeypatch, tmp_path, duration=120.0, start="5:00", end=""
    )
    assert task.section_start is None
    assert task.section_end is None


def test_in_range_bounds_survive(monkeypatch, tmp_path):
    task = _enqueue_with_range(
        monkeypatch, tmp_path, duration=600.0, start="0:51", end="1:25"
    )
    assert task.section_start == 51.0
    assert task.section_end == 85.0


def test_unknown_duration_leaves_bounds_untouched(monkeypatch, tmp_path):
    # duration 0 (live / unknown) -> the guard must not strip a valid range.
    task = _enqueue_with_range(
        monkeypatch, tmp_path, duration=0.0, start="5:00", end="9:00"
    )
    assert task.section_start == 300.0
    assert task.section_end == 540.0


# --------------------------------------------------------------------------
# 3. poll() must survive a NaN / inf / non-numeric progress percent
# --------------------------------------------------------------------------


class _PollApp:
    """Minimal app for driving DownloadService.poll once."""

    def __init__(self, events):
        from queue import Queue
        self.download_events = Queue()
        for e in events:
            self.download_events.put(e)
        self._closing = False
        self.rearmed = False
        self.rearm_count = 0
        self.refresh_count = 0
        self.download_current = None

    def after(self, _ms, _cb):  # noqa: ANN001
        # Record that poll re-armed itself (proof the pump survived).
        self.rearmed = True
        self.rearm_count += 1

    def refresh_download_queue(self):
        self.refresh_count += 1

    def log(self, *a, **k):  # noqa: ANN002, ANN003
        pass


class _Task:
    def __init__(self):
        self.progress = 0


class _ExplodingVar:
    """Stands in for ``app.subtitle_status_var`` and fails on purpose, so a
    handler error is a deliberate RuntimeError rather than a missing attribute."""

    def set(self, _value):  # noqa: ANN001
        raise RuntimeError("deliberate failure in the subtitle_status handler")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "oops", None])
def test_poll_survives_bad_progress_value(bad):
    task = _Task()
    app = _PollApp([("progress", task, bad)])
    DownloadService(app).poll()
    # The pump re-armed (did not crash out of poll) ...
    assert app.rearmed is True
    # ... and the bad value never produced a garbage progress.
    assert 0 <= task.progress <= 100


def test_poll_normal_progress_still_works():
    task = _Task()
    app = _PollApp([("progress", task, 42.7)])
    DownloadService(app).poll()
    assert task.progress == 42
    assert app.rearmed is True


def test_poll_survives_unexpected_exception_in_any_branch():
    """The original fix above only guarded the 'progress' branch's int()
    coercion. poll() now wraps EVERY event's dispatch in one try/except
    (2026-08-14, gpt-5.4-mini adversarial review), so an unrelated
    exception in a completely different branch -- here 'subtitle_status',
    whose handler is made to raise here --
    still cannot skip the after(300) re-arm and wedge the pump."""
    task = _Task()
    app = _PollApp([("subtitle_status", task, "some text")])
    app.subtitle_status_var = _ExplodingVar()
    DownloadService(app).poll()
    assert app.rearmed is True


def test_poll_one_bad_event_does_not_block_later_good_events():
    """A malformed event must not prevent LATER queued events (for other
    tasks, in the same poll() call) from being processed."""
    task1, task2 = _Task(), _Task()
    app = _PollApp([
        ("subtitle_status", task1, "boom"),  # the exploding var raises
        ("progress", task2, 55.0),  # must still be processed despite the above
    ])
    app.subtitle_status_var = _ExplodingVar()
    DownloadService(app).poll()
    assert task2.progress == 55
    assert app.rearmed is True


def test_poll_rearms_exactly_once_per_tick_not_per_event():
    """Regression guard (2026-08-14, self-caught while fact-checking a
    Gemini review finding): _dispatch_event used to end with its own
    unconditional app.after(300, self.poll) call -- left over from when
    it was split out of poll()'s own body. That meant EVERY drained event
    scheduled its own independent poll() timer on top of the one poll()
    itself schedules at the end, so N events in one tick left N+1
    redundant timers in flight -- compounding every tick a download was
    actively producing progress/log lines. after() must fire exactly
    once per poll() call, no matter how many events were in the queue."""
    tasks = [_Task() for _ in range(5)]
    app = _PollApp([("progress", t, 10.0 * i) for i, t in enumerate(tasks)])
    DownloadService(app).poll()
    assert app.rearm_count == 1


def test_poll_refreshes_queue_once_per_tick_not_per_event():
    """Companion fix: refresh_download_queue() used to run inside the
    while loop (once per event) instead of once per batch -- wasteful
    Treeview rebuilds during a fast-progressing download."""
    tasks = [_Task() for _ in range(5)]
    app = _PollApp([("progress", t, 10.0 * i) for i, t in enumerate(tasks)])
    DownloadService(app).poll()
    assert app.refresh_count == 1


def test_poll_skips_refresh_when_queue_was_already_empty():
    """No events drained -> nothing changed -> no need to rebuild the
    Treeview at all."""
    app = _PollApp([])
    DownloadService(app).poll()
    assert app.refresh_count == 0
    assert app.rearm_count == 1  # still re-arms so the pump keeps running


def test_poll_survives_refresh_download_queue_raising():
    """A failure inside refresh_download_queue() itself (e.g. a Tk error
    while rebuilding rows) must not skip the app.after() re-arm either --
    same wedge-class risk as a bad event, different call site."""
    class _BrokenRefreshApp(_PollApp):
        def refresh_download_queue(self):
            self.refresh_count += 1
            raise RuntimeError("boom")

    task = _Task()
    app = _BrokenRefreshApp([("progress", task, 50.0)])
    DownloadService(app).poll()
    assert app.refresh_count == 1
    assert app.rearm_count == 1


# --------------------------------------------------------------------------
# 4. maybe_update_yt_dlp() must not poison the 24h backoff on a failed check
#    (2026-08-14, gpt-5.4-mini adversarial review). Since the user-writable
#    yt-dlp copy (core.yt_dlp_update) the update itself lives in core; these
#    tests pin the service's side: mode gate, backoff, stamp only when the
#    updater ran to its end.
# --------------------------------------------------------------------------


class _UpdateApp:
    """Minimal app for driving DownloadService.maybe_update_yt_dlp once."""

    def __init__(self, cfg):
        from queue import Queue
        self.app_config = cfg
        self.download_events = Queue()
        self.entry_file = __file__

    def yt_dlp_path(self) -> str:
        return "yt-dlp"


def _fake_update(monkeypatch, result):
    """Replace the core updater; returns the list of calls it received."""
    from core import yt_dlp_update

    calls = []

    def _update(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(yt_dlp_update, "update_cached_copy", _update)
    monkeypatch.setattr("app.services.download_service.save_config", lambda _c: None)
    return calls


def test_maybe_update_yt_dlp_does_not_stamp_timestamp_on_timeout(monkeypatch):
    """A network hiccup / subprocess timeout must not poison the 24h
    backoff. The old code stamped last_yt_dlp_update_check unconditionally
    (even on TimeoutExpired/any Exception), so one flaky check silently
    suppressed every retry for a full day."""
    from core.yt_dlp_update import UpdateResult

    calls = _fake_update(
        monkeypatch, UpdateResult("failed", message="The update timed out.", completed=False)
    )
    cfg = {"yt_dlp_update_mode": "auto"}
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert len(calls) == 1
    assert "last_yt_dlp_update_check" not in cfg


@pytest.mark.parametrize("status", ["updated", "current", "failed"])
def test_maybe_update_yt_dlp_stamps_timestamp_when_the_check_completed(monkeypatch, status):
    """A check that actually completes (whatever yt-dlp answered) DOES stamp
    the timestamp, so a genuinely healthy check still gets its 24h backoff."""
    from core.yt_dlp_update import UpdateResult

    saved = []
    _fake_update(monkeypatch, UpdateResult(status, completed=True))
    monkeypatch.setattr(
        "app.services.download_service.save_config", lambda c: saved.append(dict(c))
    )
    cfg = {"yt_dlp_update_mode": "auto"}
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert "last_yt_dlp_update_check" in cfg
    assert saved and "last_yt_dlp_update_check" in saved[0]


@pytest.mark.parametrize("status", ["busy", "unsupported"])
def test_maybe_update_yt_dlp_skipped_run_is_not_stamped(monkeypatch, status):
    """A download already running (busy) or no copy to update: nothing was
    checked, so the next download tries again."""
    from core.yt_dlp_update import UpdateResult

    _fake_update(monkeypatch, UpdateResult(status))
    cfg = {"yt_dlp_update_mode": "auto"}
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert "last_yt_dlp_update_check" not in cfg


@pytest.mark.parametrize("mode", ["ask", "never", "", "bogus"])
def test_maybe_update_yt_dlp_only_runs_in_auto_mode(monkeypatch, mode):
    from core.yt_dlp_update import UpdateResult

    calls = _fake_update(monkeypatch, UpdateResult("updated", completed=True))
    cfg = {"yt_dlp_update_mode": mode}
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert calls == []
    assert "last_yt_dlp_update_check" not in cfg


def test_maybe_update_yt_dlp_respects_the_24h_backoff(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.yt_dlp_update import UpdateResult

    calls = _fake_update(monkeypatch, UpdateResult("updated", completed=True))
    recent = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
    cfg = {"yt_dlp_update_mode": "auto", "last_yt_dlp_update_check": recent}
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert calls == []
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    cfg["last_yt_dlp_update_check"] = old
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)
    assert len(calls) == 1
    assert cfg["last_yt_dlp_update_check"] != old


def test_maybe_update_yt_dlp_survives_a_naive_stored_timestamp(monkeypatch):
    """Found by an adversarial review (2026-09-22): a stored timestamp
    without a UTC offset (hand-edited config, or a legacy value from
    before this key always stored an aware timestamp) parses into a
    NAIVE datetime; subtracting it from the aware now() raised
    TypeError, uncaught by the old `except ValueError`, aborting every
    yt-dlp download (media and caption-only both call this) until the
    key was fixed by hand."""
    from core.yt_dlp_update import UpdateResult

    _fake_update(monkeypatch, UpdateResult("current", completed=True))
    cfg = {
        "yt_dlp_update_mode": "auto",
        "last_yt_dlp_update_check": "2026-09-01T10:00:00",  # naive, no offset
    }
    DownloadService(_UpdateApp(cfg)).maybe_update_yt_dlp(task=None)  # must not raise
    assert cfg["last_yt_dlp_update_check"] != "2026-09-01T10:00:00"


def test_maybe_update_yt_dlp_logs_the_updater_output(monkeypatch):
    from core.yt_dlp_update import UpdateResult

    calls = _fake_update(
        monkeypatch, UpdateResult("updated", before=(2026, 8, 19), after=(2026, 9, 27), completed=True)
    )
    app = _UpdateApp({"yt_dlp_update_mode": "auto"})
    DownloadService(app).maybe_update_yt_dlp(task="T")
    calls[0]["log"]("Updated yt-dlp to stable@2026.09.27")
    lines = []
    while not app.download_events.empty():
        lines.append(app.download_events.get_nowait())
    assert ("log", "T", "Updated yt-dlp to stable@2026.09.27") in lines
    assert any("2026.09.27" in ev[2] and ev[2].startswith("yt-dlp update:") for ev in lines)
