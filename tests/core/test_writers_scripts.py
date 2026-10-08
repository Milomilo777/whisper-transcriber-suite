"""Non-Latin scripts in the PDF / DOCX writers, and speaker labels in the
plain formats (txt, lrc, tsv, otr).

The PDF checks read the text back out of the produced file (PyMuPDF) and
skip when the machine has no system font for a script: the writer uses
the fonts the OS ships and bundles none.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from collections import Counter

import pytest

from core.writers import docx_writer, lrc, otr, pdf_fonts, pdf_writer, tsv, txt
from core.writers.base import is_rtl_text
from core.writers.smtv_docx_writer import language_name

SAMPLES = {
    "fa": "سلام دنیا، این یک آزمایش است",
    "ar": "مرحبا بالعالم، هذا اختبار",
    "ru": "Привет мир, это проверка",
    "zh": "你好世界，这是一个测试",
    "ja": "こんにちは世界、これはテストです",
    "he": "שלום עולם",
    "mixed": "Hello سلام Привет 你好 カタカナ",
}


def _pdf_text(data: bytes) -> str:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open(stream=data, filetype="pdf")
    return "".join(page.get_text() for page in doc)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _need_fonts(text: str) -> None:
    chain = pdf_fonts.default_chain()
    missing = [ch for ch in text if not ch.isspace() and chain.font_for(ch) is None]
    if missing:
        pytest.skip(f"no system font covers {missing[:3]!r}")


# ---------------------------------------------------------------- PDF


@pytest.mark.parametrize("lang", ["ru", "zh", "ja"])
def test_pdf_keeps_text_of_ltr_scripts(lang):
    sample = SAMPLES[lang]
    _need_fonts(sample)
    data = pdf_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": sample}], "clip.mp4"
    )
    assert _squash(sample) in _squash(_pdf_text(data))


@pytest.mark.parametrize("lang", ["fa", "ar", "he", "mixed"])
def test_pdf_draws_every_rtl_letter(lang):
    # With arabic-reshaper + python-bidi the letters are drawn as joined
    # presentation forms (folded back by NFKC); without them, unjoined
    # (see pdf_bidi). What must hold either way: every letter is a real
    # glyph that extracts as itself, never a placeholder.
    sample = SAMPLES[lang]
    _need_fonts(sample)
    data = pdf_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": sample}], "clip.mp4"
    )
    extracted = Counter(_squash(unicodedata.normalize("NFKC", _pdf_text(data))))
    assert not Counter(_squash(sample)) - extracted
    if lang == "mixed":
        text = _pdf_text(data)
        for part in ("Hello", "Привет", "你好", "カタカナ"):
            assert part in text


def test_pdf_title_and_speaker_in_other_scripts():
    _need_fonts("گزارش" + "Алиса")
    data = pdf_writer.write_bytes(
        [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "Алиса"}],
        "گزارش.mp4",
    )
    text = _pdf_text(data)
    # the title word, escaped: gaf, zain, alef, reh, sheen
    assert not Counter("\u06af\u0632\u0627\u0631\u0634") - Counter(unicodedata.normalize("NFKC", text))
    assert "Алиса: hi" in text


def test_pdf_without_any_system_font_still_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_fonts, "font_dirs", lambda: [str(tmp_path)])
    monkeypatch.setattr(pdf_fonts, "_DEFAULT_CHAIN", None)
    data = pdf_writer.write_bytes(
        [{"start": 0.0, "end": 1.0, "text": "plain <ascii> & text"}], "a.mp4"
    )
    assert data.startswith(b"%PDF")
    assert "plain <ascii> & text" in _pdf_text(data)


class _FakeFont:
    def __init__(self, name: str, chars: str) -> None:
        self.name = name
        self.bold_name = name
        self._chars = set(map(ord, chars))

    def usable(self) -> bool:
        return True

    def covers(self, cp: int) -> bool:
        return cp in self._chars


def _chain(*fonts: _FakeFont) -> pdf_fonts.FontChain:
    return pdf_fonts.FontChain(list(fonts))


def test_split_runs_falls_back_in_order():
    chain = _chain(_FakeFont("latin", "abc"), _FakeFont("cjk", "abc你好"))
    assert chain.split_runs("ab 你好 c") == [
        ("latin", "ab "), ("cjk", "你好 "), ("latin", "c"),
    ]


def test_split_runs_keeps_marks_and_joiners_with_their_letter():
    # A Persian letter with a kasra (U+0650) and a ZWNJ (U+200C): the
    # mark and the joiner must stay in the letter's run even though the
    # first font "covers" neither.
    # Invisible format characters are dropped: the fonts draw ZWNJ and
    # direction marks as a visible bar and unshaped text needs neither.
    chain = _chain(_FakeFont("latin", "a"), _FakeFont("arabic", "مي"))
    text = "a م" + "\u0650" + "\u200c" + "ي" + "\u200f"
    assert chain.split_runs(text) == [
        ("latin", "a "), ("arabic", "م" + "\u0650" + "ي"),
    ]


def test_split_runs_prefers_japanese_font_for_kanji_next_to_kana():
    zh = _FakeFont("zh", "世界こ")
    ja = _FakeFont("ja", "世界こ")
    chain = pdf_fonts.FontChain(
        [_FakeFont("latin", "a"), zh, ja], prefer={"kana": "ja"}
    )
    assert chain.split_runs("世界") == [("zh", "世界")]
    assert chain.split_runs("こ世界") == [("ja", "こ世界")]


def test_split_runs_uncovered_char_goes_to_first_font():
    chain = _chain(_FakeFont("latin", "a"), _FakeFont("other", "b"))
    assert chain.split_runs("a\U0001F600") == [("latin", "a\U0001F600")]


def test_markup_bold_names_the_bold_face_of_fallback_runs():
    cjk = _FakeFont("cjk", "你")
    cjk.bold_name = "cjk-Bold"
    chain = _chain(_FakeFont("latin", "a"), cjk)
    assert chain.markup("a你", bold=True) == 'a<font name="cjk-Bold">你</font>'
    assert chain.markup("a你") == 'a<font name="cjk">你</font>'


def _span_fonts(data: bytes) -> dict[str, str]:
    fitz = pytest.importorskip("fitz")
    page = fitz.open(stream=data, filetype="pdf")[0]
    return {
        span["text"].strip(): span["font"]
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
    }


def test_pdf_bold_speaker_and_title_in_fallback_font():
    _need_fonts("日本語")
    font = pdf_fonts.default_chain().font_for("語")
    assert font is not None
    if font.bold_name == font.name:
        pytest.skip("the CJK system font has no bold face here")
    data = pdf_writer.write_bytes(
        [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "日本語"}],
        "日本語.wav",
    )
    text = _pdf_text(data)
    assert text.count("日本語") == 2
    fonts = [f for t, f in _span_fonts(data).items() if t == "日本語"]
    assert fonts and all("Bold" in f for f in fonts)


def test_pdf_leaves_out_zero_width_characters():
    _need_fonts("میخواهم")
    data = pdf_writer.write_bytes(
        [{"start": 0.0, "end": 1.0, "text": "a" + "\u200c" + "b می" + "\u200c" + "خواهم"}],
        "a.mp4",
    )
    text = _pdf_text(data)
    assert "\u200c" not in text
    assert "ab" in text
    # shaping (when installed) emits presentation forms; NFKC folds them back
    assert not Counter("میخواهم") - Counter(unicodedata.normalize("NFKC", text))


def test_markup_escapes_and_tags_fallback_runs_only():
    chain = _chain(_FakeFont("latin", "a<&"), _FakeFont("cjk", "你"))
    assert chain.markup("a<&你") == 'a&lt;&amp;<font name="cjk">你</font>'


# ---------------------------------------------------------------- DOCX


def _document_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")


def _paragraphs(xml: str) -> list[str]:
    return re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)


@pytest.mark.parametrize("lang", ["fa", "ar", "he"])
def test_docx_rtl_paragraph_has_bidi_and_rtl_runs(lang):
    sample = SAMPLES[lang]
    xml = _document_xml(docx_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": sample}], "clip.mp4"
    ))
    para = next(p for p in _paragraphs(xml) if sample in p)
    assert "<w:bidi/>" in para or '<w:bidi w:val="1"/>' in para
    # Under w:bidi Word swaps the meaning of left/right alignment, so an
    # RTL paragraph must carry no left/right w:jc at all.
    assert not re.search(r'<w:jc w:val="(left|right)"/>', para)
    text_run = next(r for r in re.findall(r"<w:r>.*?</w:r>", para, flags=re.S)
                    if sample in r)
    assert "<w:rtl/>" in text_run or '<w:rtl w:val="1"/>' in text_run
    assert 'w:cs="' in text_run
    # The timestamp stays an LTR run inside the RTL paragraph.
    ts_run = next(r for r in re.findall(r"<w:r>.*?</w:r>", para, flags=re.S)
                  if "[00:00:01]" in r)
    assert "w:rtl" not in ts_run
    # Bold must also hold for the complex-script face Word uses there.
    assert "<w:bCs/>" in ts_run


@pytest.mark.parametrize("lang", ["ru", "zh", "ja", "mixed"])
def test_docx_ltr_paragraph_has_no_bidi(lang):
    sample = SAMPLES[lang]
    xml = _document_xml(docx_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": sample}], "clip.mp4"
    ))
    para = next(p for p in _paragraphs(xml) if sample in p)
    assert "w:bidi" not in para
    assert "w:rtl" not in para


def test_docx_persian_sentence_opening_with_latin_word_is_rtl():
    sample = "Google یک شرکت بزرگ است"
    xml = _document_xml(docx_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": sample}], "clip.mp4"
    ))
    para = next(p for p in _paragraphs(xml) if sample in p)
    assert "w:bidi" in para


def test_docx_rtl_title_and_speaker():
    xml = _document_xml(docx_writer.write_bytes(
        [{"start": 0.0, "end": 1.0, "text": "سلام", "speaker": "مریم"}],
        "گزارش.mp4",
    ))
    paras = _paragraphs(xml)
    title = next(p for p in paras if "گزارش.mp4" in p)
    assert "w:bidi" in title
    seg = next(p for p in paras if "سلام" in p)
    sp_run = next(r for r in re.findall(r"<w:r>.*?</w:r>", seg, flags=re.S)
                  if "مریم" in r)
    assert "w:rtl" in sp_run


def test_is_rtl_text_uses_first_strong_character():
    assert is_rtl_text("سلام دنیا world")
    assert is_rtl_text("Google یک شرکت بزرگ است")
    # A tie goes to the first strong letter.
    assert is_rtl_text("سل ab")
    assert not is_rtl_text("ab سل")
    assert is_rtl_text("  123 שלום")
    assert not is_rtl_text("world سلام")
    assert not is_rtl_text("123 ...")
    assert not is_rtl_text("")


# ---------------------------------------------------------------- speaker


_SPK = [
    {"start": 0.0, "end": 1.0, "text": "alpha", "speaker": "SPEAKER_00"},
    {"start": 1.0, "end": 2.0, "text": "beta"},
]


def test_txt_keeps_speaker():
    assert txt.write(_SPK) == "SPEAKER_00: alpha\nbeta\n"


def test_lrc_keeps_speaker():
    out = lrc.write(_SPK).splitlines()
    assert out[0].endswith("]SPEAKER_00: alpha")
    assert out[1].endswith("]beta")


def test_tsv_keeps_speaker_in_text_column():
    rows = tsv.write(_SPK).splitlines()
    assert rows[0] == "start\tend\ttext"
    assert rows[1] == "0\t1000\tSPEAKER_00: alpha"
    assert rows[2] == "1000\t2000\tbeta"


def test_empty_segment_gets_no_dangling_speaker_label():
    segs = [{"start": 0.0, "end": 1.0, "text": "  ", "speaker": "A"}]
    assert txt.write(segs) == "\n"
    assert lrc.write(segs).endswith("]\n")
    assert tsv.write(segs).splitlines()[1] == "0\t1000\t"
    assert "A:" not in json.loads(otr.write(segs))["text"]


def test_speaker_label_with_newline_stays_on_one_line():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "A\nB\tC"}]
    assert tsv.write(segs).splitlines()[1] == "0\t1000\tA B C: hi"
    assert txt.write(segs).splitlines() == ["A B C: hi"]


def test_otr_keeps_speaker():
    payload = json.loads(otr.write(_SPK))
    assert "SPEAKER_00: alpha" in payload["text"]
    assert "SPEAKER_00" not in payload["text"].split("beta")[1]


# ---------------------------------------------------------------- language


@pytest.mark.parametrize("code, name", [
    ("zh-TW", "Chinese (traditional)"),
    ("zh_TW", "Chinese (traditional)"),
    ("zh-tw", "Chinese (traditional)"),
    ("zh-CN", "Chinese (simplified)"),
    ("zh-Hant", "Chinese (traditional)"),
    ("zh-Hant-TW", "Chinese (traditional)"),
    ("zh-HK", "Chinese (traditional)"),
    ("zh-Hans", "Chinese (simplified)"),
    ("zh", "Chinese (simplified)"),
    ("pt-BR", "Portuguese"),
])
def test_language_name_tries_full_tag_first(code, name):
    assert language_name(code) == name
