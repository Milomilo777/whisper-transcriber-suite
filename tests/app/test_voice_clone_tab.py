"""Tests for the voice-clone consent tick (app/widgets/voice_clone_tab.py).

Builds the tab on a real Tk root but never starts a worker, model or
download: the OmniVoice worker, installer and device probe are fakes.
Consent is a visible per-voice tick, not a one-time dialog: Generate stays
disabled for a clone until it is ticked, the tick reaches the worker as
``consent_accepted``, and no message box ever opens.
"""
from __future__ import annotations

import types
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from app.widgets import voice_clone_tab as vct  # noqa: E402


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


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    """Any message box or error dialog fails the test (the old gate was one)."""
    from tkinter import messagebox

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a message box opened")

    for name in ("askyesno", "askokcancel", "askyesnocancel", "showwarning",
                 "showinfo", "showerror"):
        monkeypatch.setattr(messagebox, name, boom)
    errors: list = []
    monkeypatch.setattr(vct, "show_error", lambda *a, **k: errors.append(a))
    return errors


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Hermetic stand-ins for everything Generate would really start."""
    from app.services import voice_clone_service
    from core import _threads, config, tts_kokoro, voice_clone

    calls: dict[str, Any] = {"generate": [], "install": 0, "status_at_install": None}

    class FakeWorker:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.running = False

        def start(self) -> None:
            self.running = True

        def is_running(self) -> bool:
            return self.running

        def stop(self) -> None:
            self.running = False

        def generate(self, text: str, samples: list, output_path: str, **kwargs: Any) -> dict:
            calls["generate"].append({"text": text, "samples": list(samples), **kwargs})
            return {"output_path": output_path, "audio_seconds": 1.0, "elapsed_seconds": 2.0}

    monkeypatch.setattr(voice_clone_service, "VoiceCloneWorker", FakeWorker)
    monkeypatch.setattr(voice_clone, "is_available", lambda: True)
    monkeypatch.setattr(voice_clone, "default_device", lambda: "cpu")
    monkeypatch.setattr(voice_clone, "session_work_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tts_kokoro, "is_downloaded", lambda: True)
    monkeypatch.setattr(config, "save_config", lambda *_a, **_k: None)
    # Run the generate thread inline so the test sees its result.
    monkeypatch.setattr(_threads, "safe_thread", lambda fn, **_k: fn())
    return calls


def _make_app(root: Any, config: "dict | None" = None) -> Any:
    a = types.SimpleNamespace()
    a.app_config = config if config is not None else {}
    a.entry_file = "gui.py"
    a.logged = []
    a.log = a.logged.append
    a.log_threadsafe = a.logged.append
    a.post_to_main = lambda fn: fn()
    a.after = lambda *_a, **_k: "after#0"  # no scratch sweep, no timers
    a.after_cancel = lambda *_a: None
    return a


def _build(root: Any, fakes: Any, config: "dict | None" = None) -> Any:
    app = _make_app(root, config)
    frame = ttk.Frame(root)
    vct.build_voice_clone_tab(app, frame)
    frame.pack(fill="both", expand=True)
    root.update()
    return app


def _clone_mode(app: Any, samples: "list[str] | None" = None) -> None:
    app.vc_engine_var.set(vct._ENGINE_OMNI)
    app.vc_mode_var.set(vct._MODE_CLONE)
    vct._sync_engine(app)
    if samples is not None:
        app.vc_samples[:] = samples
    app.vc_text.insert("1.0", "Hello there.")


def _state(app: Any) -> str:
    return str(app.vc_generate_btn.cget("state"))


def _tick(app: Any) -> None:
    app.vc_consent_check.invoke()


# ----------------------------------------------------------------- the tick


def test_clone_generate_is_disabled_until_the_tick(root, fakes):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav"])
    assert app.vc_consent_var.get() is False
    assert _state(app) == "disabled"
    app.vc_generate_btn.invoke()  # a disabled button does nothing
    assert fakes["generate"] == []

    _tick(app)
    assert app.vc_consent_var.get() is True
    assert _state(app) == "normal"
    _tick(app)
    assert _state(app) == "disabled"


@pytest.mark.parametrize("engine, mode", [
    (vct._ENGINE_OMNI, vct._MODE_DESIGN),
    (vct._ENGINE_OMNI, vct._MODE_AUTO),
    (vct._ENGINE_KOKORO, vct._MODE_CLONE),
])
def test_no_tick_needed_without_reference_audio(root, fakes, engine, mode):
    app = _build(root, fakes)
    app.vc_engine_var.set(engine)
    app.vc_mode_var.set(mode)
    vct._sync_engine(app)
    assert app.vc_consent_var.get() is False
    assert _state(app) == "normal"


def test_tick_reaches_the_worker_and_no_dialog_opens(root, fakes, no_dialogs):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav", "b.wav"])
    _tick(app)
    app.vc_generate_btn.invoke()  # first clone of this profile
    assert no_dialogs == []
    assert len(fakes["generate"]) == 1
    call = fakes["generate"][0]
    assert call["consent_accepted"] is True
    assert call["samples"] == ["a.wav", "b.wav"]
    assert app.vc_status_var.get().startswith("Done")
    assert "consent_accepted" not in app.app_config.get("voice_clone", {})


def test_unticked_clone_is_refused_without_a_dialog(root, fakes, no_dialogs):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav"])
    vct._generate(app)  # bypasses the disabled button
    assert fakes["generate"] == []
    assert no_dialogs == []
    assert "permission" in app.vc_status_var.get()


def test_design_mode_sends_no_consent(root, fakes):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav"])
    _tick(app)  # a tick left over from clone mode must not leak into design
    app.vc_mode_var.set(vct._MODE_DESIGN)
    vct._sync_engine(app)
    app.vc_generate_btn.invoke()
    call = fakes["generate"][0]
    assert call["consent_accepted"] is False
    assert call["samples"] == []


def test_old_config_consent_key_is_ignored(root, fakes):
    cfg = {"voice_clone": {"consent_accepted": True, "engine": "omnivoice", "mode": "clone"}}
    app = _build(root, fakes, cfg)
    app.vc_samples[:] = ["a.wav"]
    assert app.vc_consent_var.get() is False
    assert _state(app) == "disabled"


def test_changing_the_clips_clears_the_tick(root, fakes):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav"])
    _tick(app)
    vct._finish_adding_sample(app, "b.wav", None)
    assert app.vc_consent_var.get() is False
    assert _state(app) == "disabled"
    assert "tick the permission box again" in app.vc_status_var.get()

    _tick(app)
    vct._refresh_samples_listbox(app)
    app.vc_samples_listbox.selection_set(0)
    vct._remove_sample(app)
    assert app.vc_samples == ["b.wav"]
    assert app.vc_consent_var.get() is False
    assert _state(app) == "disabled"

    vct._finish_adding_sample(app, "c.wav", None)  # unticked: plain status
    assert app.vc_status_var.get() == "2 reference sample(s)."


def test_busy_keeps_generate_disabled_even_when_ticked(root, fakes):
    app = _build(root, fakes)
    _clone_mode(app, ["a.wav"])
    _tick(app)
    vct._set_busy(app, True)
    assert _state(app) == "disabled"
    _tick(app)
    _tick(app)
    assert _state(app) == "disabled"
    vct._set_busy(app, False)
    assert _state(app) == "normal"


# ----------------------------------------------------------------- texts


def test_rules_are_always_on_the_tab(root, fakes):
    app = _build(root, fakes)
    text = str(app.vc_rules_label.cget("text"))
    assert "AI-generated" in text
    assert "own voice" in text and "permission" in text
    assert "impersonate" in text and "misleading audio of real people" in text
    for engine in (vct._ENGINE_KOKORO, vct._ENGINE_OMNI):
        app.vc_engine_var.set(engine)
        vct._sync_engine(app)
        assert app.vc_rules_label.winfo_manager() == "grid"


def test_download_size_is_shown_where_the_install_starts(root, fakes, monkeypatch):
    from core import voice_clone

    app = _build(root, fakes)

    def fake_install(**_k: Any) -> bool:
        fakes["status_at_install"] = app.vc_status_var.get()
        return False

    monkeypatch.setattr(voice_clone, "is_available", lambda: False)
    monkeypatch.setattr(voice_clone, "ensure_installed", fake_install)
    app.vc_engine_var.set(vct._ENGINE_OMNI)
    app.vc_mode_var.set(vct._MODE_AUTO)
    vct._sync_engine(app)
    app.vc_text.insert("1.0", "Hello there.")
    app.vc_generate_btn.invoke()
    status = fakes["status_at_install"]
    assert status is not None and "2 GB" in status and "one time" in status
    assert "GB" not in vct._RULES_TEXT and "GB" not in vct._CONSENT_TICK_TEXT
