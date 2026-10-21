"""The right-to-left layout wired into the app (app.rtl_layout, steps R2-R5): the main tabs,
the dynamic rows, the tab strip, the tree views, a dialog, a tooltip. Needs Tk. The same
widgets are checked in English, where nothing may move."""
from __future__ import annotations

import dataclasses
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

import pytest

from app import i18n, rtl_layout
from core.config import DEFAULT_CONFIG

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(autouse=True)
def _no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rtl_layout.ENV_OVERRIDE, raising=False)


def _force_rtl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_STATE", dataclasses.replace(i18n._STATE, direction="rtl", rtl_marks=True))
    assert rtl_layout.active()


def _build_app(tmp_path):
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    from app.app import App

    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False), \
         patch("app.app.load_config", return_value=dict(DEFAULT_CONFIG)), \
         patch("app.app.save_config"):
        return App()


@pytest.fixture
def rtl_app(tmp_path, monkeypatch):
    _force_rtl(monkeypatch)
    app = _build_app(tmp_path)
    try:
        yield app
    finally:
        _destroy(app)


@pytest.fixture
def ltr_app(tmp_path):
    assert not rtl_layout.active()
    app = _build_app(tmp_path)
    try:
        yield app
    finally:
        _destroy(app)


def _destroy(app) -> None:
    try:
        app.destroy()
    except tk.TclError:
        pass


def _x(widget: tk.Misc) -> int:
    widget.update()
    return widget.winfo_x()


def _language_row(app) -> tuple[ttk.Label, ttk.Combobox]:
    """The Transcribe tab's "Language:" label and its combobox (the first row of the form)."""
    stack: list[tk.Misc] = [app.t1]
    while stack:
        w = stack.pop()
        if isinstance(w, ttk.Label) and str(w.cget("text")) == "Language:":
            combo = w.master.pack_slaves()[1]
            assert isinstance(combo, ttk.Combobox)
            return w, combo
        stack.extend(w.winfo_children())
    raise AssertionError("language label not found")


def _columns(tree: ttk.Treeview) -> tuple[str, ...]:
    return tuple(tree.tk.splitlist(tree.cget("columns")))


def _shown(tree: ttk.Treeview) -> tuple[str, ...]:
    shown = tuple(tree.tk.splitlist(tree.cget("displaycolumns")))
    return _columns(tree) if shown == ("#all",) else shown


def _first_wrap_cell(app) -> tuple[tk.Widget, int]:
    row = app.download_more_options.master  # the Download form; its WrapRows are gridded in it
    from app.widgets.wrap_row import WrapRow
    wrap = next(w for w in row.winfo_children() if isinstance(w, WrapRow))
    cell = wrap._cells[0]
    return cell, max(len(line) for line in wrap._lines)


# --- right to left ---------------------------------------------------------------------------

def test_transcribe_language_label_sits_right_of_its_combobox(rtl_app) -> None:
    rtl_app.nb.select(rtl_app.t1)
    label, combo = _language_row(rtl_app)
    assert label.pack_info()["side"] == "right"
    assert _x(label) > _x(combo)
    assert str(combo.cget("justify")) == "left"  # the picked name still reads left to right


def test_queue_tree_columns_are_reversed_and_its_scrollbar_is_on_the_left(rtl_app) -> None:
    tree = rtl_app.tree
    assert _shown(tree) == tuple(reversed(_columns(tree)))
    assert str(tree.column("file", "anchor")) == "e"
    assert str(tree.heading("file", "anchor")) == "center"  # Tk's default heading anchor
    bar = next(w for w in tree.master.grid_slaves() if isinstance(w, ttk.Scrollbar))
    assert int(bar.grid_info()["column"]) == 0 and int(tree.grid_info()["column"]) == 1
    assert rtl_app.download_tree.cget("displaycolumns") != ("#all",)


def test_disclosure_header_sits_at_the_right(rtl_app) -> None:
    more = rtl_app.transcribe_more_options
    assert more.header.pack_info()["anchor"] == "e"
    assert str(more.header.cget("anchor")) == "e"


def test_wrap_row_first_cell_is_rightmost(rtl_app) -> None:
    rtl_app.nb.select(rtl_app.t3)
    rtl_app.update()
    cell, ncols = _first_wrap_cell(rtl_app)
    info = cell.grid_info()
    assert int(info["column"]) == ncols - 1 and info["sticky"] == "e"
    others = [w for w in cell.master.grid_slaves(row=0) if w is not cell]
    assert all(_x(cell) > _x(other) for other in others)


def test_tab_strip_is_right_aligned_and_reversed(rtl_app) -> None:
    assert ttk.Style(rtl_app).lookup("TNotebook", "tabposition") == "ne"
    tabs = rtl_app.nb.tabs()
    assert tabs[-1] == str(rtl_app.t1) and tabs[0] == str(rtl_app.t8)
    assert rtl_app.nb.select() == str(rtl_app.t1)  # the first tab is still the one shown


def test_a_dialog_is_mirrored_once_when_it_first_shows(rtl_app) -> None:
    top = tk.Toplevel(rtl_app)
    label = ttk.Label(top, text="Name")
    label.pack(side="left")
    ttk.Entry(top, width=8).pack(side="left")
    top.update()  # maps it: the hook runs once
    assert label.pack_info()["side"] == "right" and getattr(top, rtl_layout.MIRRORED_ATTR)
    top.withdraw()
    top.deiconify()
    top.update()
    assert label.pack_info()["side"] == "right"  # not flipped back by the second map
    top.destroy()


def test_search_dialog_tree_and_rows_mirror(rtl_app, monkeypatch) -> None:
    import app.dialogs.search_dialog as sd

    monkeypatch.setattr("core.search.reindex_all_history", lambda: 0)
    monkeypatch.setattr("core._threads.safe_thread", lambda target, name=None: None)
    dialog = sd.SearchDialog(rtl_app)
    try:
        rtl_layout.mirror_window(dialog)  # what the map hook does when it shows
        assert _shown(dialog.tree) == tuple(reversed(_columns(dialog.tree)))
        search_label = dialog.tree.master.master.pack_slaves()[0].pack_slaves()[0]
        assert search_label.pack_info()["side"] == "right"
        assert rtl_layout.mirror_window(dialog) == 0
    finally:
        dialog._on_close()


def test_dynamic_rows_pack_mirrored(rtl_app) -> None:
    frame = rtl_app.transcribe_lang2_frame
    wanted = str(rtl_app.mixed_lang_var)
    check = next(w for w in frame.master.winfo_children()
                 if isinstance(w, ttk.Checkbutton) and str(w.cget("variable")) == wanted)
    check.invoke()  # ticks "mixed languages": the second-language row is packed now
    assert rtl_app.mixed_lang_var.get()
    assert frame.winfo_manager() == "pack"
    assert frame.pack_info()["side"] == "right" and frame.pack_info()["padx"] == (0, 12)
    rtl_app._smtv_series_toggle(visible=True)
    top = rtl_app.download_more_options.master
    smtv = next(w for w in top.grid_slaves(row=5))
    assert smtv.grid_info()["sticky"] == "e" and smtv.grid_info()["padx"] == (0, 6)


def test_pack_kw_flips_only_into_a_master_the_pass_has_visited(rtl_app) -> None:
    # A row packed at build time is flipped by the pass itself (the Accuracy row's link was
    # flipped twice before this check existed); a row packed later gives mirrored options.
    fresh = ttk.Frame(rtl_app.t1)
    child = ttk.Label(fresh)
    assert rtl_layout.pack_kw(child, side="left", padx=(1, 2)) == {"side": "left", "padx": (1, 2)}
    assert rtl_layout.grid_kw(fresh, column=0, sticky="w") == {"column": 0, "sticky": "w"}
    rtl_layout.mirror_tree(fresh)
    assert rtl_layout.pack_kw(child, side="left", padx=(1, 2)) == {"side": "right", "padx": (2, 1)}
    assert rtl_layout.grid_kw(fresh, column=0, sticky="w")["sticky"] == "e"
    link = rtl_app.transcribe_accuracy_check_link
    assert link.pack_info()["side"] == "right" and _x(link) < _x(link.master.pack_slaves()[0])


def test_check_and_radio_indicators_sit_right_of_their_text(monkeypatch) -> None:
    """The indicator element is at the right edge of a mirrored check/radio button (Tk's
    ``identify`` names the element under a point); twice gives the base style back."""
    _force_rtl(monkeypatch)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    try:
        root.geometry("300x120+30+30")
        check = ttk.Checkbutton(root, text="tick me please")
        radio = ttk.Radiobutton(root, text="pick me please")
        check.pack(anchor="w")
        radio.pack(anchor="w")
        root.update()
        width, height = check.winfo_width(), check.winfo_height()
        assert check.identify(4, 8) == "Checkbutton.indicator"
        assert rtl_layout.mirror_tree(root) > 0
        root.update()
        assert str(check.cget("style")) == "Rtl.TCheckbutton"
        assert str(radio.cget("style")) == "Rtl.TRadiobutton"
        assert check.identify(width - 8, 8) == "Checkbutton.indicator"
        assert check.identify(4, 8) != "Checkbutton.indicator"
        assert radio.identify(radio.winfo_width() - 8, 8) == "Radiobutton.indicator"
        spec = ttk.Style(root).layout("Rtl.TCheckbutton")
        assert "'side': 'right'" in str(spec) and "'side': 'left'" not in str(spec)
        assert "Frame.border" in str(spec)  # the gap between the indicator and the text
        assert abs(check.winfo_height() - height) <= 2 * rtl_layout.INDICATOR_GAP
        rtl_layout.mirror_tree(root)  # the involution: back to the base style
        assert str(check.cget("style")) == "TCheckbutton"
        rtl_layout.mirror_tree(root)
        assert rtl_layout.refresh_styles(root) >= 2  # what a theme switch calls
        root.update()
        assert check.identify(width - 8, 8) == "Checkbutton.indicator"
    finally:
        root.destroy()


def test_app_check_buttons_use_the_mirrored_style(rtl_app) -> None:
    frame = rtl_app.transcribe_lang2_frame.master
    checks = [w for w in frame.winfo_children() if isinstance(w, ttk.Checkbutton)]
    assert checks and all(str(c.cget("style")).startswith("Rtl.") for c in checks)


def test_tooltip_is_right_justified_and_hangs_from_the_right_edge(monkeypatch) -> None:
    from app.widgets.tooltip import bind_tooltip

    _force_rtl(monkeypatch)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    try:
        host = ttk.Label(root, text="host", width=40)
        host.pack()
        bind_tooltip(host, "a hint", delay_ms=0)
        root.update()
        host.event_generate("<Enter>")
        root.update()
        tips = [w for w in host.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_children()]
        assert tips, "no tooltip appeared"
        tip = tips[-1]
        assert str(tip.winfo_children()[0].cget("justify")) == "right"
        right_edge = host.winfo_rootx() + host.winfo_width()
        assert tip.winfo_rootx() + tip.winfo_width() <= right_edge
        host.event_generate("<Leave>")
    finally:
        root.destroy()


# --- left to right: unchanged ----------------------------------------------------------------

def test_english_layout_is_untouched(ltr_app) -> None:
    label, combo = _language_row(ltr_app)
    assert label.pack_info()["side"] == "left" and _x(label) < _x(combo)
    tree = ltr_app.tree
    assert tuple(tree.tk.splitlist(tree.cget("displaycolumns"))) == ("#all",)
    assert str(tree.column("file", "anchor")) == "w"
    bar = next(w for w in tree.master.grid_slaves() if isinstance(w, ttk.Scrollbar))
    assert int(bar.grid_info()["column"]) == 1 and int(tree.grid_info()["column"]) == 0
    assert ltr_app.transcribe_more_options.header.pack_info()["anchor"] == "w"
    cell, _ncols = _first_wrap_cell(ltr_app)
    assert int(cell.grid_info()["column"]) == 0 and cell.grid_info()["sticky"] == "w"
    assert ttk.Style(ltr_app).lookup("TNotebook", "tabposition") == ""
    assert ltr_app.nb.tabs()[0] == str(ltr_app.t1)
    assert not hasattr(ltr_app, "_rtl_hook")  # no map hook is bound in English
    top = tk.Toplevel(ltr_app)
    inner = ttk.Label(top, text="x")
    inner.pack(side="left")
    top.update()
    assert inner.pack_info()["side"] == "left"
    top.destroy()
