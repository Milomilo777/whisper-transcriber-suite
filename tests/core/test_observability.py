"""Tests for app.observability — Sentry gate + launch ping gate."""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def obs(monkeypatch):
    # Reload so module-level state is fresh per test.
    for m in [k for k in list(sys.modules) if k.startswith("app.observability")]:
        del sys.modules[m]
    import app.observability as o
    return o


def test_init_sentry_no_op_when_opt_out(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: False)
    assert obs.init_sentry() is False


def test_init_sentry_no_op_without_dsn(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert obs.init_sentry() is False


def test_init_sentry_runs_when_opt_in_and_dsn_set(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("SENTRY_DSN", "https://example.invalid/123")

    captured: dict = {}

    fake_mod = types.ModuleType("sentry_sdk")
    def _init(**kw):
        captured.update(kw)
    fake_mod.init = _init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_mod)

    assert obs.init_sentry() is True
    assert captured["dsn"] == "https://example.invalid/123"
    assert captured["send_default_pii"] is False


def test_launch_ping_skipped_without_opt_in(obs, monkeypatch):
    """opt_in=False → no thread spawned, no urlopen call."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: False)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    called = {"opened": False}
    monkeypatch.setattr(
        obs.urllib.request,
        "urlopen",
        lambda *_a, **_kw: called.__setitem__("opened", True) or types.SimpleNamespace(read=lambda: b""),
    )
    obs.send_launch_ping_async()
    # Daemon thread would have raced; we never spawned one, so the
    # call counter stays 0.
    import time
    time.sleep(0.1)
    assert called["opened"] is False


def test_launch_ping_skipped_without_url(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.delenv("WHISPER_TELEMETRY_URL", raising=False)
    obs.send_launch_ping_async()  # must not raise


def test_anonymised_id_is_stable(obs, monkeypatch, tmp_path):
    """Two calls in the same install yield the same id."""
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: tmp_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)
    a = obs._anonymised_id()
    b = obs._anonymised_id()
    assert a and a == b
    # The on-disk file matches what we returned.
    assert (tmp_path / "telemetry_id").read_text(encoding="utf-8").strip() == a


def test_init_sentry_swallows_sdk_init_failure(obs, monkeypatch):
    """A malformed DSN (or any other SDK init error) must not propagate.

    ``init_sentry`` is called unguarded from ``App.__init__``; an exception
    here aborts startup before the window exists."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("SENTRY_DSN", "not-even-a-url")

    fake_mod = types.ModuleType("sentry_sdk")

    def _init(**kw):
        raise RuntimeError("bad dsn")

    fake_mod.init = _init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_mod)

    assert obs.init_sentry() is False  # must not raise


def test_anonymised_id_empty_when_cache_dir_unavailable(obs, monkeypatch, tmp_path):
    """An unwritable cache path yields no id instead of raising."""
    blocker = tmp_path / "cache"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: blocker / "nested"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)

    assert obs._anonymised_id() == ""


def test_launch_ping_survives_unwritable_cache_dir(obs, monkeypatch, tmp_path):
    """The ping is best-effort on the Tk main thread: an id it cannot
    persist must be swallowed, not surfaced to the user as a launch crash."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    blocker = tmp_path / "cache"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: blocker / "nested"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)
    monkeypatch.setattr(
        obs.urllib.request,
        "urlopen",
        lambda *_a, **_kw: types.SimpleNamespace(read=lambda: b""),
    )

    obs.send_launch_ping_async()  # must not raise

    import time
    time.sleep(0.1)
