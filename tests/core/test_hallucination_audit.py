from __future__ import annotations

import math


from core import hallucination as h

def test_detect_vad_disagreement_malformed_segments():
    # Prove behaviour when segments lack keys or have bad types
    # Hypothesis: Returns False and does not crash when parsing bad timestamps.
    bad_segs = [
        {"text": "foo"},  # missing start/end
        {"start": "a", "end": "b", "text": "bar"},
        {"start": None, "end": None, "text": "baz"},
        {"start": math.nan, "end": math.inf, "text": "qux"},
    ]
    vad = [(0.0, 10.0)]
    for seg in bad_segs:
        assert h.detect_vad_disagreement(seg, vad) is False

def test_detect_vad_disagreement_overlap_edge_cases():
    # Hypothesis: Exact boundary overlaps
    seg1 = {"start": 10.0, "end": 12.0} # starts right at the end of vad
    seg2 = {"start": 8.0, "end": 10.0}  # ends right at the end of vad
    vad = [(0.0, 10.0)]
    # e=12.0 >= vs=0.0 and s=10.0 <= ve=10.0 -> False (overlap)
    assert h.detect_vad_disagreement(seg1, vad) is False
    assert h.detect_vad_disagreement(seg2, vad) is False

def test_detect_repetition_repeated_word():
    text = "the " * 50
    assert h.detect_repetition(text) is True

def test_detect_boh_unicode_and_rtl():
    # Characterization: ensure Unicode/RTL are processed stably (they don't trigger anything unless matching explicitly)
    assert h.detect_boh("مرحبا بكم في القناة") is False
    assert h.detect_boh("😊😊😊") is False
