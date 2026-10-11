import math
import unicodedata

import pytest
from hypothesis import given, settings, strategies as st
from copy import deepcopy

from core.segment_ops import SegmentOpError, shift, linear_sync


def test_segment_op_error():
    assert issubclass(SegmentOpError, ValueError)

@settings(derandomize=True, deadline=None, database=None)
@given(
    start=st.floats(min_value=0.0, max_value=1e5),
    dur=st.floats(min_value=0.1, max_value=1e5),
    shift_val=st.floats(min_value=-1e5, max_value=1e5)
)
def test_shift_invariants(start, dur, shift_val):
    end = start + dur
    segments = [{"start": start, "end": end, "text": "foo"}]

    if start + shift_val < 0:
        with pytest.raises(SegmentOpError):
            shift(segments, shift_val)
        return

    res = shift(segments, shift_val)
    assert res is not segments
    assert res[0] is not segments[0]

    # +x then -x returns original
    res2 = shift(res, -shift_val)
    assert math.isclose(res2[0]["start"], start, abs_tol=1e-9)
    assert math.isclose(res2[0]["end"], end, abs_tol=1e-9)

def test_shift_words():
    segments = [{
        "start": 10.0,
        "end": 20.0,
        "text": "hello world",
        "words": [
            {"start": 10.0, "end": 15.0, "word": "hello", "probability": 1.0},
            {"start": 15.0, "end": 20.0, "word": "world", "probability": 0.9}
        ]
    }]
    res = shift(segments, 5.0)
    assert res[0]["start"] == 15.0
    assert res[0]["end"] == 25.0
    assert res[0]["words"][0]["start"] == 15.0
    assert res[0]["words"][0]["end"] == 20.0
    assert res[0]["words"][1]["start"] == 20.0
    assert res[0]["words"][1]["end"] == 25.0
    # Original unchanged
    assert segments[0]["start"] == 10.0

@settings(derandomize=True, deadline=None, database=None)
@given(
    start=st.floats(min_value=0.0, max_value=1e5),
    dur=st.floats(min_value=0.1, max_value=1e5)
)
def test_linear_sync_identity(start, dur):
    end = start + dur
    segments = [{"start": start, "end": end, "text": "foo"}]
    res = linear_sync(segments, (0.0, 0.0), (1.0, 1.0))
    assert math.isclose(res[0]["start"], start, abs_tol=1e-9)
    assert math.isclose(res[0]["end"], end, abs_tol=1e-9)


from core.segment_ops import merge_with_next, split_at, delete, set_text, set_times, History

def test_merge_with_next():
    segments = [
        {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "Speaker 1"},
        {"start": 2.5, "end": 3.0, "text": "world", "speaker": "Speaker 1"}
    ]
    res = merge_with_next(segments, 0)
    assert len(res) == 1
    assert res[0]["text"] == "hello world"
    assert res[0]["start"] == 1.0
    assert res[0]["end"] == 3.0
    assert res[0]["speaker"] == "Speaker 1"

def test_merge_cjk_no_space():
    # Ends with Han, starts with Han
    segments = [
        {"start": 0.0, "end": 1.0, "text": "你好"},
        {"start": 1.0, "end": 2.0, "text": "世界"}
    ]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == "你好世界"

def test_merge_speaker_mismatch():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": "A"},
        {"start": 1.0, "end": 2.0, "text": "b", "speaker": "B"}
    ]
    with pytest.raises(SegmentOpError):
        merge_with_next(segments, 0)

def test_split_at():
    segments = [{"start": 0.0, "end": 10.0, "text": "hello world"}]
    res = split_at(segments, 0, 5) # Split after 'hello'
    assert len(res) == 2
    assert res[0]["text"] == "hello"
    assert res[1]["text"] == "world"

def test_delete():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 1.0, "end": 2.0, "text": "b"}]
    res = delete(segments, 0)
    assert len(res) == 1
    assert res[0]["text"] == "b"

def test_set_text():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    res = set_text(segments, 0, " b ")
    assert res[0]["text"] == " b" # stripped trailing only

def test_set_times():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    res = set_times(segments, 0, 1.0, 2.0)
    assert res[0]["start"] == 1.0
    assert res[0]["end"] == 2.0

    with pytest.raises(SegmentOpError):
        set_times(segments, 0, -1.0, 2.0)

    with pytest.raises(SegmentOpError):
        set_times(segments, 0, 1.0, 0.5)

def test_history():
    initial = [{"start": 0.0, "end": 1.0, "text": "initial"}]
    h = History(initial, capacity=2)

    assert not h.can_undo
    assert not h.can_redo

    state1 = set_text(initial, 0, "state1")
    h.push(state1, "edit 1")

    assert h.can_undo
    assert h.undo_label == "edit 1"

    state2 = set_text(state1, 0, "state2")
    h.push(state2, "edit 2")


    # Test undo
    u1 = h.undo()
    assert u1[0]["text"] == "state1"
    assert h.can_redo
    assert h.redo_label == "edit 2"

    # capacity=2 keeps the initial state reachable
    assert h.undo()[0]["text"] == "initial"


@settings(derandomize=True, deadline=None, database=None)
@given(
    text=st.text(min_size=2)
)
def test_split_merge_identity(text):
    # Only test if it doesn't just strip away to nothing
    # because split requires both parts non-empty after stripping
    s = text.strip()
    if len(s) < 2:
        return

    segments = [{"start": 0.0, "end": 10.0, "text": text}]

    # Try splitting at index 1
    # We must ensure we split at a valid char_offset (1 <= offset < len(text))
    # and that both stripped parts are non-empty.
    # We'll just find a valid split point if it exists
    valid_split = None
    for i in range(1, len(text)):
        left = text[:i].strip()
        right = text[i:].strip()
        # never cut before a combining mark: split_at refuses to split a grapheme
        if left and right and unicodedata.combining(text[i]) == 0:
            valid_split = i
            break

    if valid_split is None:
        return

    res_split = split_at(segments, 0, valid_split)
    res_merge = merge_with_next(res_split, 0)

    # check that text matches normalized
    assert "".join(res_merge[0]["text"].split()) == "".join(text.split())
    assert res_merge[0]["start"] == 0.0
    assert res_merge[0]["end"] == 10.0

def test_split_proportional_time():
    segments = [{"start": 0.0, "end": 10.0, "text": "ab cd"}]
    res = split_at(segments, 0, 2)
    # len stripped left = 2 ("ab"), right = 2 ("cd"). Total = 4
    # so split time should be exactly in the middle = 5.0
    assert res[0]["text"] == "ab"
    assert res[0]["end"] == 5.0
    assert res[1]["text"] == "cd"
    assert res[1]["start"] == 5.0


def test_history_capacity():
    initial = [{"start": 0.0, "end": 1.0, "text": "initial"}]
    h = History(initial, capacity=2)
    h.push([{"start": 0.0, "end": 1.0, "text": "1"}], "1")
    h.push([{"start": 0.0, "end": 1.0, "text": "2"}], "2")
    h.push([{"start": 0.0, "end": 1.0, "text": "3"}], "3")

    # After 3 pushes on capacity=2, we have: "2", "3" in undo stack + initial?
    # Spec: "at capacity the oldest state is dropped."
    # States: initial -> push 1 -> push 2 -> push 3
    # With capacity 2, we can undo TWICE.
    # So we should be able to undo to "2" and then "1".
    assert h.undo_label == "3"
    u1 = h.undo()
    assert u1[0]["text"] == "2"

    assert h.undo_label == "2"
    assert h.undo()[0]["text"] == "1"

    assert h.can_undo is False
    with pytest.raises(SegmentOpError):
        h.undo()

@settings(derandomize=True, deadline=None, database=None)
@given(
    start=st.floats(min_value=0.0, max_value=1e5),
    dur=st.floats(min_value=0.1, max_value=1e5)
)
def test_history_exact_match(start, dur):
    initial = [{"start": start, "end": start+dur, "text": "foo"}]
    h = History(initial)

    state1 = set_text(initial, 0, "bar")
    h.push(state1, "edit")

    res_undo = h.undo()
    assert res_undo == initial

    res_redo = h.redo()
    assert res_redo == state1


def test_split_at_no_words():
    segments = [{"start": 0.0, "end": 10.0, "text": "hello world", "speaker": "Speaker 1", "suspect": True}]
    res = split_at(segments, 0, 5)
    assert len(res) == 2
    assert res[0]["text"] == "hello"
    assert res[1]["text"] == "world"
    assert res[0]["speaker"] == "Speaker 1"
    assert res[1]["speaker"] == "Speaker 1"
    assert res[0]["suspect"] is True
    assert res[1]["suspect"] is True

def test_merge_suspect():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello", "suspect": False},
        {"start": 1.0, "end": 2.0, "text": "world", "suspect": True, "suspect_reason": "low confidence"}
    ]
    res = merge_with_next(segments, 0)
    assert res[0]["suspect"] is True
    assert res[0]["suspect_reason"] == "low confidence"

    segments2 = [
        {"start": 0.0, "end": 1.0, "text": "hello", "suspect": True, "suspect_reason": "l1"},
        {"start": 1.0, "end": 2.0, "text": "world", "suspect": False}
    ]
    res2 = merge_with_next(segments2, 0)
    assert res2[0]["suspect"] is True
    assert res2[0]["suspect_reason"] == "l1"

    segments3 = [
        {"start": 0.0, "end": 1.0, "text": "hello", "suspect": False},
        {"start": 1.0, "end": 2.0, "text": "world", "suspect": False}
    ]
    res3 = merge_with_next(segments3, 0)
    assert res3[0]["suspect"] is False
    assert "suspect_reason" not in res3[0]

    segments4 = [
        {"start": 0.0, "end": 1.0, "text": "hello"},
        {"start": 1.0, "end": 2.0, "text": "world", "suspect": True}
    ]
    res4 = merge_with_next(segments4, 0)
    assert res4[0]["suspect"] is True

    segments5 = [
        {"start": 0.0, "end": 1.0, "text": "hello", "suspect": True, "suspect_reason": "a"},
        {"start": 1.0, "end": 2.0, "text": "world", "suspect": True, "suspect_reason": "b"}
    ]
    res5 = merge_with_next(segments5, 0)
    assert res5[0]["suspect"] is True
    assert res5[0]["suspect_reason"] == "a"

def test_set_times_invalid():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        set_times(segments, 0, float('nan'), 2.0)

def test_shift_invalid():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        shift(segments, float('inf'))

def test_split_persian_zwnj():
    segments = [{"start": 0.0, "end": 1.0, "text": "می‌روم"}]
    # ZWNJ is \u200C
    # "می‌روم" length is 6 characters: م ی \u200c ر و م
    assert "\u200c" in segments[0]["text"]
    res = split_at(segments, 0, 3) # Split after ZWNJ
    assert len(res) == 2
    assert res[0]["text"] == "می‌"
    assert res[1]["text"] == "روم"

def test_merge_arabic_cjk():
    # Arabic to Arabic doesn't trigger no-space CJK rule, but CJK to CJK does
    segments = [{"start": 0.0, "end": 1.0, "text": "مرحبا"}, {"start": 1.0, "end": 2.0, "text": "بكم"}]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == "مرحبا بكم"


def test_linear_sync_scale():
    segments = [{"start": 1.0, "end": 2.0, "text": "foo"}]
    res = linear_sync(segments, (0.0, 0.0), (1.0, 2.0)) # scale = 2.0
    assert res[0]["start"] == 2.0
    assert res[0]["end"] == 4.0

def test_merge_start_end():
    segments = [{"start": 2.0, "end": 3.0, "text": "a"}, {"start": 1.0, "end": 4.0, "text": "b"}]
    res = merge_with_next(segments, 0)
    assert res[0]["start"] == 1.0
    assert res[0]["end"] == 4.0

def test_split_bounds():
    segments = [{"start": 0.0, "end": 1.0, "text": "ab"}]
    with pytest.raises(SegmentOpError):
        split_at(segments, 0, 0)
    with pytest.raises(SegmentOpError):
        split_at(segments, 0, 2)

def test_history_deepcopy():
    initial = [{"start": 0.0, "end": 1.0, "text": "foo"}]
    h = History(initial)
    s1 = [{"start": 0.0, "end": 1.0, "text": "bar"}]
    h.push(s1, "edit")

    # modify s1 directly
    s1[0]["text"] = "mutated"

    res = h.undo()
    res2 = h.redo()
    assert res2[0]["text"] == "bar"


@settings(derandomize=True, deadline=None, database=None)
@given(
    shift_val=st.floats(min_value=0.0, max_value=1e5)
)
def test_sorting_invariant(shift_val):
    segments = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.0, "end": 2.0, "text": "b"},
        {"start": 2.0, "end": 3.0, "text": "c"}
    ]

    # whole list shift
    res = shift(segments, shift_val)
    assert res[0]["start"] <= res[1]["start"] <= res[2]["start"]

    # linear_sync
    res2 = linear_sync(segments, (0.0, 1.0), (1.0, 3.0))
    assert res2[0]["start"] <= res2[1]["start"] <= res2[2]["start"]

    # merge
    res3 = merge_with_next(segments, 0)
    assert res3[0]["start"] <= res3[1]["start"]

    # split
    res4 = split_at([{"start": 0.0, "end": 1.0, "text": "ab"}], 0, 1)
    assert res4[0]["start"] <= res4[1]["start"]

def test_set_times_does_not_resort():
    # test that set_times and sub-range shift can reorder
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 1.0, "end": 2.0, "text": "b"}]
    res = set_times(segments, 0, 3.0, 4.0)
    assert res[0]["start"] > res[1]["start"] # does not re-sort; caller decides

    res2 = shift(segments, 5.0, start_index=0, end_index=1)
    assert res2[0]["start"] > res2[1]["start"]


def test_split_word_gap():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "hello world",
        "words": [
            {"start": 1.0, "end": 2.0, "word": "hello"},
            {"start": 3.0, "end": 4.0, "word": "world"}
        ]
    }]
    # Split after 'hello'
    res = split_at(segments, 0, 5)
    assert res[0]["text"] == "hello"
    assert res[0]["end"] == 2.0
    assert res[1]["text"] == "world"
    assert res[1]["start"] == 3.0


def test_split_words_proportional():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "ab cd ef",
        "words": [
            {"start": 1.0, "end": 4.0, "word": "ab"},
            {"start": 8.0, "end": 9.0, "word": "ef"}
        ]
    }]
    # Words do not cover the text ("ab" and "ef" don't match "abcdef")
    # Split at char offset 3 ("ab |cd ef") -> lengths of stripped parts: "ab" (2), "cd ef" (5)
    # Ratio = 2 / 7
    # Time split = 0.0 + 10.0 * (2/7)
    # Left words: mid < 3.333 -> "ab" (mid 2.5) -> left
    # Right words: "ef" (mid 8.5) -> right
    res = split_at(segments, 0, 3)
    assert math.isclose(res[0]["end"], 10.0 * 2 / 7, abs_tol=1e-5)
    assert len(res[0]["words"]) == 1
    assert res[0]["words"][0]["word"] == "ab"
    assert len(res[1]["words"]) == 1
    assert res[1]["words"][0]["word"] == "ef"


def test_merge_emoji():
    # Emoji should not trigger CJK no-space rule
    segments = [{"start": 0.0, "end": 1.0, "text": "Hello 😃"}, {"start": 1.0, "end": 2.0, "text": "World"}]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == "Hello 😃 World"

def test_merge_none_text():
    segments = [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == ""

def test_split_none_text():
    segments = [{"start": 0.0, "end": 1.0}]
    with pytest.raises(SegmentOpError):
        split_at(segments, 0, 1)

def test_split_combining_marks():
    text = "é" # length 2
    segments = [{"start": 0.0, "end": 1.0, "text": text}]
    with pytest.raises(SegmentOpError):
        split_at(segments, 0, 1)

def test_delete_out_of_bounds():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        delete(segments, 1)
    with pytest.raises(SegmentOpError):
        delete(segments, -1)

def test_set_text_out_of_bounds():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        set_text(segments, 1, "b")
    with pytest.raises(SegmentOpError):
        set_text(segments, -1, "b")

def test_merge_out_of_bounds():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        merge_with_next(segments, 0) # last segment
    with pytest.raises(SegmentOpError):
        merge_with_next(segments, -1)


def test_split_empty_words():
    segments = [{"start": 0.0, "end": 10.0, "text": "hello world", "words": []}]
    res = split_at(segments, 0, 5)
    assert res[0]["words"] == []
    assert res[1]["words"] == []

    segments2 = [{"start": 0.0, "end": 10.0, "text": "hello world"}]
    res2 = split_at(segments2, 0, 5)
    assert "words" not in res2[0]
    assert "words" not in res2[1]

def test_split_inside_word():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "hello world",
        "words": [
            {"start": 1.0, "end": 4.0, "word": "hello"},
            {"start": 6.0, "end": 9.0, "word": "world"}
        ]
    }]
    # Split inside "hello" (char offset 2)
    # The left part text is "he", right part is "llo world"
    # Should fall back to proportional time and not yield zero-length segment.
    # Words should be distributed by midpoint against the new boundary time.
    res = split_at(segments, 0, 2)
    assert res[0]["start"] < res[0]["end"]
    assert res[1]["start"] < res[1]["end"]

    # Assert no words lost
    assert len(res[0].get("words", [])) + len(res[1].get("words", [])) == 2
    assert res[0].get("words", []) + res[1].get("words", []) == segments[0]["words"]

def test_none_text():
    segments = [{"start": 0.0, "end": 1.0, "text": None}, {"start": 1.0, "end": 2.0, "text": None}]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == ""

    with pytest.raises(SegmentOpError):
        split_at([{"start": 0.0, "end": 1.0, "text": None}], 0, 1)

def test_no_aliasing_deep_copy():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "ab cd",
        "words": [
            {"start": 1.0, "end": 4.0, "word": "ab"},
            {"start": 6.0, "end": 9.0, "word": "cd"}
        ],
        "speaker": "A",
        "suspect": False
    }, {
        "start": 10.0,
        "end": 20.0,
        "text": "ef",
        "words": [
            {"start": 11.0, "end": 14.0, "word": "ef"}
        ]
    }]
    import copy

    orig = copy.deepcopy(segments)

    # Run all ops
    s1 = shift(segments, 1.0)
    s2 = linear_sync(segments, (0.0, 0.0), (1.0, 2.0))
    s3 = merge_with_next(segments, 0)
    s4 = split_at(segments, 0, 2)
    s5 = delete(segments, 0)
    s6 = set_text(segments, 0, "foo")
    s7 = set_times(segments, 0, 0.0, 5.0)

    # History test
    h = History(segments)
    h.push(s1, "s1")
    u1 = h.undo()
    u2 = h.redo()

    # Mutate all results deeply
    for r in [s1, s2, s3, s4, s5, s6, s7, u1, u2]:
        for seg in r:
            seg["start"] = 999.0
            seg["text"] = "mutated"
            if "words" in seg:
                seg["words"][0]["start"] = 999.0
                seg["words"].append({"start": 0, "end": 0, "word": "bad"})

    # Assert input segments were never mutated
    assert segments == orig


def test_split_inside_last_word():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "ab cd",
        "words": [
            {"start": 1.0, "end": 4.0, "word": "ab"},
            {"start": 6.0, "end": 9.0, "word": "cd"}
        ]
    }]
    # Inside 'cd'
    res = split_at(segments, 0, 4)
    assert res[0]["start"] < res[0]["end"]
    assert res[1]["start"] < res[1]["end"]
    assert len(res[0]["words"]) + len(res[1]["words"]) == 2

def test_split_inside_middle_word():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "ab cd ef",
        "words": [
            {"start": 1.0, "end": 3.0, "word": "ab"},
            {"start": 4.0, "end": 6.0, "word": "cd"},
            {"start": 7.0, "end": 9.0, "word": "ef"}
        ]
    }]
    # Inside 'cd'
    res = split_at(segments, 0, 4)
    assert res[0]["start"] < res[0]["end"]
    assert res[1]["start"] < res[1]["end"]
    assert len(res[0]["words"]) + len(res[1]["words"]) == 3


def test_history_independent():
    initial = [{"start": 0.0, "end": 1.0, "text": "initial"}]
    h = History(initial)
    s1 = set_text(initial, 0, "edit 1")
    h.push(s1, "label 1")

    # undo returns a copy
    res_undo = h.undo()
    res_undo[0]["text"] = "mutated"

    # redo returns a copy
    res_redo = h.redo()
    res_redo[0]["text"] = "mutated 2"

    # undo again
    res_undo2 = h.undo()
    assert res_undo2[0]["text"] == "initial" # Stored state not affected by mutation


def test_split_identity_with_words():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "hello world",
        "words": [
            {"start": 1.0, "end": 4.0, "word": "hello"},
            {"start": 6.0, "end": 9.0, "word": "world"}
        ]
    }]
    res_split = split_at(segments, 0, 5) # Split after 'hello'
    res_merge = merge_with_next(res_split, 0)

    assert res_merge[0]["text"] == "hello world"
    assert res_merge[0]["start"] == 0.0
    assert res_merge[0]["end"] == 10.0
    assert res_merge[0]["words"] == segments[0]["words"]
    assert res_merge[0]["words"][0]["word"] == "hello"
    assert res_merge[0]["words"][1]["word"] == "world"


@settings(derandomize=True, deadline=None, database=None)
@given(
    text=st.text(min_size=2)
)
def test_split_merge_identity_with_words(text):
    s = text.strip()
    if len(s) < 2:
        return

    valid_split = None
    for i in range(1, len(text)):
        if text[:i].strip() and text[i:].strip() and unicodedata.combining(text[i]) == 0:
            valid_split = i
            break

    if valid_split is None:
        return

    # Generate covering words
    left_part = text[:valid_split].strip()
    right_part = text[valid_split:].strip()

    words = [
        {"start": 1.0, "end": 2.0, "word": left_part},
        {"start": 3.0, "end": 4.0, "word": right_part}
    ]

    segments = [{"start": 0.0, "end": 10.0, "text": text, "words": words}]

    res_split = split_at(segments, 0, valid_split)
    res_merge = merge_with_next(res_split, 0)

    assert "".join(res_merge[0]["text"].split()) == "".join(text.split())
    assert res_merge[0]["start"] == 0.0
    assert res_merge[0]["end"] == 10.0
    assert res_merge[0]["words"] == segments[0]["words"]


def test_split_inside_word_zero_length():
    segments = [{
        "start": 0.0,
        "end": 10.0,
        "text": "hello world",
        "words": [
            {"start": 0.0, "end": 4.0, "word": "hello"},
            {"start": 6.0, "end": 9.0, "word": "world"}
        ]
    }]
    res = split_at(segments, 0, 2)
    assert res[0]["start"] < res[0]["end"]
    assert res[1]["start"] < res[1]["end"]

