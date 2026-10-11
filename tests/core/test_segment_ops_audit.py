import pytest
from core.segment_ops import History, SegmentOpError, linear_sync, merge_with_next, set_text, shift, split_at

def test_audit_persian_zwnj():
    # ZWNJ = \u200c
    text = "می‌روم" # "می" + ZWNJ + "روم"
    segments = [{"start": 0.0, "end": 2.0, "text": text}]
    # split at index 2 (after "می")
    # char_offset = 2 is ZWNJ
    res = split_at(segments, 0, 2)
    assert res[0]["text"] == "می"
    assert res[1]["text"] == "‌روم" # right part starts with ZWNJ

def test_audit_arabic():
    text = "مرحبا بكم"
    segments = [{"start": 0.0, "end": 2.0, "text": text}]
    res = split_at(segments, 0, 5) # split at space
    assert res[0]["text"] == "مرحبا"
    assert res[1]["text"] == "بكم"

def test_audit_cjk_merge():
    segments = [{"start": 0.0, "end": 1.0, "text": "你好"}, {"start": 1.0, "end": 2.0, "text": "世界"}]
    res = merge_with_next(segments, 0)
    assert res[0]["text"] == "你好世界"

def test_audit_shift_invariants():
    segments = [{"start": 0.0, "end": 1.0, "text": "a", "words": [{"start": 0.0, "end": 1.0, "word": "a"}]}]
    with pytest.raises(SegmentOpError):
        shift(segments, float("inf"))
    with pytest.raises(SegmentOpError):
        shift(segments, float("nan"))
    with pytest.raises(SegmentOpError):
        shift(segments, -2.0)

def test_audit_capacity_eviction():
    initial = [{"start": 0.0, "end": 1.0, "text": "initial"}]
    h = History(initial, capacity=2)
    s1 = set_text(initial, 0, "edit 1")
    h.push(s1, "label 1")
    s2 = set_text(s1, 0, "edit 2")
    h.push(s2, "label 2")
    s3 = set_text(s2, 0, "edit 3")
    h.push(s3, "label 3")

    u1 = h.undo()
    assert u1[0]["text"] == "edit 2"
    u2 = h.undo()
    assert u2[0]["text"] == "edit 1"
    with pytest.raises(SegmentOpError):
        h.undo()

def test_audit_linear_sync():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        linear_sync(segments, (0, 0), (1, float("inf")))
    with pytest.raises(SegmentOpError):
        linear_sync(segments, (0, 0), (1, float("-inf")))
    with pytest.raises(SegmentOpError):
        linear_sync(segments, (0, 0), (0, 1)) # scale is +inf

    with pytest.raises(SegmentOpError): # old_a == old_b
        linear_sync(segments, (0, 0), (0, 0))

def test_audit_linear_sync_negative():
    segments = [{"start": 1.0, "end": 2.0, "text": "a"}]
    with pytest.raises(SegmentOpError):
        linear_sync(segments, (1.0, -1.0), (2.0, 0.0))

def test_audit_split_combining_marks():
    text = "e\u0301"
    segments = [{"start": 0.0, "end": 1.0, "text": text}]
    with pytest.raises(SegmentOpError, match="Cannot split before a combining mark"):
        split_at(segments, 0, 1)

def test_audit_split_space_only():
    segments = [{"start": 0.0, "end": 1.0, "text": "a   b"}]
    res = split_at(segments, 0, 2)
    assert res[0]["text"] == "a"
    assert res[1]["text"] == "b"

def test_audit_shift_subrange():
    segments = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 1.0, "end": 2.0, "text": "b"}]
    res = shift(segments, 5.0, start_index=0, end_index=1)

    assert res[0]["start"] == 5.0
    assert res[1]["start"] == 1.0
    assert res[0]["start"] > res[1]["start"]
