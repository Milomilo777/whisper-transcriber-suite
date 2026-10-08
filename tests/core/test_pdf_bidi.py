"""Right-to-left lines in the PDF writer (core.writers.pdf_bidi).

Two layers:
- the line layout (breaking, prefix placement, direction) runs against a
  stand-in engine, so it is tested on every machine;
- the real engine (arabic-reshaper + python-bidi) is tested when both
  packages are installed and skipped otherwise.

Arabic-script samples are written as escapes so the file stays ASCII.
"""
from __future__ import annotations

import logging
import random
import unicodedata
from collections import Counter

import pytest

from core.writers import pdf_bidi, pdf_fonts, pdf_writer

# Persian "salam" (seen, lam, alef, meem).
SALAM = "\u0633\u0644\u0627\u0645"
# Persian "donya" (dal, noon, yeh).
DONYA = "\u062f\u0646\u06cc\u0627"
# Persian "mi-khaham": meem, Farsi yeh, ZWNJ, khah, alef, heh, meem.
MIKHAHAM = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
# Arabic "la" (lam + alef): one ligature glyph when shaped.
LA = "\u0644\u0627"
# Urdu "Pakistan" with Urdu yeh barree: peh alef kaf seen teh alef noon.
PAKISTAN = "\u067e\u0627\u06a9\u0633\u062a\u0627\u0646"
# Extended Arabic-Indic digits 1403.
FA_1403 = "\u06f1\u06f4\u06f0\u06f3"


# ---------------------------------------------------------- stand-in engine


def _fake_reorder(line: str, base: str) -> str:
    """Toy UAX #9: reverse each run of strong-RTL letters, and in an RTL
    line also the order of the space-separated words."""
    words = line.split(" ")
    out = []
    for word in words:
        chars, run = [], []
        for ch in word:
            if unicodedata.bidirectional(ch) in ("R", "AL"):
                run.append(ch)
            else:
                chars.extend(reversed(run))
                run = []
                chars.append(ch)
        chars.extend(reversed(run))
        out.append("".join(chars))
    if base == "R":
        out.reverse()
    return " ".join(out)


FAKE = pdf_bidi.Engine(reshape=str.upper, reorder=_fake_reorder)


def _measure(text: str, bold: bool) -> float:
    return 10.0 * len(text) + (5.0 if bold else 0.0)


def _flat(line: list[tuple[str, bool]]) -> str:
    return "".join(text for text, _ in line)


def test_needs_bidi_only_for_rtl_letters():
    assert pdf_bidi.needs_bidi("Hello " + SALAM)
    assert pdf_bidi.needs_bidi("\u05e9\u05dc\u05d5\u05dd")  # Hebrew "shalom"
    assert not pdf_bidi.needs_bidi("Hello world 123")
    assert not pdf_bidi.needs_bidi("\u041f\u0440\u0438\u0432\u0435\u0442 \u4f60\u597d")
    assert not pdf_bidi.needs_bidi(FA_1403)  # digits alone carry no direction


def test_rtl_line_puts_prefix_at_the_right_end():
    lines, rtl = pdf_bidi.layout("[00:00:01]", f"{SALAM} {DONYA}", 1000, _measure, FAKE)
    assert rtl
    assert len(lines) == 1
    # visual order left to right: body, space, bold prefix
    assert lines[0][-1] == ("[00:00:01]", True)
    body = _flat(lines[0][:-2])
    assert body == f"{DONYA[::-1]} {SALAM[::-1]}"


def test_ltr_line_keeps_prefix_first_and_reverses_only_the_rtl_word():
    lines, rtl = pdf_bidi.layout("[00:00:01]", f"Hello {SALAM} world", 1000, _measure, FAKE)
    assert not rtl
    assert lines[0][0] == ("[00:00:01]", True)
    assert _flat(lines[0][2:]) == f"HELLO {SALAM[::-1]} WORLD"


def test_direction_comes_from_the_prefix_when_the_body_has_no_letters():
    _, rtl = pdf_bidi.layout(f"[00:00:01] {SALAM}:", "123 456", 1000, _measure, FAKE)
    assert rtl


def test_lines_fit_the_width_and_break_in_logical_order():
    words = [SALAM, DONYA, "abc", "12", MIKHAHAM, LA] * 6
    body = " ".join(words)
    width = 230.0
    lines, rtl = pdf_bidi.layout("[00:00:01]", body, width, _measure, FAKE)
    assert rtl and len(lines) > 2
    for i, line in enumerate(lines):
        total = sum(_measure(text, bold) for text, bold in line)
        assert total <= width, (i, line)
    # Undo the stand-in reorder per line: the lines read in order give back
    # every word of the shaped body, none lost, none moved across lines.
    logical = []
    for i, line in enumerate(lines):
        body_part = line[:-2] if i == 0 else line
        logical.append(_fake_reorder(_flat(body_part), "R"))
    assert " ".join(logical) == body.upper()


def test_word_wider_than_the_line_is_split_between_letters_not_marks():
    # Arabic "kataba" with fatha on every letter: a mark must stay on its letter.
    word = "\u0643\u064e\u062a\u064e\u0628\u064e" * 8
    lines, _ = pdf_bidi.layout("", word, 75.0, _measure, FAKE)
    assert len(lines) > 1
    pieces = [_fake_reorder(_flat(line), "R") for line in lines]
    assert "".join(pieces) == word.upper()
    for piece in pieces:
        assert unicodedata.category(piece[0]) != "Mn"
        assert _measure(piece, False) <= 75.0


def test_empty_prefix_gives_body_only():
    lines, rtl = pdf_bidi.layout("", SALAM, 1000, _measure, FAKE)
    assert rtl
    assert lines == [[(SALAM[::-1], False)]]


def _undo(lines: list[list[tuple[str, bool]]], base: str) -> tuple[str, str]:
    """Logical (prefix, body) text back from laid-out lines (stand-in engine)."""
    prefix, body = [], []
    for line in lines:
        head = "".join(t for t, bold in line if bold)
        rest = "".join(t for t, bold in line if not bold).strip(" ")
        if head:
            prefix.append(_fake_reorder(head, base))
        if rest:
            body.append(_fake_reorder(rest, base))
    return " ".join(prefix), " ".join(body)


def test_layout_property_no_word_lost_and_lines_fit():
    rng = random.Random(56)
    alphabet = [SALAM, DONYA, MIKHAHAM, LA, PAKISTAN, FA_1403, "Google", "2024", "(x)", "-", "a"]
    speakers = ["", "Bob", SALAM, "Wide Speaker Name " * 3, f"{DONYA} " * 6]
    for _ in range(500):
        body = " ".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        speaker = rng.choice(speakers).strip()
        prefix = rng.choice(["", f"[01:02:03] {speaker}:" if speaker else "[00:00:01]"])
        width = rng.choice([40.0, 90.0, 150.0, 400.0, 2000.0])
        lines, rtl = pdf_bidi.layout(prefix, body, width, _measure, FAKE)
        for line in lines:
            assert sum(_measure(t, b) for t, b in line) <= width, (width, line)
        got_prefix, got_body = _undo(lines, "R" if rtl else "L")
        # in order, nothing lost or added (narrow widths split long words)
        assert "".join(got_body.split()) == "".join(body.upper().split())
        assert "".join(got_prefix.split()) == "".join(prefix.upper().split())


def test_prefix_wider_than_the_line_gets_its_own_lines():
    prefix = "[00:00:01] " + "Wide Speaker Name " * 4 + ":"
    lines, rtl = pdf_bidi.layout(prefix, f"{SALAM} {DONYA}", 200.0, _measure, FAKE)
    assert rtl
    for line in lines:
        assert sum(_measure(t, b) for t, b in line) <= 200.0
    bold_lines = [line for line in lines if all(b for _, b in line)]
    assert len(bold_lines) >= 2
    assert lines[-1] == [(f"{DONYA[::-1]} {SALAM[::-1]}", False)]


def test_writer_lines_are_not_rewrapped_by_reportlab(monkeypatch):
    # Every row pdf_bidi breaks must stay one line in reportlab, even with a
    # speaker name wider than the page.
    from reportlab.platypus import Paragraph

    monkeypatch.setattr(pdf_bidi, "engine", lambda: FAKE)
    seen: list[tuple[int, int]] = []
    real_wrap = Paragraph.wrap

    def wrap(self, aw, ah):
        out = real_wrap(self, aw, ah)
        if self.style.name == "BodyRTL":
            seen.append((self.text.count("<br/>") + 1, len(self.blPara.lines)))
        return out

    monkeypatch.setattr(Paragraph, "wrap", wrap)
    long_speaker = "Wide Speaker Name " * 8
    body = " ".join([SALAM, DONYA, MIKHAHAM] * 40)
    pdf_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": body, "speaker": long_speaker},
         {"start": 3.0, "end": 4.0, "text": body}],
        "a.mp4",
    )
    assert seen
    for rows, drawn in seen:
        assert rows == drawn


# ------------------------------------------------------- missing packages


def test_missing_packages_write_unshaped_pdf_and_warn_once(monkeypatch, caplog):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.split(".")[0] in ("arabic_reshaper", "bidi"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(pdf_bidi, "_ENGINE", None)
    monkeypatch.setattr(pdf_bidi, "_LOADED", False)
    caplog.set_level(logging.WARNING, logger=pdf_bidi.__name__)
    seg = [{"start": 0.0, "end": 1.0, "text": f"{SALAM} {DONYA}"}]
    first = pdf_writer.write_bytes(seg, "a.mp4")
    second = pdf_writer.write_bytes(seg, "b.mp4")
    assert first.startswith(b"%PDF") and second.startswith(b"%PDF")
    warnings = [r for r in caplog.records if r.name == pdf_bidi.__name__]
    assert len(warnings) == 1
    assert "arabic-reshaper" in warnings[0].getMessage()


def test_latin_only_pdf_never_loads_the_engine(monkeypatch):
    def boom() -> None:
        raise AssertionError("engine loaded for a Latin-only transcript")

    monkeypatch.setattr(pdf_bidi, "engine", boom)
    data = pdf_writer.write_bytes([{"start": 0.0, "end": 1.0, "text": "plain text"}], "a.mp4")
    assert data.startswith(b"%PDF")


def test_writer_uses_the_engine_for_rtl_segments(monkeypatch):
    monkeypatch.setattr(pdf_bidi, "engine", lambda: FAKE)
    fitz = pytest.importorskip("fitz")
    data = pdf_writer.write_bytes(
        [{"start": 1.0, "end": 2.0, "text": f"{SALAM} {DONYA}", "speaker": "Bob"}], "a.mp4"
    )
    text = "".join(page.get_text() for page in fitz.open(stream=data, filetype="pdf"))
    # the stand-in reshape upper-cases, so its output is visible in the PDF
    assert "BOB" in text


# ------------------------------------------------------------ real engine


def _real_engine() -> pdf_bidi.Engine:
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi.algorithm")
    pdf_bidi._ENGINE = None
    pdf_bidi._LOADED = False
    eng = pdf_bidi.engine()
    assert eng is not None
    return eng


def _letters(text: str) -> Counter:
    """Letters and digits after folding presentation forms back (NFKC)."""
    folded = unicodedata.normalize("NFKC", text)
    return Counter(ch for ch in folded if unicodedata.category(ch)[0] in "LN")


def _is_presentation_form(ch: str) -> bool:
    cp = ord(ch)
    return 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def test_real_engine_joins_persian_letters():
    eng = _real_engine()
    shaped = eng.reshape(SALAM)
    assert all(_is_presentation_form(ch) for ch in shaped)
    assert _letters(shaped) == _letters(SALAM)


def test_real_engine_lam_alef_is_one_ligature():
    eng = _real_engine()
    shaped = eng.reshape(LA)
    assert len(shaped) == 1 and _is_presentation_form(shaped)
    assert unicodedata.normalize("NFKC", shaped) == LA


def test_real_engine_zwnj_breaks_the_join():
    eng = _real_engine()
    shaped = eng.reshape(MIKHAHAM)
    khah = shaped[shaped.index("\u200c") + 1]
    # after a ZWNJ, khah starts a new joined group: initial form, not medial
    assert unicodedata.name(khah).endswith("INITIAL FORM")


def test_real_engine_keeps_numbers_and_latin_left_to_right_in_an_rtl_line():
    eng = _real_engine()
    line = eng.reshape(f"{SALAM} 2024 {FA_1403} Google")
    visual = eng.reorder(line, "R")
    assert "2024" in visual
    assert FA_1403 in visual
    assert "Google" in visual
    # the first logical word sits at the right end; reverse before NFKC because
    # the lam-alef ligature is one visual glyph that folds to two letters
    assert unicodedata.normalize("NFKC", visual[::-1]).startswith(SALAM + " ")


def test_real_engine_mirrors_brackets_in_rtl():
    eng = _real_engine()
    visual = eng.reorder(eng.reshape(f"({SALAM})"), "R")
    assert visual[0] == "(" and visual[-1] == ")"


def test_real_engine_leaves_latin_unchanged():
    eng = _real_engine()
    for text in ("Hello world", "a (b) c, 12:30 - x.", "Mixed CASE 2024!"):
        assert eng.reorder(eng.reshape(text), "L") == text


def test_real_engine_property_no_letter_lost_or_added():
    eng = _real_engine()
    rng = random.Random(5602)
    pool = (
        [chr(c) for c in range(0x0621, 0x064B)]  # Arabic letters
        + ["\u067e", "\u0686", "\u0698", "\u06a9", "\u06af", "\u06cc", "\u06d2", "\u0679"]
        + ["\u064e", "\u064f", "\u0650", "\u0651"]  # harakat
        + ["\u200c", " ", " ", " ", "(", ")", ".", ",", "\u060c", "\u061f", ":", "-"]
        + list("abcXYZ0123456789")
        + [chr(c) for c in range(0x06F0, 0x06FA)]
    )
    for _ in range(500):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(1, 60)))
        shaped = eng.reshape(text)
        for base in ("L", "R"):
            visual = eng.reorder(shaped, base)
            assert _letters(visual) == _letters(text), (text, base)


def test_real_engine_keeps_marks_before_their_base_in_rtl():
    # reportlab draws a zero-width mark at the pen position; the system
    # fonts place it over the glyph that FOLLOWS in drawing order, so the
    # mark must precede its base in the visual string (no UAX #9 rule L3).
    eng = _real_engine()
    word = "\u0628\u064e\u0628"  # beh, fatha, beh
    visual = eng.reorder(eng.reshape(word), "R")
    mark = visual.index("\u064e")
    assert mark + 1 < len(visual)
    assert unicodedata.normalize("NFKC", visual[mark + 1]) == "\u0628"


def test_real_pdf_persian_line_is_joined():
    _real_engine()
    sample = f"{SALAM} {DONYA}"
    chain = pdf_fonts.default_chain()
    if any(chain.font_for(ch) is None for ch in sample.replace(" ", "")):
        pytest.skip("no system font covers Arabic script")
    fitz = pytest.importorskip("fitz")
    data = pdf_writer.write_bytes([{"start": 1.0, "end": 2.0, "text": sample}], "a.mp4")
    text = "".join(page.get_text() for page in fitz.open(stream=data, filetype="pdf"))
    assert any(_is_presentation_form(ch) for ch in text)
    assert not _letters(sample) - _letters(text)
