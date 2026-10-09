"""Last result card: its height stays bounded however many files a run wrote.

With 7 output files the card grew until the drop zone and the log pane were squeezed to
one line. The file list now scrolls after LAST_RESULT_MAX_ROWS rows, and the Transcribe tab
scrolls as a whole when the window is shorter than it.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from app import app as appmod  # noqa: E402
from app.widgets import tabs  # noqa: E402
from core.task import TranscriptionTask  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless box
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def _buttons(widget, out=None):
    out = [] if out is None else out
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            out.append(child)
        _buttons(child, out)
    return out


def _card(root, tmp_path, count: int):
    out_dir = tmp_path / f"n{count}"
    out_dir.mkdir()
    paths = []
    for i in range(count):
        p = out_dir / f"clip.fmt{i}"
        p.write_bytes(b"x" * 300)
        paths.append(str(p))
    task = TranscriptionTask(str(out_dir / "clip.mp3"))
    task.output_paths = paths
    opened: list[str] = []
    fake = SimpleNamespace(
        last_result_frame=ttk.Frame(root), last_result_empty_label=MagicMock(),
        last_result_body=ttk.Frame(root), tray=None, log=MagicMock(), nb=MagicMock(),
        t1=object(), app_config={}, chime_on_complete_var=None,
        _open_file=opened.append, _open_folder=MagicMock(),
        open_transcript_viewer_for=MagicMock(), _save_shareable_page_for=MagicMock(),
    )
    appmod.App.show_last_result(fake, task)  # type: ignore[arg-type]
    root.update_idletasks()
    return fake, paths, opened


def _height(fake) -> int:
    return fake.last_result_body.winfo_reqheight()


def test_card_height_does_not_grow_past_the_cap(root, tmp_path) -> None:
    heights = {n: _height(_card(root, tmp_path, n)[0]) for n in (1, 4, 5, 7, 30)}
    assert heights[1] < heights[4]  # a few files still grow the card, as before
    assert heights[5] == heights[7] == heights[30]  # then it stops
    assert heights[30] < heights[4] + 40  # at about the 4-row size, not 30 rows


def test_few_files_are_not_wrapped_in_a_scroller(root, tmp_path) -> None:
    fake, _paths, _opened = _card(root, tmp_path, tabs.LAST_RESULT_MAX_ROWS)
    kinds: list[str] = []

    def walk(w):
        kinds.append(w.winfo_class())
        for c in w.winfo_children():
            walk(c)

    walk(fake.last_result_body)
    assert "Canvas" not in kinds and "TScrollbar" not in kinds


def test_long_list_scrolls_and_every_file_stays_reachable(root, tmp_path) -> None:
    fake, paths, opened = _card(root, tmp_path, 12)
    canvas = next(c for c in _all(fake.last_result_body) if c.winfo_class() == "Canvas")
    assert any(w.winfo_class() == "TScrollbar" for w in _all(fake.last_result_body))
    open_buttons = [b for b in _buttons(fake.last_result_body) if str(b.cget("text")) == "Open"]
    assert len(open_buttons) == len(paths)  # nothing was dropped, only hidden by the scroll
    for button in open_buttons:
        button.invoke()
    assert opened == paths
    assert canvas.yview()[0] == 0.0 and canvas.yview()[1] < 1.0
    # The wheel scrolls the list (X11 button 5 = down) and stops there: the page must not scroll too.
    canvas.event_generate("<Button-5>")
    root.update()
    assert canvas.yview()[0] > 0.0
    # Tab focus on the last button scrolls it into view.
    open_buttons[-1].focus_force()
    open_buttons[-1].event_generate("<FocusIn>")
    root.update()
    assert canvas.yview()[1] == pytest.approx(1.0, abs=0.01)


def _all(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _all(child)


def test_transcribe_tab_scrolls_when_the_window_is_short() -> None:
    # The tab sits in fit_or_scroll like the other tall tabs, so a tall card never
    # pushes the drop zone out of view or the log below the tabs down to one line.
    assert "build_transcribe_tab(self, fit_or_scroll(self.t1))" in inspect.getsource(
        appmod.App._build_tabs
    )
