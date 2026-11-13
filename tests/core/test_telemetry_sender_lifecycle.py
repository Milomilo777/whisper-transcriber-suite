"""Optional senders remain bound to the current app and statistics choice."""
from types import SimpleNamespace
import pytest
from app import observability
from core import config, stats

@pytest.fixture(autouse=True)
def fresh_observer_policy(monkeypatch):
    monkeypatch.setattr(observability, "_CONFIG_PROVIDER", None)

def test_queued_launch_ping_rechecks_session_opt_out(monkeypatch):
    from core import _threads

    pending, sent = [], []
    enabled = [True]
    monkeypatch.setattr(observability, "_telemetry_opted_in", lambda: enabled[0])
    monkeypatch.setattr(observability, "_anonymised_id", lambda: "test-id")
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: pending.append(target))
    monkeypatch.setattr(observability.urllib.request, "urlopen",
                        lambda *args, **kwargs: sent.append(True) or SimpleNamespace(read=lambda: b""))
    observability.send_launch_ping_async()
    assert len(pending) == 1
    enabled[0] = False
    pending[0]()
    assert sent == []


def test_live_config_replacement_and_matching_app_cleanup(monkeypatch):
    disk = {"telemetry_opt_in": True}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: disk)
    current = [dict(disk)]
    provider = lambda: current[0]
    observability.configure_telemetry(provider)
    assert observability._telemetry_opted_in()
    current[0] = {"telemetry_opt_in": False}
    assert not observability._telemetry_opted_in()
    observability.clear_telemetry(lambda: disk)  # Another app cannot clear this policy.
    assert not observability._telemetry_opted_in()
    observability.clear_telemetry(provider)
    assert observability._telemetry_opted_in()  # Standalone fallback reads the disk again.


def test_queued_launch_ping_cannot_revive_after_rapid_off_on(monkeypatch):
    from core import _threads

    pending, sent = [], []
    monkeypatch.setattr(observability, "_telemetry_opted_in", lambda: True)
    monkeypatch.setattr(observability, "_anonymised_id", lambda: "test-id")
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: pending.append(target))
    monkeypatch.setattr(observability.urllib.request, "urlopen",
                        lambda *args, **kwargs: sent.append(True) or SimpleNamespace(read=lambda: b""))
    observability.send_launch_ping_async()
    stats.forget_install_id({"telemetry_opt_in": False})
    pending[0]()
    assert not sent


def test_sentry_callback_from_a_closed_app_cannot_use_old_disk_consent(monkeypatch):
    disk = {"telemetry_opt_in": True}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: disk)
    provider = lambda: disk
    observability.configure_telemetry(provider)
    callback = observability._sentry_options("https://example.invalid/1")["before_send"]
    observability.clear_telemetry(provider)
    assert callback({"message": "a technical failure"}, {}) is None


@pytest.mark.parametrize("replacement", [False, True])
def test_queued_ping_belongs_to_its_original_app(monkeypatch, replacement):
    from core import _threads

    cfg = {"telemetry_opt_in": True}
    provider = lambda: cfg
    observability.configure_telemetry(provider)
    monkeypatch.setattr(config, "load_config", lambda **kwargs: cfg)
    pending, sent = [], []
    monkeypatch.setattr(observability, "_anonymised_id", lambda: "test-id")
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: pending.append(target))
    monkeypatch.setattr(observability.urllib.request, "urlopen",
                        lambda *args, **kwargs: sent.append(True) or SimpleNamespace(read=lambda: b""))
    observability.send_launch_ping_async()
    assert len(pending) == 1
    if replacement:
        observability.configure_telemetry(lambda: dict(cfg))
    else:
        observability.clear_telemetry(provider)
    pending[0]()
    assert not sent
