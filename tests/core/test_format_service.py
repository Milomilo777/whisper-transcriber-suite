"""Tests for app.services.format_service robustness (audit finding [8]).

The format-lookup poll() runs on the Tk main thread and re-arms itself at
the END of its body. Before the fix, an exception while handling one event
(e.g. yt-dlp JSON that decoded to a non-dict) escaped poll() and the
after-chain was never rescheduled — so ALL format lookups silently died
for the rest of the session. poll() is now self-healing.
"""
from __future__ import annotations

from queue import Queue

import pytest

from app.services.format_service import FormatService, caption_lang_map


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FakeApp:
    def __init__(self):
        self.download_url_var = _Var("http://x")
        self.format_status_var = _Var()
        self.format_events: Queue = Queue()
        self._closing = False
        self.after_calls: list = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))


def test_handle_event_non_dict_payload_raises():
    svc = FormatService(_FakeApp())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        svc._handle_event("formats", "http://x", ["not", "a", "dict"])


def test_handle_event_error_sets_status():
    app = _FakeApp()
    FormatService(app)._handle_event(  # type: ignore[arg-type]
        "error", "http://x", "boom")
    assert app.format_status_var.get() == "boom"


def test_poll_self_heals_on_bad_event():
    app = _FakeApp()
    svc = FormatService(app)  # type: ignore[arg-type]
    app.format_events.put(("formats", "http://x", 12345))  # non-dict → raises

    svc.poll()  # must NOT propagate

    # poll re-armed itself despite the bad event...
    assert any(fn == svc.poll for (_ms, fn) in app.after_calls), \
        "poll() must reschedule even after an event handler raised"
    # ...and surfaced a message instead of dying silently.
    assert "Could not read formats" in app.format_status_var.get()


def test_poll_does_not_reschedule_when_closing():
    app = _FakeApp()
    app._closing = True
    svc = FormatService(app)  # type: ignore[arg-type]
    svc.poll()
    assert app.after_calls == [], "a closing app must not re-arm the poll loop"


# --- caption_lang_map ---------------------------------------------------

def test_caption_lang_map_manual_and_auto():
    payload = {
        "subtitles": {"en": [{"ext": "vtt"}], "de": [{"ext": "vtt"}]},
        "automatic_captions": {"en": [{"ext": "vtt"}], "fr": [{"ext": "vtt"}]},
    }
    assert caption_lang_map(payload) == {"en": "manual", "de": "manual", "fr": "auto"}


def test_caption_lang_map_manual_wins_over_auto_for_same_code():
    payload = {
        "subtitles": {"en": [{"ext": "vtt"}]},
        "automatic_captions": {"en": [{"ext": "vtt"}]},
    }
    assert caption_lang_map(payload) == {"en": "manual"}


def test_caption_lang_map_excludes_live_chat():
    payload = {"automatic_captions": {"live_chat": [{"ext": "json"}], "en": [{"ext": "vtt"}]}}
    assert caption_lang_map(payload) == {"en": "auto"}


def test_caption_lang_map_missing_keys():
    assert caption_lang_map({}) == {}


def test_caption_lang_map_non_dict_values_ignored():
    assert caption_lang_map({"subtitles": None, "automatic_captions": "bogus"}) == {}


# ---------- browser cookies in the paste-time lookup ---------------------------


class _LookupApp(_FakeApp):
    def __init__(self, cookies: str = ""):
        super().__init__()
        self.app_config = {"cookies_from_browser": cookies}
        self.format_lookup_after = None
        self.entry_file = __file__
        self.audio_format_combo: dict = {}
        self.video_format_combo: dict = {}
        self.audio_format_var = _Var()
        self.video_format_var = _Var()

    def yt_dlp_path(self):
        return "yt-dlp"

    def bin_path(self):
        return ""


def _run_lookup(monkeypatch, app, results):
    """Run lookup_formats synchronously with scripted yt-dlp results."""
    import subprocess
    import types

    import app.services.format_service as fs

    calls: list[list[str]] = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        rc, out, err = results[len(calls) - 1]
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    monkeypatch.setattr(subprocess, "run", fake_run)
    import core._threads as threads
    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())
    monkeypatch.setattr(fs.smtv_mod, "parse_episode_id", lambda _u: None)
    FormatService(app).lookup_formats()  # type: ignore[arg-type]
    return calls


def test_lookup_passes_the_configured_browser_cookies(monkeypatch):
    app = _LookupApp("firefox")
    calls = _run_lookup(monkeypatch, app, [(0, '{"formats": []}', "")])
    assert "--cookies-from-browser" in calls[0]
    assert calls[0][calls[0].index("--cookies-from-browser") + 1] == "firefox"
    assert app.format_events.get_nowait()[0] == "formats"


def test_lookup_without_cookies_passes_none(monkeypatch):
    calls = _run_lookup(monkeypatch, _LookupApp(""), [(0, "{}", "")])
    assert "--cookies-from-browser" not in calls[0]


def test_lookup_retries_without_cookies_when_the_jar_is_unreadable(monkeypatch):
    app = _LookupApp("chrome")
    calls = _run_lookup(monkeypatch, app, [
        (1, "", "ERROR: Could not copy Chrome cookie database. See yt-dlp#7271"),
        (0, '{"formats": []}', ""),
    ])
    assert len(calls) == 2
    assert "--cookies-from-browser" not in calls[1]
    assert app.format_events.get_nowait()[0] == "formats"


_INSTAGRAM_WALL = (
    "ERROR: [Instagram] abc: Requested content is not available, rate-limit "
    "reached or login required. Use --cookies, --cookies-from-browser, "
    "--username and --password, --netrc-cmd, or --netrc (instagram) to "
    "provide account credentials"
)


def test_login_wall_error_tells_the_user_to_pick_a_browser():
    app = _FakeApp()
    app.app_config = {"cookies_from_browser": ""}  # type: ignore[attr-defined]
    FormatService(app)._handle_event("error", "http://x", _INSTAGRAM_WALL)  # type: ignore[arg-type]
    status = app.format_status_var.get()
    assert status.startswith("This site wants you to be logged in")
    assert _INSTAGRAM_WALL in status


def test_login_wall_with_cookies_on_says_to_check_the_browser_login():
    app = _FakeApp()
    app.app_config = {"cookies_from_browser": "edge"}  # type: ignore[attr-defined]
    FormatService(app)._handle_event("error", "http://x", _INSTAGRAM_WALL)  # type: ignore[arg-type]
    assert "logged in to it in edge" in app.format_status_var.get()
