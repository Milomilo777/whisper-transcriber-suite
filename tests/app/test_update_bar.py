"""The quiet update bar in the app: when it shows, its four buttons, the
passive signs, and the manual check. The rules themselves are tested without
Tk in tests/core/test_update_notice.py.

The App methods under test run on a small Tk host (a real root with a
notebook and a Help menu) instead of the full App, which needs the whole
config stack, a tray icon and the worker services.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.app as app_mod
from app.app import App
from app.widgets import update_bar as bar_mod
from app.widgets.notice import host_for
from core import updates as u

_TODAY = date(2026, 10, 6)
_ASSETS = (
    "WhisperTranscriberSuite-Installer-Windows-v1.9.4.exe",
    "WhisperTranscriberSuite-Portable-Windows-v1.9.4.zip",
    "WhisperTranscriberSuite-v1.9.4-macOS-arm64.dmg",
    "WhisperTranscriberSuite-v1.9.4-macOS-x64.dmg",
)
_PAGE = "https://github.com/o/r/releases/tag/v1.9.4"

_BORROWED = (
    "_on_update_result", "_save_update_prefs", "_show_update_bar", "_hide_update_bar",
    "_update_whats_new", "_update_download", "_update_later", "_update_skip",
    "_refresh_update_signs", "_apply_update_setting",
)


class _Host(tk.Tk):
    """A Tk root that runs the App's update-notice methods."""


for _name in _BORROWED:
    setattr(_Host, _name, getattr(App, _name))


def _info(tag: str = "v1.9.4", *, newer: bool = True, assets: tuple[str, ...] = _ASSETS) -> u.UpdateInfo:
    return u.UpdateInfo(
        latest_tag=tag, html_url=_PAGE, is_newer=newer,
        headline="Faster model loading and a calmer update notice.",
        highlights=("Models load in half the time.", "A quiet bar instead of a dialog."),
        assets=assets,
    )


@pytest.fixture
def boxes(monkeypatch):
    box = SimpleNamespace(showinfo=MagicMock(), askyesno=MagicMock(return_value=False))
    monkeypatch.setattr(app_mod, "messagebox", box)
    return box


@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: urls.append(url) or True)
    return urls


@pytest.fixture
def host(monkeypatch, boxes):
    saved: list[dict] = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(dict(c)))
    monkeypatch.setattr(app_mod, "_today", lambda: _TODAY)
    monkeypatch.setattr(app_mod, "_APP_VERSION", "1.9.3")
    monkeypatch.delenv(u.DISABLE_ENV_VAR, raising=False)
    root = _Host()
    root.withdraw()
    root.app_config = {  # type: ignore[attr-defined]
        "update_check_enabled": True, "update_latest_seen": "", "update_skipped_version": "",
        "update_snooze_count": 0, "update_snooze_until": "",
    }
    root._closing = False  # type: ignore[attr-defined]
    root._update_bar = None  # type: ignore[attr-defined]
    root._latest_update = None  # type: ignore[attr-defined]
    root._update_bar_shown_this_launch = False  # type: ignore[attr-defined]
    root.logs = []  # type: ignore[attr-defined]
    root.log = root.logs.append  # type: ignore[attr-defined]
    root.saved = saved  # type: ignore[attr-defined]
    root._install_kind = lambda: u.INSTALL_WINDOWS_INSTALLER  # type: ignore[attr-defined]
    root.nb = ttk.Notebook(root)  # type: ignore[attr-defined]
    root.nb.pack(fill="both", expand=True)  # type: ignore[attr-defined]
    menubar = tk.Menu(root)
    help_menu = tk.Menu(menubar, tearoff=0)
    help_menu.add_command(label=app_mod._CHECK_FOR_UPDATES_LABEL)
    root._help_menu = help_menu  # type: ignore[attr-defined]
    root._check_updates_index = help_menu.index("end")  # type: ignore[attr-defined]
    menubar.add_cascade(label=app_mod._HELP_MENU_LABEL, menu=help_menu)
    root._menubar = menubar  # type: ignore[attr-defined]
    root._help_cascade_index = menubar.index("end")  # type: ignore[attr-defined]
    root.config(menu=menubar)
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _bar_visible(host) -> bool:
    return host._update_bar is not None and host._update_bar.visible


def _labels(host) -> tuple[str, str]:
    return (
        str(host._menubar.entrycget(host._help_cascade_index, "label")),
        str(host._help_menu.entrycget(host._check_updates_index, "label")),
    )


# ------------------------------------------------------------ quiet launch check

def test_a_new_version_shows_the_bar_above_the_tabs(host, boxes):
    host._on_update_result(_info(), manual=False)
    assert _bar_visible(host)
    assert host._update_bar.text_var.get().startswith("Version 1.9.4 is available (you have 1.9.3).")
    slaves = host.pack_slaves()
    assert slaves.index(host._update_bar) < slaves.index(host.nb)
    assert [b.cget("text") for b in host._update_bar.buttons.values()] == [
        "What's new", "Download", "Later", "Skip this version",
    ]
    assert host.saved[-1]["update_latest_seen"] == "1.9.4"
    assert _labels(host) == ("Help ●", "Check for updates...  ● 1.9.4 available")
    boxes.showinfo.assert_not_called()
    boxes.askyesno.assert_not_called()


def test_the_bar_never_takes_focus_or_grabs_input(host, monkeypatch):
    calls: list[str] = []
    for name in ("focus_set", "focus_force", "grab_set", "grab_set_global"):
        monkeypatch.setattr(tk.Misc, name, lambda self, *a, _n=name, **k: calls.append(_n))
    host._on_update_result(_info(), manual=False)
    host.update_idletasks()
    assert _bar_visible(host)
    assert calls == []
    assert [w for w in host.winfo_children() if isinstance(w, tk.Toplevel)] == []


def test_the_bar_shows_at_most_once_per_launch(host):
    host._on_update_result(_info(), manual=False)
    host._hide_update_bar()
    host._on_update_result(_info(), manual=False)  # the next day's check, same launch
    assert not _bar_visible(host)


def test_a_bar_left_open_follows_a_newer_release(host, opened):
    host._on_update_result(_info(), manual=False)
    host._on_update_result(_info("v1.9.5", assets=tuple(a.replace("1.9.4", "1.9.5") for a in _ASSETS)),
                           manual=False)  # a day later, the bar still unanswered
    assert _bar_visible(host)
    assert host._update_bar.text_var.get().startswith("Version 1.9.5 is available")
    host._update_bar.buttons["download"].invoke()
    assert opened == [u.asset_download_url("v1.9.5", _ASSETS[0].replace("1.9.4", "1.9.5"))]


def test_turning_the_check_off_in_advanced_hides_the_bar(host):
    host._on_update_result(_info(), manual=False)
    host.app_config["update_check_enabled"] = False  # saved by the Advanced dialog
    host._apply_update_setting()
    assert not _bar_visible(host)
    assert _labels(host) == ("Help", "Check for updates...")


def test_leaving_the_check_on_in_advanced_keeps_the_bar(host):
    host._on_update_result(_info(), manual=False)
    host._apply_update_setting()
    assert _bar_visible(host)


def test_offline_is_silent(host, boxes):
    before = dict(host.app_config)
    host._on_update_result(None, manual=False)
    assert host._update_bar is None
    assert host.app_config == before and host.saved == []
    boxes.showinfo.assert_not_called()
    assert _labels(host) == ("Help", "Check for updates...")


def test_up_to_date_is_silent(host, boxes):
    host._on_update_result(_info("v1.9.3", newer=False), manual=False)
    assert host._update_bar is None and host.saved == []
    boxes.showinfo.assert_not_called()


def test_a_snoozed_version_gets_only_the_passive_signs(host):
    host.app_config.update(
        update_latest_seen="1.9.4", update_snooze_count=1,
        update_snooze_until=(_TODAY + timedelta(days=3)).isoformat(),
    )
    host._on_update_result(_info(), manual=False)
    assert not _bar_visible(host)
    assert _labels(host)[0] == "Help ●"


def test_a_skipped_version_is_silent_until_a_newer_one(host):
    host.app_config.update(update_latest_seen="1.9.4", update_skipped_version="1.9.4")
    host._on_update_result(_info(), manual=False)
    assert not _bar_visible(host)
    assert _labels(host) == ("Help", "Check for updates...")
    host._on_update_result(_info("v1.9.5"), manual=False)
    assert _bar_visible(host)
    assert host.app_config["update_latest_seen"] == "1.9.5"


def test_no_bar_until_the_file_for_this_install_is_uploaded(host):
    host._install_kind = lambda: u.INSTALL_MACOS_APP
    host._on_update_result(_info(assets=_ASSETS[:2]), manual=False)
    assert host._update_bar is None
    assert host.app_config["update_latest_seen"] == ""  # not even remembered yet
    host._on_update_result(_info(), manual=False)
    assert _bar_visible(host)


# ------------------------------------------------------------ the four buttons

def test_later_hides_the_bar_and_snoozes_three_days(host):
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["later"].invoke()
    assert not _bar_visible(host)
    assert host.app_config["update_snooze_count"] == 1
    assert host.app_config["update_snooze_until"] == (_TODAY + timedelta(days=3)).isoformat()
    assert host.saved[-1]["update_snooze_count"] == 1
    assert "again on 2026-10-09" in host.logs[-1]
    assert _labels(host)[0] == "Help ●"  # the passive sign stays


def test_the_fourth_later_leaves_only_the_passive_signs(host):
    host.app_config.update(update_latest_seen="1.9.4", update_snooze_count=3)
    host._on_update_result(_info(), manual=True)
    host._update_bar.buttons["later"].invoke()
    assert host.app_config["update_snooze_count"] == 4
    assert "No more reminders about version 1.9.4" in host.logs[-1]
    assert u.notice_level(host.app_config, "1.9.3", _TODAY + timedelta(days=60)) == u.NOTICE_PASSIVE


def test_skip_hides_the_bar_and_the_signs(host):
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["skip"].invoke()
    assert not _bar_visible(host)
    assert host.app_config["update_skipped_version"] == "1.9.4"
    assert host.saved[-1]["update_skipped_version"] == "1.9.4"
    assert _labels(host) == ("Help", "Check for updates...")


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (u.INSTALL_WINDOWS_INSTALLER, u.asset_download_url("v1.9.4", _ASSETS[0])),
        (u.INSTALL_WINDOWS_PORTABLE, u.asset_download_url("v1.9.4", _ASSETS[1])),
        (u.INSTALL_UNKNOWN, _PAGE),
    ],
)
def test_download_opens_the_file_for_this_install(host, opened, kind, expected):
    host._install_kind = lambda: kind
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["download"].invoke()
    assert opened == [expected]
    assert not _bar_visible(host)


def test_download_without_the_matching_file_opens_the_release_page(host, opened):
    host._on_update_result(_info(assets=()), manual=True)
    host._update_bar.buttons["download"].invoke()
    assert opened == [_PAGE]


def test_download_on_a_source_checkout_shows_the_update_command(host, opened, monkeypatch):
    shown = MagicMock()
    monkeypatch.setattr(bar_mod, "show_update_command", shown)
    host._install_kind = lambda: u.INSTALL_SOURCE
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["download"].invoke()
    assert opened == []
    assert shown.call_args.kwargs["version"] == "1.9.4"
    assert "pull" in shown.call_args.kwargs["command"] or "update" in shown.call_args.kwargs["command"]


def test_whats_new_opens_a_window_that_does_not_block_the_app(host, opened):
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["whats_new"].invoke()
    windows = [w for w in host.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(windows) == 1
    top = windows[0]
    assert top.title() == "What's new in 1.9.4"
    assert host.grab_current() is None
    texts = [str(w.cget("text")) for w in _descendants(top) if "text" in w.keys()]
    assert "Faster model loading and a calmer update notice." in texts
    assert "• Models load in half the time." in texts
    full = next(w for w in _descendants(top) if isinstance(w, ttk.Button) and w.cget("text") == "Full release notes")
    full.invoke()
    assert opened == [_PAGE]
    assert _bar_visible(host)  # reading the notes is not an answer


def test_whats_new_twice_keeps_one_window(host):
    host._on_update_result(_info(), manual=False)
    host._update_bar.buttons["whats_new"].invoke()
    host._update_bar.buttons["whats_new"].invoke()
    host.update_idletasks()
    assert len([w for w in host.winfo_children() if isinstance(w, tk.Toplevel)]) == 1


def test_the_command_window_shows_and_copies_the_command(host):
    import gc

    top = bar_mod.show_update_command(host, version="1.9.4", command="bash update.sh")
    gc.collect()  # a Tk variable owned only by the function would be gone now
    host.update_idletasks()
    entry = next(w for w in _descendants(top) if isinstance(w, ttk.Entry))
    assert entry.get() == "bash update.sh"
    assert str(entry.cget("state")) == "readonly"
    copy = next(w for w in _descendants(top) if isinstance(w, ttk.Button) and w.cget("text") == "Copy")
    copy.invoke()
    assert host.clipboard_get() == "bash update.sh"


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


# ------------------------------------------------------------ manual check

def test_manual_check_shows_the_bar_even_when_snoozed_or_shown_before(host):
    host.app_config.update(
        update_latest_seen="1.9.4", update_snooze_count=4, update_snooze_until="",
    )
    host._update_bar_shown_this_launch = True
    host._on_update_result(_info(), manual=True)
    assert _bar_visible(host)


@pytest.mark.parametrize("answer", [False, True])
def test_manual_check_of_a_skipped_version_asks_first(host, boxes, answer):
    host.app_config.update(update_latest_seen="1.9.4", update_skipped_version="1.9.4")
    boxes.askyesno.return_value = answer
    host._on_update_result(_info(), manual=True)
    assert "You chose to skip it" in boxes.askyesno.call_args.args[1]
    assert _bar_visible(host) is answer
    assert host.app_config["update_skipped_version"] == ("" if answer else "1.9.4")


def test_manual_check_reports_up_to_date_and_offline(host, boxes):
    host._on_update_result(_info("v1.9.3", newer=False), manual=True)
    notices = host_for(host)
    assert notices.current is not None and "latest version (1.9.3)" in notices.current[0]
    host._on_update_result(None, manual=True)
    assert "Could not reach the update server" in notices.pending[-1][0]
    boxes.showinfo.assert_not_called()
    assert host._update_bar is None


# ------------------------------------------------------------ the launch check gate

def _gate_app(**config):
    return SimpleNamespace(
        _closing=False, _quick_start_open=False, after=MagicMock(),
        _run_update_check=MagicMock(), _maybe_quiet_update_check=MagicMock(),
        app_config={"update_check_enabled": True, "last_update_check": "", **config},
    )


def test_the_launch_check_books_the_next_one_a_day_later(monkeypatch):
    monkeypatch.setattr(app_mod, "save_config", lambda c: None)
    monkeypatch.setattr(app_mod, "_today", lambda: _TODAY)
    fake = _gate_app(last_update_check=_TODAY.isoformat())
    App._maybe_quiet_update_check(fake)  # type: ignore[arg-type]
    fake.after.assert_called_once_with(app_mod._UPDATE_RECHECK_MS, fake._maybe_quiet_update_check)
    fake._run_update_check.assert_not_called()  # already checked today


@pytest.mark.parametrize(
    ("config", "env", "runs"),
    [
        ({}, "", True),
        ({"update_check_enabled": False}, "", False),
        ({}, "1", False),
    ],
)
def test_the_launch_check_follows_the_switch_and_the_environment(monkeypatch, config, env, runs):
    saved: list[dict] = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(dict(c)))
    monkeypatch.setattr(app_mod, "_today", lambda: _TODAY)
    monkeypatch.setenv(u.DISABLE_ENV_VAR, env)
    fake = _gate_app(**config)
    App._maybe_quiet_update_check(fake)  # type: ignore[arg-type]
    assert fake._run_update_check.called is runs
    if runs:
        fake._run_update_check.assert_called_once_with(manual=False)
        assert saved[-1]["last_update_check"] == _TODAY.isoformat()


def test_a_withdrawn_release_clears_the_help_dot(host):
    host.app_config["update_latest_seen"] = "1.9.4"
    host._refresh_update_signs()
    assert "●" in _labels(host)[0]
    # 1.9.4 was withdrawn: the check now finds 1.9.3, the running version.
    host._on_update_result(_info("v1.9.3", newer=False), manual=False)
    assert host.app_config["update_latest_seen"] == "1.9.3"
    assert host.saved and host.saved[-1]["update_latest_seen"] == "1.9.3"
    assert "●" not in _labels(host)[0]
