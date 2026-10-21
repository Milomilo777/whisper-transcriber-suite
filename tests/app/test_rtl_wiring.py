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


@pytest.mark.parametrize("text", ["FLAC", "Express Scribe", "فعال کردن VAD (رد کردن بخش‌های بی‌صدا)"])
def test_mirrored_check_button_asks_for_the_full_text_plus_the_gap(monkeypatch, text: str) -> None:
    """The twin style must not shrink the text: its requested width is the base width plus
    the gap, and the label element (``identify`` at every pixel) spans the measured text."""
    from tkinter import font as tkfont

    _force_rtl(monkeypatch)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    try:
        import sv_ttk  # the app's theme: there the twin's borderwidth is the gap (the vista
        # "border" element ignores it, so a plain theme would not catch a lost gap)

        sv_ttk.set_theme("light")
        root.geometry("600x100+30+30")
        base = ttk.Checkbutton(root, text=text)
        twin = ttk.Checkbutton(root, text=text)
        base.pack(anchor="w")
        twin.pack(anchor="w")
        root.update()
        base_width = base.winfo_reqwidth()
        twin.configure(style=rtl_layout.rtl_style(twin, "TCheckbutton"))
        root.update()
        assert twin.winfo_reqwidth() >= base_width + rtl_layout.INDICATOR_GAP
        assert twin.winfo_width() == twin.winfo_reqwidth()
        y = twin.winfo_height() // 2
        label_px = sum(1 for x in range(twin.winfo_width()) if twin.identify(x, y) == "label")
        assert label_px >= tkfont.nametofont("TkDefaultFont").measure(text)
    finally:
        root.destroy()


def test_app_check_buttons_use_the_mirrored_style(rtl_app) -> None:
    frame = rtl_app.transcribe_lang2_frame.master
    checks = [w for w in frame.winfo_children() if isinstance(w, ttk.Checkbutton)]
    assert checks and all(str(c.cget("style")).startswith("Rtl.") for c in checks)


def _advanced(rtl_app):
    from app.dialogs.advanced import AdvancedDialog

    dialog = AdvancedDialog(rtl_app)
    rtl_layout.mirror_window(dialog)  # what the map hook does when the dialog shows
    dialog.update_idletasks()
    return dialog


def test_grid_removed_rows_come_back_in_their_mirrored_slot(rtl_app) -> None:
    """The VAD "Fine-tune" sliders start collapsed (grid_remove before the pass); shown
    later with a bare grid() they must land in the mirrored columns, as their visible
    siblings did, and the Jump-to links rebuilt after the pass are right-aligned too."""
    dialog = _advanced(rtl_app)
    try:
        master = dialog._vad_control_rows[0][0].master
        ncols = master.grid_size()[0]
        managers = [w.winfo_manager() for row in dialog._vad_control_rows for w in row]
        assert not any(managers), (managers, getattr(dialog, rtl_layout.MIRRORED_ATTR, None))
        dialog._toggle_vad_sliders()
        dialog.update_idletasks()
        for row_label, scale, echo_label in dialog._vad_control_rows:
            # built as label col 0 (sticky w), scale col 1, echo col 2 -> mirrored
            assert int(row_label.grid_info()["column"]) == ncols - 1
            assert row_label.grid_info()["sticky"] == "e"
            assert int(scale.grid_info()["column"]) == ncols - 2
            assert int(echo_label.grid_info()["column"]) == ncols - 3
            assert _x(row_label) > _x(scale) > _x(echo_label)
        dialog._refresh_nav()
        links = [w for w in dialog._nav_links if isinstance(w, ttk.Label)]
        assert links and all(w.pack_info()["anchor"] == "e" for w in links)
        jump = [w for w in links if str(w.cget("cursor")) == "hand2"]  # the links, not the captions
        assert jump and all(str(w.cget("justify")) == "right" for w in jump)
    finally:
        dialog.destroy()


def test_a_master_with_only_unmanaged_children_stays_packable(rtl_app) -> None:
    """The engine setup frames are pack_forget'd before the pass: the pass must not grid
    them for a look (grid would then own their master, and the later pack() would fail)."""
    holder = ttk.Frame(rtl_app.t1)
    later = ttk.Frame(holder)
    ttk.Label(later, text="x").pack(side="left")
    rtl_layout.mirror_tree(holder)
    assert not later.winfo_manager()
    later.pack(fill="x")  # no TclError: the master is still free for pack
    assert later.winfo_manager() == "pack"


def test_weightless_grids_and_wrap_rows_hug_the_right_edge(rtl_app) -> None:
    rtl_app.nb.select(rtl_app.t3)
    rtl_app.update()
    cell, _ncols = _first_wrap_cell(rtl_app)
    wrap = cell.master
    assert str(wrap.tk.call("grid", "anchor", wrap._w)) == "ne"
    assert wrap.winfo_width() - (cell.winfo_x() + cell.winfo_width()) <= 2
    row = ttk.Frame(rtl_app.t1)
    for column in range(3):
        ttk.Label(row, text=f"c{column}").grid(row=0, column=column, padx=4)
    assert str(row.tk.call("grid", "anchor", row._w)) == "nw"
    rtl_layout.mirror_tree(row)
    assert str(row.tk.call("grid", "anchor", row._w)) == "ne"
    centred = ttk.Frame(rtl_app.t1)
    centred.grid_anchor("center")
    ttk.Label(centred, text="c").grid(row=0, column=0)
    rtl_layout.mirror_tree(centred)
    assert str(centred.tk.call("grid", "anchor", centred._w)) == "center"


def test_tab_strip_stays_right_aligned_after_a_theme_switch(rtl_app) -> None:
    assert ttk.Style(rtl_app).lookup("TNotebook", "tabposition") == "ne"
    rtl_app._restyle("dark")
    try:
        assert ttk.Style(rtl_app).lookup("TNotebook", "tabposition") == "ne"
        assert ttk.Style(rtl_app).layout("Rtl.TCheckbutton")
    finally:
        rtl_app._restyle("light")
    assert ttk.Style(rtl_app).lookup("TNotebook", "tabposition") == "ne"


def test_notice_bar_button_repacks_mirrored(rtl_app) -> None:
    from app.widgets.update_bar import DownloaderUpdateBar

    bar = DownloaderUpdateBar(rtl_app, on_update=lambda: None, on_dismiss=lambda: None)
    rtl_layout.mirror_tree(bar)
    assert bar.update_button.pack_info()["side"] == "right"
    bar._set_buttons(update="hidden", dismiss="Close")
    bar._set_buttons(update="enabled", dismiss="Close")
    assert bar.update_button.pack_info()["side"] == "right"
    assert bar._button_row.pack_slaves().index(bar.update_button) < \
        bar._button_row.pack_slaves().index(bar.dismiss_button)
    bar.destroy()


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
