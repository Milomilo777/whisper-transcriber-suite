"""PDF export: yt-dlp look-alike path characters fall back to ASCII only when no font can draw them."""
import pytest

from core.writers import pdf_fonts, pdf_writer

LOOKALIKES = "⧸ ⧹ ： ？ ＊ ＜ ＞ ｜ ＂"


def test_replace_missing_lookalikes_only_without_glyph():
    assert pdf_writer.replace_missing_lookalikes(LOOKALIKES, lambda ch: False) == '/ \\ : ? * < > | "'
    assert pdf_writer.replace_missing_lookalikes(LOOKALIKES, lambda ch: True) == LOOKALIKES
    # Other scripts are never touched, covered or not.
    for text in ("سلام دنیا", "你好世界", "a/b:c"):
        assert pdf_writer.replace_missing_lookalikes(text, lambda ch: False) == text


@pytest.fixture()
def no_lookalike_glyphs(monkeypatch):
    """Make every font miss the look-alike characters, whatever fonts this machine has."""
    real = pdf_fonts.FontChain.font_for

    def font_for(self, ch, preferred=None):
        if ord(ch) in (0x29F8, 0xFF1A):
            return None
        return real(self, ch, preferred)

    monkeypatch.setattr(pdf_fonts.FontChain, "font_for", font_for)


def _pdf_text(pdf_bytes: bytes) -> str:
    fitz = pytest.importorskip("fitz", reason="PyMuPDF reads the text back")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "".join(page.get_text() for page in doc)


def test_title_and_body_fall_back_when_fonts_lack_the_glyph(no_lookalike_glyphs):
    segments = [{"start": 0.0, "end": 1.0, "text": "Lookalike ⧸ char and ：", "speaker": "A⧸B"}]
    text = _pdf_text(pdf_writer.write_bytes(segments, "Video ⧸ title.mp3"))
    assert "⧸" not in text and "：" not in text
    assert "Video / title.mp3" in text
    assert "Lookalike / char and :" in text
    assert "A/B" in text


def test_covered_lookalike_is_kept(monkeypatch):
    real = pdf_fonts.FontChain.font_for
    covered = []

    def font_for(self, ch, preferred=None):
        found = real(self, ch, preferred)
        if ord(ch) == 0x29F8:
            covered.append(found is not None)
        return found

    monkeypatch.setattr(pdf_fonts.FontChain, "font_for", font_for)
    text = _pdf_text(pdf_writer.write_bytes([{"start": 0.0, "end": 1.0, "text": "x ⧸ y"}], "t.mp3"))
    if not covered or not all(covered):
        pytest.skip("no font on this machine draws U+29F8, so the kept-glyph path cannot be shown here")
    assert "x ⧸ y" in text
