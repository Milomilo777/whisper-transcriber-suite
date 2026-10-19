"""Property tests for core.transcript_qa: invariants that must hold for any transcript text."""
from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from core import transcript_qa as qa

# Latin, Persian/Arabic (incl. harakat, tatweel, ZWNJ, digits), Devanagari, CJK, punctuation.
_ALPHABET = st.sampled_from(
    list("abcXYZ 019.,!?-") + [chr(c) for c in range(0x0600, 0x06FF, 3)]
    + ["‌", "ـ", "ً", "ِ", "۱", "٣"]
    + list("नमस्ते") + list("咖啡店ひら")
)
_TEXT = st.text(_ALPHABET, max_size=60)
_SEGMENTS = st.lists(_TEXT, max_size=25).map(
    lambda texts: [{"start": i * 2.0, "end": i * 2.0 + 2, "text": t} for i, t in enumerate(texts)]
)


@settings(max_examples=300)
@given(st.text(max_size=80))
def test_fold_is_idempotent_on_any_text(text):
    once = qa.fold(text)
    assert qa.fold(once) == once


def test_fold_is_idempotent_when_lower_case_adds_a_combining_mark():
    # "İ".lower() is "i" + U+0307; next to another mark the pair needs a second NFKC to settle.
    text = "".join(map(chr, [0x0326, 0x017C, 0x014D, 0x0130, 0x0326]))
    once = qa.fold(text)
    assert qa.fold(once) == once


@settings(max_examples=300)
@given(_TEXT)
def test_fold_is_idempotent_on_mixed_scripts(text):
    once = qa.fold(text)
    assert qa.fold(once) == once


@settings(max_examples=200)
@given(_SEGMENTS, st.integers(1, 120), st.integers(0, 3))
def test_windows_cover_every_segment_in_order(segments, max_chars, overlap):
    windows = qa.make_windows(segments, max_chars=max_chars, overlap=overlap)
    covered = [i for w in windows for i in w]
    assert sorted(set(covered)) == list(range(len(segments)))
    for w in windows:
        assert list(w) == list(range(w[0], w[-1] + 1))  # consecutive segments
    assert [w[0] for w in windows] == sorted({w[0] for w in windows})  # strictly forward


@settings(max_examples=200)
@given(_SEGMENTS, _TEXT, st.integers(10, 400))
def test_context_is_time_ordered_unique_and_within_budget(segments, question, budget):
    picked = qa.select_context(segments, question, count_tokens=len, budget_tokens=budget,
                               max_chars=50, top_k=3)
    assert picked == sorted(set(picked))
    assert all(0 <= i < len(segments) for i in picked)
    if picked:
        assert len(qa.build_evidence(segments, picked).prompt_lines) <= budget


@settings(max_examples=200)
@given(_SEGMENTS.filter(bool), st.data())
def test_evidence_map_is_a_bijection(segments, data):
    indices = data.draw(st.lists(st.integers(0, len(segments) - 1), max_size=10))
    ev = qa.build_evidence(segments, indices)
    with_text = sorted(i for i in set(indices) if segments[i]["text"].strip())
    assert sorted(ev.ids) == list(range(1, len(with_text) + 1))
    assert sorted(ev.ids.values()) == with_text
    assert len(ev.prompt_lines.splitlines()) == len(with_text)  # one line per segment


@settings(max_examples=300)
@given(_SEGMENTS.filter(bool), st.data(), st.text(max_size=80))
def test_check_answer_cites_only_shown_segments(segments, data, noise):
    indices = data.draw(st.lists(st.integers(0, len(segments) - 1), max_size=8))
    ev = qa.build_evidence(segments, indices)
    ids = data.draw(st.lists(st.integers(0, 30), max_size=6))
    answer = noise + " " + " ".join(f"[E{n}]" for n in ids)
    checked = qa.check_answer(answer, ev, segments)
    assert set(checked.cited) <= set(ev.ids.values())
    assert all(n not in ev.ids for n in checked.rejected_ids)
    assert "[E" not in checked.text


@settings(max_examples=200)
@given(st.floats(min_value=0, max_value=200_000, allow_nan=False))
def test_timestamp_round_trips_to_the_rounded_second(seconds):
    text = qa.format_timestamp(seconds)
    parts = [int(p) for p in text.strip("[]").split(":")]
    total = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
    assert total == math.floor(seconds + 0.5)  # half up, not banker's rounding
    assert all(p < 60 for p in parts[1:])
