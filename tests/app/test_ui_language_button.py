"""The interface-language button, its chooser, the View menu item and the restart question.

The first half needs no display: entries, saving, the restart rules. The second half builds the
real widgets on a withdrawn Tk root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import i18n
from app.dialogs import ui_language
from core import process_exit


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(i18n, "_WARNED", set())
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    monkeypatch.setattr(i18n, "_OS_LANGUAGE", [])
    monkeypatch.delenv(i18n.ENV_LANGUAGE, raising=False)
    folder = tmp_path / "locales"
    folder.mkdir()
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    for code, status in (("de", "reviewed"), ("fr", "machine")):
        lang = i18n.LANGUAGES_BY_CODE[code]
        doc = {"_meta": {"code": code, "name": lang.endonym, "direction": "ltr", "status": status,
                         "plural": lang.plural}, "messages": {}}
        (folder / f"{code}.json").write_text(json.dumps(doc), encoding="utf-8")
    process_exit.cancel_relaunch()
    i18n.set_language("en")
    yield
    process_exit.cancel_relaunch()
    i18n.set_language("en")


def _task(status: str) -> Any:
    return SimpleNamespace(status=status)


def _app(**kw: Any) -> Any:
    base: dict[str, Any] = dict(app_config={"ui_language": "auto"}, queue=[], download_queue=[],
                                _closing=False, _force_exit=lambda: None)
    base.update(kw)
    return SimpleNamespace(**base)


# --- entries ---------------------------------------------------------------------------------

def test_automatic_comes_first_and_names_the_language_it_gives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: "de-DE")
    entries = ui_language.chooser_entries("auto")
    assert entries[0] == ("Automatic (system: Deutsch)", "auto")


def test_automatic_names_english_when_the_system_language_has_no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: "ja-JP")
    assert ui_language.chooser_entries("auto")[0][0] == "Automatic (system: English)"


def test_english_is_pinned_right_below_automatic_and_listed_once() -> None:
    entries = ui_language.chooser_entries("auto")
    assert [v for _l, v in entries[:3]] == ["auto", "en", "de"]
    assert [v for _l, v in entries].count("en") == 1
    assert entries[1][0] == "English"


def test_a_setting_the_list_does_not_offer_is_kept_at_the_end() -> None:
    entries = ui_language.chooser_entries("qps-ploc")
    assert entries[-1][1] == "qps-ploc"


def test_the_button_shows_the_own_name_of_the_running_language() -> None:
    assert "English" in ui_language.button_text()
    i18n.set_language("de")
    assert "Deutsch" in ui_language.button_text()
    assert ui_language.button_text().endswith("▾")


# --- saving and the restart question ---------------------------------------------------------

def test_apply_choice_stores_the_value_in_ui_language(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ui_language, "save_config", lambda cfg: saved.append(dict(cfg)))
    monkeypatch.setattr(ui_language, "offer_restart", lambda *_a, **_k: None)
    app = _app()
    assert ui_language.apply_choice(app, "de") is True
    assert app.app_config["ui_language"] == "de" and saved == [{"ui_language": "de"}]


def test_a_failed_save_restores_the_old_value_and_offers_no_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_cfg: Any) -> None:
        raise OSError("disk full")

    shown: list[Any] = []
    offered: list[Any] = []
    monkeypatch.setattr(ui_language, "save_config", boom)
    monkeypatch.setattr(ui_language.messagebox, "showerror", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(ui_language, "offer_restart", lambda *a, **k: offered.append(a))
    app = _app()
    assert ui_language.apply_choice(app, "de") is False
    assert app.app_config["ui_language"] == "auto" and shown and not offered


@pytest.mark.parametrize(("statuses", "busy"), [
    ([], False), (["finished", "cancelled", "error"], False),
    (["waiting"], True), (["running"], True), (["paused"], True), (["finished", "running"], True),
])
def test_jobs_running_counts_every_task_that_is_not_done(statuses: list[str], busy: bool) -> None:
    assert ui_language.jobs_running(_app(queue=[_task(s) for s in statuses])) is busy
    assert ui_language.jobs_running(_app(download_queue=[_task(s) for s in statuses])) is busy


def _restartable(monkeypatch: pytest.MonkeyPatch, answers: list[tuple[str, bool]], answer: bool) -> None:
    monkeypatch.setattr(ui_language, "restart_supported", lambda: True)
    monkeypatch.setattr(process_exit, "relaunch_command", lambda: [sys.executable, "gui.py"])

    def ask(_app: Any, text: str, busy: bool) -> bool:
        answers.append((text, busy))
        return answer

    monkeypatch.setattr(ui_language, "ask_restart", ask)


def test_restart_now_requests_the_relaunch_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, bool]] = []
    _restartable(monkeypatch, asked, True)
    exits: list[bool] = []
    app = _app(_force_exit=lambda: (exits.append(process_exit.relaunch_requested()),
                                    setattr(app, "_closing", True)))
    ui_language.offer_restart(app, "de")
    assert asked == [("The interface language changes the next time you start the app.", False)]
    assert exits == [True]  # the relaunch was already requested when the exit began
    assert process_exit.relaunch_requested()


def test_later_does_nothing_more(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, bool]] = []
    _restartable(monkeypatch, asked, False)
    exits: list[int] = []
    ui_language.offer_restart(_app(_force_exit=lambda: exits.append(1)), "de")
    assert asked and exits == [] and not process_exit.relaunch_requested()


def test_a_declined_exit_cancels_the_relaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    # File > Exit asked about unsaved work and the person said Cancel: _closing stays False.
    _restartable(monkeypatch, [], True)
    ui_language.offer_restart(_app(), "de")
    assert not process_exit.relaunch_requested()


def test_a_running_job_is_passed_to_the_question(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, bool]] = []
    _restartable(monkeypatch, asked, False)
    ui_language.offer_restart(_app(queue=[_task("running")]), "de")
    assert asked[0][1] is True


def test_where_restart_is_unsupported_the_old_notice_is_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_language, "restart_supported", lambda: False)
    notices: list[str] = []
    ui_language.offer_restart(_app(), "de", notifier=lambda _w, text, kind="info": notices.append(text))
    assert notices == ["The interface language changes the next time you start the app."]


def test_nothing_is_said_when_the_running_language_already_is_the_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []
    _restartable(monkeypatch, asked, True)
    ui_language.offer_restart(_app(), "en")
    assert asked == []


def test_the_environment_override_is_explained_and_never_restarts(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []
    _restartable(monkeypatch, asked, True)
    monkeypatch.setenv(i18n.ENV_LANGUAGE, "qps-ploc")
    notices: list[str] = []
    ui_language.offer_restart(_app(), "de", notifier=lambda _w, text, kind="info": notices.append(text))
    assert asked == [] and "WTS_UI_LANGUAGE" in notices[0]


def test_the_advanced_dialog_save_asks_after_it_is_gone() -> None:
    """Static: Advanced settings destroys itself before the question (Restart now closes the app)."""
    import inspect

    from app.dialogs import advanced

    src = inspect.getsource(advanced.AdvancedDialog._save_and_close)
    assert src.index("self.destroy()") < src.index("self._notify_ui_language_restart(")


# --- real Tk ---------------------------------------------------------------------------------

@pytest.fixture
def tk_app(monkeypatch: pytest.MonkeyPatch):
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    root.app_config = {"ui_language": "auto"}  # type: ignore[attr-defined]
    root.queue = []  # type: ignore[attr-defined]
    root.download_queue = []  # type: ignore[attr-defined]
    root.open_ui_language_chooser = lambda: ui_language.open_chooser(root)  # type: ignore[attr-defined]
    monkeypatch.setattr(tk.Misc, "grab_set", lambda _self: None)
    monkeypatch.setattr(ui_language, "place_over", lambda *_a, **_k: None)
    try:
        yield root
    finally:
        root.destroy()


def test_tk_the_button_sits_top_right_with_the_icon_the_name_and_a_tooltip(tk_app: Any) -> None:
    from tkinter import ttk

    button = ui_language.build_button(tk_app, tk_app)
    tk_app.update_idletasks()
    assert isinstance(button, ttk.Button)
    assert "English" in str(button.cget("text")) and str(button.cget("compound")) == "left"
    assert str(button.cget("image")) != ""
    assert str(button.cget("takefocus")) in ("1", "True", "true")
    bar = button.master
    assert str(bar.pack_info()["side"]) == "top" and str(bar.pack_info()["fill"]) == "x"
    assert str(button.pack_info()["side"]) == "right"
    # Same place and same icon in a right-to-left interface: the bar is never mirrored.
    from app import rtl_layout

    assert getattr(bar, rtl_layout.KEEP_ATTR, False) is True


def test_tk_the_button_opens_the_chooser(tk_app: Any) -> None:
    button = ui_language.build_button(tk_app, tk_app)
    button.invoke()
    dlg = tk_app._ui_language_chooser
    assert dlg.winfo_exists()
    ui_language.open_chooser(tk_app)  # a second click raises the same window, no second one
    assert tk_app._ui_language_chooser is dlg


def _key(widget: Any, sequence: str) -> None:
    """Send a key event to a widget that has the keyboard focus (events need it on Windows)."""
    widget.update()
    widget.focus_force()
    widget.update()
    widget.event_generate(sequence)
    widget.update()


def _listbox(widget: Any) -> Any:
    if widget.winfo_class() == "Listbox":
        return widget
    for child in widget.winfo_children():
        found = _listbox(child)
        if found is not None:
            return found
    return None


def test_tk_chooser_marks_the_current_language_and_lists_automatic_then_english(tk_app: Any) -> None:
    ui_language.open_chooser(tk_app)
    box = _listbox(tk_app._ui_language_chooser)
    items = [box.get(i) for i in range(box.size())]
    assert items[0].lstrip().startswith("✓") and "Automatic (system:" in items[0]
    assert items[1].strip() == "English" and items[2].strip() == "Deutsch"
    assert [i for i in items if i.lstrip().startswith("✓")] == [items[0]]
    assert box.curselection() == (0,)


def test_tk_picking_a_language_saves_it_and_asks_about_the_restart(
        tk_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    asked: list[str] = []
    monkeypatch.setattr(ui_language, "save_config", lambda cfg: saved.append(cfg["ui_language"]))
    monkeypatch.setattr(ui_language, "offer_restart", lambda _app, value, **_k: asked.append(value))
    ui_language.open_chooser(tk_app)
    dlg = tk_app._ui_language_chooser
    box = _listbox(dlg)
    box.selection_clear(0, "end")
    box.selection_set(2)  # Deutsch
    _key(box, "<Return>")
    assert saved == ["de"] and asked == ["de"]
    assert tk_app._ui_language_chooser is None


def test_tk_picking_the_current_language_changes_nothing(tk_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_language, "save_config", lambda _cfg: pytest.fail("must not save"))
    ui_language.open_chooser(tk_app)
    _key(_listbox(tk_app._ui_language_chooser), "<Return>")
    assert tk_app.app_config["ui_language"] == "auto"


def test_tk_cancel_and_escape_close_without_saving(tk_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_language, "save_config", lambda _cfg: pytest.fail("must not save"))
    ui_language.open_chooser(tk_app)
    dlg = tk_app._ui_language_chooser
    _key(dlg, "<Escape>")
    assert tk_app._ui_language_chooser is None and not _exists(dlg)


def _exists(widget: Any) -> bool:
    try:
        return bool(widget.winfo_exists())
    except Exception:  # noqa: BLE001
        return False


def _buttons(widget: Any, out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    for child in widget.winfo_children():
        if child.winfo_class() == "TButton":
            out.append(str(child.cget("text")))
        _buttons(child, out)
    return out


@pytest.mark.parametrize(("busy", "expected"), [(False, ["Later", "Restart now"]), (True, ["Later"])])
def test_tk_restart_question_offers_restart_now_only_without_a_running_job(
        tk_app: Any, busy: bool, expected: list[str]) -> None:
    seen: list[list[str]] = []

    def peek(_ms: int, *_a: Any) -> None:
        for child in tk_app.winfo_children():
            if child.winfo_class() == "Toplevel":
                seen.append(sorted(_buttons(child)))
                child.destroy()

    tk_app.wait_window = lambda _dlg: peek(0)  # type: ignore[method-assign]
    assert ui_language.ask_restart(tk_app, "text", busy) is False
    assert seen == [sorted(expected)]


def test_tk_the_view_menu_item_opens_the_same_chooser() -> None:
    import tkinter as tk
    from unittest.mock import MagicMock

    from app import mac_native, shortcuts
    from tests.app.test_menu_and_empty_state import _menu_host

    mp = pytest.MonkeyPatch()
    mp.setattr(mac_native, "is_aqua", lambda _w: False)
    mp.setattr(shortcuts, "is_mac", lambda: False)
    try:
        root = _menu_host()
    except tk.TclError:
        mp.undo()
        pytest.skip("no display")
    try:
        root.open_ui_language_chooser = MagicMock(name="open_ui_language_chooser")  # type: ignore[attr-defined]
        root._build_menu()
        view = root.nametowidget(root._menubar.entrycget(1 + (1 if root._menubar.type(0) == "tearoff" else 0), "menu"))
        labels = [str(view.entrycget(i, "label")) for i in range(view.index("end") + 1) if view.type(i) == "command"]
        assert labels == ["Interface language…"]
        index = next(i for i in range(view.index("end") + 1) if view.type(i) == "command")
        view.invoke(index)
        root.open_ui_language_chooser.assert_called_once_with()
        assert str(root._menubar.index("end")) == str(2 + (1 if root._menubar.type(0) == "tearoff" else 0))  # still 3 menus
    finally:
        root.destroy()
        mp.undo()
