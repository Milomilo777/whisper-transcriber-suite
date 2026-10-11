"""Property-based invariants of core.text_metrics.count_words."""
import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

from core.text_metrics import count_words  # noqa: E402

_SETTINGS = settings(derandomize=True, deadline=None, database=None)


@_SETTINGS
@given(st.text())
def test_never_negative(text):
    assert count_words(text) >= 0


@_SETTINGS
@given(st.text())
def test_trailing_space_never_changes_the_count(text):
    assert count_words(text) == count_words(text + " ")


@_SETTINGS
@given(st.text(), st.text())
def test_concatenation_adds_up_within_one(text1, text2):
    # A join can merge two words, or two partial Thai/Lao/Khmer/Myanmar runs, into one.
    assert abs(count_words(text1 + text2) - (count_words(text1) + count_words(text2))) <= 1


@_SETTINGS
@given(st.text(alphabet=st.characters(min_codepoint=0, max_codepoint=127)))
def test_pure_ascii_equals_the_old_whitespace_count(text):
    assert count_words(text) == len(text.split())
