"""Tests for the simplified Advanced settings dialog (2026-09-12).

Two halves:

* SimpleNamespace fakes (no Tk), like test_advanced_model_change.py: the
  settings whose controls were removed from the dialog -- GPU batch size,
  the output filename template, the Download Videos tab's own "Transcribe
  after download" checkbox, and the never-wired voiceprint toggle -- must
  survive a Save untouched, and "Restore transcription defaults" must still
  reset batch size even though it no longer has a control.
* A real (withdrawn) Tk root for the contextual sections: only the setup
  section of the engine picked in the dialog is shown, and only the AI
  Layer rows of the picked LLM provider.
"""
from __future__ import annotations

import time
import types
from typing import Any

import pytest


class _V:
    """Minimal stand-in for a Tk *Var: .get()/.set() against one slot."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


def _fake_dialog(app: Any, **overrides: Any) -> types.SimpleNamespace:
    """What _save_and_close and _restore_transcription_defaults read."""
    fields: dict[str, Any] = dict(
        app=app,
        _vad_enabled=_V(True),
        _vad_min_silence=_V(500),
        _vad_threshold=_V(0.5),
        _vad_speech_pad=_V(400),
        _format_vars={"srt": _V(True)},
        _reset_hidden_tuning=False,
        _initial_prompt=_V(""),
        _hotwords=_V(""),
        _sb_vars={},
        _cookies_browser=_V("(off)"),
        _backend_display=_V("Faster-Whisper — offline, default"),
        _cloud_api_key=_V(""),
        _cloud_model=_V("gemini-3.5-flash"),
        _gcloud_credentials=_V(""),
        _gcloud_batch_mode=_V(False),
        _gcloud_bucket=_V(""),
        _gcloud_diarization=_V(False),
        _nvidia_model_id=_V(""),
        _alignment_enabled=_V(False),
        _hallucination_detect=_V(True),
        _demucs_enabled=_V(False),
        _denoise_enabled=_V(False),
        _denoise_level=_V("auto"),
        _ai_enabled=_V(False),
        _llm_provider_display=_V("Local — offline, downloaded model"),
        _llm_remote_base_url=_V("https://api.openai.com/v1"),
        _llm_remote_api_key=_V(""),
        _llm_remote_model=_V(""),
        _auto_chapters_enabled=_V(True),
        _model_display=_V("Large-v3"),
        _model_label_to_slug={"Large-v3": "large-v3"},
        _telemetry_opt_in=_V(False),
        _minimise_to_tray=_V(False),
        _watched_folder=_V(""),
        _watched_folder_enabled=_V(False),
        _sync_vad_controls_state=lambda: None,
        _sync_denoise_level_state=lambda: None,
        _teardown_mousewheel=lambda: None,
        destroy=lambda: None,
    )
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


def _fake_app(cfg: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        app_config=cfg,
        transcription_service=types.SimpleNamespace(stop_all=lambda: None),
        log=lambda _m: None,
    )


def _base_cfg() -> dict:
    return {
        "whisper_model": "large-v3",
        "transcribe_backend": "faster_whisper",
        "batch_size": 4,
        "output_filename_template": "{base}.{lang}.{ext}",
        "auto_transcribe_after_download": True,
        "voiceprint_enabled": False,
    }


def test_save_leaves_settings_without_a_control_untouched(monkeypatch) -> None:
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    cfg = _base_cfg()

    adv.AdvancedDialog._save_and_close(_fake_dialog(_fake_app(cfg)))  # type: ignore[arg-type]

    assert cfg["batch_size"] == 4
    assert cfg["output_filename_template"] == "{base}.{lang}.{ext}"
    assert cfg["auto_transcribe_after_download"] is True
    assert cfg["voiceprint_enabled"] is False


def test_restore_defaults_then_save_resets_hidden_batch_size(monkeypatch) -> None:
    from app.dialogs import advanced as adv
    from core.config import DEFAULT_CONFIG

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    cfg = _base_cfg()
    dlg = _fake_dialog(_fake_app(cfg), _alignment_enabled=_V(True))

    adv.AdvancedDialog._restore_transcription_defaults(dlg)  # type: ignore[arg-type]
    assert dlg._reset_hidden_tuning is True
    assert cfg["batch_size"] == 4, "nothing may be written before Save"

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]
    assert cfg["batch_size"] == DEFAULT_CONFIG["batch_size"]
    assert cfg["alignment"] == "none"
    # A naming choice, not a tuning knob: restore-defaults leaves it alone.
    assert cfg["output_filename_template"] == "{base}.{lang}.{ext}"


@pytest.mark.parametrize(("checked", "stored"), [(True, "stable_ts"), (False, "none")])
def test_word_timing_checkbox_maps_to_alignment_value(monkeypatch, checked, stored) -> None:
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    cfg = _base_cfg()

    adv.AdvancedDialog._save_and_close(
        _fake_dialog(_fake_app(cfg), _alignment_enabled=_V(checked))  # type: ignore[arg-type]
    )

    assert cfg["alignment"] == stored


# --------------------------------------------------------------- real Tk


@pytest.fixture
def make_dialog(monkeypatch, tmp_path):
    """Build real AdvancedDialogs on one withdrawn Tk root."""
    tk = pytest.importorskip("tkinter")
    from app.dialogs import advanced as adv
    from core.config import DEFAULT_CONFIG

    try:
        root = tk.Tk()
    except tk.TclError as e:  # no display available
        pytest.skip(f"Tk unavailable: {e}")
    root.withdraw()
    # Modality isn't under test, and a grab on a window whose parent is
    # withdrawn can fail on some window managers.
    monkeypatch.setattr(adv.AdvancedDialog, "grab_set", lambda self, *a, **k: None)
    made: list[Any] = []

    def _make(**cfg_overrides: Any) -> Any:
        cfg = dict(DEFAULT_CONFIG)
        cfg["hub_folder"] = str(tmp_path / "models")
        cfg.update(cfg_overrides)
        root.app_config = cfg  # type: ignore[attr-defined]
        root.log = lambda _m: None  # type: ignore[attr-defined]
        dlg = adv.AdvancedDialog(root)  # type: ignore[arg-type]
        made.append(dlg)
        return dlg

    try:
        yield _make
    finally:
        for dlg in made:
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        try:
            root.destroy()
        except tk.TclError:
            pass


def _shown_setup(dlg: Any) -> set[str]:
    return {
        value for value, frame in dlg._engine_setup_frames.items()
        if frame.winfo_manager() == "pack"
    }


def _nav_texts(dlg: Any) -> list[str]:
    return [
        str(w.cget("text")) for w in dlg._nav_links
        if w.winfo_class() == "TLabel" and str(w.cget("cursor")) == "hand2"
    ]


def test_default_engine_shows_no_engine_setup(make_dialog) -> None:
    dlg = make_dialog(transcribe_backend="faster_whisper")

    assert _shown_setup(dlg) == set()
    assert dlg._whisper_cpp_btn.winfo_manager() == ""
    nav = _nav_texts(dlg)
    assert nav[0] == "Model & engine"
    assert not {"Gemini setup", "Google Cloud setup", "Parakeet setup"} & set(nav)


@pytest.mark.parametrize(
    ("engine", "nav_label"),
    [
        ("cloud_stt", "Gemini setup"),
        ("google_cloud_stt", "Google Cloud setup"),
        ("nvidia_asr", "Parakeet setup"),
    ],
)
def test_picked_engine_shows_only_its_setup_right_below_model_and_engine(
    make_dialog, engine, nav_label,
) -> None:
    from app.dialogs.advanced import _BACKEND_VALUE_TO_LABEL

    dlg = make_dialog(transcribe_backend=engine)

    assert _shown_setup(dlg) == {engine}
    slaves = dlg._scroll_body.pack_slaves()
    assert slaves.index(dlg._engine_setup_frames[engine]) == (
        slaves.index(dlg._engine_section) + 1
    )
    assert _nav_texts(dlg)[:2] == ["Model & engine", nav_label]

    # Picking another engine in the dialog's own combobox hides it again.
    dlg._backend_display.set(_BACKEND_VALUE_TO_LABEL["faster_whisper"])
    dlg._sync_engine_sections()
    assert _shown_setup(dlg) == set()
    assert nav_label not in _nav_texts(dlg)


def test_whisper_cpp_button_only_for_whisper_cpp(make_dialog) -> None:
    dlg = make_dialog(transcribe_backend="whisper_cpp")

    assert dlg._whisper_cpp_btn.winfo_manager() == "grid"
    assert _shown_setup(dlg) == set()


def test_llm_provider_rows_follow_the_picked_provider(make_dialog) -> None:
    from app.dialogs.advanced import _LLM_PROVIDER_VALUE_TO_LABEL

    dlg = make_dialog(llm_provider="local")
    assert all(w.winfo_manager() == "grid" for w in dlg._llm_local_widgets)
    assert all(w.winfo_manager() == "" for w in dlg._llm_remote_widgets)

    dlg._llm_provider_display.set(_LLM_PROVIDER_VALUE_TO_LABEL["remote"])
    dlg._sync_llm_provider_rows()
    assert all(w.winfo_manager() == "" for w in dlg._llm_local_widgets)
    assert all(w.winfo_manager() == "grid" for w in dlg._llm_remote_widgets)


def test_remote_provider_opens_with_its_fields_visible(make_dialog) -> None:
    dlg = make_dialog(llm_provider="remote")

    assert all(w.winfo_manager() == "grid" for w in dlg._llm_remote_widgets)
    assert all(w.winfo_manager() == "" for w in dlg._llm_local_widgets)


def _all_texts(widget: Any) -> list[str]:
    texts: list[str] = []
    stack = [widget]
    while stack:
        w = stack.pop()
        try:
            texts.append(str(w.cget("text")))
        except Exception:  # noqa: BLE001 — widgets without a text option
            pass
        stack.extend(w.winfo_children())
    return texts


def test_removed_settings_are_gone(make_dialog) -> None:
    dlg = make_dialog(transcribe_backend="faster_whisper")

    joined = "\n".join(_all_texts(dlg))
    for gone in (
        "Batch size",
        "Output filename template",
        "voice fingerprint",
        "Transcribe after download",
    ):
        assert gone not in joined, gone


@pytest.mark.parametrize(
    ("engine", "expected_calls"), [("faster_whisper", 0), ("google_cloud_stt", 1)],
)
def test_gcloud_autotest_only_runs_when_google_cloud_is_picked(
    make_dialog, monkeypatch, engine, expected_calls,
) -> None:
    """The on-open connection test can pip-install the google-cloud
    libraries; it must not fire for someone who picked another engine."""
    from app.dialogs import advanced as adv
    from core.backends import availability

    calls: list[int] = []
    monkeypatch.setattr(availability, "has_gcloud_key", lambda _cfg: True)
    monkeypatch.setattr(
        adv.AdvancedDialog, "_test_gcloud_connection", lambda self: calls.append(1),
    )

    dlg = make_dialog(transcribe_backend=engine)
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline and not calls:
        dlg.update()
        time.sleep(0.02)

    assert len(calls) == expected_calls
