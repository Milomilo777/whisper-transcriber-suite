"""Combining glyph coverage follows the base across logical and visual order."""
import unicodedata

import pytest

from core.writers import pdf_bidi, pdf_fonts
from tests.core.test_pdf_combining_font_fallback import Font


def test_leading_mark_does_not_move_into_an_uncovered_cjk_font():
    chain = pdf_fonts.FontChain([Font("Latin", "a\u0301"), Font("CJK", "你")])
    assert chain.split_runs("\u0301你") == [("Latin", "\u0301"), ("CJK", "你")]


def test_space_after_fallback_mark_stays_with_the_base():
    chain = pdf_fonts.FontChain([Font("Latin", "ab "), Font("Thai", "\u0e35")])
    assert chain.split_runs("a\u0e35 b") == [("Latin", "a"), ("Thai", "\u0e35"), ("Latin", " b")]


@pytest.mark.parametrize("mark", ["\u064e", "\u05b0"])
def test_visual_mark_prefers_its_following_rtl_base(mark):
    base = "ب" if mark == "\u064e" else "ב"
    chain = pdf_fonts.FontChain([Font("Latin", "a" + mark), Font("RTL", base + mark)])
    visual = pdf_bidi.VisualText("a" + mark + base, {1: 2})
    assert chain.split_runs(visual, visual_order=True) == [("Latin", "a"), ("RTL", mark + base)]


def test_real_bidi_layout_keeps_a_vowel_with_its_visual_base():
    engine = pdf_bidi.engine()
    if engine is None:
        pytest.skip("Arabic shaping dependencies unavailable")
    lines, _ = pdf_bidi.layout("", "بَ a", 1000, lambda t, b: len(t), engine)
    visual = lines[0][0][0]
    assert "\u064e" in visual
    arabic_chars = "".join(c for c in visual if unicodedata.bidirectional(c) == "AL")
    assert arabic_chars and visual.index("\u064e") < visual.index(arabic_chars[0])
    chain = pdf_fonts.FontChain([Font("Latin", "a \u064e"), Font("Arabic", arabic_chars + "\u064e")])
    runs = chain.split_runs(visual, visual_order=True)
    assert next(name for name, text in runs if "\u064e" in text) == "Arabic"


@pytest.mark.parametrize("mark", ["\u0e35", "\u093f", "\u20e3", "\ufe0f"])
def test_each_mark_category_preserves_text_and_selects_covering_run(mark):
    chain = pdf_fonts.FontChain([Font("Latin", "a "), Font("Other", mark)])
    runs = chain.split_runs("a" + mark)
    assert runs == [("Latin", "a"), ("Other", mark)]
    assert chain.markup("a" + mark, bold=True) == 'a<font name="Other">' + mark + '</font>'


def test_run_concatenation_preserves_all_visible_text():
    hypothesis = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st
    chain = pdf_fonts.FontChain([Font("Latin", "ab \u0301"), Font("Other", "你ب\u064e\u0e35\u093f\u20e3\ufe0f")])

    @hypothesis.given(st.text(alphabet="ab你ب \u0301\u064e\u0e35\u093f\u20e3\ufe0f\u200d", max_size=100))
    def check(text):
        for visual in (False, True):
            assert "".join(chunk for _, chunk in chain.split_runs(text, visual_order=visual)) == "".join(
                ch for ch in text if ch not in pdf_fonts._INVISIBLE)
    check()


@pytest.mark.parametrize("text", ["בa\u0301", "ב a\u0301"])
def test_visual_latin_accent_stays_with_latin_base(text):
    engine = pdf_bidi.engine()
    if engine is None:
        pytest.skip("Bidi dependencies unavailable")
    visual = engine.reorder(text, "R")
    assert visual.startswith("a\u0301") and visual.endswith("ב")
    chain = pdf_fonts.FontChain([Font("Latin", "a \u0301"), Font("Hebrew", "ב\u0301")])
    runs = chain.split_runs(visual, visual_order=True)
    assert next(name for name, chunk in runs if "\u0301" in chunk) == "Latin"


@pytest.mark.parametrize("text", ["بَ a", "a\u0301ב", "(בְ) á", "你好 بَ!", "\u202bبَ a\u202c"])
def test_visual_text_matches_unmodified_upstream_display(text):
    engine = pdf_bidi.engine()
    if engine is None:
        pytest.skip("Bidi dependencies unavailable")
    from bidi.algorithm import get_display
    for base in ("L", "R"):
        assert engine.reorder(text, base) == get_display(text, base_dir=base)


def test_bidi_control_removal_keeps_the_surviving_mark_base():
    engine = pdf_bidi.engine()
    if engine is None:
        pytest.skip("Bidi dependencies unavailable")
    visual = engine.reorder("\u202bبَ a\u202c", "R")
    assert "\u202b" not in visual and "\u202c" not in visual
    mark = visual.index("\u064e")
    assert visual[visual.mark_bases[mark]] == "ب"


def test_bold_markup_names_the_fallback_bold_face():
    latin, other = Font("Latin", "a"), Font("Other", "\u0e35")
    other.bold_name = "OtherBold"
    assert pdf_fonts.FontChain([latin, other]).markup("a\u0e35", bold=True) == (
        'a<font name="OtherBold">\u0e35</font>')


def test_real_pdf_keeps_the_mark_in_body_and_bold_speaker():
    pdfium = pytest.importorskip("pypdfium2", reason="read back exported PDF text")
    from core.writers import pdf_writer
    from reportlab.pdfbase import pdfmetrics

    chain = pdf_fonts.default_chain()
    font = chain.font_for("\u0e35")
    if font is None:
        pytest.skip("no installed font covers the Thai combining mark")
    assert ord("\u0e35") in pdfmetrics.getFont(font.bold_name).face.charToGlyph
    data = pdf_writer.write_bytes([
        dict(start=0., end=1., text="a\u0e35", speaker="a\u0e35")], "marks.wav")
    with pdfium.PdfDocument(data) as doc:
        assert len(doc) == 1
        page = doc[0]
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        textpage.close()
        page.close()
    assert text.count("\u0e35") == 2
    assert "\ufffd" not in text and "\x00" not in text
