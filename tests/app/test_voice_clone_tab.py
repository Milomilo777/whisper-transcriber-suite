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
    from core import _threads, config, tts_kokoro, tts_plan, voice_clone

    calls: dict[str, Any] = {"generate": [], "install": 0, "status_at_install": None,
                             "kokoro": [], "measure": 0, "free": 10**12,
                             "omni_result": {"audio_seconds": 1.0, "elapsed_seconds": 2.0}}

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
            return {"output_path": output_path, **calls["omni_result"]}

    def fake_kokoro(text: str, voice: str, out: str, **_k: Any) -> Any:
        calls["kokoro"].append(text)
        return tts_kokoro.KokoroResult(out, len(text) / 20.0, len(text) / 40.0)

    def fake_measure(**_k: Any) -> Any:
        calls["measure"] += 1
        return tts_kokoro.KokoroResult("speed.wav", 10.0, 5.0)

    monkeypatch.setattr(voice_clone_service, "VoiceCloneWorker", FakeWorker)
    monkeypatch.setattr(voice_clone, "is_available", lambda: True)
    monkeypatch.setattr(voice_clone, "default_device", lambda: "cpu")
    monkeypatch.setattr(voice_clone, "session_work_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tts_kokoro, "is_downloaded", lambda: True)
    monkeypatch.setattr(tts_kokoro, "generate", fake_kokoro)
    monkeypatch.setattr(tts_kokoro, "measure_speed", fake_measure)
    # The speed store, versions and free space never touch the real profile.
    monkeypatch.setattr(tts_plan, "calibration_path", lambda: tmp_path / "speed.json")
    monkeypatch.setattr(tts_plan, "engine_version", lambda engine: f"{engine} 1.0")
    monkeypatch.setattr(tts_plan, "output_root", lambda: tmp_path)
    monkeypatch.setattr(tts_plan, "free_bytes", lambda _path: calls["free"])
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


# ----------------------------------------------------------------- the estimate before a long job

# About 4,000 characters: about 4 minutes of speech.
LONG = ("The quick brown fox jumps over the lazy dog. " * 90).strip()


def _engine(app: Any, engine: str, text: str, mode: str = vct._MODE_AUTO) -> None:
    app.vc_engine_var.set(engine)
    app.vc_mode_var.set(mode)
    vct._sync_engine(app)
    app.vc_text.insert("1.0", text)


def _confirm_shown(app: Any) -> bool:
    return app.vc_confirm_frame.winfo_manager() == "grid"


def _packed(btn: Any) -> bool:
    return btn.winfo_manager() == "pack"


def _stored(tmp_path: Any) -> dict:
    import json

    path = tmp_path / "speed.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else {}


def test_short_text_starts_without_the_confirm_step(root, fakes):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, "Hello there.")
    app.vc_generate_btn.invoke()
    assert fakes["kokoro"] == ["Hello there."]
    assert not _confirm_shown(app) and fakes["measure"] == 0
    assert app.vc_status_var.get().startswith("Done")


def test_cancel_on_the_confirm_step_runs_nothing(root, fakes, tmp_path):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    assert _packed(app.vc_confirm_measure_btn) and not _packed(app.vc_confirm_start_btn)
    assert "Measure this computer's speed first" in app.vc_confirm_var.get()
    assert _state(app) == "disabled"
    assert str(app.vc_text.cget("state")) == "disabled"

    app.vc_confirm_cancel_btn.invoke()
    assert fakes["measure"] == 0 and fakes["kokoro"] == []
    assert _stored(tmp_path) == {}
    assert not _confirm_shown(app)
    assert app.vc_status_var.get() == "Cancelled."
    assert str(app.vc_text.cget("state")) == "normal" and _state(app) == "normal"


def test_measured_speed_is_stored_shown_and_reused(root, fakes, tmp_path):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    app.vc_confirm_measure_btn.invoke()
    assert fakes["measure"] == 1
    assert _stored(tmp_path)["kokoro/cpu"]["source"] == "check"
    text = app.vc_confirm_var.get()
    assert "Time on this computer:" in text and "(measured on this computer)" in text
    assert "Speech:" in text and "MB (WAV)" in text and "Free disk space" in text
    assert _packed(app.vc_confirm_start_btn) and not _packed(app.vc_confirm_measure_btn)
    assert fakes["kokoro"] == []  # measuring is not starting

    app.vc_confirm_start_btn.invoke()
    assert fakes["kokoro"] == [LONG]
    assert not _confirm_shown(app)
    # The finished job (202 s of speech) replaces the short check.
    assert _stored(tmp_path)["kokoro/cpu"]["source"] == "run"

    app.vc_generate_btn.invoke()
    assert _confirm_shown(app) and fakes["measure"] == 1  # reused, not measured again
    assert _packed(app.vc_confirm_start_btn)
    assert "(measured on this computer)" in app.vc_confirm_var.get()
    app.vc_confirm_cancel_btn.invoke()


def test_not_enough_disk_space_refuses_the_job(root, fakes, tmp_path):
    fakes["free"] = 1000
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    assert "Not enough free disk space" in app.vc_confirm_var.get()
    assert "500 MB kept free" in app.vc_confirm_var.get()
    assert str(app.vc_confirm_measure_btn.cget("state")) == "disabled"
    vct._measure_speed(app)
    vct._confirm_start(app)
    assert fakes["measure"] == 0 and fakes["kokoro"] == []
    app.vc_confirm_cancel_btn.invoke()
    assert not _confirm_shown(app) and _state(app) == "normal"


def test_omnivoice_long_text_shows_the_reference_estimate(root, fakes):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG)
    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    text = app.vc_confirm_var.get()
    assert "estimated from a reference computer" in text
    assert "at least 8 seconds of speech" in text
    assert "downloads first" not in text  # installed
    assert _packed(app.vc_confirm_start_btn) and not _packed(app.vc_confirm_measure_btn)
    assert fakes["generate"] == []

    est = app.vc_plan.estimate
    app.vc_confirm_start_btn.invoke()
    assert len(fakes["generate"]) == 1
    call = fakes["generate"][0]
    assert call["text"] == LONG
    assert call["timeout_s"] == pytest.approx(est.time_high * 3)
    assert app.vc_status_var.get().startswith("Done")


def test_omnivoice_not_installed_says_it_downloads_first(root, fakes, monkeypatch):
    from core import voice_clone

    monkeypatch.setattr(voice_clone, "is_available", lambda: False)
    monkeypatch.setattr(voice_clone, "default_device",
                        lambda: pytest.fail("torch probed before the install"))
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG)
    app.vc_generate_btn.invoke()
    assert "OmniVoice downloads first (about 2 GB, one time)." in app.vc_confirm_var.get()
    app.vc_confirm_cancel_btn.invoke()
    assert fakes["install"] == 0


def test_a_finished_run_becomes_the_speed_figure(root, fakes, tmp_path):
    fakes["omni_result"] = {"audio_seconds": 20.0, "elapsed_seconds": 400.0}
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, "Hello there.")
    app.vc_generate_btn.invoke()  # short: no confirm step
    entry = _stored(tmp_path)["omnivoice/cpu"]
    assert (entry["source"], entry["compute_seconds"]) == ("run", 400.0)

    app.vc_text.delete("1.0", "end")
    app.vc_text.insert("1.0", LONG)
    app.vc_generate_btn.invoke()
    assert "Time on this computer:" in app.vc_confirm_var.get()
    app.vc_confirm_cancel_btn.invoke()


def test_short_runs_are_not_stored(root, fakes, tmp_path):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, "Hello there.")  # the fake returns 1 s of speech
    app.vc_generate_btn.invoke()
    assert fakes["generate"] and _stored(tmp_path) == {}


def test_failed_measurement_falls_back_to_start(root, fakes, monkeypatch, no_dialogs):
    from core import tts_kokoro

    def broken(**_k: Any) -> Any:
        raise RuntimeError("engine broke")

    monkeypatch.setattr(tts_kokoro, "measure_speed", broken)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    app.vc_confirm_measure_btn.invoke()
    assert no_dialogs == []
    assert "Could not measure" in app.vc_status_var.get()
    assert "on a typical computer" not in app.vc_confirm_var.get()
    assert "estimated from a reference computer" in app.vc_confirm_var.get()
    assert _packed(app.vc_confirm_start_btn)
    app.vc_confirm_start_btn.invoke()
    assert fakes["kokoro"] == [LONG]


def test_cancel_while_planning_keeps_a_loaded_worker(root, fakes, monkeypatch):
    stops = []
    real_plan = vct._make_plan

    class LoadedWorker:
        def is_running(self) -> bool:
            return True

        def stop(self) -> None:
            stops.append(1)

    app = _build(root, fakes)
    app.vc_worker = LoadedWorker()  # OmniVoice loaded by an earlier job

    def plan_then_cancel(*args: Any) -> Any:
        vct._cancel_generate(app)  # Cancel pressed while estimating
        return real_plan(*args)

    monkeypatch.setattr(vct, "_make_plan", plan_then_cancel)
    _engine(app, vct._ENGINE_OMNI, LONG)
    app.vc_generate_btn.invoke()
    assert stops == [] and fakes["generate"] == []
    assert app.vc_status_var.get() == "Cancelled." and not _confirm_shown(app)
    assert _state(app) == "normal"


def test_speed_is_locked_while_the_confirm_step_is_open(root, fakes):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG)
    app.vc_generate_btn.invoke()
    assert app.vc_speed_scale.instate(["disabled"])
    app.vc_confirm_cancel_btn.invoke()
    assert not app.vc_speed_scale.instate(["disabled"])


def test_start_checks_the_free_space_again(root, fakes):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG)
    app.vc_generate_btn.invoke()
    assert str(app.vc_confirm_start_btn.cget("state")) == "normal"
    fakes["free"] = 1000  # the disk filled up while the step was open
    app.vc_confirm_start_btn.invoke()
    assert fakes["generate"] == []
    assert _confirm_shown(app) and "Not enough free disk space" in app.vc_confirm_var.get()
    assert str(app.vc_confirm_start_btn.cget("state")) == "disabled"
    app.vc_confirm_cancel_btn.invoke()


def test_cancel_as_the_measurement_fails_closes_the_step(root, fakes):
    import threading

    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    event = threading.Event()
    event.set()  # Cancel was pressed before the failure reached the Tk thread
    vct._measure_failed(app, app.vc_plan, "engine broke", event)
    assert not _confirm_shown(app) and app.vc_status_var.get() == "Cancelled."
    assert fakes["kokoro"] == []


def test_cancel_while_measuring_starts_nothing(root, fakes, monkeypatch, tmp_path):
    from core import tts_kokoro

    app = _build(root, fakes)

    def cancelled_midway(cancel_event: Any = None, **_k: Any) -> Any:
        vct._cancel_generate(app)  # the user presses Cancel during the run
        assert cancel_event.is_set()
        raise RuntimeError("Cancelled.")

    monkeypatch.setattr(tts_kokoro, "measure_speed", cancelled_midway)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    app.vc_generate_btn.invoke()
    app.vc_confirm_measure_btn.invoke()
    assert not _confirm_shown(app)
    assert app.vc_status_var.get() == "Cancelled."
    assert fakes["kokoro"] == [] and _stored(tmp_path) == {}
    assert _state(app) == "normal"
