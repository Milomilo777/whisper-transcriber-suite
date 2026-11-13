"""Windowless regression for translated quality headings through the real panel builder."""
from types import SimpleNamespace
from tkinter import font as tkfont

import pytest

from app.dialogs import transcript_viewer as tv


class Widget:
    def __init__(self, *args, **kwargs):
        self.columns = {}; self.headings = {}

    def pack(self, **kwargs): pass
    def grid(self, **kwargs): pass
    def bind(self, *args): pass
    def configure(self, **kwargs): pass
    def columnconfigure(self, *args, **kwargs): pass
    def rowconfigure(self, *args, **kwargs): pass
    def set(self, *args): pass
    def xview(self, *args): pass
    def yview(self, *args): pass
    def cget(self, key): return ''
    def heading(self, key, **kwargs): self.headings[key] = kwargs['text']
    def column(self, key, **kwargs): self.columns[key] = kwargs


@pytest.mark.parametrize('factor', [1, 2])
@pytest.mark.parametrize('cue', ['Segment de subtítols', 'Titulkový blok', 'Undertekstblok'])
def test_quality_heading_fits_measured_font_without_collapsing_other_columns(monkeypatch, factor, cue):
    for name in ['Frame', 'Label', 'Combobox', 'Treeview', 'Scrollbar']:
        monkeypatch.setattr(tv.ttk, name, Widget)
    monkeypatch.setattr(tv.tk, 'StringVar', lambda **kwargs: object())
    monkeypatch.setattr(tv, 'px', lambda n: n * factor)
    monkeypatch.setattr(tv, '_', lambda message: cue if message == 'Cue' else message)
    monkeypatch.setattr(tv.ttk, 'Style', lambda *args: SimpleNamespace(lookup=lambda *args: 'HeadingFont'))
    measured = lambda text: len(text) * 8 * factor
    monkeypatch.setattr(tkfont, 'Font', lambda **kwargs: SimpleNamespace(measure=measured))
    viewer = SimpleNamespace(_refresh_quality=lambda: None, _on_qc_select=lambda event: None)
    tv.TranscriptViewer._build_quality_panel(viewer, Widget())
    for key in ['cue', 'level', 'finding']:
        options = viewer._qc_tree.columns[key]
        assert options['width'] >= measured(viewer._qc_tree.headings[key]) + 16 * factor
        assert options['minwidth'] >= measured(viewer._qc_tree.headings[key]) + 16 * factor
        assert options['stretch'] is (key == 'finding')
    assert viewer._qc_tree.columns['finding']['width'] == 240 * factor
