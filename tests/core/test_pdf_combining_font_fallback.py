"""Combining characters must use an available font that has their glyph."""
from __future__ import annotations
import unittest
from core.writers.pdf_fonts import FontChain

class Font:
    def __init__(self,name: str,chars: str) -> None:
        self.name=name;self.bold_name=name;self.chars=set(map(ord,chars))
    def usable(self) -> bool:return True
    def covers(self,cp: int) -> bool:return cp in self.chars

class CombiningFontTests(unittest.TestCase):
    def test_uncovered_combining_mark_uses_available_fallback(self) -> None:
        arabic=Font('Arabic','\u0627');thai=Font('Thai','\u0627\u0e35')
        chain=FontChain([arabic,thai])
        self.assertEqual(chain.split_runs('\u0627\u0e35'),[('Arabic','\u0627'),('Thai','\u0e35')])

    def test_leading_combining_mark_uses_its_covering_font(self) -> None:
        latin=Font('Latin','a');thai=Font('Thai','\u0e35')
        self.assertEqual(FontChain([latin,thai]).split_runs('\u0e35a'),[('Thai','\u0e35'),('Latin','a')])

    def test_covered_combining_mark_stays_with_its_base(self) -> None:
        latin=Font('Latin','a\u0301');other=Font('Other','\u0301')
        self.assertEqual(FontChain([latin,other]).split_runs('a\u0301'),[('Latin','a\u0301')])

    def test_mark_without_any_covering_font_is_not_dropped(self) -> None:
        latin=Font('Latin','a')
        self.assertEqual(FontChain([latin]).split_runs('a\u0e35'),[('Latin','a\u0e35')])

    def test_spaces_and_format_controls_keep_their_existing_run(self) -> None:
        latin=Font('Latin','a');other=Font('Other',' \u00ad')
        self.assertEqual(FontChain([latin,other]).split_runs('a \u00ad'),[('Latin','a \u00ad')])

if __name__=='__main__':unittest.main()
