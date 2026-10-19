"""The "Faster on this CPU" hint beside the Transcribe-tab model picker.

core.hardware.faster_cpu_model picks the lighter twin; App._cpu_speed_hint shows it only
once a worker has reported the CPU, never for the translate task (turbo cannot translate),
and logs the full sentence once per model. Hermetic: bare App objects, no Tk root.
"""
from __future__ import annotations

import sys
import types

import pytest

from core import hardware as hw


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


class _Var:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


def _bare_app(App, *, slug: str = "large-v3", on_cpu: bool = True, translate: bool = False):
    a = App.__new__(App)
    a.app_config = {"whisper_model": slug, "translate_to_english": translate}
    a.logs = []
    a.log = a.logs.append
    a.model_status_var = _Var("")
    a._engine_uses_whisper_model = lambda: True
    if on_cpu:
        a._runs_on_cpu = True
    return a


def test_faster_cpu_model_suggests_turbo_for_large_v3():
    faster, ratio = hw.faster_cpu_model("large-v3") or ("", 0.0)
    assert faster == "large-v3-turbo"
    assert ratio == pytest.approx(2.24 / 1.41)


@pytest.mark.parametrize("slug", ["large-v3-turbo", "small", "medium", "tiny", "not-a-model"])
def test_faster_cpu_model_none_without_a_lighter_twin(slug):
    assert hw.faster_cpu_model(slug) is None


def test_faster_cpu_model_none_for_translation():
    assert hw.faster_cpu_model("large-v3", translate=True) is None


def test_hint_shown_on_cpu_and_logged_once(App, monkeypatch):
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: True)
    a = _bare_app(App)

    App._refresh_model_status(a)
    App._refresh_model_status(a)

    assert a.model_status_var.get() == "Faster on this CPU: Large v3 Turbo (about 1.6x)"
    assert len(a.logs) == 1
    assert "Large v3 Turbo is about 1.6x faster" in a.logs[0]


def test_no_hint_before_the_cpu_is_known(App, monkeypatch):
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: False)
    a = _bare_app(App, on_cpu=False)

    App._refresh_model_status(a)

    assert a.model_status_var.get() == "Downloads automatically on first use"
    assert a.logs == []


@pytest.mark.parametrize("slug,translate", [("large-v3", True), ("small", False), ("large-v3-turbo", False)])
def test_no_hint_when_nothing_faster_fits(App, monkeypatch, slug, translate):
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: True)
    a = _bare_app(App, slug=slug, translate=translate)

    App._refresh_model_status(a)

    assert a.model_status_var.get() == "✓ Downloaded"
    assert a.logs == []


@pytest.mark.parametrize("kind,expected", [("cpu", True), ("cpu_downgraded", True), ("gpu", False)])
def test_device_badge_sets_the_cpu_flag_and_refreshes(App, kind, expected):
    a = App.__new__(App)
    a.device_badge_var = _Var("")
    a.device_badge_labels = []
    refreshed: list[bool] = []
    a._refresh_model_status = lambda: refreshed.append(True)
    a._runs_on_cpu = not expected  # a change of device must refresh the status line

    App.apply_device_badge(a, "badge", kind, {"device": "cpu" if expected else "cuda"})

    assert a._runs_on_cpu is expected
    assert refreshed == [True]
