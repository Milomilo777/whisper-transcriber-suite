"""Contained tail capping preserves ordered decoded words and raw evidence."""
from copy import deepcopy

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

from core import transcriber as tr  # noqa: E402


@settings(max_examples=50, database=None, derandomize=True, deadline=None)
@given(
    eof_samples=st.integers(min_value=1, max_value=160000),
    tails=st.lists(st.tuples(st.integers(1, 16000), st.integers(1, 16000)), min_size=2, max_size=6),
)
def test_multiple_contained_tail_words_keep_identity_order_and_bounded_clocks(eof_samples, tails):
    eof = eof_samples / 16000
    words = [{'start': 0.0, 'end': eof / 2, 'word': 'head', 'probability': 0.9}]
    cursor = eof
    for index, (gap, duration) in enumerate(tails):
        start = cursor + gap / 16000
        cursor = start + duration / 16000
        words.append({'start': start, 'end': cursor, 'word': f' tail{index}', 'probability': 0.9})
    segment = {'start': 0.0, 'end': cursor, 'text': ''.join(word['word'] for word in words), 'words': words}
    original = deepcopy(segment)
    bounded = tr._cap_segment(segment, eof)
    assert segment == original
    assert 0 <= bounded['start'] <= bounded['end'] == eof
    assert bounded['text'] == original['text']
    assert len(bounded['words']) == len(original['words'])
    assert [word['word'] for word in bounded['words']] == [word['word'] for word in original['words']]
    assert [word['probability'] for word in bounded['words']] == [word['probability'] for word in original['words']]
    assert bounded['words'][0] == original['words'][0]
    assert all(0 <= word['start'] <= word['end'] <= eof for word in bounded['words'])
    assert all(word['start'] == word['end'] == eof for word in bounded['words'][1:])
    assert tr._cap_segment(bounded, eof) == bounded
