"""The Queue's Language cell names the detected language ("Chinese", not "zh (88%)")."""
from __future__ import annotations


def test_language_cell_shows_the_name():
    from app.widgets.tabs import queue_language_cell

    assert queue_language_cell("zh", 0.88) == "Chinese"
    assert queue_language_cell("en", 1.0) == "English"
    assert queue_language_cell("fa", None) == "Persian"


def test_language_cell_says_when_the_detection_was_unsure():
    from app.widgets.tabs import queue_language_cell

    assert queue_language_cell("de", 0.31) == "German (not sure)"
    assert queue_language_cell("de", 0.5) == "German"
    # 0 = no detection ran (a chosen language on some engines), not "unsure".
    assert queue_language_cell("de", 0.0) == "German"
    assert queue_language_cell("pt", 0.9) == "Portuguese"


def test_language_cell_keeps_an_unknown_code_and_empty():
    from app.widgets.tabs import queue_language_cell

    assert queue_language_cell("xx", 0.9) == "xx"
    assert queue_language_cell("", 0.9) == ""
    assert queue_language_cell("en", True) == "English"




def test_every_whisper_language_has_a_name():
    """No bare code such as "he" or "yue" in the Language cell (review, 2026-10-21)."""
    import pytest

    from app.widgets.tabs import queue_language_cell

    tokenizer = pytest.importorskip("faster_whisper.tokenizer")
    bare = [code for code in tokenizer._LANGUAGE_CODES if queue_language_cell(code, 0.9) == code]
    assert bare == []
    assert queue_language_cell("he", 0.9) == "Hebrew"
    assert queue_language_cell("yue", 0.9) == "Cantonese"
