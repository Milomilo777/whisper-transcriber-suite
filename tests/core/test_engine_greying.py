r"""Regression tests for "grey out unusable engine/model combinations".

Hermetic — no Tk root, no network, no real ML backend. The pure
presentation helpers in ``core.backends.availability`` are exercised
directly; ``App`` UI methods run as unbound functions on a bare
``App.__new__(App)`` object with only the attributes each method touches
stubbed (the same pattern as tests/core/test_engine_selector.py).

Covered:
  1. engine_value_for_label — plain labels, "⚠ unavailable"-marked labels,
     and unknown input.
  2. engine_options — cheap readiness markers for the cloud engines (missing
     key => blocked/marked), and label round-tripping.
  3. blocked classification — whisper.cpp missing the package is blocked;
     NVIDIA Parakeet missing transformers is a first-use install (not
     blocked) while a broken import is blocked; Google Cloud missing the
     client is a first-use install (not blocked) while a missing key is.
  4. format_engine_status / engine_status_summary — the shared reason strings.
  5. App._apply_engine_status — caches the deep verdict, refreshes the
     combobox markers, and only blocked engines get the "set it up" pointer.
  6. App._on_engine_selected — a marked label still maps to its engine value
     (regression guard for the label<->value round-trip).
  7. App._sync_model_picker_for_engine / _model_picker_disabled_reason —
     the Whisper-model picker is disabled (with a hover reason) under every
     non-Faster-Whisper engine.
  8. App._refresh_engine_selector — clears stale cached deep verdicts after
     the Advanced dialog closes.
"""
from __future__ import annotations

import sys
import types

import pytest

from core.backends import availability as eng


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


class _Combo:
    """Minimal stand-in for the comboboxes' configure/cget surface."""

    def __init__(self, state: str = "readonly") -> None:
        self.state = state
        self.values: list[str] = []
        self.calls: list[dict] = []

    def configure(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))
        if "state" in kwargs:
            self.state = str(kwargs["state"])
        if "values" in kwargs:
            self.values = list(kwargs["values"])  # type: ignore[arg-type]

    def cget(self, key: str) -> str:
        if key == "state":
            return self.state
        raise KeyError(key)


class _Svc:
    def __init__(self) -> None:
        self.stop_all_calls = 0

    def stop_all(self) -> None:
        self.stop_all_calls += 1

    def active_workers(self) -> list:
        return []


def _bare_app(
    App,
    *,
    engine_label: str,
    backend: str = "faster_whisper",
    engine_combo: _Combo | None = None,
    deep: dict | None = None,
    with_model_picker: bool = True,
):
    a = App.__new__(App)
    a.transcribe_engine_var = _Var(engine_label)
    a.app_config = {"transcribe_backend": backend}
    a.transcription_service = _Svc()
    a.logs: list[str] = []
    a.log = a.logs.append
    a.engine_status_var = _Var("")
    a.engine_status_label = None
    a._engine_deep_statuses = {} if deep is None else deep
    if engine_combo is not None:
        a.transcribe_engine_combo = engine_combo
    if with_model_picker:
        a.transcribe_model_combo = _Combo()
        a.model_status_var = _Var("")
    a.after = lambda _ms, fn: fn()
    a.post_to_main = lambda fn: fn()
    return a


def _run_probe_inline(monkeypatch) -> None:
    """Make _refresh_engine_status's background thread run synchronously."""
    import app.app as app_mod

    class _InlineThread:
        def __init__(self, target=None, daemon=None, **_kw):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(app_mod.threading, "Thread", _InlineThread)


@pytest.fixture(autouse=True)
def _no_bundled_gcloud_key(monkeypatch):
    """Never let a real creds/gcloud_stt.json next to the app leak into
    these assertions (has_gcloud_key consults it)."""
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: "")


# ------------------------------------------------ 1. engine_value_for_label


def test_engine_value_for_label_plain_marked_and_unknown():
    label = eng.VALUE_TO_LABEL["cloud_stt"]
    assert eng.engine_value_for_label(label) == "cloud_stt"
    assert eng.engine_value_for_label(label + eng.UNAVAILABLE_MARK) == "cloud_stt"
    for bad in ("", "   ", None, "nonsense"):
        assert eng.engine_value_for_label(bad) is None


# ---------------------------------------------------- 2. engine_options


def test_engine_options_cheap_marks_blocked_cloud_engines():
    options = {o.value: o for o in eng.engine_options({}, deep=False)}

    fw = options["faster_whisper"]
    assert fw.ready is True and fw.blocked is False
    assert fw.display_label == fw.label

    for value in ("cloud_stt", "google_cloud_stt"):
        opt = options[value]
        assert opt.ready is False and opt.blocked is True
        assert opt.reason, "a blocked engine must carry its reason"
        assert opt.display_label.endswith(eng.UNAVAILABLE_MARK)
        assert eng.engine_value_for_label(opt.display_label) == value


def test_engine_options_cheap_unblocks_cloud_engines_with_creds(tmp_path):
    key = tmp_path / "key.json"
    key.write_text("{}", encoding="utf-8")
    cfg = {
        "cloud_stt_api_key": "gemini-key",
        "gcloud_stt_credentials_json": str(key),
    }

    options = {o.value: o for o in eng.engine_options(cfg, deep=False)}

    assert options["cloud_stt"].ready is True
    assert options["cloud_stt"].blocked is False
    assert options["google_cloud_stt"].ready is True
    assert options["google_cloud_stt"].display_label == (
        eng.VALUE_TO_LABEL["google_cloud_stt"]
    )


def test_engine_options_statuses_override_wins():
    st = eng.EngineStatus("whisper_cpp", False, "custom reason", blocked=True)
    options = {
        o.value: o
        for o in eng.engine_options({}, deep=False, statuses={"whisper_cpp": st})
    }
    assert options["whisper_cpp"].blocked is True
    assert options["whisper_cpp"].reason == "custom reason"
    assert eng.UNAVAILABLE_MARK in options["whisper_cpp"].display_label


# ------------------------------------------------ 3. blocked classification


def test_whisper_cpp_missing_package_is_blocked(monkeypatch):
    from core.backends import whisper_cpp as wc

    monkeypatch.setattr(wc, "is_available", lambda: False)
    monkeypatch.setattr(
        wc, "availability_reason", lambda: "pywhispercpp Python package not installed"
    )

    st = eng.engine_status("whisper_cpp", {}, deep=True)

    assert st.ready is False and st.blocked is True
    assert "pywhispercpp" in st.detail


def test_nvidia_missing_transformers_is_a_first_use_install(monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    st = eng.engine_status("nvidia_asr", {}, deep=True)

    assert st.ready is False
    assert st.blocked is False, (
        "transformers/torch install automatically on first use — a setup "
        "wait, not a dead end"
    )


def test_nvidia_broken_import_is_blocked(monkeypatch):
    import importlib.util

    from core.backends import availability

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def _boom() -> None:
        raise ImportError("tokenizers version clash")

    monkeypatch.setattr(availability, "_import_transformers", _boom)

    st = availability.engine_status("nvidia_asr", {}, deep=True)

    assert st.ready is False and st.blocked is True


def test_google_cloud_missing_client_is_a_first_use_install(monkeypatch):
    monkeypatch.setattr(eng, "has_gcloud_key", lambda cfg: True)
    from core.backends import google_cloud_stt as gcs

    monkeypatch.setattr(gcs, "runtime_available", lambda: False)

    st = eng.engine_status("google_cloud_stt", {}, deep=True)

    assert st.ready is False and st.blocked is False


def test_google_cloud_missing_key_is_blocked(monkeypatch):
    from core.backends import google_cloud_stt as gcs

    monkeypatch.setattr(gcs, "runtime_available", lambda: True)
    monkeypatch.setattr(eng, "has_gcloud_key", lambda cfg: False)

    st = eng.engine_status("google_cloud_stt", {}, deep=True)

    assert st.ready is False and st.blocked is True
    assert "service-account" in st.detail


def test_faster_whisper_unimportable_is_blocked(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    st = eng.engine_status("faster_whisper", {}, deep=True)

    assert st.ready is False and st.blocked is True


def test_faster_whisper_missing_model_is_a_download_wait(monkeypatch):
    monkeypatch.setattr(eng, "_faster_whisper_model_present", lambda cfg: False)

    st = eng.engine_status("faster_whisper", {}, deep=True)

    assert st.ready is False
    assert st.blocked is False
    assert "not downloaded" in st.detail.lower()


# ------------------------------------------ 4. format_engine_status / summary


def test_format_engine_status_variants():
    ready = eng.format_engine_status(eng.EngineStatus("x", True, "hint"))
    assert ready == "✓ Ready — hint"

    auto = eng.format_engine_status(
        eng.EngineStatus("x", False, "Model not downloaded yet")
    )
    assert auto == "⚠ Model not downloaded yet"
    assert "(set up" not in auto

    blocked = eng.format_engine_status(
        eng.EngineStatus("x", False, "paste a key", blocked=True)
    )
    assert blocked == "⚠ paste a key  (set up in Advanced settings…)"

    no_hint = eng.format_engine_status(
        eng.EngineStatus("x", False, "paste a key", blocked=True), action_hint=""
    )
    assert no_hint == "⚠ paste a key"


def test_engine_status_summary_names_every_engine_and_reason():
    text = eng.engine_status_summary({}, deep=False)

    for _label, value in eng.ENGINE_CHOICES:
        assert eng.VALUE_TO_LABEL[value] in text
    assert "API key" in text, "the blocked Gemini reason must be listed"


# ----------------------------------------- 5. App._apply_engine_status markers


def test_apply_engine_status_marks_blocked_engine_and_caches(App):
    label = eng.VALUE_TO_LABEL["whisper_cpp"]
    combo = _Combo()
    a = _bare_app(
        App, engine_label=label, backend="whisper_cpp", engine_combo=combo
    )
    st = eng.EngineStatus(
        "whisper_cpp", False, "pywhispercpp Python package not installed", blocked=True
    )

    App._apply_engine_status(a, "whisper_cpp", st)

    marked = label + eng.UNAVAILABLE_MARK
    assert a._engine_deep_statuses["whisper_cpp"] is st
    assert marked in combo.values
    assert a.transcribe_engine_var.get() == marked
    assert "pywhispercpp" in a.engine_status_var.get()
    assert "(set up in Advanced settings" in a.engine_status_var.get()


def test_apply_engine_status_auto_pending_has_no_action_pointer(App):
    label = eng.VALUE_TO_LABEL["faster_whisper"]
    a = _bare_app(App, engine_label=label, engine_combo=_Combo())
    st = eng.EngineStatus("faster_whisper", False, "Model not downloaded yet")

    App._apply_engine_status(a, "faster_whisper", st)

    text = a.engine_status_var.get()
    assert text.startswith("⚠")
    assert "not downloaded" in text.lower()
    assert "(set up" not in text


def test_apply_engine_status_drops_stale_result(App):
    a = _bare_app(
        App,
        engine_label=eng.VALUE_TO_LABEL["faster_whisper"],
        backend="faster_whisper",
    )
    st = eng.EngineStatus("whisper_cpp", False, "gone", blocked=True)

    App._apply_engine_status(a, "whisper_cpp", st)

    assert "whisper_cpp" not in a._engine_deep_statuses
    assert a.engine_status_var.get() == ""


# ------------------------------------------- 6. App._on_engine_selected labels


def test_on_engine_selected_accepts_marked_label(App, monkeypatch):
    label = eng.VALUE_TO_LABEL["cloud_stt"] + eng.UNAVAILABLE_MARK
    a = _bare_app(App, engine_label=label, backend="faster_whisper")
    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda cfg: saved.append(cfg))
    monkeypatch.setattr(
        eng, "engine_status", lambda value, cfg, deep=True: eng.EngineStatus(value, True, "")
    )

    App._on_engine_selected(a)

    assert a.app_config["transcribe_backend"] == "cloud_stt"
    assert a.transcription_service.stop_all_calls == 1
    assert len(saved) == 1


# ------------------------------------ 7. App model-picker greying + hover reason


def test_sync_model_picker_disables_it_for_cloud_engine(App):
    combo = _Combo()
    a = _bare_app(
        App, engine_label=eng.VALUE_TO_LABEL["cloud_stt"], backend="cloud_stt"
    )
    a.transcribe_model_combo = combo

    App._sync_model_picker_for_engine(a)

    assert combo.state == "disabled"
    assert a.model_status_var.get() == "Only used by Faster-Whisper"
    reason = App._model_picker_disabled_reason(a)
    assert "uses its own model" in reason
    assert "Faster-Whisper" in reason


def test_sync_model_picker_keeps_it_live_for_faster_whisper(App, monkeypatch):
    combo = _Combo(state="disabled")
    a = _bare_app(
        App,
        engine_label=eng.VALUE_TO_LABEL["faster_whisper"],
        backend="faster_whisper",
    )
    a.transcribe_model_combo = combo
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda cfg, slug: True)

    App._sync_model_picker_for_engine(a)

    assert combo.state == "readonly"
    assert a.model_status_var.get() == "✓ Downloaded"
    assert App._model_picker_disabled_reason(a) == ""


# --------------------------------------- 8. App._refresh_engine_selector cache


def test_refresh_engine_selector_clears_stale_deep_cache(App, monkeypatch):
    a = _bare_app(
        App,
        engine_label=eng.VALUE_TO_LABEL["faster_whisper"],
        backend="faster_whisper",
    )
    a._engine_deep_statuses["whisper_cpp"] = eng.EngineStatus(
        "whisper_cpp", False, "stale", blocked=True
    )
    _run_probe_inline(monkeypatch)

    App._refresh_engine_selector(a)

    assert "whisper_cpp" not in a._engine_deep_statuses, (
        "a cached verdict from before the Advanced dialog opened must not "
        "survive the re-sync"
    )
