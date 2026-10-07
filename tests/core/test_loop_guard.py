"""core.loop_guard: contain repetition loops while segments are decoded.

Field report: a 62-minute lecture produced "so good" as 30 one-second
segments in a row (and decoding slowed to ~0.12x real time); runs of 3-7
identical lines also appeared with conditioning off, over music.

These tests pass ``hard=limit`` so a tight run of ``limit`` copies is a loop;
the default ``hard`` and the keep-and-mark band are covered in
test_loop_guard_real_speech.py.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from core import loop_guard
from core.loop_guard import LoopGuardStats, guard_repeats, repeat_key, repeat_limit


@dataclass
class Seg:
    start: float
    end: float
    text: str


def segs(*texts: str, start: float = 0.0) -> list[Seg]:
    return [Seg(start + i, start + i + 1, t) for i, t in enumerate(texts)]


def texts(items) -> list[str]:
    return [s.text for s in items]


def longest_run(items) -> int:
    best = run = 0
    prev = None
    for s in items:
        key = repeat_key(s.text)
        run = run + 1 if key and key == prev else 1
        prev = key
        best = max(best, run)
    return best


# ---- helpers ----------------------------------------------------------------

def test_repeat_key_ignores_case_punctuation_and_spaces():
    assert repeat_key("So good.") == repeat_key(" so  GOOD ") == "sogood"
    assert repeat_key("这个是。") == "这个是"
    assert repeat_key("♪ ♪") == "" and repeat_key("...") == ""


@pytest.mark.parametrize(
    "raw, expected",
    [(None, 3), ("x", 3), (3, 3), ("5", 5), (2, 2), (1, 0), (0, 0), (-4, 0),
     (False, 0), (True, 3)],
)
def test_repeat_limit_parses_config(raw, expected):
    assert repeat_limit({"loop_guard_repeats": raw}) == expected


def test_repeat_limit_default_and_config_default():
    from core.config import DEFAULT_CONFIG

    assert repeat_limit({}) == loop_guard.DEFAULT_REPEATS == 3
    assert DEFAULT_CONFIG["loop_guard_repeats"] == 3


# ---- pass-through -------------------------------------------------------------

def test_short_repeats_pass_unchanged():
    items = segs("a", "okay", "okay", "b", "okay", "okay", "c")
    stats = LoopGuardStats()
    assert texts(guard_repeats(items, limit=3, hard=3, stats=stats)) == texts(items)
    assert stats == LoopGuardStats()


def test_held_repeats_at_the_end_are_flushed():
    items = segs("a", "b", "b")
    assert texts(guard_repeats(items, limit=3, hard=3)) == ["a", "b", "b"]


def test_guard_off_below_two_passes_everything():
    items = segs(*["so good"] * 10)
    assert texts(guard_repeats(items, limit=0)) == ["so good"] * 10


def test_lines_without_letters_never_count_as_repeats():
    items = segs("♪", "♪", "♪", "♪")
    assert texts(guard_repeats(items, limit=3, hard=3)) == ["♪"] * 4


# ---- restart --------------------------------------------------------------------

def test_loop_restarts_once_from_the_second_copy():
    looped = segs("intro", *["so good"] * 30, "never reached", start=0)
    calls: list[float] = []

    def restart(at: float):
        calls.append(at)
        return iter(segs("real words", "more words", start=at))

    events: list[str] = []
    stats = LoopGuardStats()
    out = list(guard_repeats(looped, limit=3, hard=3, restart=restart,
                             on_event=events.append, stats=stats))
    assert calls == [2.0]  # start of the second "so good"
    assert texts(out) == ["intro", "so good", "real words", "more words"]
    assert [s.start for s in out] == [0.0, 1.0, 2.0, 3.0]
    assert stats.restarts == 1 and stats.dropped == 0
    assert len(events) == 1 and "00:00:02" in events[0]


def test_loop_after_the_restart_is_dropped_not_restarted_again():
    calls: list[float] = []

    def restart(at: float):
        calls.append(at)
        return iter(segs(*["so good"] * 5, "next", "next", "next", "next", "end",
                         start=at))

    stats = LoopGuardStats()
    out = list(guard_repeats(segs("a", *["so good"] * 4), limit=3, hard=3,
                             restart=restart, stats=stats))
    assert len(calls) == 1
    assert texts(out) == ["a", "so good", "next", "end"]
    assert stats.restarts == 1 and stats.dropped == 5 + 3
    assert longest_run(out) < 3


def test_failed_restart_falls_back_to_dropping():
    def restart(at: float):
        raise RuntimeError("ffmpeg missing")

    events: list[str] = []
    stats = LoopGuardStats()
    out = list(guard_repeats(segs(*["x y"] * 6, "z"), limit=3, hard=3, restart=restart,
                             on_event=events.append, stats=stats))
    assert texts(out) == ["x y", "z"]
    assert stats.restarts == 0 and stats.dropped == 5
    assert "ffmpeg missing" in events[0]


def test_replaced_and_final_iterators_are_closed():
    closed: list[str] = []

    def gen(name: str, items):
        try:
            yield from items
        finally:
            closed.append(name)

    first = gen("first", segs(*["loop"] * 5))
    second = gen("second", segs("tail", start=1))
    out = list(guard_repeats(first, limit=3, hard=3, restart=lambda at: second))
    assert texts(out) == ["loop", "tail"]
    assert closed == ["first", "second"]


def test_closing_the_guard_closes_the_decoder():
    closed: list[bool] = []

    def gen():
        try:
            yield from segs("a", "b", "c")
        finally:
            closed.append(True)

    guarded = guard_repeats(gen(), limit=3, hard=3)
    assert next(guarded).text == "a"
    guarded.close()  # what a cancelled transcription does
    assert closed == [True]


# ---- collapse-only (batched pipeline, backend path) ----------------------------

def test_without_restart_runs_collapse_to_one_line():
    items = segs("a", *["这个是"] * 7, "b", *["so good"] * 3, "c")
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, hard=3, stats=stats))
    assert texts(out) == ["a", "这个是", "b", "so good", "c"]
    assert stats.dropped == 6 + 2


def test_a_short_repeat_after_a_dropped_run_is_kept():
    items = segs("x", "x", "x", "b", "b", "c")
    assert texts(guard_repeats(items, limit=3, hard=3)) == ["x", "b", "b", "c"]


def test_previous_text_does_not_make_the_first_tail_copy_tight():
    # The checkpointed line's times are on another timeline, so the first
    # tail copy cannot be judged back to back with it (it used to be
    # counted, which dropped both copies here: ["new"]).
    out = list(guard_repeats(segs("so good", "so good", "new"), limit=3, hard=3,
                             previous_text="So good!"))
    assert texts(out) == ["so good", "so good", "new"]


# ---- invariants on random input (stdlib only) ----------------------------------

@pytest.mark.parametrize("seed", range(40))
def test_random_streams_keep_order_and_never_hold_a_long_run(seed):
    rng = random.Random(seed)
    words = ["a", "b", "so good", "Okay.", "okay", "♪"]
    items = segs(*[rng.choice(words) for _ in range(rng.randint(0, 60))])
    limit = rng.choice([2, 3, 4])
    out = list(guard_repeats(items, limit=limit, hard=limit))
    # a subsequence of the input, in order, nothing invented
    pos = iter(items)
    assert all(any(o is s for s in pos) for o in out)
    assert longest_run(out) < limit
    # without a run of `limit` the stream is untouched
    if longest_run(items) < limit:
        assert out == items
