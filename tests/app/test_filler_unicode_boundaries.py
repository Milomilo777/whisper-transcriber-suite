"""Unicode punctuation and combining marks are part of adjacent real words."""
import pytest

from app.dialogs import transcript_viewer as tv


@pytest.mark.parametrize("text", [
    "Did you go? Mm\u2011hmm.", "Did you go? Mm\u2010hmm.",
    "cre\u0301er un fichier", "er\u0301 est un mot",
    "Mm\u00adhmm means yes.", "er\u093f is part of a word",
])
def test_word_boundaries_keep_unicode_word_parts(text):
    assert tv._strip_fillers(text, tv._filler_regex(tv._filler_words_for("en"))) == text


@pytest.mark.parametrize("text,expected", [
    ("hello—um—world", "hello—world"),
    ("so – um – then", "so – then"),
])
def test_delimiting_dashes_still_allow_real_filler_removal(text, expected):
    assert tv._strip_fillers(text, tv._filler_regex(tv._filler_words_for("en"))) == expected
