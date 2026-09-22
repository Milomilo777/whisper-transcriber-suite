"""Tests for the Live tab wiring (app/widgets/live_tab.py).

Builds the tab on a real Tk root — a layout that "looks fine" in source
can still fail to construct — but never starts a real session, so no
sound card, model, or subprocess is involved.
"""
from __future__ import annotations

import threading
import types

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from app.widgets import live_tab  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover — headless CI without a display
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(root):
    """The smallest object build_live_tab actually touches."""
    a = types.SimpleNamespace()
    a.app_config = {}
    a.entry_file = "gui.py"
    a.logged: list[str] = []
    a.log = a.logged.append
    a.posted: list = []
    a.post_to_main = lambda fn: (a.posted.append(fn), fn())[1]
    a.after = root.after
    a.clipboard_clear = root.clipboard_clear
    a.clipboard_append = root.clipboard_append
    a.errors: list = []
    return a


@pytest.fixture
def built(app, root):
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack(fill="both", expand=True)
    root.update()
    return app


# ----------------------------------------------------------------- build


def test_tab_builds_and_starts_idle(built):
    assert built.live_session is None
    assert built.live_transcriber is None
    assert str(built.live_start_btn.cget("state")) == "normal"
    assert str(built.live_stop_btn.cget("state")) == "disabled"
    assert "Idle" in built.live_status_var.get()


def test_microphone_is_always_offered(built):
    assert "Microphone" in list(built.live_source_combo.cget("values"))


def test_system_audio_is_only_offered_when_supported(app, root, monkeypatch):
    from core import live as _live

    monkeypatch.setattr(_live, "is_available", lambda mode="mic": False)
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    root.update()
    assert list(app.live_source_combo.cget("values")) == ["Microphone"]


def test_transcript_starts_empty_and_read_only(built):
    assert live_tab._transcript_text(built) == ""
    # state stays "normal" so mouse drag-selection/copy work; typing is
    # blocked by the <Key> filter instead (see test_blocks_edit below).
    assert str(built.live_text.cget("state")) == "normal"


@pytest.mark.parametrize(
    ("keysym", "state", "expected"),
    [
        ("a", 0, True),          # plain typing -> blocked
        ("BackSpace", 0, True),  # would delete text -> blocked
        ("Left", 0, False),      # navigation -> allowed
        ("Home", 0, False),
        ("c", 4, False),         # Ctrl+C (state bit 0x4) -> allowed
        ("a", 4, False),         # Ctrl+A (select all) -> allowed
    ],
)
def test_blocks_edit(keysym, state, expected):
    assert live_tab._blocks_edit(keysym, state) is expected


# -------------------------------------------------------------- language


def test_auto_language_means_let_the_model_decide(built):
    built.live_lang_var.set("Auto")
    assert live_tab._selected_language_code(built) is None


def test_language_list_has_no_duplicate_auto_entry(built):
    """yt-dlp's 'Automatic' means the same as our 'Auto' and has no code."""
    values = list(built.live_lang_combo.cget("values"))
    assert values[0] == "Auto"
    assert "Automatic" not in values[1:]


def test_every_offered_language_maps_to_a_real_code(built):
    """A blank code would be forced onto the engine as a bad language."""
    for name in list(built.live_lang_combo.cget("values"))[1:]:
        built.live_lang_var.set(name)
        assert live_tab._selected_language_code(built), name


def test_unknown_language_falls_back_to_auto(built):
    built.live_lang_var.set("Klingon")
    assert live_tab._selected_language_code(built) is None


def test_language_resolution_matches_the_transcribe_tab(built):
    """Live and file transcription must not disagree about a language."""
    from app.domain.languages import SUBTITLE_LANGUAGES

    name, expected = next((n, c) for n, c in SUBTITLE_LANGUAGES if c)
    built.live_lang_var.set(name)
    assert live_tab._selected_language_code(built) == expected


# ---------------------------------------------------------------- devices


def test_device_picker_is_disabled_for_system_audio(built):
    built.live_source_var.set("System audio (what you hear)")
    live_tab._sync_device_state(built)
    assert str(built.live_device_combo.cget("state")) == "disabled"
    built.live_source_var.set("Microphone")
    live_tab._sync_device_state(built)
    assert str(built.live_device_combo.cget("state")) == "readonly"


def test_default_device_maps_to_none(built):
    built.live_device_var.set("Default input device")
    assert live_tab._selected_device_index(built) is None


def test_named_device_maps_to_its_index(built, monkeypatch):
    from core import live as _live

    dev = types.SimpleNamespace(index=3, name="USB Mic")
    monkeypatch.setattr(_live, "list_input_devices", lambda: [dev])
    live_tab._refresh_devices(built)
    built.live_device_var.set("3: USB Mic")
    assert live_tab._selected_device_index(built) == 3


def test_device_listing_failure_does_not_break_the_tab(built, monkeypatch):
    from core import live as _live

    def boom():
        raise RuntimeError("audio subsystem exploded")

    monkeypatch.setattr(_live, "list_input_devices", boom)
    live_tab._refresh_devices(built)   # must not raise
    assert "Default input device" in list(built.live_device_combo.cget("values"))


# ------------------------------------------------------------- transcript


def test_appending_text_builds_the_transcript(built):
    live_tab._append_line(built, "hello")
    live_tab._append_line(built, "world")
    assert live_tab._transcript_text(built) == "hello\nworld"
    assert str(built.live_text.cget("state")) == "normal", "must stay selectable"


def test_empty_text_is_ignored(built):
    live_tab._append_line(built, "")
    assert live_tab._transcript_text(built) == ""


def test_clear_empties_both_the_widget_and_the_buffer(built):
    live_tab._append_line(built, "hello")
    live_tab._clear(built)
    assert live_tab._transcript_text(built) == ""
    assert built.live_text.get("1.0", "end").strip() == ""


def test_copy_puts_the_transcript_on_the_clipboard(built, root):
    live_tab._append_line(built, "clipboard line")
    live_tab._copy(built)
    assert "clipboard line" in root.clipboard_get()


def test_save_writes_the_transcript(built, tmp_path, monkeypatch):
    live_tab._append_line(built, "line one")
    target = tmp_path / "out.txt"
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename",
                        lambda **kw: str(target))
    live_tab._save(built)
    assert target.read_text(encoding="utf-8").strip() == "line one"


def test_save_cancelled_writes_nothing(built, tmp_path, monkeypatch):
    live_tab._append_line(built, "line one")
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kw: "")
    live_tab._save(built)
    assert list(tmp_path.iterdir()) == []


def test_saving_an_empty_transcript_warns_instead_of_writing(built, monkeypatch):
    shown: list = []
    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: shown.append(a))
    monkeypatch.setattr(
        live_tab.filedialog, "asksaveasfilename",
        lambda **kw: pytest.fail("asked for a path with nothing to save"),
    )
    live_tab._save(built)
    assert shown


# ------------------------------------------------------------ start guard


def test_start_refuses_when_the_backend_is_missing(built, monkeypatch):
    from core import live as _live

    shown: list = []
    monkeypatch.setattr(_live, "is_available", lambda mode="mic": False)
    monkeypatch.setattr(
        _live, "availability_reason",
        lambda mode="mic": "sounddevice not installed",
    )
    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: shown.append(kw.get("detail", "")))
    live_tab._start(built)
    assert shown, "the user got no explanation"
    assert built.live_session is None
    assert str(built.live_start_btn.cget("state")) == "normal", "controls stayed locked"


# ------------------------------------------------ stop-during-load race
#
# Found by an adversarial review (2026-09-22): Stop, pressed while the
# worker thread was still loading the model (live_session is still
# None), used to be silently dropped -- _stop() just reset the button
# state and returned with no record of the request. When the worker
# eventually reached _started(), the session was activated anyway with
# Stop disabled and Start enabled, leaving an unstoppable, unreachable
# session; a second Start then orphaned it entirely. The fix threads a
# cancellation flag from _stop() through to _started().


def test_stop_during_load_records_cancellation_instead_of_dropping_it(built):
    assert built.live_session is None  # still "loading" from the caller's POV
    built._live_cancel_pending = False

    live_tab._stop(built)

    assert built._live_cancel_pending is True
    assert str(built.live_stop_btn.cget("state")) == "disabled"
    assert "loading" in built.live_status_var.get().lower()


def test_started_after_cancel_tears_down_instead_of_activating(built):
    done = threading.Event()
    stopped: list[str] = []
    posted: list = []

    def session_stop(**kw):
        stopped.append("session")

    def transcriber_stop():
        stopped.append("worker")

    fake_session = types.SimpleNamespace(
        stop=session_stop, drain_events=lambda limit=64: []
    )
    fake_transcriber = types.SimpleNamespace(stop=transcriber_stop)

    def post_and_signal(fn):
        # Mirror the real post_to_main bridge: queue for the caller to
        # drain on the main thread rather than running fn() here. The
        # `app` fixture's own post_to_main runs fn() immediately, which
        # is fine for every other test (always called from the main
        # thread) but this is the first test where _started's
        # cancel-teardown worker calls post_to_main from a real
        # background thread -- running a Tk widget update there raises
        # "main thread is not in main loop", same as the real app would
        # hit if it called Tk directly off-thread instead of marshalling.
        posted.append(fn)
        done.set()

    built.post_to_main = post_and_signal
    built._live_cancel_pending = True
    live_tab._started(built, fake_transcriber, fake_session)

    assert done.wait(timeout=2.0), "the cancel-teardown worker never posted back"
    assert stopped == ["session", "worker"]
    assert posted, "_stopped was never queued back to the main thread"
    posted[0]()  # drain on the main (Tk) thread, like the real bridge would

    assert built.live_session is None
    assert built.live_transcriber is None
    assert built._live_cancel_pending is False
    assert "Stopped" in built.live_status_var.get()
    assert str(built.live_start_btn.cget("state")) == "normal"
    assert str(built.live_stop_btn.cget("state")) == "disabled"


def test_started_without_cancel_activates_normally(built):
    fake_session = types.SimpleNamespace(stop=lambda **kw: None)
    fake_transcriber = types.SimpleNamespace(stop=lambda: None)

    built._live_cancel_pending = False
    live_tab._started(built, fake_transcriber, fake_session)

    assert built.live_session is fake_session
    assert built.live_transcriber is fake_transcriber
    assert "Listening" in built.live_status_var.get()


# ---------------------------------------------------------------- polling


def _fake_session(events):
    return types.SimpleNamespace(
        drain_events=lambda limit=64: events,
        stop=lambda **kw: "",
    )


def test_poll_appends_text_events(built):
    from core.live import LiveEvent

    built.live_session = _fake_session([LiveEvent(kind="text", text="spoken")])
    live_tab._poll_once(built)
    assert "spoken" in live_tab._transcript_text(built)


def test_poll_surfaces_a_warning_in_the_status_line(built):
    from core.live import LiveEvent

    built.live_session = _fake_session(
        [LiveEvent(kind="warning", detail="falling behind")]
    )
    live_tab._poll_once(built)
    assert "falling behind" in built.live_status_var.get()


def test_poll_logs_errors_without_killing_the_tab(built):
    from core.live import LiveEvent

    built.live_session = _fake_session([LiveEvent(kind="error", detail="boom")])
    live_tab._poll_once(built)
    assert any("boom" in line for line in built.logged)


def test_poll_with_no_session_is_a_no_op(built):
    built.live_session = None
    live_tab._poll_once(built)   # must not raise


def test_drain_failure_does_not_propagate(built):
    def boom(limit=64):
        raise RuntimeError("queue exploded")

    built.live_session = types.SimpleNamespace(drain_events=boom)
    live_tab._poll_once(built)   # must not raise


# ---------------------------------------------------------------- teardown


def test_stop_live_session_is_safe_when_nothing_runs(built):
    live_tab.stop_live_session(built)
    assert built.live_session is None


def test_stop_live_session_stops_both_halves(built):
    stopped: list[str] = []
    built.live_session = types.SimpleNamespace(
        stop=lambda **kw: stopped.append("session")
    )
    built.live_transcriber = types.SimpleNamespace(
        stop=lambda: stopped.append("worker")
    )
    live_tab.stop_live_session(built)
    assert stopped == ["session", "worker"]
    assert built.live_session is None
    assert built.live_transcriber is None


def test_teardown_continues_when_the_session_raises(built):
    """A wedged session must not stop the worker subprocess being killed."""
    stopped: list[str] = []

    def boom(**kw):
        raise RuntimeError("wedged")

    built.live_session = types.SimpleNamespace(stop=boom)
    built.live_transcriber = types.SimpleNamespace(
        stop=lambda: stopped.append("worker")
    )
    live_tab.stop_live_session(built)
    assert stopped == ["worker"], "the worker subprocess would have leaked"
