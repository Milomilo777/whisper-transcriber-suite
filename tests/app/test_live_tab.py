"""Tests for the Live tab wiring (app/widgets/live_tab.py).

Builds the tab on a real Tk root — a layout that "looks fine" in source
can still fail to construct — but never starts a real session, so no
sound card, model, or subprocess is involved.
"""
from __future__ import annotations

import threading
import time
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


# ------------------------------------------------------ stop: drain / discard


def _drain_posted(app, root, until, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not until():
        while app.posted:
            app.posted.pop(0)()
        root.update()
        time.sleep(0.01)


def test_first_stop_drains_backlog_second_stop_discards(built, root):
    """First Stop: mic off, backlog keeps transcribing, button offers
    "Discard rest". Second press: backlog dropped, worker stopped."""
    finished = threading.Event()
    calls: list[str] = []
    built.post_to_main = built.posted.append  # run on the Tk thread only

    def discard_pending():
        calls.append("discard")
        finished.set()
        return 2

    session = types.SimpleNamespace(
        stop_capture=lambda: calls.append("capture"),
        wait_drained=lambda timeout=None: finished.wait(5.0),
        discard_pending=discard_pending,
        pending_chunks=lambda: 3,
        drain_events=lambda limit=64: [],
    )
    transcriber = types.SimpleNamespace(stop=lambda: calls.append("worker"))
    built.live_session, built.live_transcriber = session, transcriber
    live_tab._set_running(built, True)

    live_tab._stop(built)
    _drain_posted(built, root, lambda: "capture" in calls)
    assert built._live_draining is True
    assert built.live_stop_btn.cget("text") == "Discard rest"
    assert str(built.live_stop_btn.cget("state")) == "normal"
    live_tab._poll_once(built)
    assert "3 remaining" in built.live_status_var.get()

    live_tab._stop(built)
    _drain_posted(built, root, lambda: built.live_session is None)
    assert calls.count("discard") == 1 and "worker" in calls
    assert built.live_session is None
    assert built._live_draining is False
    assert built.live_stop_btn.cget("text") == "Stop"
    assert any("discarded 2" in m for m in built.logged)


# ------------------------------------------------------------ model picker


def _menu_labels(built):
    menu = built.live_model_menu
    return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
            if menu.type(i) == "radiobutton"]


def test_model_picker_defaults_to_tiny_and_saves_choice(built, monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr("core.config.save_config", lambda cfg: saved.append(dict(cfg)))
    labels = _menu_labels(built)
    assert labels[0] == live_tab._MODEL_AUTO and labels[1] == live_tab._MODEL_MAIN
    assert len(labels) > 2  # catalog models follow
    assert live_tab._selected_live_value(built) == "tiny"

    built.live_model_var.set(live_tab._MODEL_MAIN)
    live_tab._on_live_model_selected(built)
    assert built.app_config["live_model"] == "main"
    assert saved and saved[-1]["live_model"] == "main"


def test_language_defaults_to_english(built):
    assert built.live_lang_var.get() == "English"
    assert live_tab._selected_language_code(built) == "en"


def test_missing_model_is_greyed_and_offers_download(app, root, monkeypatch, tmp_path):
    app.app_config["hub_folder"] = str(tmp_path)  # empty hub: nothing downloaded
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack()
    root.update()
    menu = app.live_model_menu
    tiny_label = app.live_model_var.get()  # the tiny default is selected
    tiny = next(i for i in range(menu.index("end") + 1)
                if menu.type(i) == "radiobutton"
                and menu.entrycget(i, "value") == tiny_label)
    assert "not downloaded" in menu.entrycget(tiny, "label")
    assert app.live_model_btn.cget("style") == live_tab._MODEL_MISSING_STYLE
    assert app.live_model_dl_btn.grid_info()


def test_downloaded_model_is_bold_and_hides_download(app, root, monkeypatch):
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: True)
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack()
    root.update()
    assert not any("not downloaded" in lbl for lbl in _menu_labels(app))
    assert app.live_model_btn.cget("style") == live_tab._MODEL_READY_STYLE
    assert not app.live_model_dl_btn.grid_info()


def test_download_button_fetches_the_selected_model(app, root, monkeypatch, tmp_path):
    app.app_config["hub_folder"] = str(tmp_path)
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack()
    root.update()
    got: list[str] = []

    def fake_ensure(cfg, progress_cb=None, **kw):
        got.append(cfg["whisper_model"])
        if progress_cb:
            progress_cb({"percent": 50, "detail": "halfway"})
        import pathlib
        p = pathlib.Path(cfg["model_path"])
        p.mkdir(parents=True, exist_ok=True)
        (p / "model.bin").write_bytes(b"x")
        return str(p)

    monkeypatch.setattr("core.model_manager.ensure_model", fake_ensure)
    queued: list = []
    app.post_to_main = queued.append  # like the real app: run later, on Tk
    live_tab._download_live_model(app)
    deadline = time.time() + 5
    while app._live_model_downloading and time.time() < deadline:
        while queued:
            queued.pop(0)()
        root.update()
        time.sleep(0.02)
    root.update()
    assert got == ["tiny"]
    assert app.live_model_btn.cget("style") == live_tab._MODEL_READY_STYLE
    assert not app.live_model_dl_btn.grid_info()


def test_prepare_live_model_uses_main_model_on_gpu(built, monkeypatch):
    monkeypatch.setattr("core.hardware.detect_device_for", lambda cfg: ("cuda", "float16"))
    built.app_config["live_model"] = "auto"
    assert live_tab._prepare_live_model(built, "fa") is None


def test_prepare_live_model_falls_back_when_download_fails(built, monkeypatch, tmp_path):
    monkeypatch.setattr("core.hardware.detect_device_for", lambda cfg: ("cpu", "int8"))

    def boom(cfg, *a, **kw):
        raise OSError("offline")

    monkeypatch.setattr("core.model_manager.ensure_model", boom)
    built.app_config.update(live_model="auto", hub_folder=str(tmp_path))
    assert live_tab._prepare_live_model(built, "fa") is None
    assert any("could not download" in m for m in built.logged)


# ------------------------------------------- read-only transcript (L3/L4)


@pytest.mark.parametrize(
    ("keysym", "state", "platform", "expected"),
    [
        ("v", 4, "win32", True),       # Ctrl+V pastes -> blocked
        ("x", 4, "win32", True),       # Ctrl+X cuts -> blocked
        ("h", 4, "win32", True),       # Text class Ctrl+H deletes -> blocked
        ("Tab", 0, "win32", True),     # inserts a tab character -> blocked
        ("Insert", 1, "win32", True),  # Shift+Insert pastes -> blocked
        ("Insert", 4, "win32", False), # Ctrl+Insert copies -> allowed
        ("c", 8, "darwin", False),     # Command+C on macOS -> allowed
        ("a", 8, "darwin", False),     # Command+A on macOS -> allowed
        ("v", 8, "darwin", True),      # Command+V on macOS -> blocked
        ("c", 8, "win32", True),       # 0x8 is Num Lock off macOS: no copy pass
        ("Left", 4, "win32", False),   # Ctrl+Left word jump -> allowed
    ],
)
def test_blocks_edit_per_platform(keysym, state, platform, expected):
    assert live_tab._blocks_edit(keysym, state, platform) is expected


@pytest.mark.parametrize(
    ("keycode", "expected"),
    [(67, False), (65, False), (45, False), (86, True), (88, True)],
)
def test_copy_works_with_a_non_latin_keyboard_layout(keycode, expected):
    """A Persian layout reports the layout's letter as the keysym."""
    assert live_tab._blocks_edit("Arabic_seen", 4, "win32", keycode) is expected
    assert live_tab._blocks_edit("Arabic_seen", 0, "win32", keycode) is True


def test_keys_and_paste_cannot_change_the_transcript(built, root):
    text = built.live_text
    live_tab._append_line(built, "kept line")
    before = text.get("1.0", "end")
    root.clipboard_clear()
    root.clipboard_append("PASTED")
    text.focus_force()
    root.update()
    for seq in ("<Tab>", "<Control-v>", "<Control-x>", "<Control-h>",
                "<Control-d>", "<Control-k>", "<Control-o>", "<Control-t>",
                "<BackSpace>", "<Delete>", "<Return>", "<Key-z>"):
        text.event_generate(seq, when="now")
    for virtual in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
        text.event_generate(virtual, when="now")
    root.update()
    assert text.get("1.0", "end") == before


# -------------------------------------------- dead mic / dead worker (S07-2)


def _health_session(**overrides):
    calls: list[str] = []
    ns = types.SimpleNamespace(
        calls=calls,
        drain_events=lambda limit=64: [],
        capture_error=lambda: "",
        input_signal_state=lambda: "ok",
        stop_capture=lambda: calls.append("capture"),
        wait_drained=lambda timeout=None: True,
        pending_chunks=lambda: 0,
        finish_recording=lambda: calls.append("finish") or "",
        keep_recording=False,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def _listening(built, session, transcriber=None):
    built.post_to_main = built.posted.append  # Tk-thread only, like the app
    built.live_session = session
    built.live_transcriber = transcriber or types.SimpleNamespace(
        stop=lambda: None, is_running=lambda: True
    )
    built._live_stop_reason = ""
    live_tab._set_running(built, True)
    built.live_status_var.set("Listening…")


def test_a_microphone_that_dies_is_shown_and_the_session_stops(built, root, monkeypatch):
    shown: list = []
    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: shown.append(kw.get("detail", "")))
    session = _health_session(capture_error=lambda: "Error querying device -1")
    _listening(built, session)

    live_tab._poll(built)
    assert "Error querying device -1" in built.live_status_var.get()
    _drain_posted(built, root, lambda: built.live_session is None)
    assert built.live_session is None
    assert shown == ["Error querying device -1"]
    assert "capture" in session.calls, "captured audio was not drained"
    assert built.live_status_var.get() == "Stopped: Error querying device -1"
    assert str(built.live_start_btn.cget("state")) == "normal"


def test_a_dead_worker_is_shown_and_the_session_stops(built, root, monkeypatch):
    shown: list = []
    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: shown.append(kw.get("detail", "")))
    _listening(built, _health_session(), types.SimpleNamespace(
        stop=lambda: None, is_running=lambda: False))

    live_tab._poll(built)
    _drain_posted(built, root, lambda: built.live_session is None)
    assert shown and "stopped unexpectedly" in shown[0]
    assert built.live_status_var.get().startswith("Stopped: ")


def test_a_fatal_event_stops_the_session_once(built, root, monkeypatch):
    from core.live import LiveEvent

    shown: list = []
    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: shown.append(kw.get("detail", "")))
    events = [LiveEvent(kind="fatal", detail="worker gone"),
              LiveEvent(kind="fatal", detail="worker gone")]
    session = _health_session(drain_events=lambda limit=64: list(events))
    _listening(built, session)

    live_tab._poll(built)
    _drain_posted(built, root, lambda: built.live_session is None)
    assert len(shown) == 1 and "worker gone" in shown[0]
    assert session.calls.count("capture") == 1


def test_a_fatal_event_during_exit_starts_nothing(built, monkeypatch):
    from core.live import LiveEvent

    monkeypatch.setattr(live_tab, "show_error",
                        lambda *a, **kw: pytest.fail("dialog during teardown"))
    session = _health_session(
        drain_events=lambda limit=64: [LiveEvent(kind="fatal", detail="x")])
    _listening(built, session)
    built._closing = True
    live_tab._poll_once(built)
    assert "capture" not in session.calls
    assert built._live_stop_reason == ""
    built.live_session = None


def test_failed_start_removes_the_session_folder(built, root, monkeypatch, tmp_path):
    import app.services.live_service as live_service
    from core import live as _live

    class FakeTranscriber:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

        def transcribe_chunk(self, path):
            return ""

        def stop(self):
            pass

    finished: list = []

    class FailingSession:
        def __init__(self, **kw):
            self.keep_recording = kw.get("keep_recording")

        def start(self):
            raise RuntimeError("device busy")

        def finish_recording(self):
            finished.append(self.keep_recording)
            return ""

    monkeypatch.setattr(live_service, "LiveTranscriber", FakeTranscriber)
    monkeypatch.setattr(_live, "LiveSession", FailingSession)
    monkeypatch.setattr(_live, "is_available", lambda mode="mic": True)
    monkeypatch.setattr(live_tab, "_prepare_live_model", lambda app, lang: None)
    monkeypatch.setattr(live_tab, "show_error", lambda *a, **kw: None)
    built.post_to_main = built.posted.append
    live_tab._start(built)
    _drain_posted(built, root, lambda: finished and "Idle" in built.live_status_var.get())
    assert finished == [False]


def test_lines_added_during_the_save_dialog_stay_unsaved(built, tmp_path, monkeypatch):
    out = tmp_path / "mine.txt"

    def dialog(**kw):
        live_tab._append_line(built, "arrived while the dialog was open")
        return str(out)

    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", dialog)
    live_tab._append_line(built, "line one")
    assert live_tab._save(built) is True
    assert out.read_text(encoding="utf-8").splitlines() == ["line one"]
    assert live_tab.has_unsaved_transcript(built), "the late line would be lost at exit"


def test_autosave_never_overwrites_and_picks_a_free_name(built, tmp_path, monkeypatch):
    built.app_config["download_folder"] = str(tmp_path)
    monkeypatch.setattr(live_tab.time, "strftime", lambda fmt: "20260101-000000")
    taken = tmp_path / "live-transcript-20260101-000000.txt"
    taken.write_text("older file", encoding="utf-8")
    live_tab._append_line(built, "new text")
    path = live_tab.autosave_unsaved_transcript(built)
    assert path.endswith("live-transcript-20260101-000000-2.txt")
    assert taken.read_text(encoding="utf-8") == "older file"


def test_no_signal_hint_comes_and_goes(built):
    state = {"value": "no_audio"}
    _listening(built, _health_session(input_signal_state=lambda: state["value"]))
    live_tab._check_health(built)
    assert built.live_status_var.get() == live_tab._NO_AUDIO_HINT
    state["value"] = "silent"
    live_tab._check_health(built)
    assert built.live_status_var.get() == live_tab._SILENT_HINT
    state["value"] = "ok"
    live_tab._check_health(built)
    assert built.live_status_var.get() == "Listening…"
    built.live_session = None


def test_poll_rearms_even_when_a_step_raises(built, monkeypatch):
    _listening(built, _health_session())

    def boom(app):
        raise RuntimeError("bad event")

    monkeypatch.setattr(live_tab, "_poll_once", boom)
    built._live_poll_scheduled = False
    live_tab._poll(built)
    assert built._live_poll_scheduled is True, "the transcript would freeze"
    built.live_session = None


# ------------------------------------------------ thread-safe log (S07-8)


def test_live_worker_gets_a_thread_safe_log(built, root, monkeypatch):
    import app.services.live_service as live_service
    from core import live as _live

    got: dict = {}

    class FakeTranscriber:
        def __init__(self, entry_file, *, language=None, log=None, model_slug=None):
            got["log"] = log

        def start(self):
            pass

        def transcribe_chunk(self, path):
            return ""

        def stop(self):
            pass

    class FakeSession:
        def __init__(self, **kw):
            got["keep"] = kw.get("keep_recording")

        def start(self):
            pass

    monkeypatch.setattr(live_service, "LiveTranscriber", FakeTranscriber)
    monkeypatch.setattr(_live, "LiveSession", FakeSession)
    monkeypatch.setattr(_live, "is_available", lambda mode="mic": True)
    monkeypatch.setattr(live_tab, "_prepare_live_model", lambda app, lang: None)
    built.post_to_main = built.posted.append
    live_tab._start(built)
    _drain_posted(built, root, lambda: "log" in got and built.live_session is not None)
    assert got["log"] is not built.log
    assert got["keep"] is False

    worker = threading.Thread(target=lambda: got["log"]("from the reader thread"))
    worker.start()
    worker.join()
    assert "from the reader thread" not in built.logged, "Tk touched off-thread"
    _drain_posted(built, root, lambda: "from the reader thread" in built.logged)
    assert "from the reader thread" in built.logged
    built.live_session = None


# ----------------------------------------------- the recording (S07-6)


@pytest.mark.parametrize("keep", [False, True])
def test_stop_applies_the_keep_audio_choice(built, root, keep):
    kept_path = "C:/cache/live/x/live-session.wav"
    session = _health_session()
    session.finish_recording = lambda: kept_path if session.keep_recording else ""
    _listening(built, session)
    built.live_keep_var.set(keep)
    live_tab._stop(built)
    _drain_posted(built, root, lambda: built.live_session is None)
    assert session.keep_recording is keep
    assert any(kept_path in m for m in built.logged) is keep


def test_keep_audio_choice_is_saved(built, monkeypatch):
    saved: list = []
    monkeypatch.setattr("core.config.save_config", lambda cfg: saved.append(dict(cfg)))
    built.live_keep_var.set(True)
    live_tab._on_keep_toggled(built)
    assert built.app_config["live_keep_recording"] is True
    assert saved and saved[-1]["live_keep_recording"] is True


# --------------------------------------------- nothing lost on exit (S07-5)


def test_exit_with_nothing_unsaved_asks_nothing(built, monkeypatch):
    from tkinter import messagebox

    monkeypatch.setattr(messagebox, "askyesnocancel",
                        lambda *a, **kw: pytest.fail("asked without unsaved text"))
    assert live_tab.save_before_exit(built) is True
    live_tab._append_line(built, "said")
    built._live_saved_count = 1
    assert live_tab.save_before_exit(built) is True


@pytest.mark.parametrize(
    ("answer", "dialog_path", "exits"),
    [(None, "", False), (False, "", True), (True, "", False), (True, "OUT", True)],
)
def test_exit_question_for_unsaved_text(built, monkeypatch, tmp_path,
                                        answer, dialog_path, exits):
    from tkinter import messagebox

    out = tmp_path / "t.txt"
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **kw: answer)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename",
                        lambda **kw: str(out) if dialog_path else "")
    live_tab._append_line(built, "hello there")
    assert live_tab.save_before_exit(built) is exits
    assert out.exists() is (dialog_path == "OUT")
    assert built._live_exit_discard is (answer is False)


def test_teardown_autosaves_unsaved_text_including_the_tail(built, tmp_path):
    from core.live import LiveEvent

    built.app_config["download_folder"] = str(tmp_path)
    live_tab._append_line(built, "first line")
    tail = [LiveEvent(kind="text", text="tail line")]
    built.live_session = types.SimpleNamespace(
        stop=lambda **kw: "",
        drain_events=lambda limit=64: [tail.pop()] if tail else [],
        finish_recording=lambda: "",
    )
    built.live_transcriber = types.SimpleNamespace(stop=lambda: None)
    live_tab.stop_live_session(built)
    files = list(tmp_path.glob("live-transcript-*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8").splitlines() == ["first line", "tail line"]
    assert any(str(files[0]) in m for m in built.logged)


def test_teardown_respects_a_no_to_saving(built, tmp_path):
    built.app_config["download_folder"] = str(tmp_path)
    live_tab._append_line(built, "throw away")
    built._live_exit_discard = True
    live_tab.stop_live_session(built)
    assert not list(tmp_path.glob("live-transcript-*.txt"))


def test_saved_text_is_not_autosaved_again(built, tmp_path, monkeypatch):
    built.app_config["download_folder"] = str(tmp_path)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename",
                        lambda **kw: str(tmp_path / "mine.txt"))
    live_tab._append_line(built, "saved by hand")
    assert live_tab._save(built) is True
    built._live_exit_discard = False
    live_tab.stop_live_session(built)
    assert not list(tmp_path.glob("live-transcript-*.txt"))


def test_theme_switch_recolours_the_model_picker(app, root, monkeypatch, tmp_path):
    """ttk styles belong to a theme and menu entries are not widgets: both are redone after a
    theme switch (card C2.61 review)."""
    sv_ttk = pytest.importorskip("sv_ttk")
    from app.theme import tokens

    monkeypatch.setattr(tokens, "_theme", "dark")
    sv_ttk.set_theme("dark", root)
    app.app_config["hub_folder"] = str(tmp_path)  # nothing downloaded: the grey entries
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack()
    root.update()
    dark = tokens.DARK_VARIANTS[tokens.TEXT_MISSING]
    style = ttk.Style(root)
    assert str(style.lookup(live_tab._MODEL_MISSING_STYLE, "foreground")) == dark

    def grey_entries() -> set[str]:
        menu = app.live_model_menu
        return {str(menu.entrycget(i, "foreground")) for i in range(menu.index("end") + 1)
                if menu.type(i) == "radiobutton" and "not downloaded" in menu.entrycget(i, "label")}

    assert grey_entries() == {dark}
    sv_ttk.set_theme("light", root)
    tokens.set_theme("light")
    live_tab.apply_theme(app)
    assert str(style.lookup(live_tab._MODEL_MISSING_STYLE, "foreground")) == tokens.TEXT_MISSING
    assert grey_entries() == {tokens.TEXT_MISSING}


# ------------------------------- English-only model + another language (C2.59b)
#
# tiny.en with Persian turned Persian speech into made-up English lines
# ("Ciao, ciao, ciao") with only a log warning. The tab now asks first.


@pytest.fixture
def ask(built, monkeypatch):
    """Answer the English-only dialog with ``ask.answer``; record each prompt."""
    from app.dialogs import english_only_model as dlg

    monkeypatch.setattr(live_tab, "_live_device", lambda app: "cpu")
    monkeypatch.setattr("core.config.save_config", lambda cfg: None)
    prompts: list = []

    def fake(master, prompt):
        prompts.append(prompt)
        return fake.answer

    fake.answer = dlg.CHOICE_CANCEL
    fake.prompts = prompts
    monkeypatch.setattr(dlg, "ask_english_only", fake)
    return fake


def _pick(built, slug, language):
    built.app_config["live_model"] = slug
    label = next(lbl for lbl, v in live_tab._live_model_choices(built) if v == slug)
    built.live_model_var.set(label)
    built.live_lang_var.set(language)


@pytest.mark.parametrize("slug,language,expected", [
    ("tiny.en", "English", None),
    ("tiny.en", "Persian", ("tiny.en", "small", "small", "cpu")),
    ("tiny.en", "Auto", ("tiny.en", "small", "small", "cpu")),
    ("distil-large-v3", "German", ("distil-large-v3", "small", "small", "cpu")),
    ("small", "Persian", None),
    ("auto", "Persian", None),       # Automatic picks a multilingual model on a CPU
])
def test_english_only_pair_decision(built, ask, slug, language, expected):
    _pick(built, slug, language)
    lang = live_tab._selected_language_code(built)
    assert live_tab._english_only_pair(built, lang) == expected


def test_main_model_counts_when_live_uses_it(built, ask):
    built.app_config["whisper_model"] = "medium.en"
    _pick(built, "main", "Persian")
    assert live_tab._english_only_pair(built, "fa") == ("medium.en", "small", "small", "cpu")


def test_automatic_on_a_gpu_with_an_english_only_main_model(built, ask, monkeypatch):
    monkeypatch.setattr(live_tab, "_live_device", lambda app: "cuda")
    built.app_config["whisper_model"] = "distil-large-v3"
    _pick(built, "auto", "Persian")
    assert live_tab._english_only_pair(built, "fa") == (
        "distil-large-v3", "large-v3-turbo", "large-v3-turbo", "cuda",
    )


def test_fine_pair_never_asks(built, ask):
    _pick(built, "tiny.en", "English")
    assert live_tab._confirm_model_language(built, on_start=True) is True
    _pick(built, "small", "Persian")
    assert live_tab._confirm_model_language(built, on_start=True) is True
    assert ask.prompts == []


def test_prompt_names_the_problem_and_the_fix(built, ask):
    _pick(built, "tiny.en", "Persian")
    live_tab._confirm_model_language(built, on_start=True)
    prompt = ask.prompts[0]
    assert prompt.model == "tiny.en" and prompt.alternative == "small"
    assert "Persian speech will come out as wrong English text" in prompt.problem()
    assert "Persian" in prompt.reason
    assert "500 MB" in prompt.recommendation() or "Already" in prompt.recommendation()


def test_switch_changes_the_live_model_and_lets_start_go_on(built, ask):
    from app.dialogs import english_only_model as dlg

    ask.answer = dlg.CHOICE_SWITCH
    _pick(built, "tiny.en", "Persian")
    assert live_tab._confirm_model_language(built, on_start=True) is True
    assert built.app_config["live_model"] == "small"
    assert live_tab._selected_live_value(built) == "small"
    assert len(ask.prompts) == 1  # the switch itself does not ask again


def test_switch_on_a_change_downloads_a_missing_model(built, ask, monkeypatch, tmp_path):
    from app.dialogs import english_only_model as dlg

    built.app_config["hub_folder"] = str(tmp_path)  # nothing downloaded
    fetched: list[str] = []
    monkeypatch.setattr(live_tab, "_download_live_model",
                        lambda app: fetched.append(live_tab._selected_live_value(app)))
    ask.answer = dlg.CHOICE_SWITCH
    _pick(built, "tiny.en", "Persian")
    assert live_tab._confirm_model_language(built, on_start=False) is True
    assert fetched == ["small"]


def test_keep_is_remembered_for_the_session(built, ask):
    from app.dialogs import english_only_model as dlg

    ask.answer = dlg.CHOICE_KEEP
    _pick(built, "tiny.en", "Persian")
    assert live_tab._confirm_model_language(built, on_start=True) is True
    assert built.app_config["live_model"] == "tiny.en"  # never switched silently
    assert live_tab._confirm_model_language(built, on_start=True) is True
    assert len(ask.prompts) == 1
    built.live_lang_var.set("German")  # a different pair asks again
    live_tab._confirm_model_language(built, on_start=True)
    assert len(ask.prompts) == 2


def test_cancel_stops_start_before_anything_runs(built, ask, monkeypatch):
    from core import live as _live

    monkeypatch.setattr(_live, "is_available", lambda mode="mic": True)
    _pick(built, "tiny.en", "Persian")
    live_tab._start(built)
    assert len(ask.prompts) == 1
    assert built.live_status_var.get() == "Idle."
    assert str(built.live_start_btn.cget("state")) == "normal"
    assert built.app_config["live_model"] == "tiny.en"


def test_choose_another_opens_the_model_menu(built, ask, monkeypatch, root):
    from app.dialogs import english_only_model as dlg

    opened: list = []
    monkeypatch.setattr(live_tab, "_open_model_menu", lambda app: opened.append(app))
    ask.answer = dlg.CHOICE_CHOOSE
    _pick(built, "tiny.en", "Persian")
    assert live_tab._confirm_model_language(built, on_start=True) is False
    deadline = time.time() + 2
    while not opened and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert opened == [built]


def test_changing_the_language_asks(built, ask, root):
    _pick(built, "tiny.en", "English")
    built.live_lang_var.set("Persian")
    built.live_lang_combo.event_generate("<<ComboboxSelected>>")
    root.update()
    assert len(ask.prompts) == 1


def test_changing_the_model_asks(built, ask):
    _pick(built, "small", "Persian")
    label = next(lbl for lbl, v in live_tab._live_model_choices(built) if v == "base.en")
    built.live_model_var.set(label)
    live_tab._on_live_model_selected(built)
    assert [p.model for p in ask.prompts] == ["base.en"]


def test_model_menu_marks_english_only_models(built):
    labels = _menu_labels(built)
    tiny_en = next(lbl for lbl in labels if lbl.startswith("Tiny (English)"))
    assert "English-only" in tiny_en
    tiny = next(lbl for lbl in labels if lbl.startswith("Tiny —"))
    assert "English-only" not in tiny
    distil = [lbl for lbl in labels if lbl.startswith("Distil")]
    assert distil and all(lbl.count("English-only") == 1 for lbl in distil)


def test_no_fallback_to_an_english_only_main_model(built, monkeypatch, tmp_path):
    """Reviewer finding: a failed download of the switched-to model fell back
    to the main model, which may itself be English-only."""
    monkeypatch.setattr("core.hardware.detect_device_for", lambda cfg: ("cpu", "int8"))

    def boom(cfg, *a, **kw):
        raise OSError("offline")

    monkeypatch.setattr("core.model_manager.ensure_model", boom)
    built.app_config.update(live_model="small", whisper_model="small.en",
                            hub_folder=str(tmp_path))
    with pytest.raises(RuntimeError, match="understands English only"):
        live_tab._prepare_live_model(built, "fa")
    with pytest.raises(RuntimeError, match="understands English only"):
        live_tab._prepare_live_model(built, None)
    # English speech may still fall back to it.
    assert live_tab._prepare_live_model(built, "en") is None
    # So may an unknown live model, unless the language rules it out.
    built.app_config["live_model"] = "no-such-model"
    assert live_tab._prepare_live_model(built, "en") is None
    with pytest.raises(RuntimeError, match="not in the model list"):
        live_tab._prepare_live_model(built, "fa")
