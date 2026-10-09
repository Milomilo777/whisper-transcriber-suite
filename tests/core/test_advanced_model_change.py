"""Regression tests for AdvancedDialog model-change worker restart (HIGH-4).

When the chosen Whisper model changes, _save_and_close used to rewrite
cfg['model']/['whisper_model']/['model_path'] but did NOT restart the worker,
so the OLD model kept transcribing until the process happened to restart. The
fix calls ``transcription_service.stop_all()`` on a model change so the next
transcribe spawns a fresh worker loading the new model.

Runs against SimpleNamespace fakes with stub Vars — no real Tk root.
"""
from __future__ import annotations

import types
from typing import Any


class _V:
    """Minimal stand-in for a Tk *Var: .get() returns a fixed value."""
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _advanced_fake(app, *, chosen_label, slug_map):
    """Build a SimpleNamespace carrying only what _save_and_close reads."""
    return types.SimpleNamespace(
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
        _cookies_browser_initial="(off)",
        _backend_display=_V("Faster-Whisper (local)"),
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
        _auto_chapters_enabled=_V(False),
        _model_display=_V(chosen_label),
        _model_label_to_slug=slug_map,
        _telemetry_opt_in=_V(False),
        _work_offline=_V(False),
        _update_check_enabled=_V(True),
        _yt_dlp_update_mode=_V("ask"),
        _caption_choice_var=_V("ask"),
        _minimise_to_tray=_V(False),
        _tts_no_text_limit=_V(False),
        _subtitle_edit_path=_V(""),
        _watched_folder=_V(""),
        _watched_folder_enabled=_V(False),
        _teardown_mousewheel=lambda: None,
        destroy=lambda: None,
    )


def _fake_app(cfg):
    stop_calls = {"count": 0, "idle": 0}
    svc = types.SimpleNamespace(
        stop_all=lambda: stop_calls.__setitem__("count", stop_calls["count"] + 1),
        restart_when_idle=lambda: stop_calls.__setitem__("idle", stop_calls["idle"] + 1),
    )
    app = types.SimpleNamespace(
        app_config=cfg,
        transcription_service=svc,
        log=lambda _m: None,
    )
    return app, stop_calls


def test_model_change_stops_worker(monkeypatch: Any) -> None:
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    dlg = _advanced_fake(app, chosen_label="Medium", slug_map={"Medium": "medium"})

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert cfg["whisper_model"] == "medium"
    assert stop_calls["count"] == 1, "changing the model must stop the live worker"


def test_same_model_does_not_stop_worker(monkeypatch: Any) -> None:
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    dlg = _advanced_fake(app, chosen_label="Large-v3", slug_map={"Large-v3": "large-v3"})

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert stop_calls["count"] == 0  # no change -> no worker restart


def test_google_cloud_stt_save_preserves_diarization(monkeypatch: Any) -> None:
    """Diarization is a real, working option on this backend (see
    core/backends/google_cloud_stt.py's SpeakerDiarizationConfig wiring in
    both Standard and Batch mode) -- _save_and_close must not silently wipe
    the user's checkbox choice back to False just because this backend is
    selected. Regression test for a stale guard that predated (or was never
    reconciled with) the backend's actual diarization support."""
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "google_cloud_stt"}
    app, stop_calls = _fake_app(cfg)
    dlg = _advanced_fake(
        app,
        chosen_label="Large-v3",
        slug_map={"Large-v3": "large-v3"},
    )
    dlg._gcloud_diarization = _V(True)
    dlg._backend_display = _V(
        "Google Cloud Speech-to-Text — service account (60 min/mo free)"
    )

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert cfg["gcloud_stt_diarization"] is True
    # Same backend + same model -> no worker restart (isolates diarization).
    assert stop_calls["count"] == 0


def test_backend_change_stops_worker(monkeypatch: Any) -> None:
    """Switching the engine (without a model change) must restart the worker.

    The live worker snapshots transcribe_backend at spawn and the dispatch
    prefers that stale value, so a fresh worker is required for the new engine
    to take effect.
    """
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    dlg = _advanced_fake(app, chosen_label="Large-v3", slug_map={"Large-v3": "large-v3"})
    dlg._backend_display = _V(
        "Google Cloud Speech-to-Text — service account (60 min/mo free)"
    )

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert cfg["transcribe_backend"] == "google_cloud_stt"
    assert stop_calls["count"] == 1, "switching the engine must restart the worker"
    assert stop_calls["idle"] == 0


def test_backend_change_skips_stop_all_when_switch_declined(monkeypatch: Any) -> None:
    """Declining App._confirm_backend_switch (a worker is busy) must still
    save the new backend but leave the active worker alone -- stop_all() is
    a hard terminate, not the cooperative per-task Cancel."""
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    app._confirm_backend_switch = lambda *_a, **_k: False
    dlg = _advanced_fake(app, chosen_label="Large-v3", slug_map={"Large-v3": "large-v3"})
    dlg._backend_display = _V(
        "Google Cloud Speech-to-Text — service account (60 min/mo free)"
    )

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    # The pick is still saved (the NEXT freshly-spawned worker will use it)...
    assert cfg["transcribe_backend"] == "google_cloud_stt"
    # ...but the busy worker was not force-stopped; it is marked to be
    # replaced once it is idle, so the saved engine really takes effect.
    assert stop_calls["count"] == 0
    assert stop_calls["idle"] == 1


def test_model_change_with_a_failed_save_leaves_the_worker_running(monkeypatch: Any) -> None:
    """The worker restart waits for the save: a failed save keeps the old
    model in memory AND must not hard-terminate a running transcription."""
    import tkinter.messagebox as mb

    from app.dialogs import advanced as adv

    def failing_save(_cfg: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(adv, "save_config", failing_save)
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    dlg = _advanced_fake(app, chosen_label="Medium", slug_map={"Medium": "medium"})

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert stop_calls["count"] == 0, "a failed save must not kill the running worker"
    assert cfg["whisper_model"] == "large-v3", "the unsaved model must be undone"


def test_model_change_asks_before_stopping_a_busy_worker(monkeypatch: Any) -> None:
    """Changing the model hard-stops a running job, so it asks like an engine
    switch does; declining still saves the model but leaves the worker alone."""
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    asked: list[dict[str, Any]] = []

    def decline(_parent: Any, **kwargs: Any) -> bool:
        asked.append(kwargs)
        return False

    app._confirm_backend_switch = decline  # type: ignore[attr-defined]
    dlg = _advanced_fake(app, chosen_label="Medium", slug_map={"Medium": "medium"})

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert len(asked) == 1 and asked[0]["action"] == "Changing the model"
    assert cfg["whisper_model"] == "medium"
    assert stop_calls["count"] == 0
    assert stop_calls["idle"] == 1, "the declined switch must still replace the worker later"


def test_model_and_engine_change_together_ask_once(monkeypatch: Any) -> None:
    from app.dialogs import advanced as adv

    monkeypatch.setattr(adv, "save_config", lambda _cfg: None)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )

    cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
    app, stop_calls = _fake_app(cfg)
    asked: list[Any] = []
    app._confirm_backend_switch = lambda *a, **k: asked.append(a) or True  # type: ignore[attr-defined]
    dlg = _advanced_fake(app, chosen_label="Medium", slug_map={"Medium": "medium"})
    dlg._backend_display = _V(
        "Google Cloud Speech-to-Text — service account (60 min/mo free)"
    )

    adv.AdvancedDialog._save_and_close(dlg)  # type: ignore[arg-type]

    assert len(asked) == 1
    assert stop_calls["count"] == 1
    assert stop_calls["idle"] == 0, "the accepted path stops the worker now, nothing is deferred"


def _download_fake(app: Any) -> Any:
    return types.SimpleNamespace(
        app=app,
        _model_display=_V("Medium"),
        _model_label_to_slug={"Medium": "medium"},
        _model_downloaded=lambda _slug: False,
        _teardown_mousewheel=lambda: None,
        grab_release=lambda: None,
        destroy=lambda: None,
    )


def test_download_now_with_a_failed_save_restores_the_model_choice(monkeypatch: Any) -> None:
    from app.dialogs import advanced as adv

    def failing_save(_cfg: Any) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(adv, "save_config", failing_save)
    monkeypatch.setattr(
        adv, "catalog_resolve_entry",
        lambda _cfg, slug: {"name": slug, "url": "u", "md5": "m"},
    )
    cfg = {"whisper_model": "large-v3", "model": {"name": "large-v3"}, "model_path": "keep"}
    app, _stop = _fake_app(cfg)
    app.after = lambda *_a, **_k: None  # type: ignore[attr-defined]

    adv.AdvancedDialog._download_selected_model(_download_fake(app))  # type: ignore[arg-type]

    assert cfg == {
        "whisper_model": "large-v3", "model": {"name": "large-v3"}, "model_path": "keep",
    }
