"""Real Tk heading metrics; run on the shared desktop worker."""
from types import SimpleNamespace
from tkinter import font as tkfont
import tkinter as tk
from tkinter import ttk

import pytest

from app.dialogs import transcript_viewer as tv


@pytest.mark.parametrize('cue', ['Segment de subtítols', 'Titulkový blok', 'Undertekstblok'])
@pytest.mark.parametrize('large_font', [False, True])
def test_real_quality_headings_fit_current_ttk_font(monkeypatch, cue, large_font):
    root = tk.Tk()
    root.withdraw()
    try:
        if large_font:
            ttk.Style(root).configure('Treeview.Heading', font=('TkDefaultFont', 24, 'bold'))
        monkeypatch.setattr(tv, '_', lambda message: cue if message == 'Cue' else message)
        viewer = SimpleNamespace(_refresh_quality=lambda: None, _on_qc_select=lambda event: None)
        parent = ttk.Frame(root)
        parent.pack()
        tv.TranscriptViewer._build_quality_panel(viewer, parent)
        root.update_idletasks()
        specification = ttk.Style(root).lookup('Treeview.Heading', 'font') or 'TkHeadingFont'
        heading = tkfont.Font(root=root, font=specification)
        for key in ['cue', 'level', 'finding']:
            needed = heading.measure(viewer._qc_tree.heading(key, 'text')) + tv.px(16)
            assert viewer._qc_tree.column(key, 'width') >= needed
            assert viewer._qc_tree.column(key, 'minwidth') >= needed
    finally:
        root.destroy()
