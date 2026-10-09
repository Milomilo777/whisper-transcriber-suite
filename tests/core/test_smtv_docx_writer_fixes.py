"""SMTV docx writer: right-to-left cells and segments whose text is the number 0."""
from __future__ import annotations

import io
import re

import pytest

pytest.importorskip("docx")

import docx  # noqa: E402

from core.writers import smtv_docx_writer  # noqa: E402

FA = "سلام دنیا، این یک آزمایش است."
FIRST_DATA_ROW = 2


def _table(segments: list[dict]):
    data = smtv_docx_writer.write_bytes(
        segments, "clip.wav", language="fa", work_title="clip"
    )
    return docx.Document(io.BytesIO(data)).tables[0]


def _cell_xml(table, row: int) -> str:
    from lxml import etree

    return etree.tostring(table.rows[row].cells[2]._tc, encoding="unicode")


def _seg(text, start=1.0) -> dict:
    return {"start": start, "end": start + 1.0, "text": text}


def _has(xml: str, tag: str) -> bool:
    return re.search(rf"<w:{tag}(/| )", xml) is not None


def test_text_of_zero_keeps_its_row():
    table = _table([_seg(0), _seg("hello", 2.0)])
    row = table.rows[FIRST_DATA_ROW + 1].cells
    assert row[2].text == "hello"
    assert row[0].text == "2"
    assert "0" in table.rows[FIRST_DATA_ROW].cells[2].text


def test_rtl_cell_has_bidi_paragraph_and_rtl_run():
    table = _table([_seg("first"), _seg(FA, 2.0)])
    xml = _cell_xml(table, FIRST_DATA_ROW + 1)
    assert FA in xml
    assert _has(xml, "bidi")
    assert _has(xml, "rtl")


def test_rtl_text_after_the_start_marker_has_an_rtl_run():
    # Row 1 holds "[(Persian) starts]" first; the paragraph stays LTR so the
    # marker is not scrambled, and the text run itself is right-to-left.
    table = _table([_seg(FA)])
    xml = _cell_xml(table, FIRST_DATA_ROW)
    run = next(r for r in re.findall(r"<w:r[ >].*?</w:r>", xml, flags=re.S) if FA in r)
    assert _has(run, "rtl")


def test_ltr_cell_has_no_direction_marks():
    table = _table([_seg("plain english", 1.0), _seg("more english", 2.0)])
    xml = _cell_xml(table, FIRST_DATA_ROW + 1)
    assert "more english" in xml
    assert not _has(xml, "bidi")
    assert not _has(xml, "rtl")


def test_a_cloned_row_does_not_inherit_the_direction_of_the_row_it_copies():
    # 31 template rows are Persian; the 32nd row is cloned from the last one.
    segments = [_seg(FA, float(n)) for n in range(31)] + [_seg("english tail", 40.0)]
    table = _table(segments)
    assert len(table.rows) == FIRST_DATA_ROW + 32
    assert _has(_cell_xml(table, FIRST_DATA_ROW + 30), "bidi")
    tail = _cell_xml(table, FIRST_DATA_ROW + 31)
    assert "english tail" in tail
    assert not _has(tail, "bidi")
    assert not _has(tail, "rtl")


@pytest.mark.parametrize("speaker", ["Speaker 1", "SPEAKER_00"])
def test_a_short_persian_line_stays_right_to_left_with_a_latin_speaker_label(speaker):
    # The label ("Speaker 1: ") has more Latin letters than "بله" has Persian ones; the
    # direction follows the text, as the plain DOCX writer does.
    table = _table([
        {"start": 1.0, "end": 2.0, "text": "بله", "speaker": speaker},
        {"start": 2.0, "end": 3.0, "text": "بله", "speaker": speaker},
    ])
    xml = _cell_xml(table, FIRST_DATA_ROW + 1)
    assert speaker in xml
    assert _has(xml, "bidi")
    assert _has(xml, "rtl")
    first = _cell_xml(table, FIRST_DATA_ROW)
    run = next(r for r in re.findall(r"<w:r[ >].*?</w:r>", first, flags=re.S) if "بله" in r)
    assert _has(run, "rtl")


def test_a_latin_line_with_a_persian_speaker_label_stays_left_to_right():
    table = _table([
        {"start": 1.0, "end": 2.0, "text": "ok", "speaker": "ali"},
        {"start": 2.0, "end": 3.0, "text": "ok", "speaker": "مهمان یک"},
    ])
    xml = _cell_xml(table, FIRST_DATA_ROW + 1)
    assert not _has(xml, "bidi")
    assert not _has(xml, "rtl")
