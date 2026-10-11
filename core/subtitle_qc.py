"""Subtitle quality checks.

Pure functions for light subtitle QC, without I/O.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from core.writers.base import coerce_seconds


@dataclass(frozen=True)
class QcLimits:
    """Quality control limits for subtitles.

    These are common broadcast/streaming style-guide values, adjustable by the caller.
    """
    max_cps: float = 20.0
    max_line_chars: int = 42
    max_lines: int = 2
    min_duration: float = 0.833
    max_duration: float = 7.0
    min_gap: float = 0.083


def limits_for_language(language: str | None) -> QcLimits:
    """Returns QcLimits appropriate for the given language.

    For CJK scripts (zh, ja, ko and variants), uses conservative defaults
    (max_line_chars=16, max_cps=9.0) documented as such, not attributed
    to any specific style guide.
    """
    if language:
        base_lang = language.lower().replace('_', '-').split('-')[0]
        if base_lang in ('zh', 'ja', 'ko', 'yue'):
            return QcLimits(max_cps=9.0, max_line_chars=16)
    return QcLimits()


_INVISIBLE_CHARS = frozenset({
    '\u200B', '\u200C', '\u200D', '\u200E', '\u200F',
    '\u202A', '\u202B', '\u202C', '\u202D', '\u202E',
    '\u2066', '\u2067', '\u2068', '\u2069', '\uFEFF'
})


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF) or \
           (0x3040 <= cp <= 0x309F) or \
           (0x30A0 <= cp <= 0x30FF) or \
           (0xAC00 <= cp <= 0xD7AF) or \
           (0x3400 <= cp <= 0x4DBF) or \
           (0x20000 <= cp <= 0x2A6DF)


def visible_length(text: str) -> int:
    """Returns the visible length of a string.

    Normalizes to NFC. Excludes newlines, specific zero-width/bidi control characters,
    and combining marks. Every other character counts as 1.
    """
    text_nfc = unicodedata.normalize('NFC', text)
    length = 0
    for ch in text_nfc:
        if ch in ('\n', '\r'):
            continue
        if ch in _INVISIBLE_CHARS:
            continue
        # Unicode category Mn (Mark, Nonspacing), Me (Mark, Enclosing), Mc (Mark, Spacing Combining)
        # Spec says: do not count combining marks (unicodedata.combining(ch) != 0)
        if unicodedata.combining(ch) != 0:
            continue
        length += 1
    return length


@dataclass(frozen=True)
class QcIssue:
    index: int
    code: str
    severity: str
    message: str
    value: float | None
    limit: float | None


def suggest_line_break(text: str, max_line_chars: int, max_lines: int = 2) -> list[str] | None:
    """Suggests breaking a single line into two lines."""
    if max_lines < 2:
        return None

    full_len = visible_length(text)
    if full_len <= max_line_chars:
        return None

    has_space = " " in text
    max_possible = max_line_chars * 2 + (1 if has_space else 0)
    if full_len > max_possible:
        return None

    splits = []
    for i in range(1, len(text)):
        if text[i] == ' ':
            splits.append((i, True))
        elif unicodedata.combining(text[i]) == 0:
            # split before a CJK base char whose previous base char (skipping combining marks) is also CJK
            prev_base = i - 1
            while prev_base >= 0 and unicodedata.combining(text[prev_base]) != 0:
                prev_base -= 1

            if prev_base >= 0 and _is_cjk(text[prev_base]) and _is_cjk(text[i]):
                splits.append((i, False))

    if not splits:
        return None

    prev = 0
    chunk_lens = []
    for i, is_space in splits:
        chunk_lens.append(visible_length(text[prev:i]))
        prev = i
    chunk_lens.append(visible_length(text[prev:]))

    best_break = None
    best_len_l = float('inf')
    min_diff = float('inf')

    len_l = 0
    for idx, (i, is_space) in enumerate(splits):
        len_l += chunk_lens[idx]
        len_r = full_len - len_l - (1 if is_space else 0)

        if len_l <= max_line_chars and len_r <= max_line_chars:
            diff = abs(len_l - len_r)
            if diff < min_diff or (diff == min_diff and len_l < best_len_l):
                min_diff = diff
                best_len_l = len_l
                left_str = text[:i]
                right_str = text[i+1:] if is_space else text[i:]
                best_break = [left_str, right_str]

    return best_break


def _normalize_text_for_repeated(text: str) -> str:
    nfc = unicodedata.normalize('NFC', text).casefold()
    res = []
    for ch in nfc:
        cat = unicodedata.category(ch)
        if not (cat.startswith('P') or cat.startswith('Z')):
            res.append(ch)
    return "".join(res)


def check_segments(segments: list[dict], limits: QcLimits | None = None, language: str | None = None) -> list[QcIssue]:
    """Checks segments for quality issues.

    Segments must be a list of dicts. Non-dict segments will raise TypeError or AttributeError.
    """
    if limits is None:
        limits = limits_for_language(language)

    issues: list[QcIssue] = []
    prev_valid_start = None
    prev_valid_end = None
    prev_norm_text = None

    for i, seg in enumerate(segments):
        start = coerce_seconds(seg.get('start'), math.nan)
        end = coerce_seconds(seg.get('end'), math.nan)
        text = seg.get('text', "")
        if text is None:
            text = ""
        elif not isinstance(text, str):
            text = str(text)

        if not (math.isfinite(start) and math.isfinite(end) and start >= 0 and end >= 0):
            issues.append(QcIssue(
                index=i, code='bad_timing', severity='error',
                message='Segment timing is missing, negative, or invalid.',
                value=None, limit=None
            ))
            # skip other timing checks
        else:
            duration = end - start
            if duration <= 0:
                issues.append(QcIssue(
                    index=i, code='non_positive_duration', severity='error',
                    message=f'Duration is non-positive: {duration:.3f}s.',
                    value=duration, limit=0.0
                ))
            else:
                vis_len = visible_length(text)
                cps = vis_len / duration
                if cps > limits.max_cps:
                    issues.append(QcIssue(
                        index=i, code='reading_speed', severity='warning',
                        message=f'Reading speed {cps:.1f} characters per second (limit {limits.max_cps}).',
                        value=cps, limit=limits.max_cps
                    ))
                if duration > 0 and duration < limits.min_duration:
                    issues.append(QcIssue(
                        index=i, code='too_short', severity='warning',
                        message=f'Duration {duration:.3f}s is too short (minimum {limits.min_duration}s).',
                        value=duration, limit=limits.min_duration
                    ))
                elif duration > limits.max_duration:
                    issues.append(QcIssue(
                        index=i, code='too_long', severity='warning',
                        message=f'Duration {duration:.3f}s is too long (maximum {limits.max_duration}s).',
                        value=duration, limit=limits.max_duration
                    ))

            if prev_valid_start is not None and prev_valid_end is not None:
                if start < prev_valid_start:
                    issues.append(QcIssue(
                        index=i, code='out_of_order', severity='error',
                        message='Segment starts before the previous segment.',
                        value=start, limit=prev_valid_start
                    ))
                if start < prev_valid_end - 0.001:
                    issues.append(QcIssue(
                        index=i, code='overlap', severity='error',
                        message='Segment overlaps with the previous segment.',
                        value=start, limit=prev_valid_end
                    ))

                gap = start - prev_valid_end
                if 0 <= gap < limits.min_gap:
                    issues.append(QcIssue(
                        index=i, code='gap_too_small', severity='warning',
                        message=f'Gap between segments {gap:.3f}s is too small (minimum {limits.min_gap}s).',
                        value=gap, limit=limits.min_gap
                    ))

            prev_valid_start = start
            prev_valid_end = end

        # text checks
        stripped_text = text.strip()
        if not stripped_text:
            issues.append(QcIssue(
                index=i, code='empty_text', severity='error',
                message='Text is empty after stripping whitespace.',
                value=None, limit=None
            ))
        else:
            lines = text.split('\n')
            non_empty_lines = [line for line in lines if line.strip()]
            if len(non_empty_lines) > limits.max_lines:
                issues.append(QcIssue(
                    index=i, code='too_many_lines', severity='warning',
                    message=f'Segment has {len(non_empty_lines)} lines (limit {limits.max_lines}).',
                    value=len(non_empty_lines), limit=limits.max_lines
                ))

            longest_line = max((visible_length(line) for line in lines), default=0)
            if longest_line > limits.max_line_chars:
                msg = f'Line is too long: {longest_line} characters (limit {limits.max_line_chars}).'
                if len(lines) == 1:
                    suggested = suggest_line_break(text, limits.max_line_chars, limits.max_lines)
                    if suggested is not None:
                        msg += ' (a 2-line break fits)'

                issues.append(QcIssue(
                    index=i, code='line_too_long', severity='warning',
                    message=msg,
                    value=longest_line, limit=limits.max_line_chars
                ))

            norm_text = _normalize_text_for_repeated(text)
            if norm_text and prev_norm_text == norm_text:
                issues.append(QcIssue(
                    index=i, code='repeated', severity='warning',
                    message='Text is identical to the previous segment.',
                    value=None, limit=None
                ))

        prev_norm_text = _normalize_text_for_repeated(text) if text.strip() else ""

    # Sort by index, then code
    issues.sort(key=lambda iss: (iss.index, iss.code))
    return issues


def summarize(issues: list[QcIssue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for iss in issues:
        counts[iss.code] = counts.get(iss.code, 0) + 1

    # Sort keys
    return {k: counts[k] for k in sorted(counts.keys())}
