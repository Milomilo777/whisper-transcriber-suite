r"""Regression tests for the Transcribe-tab Whisper-model picker.

Mirrors tests/core/test_engine_selector.py's structure and hermetic style
(no Tk root, no network, no real model download): App UI methods are
exercised as unbound functions on a bare App.__new__(App) object with only
the attributes each method touches stubbed.

Covered:
  1. core.model_manager.model_downloaded — true/false against a real
     tmp_path folder layout, and false for an unknown slug.
  2. App._on_model_selected — persists the pick, restarts the worker exactly
     once on a real change, is a no-op on a repeat selection, and leaves
     the config untouched (with a log line) for an unrecognised label.
  3. App._refresh_model_status — "Downloaded" vs "downloads on first use".
  4. App._refresh_model_selector — re-syncs the tab's var + label map to a
     slug changed elsewhere (e.g. by the Advanced dialog / model folder).
"""
from __future__ import annotations

import sys
import types

import pytest

from core import model_manager as mm
from core.hub import model_folder_for


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


class _Var:
    """Minimal stand-in for a tkinter StringVar."""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class _Svc:
    def __init__(self, busy: bool = False) -> None:
        self.stop_all_calls = 0
        self._busy = busy

    def stop_all(self) -> None:
        self.stop_all_calls += 1

    def active_workers(self) -> list:
        # _on_model_selected asks before stop_all() only when a worker has a
        # task (App._confirm_backend_switch); empty = nothing running.
        return [{"task": object()}] if self._busy else []


def _bare_app(App, *, model_label_to_slug: dict[str, str], model_label: str, whisper_model: str):
    a = App.__new__(App)
    a.transcribe_model_var = _Var(model_label)
    a._transcribe_model_label_to_slug = model_label_to_slug
    a.app_config = {"whisper_model": whisper_model}
    a.transcription_service = _Svc()
    a.logs = []
    a.log = a.logs.append
    a.model_status_var = _Var("")
    return a


# --------------------------------------------------- 1. model_downloaded


def test_model_downloaded_true_when_model_bin_present(tmp_path):
    entry_name = mm.MODEL_REGISTRY["tiny"]["name"]
    model_dir = model_folder_for(tmp_path, entry_name)
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"x")

    assert mm.model_downloaded({"hub_folder": str(tmp_path)}, "tiny") is True


def test_model_downloaded_false_when_missing(tmp_path):
    assert mm.model_downloaded({"hub_folder": str(tmp_path)}, "tiny") is False


def test_model_downloaded_false_for_unknown_slug(tmp_path):
    assert mm.model_downloaded({"hub_folder": str(tmp_path)}, "not-a-real-slug") is False


def test_model_downloaded_falls_back_to_default_hub_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr("core.hub.default_hub_folder", lambda: tmp_path)
    entry_name = mm.MODEL_REGISTRY["tiny"]["name"]
    model_dir = model_folder_for(tmp_path, entry_name)
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"x")

    assert mm.model_downloaded({}, "tiny") is True


# ---------------------------------------------------- 2. App._on_model_selected


def test_on_model_selected_persists_and_restarts_once(App, monkeypatch):
    label_to_slug = {
        "Tiny [needs download]": "tiny",
        "Large v3 [needs download]": "large-v3",
    }
    a = _bare_app(
        App,
        model_label_to_slug=label_to_slug,
        model_label="Tiny [needs download]",
        whisper_model="large-v3",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)

    assert a.app_config["whisper_model"] == "tiny"
    assert a.app_config["model"]["name"] == mm.MODEL_REGISTRY["tiny"]["name"]
    assert a.app_config["model_path"] == ""
    assert a.transcription_service.stop_all_calls == 1
    assert len(saved) == 1


def test_on_model_selected_noop_on_repeat_selection(App, monkeypatch):
    label_to_slug = {"Large v3 [needs download]": "large-v3"}
    a = _bare_app(
        App,
        model_label_to_slug=label_to_slug,
        model_label="Large v3 [needs download]",
        whisper_model="large-v3",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)

    assert saved == []
    assert a.transcription_service.stop_all_calls == 0


def test_on_model_selected_noop_when_label_map_missing(App, monkeypatch):
    """Guard clause: an empty/missing label->slug map (tab not fully built
    yet) must be a safe no-op, never a KeyError/crash."""
    a = _bare_app(
        App, model_label_to_slug={}, model_label="anything", whisper_model="large-v3",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)  # must not raise

    assert saved == []
    assert a.transcription_service.stop_all_calls == 0


def test_on_model_selected_unrecognised_label_falls_back_to_default_slug(App, monkeypatch):
    """A combobox label absent from a NON-empty label->slug map (a stale
    map, or a test double) falls back to DEFAULT_MODEL_SLUG via
    ``label_to_slug.get(label, DEFAULT_MODEL_SLUG)`` -- and since the
    config is already on that default, nothing changes."""
    a = _bare_app(
        App,
        model_label_to_slug={"Tiny [needs download]": "tiny"},  # no "Mystery model" entry
        model_label="Mystery model",
        whisper_model=mm.DEFAULT_MODEL_SLUG,
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)

    assert a.app_config["whisper_model"] == mm.DEFAULT_MODEL_SLUG
    assert saved == []
    assert a.transcription_service.stop_all_calls == 0


def test_on_model_selected_resolves_to_unknown_slug_logs_and_keeps_current(App, monkeypatch):
    """A label that DOES map to a slug, but one absent from the merged
    catalog (e.g. removed from an online model_catalog since the tab was
    built), must log and leave the current model untouched."""
    a = _bare_app(
        App,
        model_label_to_slug={"Ghost model": "ghost-slug"},
        model_label="Ghost model",
        whisper_model="large-v3",
    )
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)

    assert a.app_config["whisper_model"] == "large-v3"
    assert saved == []
    assert a.transcription_service.stop_all_calls == 0
    assert any("Unknown model slug" in m for m in a.logs)


# --------------------------------------------------- 3. App._refresh_model_status


def test_refresh_model_status_downloaded(App, monkeypatch):
    a = _bare_app(App, model_label_to_slug={}, model_label="", whisper_model="large-v3")
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: True)

    App._refresh_model_status(a)

    assert a.model_status_var.get() == "✓ Downloaded"


def test_refresh_model_status_not_downloaded(App, monkeypatch):
    a = _bare_app(App, model_label_to_slug={}, model_label="", whisper_model="large-v3")
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: False)

    App._refresh_model_status(a)

    assert "first use" in a.model_status_var.get()


# ------------------------------------------------- 4. App._refresh_model_selector


def test_refresh_model_selector_resyncs_after_external_change(App):
    """After the model changes elsewhere (Advanced dialog, or a folder
    change that only affects downloaded-status), the tab's own var + label
    map must follow -- mirroring _refresh_engine_selector."""
    a = _bare_app(
        App,
        model_label_to_slug={"Tiny [needs download]": "tiny"},
        model_label="Tiny [needs download]",
        whisper_model="tiny",
    )
    a.app_config["whisper_model"] = "large-v3"  # changed elsewhere

    App._refresh_model_selector(a)

    new_label = a.transcribe_model_var.get()
    assert new_label != "Tiny [needs download]"
    assert a._transcribe_model_label_to_slug.get(new_label) == "large-v3"


def test_refresh_model_selector_noop_without_a_var(App):
    """Must not raise when the Transcribe tab hasn't built the model
    picker yet (e.g. called too early during startup).

    transcribe_model_var must be explicitly set to None (not merely
    absent): tk.Misc.__getattr__ (App's base class) proxies any truly
    missing attribute to self.tk, which doesn't exist on a bare
    App.__new__(App) and recurses infinitely -- same gotcha documented
    in test_fixpack_bl_appui.py.
    """
    a = App.__new__(App)
    a.app_config = {"whisper_model": "large-v3"}
    a.transcribe_model_var = None

    App._refresh_model_selector(a)  # must not raise


@pytest.mark.parametrize("answer", [False, True])
def test_model_switch_asks_before_stopping_a_running_transcription(App, monkeypatch, answer):
    """stop_all() is a hard stop: switching models mid-transcription must ask
    (the engine picker already did; the model picker did not)."""
    label_to_slug = {"Tiny": "tiny", "Large v3": "large-v3"}
    a = _bare_app(App, model_label_to_slug=label_to_slug, model_label="Tiny",
                  whisper_model="large-v3")
    a.transcription_service = _Svc(busy=True)
    asked: list[str] = []

    def _ask(title, _msg, parent=None):
        asked.append(title)
        return answer

    monkeypatch.setattr("tkinter.messagebox.askyesno", _ask)
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_model_selected(a)

    assert asked == ["Change the Whisper model?"]
    if answer:
        assert a.app_config["whisper_model"] == "tiny"
        assert a.transcription_service.stop_all_calls == 1
    else:
        assert a.app_config["whisper_model"] == "large-v3"
        assert a.transcription_service.stop_all_calls == 0
        assert saved == []
        assert a.transcribe_model_var.get() == "Large v3"  # picker reverted
