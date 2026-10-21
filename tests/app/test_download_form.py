"""The compact Download form (tabs.build_download_tab, 2026-10-22).

Five grid rows and a "More options" disclosure: the cookies and the time range sit behind it,
closed on a new install and remembered in ``download_more_options_open``; a set time range
opens it for the session so a range is never hidden. The quality choices and the after-download
toggles are WrapRows that flow onto a second line when the window is too narrow. Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets import tabs
from app.widgets.wrap_row import WrapRow
from tests.app.test_i18n_wave_4 import _StubApp


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


WIDE = 1100  # the page width of a default (960-px minimum) window and more


def _build(root: tk.Tk, config: dict | None = None, width: int = WIDE) -> _StubApp:
    app = _StubApp(root)
    app.app_config = dict(config or {})
    frame = ttk.Frame(root)
    tabs.build_download_tab(app, frame)  # type: ignore[arg-type]
    # A page of a known width, as the tab's scroller gives it (a withdrawn root alone lays
    # its frames out 1 px wide). The size takes effect only on a frame Tk has laid out once.
    frame.pack(anchor="nw")  # no fill: the frame's own size counts, not the root's
    root.update_idletasks()
    frame.configure(width=width, height=700)
    frame.pack_propagate(False)
    root.update_idletasks()
    app.page = frame  # type: ignore[attr-defined]
    return app


def _grid_row(widget: tk.Misc) -> int:
    return int(widget.grid_info()["row"])


def test_more_options_starts_closed_and_holds_the_cookies_and_the_time_range(root: tk.Tk) -> None:
    app = _build(root)
    more = app.download_more_options
    assert not more.is_open and not more.body.winfo_manager()
    body = str(more.body)
    assert str(app.download_cookies_combo).startswith(body)
    assert str(app.download_start_scale).startswith(body)
    assert app.app_config.get("download_more_options_open") is None  # nothing written at build


def test_more_options_state_is_read_from_and_written_to_the_config(root: tk.Tk) -> None:
    app = _build(root, {"download_more_options_open": True})
    more = app.download_more_options
    assert more.is_open and more.body.winfo_manager() == "pack"
    more.toggle()
    assert app.app_config["download_more_options_open"] is False
    assert not more.body.winfo_manager()


@pytest.mark.parametrize("side", ["start", "end"])
def test_a_set_time_range_opens_more_options_without_saving_it(root: tk.Tk, side: str) -> None:
    app = _build(root)
    var = app.download_start_time_var if side == "start" else app.download_end_time_var
    var.set("0:00:45")
    more = app.download_more_options
    assert more.is_open and more.body.winfo_manager() == "pack"
    assert "download_more_options_open" not in app.app_config  # a session reveal, not a preference


def test_a_zero_or_invalid_bound_leaves_more_options_closed(root: tk.Tk) -> None:
    app = _build(root)
    app.download_start_time_var.set("0:00:00")
    app.download_end_time_var.set("garbage")
    assert not app.download_more_options.is_open


def test_a_set_range_does_not_reopen_what_the_user_closed_again_until_it_changes(root: tk.Tk) -> None:
    app = _build(root)
    app.download_end_time_var.set("0:01:00")
    app.download_more_options.toggle()  # the person closes it
    assert not app.download_more_options.is_open
    app.download_end_time_var.set("0:02:00")  # a new bound shows it again
    assert app.download_more_options.is_open


def test_the_form_has_five_rows_before_more_options(root: tk.Tk) -> None:
    app = _build(root)
    top = app.download_more_options.master
    assert _grid_row(app.download_more_options) == 4
    assert _grid_row(app.download_quality_row) == 2
    labels = {str(w.cget("text")): _grid_row(w) for w in top.winfo_children()
              if isinstance(w, ttk.Label) and str(w.cget("text"))}
    assert labels["Video link"] == 0 and labels["Folder"] == 1 and labels["Quality"] == 2
    # the mode sits on the folder row, next to Browse
    assert str(app.download_mode_combo.master.grid_info()["row"]) == "1"
    # the Download button is still the last row
    button = next(w for w in top.winfo_children()
                  if isinstance(w, ttk.Button) and "Download" in str(w.cget("text")))
    assert _grid_row(button) > 4


def test_every_moved_widget_keeps_its_variable(root: tk.Tk) -> None:
    app = _build(root)
    pairs = [
        (app.download_mode_combo, None),
        (app.audio_format_combo, app.audio_format_var),
        (app.video_format_combo, app.video_format_var),
        (app.output_format_combo, app.output_format_var),
        (app.download_cookies_combo, app.download_cookies_var),
    ]
    for widget, var in pairs:
        assert widget.winfo_exists()
        if var is not None:
            assert str(widget.cget("textvariable")) == str(var)
    assert app.subtitle_lang_combo.winfo_exists() and app.download_start_scale.winfo_exists()
    # the caption shortcut button is built but, as before, not shown until captions are found
    assert app.caption_shortcut_button.winfo_exists() and not app.caption_shortcut_button.winfo_manager()


def test_the_quality_row_falls_back_to_more_lines_when_narrow(root: tk.Tk) -> None:
    app = _build(root)
    row: WrapRow = app.download_quality_row
    cells = [w for w in row.winfo_children() if w.winfo_manager() == "grid"]
    assert len(cells) == 3 and row.line_count == 1
    assert {int(c.grid_info()["row"]) for c in cells} == {0}
    one_line = sum(c.winfo_reqwidth() for c in cells) + 2 * 18
    row.reflow(one_line)  # exactly enough
    assert row.line_count == 1
    row.reflow(one_line - 1)
    assert row.line_count == 2
    assert [int(c.grid_info()["row"]) for c in cells] == [0, 0, 1]
    row.reflow(max(c.winfo_reqwidth() for c in cells))  # one cell per line
    assert row.line_count == 3
    row.reflow(one_line + 200)  # wide again: back to one line
    assert row.line_count == 1 and {int(c.grid_info()["row"]) for c in cells} == {0}


def test_the_rows_follow_the_page_width(root: tk.Tk) -> None:
    """A narrow page wraps the quality row through Tk's own resize events; a wide page
    unwraps it again (the row must not request the one-line width, or the form would be
    clipped instead of resized and never wrap)."""
    app = _build(root)
    row: WrapRow = app.download_quality_row
    cells = [w for w in row.winfo_children() if w.winfo_manager() == "grid"]
    one_line = sum(c.winfo_reqwidth() for c in cells) + 2 * 18
    assert row.line_count == 1 and row.winfo_width() >= one_line
    page = app.page  # type: ignore[attr-defined]
    page.configure(width=one_line // 2)
    root.update_idletasks()
    assert row.line_count >= 2
    page.configure(width=WIDE)
    root.update_idletasks()
    assert row.line_count == 1
    # the form never asks for more than its widest cell on that row, so the page is never clipped
    assert row.winfo_reqwidth() < one_line
