"""app.rtl_layout: pure flips, their involution, and mirror_tree on real Tk widgets."""
from __future__ import annotations

import dataclasses
import tkinter as tk
from tkinter import ttk
from typing import Any

import pytest

from app import i18n, rtl_layout

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(autouse=True)
def _no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rtl_layout.ENV_OVERRIDE, raising=False)


@pytest.fixture
def rtl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the i18n decision the app takes at start-up for a right-to-left catalog."""
    monkeypatch.setattr(i18n, "_STATE", dataclasses.replace(i18n._STATE, direction="rtl", rtl_marks=True))
    assert rtl_layout.active()


@pytest.fixture(scope="module")
def root():
    try:
        win = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless box
        pytest.skip("no display")
    win.geometry("500x300+40+40")
    yield win
    win.destroy()


@pytest.fixture
def frame(root: tk.Tk):
    f = ttk.Frame(root, width=400, height=200)
    f.pack(fill="both", expand=True)
    yield f
    f.destroy()


# --- pure helpers -------------------------------------------------------------------------

@pytest.mark.parametrize("fn, cases", [
    (rtl_layout.flip_side, {"left": "right", "right": "left", "top": "top", "bottom": "bottom"}),
    (rtl_layout.flip_anchor, {"w": "e", "e": "w", "nw": "ne", "ne": "nw", "sw": "se", "se": "sw",
                              "n": "n", "s": "s", "center": "center", "": ""}),
    (rtl_layout.flip_sticky, {"ew": "we", "nsew": "nswe", "n": "n", "": "", "ns": "ns"}),
    (rtl_layout.flip_justify, {"left": "right", "right": "left", "center": "center", "": ""}),
    (rtl_layout.flip_padx, {(2, 5): (5, 2), 3: 3, (4, 4): (4, 4)}),
])
def test_flip_tables(fn: Any, cases: dict[Any, Any]) -> None:
    for value, expected in cases.items():
        assert fn(value) == expected, value


def test_active_follows_i18n_and_the_override(monkeypatch: pytest.MonkeyPatch, rtl: None) -> None:
    monkeypatch.setenv(rtl_layout.ENV_OVERRIDE, "0")
    assert not rtl_layout.active()
    monkeypatch.setattr(i18n, "_STATE", i18n._english_catalog())
    assert not rtl_layout.active()
    monkeypatch.setenv(rtl_layout.ENV_OVERRIDE, "1")
    assert rtl_layout.active()


SIDES = st.sampled_from(["left", "right", "top", "bottom"])
ANCHORS = st.sampled_from(["n", "s", "e", "w", "ne", "nw", "se", "sw", "center", ""])
STICKIES = st.sampled_from(["", "n", "s", "e", "w", "ns", "ew", "new", "sew", "nsew", "nw", "se"])
PADS = st.one_of(st.integers(0, 9), st.tuples(st.integers(0, 9), st.integers(0, 9)))


@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])  # slow shared CI runners
@given(SIDES, ANCHORS, STICKIES, st.sampled_from(["left", "right", "center"]), PADS)
def test_property_every_flip_is_an_involution(side: str, anchor: str, sticky: str, justify: str,
                                              padx: Any) -> None:
    assert rtl_layout.flip_side(rtl_layout.flip_side(side)) == side
    assert rtl_layout.flip_anchor(rtl_layout.flip_anchor(anchor)) == anchor
    assert rtl_layout.flip_sticky(rtl_layout.flip_sticky(sticky)) == sticky
    assert rtl_layout.flip_justify(rtl_layout.flip_justify(justify)) == justify
    assert rtl_layout.flip_padx(rtl_layout.flip_padx(padx)) == padx
    assert sorted(rtl_layout.flip_sticky(sticky).replace("e", "w")) == sorted(sticky.replace("e", "w"))
    # and never the identity where a left/right side exists (an identity is an involution too)
    assert (rtl_layout.flip_side(side) != side) == (side in ("left", "right"))
    assert (rtl_layout.flip_anchor(anchor) != anchor) == (anchor in ("w", "e", "nw", "ne", "sw", "se"))
    assert (set(rtl_layout.flip_sticky(sticky)) != set(sticky)) == (sticky.count("e") != sticky.count("w"))
    assert (rtl_layout.flip_justify(justify) != justify) == (justify != "center")
    assert (rtl_layout.flip_padx(padx) != padx) == (isinstance(padx, tuple) and padx[0] != padx[1])


# --- real Tk -------------------------------------------------------------------------------

def _x(widget: tk.Misc) -> int:
    widget.update()  # maps the window; a never-mapped widget reports x = 0
    return widget.winfo_x()


def test_label_left_of_entry_ends_up_right_of_it(frame: ttk.Frame, rtl: None) -> None:
    label = ttk.Label(frame, text="Name")
    entry = ttk.Entry(frame, width=12)
    label.pack(side="left", padx=(2, 6))
    entry.pack(side="left")
    assert _x(label) < _x(entry)
    assert rtl_layout.mirror_tree(frame) > 0
    assert _x(label) > _x(entry)
    assert label.pack_info()["side"] == "right" and label.pack_info()["padx"] == (6, 2)
    assert str(label.cget("anchor")) == "e" and str(label.cget("justify")) == "right"
    assert str(entry.cget("justify")) == "left"  # paths and URLs keep reading left to right


def test_grid_columnspan_sticky_and_weights_map_to_the_mirror_column(frame: ttk.Frame,
                                                                      rtl: None) -> None:
    wide = ttk.Label(frame, text="wide")
    wide.grid(row=0, column=0, columnspan=2, sticky="w", padx=(1, 4))
    entry = ttk.Entry(frame)
    entry.grid(row=0, column=2, sticky="ew")
    frame.grid_columnconfigure(0, weight=1, minsize=30)
    rtl_layout.mirror_tree(frame)
    assert (wide.grid_info()["column"], wide.grid_info()["columnspan"]) == (1, 2)
    assert wide.grid_info()["sticky"] == "e" and wide.grid_info()["padx"] == (4, 1)
    assert entry.grid_info()["column"] == 0 and entry.grid_info()["sticky"] == "ew"
    assert frame.grid_columnconfigure(2)["weight"] == 1 and frame.grid_columnconfigure(2)["minsize"] == 30
    assert frame.grid_columnconfigure(0)["weight"] == 0
    assert _x(entry) < _x(wide)


def test_scrollbar_on_the_right_moves_to_the_left(frame: ttk.Frame, rtl: None) -> None:
    text = tk.Text(frame, width=20, height=4)
    bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    assert _x(bar) > _x(text)
    rtl_layout.mirror_tree(frame)
    assert _x(bar) < _x(text)
    assert bar.pack_info()["side"] == "left"


def test_keep_ltr_subtree_is_untouched_but_takes_the_mirrored_slot(frame: ttk.Frame, rtl: None) -> None:
    kept = ttk.Frame(frame)
    rtl_layout.keep_ltr(kept)
    kept.pack(side="left")
    other = ttk.Label(frame, text="other")
    other.pack(side="left")
    inner_label = ttk.Label(kept, text="in")
    inner_label.pack(side="left")
    inner_entry = ttk.Entry(kept, width=5)
    inner_entry.pack(side="left")
    assert _x(kept) < _x(other)
    rtl_layout.mirror_tree(frame)
    assert _x(kept) > _x(other)  # the slot among its siblings is mirrored
    assert inner_label.pack_info()["side"] == "left"
    assert str(inner_label.cget("anchor")) in ("", "w")  # unset: "" on CI's Tk, "w" on 8.6.15
    assert _x(inner_label) < _x(inner_entry)


class _OldTkLabel(ttk.Label):
    """A ttk.Label as the Tk build on CI reports it: an unset anchor / justify reads "" and
    may be set back to "" (Tk 8.6.15 here reads "w" / "left" and rejects "")."""

    _DEFAULTS = {"anchor": "w", "justify": "left"}

    def __init__(self, master: tk.Misc, **kw: Any) -> None:
        super().__init__(master, **kw)
        self._explicit: dict[str, str] = {}

    def cget(self, key: str) -> Any:
        if key in self._DEFAULTS and key not in self._explicit:
            return ""
        return super().cget(key)

    def configure(self, cnf: Any = None, **kw: Any) -> Any:  # type: ignore[override]
        options = dict(cnf or {}, **kw)
        for key, default in self._DEFAULTS.items():
            if key in options and options[key] == "":
                self._explicit.pop(key, None)
                options[key] = default
            elif key in options:
                self._explicit[key] = options[key]
        return super().configure(options)


class _RejectingOldTkLabel(_OldTkLabel):
    """Like ``_OldTkLabel``, but ``""`` is not a settable value (Tk raises, as 8.6.15 does here):
    the unset state cannot be restored, only its meaning (the left default)."""

    def configure(self, cnf: Any = None, **kw: Any) -> Any:  # type: ignore[override]
        options = dict(cnf or {}, **kw)
        for key in self._DEFAULTS:
            if options.get(key) == "":
                raise tk.TclError(f'ambiguous {key} "": must be a valid value')
        return super().configure(options)


def test_blank_options_a_tk_cannot_set_back_end_as_the_explicit_left_default(frame: ttk.Frame,
                                                                          rtl: None) -> None:
    # Regression: Hypothesis tree [[('left', 'n', 0)]] on CI (Windows, Python 3.11): the second
    # pass could only write "w" / "left", and the snapshot compared them with the original "".
    label = _RejectingOldTkLabel(frame, text="Name")
    label.pack(side="left", anchor="n")
    assert str(label.cget("anchor")) == "" and str(label.cget("justify")) == ""
    before = _snapshot(frame)
    first = rtl_layout.mirror_tree(frame)
    assert str(label.cget("anchor")) == "e" and str(label.cget("justify")) == "right"
    assert rtl_layout.mirror_tree(frame) == first
    assert _snapshot(frame) == before  # "" and the explicit left default are the same state
    assert str(label.cget("anchor")) == "w" and str(label.cget("justify")) == "left"
    assert not getattr(label, rtl_layout.BLANK_ATTR)
    assert _snapshot(label)[0][3] == ["w", "left"]


def test_blank_anchor_and_justify_count_as_the_left_default(frame: ttk.Frame, rtl: None) -> None:
    label = _OldTkLabel(frame, text="Name")
    entry = ttk.Entry(frame, width=12)
    label.pack(side="left")
    entry.pack(side="left")
    assert str(label.cget("anchor")) == "" and str(label.cget("justify")) == ""
    rtl_layout.mirror_tree(frame)
    assert str(label.cget("anchor")) == "e" and str(label.cget("justify")) == "right"
    assert _x(label) > _x(entry)
    rtl_layout.mirror_tree(frame)  # the second pass puts the unset options back
    assert str(label.cget("anchor")) == "" and str(label.cget("justify")) == ""
    assert not getattr(label, rtl_layout.BLANK_ATTR)


@pytest.mark.parametrize("theme", ["default", "clam"])
def test_plain_themes_mirror_the_label_too(root: tk.Tk, frame: ttk.Frame, rtl: None, theme: str) -> None:
    style = ttk.Style(root)
    previous = style.theme_use()
    style.theme_use(theme)
    try:
        label = ttk.Label(frame, text="Name")
        label.pack(side="left")
        rtl_layout.mirror_tree(frame)
        assert str(label.cget("anchor")) == "e" and str(label.cget("justify")) == "right"
    finally:
        style.theme_use(previous)


def test_left_to_right_interface_is_a_no_op(frame: ttk.Frame) -> None:
    label = ttk.Label(frame, text="Name")
    label.pack(side="left", padx=(2, 6))
    assert not rtl_layout.active()
    assert rtl_layout.mirror_tree(frame) == 0
    assert label.pack_info()["side"] == "left" and label.pack_info()["padx"] == (2, 6)


# --- involution on generated trees ----------------------------------------------------------

PACK_ROW = st.lists(st.tuples(SIDES, ANCHORS, PADS), min_size=1, max_size=4)
GRID_ROW = st.tuples(st.lists(st.tuples(st.integers(1, 3), STICKIES, PADS), min_size=1, max_size=4),
                     st.lists(st.integers(0, 3), min_size=0, max_size=6))
TREE = st.lists(st.one_of(PACK_ROW, GRID_ROW), min_size=1, max_size=4)
# The stand-ins come first so every generated tree (its first widget) covers CI's Tk.
KINDS = [_RejectingOldTkLabel, _OldTkLabel, ttk.Label, ttk.Entry, ttk.Button, tk.Label, tk.Checkbutton,
         ttk.LabelFrame, tk.LabelFrame]


def _build(master: tk.Misc, tree: list[Any]) -> None:
    for i, row in enumerate(tree):
        holder = ttk.Frame(master)
        holder.pack(side="top", fill="x")
        if isinstance(row, tuple):
            cells, weights = row
            column = 0
            for j, (span, sticky, padx) in enumerate(cells):
                w = KINDS[(i + j) % len(KINDS)](holder)
                w.grid(row=0, column=column, columnspan=span, sticky=sticky, padx=padx)
                column += span
            for c, weight in enumerate(weights):
                holder.grid_columnconfigure(c, weight=weight, uniform="u" if weight % 2 else "")
        else:
            for j, (side, anchor, padx) in enumerate(row):
                w = KINDS[(i + j) % len(KINDS)](holder)
                w.pack(side=side, anchor=anchor or "center", padx=padx)
        if i % 2:
            rtl_layout.keep_ltr(holder)


def _snapshot(w: tk.Misc) -> list[Any]:
    """Geometry, text options and column configuration of ``w`` and everything under it."""
    manager = w.winfo_manager()
    info = dict(w.pack_info()) if manager == "pack" else dict(w.grid_info()) if manager == "grid" else {}
    info.pop("in", None)
    keys = w.keys()
    unset = {"anchor": "w", "justify": "left"} if isinstance(w, ttk.Label) else {}
    texts = [str(w.cget(o)) or unset.get(o, "") for o in ("anchor", "justify", "labelanchor") if o in keys]
    rows: list[Any] = [(type(w).__name__, manager, sorted(info.items()), texts)]
    if w.grid_slaves():
        rows.append([sorted(w.grid_columnconfigure(c).items()) for c in range(w.grid_size()[0])])
    rows.extend(_snapshot(child) for child in w.winfo_children())
    return rows


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(TREE)
def test_property_mirroring_twice_restores_every_pack_grid_and_text_option(root: tk.Tk, rtl: None,
                                                                            tree: list[Any]) -> None:
    holder = ttk.Frame(root)
    holder.pack(fill="both", expand=True)
    try:
        _build(holder, tree)
        before = _snapshot(holder)
        first = rtl_layout.mirror_tree(holder)
        assert first > 0
        assert rtl_layout.mirror_tree(holder) == first
        assert _snapshot(holder) == before
    finally:
        holder.destroy()


# --- LabelFrame heading ---------------------------------------------------------------------

@pytest.mark.parametrize("kind", [ttk.LabelFrame, tk.LabelFrame])
@pytest.mark.parametrize("start, mirrored", [("nw", "ne"), ("w", "e"), ("sw", "se"), ("n", "n")])
def test_labelframe_heading_side_flips_and_comes_back(frame: ttk.Frame, rtl: None, kind: Any,
                                                      start: str, mirrored: str) -> None:
    box = kind(frame, text="Last result", labelanchor=start)
    box.pack(fill="x")
    rtl_layout.mirror_tree(frame)
    assert str(box.cget("labelanchor")) == mirrored
    rtl_layout.mirror_tree(frame)
    assert str(box.cget("labelanchor")) == start


@pytest.mark.parametrize("kind", [ttk.LabelFrame, tk.LabelFrame])
def test_default_labelframe_heading_moves_right_and_is_restored(frame: ttk.Frame, rtl: None,
                                                                kind: Any) -> None:
    box = kind(frame, text="Last result")
    box.pack(fill="x")
    before = str(box.cget("labelanchor"))
    rtl_layout.mirror_tree(frame)
    assert str(box.cget("labelanchor")) == "ne"
    rtl_layout.mirror_tree(frame)
    assert str(box.cget("labelanchor")) == before


def test_labelframe_is_untouched_in_a_left_to_right_interface(frame: ttk.Frame) -> None:
    box = ttk.LabelFrame(frame, text="Last result", labelanchor="nw")
    box.pack()
    assert rtl_layout.mirror_tree(frame) == 0
    assert str(box.cget("labelanchor")) == "nw"
