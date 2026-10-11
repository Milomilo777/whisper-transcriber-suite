"""Plausibility check for transcripts.

This module provides heuristics to detect incomplete transcripts (e.g., missing
tails, long gaps) by comparing the segments against the media duration and optional
voice activity detection (VAD) regions. This is a plausibility check, not a proof
of accuracy.
"""

import math
from dataclasses import dataclass
from typing import Any
from core.writers.base import coerce_seconds

# Zero-width spaces/joiners, LRM/RLM, bidi embeddings and overrides, word joiner, BOM: deleted before the
# blank-text test, so a segment holding only these marks counts as empty.
_INVISIBLE = dict.fromkeys([*range(0x200B, 0x2010), *range(0x202A, 0x202F), 0x2060, 0xFEFF])


@dataclass(frozen=True)
class Report:
    covered_s: float
    media_duration: float | None
    coverage_ratio: float | None
    gaps: list[tuple[float, float]]
    missing_tail: bool
    empty: bool
    out_of_order: int
    bad_segments: int
    verdict: str
    bad_regions: int = 0

    def summary(self) -> str:
        """Returns a one-line English summary for the log."""
        
        def format_time(seconds: float) -> str:
            if not math.isfinite(seconds) or seconds < 0:
                return "0:00"
            m, s = divmod(int(seconds), 60)
            return f"{m}:{s:02d}"

        cov_str = format_time(self.covered_s)
        dur_str = format_time(self.media_duration) if self.media_duration is not None else "unknown duration"
        
        parts = [f"Transcript covers {cov_str} of {dur_str}"]
        
        if self.empty:
            parts.append("transcript is empty")
        elif self.gaps:
            gap_count = len(self.gaps)
            s_word = "" if gap_count == 1 else "s"
            # just show the first gap as an example
            g_start = format_time(self.gaps[0][0])
            g_end = format_time(self.gaps[0][1])
            parts.append(f"{gap_count} silent-looking gap{s_word} at {g_start}-{g_end} with speech")
            
        if self.missing_tail:
            parts.append("missing tail")
            
        if self.out_of_order > 0:
            s_ooo = "" if self.out_of_order == 1 else "s"
            parts.append(f"{self.out_of_order} out-of-order segment{s_ooo}")
            
        if self.bad_segments > 0:
            s_bad = "" if self.bad_segments == 1 else "s"
            parts.append(f"{self.bad_segments} bad segment{s_bad} skipped")
            
        if self.bad_regions > 0:
            s_reg = "" if self.bad_regions == 1 else "s"
            parts.append(f"{self.bad_regions} bad speech region{s_reg} skipped")

        summary = "; ".join(parts) + f"; verdict: {self.verdict}."
        if self.verdict == "check":
            summary = summary.replace("verdict: check.", "check it.")
        
        return summary


def check_completeness(
    segments: list[dict[str, Any]],
    media_duration: float | None,
    speech_regions: list[tuple[float, float]] | None = None,
    *,
    gap_s: float = 30.0,
    tail_s: float = 20.0,
) -> Report:
    """Check the completeness of a transcript against its expected duration.
    
    This is a plausibility check, not a proof of accuracy.
    """
    bad_segments = 0
    out_of_order = 0
    empty = True
    
    valid_intervals: list[tuple[float, float]] = []
    
    last_start = -1.0
    
    for seg in segments:
        if not isinstance(seg, dict):
            bad_segments += 1
            continue

        # A dict subclass with a misbehaving .get() counts as a bad segment instead of aborting the check.
        try:
            start = seg.get("start")
            end = seg.get("end")
            text = seg.get("text")
        except (KeyError, TypeError, ValueError):
            bad_segments += 1
            continue

        # Robust validation
        if start is None or end is None:
            bad_segments += 1
            continue

        start = coerce_seconds(start, float('nan'))
        end = coerce_seconds(end, float('nan'))

        if not (math.isfinite(start) and math.isfinite(end) and start >= 0.0 and end >= 0.0 and start <= end):
            bad_segments += 1
            continue
            
        if text is None:
            bad_segments += 1
            continue
            
        # check if empty; zero-width and bidi control characters alone are not speech
        if empty and str(text).translate(_INVISIBLE).strip():
            empty = False
            
        if start < last_start:
            out_of_order += 1
        last_start = start
        
        valid_intervals.append((start, end))

    # sort intervals to compute coverage and gaps
    valid_intervals.sort()
    
    covered_s = 0.0
    gaps: list[tuple[float, float]] = []
    
    if not valid_intervals:
        try:
            media_dur_early = float(media_duration) if media_duration is not None else float('nan')
        except (TypeError, ValueError, OverflowError):
            media_dur_early = float('nan')
        valid_dur = math.isfinite(media_dur_early) and media_dur_early > 0.0
        return Report(
            covered_s=0.0,
            media_duration=media_dur_early if valid_dur else None,
            coverage_ratio=0.0 if valid_dur else None,
            gaps=[],
            missing_tail=False,
            empty=True,
            out_of_order=out_of_order,
            bad_segments=bad_segments,
            verdict="check" if valid_dur else "unknown",
            bad_regions=0
        )
        
    merged_intervals = [valid_intervals[0]]
    for current in valid_intervals[1:]:
        last = merged_intervals[-1]
        if current[0] <= last[1]:
            # Overlap
            merged_intervals[-1] = (last[0], max(last[1], current[1]))
        else:
            merged_intervals.append(current)
            
    for interval in merged_intervals:
        covered_s += interval[1] - interval[0]
        
    for i in range(len(merged_intervals) - 1):
        gap_start = merged_intervals[i][1]
        gap_end = merged_intervals[i+1][0]
        if gap_end - gap_start > gap_s:
            gaps.append((gap_start, gap_end))
            
    # Filter gaps by speech_regions
    valid_speech_regions = []
    bad_regions = 0
    if speech_regions is not None:
        for sr in speech_regions:
            if not isinstance(sr, (tuple, list)) or len(sr) != 2:
                bad_regions += 1
                continue
            sr_start, sr_end = sr[0], sr[1]
            
            # Reject bools and strings, accept int/float
            if isinstance(sr_start, bool) or isinstance(sr_end, bool) or isinstance(sr_start, str) or isinstance(sr_end, str):
                bad_regions += 1
                continue
                
            try:
                sr_start = float(sr_start)
                sr_end = float(sr_end)
            except (TypeError, ValueError, OverflowError):
                bad_regions += 1
                continue
                
            if not (math.isfinite(sr_start) and math.isfinite(sr_end) and sr_start <= sr_end):
                bad_regions += 1
                continue
                
            valid_speech_regions.append((sr_start, sr_end))
        
        valid_speech_regions.sort()
        if valid_speech_regions:
            merged_sr = [valid_speech_regions[0]]
            for current in valid_speech_regions[1:]:
                last = merged_sr[-1]
                if current[0] <= last[1]:
                    merged_sr[-1] = (last[0], max(last[1], current[1]))
                else:
                    merged_sr.append(current)
            valid_speech_regions = merged_sr

    if speech_regions is not None and gaps:
        filtered_gaps = []
        sr_idx = 0
        num_sr = len(valid_speech_regions)
        for g_start, g_end in gaps:
            gap_len = g_end - g_start
            overlap = 0.0
            
            # advance sr_idx until sr_end is strictly after g_start
            while sr_idx < num_sr and valid_speech_regions[sr_idx][1] <= g_start:
                sr_idx += 1
                
            curr_sr = sr_idx
            while curr_sr < num_sr:
                sr_start, sr_end = valid_speech_regions[curr_sr]
                if sr_start >= g_end:
                    break
                o_start = max(g_start, sr_start)
                o_end = min(g_end, sr_end)
                if o_start < o_end:
                    overlap += (o_end - o_start)
                curr_sr += 1
                
            if overlap >= 0.5 * gap_len:
                filtered_gaps.append((g_start, g_end))
        gaps = filtered_gaps

    last_segment_end = merged_intervals[-1][1]
    
    try:
        media_duration_float = float(media_duration) if media_duration is not None else float('nan')
    except (TypeError, ValueError, OverflowError):
        media_duration_float = float('nan')
    has_valid_duration = math.isfinite(media_duration_float) and media_duration_float > 0.0
    media_dur_val = media_duration_float if has_valid_duration else None

    
    # MIN_TAIL_SPEECH_S: Require at least 2.0 seconds of detected speech overlapping
    # the tail [last_segment_end, media_duration] to trigger missing_tail=True.
    missing_tail = False
    if has_valid_duration:
        assert media_dur_val is not None
        if media_dur_val - last_segment_end > tail_s:
            if speech_regions is not None:
                tail_speech_s = 0.0
                for sr_start, sr_end in valid_speech_regions:
                    o_start = max(last_segment_end, sr_start)
                    o_end = min(media_dur_val, sr_end)
                    if o_start < o_end:
                        tail_speech_s += (o_end - o_start)
                if tail_speech_s >= 2.0:
                    missing_tail = True
            else:
                missing_tail = True
                
    coverage_ratio = None
    if media_dur_val is not None:
        coverage_ratio = covered_s / media_dur_val if media_dur_val > 0.0 else 0.0
        coverage_ratio = min(1.0, max(0.0, coverage_ratio))
        
    verdict = "ok"
    if not has_valid_duration:
        verdict = "unknown"
    elif missing_tail or gaps or empty:
        verdict = "check"
        
    return Report(
        covered_s=covered_s,
        media_duration=media_dur_val,
        coverage_ratio=coverage_ratio,
        gaps=gaps,
        missing_tail=missing_tail,
        empty=empty,
        out_of_order=out_of_order,
        bad_segments=bad_segments,
        verdict=verdict,
        bad_regions=bad_regions,
    )
