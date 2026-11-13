"""Default reporting does not depend on a retired UI or profile marker."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import observability
from app.widgets import update_bar
from app.services import telemetry_notice
from core import config, stats

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("legacy", [{}, {"telemetry_notice_version": 0},
                                     {"telemetry_notice_version": 1},
                                     {"telemetry_notice_version": "invalid"}])
def test_default_enabled_fresh_or_upgraded_profile_needs_no_marker(legacy):
    cfg = {**config.DEFAULT_CONFIG, **legacy}
    assert cfg["telemetry_opt_in"] is True
    assert stats.automatic_stats_allowed(cfg)
    cfg["telemetry_opt_in"] = False
    assert not stats.automatic_stats_allowed(cfg)


def test_saved_enabled_profile_does_not_need_marker(tmp_path):
    saved = tmp_path / "config.json"
    saved.write_text(json.dumps({"telemetry_opt_in": True}), encoding="utf-8")
    assert stats._saved_consent_allows(saved)
    saved.write_text(json.dumps({"telemetry_opt_in": False}), encoding="utf-8")
    assert not stats._saved_consent_allows(saved)


def test_diagnostics_do_not_depend_on_marker_but_still_wait_for_erasure():
    assert stats._ERASURE_DONE.wait(2)
    assert stats.diagnostics_enabled({"telemetry_opt_in": True})
    assert not stats.diagnostics_enabled({"telemetry_opt_in": False})


def test_optional_observers_use_live_enabled_choice_without_marker(monkeypatch):
    cfg = {"telemetry_opt_in": True}
    monkeypatch.setattr(observability, "_CONFIG_PROVIDER", lambda: cfg)
    assert observability._telemetry_opted_in()
    cfg["telemetry_opt_in"] = False
    assert not observability._telemetry_opted_in()


@pytest.mark.parametrize("turn_off", [False, True])
def test_queued_delivery_ignores_retired_marker_but_rechecks_switch(monkeypatch, turn_off):
    pending, sent = [], []
    class Deferred:
        def __init__(self, *, target, **kwargs): pending.append(target)
        def start(self): pass
    monkeypatch.setattr(stats.threading, "Thread", Deferred)
    monkeypatch.setattr(stats, "_saved_consent_allows", lambda path: True)
    monkeypatch.setattr(stats, "_post", lambda *args: sent.append(args))
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2,
           "stats_url": "https://example.invalid/v1/runs"}
    row = stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                    transcription_time=1, status="finished")
    assert stats.post_stats_async(cfg, row)
    cfg["telemetry_notice_version"] = 0
    if turn_off:
        cfg["telemetry_opt_in"] = False
    pending[0]()
    assert len(sent) == (0 if turn_off else 1)


def test_startup_cannot_construct_retired_telemetry_ui():
    tree = ast.parse((ROOT / "app/app.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "app.services.telemetry_notice"
                   for node in ast.walk(tree))
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App")
    init = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "_start_optional_telemetry" for node in ast.walk(init))
    assert not hasattr(update_bar, "TelemetryBar")
    assert not hasattr(telemetry_notice, "TelemetryNotice")


@pytest.mark.parametrize("spec", ["whisper_project_onefile.spec", "whisper_project_onedir.spec",
                                  "platform/macos/pyinstaller/whisper_project_mac.spec"])
def test_bundles_keep_nonexecuting_registry_compatibility_module(spec):
    assert "app.services.telemetry_notice" in (ROOT / spec).read_text(encoding="utf-8")
    shim = ast.parse((ROOT / "app/services/telemetry_notice.py").read_text(encoding="utf-8"))
    assert len(shim.body) == 1
    assert isinstance(shim.body[0], ast.Expr)
    assert isinstance(shim.body[0].value, ast.Constant) and isinstance(shim.body[0].value.value, str)


@pytest.mark.parametrize("failing", ["init_sentry", "send_launch_ping_async"])
def test_optional_sender_setup_failure_cannot_abort_startup_or_other_sender(monkeypatch, failing):
    import app.app as app_module
    calls = []
    def sender(name):
        def start():
            calls.append(name)
            if name == failing:
                raise RuntimeError("synthetic sender setup failure")
        return start
    for name in ("init_sentry", "send_launch_ping_async"):
        monkeypatch.setattr(app_module, name, sender(name))
    app_module.App._start_optional_telemetry(SimpleNamespace())
    assert calls == ["init_sentry", "send_launch_ping_async"]


def test_corrupt_launch_id_cannot_abort_startup_or_overwrite_existing_bytes(monkeypatch, tmp_path):
    import app.app as app_module
    from core import _threads
    identifier = tmp_path / "telemetry_id"
    identifier.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(config, "user_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(observability, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    monkeypatch.setattr(app_module, "init_sentry", lambda: None)
    created = []
    def refuse_thread(*args, **kwargs):
        created.append(True)
        pytest.fail("Corrupt ID must stop before networking")
    monkeypatch.setattr(_threads, "safe_thread", refuse_thread)
    app_module.App._start_optional_telemetry(SimpleNamespace())
    assert identifier.read_bytes() == b"\xff\xfe"
    assert created == []
