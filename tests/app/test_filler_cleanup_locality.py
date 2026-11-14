"""Filler cleanup only tidies punctuation at the actual removed token."""
import pytest

from app.dialogs import transcript_viewer as tv


@pytest.mark.parametrize("text,expected", [
    ("We use C#, .NET and um Java.", "We use C#, .NET and Java."),
    ("um run git commit --amend", "run git commit --amend"),
    ("Use arr [:5] um here", "Use arr [:5] here"),
    ("Sold to Acme Inc., a um big firm", "Sold to Acme Inc., a big firm"),
    ('Keep () and "" um please.', 'Keep () and "" please.'),
    ("Keep two\n\nparagraphs um here.", "Keep two\n\nparagraphs here."),
    ("Keep a   b, um then go.", "Keep a   b, then go."),
    ("Keep \ue000 literal, um then go.", "Keep \ue000 literal, then go."),
])
def test_cleanup_does_not_rewrite_unrelated_source(text, expected):
    pattern = tv._filler_regex(tv._filler_words_for("en"))
    assert tv._strip_fillers(text, pattern) == expected


@pytest.mark.parametrize("text,expected", [
    ("a um   b", "a b"), ("a um uh b", "a b"),
    ("um uh next", "next"), ("um", ""),
])
def test_cleanup_still_removes_real_fillers_and_local_spacing(text, expected):
    assert tv._strip_fillers(text, tv._filler_regex(tv._filler_words_for("en"))) == expected
