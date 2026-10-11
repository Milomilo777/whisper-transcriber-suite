import math
import sys
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.completeness import Report, check_completeness


@settings(max_examples=200, derandomize=True, deadline=None, database=None)
@given(
    segments=st.lists(
        st.fixed_dictionaries({
            "start": st.floats(min_value=0.0, max_value=3600.0),
            "end": st.floats(min_value=0.0, max_value=3600.0),
            "text": st.just("text"),
        })
    ),
    media_duration=st.floats(min_value=0.0, max_value=4000.0),
)
def test_hypothesis_coverage_ratio_bounds(segments: list[dict[str, Any]], media_duration: float) -> None:
    # coverage_ratio in [0, 1]
    report = check_completeness(segments, media_duration)
    if report.coverage_ratio is not None:
        assert 0.0 <= report.coverage_ratio <= 1.0


@settings(max_examples=200, derandomize=True, deadline=None, database=None)
@given(
    segments=st.lists(
        st.fixed_dictionaries({
            "start": st.floats(min_value=0.0, max_value=3600.0),
            "end": st.floats(min_value=0.0, max_value=3600.0),
            "text": st.just("text"),
        })
    ),
    new_segment=st.fixed_dictionaries({
        "start": st.floats(min_value=0.0, max_value=3600.0),
        "end": st.floats(min_value=0.0, max_value=3600.0),
        "text": st.just("text"),
    }),
    media_duration=st.floats(min_value=0.0, max_value=4000.0),
)
def test_hypothesis_adding_segment_never_lowers_covered_s(
    segments: list[dict[str, Any]], new_segment: dict[str, Any], media_duration: float
) -> None:
    # adding a segment never lowers covered_s
    r1 = check_completeness(segments, media_duration)
    r2 = check_completeness(segments + [new_segment], media_duration)
    assert r2.covered_s >= r1.covered_s - 1e-9


@settings(max_examples=200, derandomize=True, deadline=None, database=None)
@given(
    segments=st.lists(
        st.builds(
            lambda s, e: {"start": min(s, e), "end": max(s, e), "text": "text"},
            st.floats(min_value=0.0, max_value=3600.0),
            st.floats(min_value=0.0, max_value=3600.0),
        )
    ),
    media_duration=st.floats(min_value=1.0, max_value=4000.0),
    offset=st.floats(min_value=10.0, max_value=1000.0),
)
def test_hypothesis_shifting_preserves_gap_lengths(
    segments: list[dict[str, Any]], media_duration: float, offset: float
) -> None:
    # shifting every segment and the media by the same offset leaves gaps' lengths unchanged
    r1 = check_completeness(segments, media_duration)
    
    shifted_segments = []
    for s in segments:
        shifted = dict(s)
        shifted["start"] = s["start"] + offset
        shifted["end"] = s["end"] + offset
        shifted_segments.append(shifted)
        
    r2 = check_completeness(shifted_segments, media_duration + offset)
    
    gaps1_len = sum(e - s for s, e in r1.gaps)
    gaps2_len = sum(e - s for s, e in r2.gaps)
    assert math.isclose(gaps1_len, gaps2_len, abs_tol=1e-5)


@settings(max_examples=200, derandomize=True, deadline=None, database=None)
@given(
    duration=st.floats(min_value=1.0, max_value=3600.0),
)
def test_hypothesis_single_segment_spanning_whole_media(duration: float) -> None:
    # a single segment spanning the whole media gives verdict "ok"
    segments = [{"start": 0.0, "end": duration, "text": "test"}]
    report = check_completeness(segments, duration)
    assert report.verdict == "ok"
    assert math.isclose(report.coverage_ratio, 1.0, abs_tol=1e-5)
    assert not report.gaps
    assert not report.missing_tail
    assert not report.empty
    assert report.out_of_order == 0


def test_missing_tail() -> None:
    # a 60-min file whose transcript stops at 41 min
    # Missing tail, verdict check
    duration = 3600.0
    segments = [{"start": 0.0, "end": 2460.0, "text": "all done"}]
    report = check_completeness(segments, duration)
    assert report.missing_tail is True
    assert report.verdict == "check"


def test_long_instrumental_break() -> None:
    # a long instrumental break without speech_regions (gap reported)
    duration = 1000.0
    segments = [
        {"start": 0.0, "end": 100.0, "text": "start"},
        {"start": 500.0, "end": 1000.0, "text": "end"},
    ]
    report = check_completeness(segments, duration)
    assert len(report.gaps) == 1
    assert report.gaps[0] == (100.0, 500.0)
    assert report.verdict == "check"
    
    # and with speech_regions showing silence there (no gap reported)
    speech_regions = [(0.0, 100.0), (500.0, 1000.0)]
    report2 = check_completeness(segments, duration, speech_regions=speech_regions)
    assert len(report2.gaps) == 0
    assert report2.verdict == "ok"


def test_gap_with_speech_regions_50_percent() -> None:
    # Gap 100 to 500 (length 400).
    duration = 1000.0
    segments = [
        {"start": 0.0, "end": 100.0, "text": "start"},
        {"start": 500.0, "end": 1000.0, "text": "end"},
    ]
    # Speech region overlaps the gap by exactly 200s (50% of 400s) -> gap should count
    speech_regions = [(100.0, 300.0)]
    report = check_completeness(segments, duration, speech_regions=speech_regions)
    assert len(report.gaps) == 1
    
    # Speech region overlaps the gap by 199s (<50%) -> gap ignored
    speech_regions_less = [(100.0, 299.0)]
    report_less = check_completeness(segments, duration, speech_regions=speech_regions_less)
    assert len(report_less.gaps) == 0


def test_missing_tail_with_speech_regions() -> None:
    duration = 100.0
    segments = [{"start": 0.0, "end": 50.0, "text": "first"}]
    
    # Missing tail if no speech region given
    rep1 = check_completeness(segments, duration)
    assert rep1.missing_tail is True
    
    # Missing tail if speech region exists after the last segment
    rep2 = check_completeness(segments, duration, speech_regions=[(60.0, 80.0)])
    assert rep2.missing_tail is True
    
    # NOT missing tail if no speech region exists after the last segment
    rep3 = check_completeness(segments, duration, speech_regions=[(0.0, 50.0)])
    assert rep3.missing_tail is False


def test_unknown_duration() -> None:
    # unknown duration (verdict unknown, no crash)
    segments = [{"start": 0.0, "end": 10.0, "text": "hello"}]
    report = check_completeness(segments, 0.0)
    assert report.verdict == "unknown"
    assert report.coverage_ratio is None
    assert report.missing_tail is False
    
    report2 = check_completeness(segments, None)
    assert report2.verdict == "unknown"
    assert report2.coverage_ratio is None


def test_robust_input() -> None:
    segments = [
        {"start": float('nan'), "end": 10.0, "text": "bad start"},
        {"start": 0.0, "end": float('inf'), "text": "bad end"},
        {"start": 0.0, "end": -5.0, "text": "negative time"},
        {"start": 10.0, "end": 5.0, "text": "end < start"},
        {"start": 0.0, "end": 10.0, "text": None},
        {"start": 5.0, "end": 15.0, "text": "overlapping"},
        {"start": 2.0, "end": 8.0, "text": "unsorted"},
        "not a dict",
        None
    ]
    report = check_completeness(segments, 20.0)
    assert report.bad_segments == 7  # 4 bad times, 1 None text, 2 not-dict.
    # The valid segments remaining are:
    # {"start": 5.0, "end": 15.0, "text": "overlapping"},
    # {"start": 2.0, "end": 8.0, "text": "unsorted"}
    # Starts are [5.0, 2.0]. out_of_order is 1.
    # Covered is [2.0, 8.0] merged with [5.0, 15.0] = [2.0, 15.0]. Duration = 13.0
    assert report.out_of_order == 1
    assert math.isclose(report.covered_s, 13.0, abs_tol=1e-5)


@pytest.mark.parametrize("text", [
    "سلام", "مرحبا", "你好", "🚀"
])
def test_text_identification_valid(text: str) -> None:
    report = check_completeness([{"start": 0.0, "end": 1.0, "text": text}], 1.0)
    assert report.empty is False

@pytest.mark.parametrize("text", [
    "   ", "\n\t", " ", "　"
])
def test_text_identification_blank(text: str) -> None:
    report = check_completeness([{"start": 0.0, "end": 1.0, "text": text}], 1.0)
    assert report.empty is True


@pytest.mark.parametrize("codes", [
    (0x200B,), (0x200F, 0x20), (0x202B, 0x202C), (0xFEFF,), (0x2060, 0x200C, 0x200D),
])
def test_invisible_marks_alone_are_blank(codes: tuple[int, ...]) -> None:
    text = "".join(map(chr, codes))
    report = check_completeness([{"start": 0.0, "end": 1.0, "text": text}], 1.0)
    assert report.empty is True


def test_word_with_zero_width_non_joiner_is_speech() -> None:
    # A Persian word written with ZWNJ inside it is real text.
    text = "".join(map(chr, (0x645, 0x6CC, 0x200C, 0x631, 0x648, 0x645)))
    report = check_completeness([{"start": 0.0, "end": 1.0, "text": text}], 1.0)
    assert report.empty is False



def test_100k_segments_do_not_crash() -> None:
    segments = []
    for i in range(100000):
        segments.append({"start": i * 1.0, "end": i * 1.0 + 0.5, "text": "ok"})
    report = check_completeness(segments, 100000.0)
    assert report.verdict in ["ok", "check"]


def test_summary_format() -> None:
    report = Report(
        covered_s=3520.0,
        media_duration=3602.0,
        coverage_ratio=3520.0/3602.0,
        gaps=[(730.0, 785.0)],
        missing_tail=False,
        empty=False,
        out_of_order=0,
        bad_segments=0,
        verdict="check",
    )
    assert report.summary() == "Transcript covers 58:40 of 60:02; 1 silent-looking gap at 12:10-13:05 with speech; check it."
    
    rep2 = Report(
        covered_s=60.0,
        media_duration=None,
        coverage_ratio=None,
        gaps=[],
        missing_tail=False,
        empty=False,
        out_of_order=0,
        bad_segments=0,
        verdict="unknown",
    )
    assert rep2.summary() == "Transcript covers 1:00 of unknown duration; verdict: unknown."
    
    rep3 = Report(
        covered_s=60.0,
        media_duration=100.0,
        coverage_ratio=0.6,
        gaps=[],
        missing_tail=True,
        empty=False,
        out_of_order=0,
        bad_segments=0,
        verdict="check",
    )
    assert rep3.summary() == "Transcript covers 1:00 of 1:40; missing tail; check it."
    
    rep4 = Report(
        covered_s=60.0,
        media_duration=100.0,
        coverage_ratio=0.6,
        gaps=[(10.0, 20.0), (30.0, 50.0)],
        missing_tail=False,
        empty=False,
        out_of_order=0,
        bad_segments=0,
        verdict="check",
    )
    assert rep4.summary() == "Transcript covers 1:00 of 1:40; 2 silent-looking gaps at 0:10-0:20 with speech; check it."
    
    rep5 = Report(
        covered_s=100.0,
        media_duration=100.0,
        coverage_ratio=1.0,
        gaps=[],
        missing_tail=False,
        empty=False,
        out_of_order=2,
        bad_segments=3,
        verdict="ok",
        bad_regions=0,
    )
    assert rep5.summary() == "Transcript covers 1:40 of 1:40; 2 out-of-order segments; 3 bad segments skipped; verdict: ok."
    
    rep6 = Report(
        covered_s=100.0,
        media_duration=100.0,
        coverage_ratio=1.0,
        gaps=[],
        missing_tail=False,
        empty=False,
        out_of_order=1,
        bad_segments=1,
        verdict="ok",
        bad_regions=1,
    )
    assert rep6.summary() == "Transcript covers 1:40 of 1:40; 1 out-of-order segment; 1 bad segment skipped; 1 bad speech region skipped; verdict: ok."



def test_empty_transcript_behavior() -> None:
    # check_completeness([], 3600.0) returns verdict 'check', empty=True, missing_tail=False
    report_a = check_completeness([], 3600.0)
    assert report_a.verdict == "check"
    assert report_a.empty is True
    assert report_a.missing_tail is False
    assert "transcript is empty" in report_a.summary()
    assert report_a.summary().endswith("check it.")

    # [{'start':0,'end':3600,'text':'   '}] with media 3600 gives verdict 'check' and empty True
    report_b = check_completeness([{'start':0,'end':3600,'text':'   '}], 3600.0)
    assert report_b.verdict == "check"
    assert report_b.empty is True

    # [] with media None gives verdict 'unknown' (spec R6) and still empty True
    report_c = check_completeness([], None)
    assert report_c.verdict == "unknown"
    assert report_c.empty is True

@pytest.mark.parametrize("val", [
    10**400, -10**400, "1e999", "nan", [], {}, object(), True, "5"
])
def test_robust_start_end_values_never_raise(val) -> None:
    # Must never raise. 
    report = check_completeness([{"start": val, "end": 10.0, "text": "hello"}], 100.0)
    assert report.verdict in ["ok", "check", "unknown"]
    # numeric strings and True might be valid.
    try:
        val_f = float(val)
    except Exception:
        val_f = float('nan')
    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val_f) and val_f >= 0.0:
        assert report.bad_segments == 0
    elif val == "5":
        assert report.bad_segments == 0
    elif val is True:
        # coerce_seconds(True) gives 1.0
        assert report.bad_segments == 0
    else:
        assert report.bad_segments == 1


@pytest.mark.parametrize("val", [
    10**400, "abc", float("nan"), float("inf"), -1.0
])
def test_robust_media_duration_never_raise(val) -> None:
    report = check_completeness([{"start": 0.0, "end": 10.0, "text": "hello"}], val)
    assert report.verdict == "unknown"
    assert report.media_duration is None

def test_speech_regions_empty_list() -> None:
    duration = 1000.0
    segments = [
        {"start": 0.0, "end": 100.0, "text": "start"},
        {"start": 500.0, "end": 1000.0, "text": "end"},
    ]
    report = check_completeness(segments, duration, speech_regions=[])
    assert report.gaps == []
    assert report.verdict == "ok"
    assert report.missing_tail is False

def test_speech_regions_malformed() -> None:
    duration = 1000.0
    segments = [
        {"start": 0.0, "end": 100.0, "text": "start"},
        {"start": 500.0, "end": 1000.0, "text": "end"},
    ]
    # malformed regions skipped without raising
    speech_regions = [
        None,
        (float('nan'), 100.0),
        (50.0, float('nan')),
        (200.0, 100.0), # start > end
        (10.0, 20.0, 30.0), # 3-tuple
        "not a tuple",
        (100.0, 300.0) # valid region overlapping gap
    ]
    report = check_completeness(segments, duration, speech_regions=speech_regions) # type: ignore
    assert len(report.gaps) == 1
    assert report.gaps[0] == (100.0, 500.0)
    assert report.verdict == "check"

def test_large_number_of_gaps_and_regions_complexity() -> None:
    segments = []
    regions = []
    for i in range(20000):
        start = i * 100.0
        end = start + 60.0
        segments.append({"start": start, "end": end, "text": "speech"})
        regions.append((start + 65.0, start + 95.0))
        
    duration = 20000 * 100.0 + 100.0
    
    lines_executed = 0
    budget = 400 * 20000
    
    def trace_calls(frame, event, arg):
        nonlocal lines_executed
        if event == 'line':
            if "core/completeness.py" in frame.f_code.co_filename or "core\\completeness.py" in frame.f_code.co_filename:
                lines_executed += 1
                if lines_executed > budget:
                    raise AssertionError("Budget exceeded")
        return trace_calls

    old_trace = sys.gettrace()
    sys.settrace(trace_calls)
    try:
        check_completeness(segments, duration, speech_regions=regions)
    finally:
        sys.settrace(old_trace)
        
    assert lines_executed <= budget


def test_boundaries_and_exact_metrics() -> None:
    # out_of_order for starts [5,1,3,2] is exactly 2
    segments = [
        {"start": 5.0, "end": 6.0, "text": "t"},
        {"start": 1.0, "end": 2.0, "text": "t"}, # out of order (1 < 5)
        {"start": 3.0, "end": 4.0, "text": "t"},
        {"start": 2.0, "end": 3.5, "text": "t"}  # out of order (2 < 3)
    ]
    report = check_completeness(segments, 10.0)
    assert report.out_of_order == 2
    
    # gap of exactly gap_s is NOT reported, gap_s + 0.001 IS reported
    # gap_s defaults to 30.0.
    seg_gap_30 = [
        {"start": 0.0, "end": 10.0, "text": "t"},
        {"start": 40.0, "end": 50.0, "text": "t"}
    ]
    assert len(check_completeness(seg_gap_30, 60.0).gaps) == 0
    
    seg_gap_30_001 = [
        {"start": 0.0, "end": 10.0, "text": "t"},
        {"start": 40.002, "end": 50.0, "text": "t"} # 40.002 - 10.0 = 30.002
    ]
    assert len(check_completeness(seg_gap_30_001, 60.0).gaps) == 1
    
    # tail of exactly tail_s is NOT missing, tail_s + 0.001 is missing. tail_s=20.0
    seg_tail_20 = [{"start": 0.0, "end": 80.0, "text": "t"}]
    assert check_completeness(seg_tail_20, 100.0).missing_tail is False
    assert check_completeness(seg_tail_20, 100.002).missing_tail is True

def test_speech_regions_robustness() -> None:
    # speech_regions=[(0, 10**400), (-10**400, 5), ('1','2'), (True, 5), None] never raises;
    duration = 100.0
    segments = [{"start": 0.0, "end": 10.0, "text": "start"}]
    
    # None is valid region list element, just skipped
    sr = [(0, 10**400), (-10**400, 5), ('1','2'), (True, 5), None]
    report = check_completeness(segments, duration, speech_regions=sr) # type: ignore
    assert report.bad_regions == 5
    assert "5 bad speech regions skipped" in report.summary()

def test_speech_regions_list_form() -> None:
    # list-form regions [[500, 900]] behave exactly like tuples;
    duration = 1000.0
    segments = [
        {"start": 0.0, "end": 100.0, "text": "start"},
        {"start": 500.0, "end": 1000.0, "text": "end"},
    ]
    report = check_completeness(segments, duration, speech_regions=[[100.0, 500.0]]) # type: ignore
    assert report.bad_regions == 0
    assert len(report.gaps) == 1
    assert report.gaps[0] == (100.0, 500.0)

def test_speech_regions_singular_bad_summary() -> None:
    duration = 100.0
    segments = [{"start": 0.0, "end": 10.0, "text": "start"}]
    report = check_completeness(segments, duration, speech_regions=[None]) # type: ignore
    assert report.bad_regions == 1
    assert "1 bad speech region skipped" in report.summary()

def test_robust_input_dict_subclass_exception() -> None:
    # Prove that a dict subclass whose .get raises KeyError-free weird values still gives bad_segments
    class BadDict(dict):
        def get(self, key, default=None):
            if key == "start":
                raise ValueError("custom error")
            return super().get(key, default)
            
    segments = [
        {"start": 0.0, "end": 10.0, "text": "ok"},
        BadDict({"start": 0.0, "end": 10.0, "text": "bad"}),
    ]
    report = check_completeness(segments, 20.0) # type: ignore
    assert report.bad_segments == 1

def test_missing_tail_min_tail_speech_overlap() -> None:
    # check_completeness([{'start':0,'end':100,'text':'a'}], 3600, speech_regions=[(0, 100.4)])
    # returns missing_tail=False, verdict 'ok'
    report1 = check_completeness([{"start":0, "end":100, "text":"a"}], 3600, speech_regions=[(0, 100.4)])
    assert report1.missing_tail is False
    
    # regions [(0, 100.4), (3000, 3001)] (1 s of speech after) also False
    report2 = check_completeness([{"start":0, "end":100, "text":"a"}], 3600, speech_regions=[(0, 100.4), (3000, 3001)])
    assert report2.missing_tail is False

    # [(0,100.4),(3000,3003)] (3 s after) True
    report3 = check_completeness([{"start":0, "end":100, "text":"a"}], 3600, speech_regions=[(0, 100.4), (3000, 3003)])
    assert report3.missing_tail is True
