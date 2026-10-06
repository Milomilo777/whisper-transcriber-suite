"""About lives under Help, and the empty Transcribe tab tells a new user what to do.

Both run on a small Tk host (a real root) instead of the full App, which needs the whole
config stack, a tray icon and the worker services: the real ``App._build_menu`` builds the
real menu bar, and the real ``sync_transcribe_empty_state`` drives the empty-state block.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.app as app_mod
from app.app import App
from app.widgets import tabs


class _MenuHost(tk.Tk):
    """A Tk root that runs the App's real ``_build_menu``."""

    _build_menu = App._build_menu


def _menu_host() -> _MenuHost:
    root = _MenuHost()
    root.withdraw()
    root.app_config = {}  # type: ignore[attr-defined]
    root.theme_var = tk.StringVar(master=root, value="system")  # type: ignore[attr-defined]
    for name in (
        "browse", "convert_transcript", "show_statistics", "_force_exit", "apply_theme",
        "_save_chime_pref", "_open_transcript_viewer_picker", "_open_search_dialog",
        "open_log_folder", "_check_for_updates_manual", "_save_telemetry_pref",
        "_show_about", "_populate_recent_menu", "_toggle_work_offline",
    ):
        setattr(root, name, MagicMock(name=name))
    root.integrations_service = MagicMock()  # type: ignore[attr-defined]
    return root


@pytest.fixture
def menu_host():
    root = _menu_host()
    try:
        root._build_menu()
        yield root
    finally:
        root.destroy()


def _labels(menu: tk.Menu) -> list[str]:
    last = menu.index("end")
    kinds = [menu.type(i) for i in range(0, (last or -1) + 1)]
    return [
        "-" if kind == "separator" else str(menu.entrycget(i, "label"))
        for i, kind in enumerate(kinds)
        if kind != "tearoff"
    ]


def test_menubar_has_only_the_three_menus_and_no_direct_about(menu_host):
    assert _labels(menu_host._menubar) == ["File", "View", "Help"]


def test_about_is_the_last_help_item_and_opens_the_dialog(menu_host):
    help_menu = menu_host._help_menu
    last = help_menu.index("end")
    assert help_menu.entrycget(last, "label") == "About"
    assert help_menu.type(last) == "command"
    help_menu.invoke(last)
    menu_host._show_about.assert_called_once_with()


def test_file_menu_has_the_work_offline_check_item_before_exit(menu_host):
    bar = menu_host._menubar
    cascade = next(
        i for i in range(bar.index("end") + 1)
        if bar.type(i) == "cascade" and bar.entrycget(i, "label") == "File"
    )
    file_menu = menu_host.nametowidget(bar.entrycget(cascade, "menu"))
    labels = _labels(file_menu)
    index = labels.index("Work offline")
    assert labels[index + 1] == "-" and labels[index + 2].startswith("Exit")
    entry = index + (1 if file_menu.type(0) == "tearoff" else 0)
    assert file_menu.type(entry) == "checkbutton"
    assert str(file_menu.entrycget(entry, "variable")) == str(menu_host.work_offline_var)
    file_menu.invoke(entry)
    menu_host._toggle_work_offline.assert_called_once_with()
    assert menu_host.work_offline_var.get() is True  # the tick the handler reads


def test_update_sign_indexes_still_point_at_their_items(menu_host):
    help_menu = menu_host._help_menu
    assert help_menu.entrycget(menu_host._check_updates_index, "label") == app_mod._CHECK_FOR_UPDATES_LABEL
    assert menu_host._menubar.entrycget(menu_host._help_cascade_index, "label") == app_mod._HELP_MENU_LABEL


# ----------------------------------------------------------------- empty state

@pytest.mark.parametrize(
    ("dnd", "sample", "expected"),
    [
        (True, True, "Drop a file here, paste a link, or try the sample"),
        (True, False, "Drop a file here or paste a link"),
        (False, True, "Pick a file, paste a link, or try the sample"),
        (False, False, "Pick a file or paste a link"),
    ],
)
def test_headline_promises_only_what_this_install_can_do(dnd, sample, expected):
    assert tabs.empty_state_headline(dnd, sample) == expected


def test_formats_line_is_one_line_naming_common_formats():
    assert "\n" not in tabs.EMPTY_STATE_FORMATS
    for fmt in ("MP3", "WAV", "MP4", "MKV"):
        assert fmt in tabs.EMPTY_STATE_FORMATS


@pytest.fixture
def tab_host():
    root = tk.Tk()
    root.withdraw()
    drop_zone = ttk.LabelFrame(root)
    drop_zone.pack()
    frame = ttk.Frame(drop_zone)
    ttk.Label(frame, text="x").pack()
    browse_row = ttk.Frame(drop_zone)
    browse_row.pack()
    frame.pack(before=browse_row)
    host = SimpleNamespace(
        queue=[],
        _dnd_ready=False,
        transcribe_has_sample=True,
        transcribe_empty_state=frame,
        transcribe_browse_row=browse_row,
        transcribe_empty_headline_var=tk.StringVar(master=root),
    )
    try:
        yield host
    finally:
        root.destroy()


def test_empty_state_is_shown_with_an_empty_queue(tab_host):
    tabs.sync_transcribe_empty_state(tab_host)
    assert tab_host.transcribe_empty_state.winfo_manager() == "pack"
    assert tab_host.transcribe_empty_headline_var.get() == "Pick a file, paste a link, or try the sample"


def test_empty_state_hides_once_a_file_is_queued_and_returns_when_it_is_gone(tab_host):
    tab_host.queue.append(object())
    tabs.sync_transcribe_empty_state(tab_host)
    assert tab_host.transcribe_empty_state.winfo_manager() == ""
    # Browse stays, so more files can still be added.
    assert tab_host.transcribe_browse_row.winfo_manager() == "pack"
    tab_host.queue.clear()
    tabs.sync_transcribe_empty_state(tab_host)
    assert tab_host.transcribe_empty_state.winfo_manager() == "pack"
    # It comes back above Browse, not below it.
    siblings = tab_host.transcribe_browse_row.master.pack_slaves()
    assert siblings.index(tab_host.transcribe_empty_state) < siblings.index(tab_host.transcribe_browse_row)


def test_headline_follows_drag_and_drop_becoming_ready(tab_host):
    tab_host._dnd_ready = True
    tabs.sync_transcribe_empty_state(tab_host)
    assert tab_host.transcribe_empty_headline_var.get() == "Drop a file here, paste a link, or try the sample"


def test_sync_is_a_no_op_before_the_tab_is_built():
    tabs.sync_transcribe_empty_state(SimpleNamespace(queue=[]))  # type: ignore[arg-type]
