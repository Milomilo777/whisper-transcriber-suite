"""Windows production-theme severity cells, all shipped catalogs at two DPI factors.

Run on the admitted interactive Windows test worker. Padding combines the real
data-cell layout's intrinsic request with Tk8.6's separate renderer insets, not
the viewer's width formula. No widget, font, translation or style lookup is replaced.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import sv_ttk

from app import dpi, i18n
from app.dialogs import transcript_viewer as tv
from app.theme import script_fonts


CATALOGS = sorted((Path(tv.__file__).parents[1] / "locales").glob("*.json"))


def _layout_elements(layout):
    """Yield live ttk element names, including nested inherited layout elements."""
    for name, options in layout:
        yield name
        yield from _layout_elements(options.get("children", []))


def cell_text_padding(tree, item, column, row_font):
    """Measure the live data-cell layout's requested size with the actual row font.

    Tk8.6 identify_element can describe the first-column Item parcel even for a
    data-column coordinate, so hit-test offsets cannot establish cell padding.
    A throwaway label uses an exact clone of Treeview.Cell, including the real
    Treedata.padding element and its C defaults. Its natural width minus the
    same font's measured text is the theme's intrinsic horizontal overhead.
    Tk's renderer separately insets that layout inside the column's bbox.
    """
    bbox = tree.bbox(item, column)
    assert bbox, ("Cell is not mapped", item, column)
    style = ttk.Style(tree)
    layout = style.layout("Treeview.Cell")
    elements = list(_layout_elements(layout))
    assert "Treedata.padding" in elements and "Treeitem.text" in elements, layout
    assert not any(name.endswith(".indicator") for name in elements), layout
    probe_style = "QualityMeasure.Treeview.Cell"
    style.layout(probe_style, layout)
    assert style.layout(probe_style) == layout
    # Clone inherits Cell's style chain. Only font is overridden: real rows use
    # Treeview's WtsTreeFont, while Cell's inherited font can still be sv_ttk's.
    style.configure(probe_style, font=str(row_font))
    options = {element: list(style.element_options(element)) for element in elements}
    text = str(tree.set(item, column))
    measurements = []
    for sample in (text, "MMMM", "iiii"):
        label = ttk.Label(tree, text=sample, font=row_font, style=probe_style, width=0)
        try:
            label.state(tree.state())
            label.update_idletasks()
            requested = label.winfo_reqwidth()
            measured = row_font.measure(sample)
            measurements.append({"text": sample, "requested": requested,
                                 "measured": measured, "overhead": requested - measured})
        finally:
            label.destroy()
    intrinsic = measurements[0]["overhead"]
    assert intrinsic >= 0 and all(m["overhead"] == intrinsic for m in measurements), measurements
    tk_version = str(tree.tk.call("set", "tk_patchLevel"))
    assert tk_version.split(".")[:2] == ["8", "6"], ("Unverified Treeview renderer", tk_version)
    # Adapted from Tk DrawCells (https://github.com/tcltk/tk/blob/core-8-6-branch/generic/ttk/ttkTreeview.c)
    # — its cellPadding={4,0,4,0} insets the Cell layout inside bbox. These are
    # fixed renderer pixels at both DPI factors, separate from theme padding.
    renderer_left = renderer_right = 4
    return {"total": intrinsic + renderer_left + renderer_right,
            "intrinsic": intrinsic, "renderer_left": renderer_left,
            "renderer_right": renderer_right, "tk_version": tk_version,
            "renderer_source": "Tk8.6 DrawCells cellPadding={4,0,4,0}",
            "bbox": list(bbox), "layout": layout,
            "element_options": options, "source_style": "Treeview.Cell",
            "source_padding_lookup": str(style.lookup("Treeview.Cell", "padding", tree.state())),
            "probe_font": str(row_font), "measurements": measurements}


def prepare_production_theme(root, factor):
    """Change only this Tcl interpreter's DPI, then run the application startup chain."""
    assert sys.platform == "win32", "This gate requires the real Windows production font chain"
    assert tk._default_root is root, "Production implicit-root theme/StringVar calls must target this root"
    root.tk.call("tk", "scaling", float(factor) * 96.0 / 72.0)
    sv_ttk.set_theme("light")
    script_fonts.apply_theme_fonts(root)
    actual_factor = dpi.remember_scale(root)
    assert abs(actual_factor - factor) <= 0.02, (factor, actual_factor)
    assert dpi.px(100) == round(100 * actual_factor)
    root.update()
    body_size = int(root.tk.call("font", "configure", "SunValleyBodyFont", "-size"))
    base_size = int(root.tk.call("set", "wts_theme_font_base(SunValleyBodyFont)"))
    assert body_size < 0 and base_size < 0
    if factor == 2:
        assert abs(body_size) >= 1.9 * abs(base_size), (base_size, body_size)
    return {"requested_factor": factor, "actual_factor": actual_factor,
            "tk_scaling": float(root.tk.call("tk", "scaling")),
            "dpi_px100": dpi.px(100), "theme": ttk.Style(root).theme_use(),
            "body_font_base_size": base_size, "body_font_size": body_size}


def measure_production_severity(root, locale):
    """Build the actual panel and return mapped Error/Warning cell measurements."""
    assert i18n.set_language(locale) == locale
    parent = ttk.Frame(root)
    parent.pack(fill="both", expand=True)
    viewer = SimpleNamespace(_refresh_quality=lambda: None, _on_qc_select=lambda event: None)
    tv.TranscriptViewer._build_quality_panel(viewer, parent)
    tree = viewer._qc_tree
    style = ttk.Style(tree)
    style_name = str(tree.cget("style")) or "Treeview"
    font_name = str(style.lookup(style_name, "font", tree.state()))
    assert font_name, ("Missing drawn row font", style_name)
    row_font = tkfont.nametofont(font_name, root=tree)
    labels = {key: i18n._(key) for key in ("Error", "Warning")}
    items = {key: tree.insert("", "end", values=("1", text, "")) for key, text in labels.items()}
    root.update()
    assert root.winfo_ismapped() and tree.winfo_ismapped()
    rows = []
    for key, item in items.items():
        assert not tree.item(item, "tags"), "A tag could override the style's drawn font"
        text = str(tree.set(item, "level"))
        assert text == labels[key]
        padding = cell_text_padding(tree, item, "level", row_font)
        rows.append({"key": key, "text": text, "text_pixels": row_font.measure(text),
                     "cell_pixels": padding["bbox"][2], "padding": padding,
                     "font_name": font_name, "font_actual": row_font.actual(),
                     "font_size": row_font.cget("size"), "style": style_name})
    return rows


def pytest_generate_tests(metafunc):
    # Keep the measurement helpers importable by the packaged native probe,
    # whose production interpreter does not need a pytest installation.
    if metafunc.function.__name__ == "test_quality_severity_fits_production_theme":
        cases = [(catalog, factor) for catalog in CATALOGS for factor in (1, 2)]
        metafunc.parametrize(("catalog", "factor"), cases,
                             ids=[f"{catalog.stem}-{factor * 100}pct" for catalog, factor in cases])


def test_quality_severity_fits_production_theme(catalog, factor, record_property):
    assert len(CATALOGS) == 42, "The native gate must exercise every shipped catalog"
    previous_catalog = i18n._STATE
    previous_factor = dpi._process_factor
    previous_families = script_fonts._families
    previous_missing = set(script_fonts._missing_logged)
    root = tk.Tk()
    previous_tk_scaling = root.tk.call("tk", "scaling")
    try:
        root.geometry("1200x800+0+0")
        scale = prepare_production_theme(root, factor)
        rows = measure_production_severity(root, catalog.stem)
        metrics = {"locale": catalog.stem, **scale, "rows": rows}
        record_property("quality_production_theme", json.dumps(metrics, ensure_ascii=True, sort_keys=True))
        for row in rows:
            assert row["cell_pixels"] >= row["text_pixels"] + row["padding"]["total"], metrics
    finally:
        try:
            i18n.set_language(previous_catalog.code)
        finally:
            with i18n._LOCK:
                i18n._STATE = previous_catalog
            dpi._process_factor = previous_factor
            script_fonts._families = previous_families
            script_fonts._missing_logged.clear()
            script_fonts._missing_logged.update(previous_missing)
            try:
                root.tk.call("tk", "scaling", previous_tk_scaling)
            finally:
                root.destroy()
