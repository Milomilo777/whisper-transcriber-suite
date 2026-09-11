"""Regression tests for AdvancedDialog's "Restore transcription defaults".

Scoped like Voice-Pro's own per-panel "Load Defaults" button (see
docs/SESSION_HANDOFF_NEXT.md, 2026-08-14 entry): only the settings that
shape a single transcription run get reset. Output formats, the
initial_prompt/hotwords text, model/backend choice, watched folder, and
every credential field must be left untouched -- those are persistent
choices, not per-job experiments a user wants to undo.

Runs against a SimpleNamespace fake with stub Vars -- no real Tk root.
"""
from __future__ import annotations

import types


class _V:
    """Minimal stand-in for a Tk *Var: .get()/.set() against one slot."""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _dirty_dialog(sync_calls: list[str]) -> types.SimpleNamespace:
    """A fake dialog with every touched field set AWAY from its default,
    plus a couple of untouched fields that must survive unchanged."""
    return types.SimpleNamespace(
        _vad_enabled=_V(False),
        _vad_min_silence=_V(1500),
        _vad_threshold=_V(0.2),
        _vad_speech_pad=_V(900),
        _hallucination_detect=_V(False),
        _alignment_enabled=_V(True),
        _demucs_enabled=_V(True),
        _denoise_enabled=_V(True),
        _denoise_level=_V("strong"),
        _auto_chapters_enabled=_V(False),
        _reset_hidden_tuning=False,
        _sync_vad_controls_state=lambda: sync_calls.append("vad_sync"),
        _sync_denoise_level_state=lambda: sync_calls.append("sync"),
        # Deliberately NOT reset -- persistent choices / user-authored text.
        _initial_prompt=_V("proper nouns: Acme Corp, Jane Doe"),
        _hotwords=_V("Acme, Doe"),
        _whisper_model=_V("small"),
        _cloud_api_key=_V("secret-key-value"),
    )


def test_restore_transcription_defaults_resets_only_the_tuning_knobs() -> None:
    from app.dialogs import advanced as adv

    sync_calls: list[str] = []
    dlg = _dirty_dialog(sync_calls)

    adv.AdvancedDialog._restore_transcription_defaults(dlg)  # type: ignore[arg-type]

    assert dlg._vad_enabled.get() is True
    assert dlg._vad_min_silence.get() == 500
    assert dlg._vad_threshold.get() == 0.5
    assert dlg._vad_speech_pad.get() == 400
    assert dlg._hallucination_detect.get() is True
    assert dlg._alignment_enabled.get() is False
    assert dlg._demucs_enabled.get() is False
    assert dlg._denoise_enabled.get() is False
    assert dlg._denoise_level.get() == "auto"
    assert dlg._auto_chapters_enabled.get() is True
    # batch_size has no control any more; its reset is queued for Save.
    assert dlg._reset_hidden_tuning is True

    # Persistent / user-authored fields must be left exactly as they were.
    assert dlg._initial_prompt.get() == "proper nouns: Acme Corp, Jane Doe"
    assert dlg._hotwords.get() == "Acme, Doe"
    assert dlg._whisper_model.get() == "small"
    assert dlg._cloud_api_key.get() == "secret-key-value"


def test_restore_transcription_defaults_resyncs_denoise_combobox_state() -> None:
    """_denoise_enabled is set programmatically, which does NOT fire the
    checkbutton's own `command` callback -- the strength combobox would
    stay stuck in whatever enabled/disabled state it was in before the
    reset unless _sync_denoise_level_state is called explicitly."""
    from app.dialogs import advanced as adv

    sync_calls: list[str] = []
    dlg = _dirty_dialog(sync_calls)

    adv.AdvancedDialog._restore_transcription_defaults(dlg)  # type: ignore[arg-type]

    assert sync_calls == ["vad_sync", "sync"], (
        "resetting _vad_enabled must re-sync the VAD sliders' "
        "enabled/disabled state, and resetting _denoise_enabled must "
        "re-sync the strength combobox's enabled/disabled state"
    )


def test_defaults_match_core_config_default_config() -> None:
    """The hand-picked reset values must not drift from DEFAULT_CONFIG."""
    from core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["vad_enabled"] is True
    assert DEFAULT_CONFIG["vad_min_silence_ms"] == 500
    assert DEFAULT_CONFIG["vad_threshold"] == 0.5
    assert DEFAULT_CONFIG["vad_speech_pad_ms"] == 400
    assert DEFAULT_CONFIG["batch_size"] == 16
    assert DEFAULT_CONFIG["hallucination_detect_enabled"] is True
    assert DEFAULT_CONFIG["demucs_enabled"] is False
    assert DEFAULT_CONFIG["denoise_enabled"] is False
    assert DEFAULT_CONFIG["denoise_level"] == "auto"
    assert DEFAULT_CONFIG["auto_chapters_enabled"] is True
    # "alignment" has no DEFAULT_CONFIG entry; an unchecked word-timing
    # checkbox saves "none", which is also what core treats a missing key
    # as, so unchecked is the correct reset target.
    assert "alignment" not in DEFAULT_CONFIG
