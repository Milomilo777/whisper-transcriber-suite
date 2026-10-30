"""One-copy speech gathering (core/speech_collect.py) equals faster-whisper's collect_chunks."""
from __future__ import annotations

import numpy as np
import pytest

fw_vad = pytest.importorskip("faster_whisper.vad")
fw_transcribe = pytest.importorskip("faster_whisper.transcribe")

from core import speech_collect  # noqa: E402


def _upstream():
    fn = fw_vad.collect_chunks
    return getattr(fn, "__wrapped__", fn)


def _chunks(spans):
    return [{"start": s, "end": e} for s, e in spans]


def _same(audio, spans, sr=16000):
    want_a, want_m = _upstream()(audio, _chunks(spans), sr)
    got_a, got_m = speech_collect.gather_speech(audio, _chunks(spans), sr)
    assert len(got_a) == len(want_a) == 1
    assert got_a[0].dtype == want_a[0].dtype
    np.testing.assert_array_equal(got_a[0], want_a[0])
    assert got_m == want_m


@pytest.mark.parametrize("spans", [
    [(0, 10)],
    [(5, 100), (100, 150), (400, 400), (700, 999)],
    [(10, 20)] * 3,           # repeated region
    [(0, 0)],                 # empty region only
])
def test_gather_equals_upstream(spans):
    _same(np.linspace(-1, 1, 1000, dtype=np.float32), spans)


def test_gather_keeps_float64_promotion_and_sampling_rate():
    _same(np.linspace(-1, 1, 1000), [(1, 50), (60, 70)], sr=8000)


def test_install_patches_both_names_and_routes_finite_durations_upstream(monkeypatch):
    assert speech_collect.install() is True
    assert speech_collect.install() is True  # idempotent
    patched = fw_vad.collect_chunks
    assert getattr(patched, "_wts_speech_collect", False)
    assert fw_transcribe.collect_chunks is patched
    audio = np.arange(2000, dtype=np.float32)
    spans = _chunks([(0, 600), (700, 1500), (1600, 1990)])
    # Batched pipeline: finite max_duration splits into several chunks -> upstream.
    want = _upstream()(audio, [dict(c) for c in spans], 16000, 0.05)
    got = patched(audio, [dict(c) for c in spans], 16000, 0.05)
    assert len(got[0]) == len(want[0]) > 1
    for g, w in zip(got[0], want[0]):
        np.testing.assert_array_equal(g, w)
    assert got[1] == want[1]
    # No chunks -> upstream's empty result.
    assert patched(audio, [])[1] == _upstream()(audio, [])[1]
    # The plain path (max_duration=inf) takes the one-copy gather.
    seen = []
    real = speech_collect.gather_speech
    monkeypatch.setattr(speech_collect, "gather_speech",
                        lambda *a, **k: seen.append(1) or real(*a, **k))
    patched(audio, [dict(c) for c in spans])
    assert seen == [1]


def test_install_refuses_a_collect_chunks_it_cannot_reproduce(monkeypatch):  # noqa: D103
    def other(audio, chunks, sampling_rate=16000, max_duration=float("inf")):
        a, m = _upstream()(audio, chunks, sampling_rate, max_duration)
        return [a[0] * 2], m

    monkeypatch.setattr(fw_vad, "collect_chunks", other)
    monkeypatch.setattr(fw_transcribe, "collect_chunks", other)
    assert speech_collect.install() is False
    assert fw_vad.collect_chunks is other


def test_gather_copies_once():
    # Upstream re-copies the growing array per region: total copied bytes are
    # quadratic. The fast path's peak is about one result plus the slice list.
    import tracemalloc

    audio = np.zeros(16000 * 600, dtype=np.float32)
    spans = [(i * 3200, i * 3200 + 1600) for i in range(3000)]
    tracemalloc.start()
    try:
        speech_collect.gather_speech(audio, _chunks(spans))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    result_bytes = 3000 * 1600 * 4
    assert peak < result_bytes * 1.5, (peak, result_bytes)


hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies


@hypothesis.settings(max_examples=60, deadline=None)
@hypothesis.given(
    n=st.integers(min_value=1, max_value=5000),
    raw=st.lists(st.tuples(st.integers(0, 5000), st.integers(0, 400)), min_size=1, max_size=40),
)
def test_property_gather_equals_upstream(n, raw):
    audio = np.random.default_rng(n).standard_normal(n).astype(np.float32)
    spans = [(min(s, n), min(s + d, n)) for s, d in raw]
    _same(audio, spans)
