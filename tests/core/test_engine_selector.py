r"""Regression tests for the engine-selector feature (engine picker registry +
Transcribe-tab wiring).

Hermetic — no Tk root, no network, no real ML backend. Pure-function probes
in ``core.backends.availability`` / ``core.config`` are exercised directly;
``App`` UI methods are exercised as unbound functions on a bare
``App.__new__(App)`` object with only the attributes the method touches
stubbed (the App.__new__ + stubbed-attrs pattern from
test_fixpack_bl_appui.py).

Covered:
  1. normalise_engine — known/unknown/empty/None mapping to FALLBACK_ENGINE.
  2. default_engine — bundled-key vs explicit-cfg vs neither.
  3. has_gcloud_key / gcloud_key_path — explicit-on-disk wins, else bundled,
     else "".
  4. engine_status(deep=False) — the cheap Transcribe-tab probe for each
     engine.
  5. core.config defaults — _default_transcribe_backend stays offline even
     when a creds/gcloud_stt.json sits under resource_base() (the removed
     shared-credential default must not come back).
  6. App._on_engine_selected — persists the pick, restarts the worker exactly
     once on a real change, and is a no-op restart on a repeat selection.
  7. App._refresh_engine_status — the always-ready faster-whisper engine
     produces a "✓ ..." status line.
"""
from __future__ import annotations

import sys
import types

import pytest

from core.backends import availability as eng


# --------------------------------------------------------------------- fixtures


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
        # App._confirm_backend_switch (called by _on_engine_selected before
        # stop_all()) only prompts when this reports a worker with an
        # assigned task; empty means "nothing running, no prompt needed."
        return [{"task": object()}] if self._busy else []


def _bare_app(App, *, engine_label: str, backend: str, busy: bool = False):
    a = App.__new__(App)
    a.transcribe_engine_var = _Var(engine_label)
    a.app_config = {"transcribe_backend": backend}
    a.transcription_service = _Svc(busy=busy)
    a.logs = []
    a.log = a.logs.append
    a.engine_status_var = _Var("")
    a.engine_status_label = None
    # _refresh_engine_status now probes on a background thread and marshals
    # the result back via self.post_to_main — run callbacks inline
    # (synchronously, on the same thread) so the test can assert on the
    # final state without a real Tk event loop.
    a.after = lambda _ms, fn: fn()
    a.post_to_main = lambda fn: fn()
    return a


# ------------------------------------------------------- 1. normalise_engine


def test_normalise_engine_known_value_lowercased():
    assert eng.normalise_engine("Faster_Whisper") == "faster_whisper"
    assert eng.normalise_engine("google_cloud_stt") == "google_cloud_stt"


@pytest.mark.parametrize("value", ["bogus", "", None, "   "])
def test_normalise_engine_unknown_falls_back(value):
    assert eng.normalise_engine(value) == eng.FALLBACK_ENGINE


# ----------------------------------------------------------- 2. default_engine


def test_default_engine_no_key_anywhere(monkeypatch):
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: "")
    assert eng.default_engine({}) == "faster_whisper"


def test_default_engine_explicit_cfg_key(monkeypatch, tmp_path):
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: "")
    key = tmp_path / "my_key.json"
    key.write_text("{}", encoding="utf-8")
    cfg = {"gcloud_stt_credentials_json": str(key)}
    assert eng.default_engine(cfg) == "google_cloud_stt"


def test_default_engine_ignores_a_bundled_key(monkeypatch, tmp_path):
    """A key next to the app must NOT make cloud STT the default.

    Builds used to bundle a maintainer-owned service-account key and this
    default honoured it, so a fresh install transcribed through one shared
    cloud account without anyone opting in. The bundling is removed and the
    key revoked; the default must stay offline even if a key file reappears.
    """
    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: str(bundled))
    assert eng.default_engine({}) == "faster_whisper"


# ------------------------------------------------- 3. has_gcloud_key / path


def test_gcloud_key_path_explicit_on_disk_wins(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: str(bundled))

    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")
    cfg = {"gcloud_stt_credentials_json": str(explicit)}

    assert eng.gcloud_key_path(cfg) == str(explicit)
    assert eng.has_gcloud_key(cfg) is True


def test_gcloud_key_path_nonexistent_explicit_falls_back_to_bundled(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: str(bundled))

    cfg = {"gcloud_stt_credentials_json": str(tmp_path / "does_not_exist.json")}

    assert eng.gcloud_key_path(cfg) == str(bundled)
    assert eng.has_gcloud_key(cfg) is True


def test_gcloud_key_path_no_bundled_no_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: "")

    cfg = {"gcloud_stt_credentials_json": str(tmp_path / "missing.json")}
    assert eng.gcloud_key_path(cfg) == ""
    assert eng.has_gcloud_key(cfg) is False

    assert eng.gcloud_key_path({}) == ""
    assert eng.has_gcloud_key({}) is False


# -------------------------------------------------- 4. engine_status(deep=False)


def test_engine_status_shallow_faster_whisper_always_ready():
    st = eng.engine_status("faster_whisper", {}, deep=False)
    assert st.value == "faster_whisper"
    assert st.ready is True
    # detail may be empty (model present) or mention the first-run download.
    assert st.detail == "" or "download" in st.detail


def test_engine_status_shallow_google_cloud_stt_with_key(monkeypatch, tmp_path):
    key = tmp_path / "key.json"
    key.write_text("{}", encoding="utf-8")
    cfg = {"gcloud_stt_credentials_json": str(key)}
    st = eng.engine_status("google_cloud_stt", cfg, deep=False)
    assert st.ready is True
    assert st.detail == ""


def test_engine_status_shallow_google_cloud_stt_without_key(monkeypatch):
    monkeypatch.setattr(eng, "bundled_gcloud_key_path", lambda: "")
    st = eng.engine_status("google_cloud_stt", {}, deep=False)
    assert st.ready is False
    assert st.detail != ""


def test_engine_status_shallow_cloud_stt_key_present_and_absent():
    ready = eng.engine_status("cloud_stt", {"cloud_stt_api_key": "x"}, deep=False)
    assert ready.ready is True

    not_ready = eng.engine_status("cloud_stt", {}, deep=False)
    assert not_ready.ready is False


# --------------------------------------------------------- 5. config defaults


def test_default_backend_never_flips_to_cloud_for_a_bundled_key(
    monkeypatch, tmp_path
):
    """The default engine is offline, key on disk or not.

    Regression guard for the removed shared-credential default: a build used
    to ship a maintainer-owned creds/gcloud_stt.json and this default flipped
    to google_cloud_stt whenever that file existed, so every install silently
    transcribed through one shared cloud account. Even if a key reappears
    next to the app, the default must stay faster_whisper — a cloud backend
    is only ever reached by an explicit user choice.
    """
    import core.config as cfgmod
    import core.paths as pathsmod

    monkeypatch.setattr(pathsmod, "resource_base", lambda: str(tmp_path))

    # No creds/gcloud_stt.json -> offline.
    assert cfgmod._default_transcribe_backend() == "faster_whisper"

    # A key sitting next to the app must NOT change the default.
    creds_dir = tmp_path / "creds"
    creds_dir.mkdir(parents=True, exist_ok=True)
    (creds_dir / "gcloud_stt.json").write_text("{}", encoding="utf-8")

    assert cfgmod._default_transcribe_backend() == "faster_whisper"
    assert cfgmod.DEFAULT_CONFIG["transcribe_backend"] == "faster_whisper"

    # The key-sniffing helper is gone; its return value must never again
    # be wired into the default.
    assert not hasattr(cfgmod, "_bundled_gcloud_key_present")


# --------------------------------------------------- 6. App._on_engine_selected


def test_on_engine_selected_persists_and_restarts_once(App, monkeypatch):
    google_label = eng.VALUE_TO_LABEL["google_cloud_stt"]
    a = _bare_app(App, engine_label=google_label, backend="faster_whisper")

    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))

    App._on_engine_selected(a)

    assert a.app_config["transcribe_backend"] == "google_cloud_stt"
    assert a.transcription_service.stop_all_calls == 1
    assert len(saved) == 1


def test_on_engine_selected_asks_before_stopping_a_busy_worker(App, monkeypatch):
    """stop_worker() hard-terminates rather than cooperatively cancelling,
    so switching engines while something is actually transcribing must ask
    first. Declining must not touch config or stop the worker -- the
    dropdown reverts to the engine still actually in effect."""
    google_label = eng.VALUE_TO_LABEL["google_cloud_stt"]
    a = _bare_app(
        App, engine_label=google_label, backend="faster_whisper", busy=True
    )

    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **k: False)

    App._on_engine_selected(a)

    assert a.transcription_service.stop_all_calls == 0
    assert not saved
    assert a.app_config["transcribe_backend"] == "faster_whisper"
    assert a.transcribe_engine_var.get() == eng.VALUE_TO_LABEL["faster_whisper"]


def test_on_engine_selected_stops_busy_worker_when_confirmed(App, monkeypatch):
    """Confirming the prompt proceeds exactly like the no-prompt case."""
    google_label = eng.VALUE_TO_LABEL["google_cloud_stt"]
    a = _bare_app(
        App, engine_label=google_label, backend="faster_whisper", busy=True
    )

    saved: list[dict] = []
    monkeypatch.setattr("app.app.save_config", lambda _cfg: saved.append(_cfg))
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **k: True)

    App._on_engine_selected(a)

    assert a.app_config["transcribe_backend"] == "google_cloud_stt"
    assert a.transcription_service.stop_all_calls == 1
    assert len(saved) == 1

    # A second selection of the SAME engine must not re-persist or restart.
    App._on_engine_selected(a)

    assert a.transcription_service.stop_all_calls == 1
    assert len(saved) == 1


# ------------------------------------------------- 7. App._refresh_engine_status
#
# _refresh_engine_status now does a REAL (deep=True) readiness check on a
# background thread, after first painting an immediate "Checking…" line
# synchronously. To keep these tests hermetic and deterministic (no real
# model download, no thread-timing races), run the probe inline by
# monkeypatching threading.Thread to execute synchronously.


def _run_probe_inline(monkeypatch):
    """Make _refresh_engine_status's background thread run synchronously."""
    import threading as _threading

    class _InlineThread:
        def __init__(self, target=None, daemon=None, **_kw):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("app.app.threading.Thread", _InlineThread)
    _ = _threading  # keep the import referenced for clarity


def test_refresh_engine_status_paints_checking_then_real_result(App, monkeypatch):
    fw_label = eng.VALUE_TO_LABEL["faster_whisper"]
    a = _bare_app(App, engine_label=fw_label, backend="faster_whisper")
    _run_probe_inline(monkeypatch)

    monkeypatch.setattr(
        eng,
        "engine_status",
        lambda value, cfg, deep=True: eng.EngineStatus(value, True, ""),
    )

    App._refresh_engine_status(a)

    text = a.engine_status_var.get()
    assert text != ""
    assert text.startswith("✓")


def test_refresh_engine_status_faster_whisper_not_ready_without_model(App, monkeypatch):
    """The deep probe must report faster-whisper as NOT ready when its model
    folder is absent — this is the whole point of the real readiness check
    (the cosmetic cheap probe always said "Ready")."""
    fw_label = eng.VALUE_TO_LABEL["faster_whisper"]
    a = _bare_app(App, engine_label=fw_label, backend="faster_whisper")
    _run_probe_inline(monkeypatch)

    monkeypatch.setattr(eng, "_faster_whisper_model_present", lambda cfg: False)

    App._refresh_engine_status(a)

    text = a.engine_status_var.get()
    assert text.startswith("⚠")
    assert "not downloaded" in text.lower()


def test_refresh_engine_status_drops_stale_result_after_engine_switch(App, monkeypatch):
    """If the user switches engines while the probe is in flight, the late
    result for the OLD engine must be dropped (race guard)."""
    fw_label = eng.VALUE_TO_LABEL["faster_whisper"]
    gcloud_label = eng.VALUE_TO_LABEL["google_cloud_stt"]
    a = _bare_app(App, engine_label=fw_label, backend="faster_whisper")

    real_status = eng.engine_status

    def _slow_status(value, cfg, deep=True):
        # Simulate the user switching engines mid-probe.
        a.transcribe_engine_var.set(gcloud_label)
        a.app_config["transcribe_backend"] = "google_cloud_stt"
        return real_status(value, cfg, deep=deep)

    monkeypatch.setattr(eng, "engine_status", _slow_status)
    _run_probe_inline(monkeypatch)

    App._refresh_engine_status(a)

    text = a.engine_status_var.get()
    # The stale faster_whisper verdict must have been dropped — the line
    # still shows the synchronous "Checking…" placeholder, never a ✓/⚠
    # result computed for the engine the user has since switched away from.
    assert text == "Checking…"


def test_refresh_engine_status_falls_back_when_the_probe_never_answers(App, monkeypatch):
    """A deep probe that hangs (seen on macOS 10.15) must not leave
    "Checking…" up forever: the cheap status replaces it after a while."""
    fw_label = eng.VALUE_TO_LABEL["faster_whisper"]
    a = _bare_app(App, engine_label=fw_label, backend="faster_whisper")
    pending: list = []
    a.after = lambda _ms, fn: pending.append(fn)  # fire the timer by hand

    class _NeverThread:  # the probe thread never runs -> never answers
        def __init__(self, target=None, daemon=None, **_kw):
            pass

        def start(self):
            pass

    monkeypatch.setattr("app.app.threading.Thread", _NeverThread)
    monkeypatch.setattr(eng, "_faster_whisper_model_present", lambda cfg: True)

    App._refresh_engine_status(a)
    assert a.engine_status_var.get() == "Checking…"
    assert len(pending) == 1
    pending[0]()  # the fallback timer fires
    assert a.engine_status_var.get().startswith("✓")


def test_engine_status_fallback_keeps_a_real_answer(App, monkeypatch):
    fw_label = eng.VALUE_TO_LABEL["faster_whisper"]
    a = _bare_app(App, engine_label=fw_label, backend="faster_whisper")
    pending: list = []
    a.after = lambda _ms, fn: pending.append(fn)
    _run_probe_inline(monkeypatch)
    monkeypatch.setattr(
        eng, "engine_status",
        lambda value, cfg, deep=True: eng.EngineStatus(value, False, "deep verdict"),
    )
    App._refresh_engine_status(a)
    answered = a.engine_status_var.get()
    pending[0]()
    assert a.engine_status_var.get() == answered  # not overwritten


def test_cheap_status_names_the_selected_models_size(monkeypatch):
    monkeypatch.setattr(eng, "_faster_whisper_model_present", lambda cfg: False)
    st = eng.engine_status(
        "faster_whisper",
        {"whisper_model": "small", "model_path": "/definitely/missing"},
        deep=False,
    )
    assert "about 500 MB" in st.detail
