"""Mirror a finished Tk widget tree for right-to-left interfaces (Persian, Arabic, Hebrew).

Tk has no right-to-left layout mode: pack sides, grid columns and label anchors are given left to
right by the code that builds a window. :func:`mirror_tree` is a post-pass over a finished tree
that reflects the geometry horizontally, only when :func:`active`:

* pack slaves: ``side`` left <-> right, ``anchor`` and ``padx`` mirrored (a pack order stays, so a
  row packed left to right comes out right to left);
* grid slaves: ``column`` -> ``ncols - column - columnspan``, ``sticky`` e <-> w, ``padx``
  mirrored, and the master's column weights/minsize/pad/uniform swapped the same way;
* text widgets (labels, buttons, check and radio buttons, ``tk.Message``): ``anchor`` and
  ``justify`` mirrored. A ``ttk.Scrollbar`` packed on the right therefore moves to the left;
* a ``ttk.Checkbutton`` / ``ttk.Radiobutton``: its style is swapped for an ``Rtl.`` twin whose
  layout puts the indicator at the right of the text (:func:`rtl_style`; a theme switch
  calls :func:`refresh_styles`, since layouts live per theme);
* a ``ttk.Treeview``: its ``displaycolumns`` reversed (column ids unchanged) and every column
  and heading anchor mirrored; the ``#0`` tree column cannot move.

The interior of an Entry, Combobox, Spinbox, Text and Listbox stays as it is (a path, a URL or
a time reads left to right), and so does everything under a widget marked with
:func:`keep_ltr`; such widgets still take the mirrored slot among their siblings, else two
widgets would share one cell. A widget marked with :func:`manages_own_layout` places its own
slaves (``WrapRow``), so the pass leaves their geometry alone but still descends into them.
Place-managed slaves, menus and native message boxes are untouched (Tk cannot mirror them).

Every flip is an involution: applied twice it gives the original back, so a tree is mirrored
exactly once, after it is built (the pass is not idempotent). A call site that packs or grids a
widget later (or both at build time and later) uses :func:`pack_kw` / :func:`grid_kw`, which
flip only into a master the pass has already visited, and a subtree built later is passed to
:func:`mirror_tree` on its own. Dialogs need no call of their own:
:func:`install_window_hook` mirrors every new ``Toplevel`` once, when it is first mapped
(:func:`mirror_window` does the same by hand, earlier). The decision is the one ``app.i18n``
takes at start-up (:func:`app.i18n.rtl_marks`); ``WTS_RTL_LAYOUT=1`` or ``0`` overrides it for a
manual try.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from app import i18n

#: "1" forces the mirrored layout on, "0" off; unset or anything else: ``i18n.rtl_marks()``.
ENV_OVERRIDE = "WTS_RTL_LAYOUT"
#: Set on a widget by :func:`keep_ltr`: its options and its whole subtree stay left to right.
KEEP_ATTR = "_rtl_keep"
#: Set by :func:`manages_own_layout`: the widget grids/packs its own slaves right to left.
OWN_LAYOUT_ATTR = "_rtl_own_layout"
#: Set on every container the pass visits (and by :func:`mirror_window` on a Toplevel the hook
#: must not mirror again): :func:`pack_kw` / :func:`grid_kw` flip only into a marked master.
MIRRORED_ATTR = "_rtl_mirrored"

_ANCHORS = {"w": "e", "e": "w", "nw": "ne", "ne": "nw", "sw": "se", "se": "sw"}
_SIDES = {"left": "right", "right": "left"}
_JUSTIFY = {"left": "right", "right": "left"}
_STICKY = str.maketrans("ew", "we")
#: Their contents stay left to right and the pass does not descend into them.
_KEEP_INSIDE = (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox, tk.Text, tk.Listbox,
                tk.Menu)
#: ttk widgets with an indicator left of their text: they get a mirrored twin style.
_INDICATOR_WIDGETS = (ttk.Checkbutton, ttk.Radiobutton)
#: Prefix of a mirrored twin style; ``_RTL_STYLES`` maps each twin to its base style.
STYLE_PREFIX = "Rtl."
_RTL_STYLES: dict[str, str] = {}
#: Pixels between a mirrored indicator and its text (sv_ttk's indicator image carries a
#: 6 px gap on its own right, which ends up outside once the element sits at the right).
INDICATOR_GAP = 4
#: Set on a ttk.Label whose unset anchor / justify read "" before the pass flipped them.
BLANK_ATTR = "_rtl_blank"
_BLANK_DEFAULTS = {"anchor": "w", "justify": "left"}
#: "notebook": a tab strip was mirrored, so a theme switch sets ``tabposition`` again.
_STATE = {"notebook": False}
#: Widgets whose ``anchor`` / ``justify`` place text (never the editable ones above).
_TEXT_WIDGETS = (tk.Label, ttk.Label, tk.Button, ttk.Button, tk.Checkbutton, ttk.Checkbutton,
                 tk.Radiobutton, ttk.Radiobutton, tk.Message, tk.Menubutton, ttk.Menubutton)


def active() -> bool:
    """True when the interface is right to left: the ``app.i18n`` decision, or the override."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override in ("0", "1"):
        return override == "1"
    return i18n.rtl_marks()


def flip_side(side: str) -> str:
    """'left' <-> 'right'; 'top' and 'bottom' unchanged."""
    return _SIDES.get(side, side)


def flip_anchor(anchor: str) -> str:
    """w <-> e, nw <-> ne, sw <-> se; n, s, center and '' unchanged."""
    return _ANCHORS.get(anchor, anchor)


def flip_sticky(sticky: str) -> str:
    """Swap the e and w letters, keep n and s ('new' -> 'nwe'; Tk normalises the order)."""
    return sticky.translate(_STICKY)


def flip_justify(justify: str) -> str:
    """'left' <-> 'right'; 'center' and '' unchanged."""
    return _JUSTIFY.get(justify, justify)


def flip_padx(padx: int | tuple[int, int]) -> int | tuple[int, int]:
    """(left, right) -> (right, left); a single number unchanged."""
    if isinstance(padx, tuple) and len(padx) == 2:
        return (padx[1], padx[0])
    return padx


def pack_kw(widget: tk.Misc, **options: Any) -> dict[str, Any]:
    """``pack`` options for ``widget`` at a call site that may run before or after the pass:
    ``side``, ``anchor`` and ``padx`` are mirrored only once its master has been mirrored
    (:func:`mirrored`), since a pack made before the pass is flipped by the pass itself;
    ``before`` / ``after`` and the rest are untouched (the pack order carries the same
    meaning in both directions)."""
    master = options.get("in_") or getattr(widget, "master", None)  # test doubles have none
    if master is None or not mirrored(master):
        return options
    flipped = dict(options)
    if "side" in flipped:
        flipped["side"] = flip_side(str(flipped["side"]))
    if "anchor" in flipped:
        flipped["anchor"] = flip_anchor(str(flipped["anchor"]))
    if "padx" in flipped:
        flipped["padx"] = flip_padx(flipped["padx"])
    return flipped


def grid_kw(master: tk.Misc, **options: Any) -> dict[str, Any]:
    """``grid`` options for a slave gridded into ``master``: once ``master`` has been
    mirrored, the column is mapped to its mirror among its current columns and ``sticky``
    and ``padx`` are flipped; before the pass they are left for the pass to flip."""
    if not mirrored(master):
        return options
    flipped = dict(options)
    if "column" in flipped:
        ncols = master.grid_size()[0]
        span = int(flipped.get("columnspan", 1))
        flipped["column"] = max(0, ncols - int(flipped["column"]) - span)
    if "sticky" in flipped:
        flipped["sticky"] = flip_sticky(str(flipped["sticky"]))
    if "padx" in flipped:
        flipped["padx"] = flip_padx(flipped["padx"])
    return flipped


def keep_ltr(widget: tk.Misc) -> None:
    """Mark ``widget``: :func:`mirror_tree` leaves its options and its whole subtree alone."""
    setattr(widget, KEEP_ATTR, True)


def manages_own_layout(widget: tk.Misc) -> None:
    """Mark ``widget`` as placing its own slaves right to left: the pass keeps their
    geometry but still mirrors the slaves' contents."""
    setattr(widget, OWN_LAYOUT_ATTR, True)


def mirrored(widget: tk.Misc) -> bool:
    """True when the interface is right to left and the pass has already run over
    ``widget`` (every container it visits is marked), so a later pack or grid into it must
    give mirrored options itself."""
    return active() and bool(getattr(widget, MIRRORED_ATTR, False))


def _keeps_ltr(widget: tk.Misc) -> bool:
    return bool(getattr(widget, KEEP_ATTR, False)) or isinstance(widget, _KEEP_INSIDE)


def _flip_layout(spec: Any) -> Any:
    """A ttk layout spec with every ``side`` left <-> right and ``sticky`` e <-> w swapped,
    recursively through ``children``: the indicator of a check or radio button moves to the
    right of its text."""
    flipped = []
    for element, options in spec:
        options = dict(options)
        if "side" in options:
            options["side"] = flip_side(str(options["side"]))
        if "sticky" in options:
            options["sticky"] = flip_sticky(str(options["sticky"]))
        if "children" in options:
            options["children"] = _flip_layout(options["children"])
        flipped.append((element, options))
    return flipped


def _wrap_label(spec: Any) -> Any:
    """``spec`` with its ``*.label`` element inside a flat ``Frame.border`` element: the
    twin style's ``borderwidth`` then keeps :data:`INDICATOR_GAP` px between the text and
    the indicator (an image element draws its own gap on its left-to-right side only)."""
    wrapped = []
    for element, options in spec:
        options = dict(options)
        if element.endswith(".label"):
            outer = {k: v for k, v in options.items() if k in ("side", "sticky", "expand")}
            outer["children"] = [(element, {"sticky": "nswe"})]
            wrapped.append(("Frame.border", outer))
            continue
        if "children" in options:
            options["children"] = _wrap_label(options["children"])
        wrapped.append((element, options))
    return wrapped


def rtl_style(widget: tk.Misc, base: str) -> str:
    """The name of the mirrored twin of ttk style ``base`` (``Rtl.`` + base, so it inherits
    the base's colours and maps), with its layout defined in the current theme."""
    derived = base if base.startswith(STYLE_PREFIX) else STYLE_PREFIX + base
    style = ttk.Style(widget)
    style.layout(derived, _wrap_label(_flip_layout(style.layout(base))))
    style.configure(derived, borderwidth=INDICATOR_GAP, relief="flat")
    _RTL_STYLES[derived] = base
    return derived


def refresh_styles(root: tk.Misc) -> int:
    """Define every mirrored style again in the current theme, and the tab strip's right
    alignment: call after a theme switch (``sv_ttk.set_theme`` rebuilds the base layouts in
    another theme, where ``tabposition`` is unset again). Returns the style count."""
    if not active():
        return 0
    for derived, base in list(_RTL_STYLES.items()):
        rtl_style(root, base)
        assert _RTL_STYLES[derived] == base
    if _STATE["notebook"]:
        ttk.Style(root).configure("TNotebook", tabposition="ne")
    return len(_RTL_STYLES)


def text_kw(master: tk.Misc, **options: Any) -> dict[str, Any]:
    """Widget options (``anchor``, ``justify``) for a label or button created under
    ``master`` after the pass: mirrored once ``master`` has been mirrored, else as given."""
    if not mirrored(master):
        return options
    flipped = dict(options)
    if "anchor" in flipped:
        flipped["anchor"] = flip_anchor(str(flipped["anchor"]))
    if "justify" in flipped:
        flipped["justify"] = flip_justify(str(flipped["justify"]))
    return flipped


def _mirror_indicator_style(widget: tk.Misc) -> int:
    """Swap a ttk check or radio button between its style and the ``Rtl.`` twin."""
    current = str(widget.cget("style")) or "T" + widget.winfo_class().removeprefix("T")
    if current.startswith(STYLE_PREFIX):
        widget.configure({"style": _RTL_STYLES.get(current, current[len(STYLE_PREFIX):])})
    else:
        widget.configure({"style": rtl_style(widget, current)})
    return 1


def _mirror_options(widget: tk.Misc) -> int:
    if not isinstance(widget, _TEXT_WIDGETS):
        return 0
    keys = widget.keys()
    changed = _mirror_indicator_style(widget) if isinstance(widget, _INDICATOR_WIDGETS) else 0
    blank: set[str] = getattr(widget, BLANK_ATTR, set())
    for option, flip in (("anchor", flip_anchor), ("justify", flip_justify)):
        if option not in keys:
            continue
        old = str(widget.cget(option))
        was_blank = old == "" and isinstance(widget, ttk.Label)
        if was_blank:
            # An unset ttk.Label option reads "" on some Tk builds (CI: Python 3.12's Tk
            # 8.6) and "w" / "left" on others; both mean the same default.
            old = _BLANK_DEFAULTS[option]
        new = flip(old)
        if option in blank and new == _BLANK_DEFAULTS[option]:
            # The second pass: put the unset option back where the build accepts "".
            blank.discard(option)
            try:
                widget.configure({option: ""})
            except tk.TclError:
                widget.configure({option: new})
            changed += 1
        elif new != old:
            widget.configure({option: new})
            if was_blank:
                blank.add(option)
            changed += 1
    setattr(widget, BLANK_ATTR, blank)
    return changed


def _mirror_pack_slaves(master: tk.Misc) -> int:
    changed = 0
    for slave in master.pack_slaves():
        info = slave.pack_info()
        slave.pack_configure({"side": flip_side(str(info["side"])),
                              "anchor": flip_anchor(str(info["anchor"])),
                              "padx": flip_padx(info["padx"])})
        changed += 1
    return changed


def _hidden_grid_children(master: tk.Misc) -> list[tk.Widget]:
    """Children taken off the grid with ``grid_remove`` (the VAD sliders of the Advanced
    dialog start collapsed): Tk remembers their options but reports nothing for them, so
    they are gridded again for the pass and removed after it. Only for a master that grids
    something already: gridding a never-managed child makes grid the master's manager for
    good (a removed slave stays registered), and a later pack() into it would fail."""
    hidden: list[tk.Widget] = []
    if not master.grid_slaves():
        return hidden
    for child in master.winfo_children():
        if child.winfo_manager() or isinstance(child, (tk.Toplevel, tk.Menu)):
            continue
        try:
            child.grid()
        except tk.TclError:
            continue  # the master packs its slaves, or the child cannot be gridded
        hidden.append(child)
    return hidden


def _mirror_grid_slaves(master: tk.Misc) -> int:
    hidden = _hidden_grid_children(master)
    slaves = master.grid_slaves()
    if not slaves:
        return 0
    ncols = master.grid_size()[0]
    for slave in slaves:
        info = slave.grid_info()
        column, span = int(info["column"]), int(info["columnspan"])
        slave.grid_configure(column=ncols - column - span, sticky=flip_sticky(str(info["sticky"])),
                             padx=flip_padx(info["padx"]))
    for left in range(ncols // 2):
        right = ncols - 1 - left
        a, b = _column_options(master, left), _column_options(master, right)
        master.grid_columnconfigure(left, **b)
        master.grid_columnconfigure(right, **a)
    # The block of a grid without a weighted column hugs Tk's default "nw" corner: mirror
    # the anchor too ("center" and "n", chosen on purpose, stay).
    anchor: Any = flip_anchor(str(master.tk.call("grid", "anchor", str(master))))
    master.grid_anchor(anchor)
    for child in hidden:
        child.grid_remove()
    return len(slaves)


def _column_options(master: tk.Misc, column: int) -> dict[str, Any]:
    info = master.grid_columnconfigure(column)
    # tkinter drops None options, so an unset uniform group is written back as "".
    return {"minsize": info.get("minsize", 0), "pad": info.get("pad", 0),
            "weight": info.get("weight", 0), "uniform": info.get("uniform") or ""}


def _mirror_treeview(tree: ttk.Treeview) -> int:
    """Reverse the shown column order and mirror the cell and heading anchors; the ids,
    widths and the ``#0`` column's place are Tk's and stay."""
    columns = tuple(tree.tk.splitlist(tree.cget("columns") or ()))
    if not columns:
        return 0
    shown = tuple(tree.tk.splitlist(tree.cget("displaycolumns") or ()))
    if shown == ("#all",):
        shown = columns
    tree.configure(displaycolumns=tuple(reversed(shown)))
    for column in ("#0",) + columns:
        cell: Any = flip_anchor(str(tree.column(column, "anchor")))
        heading: Any = flip_anchor(str(tree.heading(column, "anchor")))
        tree.column(column, anchor=cell)
        tree.heading(column, anchor=heading)
    return 1


def _mirror(widget: tk.Misc) -> int:
    if _keeps_ltr(widget):
        return 0
    if isinstance(widget, ttk.Treeview):
        return _mirror_treeview(widget)
    changed = _mirror_options(widget)
    setattr(widget, MIRRORED_ATTR, True)
    if not getattr(widget, OWN_LAYOUT_ATTR, False):
        changed += _mirror_pack_slaves(widget) + _mirror_grid_slaves(widget)
    for child in widget.winfo_children():
        changed += _mirror(child)
    return changed


def mirror_tree(widget: tk.Misc) -> int:
    """Reflect ``widget`` and everything under it horizontally when :func:`active`.

    Call it once, after the tree is built and before the window is shown. Returns the number of
    widgets whose options or geometry changed: 0 in a left-to-right interface.
    """
    if not active():
        return 0
    return _mirror(widget)


def mirror_window(window: tk.Misc) -> int:
    """:func:`mirror_tree` for a Toplevel (or the root), at most once: a later map of the same
    window (the hook, a deiconify) leaves it as it is."""
    if getattr(window, MIRRORED_ATTR, False):
        return 0
    setattr(window, MIRRORED_ATTR, True)
    return mirror_tree(window)


def install_window_hook(root: tk.Tk) -> None:
    """Mirror every Toplevel under ``root`` once, when it is first mapped: dialogs are built
    in full before they show. ``root`` itself is marked done (its tabs are mirrored by hand,
    one per finished tab). Does nothing in a left-to-right interface."""
    setattr(root, MIRRORED_ATTR, True)
    if not active():
        return

    def _on_map(event: Any) -> None:
        window = getattr(event, "widget", None)
        if isinstance(window, tk.Toplevel):
            mirror_window(window)

    root.bind_all("<Map>", _on_map, add="+")


def mirror_notebook(notebook: ttk.Notebook) -> int:
    """Right-align the tab strip (``tabposition`` ne) and reverse the tab order, so the first
    tab is the rightmost one; the tab ids and ``select(widget)`` are unaffected. Probe (Tk
    8.6.15, Windows): ``tabposition`` alone keeps the left-to-right order."""
    if not active():
        return 0
    ttk.Style(notebook).configure("TNotebook", tabposition="ne")
    _STATE["notebook"] = True
    tabs = list(notebook.tabs())
    for tab in tabs:
        notebook.insert(0, tab)
    return len(tabs)


def mirror_panes(paned: ttk.PanedWindow) -> int:
    """Reverse the panes of a horizontal ``ttk.PanedWindow`` (first pane at the right)."""
    if not active() or str(paned.cget("orient")) != "horizontal":
        return 0
    panes = list(paned.panes())
    for pane in panes:
        paned.insert(0, pane)
    return len(panes)


__all__ = ["ENV_OVERRIDE", "KEEP_ATTR", "MIRRORED_ATTR", "OWN_LAYOUT_ATTR", "STYLE_PREFIX",
           "active", "flip_anchor", "flip_justify", "flip_padx", "flip_side", "flip_sticky",
           "grid_kw", "install_window_hook", "keep_ltr", "manages_own_layout",
           "mirror_notebook", "mirror_panes", "mirror_tree", "mirror_window", "mirrored",
           "pack_kw", "refresh_styles", "rtl_style", "text_kw"]
