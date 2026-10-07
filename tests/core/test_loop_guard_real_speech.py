"""core.loop_guard keeps real repeated speech and stays responsive.

A decoder loop and a repeated prayer look alike as text ("Amen." x4). They
differ in structure: loop copies come back to back (gap under 0.25 s) and
are short, real repeats are spoken with normal pauses. The guard drops only
a long streak of tight copies (``hard``); shorter tight streaks are kept and
marked for review; anything with real pauses passes unchanged.
"""
from __future__ import annotations

import random
from collections import namedtuple
from dataclasses import dataclass

import pytest

from core import loop_guard
from core.loop_guard import (
    LoopGuardStats,
    LoopGuardTick,
    guard_repeats,
    repeat_key,
    take_mark,
)


@dataclass
class Seg:
    start: float
    end: float
    text: str


def spaced(text: str, n: int, *, start: float = 0.0, dur: float = 2.5,
           gap: float = 0.5) -> list[Seg]:
    out: list[Seg] = []
    t = start
    for _ in range(n):
        out.append(Seg(round(t, 2), round(t + dur, 2), text))
        t = round(t + dur + gap, 2)
    return out


def segs_only(items) -> list[Seg]:
    return [s for s in items if not isinstance(s, LoopGuardTick)]


def texts(items) -> list[str]:
    return [s.text for s in segs_only(items)]


def marks(stats: LoopGuardStats, items) -> list[str | None]:
    return [take_mark(stats, s) for s in segs_only(items)]


def longest_tight_run(items) -> int:
    best = run = 0
    prev = None
    for s in items:
        key = repeat_key(s.text)
        tight = (
            prev is not None and key and key == repeat_key(prev.text)
            and -0.2 <= round(s.start - prev.end, 2) < 0.25
            and (s.end - s.start) < 5.0
        )
        run = run + 1 if tight else 1
        prev = s
        best = max(best, run)
    return best


# ---- S01-1: real repeated speech survives ------------------------------------

def test_amen_four_times_with_normal_pauses_is_kept_unmarked():
    items = spaced("Amen.", 4, dur=2.5, gap=0.5) + [Seg(12.0, 14.0, "Praise the Lord.")]
    calls: list[float] = []
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, restart=lambda at: calls.append(at) or iter(()),
                             stats=stats))
    assert out == items
    assert calls == [] and stats.restarts == 0 and stats.dropped == 0
    assert marks(stats, out) == [None] * 5


@pytest.mark.parametrize("seed", range(8))
def test_repeats_with_real_pauses_are_never_altered(seed):
    rng = random.Random(seed)
    for _ in range(40):
        n = rng.randint(2, 40)
        gap = rng.choice([0.25, 0.26, 0.3, 0.5, 1.0, 2.0])
        dur = round(rng.uniform(0.3, 4.9), 2)
        items = spaced(rng.choice(["Amen.", "so good", "Hallelujah"]), n, dur=dur, gap=gap)
        stats = LoopGuardStats()
        out = list(guard_repeats(items, limit=3, stats=stats,
                                 restart=lambda at: pytest.fail("no restart expected")))
        assert out == items, (n, gap, dur)
        assert stats.dropped == 0 and not stats.marked_ids


def test_long_copies_are_never_tight():
    items = spaced("We pray.", 12, dur=5.0, gap=0.0)
    assert list(guard_repeats(items, limit=3)) == items


def test_two_decimal_gap_of_exactly_a_quarter_second_is_a_pause():
    # 1.4 - 1.15 is 0.2499999... in floating point; the timestamps carry two
    # decimals, so the gap must be read as 0.25 (a pause), not as tight.
    items = [Seg(0.9, 1.15, "Amen.")] + [
        Seg(round(1.4 + i * 0.5, 2), round(1.65 + i * 0.5, 2), "Amen.") for i in range(10)
    ]
    assert list(guard_repeats(items, limit=3)) == items


# ---- tight streaks under the hard limit: kept and marked ---------------------

@pytest.mark.parametrize("n", [3, 4, 5, 6, 7])
def test_short_tight_streak_is_kept_and_marked(n):
    items = [Seg(0, 1, "a")] + spaced("Amen.", n, start=1.0, dur=0.3, gap=0.05) + [
        Seg(30, 31, "b")]
    events: list[str] = []
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, stats=stats, on_event=events.append))
    assert out == items
    got = marks(stats, out)
    assert got == [None, None] + ["repeated-line"] * (n - 1) + [None]
    assert stats.marked == n - 1 and stats.dropped == 0
    assert len(events) == 1 and f"{n} identical" in events[0]


def test_streak_below_limit_is_not_marked():
    items = spaced("Amen.", 2, dur=0.3, gap=0.05)
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, stats=stats))
    assert out == items and marks(stats, out) == [None, None]


def test_pause_splits_a_run_and_each_part_is_judged_alone():
    first = spaced("Amen.", 7, dur=0.3, gap=0.05)
    second = spaced("Amen.", 7, start=10.0, dur=0.3, gap=0.05)
    stats = LoopGuardStats()
    out = list(guard_repeats(first + second, limit=3, stats=stats))
    assert out == first + second
    assert stats.marked == 12

    first = spaced("Amen.", 8, dur=0.3, gap=0.05)
    second = spaced("Amen.", 8, start=10.0, dur=0.3, gap=0.05)
    stats = LoopGuardStats()
    out = list(guard_repeats(first + second, limit=3, stats=stats))
    assert out == [first[0], second[0]]
    assert stats.dropped == 14


@pytest.mark.parametrize("gap", [-0.2, -0.1, 0.0, 0.24])
def test_tight_gaps_collapse_a_long_streak(gap):
    items = spaced("so good", 10, dur=1.0, gap=gap)
    assert texts(guard_repeats(items, limit=3)) == ["so good"]


def test_real_overlap_is_not_tight():
    items = spaced("so good", 10, dur=1.0, gap=-0.3)
    assert list(guard_repeats(items, limit=3)) == items


# ---- S01-1 / S01-2: a real loop is contained, the guard stays responsive -----

def test_back_to_back_loop_drops_to_one_copy_and_yields_ticks():
    pulled: list[int] = []

    def decoder():
        for i in range(1000):
            pulled.append(i)
            yield Seg(float(i), float(i + 1), "so good")
        yield Seg(1000.0, 1001.0, "different")

    stats = LoopGuardStats()
    gaps: list[int] = []
    out = []
    last = 0
    for item in guard_repeats(decoder(), limit=3, stats=stats, ticks=True):
        gaps.append(len(pulled) - last)
        last = len(pulled)
        out.append(item)
    assert texts(out) == ["so good", "different"]
    assert stats.dropped == 999
    assert max(gaps) <= loop_guard.HARD_REPEATS
    ticks = [t for t in out if isinstance(t, LoopGuardTick)]
    assert len(ticks) == 999 and ticks[-1].end == 1000.0


def test_without_ticks_nothing_but_segments_is_yielded():
    items = spaced("so good", 20, dur=1.0, gap=0.0)
    out = list(guard_repeats(items, limit=3))
    assert out == [items[0]]


def test_restart_point_is_the_first_held_copy():
    calls: list[float] = []

    def restart(at: float):
        calls.append(at)
        return iter([Seg(at, at + 3, "real words")])

    items = [Seg(0, 5, "intro")] + spaced("so good", 30, start=5.0, dur=1.0, gap=0.0)
    out = list(guard_repeats(items, limit=3, restart=restart))
    assert calls == [6.0]
    assert texts(out) == ["intro", "so good", "real words"]


def test_restarted_copies_are_compared_with_the_anchor():
    def restart(at: float):
        # the second decode loops as well: all of it is dropped
        return iter(spaced("so good", 9, start=at, dur=1.0, gap=0.0)
                    + [Seg(at + 20, at + 21, "end")])

    stats = LoopGuardStats()
    items = spaced("so good", 8, dur=1.0, gap=0.0)
    out = list(guard_repeats(items, limit=3, restart=restart, stats=stats))
    assert texts(out) == ["so good", "end"]
    assert stats.restarts == 1 and stats.dropped == 9


def test_no_restart_once_the_task_is_cancelled():
    stats = LoopGuardStats()
    items = spaced("so good", 12, dur=1.0, gap=0.0)
    out = list(guard_repeats(items, limit=3, stats=stats,
                             restart=lambda at: pytest.fail("restart while cancelled"),
                             cancelled=lambda: True))
    assert texts(out) == ["so good"] and stats.restarts == 0


def test_dropped_run_is_logged_with_its_span():
    events: list[str] = []
    items = spaced("so good", 20, start=60.0, dur=1.0, gap=0.0) + [Seg(90, 91, "x")]
    list(guard_repeats(items, limit=3, on_event=events.append))
    assert any("dropped 19" in e and "00:01:01" in e and "00:01:19" in e for e in events)


def test_frozen_segments_and_broken_metrics_do_not_break_marking():
    Frozen = namedtuple("Frozen", "start end text")

    class Weird:
        def __init__(self, s: float, e: float):
            self.start, self.end, self.text = s, e, "Amen."

        @property
        def avg_logprob(self):
            raise RuntimeError("bad metric")

    items = [Frozen(0.0, 0.3, "Amen."), Frozen(0.35, 0.65, "Amen."),
             Frozen(0.7, 1.0, "Amen."), Weird(1.05, 1.35)]
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, stats=stats))
    assert out == items
    assert marks(stats, out) == [None] + ["repeated-line"] * 3


def test_resume_seam_first_tail_copy_is_not_tight():
    out = list(guard_repeats(spaced("so good", 2, dur=1.0, gap=0.0) + [Seg(5, 6, "new")],
                             limit=3, previous_text="So good!"))
    assert texts(out) == ["so good", "so good", "new"]


def test_missing_times_never_crash_and_count_as_not_tight():
    @dataclass
    class Bare:
        text: str

    items = [Bare("so good") for _ in range(12)]
    assert list(guard_repeats(items, limit=3)) == items


@pytest.mark.parametrize("seed", range(30))
def test_random_streams_keep_order_and_bound_tight_runs(seed):
    rng = random.Random(seed)
    items: list[Seg] = []
    t = 0.0
    for _ in range(rng.randint(0, 80)):
        dur = rng.choice([0.3, 1.0, 2.5, 6.0])
        gap = rng.choice([0.0, 0.05, 0.25, 0.5, -0.3])
        items.append(Seg(round(t, 2), round(t + dur, 2), rng.choice(["a", "so good", "Amen.", "♪"])))
        t = round(t + dur + gap, 2)
    stats = LoopGuardStats()
    out = list(guard_repeats(items, limit=3, stats=stats))
    pos = iter(items)
    assert all(any(o is s for s in pos) for o in out)
    if stats.dropped:
        assert longest_tight_run(out) < loop_guard.HARD_REPEATS
    if longest_tight_run(items) < loop_guard.HARD_REPEATS:
        assert out == items
