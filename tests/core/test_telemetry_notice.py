"""Disclosure precedes automatic telemetry for fresh and upgraded profiles."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import observability
from core import config, stats


def row():
    return stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                     transcription_time=1, status="finished")


@pytest.fixture(autouse=True)
def fresh_observer_policy(monkeypatch):
    monkeypatch.setattr(observability, "_CONFIG_PROVIDER", None)


@pytest.mark.parametrize("previous", [{}, {"install_id": "00000000-0000-4000-8000-000000000000"},
                                      {"telemetry_notice_version": 1}])
def test_unseen_disclosure_blocks_new_and_upgrade_stats(monkeypatch, previous):
    calls = []
    monkeypatch.setattr(stats, "_post", lambda *args: calls.append(args))
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/v1/runs", **previous}
    assert not stats.post_stats_async(cfg, row())
    assert calls == []


def test_online_config_cannot_assert_that_notice_was_shown():
    assert "telemetry_notice_version" in config.LOCAL_ONLY_KEYS
    merged = config.merge_config_sources(config.DEFAULT_CONFIG,
                                          {"telemetry_notice_version": 2}, {})
    assert merged.get("telemetry_notice_version", 0) == 0


def test_optional_observers_wait_for_the_same_disclosure(monkeypatch):
    cfg = {"telemetry_opt_in": True}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: cfg)
    monkeypatch.setattr(observability, "_note_skipped_while_offline", lambda *args: None)
    assert not observability._telemetry_opted_in()
    cfg["telemetry_notice_version"] = 2
    assert observability._telemetry_opted_in()
    cfg["telemetry_opt_in"] = False
    assert not observability._telemetry_opted_in()


@pytest.fixture
def ui(monkeypatch):
    from app.services import telemetry_notice as mod

    bars, saves, ready, callbacks = [], [], [], []
    app = SimpleNamespace(app_config={"telemetry_opt_in": True}, visible=True,
                          _closing=False, nb=object(), _quick_start_open=False,
                          winfo_viewable=lambda: app.visible,
                          after_idle=lambda fn: callbacks.append(fn),
                          after=lambda ms, fn: callbacks.append(fn),
                          _sync_telemetry_menu=lambda: None)

    class Bar:
        def __init__(self, parent, **commands):
            self.mapped = False
            self.hidden = False
            self.text = ""
            bars.append(self)

        def show(self, text, **kwargs):
            self.text = text

        def winfo_viewable(self):
            return self.mapped and app.visible and not self.hidden

        def hide(self):
            self.hidden = True

    monkeypatch.setattr(mod, "TelemetryBar", Bar)
    monkeypatch.setattr(mod, "save_config", lambda cfg: saves.append(dict(cfg)))
    controller = mod.TelemetryNotice(app, on_ready=lambda: ready.append(True))

    def tick():
        assert callbacks, "No disclosure callback was scheduled"
        callbacks.pop(0)()

    return SimpleNamespace(mod=mod, app=app, bars=bars, saves=saves, ready=ready,
                           tick=tick, callbacks=callbacks, controller=controller)


@pytest.mark.parametrize("enabled", [False, True])
def test_acknowledgement_is_saved_only_after_the_bar_is_mapped(ui, enabled):
    ui.app.app_config["telemetry_opt_in"] = enabled
    ui.controller.start()
    ui.tick()
    assert len(ui.bars) == 1
    assert not ui.ready and not ui.saves
    assert ui.app.app_config.get("telemetry_notice_version", 0) == 0
    ui.bars[0].mapped = True
    ui.tick()
    assert ui.app.app_config["telemetry_notice_version"] == 2
    assert ui.app.app_config["telemetry_opt_in"] is enabled
    assert len(ui.saves) == len(ui.ready) == 1


def test_hidden_or_minimized_start_never_marks_disclosure_seen(ui):
    ui.app.visible = False
    ui.controller.start()
    for _ in range(3):
        ui.tick()
    assert not ui.bars and not ui.ready and not ui.saves
    ui.app.visible = True
    ui.tick()
    assert len(ui.bars) == 1 and not ui.saves


def test_acknowledged_restart_does_not_create_a_second_bar(ui):
    ui.app.app_config["telemetry_notice_version"] = 2
    ui.controller.start()
    ui.tick()
    assert not ui.bars and ui.ready == [True] and not ui.saves


def test_turn_off_preserves_choice_and_hides_the_bar(ui):
    ui.controller.start()
    ui.tick()
    ui.bars[0].mapped = True
    ui.tick()
    ui.controller.turn_off()
    assert ui.app.app_config["telemetry_opt_in"] is False
    assert ui.saves[-1]["telemetry_opt_in"] is False
    assert ui.bars[0].hidden
    assert not stats.post_stats_async(ui.app.app_config, row())


def test_failed_persistence_keeps_notice_for_next_launch(ui, monkeypatch):
    def denied(cfg):
        raise OSError("test file unavailable")

    monkeypatch.setattr(ui.mod, "save_config", denied)
    ui.controller.start()
    ui.tick()
    ui.bars[0].mapped = True
    ui.tick()  # Display failure must not crash the app or silently enable sending.
    assert ui.app.app_config.get("telemetry_notice_version", 0) == 0
    assert not ui.ready


def test_failed_opt_out_save_warns_and_does_not_hide_bar(ui, monkeypatch):
    ui.controller.start()
    ui.tick()
    ui.bars[0].mapped = True
    ui.tick()

    def denied(cfg):
        raise OSError("test file unavailable")

    monkeypatch.setattr(ui.mod, "save_config", denied)
    ui.controller.turn_off()
    assert ui.app.app_config["telemetry_opt_in"] is False
    assert not ui.bars[0].hidden
    assert "could not be saved" in ui.bars[0].text


def test_failed_opt_out_save_closes_optional_observer_delivery(ui, monkeypatch):
    disk = {"telemetry_opt_in": True, "telemetry_notice_version": 2}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: dict(disk))
    observability.configure_telemetry(lambda: ui.app.app_config)
    ui.controller.start()
    ui.tick()
    ui.bars[0].mapped = True
    ui.tick()
    monkeypatch.setattr(ui.mod, "save_config", lambda cfg: (_ for _ in ()).throw(OSError("denied")))
    ui.controller.turn_off()
    assert not observability._telemetry_opted_in()
    callback = observability._sentry_options("https://example.invalid/1")["before_send"]
    assert callback({"message": "a technical failure"}, {}) is None


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


def test_notice_marker_survives_real_config_save_and_reload():
    cfg = config.load_config(fetch_online=False)
    cfg["telemetry_notice_version"] = 2
    config.save_config(cfg)
    assert config.load_config(fetch_online=False)["telemetry_notice_version"] == 2


def test_queued_sender_rechecks_disclosure_before_delivery(monkeypatch):
    pending, sent = [], []

    class Thread:
        def __init__(self, *, target, **kwargs):
            pending.append(target)

        def start(self):
            pass

    monkeypatch.setattr(stats.threading, "Thread", Thread)
    monkeypatch.setattr(stats, "_post", lambda *args: sent.append(args))
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2,
           "stats_url": "https://example.invalid/v1/runs"}
    assert stats.post_stats_async(cfg, row())
    cfg["telemetry_notice_version"] = 0
    pending[0]()
    assert sent == []


def test_start_is_idempotent_and_closing_window_never_stamps_notice(ui):
    ui.controller.start()
    ui.controller.start()
    assert len(ui.callbacks) == 1
    ui.app._closing = True
    ui.tick()
    assert not ui.callbacks and not ui.saves and not ui.ready and not ui.bars


def test_setup_dialog_does_not_count_as_viewing_the_bar(ui):
    ui.app._quick_start_open = True
    ui.controller.start()
    ui.tick()
    assert not ui.bars and not ui.saves
    ui.app._quick_start_open = False
    ui.tick()
    assert len(ui.bars) == 1 and not ui.saves


def test_live_config_replacement_and_matching_app_cleanup(monkeypatch):
    disk = {"telemetry_opt_in": True, "telemetry_notice_version": 2}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: disk)
    current = [dict(disk)]
    provider = lambda: current[0]
    observability.configure_telemetry(provider)
    assert observability._telemetry_opted_in()
    current[0] = {"telemetry_opt_in": False, "telemetry_notice_version": 2}
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
    disk = {"telemetry_opt_in": True, "telemetry_notice_version": 2}
    monkeypatch.setattr(config, "load_config", lambda **kwargs: disk)
    provider = lambda: disk
    observability.configure_telemetry(provider)
    callback = observability._sentry_options("https://example.invalid/1")["before_send"]
    observability.clear_telemetry(provider)
    assert callback({"message": "a technical failure"}, {}) is None


@pytest.mark.parametrize("replacement", [False, True])
def test_queued_ping_belongs_to_its_original_app(monkeypatch, replacement):
    from core import _threads

    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2}
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
