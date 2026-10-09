"""core.speed_meter: golden values and randomised property checks.

Hypothesis is not a dependency of this repo, so the property checks use
seeded ``random`` streams (hundreds of runs each) instead.
"""
from __future__ import annotations

import math
import random

import pytest

from core import speed_meter as sm
from core.speed_meter import SpeedMeter


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _meter(end: float, start: float = 0.0) -> tuple[SpeedMeter, FakeClock]:
    clock = FakeClock()
    return SpeedMeter(end, start, clock=clock), clock


# -- golden values --------------------------------------------------------


def test_golden_120s_audio_in_10s_is_12x():
    m, clock = _meter(120.0)
    m.start()
    for _ in range(10):
        clock.advance(1.0)
        m.update(m.pos + 12.0)
    assert m.speed_x == pytest.approx(12.0)
    m.finish()
    assert m.average_x == pytest.approx(12.0)
    assert m.audio_s == pytest.approx(120.0)
    assert m.elapsed() == pytest.approx(10.0)
    assert m.eta_s == 0.0


def test_golden_eta_is_remaining_over_speed():
    m, clock = _meter(600.0)
    m.start()
    for _ in range(10):
        clock.advance(1.0)
        m.update(m.pos + 6.0)
    # 60 s done at 6x: 540 s of audio left = 90 s.
    assert m.speed_x == pytest.approx(6.0)
    assert m.eta_s == pytest.approx(90.0)


def test_startup_work_does_not_slow_the_live_speed():
    # 20 s of voice/language detection before the first segment, then a
    # steady 10x: the live speed says 10x, the final average counts it all.
    m, clock = _meter(1200.0)
    m.start()
    clock.advance(20.0)
    for _ in range(60):
        clock.advance(1.0)
        m.update(m.pos + 10.0)
    assert m.speed_x == pytest.approx(10.0)
    assert m.eta_s == pytest.approx((1200.0 - 600.0) / 10.0)
    m.finish()
    assert m.average_x == pytest.approx(1200.0 / 80.0)


def test_pause_stops_the_clock():
    m, clock = _meter(120.0)
    m.start()
    for i in range(10):
        clock.advance(1.0)
        if i == 4:
            m.pause()
            clock.advance(500.0)  # the user went for lunch
            m.resume()
        m.update(m.pos + 12.0)
    m.finish()
    assert m.elapsed() == pytest.approx(10.0)
    assert m.average_x == pytest.approx(12.0)


def test_elapsed_frozen_while_paused():
    m, clock = _meter(120.0)
    m.start()
    clock.advance(2.0)
    m.pause()
    clock.advance(30.0)
    assert m.elapsed() == pytest.approx(2.0)
    assert m.paused


def test_rewind_never_moves_position_back():
    m, clock = _meter(120.0)
    m.start()
    clock.advance(1.0)
    m.update(60.0)
    clock.advance(1.0)
    m.update(30.0)  # a loop-guard restart re-decodes earlier audio
    assert m.pos == 60.0


def test_silent_tail_counts_in_final_speed():
    # Speech ends at 80 s of a 120 s file; the engine yields nothing more.
    m, clock = _meter(120.0)
    m.start()
    for _ in range(10):
        clock.advance(1.0)
        m.update(m.pos + 8.0)
    m.finish()
    assert m.audio_s == pytest.approx(120.0)
    assert m.average_x == pytest.approx(12.0)  # not 8.0


def test_no_eta_before_30s_of_audio():
    m, clock = _meter(600.0)
    m.start()
    for _ in range(4):
        clock.advance(1.0)
        m.update(m.pos + 6.0)
    assert m.pos == 24.0
    assert m.eta_s is None
    assert m.speed_x is None
    assert sm.live_cell(m.speed_x, m.eta_s) == "measuring speed..."


def test_resumed_tail_measures_only_this_run():
    m, clock = _meter(600.0, start=300.0)
    m.start()
    for _ in range(30):
        clock.advance(1.0)
        m.update(m.pos + 10.0)
    m.finish()
    assert m.audio_s == pytest.approx(300.0)
    assert m.average_x == pytest.approx(10.0)


def test_unknown_duration_has_no_eta_and_uses_last_position():
    m, clock = _meter(0.0)
    m.start()
    for _ in range(10):
        clock.advance(1.0)
        m.update(m.pos + 5.0)
    assert m.eta_s is None
    assert m.speed_x == pytest.approx(5.0)
    m.finish()
    assert m.audio_s == pytest.approx(50.0)
    assert m.average_x == pytest.approx(5.0)


def test_finish_without_any_segment_is_safe():
    m, _clock = _meter(0.0)
    m.finish()
    assert m.average_x is None
    assert m.eta_s == 0.0


def test_live_speed_is_the_average_since_the_first_segment():
    # 120 s at 10x then 120 s at 2x: the content changed speed. The live
    # speed is the average since the first segment (1440 s of audio after
    # it in 239 s), which predicted real runs better than a sliding window.
    m, clock = _meter(10_000.0)
    m.start()
    for _ in range(120):
        clock.advance(1.0)
        m.update(m.pos + 10.0)
    for _ in range(120):
        clock.advance(1.0)
        m.update(m.pos + 2.0)
    assert m.speed_x == pytest.approx((1440.0 - 10.0) / 239.0)
    # The time left follows remaining / that speed, trailing the still-rising
    # target by about one smoothing time constant (7 % here).
    raw = (10_000.0 - m.pos) / m.speed_x
    assert m.eta_s is not None
    assert 0.9 * raw < m.eta_s < raw


def test_eta_change_is_bounded_on_a_sudden_slowdown():
    m, clock = _meter(10_000.0)
    m.start()
    for _ in range(60):
        clock.advance(1.0)
        m.update(m.pos + 10.0)
    before = m.eta_s
    assert before is not None
    clock.advance(30.0)
    m.update(m.pos + 1.0)  # one very slow sample
    expected = before - 30.0
    raw = (10_000.0 - m.pos) / m.speed_x
    assert m.eta_s is not None
    # Moved toward the slower estimate, but only by the time-weighted share.
    assert expected < m.eta_s < raw
    assert m.eta_s == pytest.approx(expected + sm.eta_weight(30.0) * (raw - expected))


def test_a_burst_of_segments_cannot_move_the_eta():
    # A slow model emits a whole decode window's segments at the same moment.
    m, clock = _meter(10_000.0)
    m.start()
    for _ in range(60):
        clock.advance(1.0)
        m.update(m.pos + 10.0)
    before = m.eta_s
    for _ in range(8):
        m.update(m.pos + 4.0)  # dt = 0
    assert m.eta_s == before


def test_bursty_slow_model_speed_is_stable():
    # 30 s of audio per burst, one burst every 45 s (0.667x), as slow models
    # emit segments: the live speed must not swing between stall and sprint.
    m, clock = _meter(3600.0)
    m.start()
    seen = []
    for _ in range(40):
        clock.advance(45.0)
        for k in range(6):
            m.update(m.pos + 5.0)
            if m.speed_x is not None:
                seen.append(m.speed_x)
    late = seen[len(seen) // 2:]
    assert min(late) > 0.5 and max(late) < 0.9


def test_overshoot_past_probed_end_never_goes_negative():
    m, clock = _meter(100.0)
    m.start()
    for _ in range(6):
        clock.advance(1.0)
        m.update(m.pos + 25.0)  # last segment ends past the probed duration
        assert m.eta_s is None or m.eta_s >= 0.0


# -- formatting -----------------------------------------------------------


@pytest.mark.parametrize("secs,text", [
    (0, "under 1 s"), (0.4, "under 1 s"), (40, "40 s"), (60, "1 min"), (220, "3 min 40 s"),
    (2520, "42 min"), (3600, "1 h"), (3900, "1 h 5 min"),
])
def test_format_duration(secs, text):
    assert sm.format_duration(secs) == text


@pytest.mark.parametrize("eta,text", [
    (None, ""), (0.0, "audio done"), (12.0, "under 1 min left"),
    (61.0, "2 min left"), (360.0, "6 min left"), (4800.0, "1 h 20 min left"),
    (3600.0, "1 h left"),
])
def test_format_time_left(eta, text):
    assert sm.format_time_left(eta) == text


def test_live_cell_and_summary_line():
    assert sm.live_cell(4.83, 360.0) == "about 4.8x, 6 min left"
    assert sm.live_cell(None, None) == "measuring speed..."
    assert sm.summary_line(2520.0, 220.0, "small", "cpu") == (
        "42 min of audio transcribed in 3 min 40 s (11.5x) with small on CPU"
    )
    assert sm.summary_line(60.0, 30.0, "tiny", "cuda", resumed=True) == (
        "1 min of audio transcribed in 30 s (2.0x) with tiny on GPU, "
        "counting only the part done after resuming"
    )
    assert sm.summary_line(600.0, 60.0, "faster-whisper-large-v3-turbo", "") == (
        "10 min of audio transcribed in 1 min (10.0x) with large-v3-turbo"
    )
    assert sm.summary_line(300.0, 750.0, "large-v3", "cpu") == (
        "5 min of audio transcribed in 12 min 30 s "
        "(0.4x, slower than the recording plays) with large-v3 on CPU"
    )
    assert sm.summary_line(0.0, 5.0) == ""
    assert sm.summary_line(10.0, 0.2) == ""  # a blink of a clock: no line
    assert sm.live_cell(0.05, 36000.0) == "very slow, 10 h left"
    assert sm.live_cell(4.8, 0.0) == "about 4.8x, audio done"
    assert sm.format_speed(99.96) == "100x"
    assert sm.format_speed(99.94) == "99.9x"
    assert sm.format_speed(float("inf")) == ""


# -- randomised properties --------------------------------------------------


def _random_run(seed: int):
    """Drive a meter with a random stream; yield (meter, clock, record)."""
    rng = random.Random(seed)
    total = rng.choice([0.0, rng.uniform(5.0, 7200.0)])
    start = rng.choice([0.0, 0.0, rng.uniform(0.0, total * 0.8 if total else 100.0)])
    m, clock = _meter(total, start)
    m.start()
    pos = start
    active = 0.0
    history = []
    last_t = 0.0
    for _ in range(rng.randint(0, 300)):
        dt = rng.choice([0.0, rng.uniform(0.05, 3.0), rng.uniform(3.0, 40.0)])
        clock.advance(dt)
        active += dt
        if rng.random() < 0.08:
            m.pause()
            clock.advance(rng.uniform(1.0, 900.0))
            m.resume()
        roll = rng.random()
        if roll < 0.1:
            seg_end = pos - rng.uniform(0.0, 60.0)  # rewind
        elif roll < 0.25:
            seg_end = pos  # a dropped loop copy / silence
        else:
            seg_end = pos + rng.uniform(0.0, 30.0)
            pos = seg_end
        prev_eta, prev_t = m.eta_s, last_t
        m.update(seg_end)
        last_t = m.elapsed()
        speed = m.speed_x
        raw = None
        if prev_eta is not None:
            raw = max(0.0, m.end_pos - m.pos) / speed if speed else prev_eta
        history.append((prev_eta, prev_t, m.eta_s, last_t, m.pos, speed, raw))
    return m, clock, history, active


SEEDS = range(400)


@pytest.mark.parametrize("seed", SEEDS)
def test_property_speed_positive_eta_nonnegative_bounded(seed):
    m, _, history, active = _random_run(seed)
    last_pos = m.start_pos
    for prev_eta, prev_t, eta, t, pos, speed, raw in history:
        assert pos >= last_pos  # monotone audio position
        last_pos = pos
        assert speed is None or (speed > 0 and math.isfinite(speed))
        assert eta is None or (eta >= 0 and math.isfinite(eta))
        if prev_eta is not None and eta is not None and pos < m.end_pos:
            # Bounded: between the counted-down estimate and the new one,
            # and at most the time-weighted share of the way.
            dt = t - prev_t
            expected = max(0.0, prev_eta - dt)
            assert min(expected, raw) - 1e-6 <= eta <= max(expected, raw) + 1e-6
            assert abs(eta - expected) <= sm.eta_weight(dt) * abs(raw - expected) + 1e-6
    # Pauses never count as decode time.
    assert m.elapsed() == pytest.approx(active)
    m.finish()
    assert m.eta_s == 0.0
    avg = m.average_x
    assert avg is None or avg > 0


@pytest.mark.parametrize("seed", range(150))
def test_property_constant_rate_is_measured_exactly(seed):
    rng = random.Random(10_000 + seed)
    rate = rng.uniform(0.2, 40.0)
    total = rng.uniform(200.0, 5000.0)
    m, clock = _meter(total)
    m.start()
    t = 0.0
    while m.pos < total:
        dt = rng.uniform(0.2, 5.0)
        if rng.random() < 0.1:
            m.pause()
            clock.advance(rng.uniform(1.0, 300.0))
            m.resume()
        clock.advance(dt)
        t += dt
        m.update(min(total, rate * t))
        if m.eta_s is not None and m.pos < total:
            assert m.speed_x == pytest.approx(rate, rel=1e-6)
            assert m.eta_s == pytest.approx((total - m.pos) / rate, rel=1e-6, abs=1e-6)
    assert m.eta_s == 0.0  # ETA reaches 0 at the end
    m.finish()
    assert m.average_x == pytest.approx(total / t, rel=1e-6)
