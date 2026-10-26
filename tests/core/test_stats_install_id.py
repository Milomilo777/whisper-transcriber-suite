"""The per-install random id in usage statistics (not in problem reports).

The id lets the maintainer count distinct installs. It is random, lives only in config.json while the
usage-statistics switch is on, and is deleted when the switch is turned off.
"""
from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest

from core import problem_report, stats
from core.config import DEFAULT_CONFIG, LOCAL_ONLY_KEYS

_KW = dict(model="m", language="en", audio_duration=1.0, transcription_time=1.0, status="finished")


@pytest.fixture()
def saved(monkeypatch):
    """Record every save_config call the id code makes (no disk)."""
    calls: list[dict] = []
    import core.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "save_config", lambda c: calls.append(dict(c)))
    return calls


def _is_uuid4(text: str) -> bool:
    try:
        return str(uuid.UUID(text)) == text and uuid.UUID(text).version == 4
    except ValueError:
        return False


def test_default_config_has_an_empty_install_id_that_the_online_layer_cannot_set():
    assert DEFAULT_CONFIG["install_id"] == ""
    assert "install_id" in LOCAL_ONLY_KEYS


def test_id_is_created_once_as_uuid4_and_stored(saved):
    config = {"telemetry_opt_in": True}
    first = stats.install_id_for(config)
    assert _is_uuid4(first)
    assert config["install_id"] == first
    assert len(saved) == 1 and saved[0]["install_id"] == first
    assert stats.install_id_for(config) == first  # stable
    assert len(saved) == 1  # nothing re-saved


def test_two_installs_get_different_ids(saved):
    a, b = {"telemetry_opt_in": True}, {"telemetry_opt_in": True}
    assert stats.install_id_for(a) != stats.install_id_for(b)


def test_a_damaged_stored_id_is_replaced(saved):
    config = {"telemetry_opt_in": True, "install_id": "not-an-id"}
    assert _is_uuid4(stats.install_id_for(config))


def test_no_id_is_made_or_returned_while_stats_are_off(saved):
    config = {"telemetry_opt_in": False}
    assert stats.install_id_for(config) == ""
    assert "install_id" not in config and saved == []
    config["install_id"] = str(uuid.uuid4())
    assert stats.install_id_for(config) == ""  # a stale stored id is not sent either


def test_payload_carries_the_id_and_it_is_the_same_in_every_payload(saved):
    config = {"telemetry_opt_in": True}
    one = stats.build_stats_payload(**_KW, install_id=stats.install_id_for(config))
    two = stats.build_stats_payload(**_KW, install_id=stats.install_id_for(config))
    assert _is_uuid4(one["install_id"]) and one["install_id"] == two["install_id"]


def test_payload_without_an_id_has_no_install_id_field():
    assert "install_id" not in stats.build_stats_payload(**_KW)
    assert "install_id" not in stats.build_stats_payload(**_KW, install_id="")
    assert "install_id" not in stats.build_stats_payload(**_KW, install_id="C:\\Users\\bob")


def test_turning_stats_off_deletes_the_id_and_turning_on_makes_a_new_one(saved):
    config = {"telemetry_opt_in": True}
    old = stats.install_id_for(config)
    config["telemetry_opt_in"] = False
    stats.forget_install_id(config)
    assert config["install_id"] == ""
    config["telemetry_opt_in"] = True
    new = stats.install_id_for(config)
    assert _is_uuid4(new) and new != old


def test_forget_keeps_the_id_while_stats_are_on_and_adds_no_key():
    config = {"telemetry_opt_in": True, "install_id": str(uuid.uuid4())}
    keep = config["install_id"]
    stats.forget_install_id(config)
    assert config["install_id"] == keep
    bare = {"telemetry_opt_in": False}
    stats.forget_install_id(bare)
    assert bare == {"telemetry_opt_in": False}


def test_both_switch_handlers_forget_the_id():
    from app import app as app_mod
    from app.dialogs import advanced

    assert "forget_install_id" in inspect.getsource(app_mod.App._save_telemetry_pref)
    assert "forget_install_id" in inspect.getsource(advanced)


def test_the_service_passes_the_id_from_the_config():
    from app.services import transcription_service as ts

    assert "install_id_for(app.app_config)" in inspect.getsource(ts)


def test_problem_reports_never_carry_the_id():
    payload = problem_report.build_payload("it crashed")
    assert "install_id" not in payload
    assert "install_id" not in inspect.getsource(problem_report)


def test_server_script_stores_the_column():
    php = (Path(__file__).resolve().parents[2] / "platform" / "stats-server" / "transcription_stats.php").read_text(
        encoding="utf-8"
    )
    assert "'install_id'" in php and ":install_id" in php
