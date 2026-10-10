"""Help → Usage statistics: the menu item and the Advanced checkbox share one config key.

Constructing the real App needs a display and the whole config stack, so the menu wiring is
checked from the source (like test_app_init_order) and the two small handlers run on a stub.
The real menu was driven end to end on Windows for the change that added it.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import app.app as app_mod
from app.app import App, build_about_sections


class _Var:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


def _stub(var_value: bool, cfg: dict) -> SimpleNamespace:
    logs: list[str] = []
    return SimpleNamespace(app_config=cfg, telemetry_opt_in_var=_Var(var_value), log=logs.append, logs=logs)


def test_help_menu_has_the_stats_check_item_bound_to_the_config_key():
    src = inspect.getsource(App._build_menu)
    item = src[src.index("h.add_checkbutton("):]
    item = item[: item.index(")") + 1]
    assert 'label="Usage statistics"' in item
    assert "variable=self.telemetry_opt_in_var" in item
    assert "command=self._save_telemetry_pref" in item
    assert 'self.app_config.get("telemetry_opt_in", True)' in src


def test_advanced_dialog_close_resyncs_the_menu_item():
    src = inspect.getsource(App.open_advanced_dialog)
    assert src.index("self.wait_window(dlg)") < src.index("self._sync_telemetry_menu()")


@pytest.mark.parametrize("on", [False, True])
def test_menu_toggle_saves_the_choice(monkeypatch, on):
    saved: list[dict] = []
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: saved.append(dict(cfg)))
    stub = _stub(on, {"telemetry_opt_in": not on, "other": 1})
    App._save_telemetry_pref(stub)  # type: ignore[arg-type]
    assert stub.app_config["telemetry_opt_in"] is on
    assert saved == [{"telemetry_opt_in": on, "other": 1}]
    assert stub.logs and ("off" in stub.logs[-1]) is (not on)


def test_menu_toggle_reports_a_failed_save(monkeypatch):
    def boom(cfg):
        raise OSError("disk full")

    monkeypatch.setattr(app_mod, "save_config", boom)
    stub = _stub(False, {"telemetry_opt_in": True})
    App._save_telemetry_pref(stub)  # type: ignore[arg-type]
    assert stub.logs == ["Could not save preference: disk full"]


def test_sync_reads_the_config_written_by_the_advanced_dialog():
    stub = _stub(True, {"telemetry_opt_in": False})
    App._sync_telemetry_menu(stub)  # type: ignore[arg-type]
    assert stub.telemetry_opt_in_var.get() is False
    stub.app_config["telemetry_opt_in"] = True
    App._sync_telemetry_menu(stub)  # type: ignore[arg-type]
    assert stub.telemetry_opt_in_var.get() is True
    App._sync_telemetry_menu(SimpleNamespace(app_config={}))  # type: ignore[arg-type]  # menu not built yet


def test_about_names_both_switches_and_avoids_anonymous():
    text = " ".join(
        line for _title, subs in build_about_sections() for _sub, lines in subs for line in lines
    )
    assert "Help → Usage statistics" in text and "Advanced → App" in text
    assert "computer name" in text
    assert "anonymous" not in text.lower()


def test_about_does_not_list_the_file_name_as_sent():
    text = " ".join(
        line for _title, subs in build_about_sections() for _sub, lines in subs for line in lines
    )
    sent = text.split("What is sent:", 1)[1].split(";", 1)[0]
    assert "model" in sent  # the split found the list
    assert "file" not in sent.lower()
