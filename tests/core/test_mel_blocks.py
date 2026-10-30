"""Block-wise log-mel features (core/mel_blocks.py): same result, bounded memory."""
from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

fe_mod = pytest.importorskip("faster_whisper.feature_extractor")

from core import mel_blocks  # noqa: E402

FeatureExtractor = fe_mod.FeatureExtractor


def _upstream():
    """faster-whisper's own __call__, even after install() replaced it."""
    call = FeatureExtractor.__call__
    return getattr(call, "__wrapped__", call)


def _signal(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float32)
    return (0.3 * np.sin(t * 0.013) + 0.05 * rng.standard_normal(n)).astype(np.float32)


@pytest.mark.parametrize("n_mels", [80, 128])
@pytest.mark.parametrize("n,block", [
    (16000 * 20, 97),      # many blocks, last one short
    (16000 * 20, 1999),    # exactly one block edge inside
    (16000 * 20 + 77, 1),  # one frame per block
    (16000 * 3, 10_000),   # one block covering everything
    (1000, 3),             # shorter than one second
    (241, 5),              # with the 160-sample padding: just above n_fft
    (239, 5),              # just below: numpy's own reflection path
])
def test_blocks_equal_upstream(n_mels, n, block):
    fe = FeatureExtractor(feature_size=n_mels)
    x = _signal(n, seed=n_mels)
    want = _upstream()(fe, x)
    got = mel_blocks.blockwise_log_mel(fe, x, block_frames=block)
    assert got.shape == want.shape
    assert got.dtype == want.dtype
    # Equal up to float32 rounding of the mel matrix product (BLAS blocking).
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5)


def test_blocks_keep_upstream_padding_and_chunk_length_side_effects():
    a = FeatureExtractor(feature_size=80)
    b = FeatureExtractor(feature_size=80)
    x = _signal(16000 * 7)
    want = _upstream()(a, x, padding=0, chunk_length=20)
    got = mel_blocks.blockwise_log_mel(b, x, padding=0, chunk_length=20, block_frames=50)
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5)
    assert (b.n_samples, b.nb_max_frames) == (a.n_samples, a.nb_max_frames) == (320000, 2000)


def test_blocks_accept_float64_and_do_not_modify_the_input():
    fe = FeatureExtractor(feature_size=80)
    x = _signal(16000 * 5).astype(np.float64)
    before = x.copy()
    want = _upstream()(fe, x)
    got = mel_blocks.blockwise_log_mel(fe, x, block_frames=64)
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5)
    np.testing.assert_array_equal(x, before)


def test_install_routes_long_inputs_to_blocks_and_short_ones_upstream(monkeypatch):
    assert mel_blocks.install() is True
    assert mel_blocks.install() is True  # idempotent
    call = FeatureExtractor.__call__
    assert getattr(call, "_wts_mel_blocks", False)
    fe = FeatureExtractor(feature_size=80)
    seen = []
    real = mel_blocks.blockwise_log_mel
    monkeypatch.setattr(mel_blocks, "blockwise_log_mel",
                        lambda *a, **k: seen.append(1) or real(*a, **k))
    monkeypatch.setattr(mel_blocks, "BLOCK_FRAMES", 500)
    short = _signal(16000 * 4)    # 400 frames: upstream
    np.testing.assert_array_equal(fe(short), _upstream()(fe, short))
    assert seen == []
    long = _signal(16000 * 12)    # 1200 frames: blocks
    np.testing.assert_allclose(fe(long), _upstream()(fe, long), rtol=0, atol=1e-5)
    assert seen == [1]
    # An argument only a later faster-whisper knows goes to upstream untouched.
    with pytest.raises(TypeError):
        fe(long, 160, None, "future-arg")
    assert seen == [1]


def test_install_refuses_an_extractor_it_cannot_reproduce(monkeypatch):
    class Other(FeatureExtractor):  # an upstream change: different scaling
        def __call__(self, waveform, padding=160, chunk_length=None):
            return _upstream()(self, waveform, padding, chunk_length) * 1.01

    monkeypatch.setattr(fe_mod, "FeatureExtractor", Other)
    before = Other.__call__
    assert mel_blocks.install() is False
    assert Other.__call__ is before


def test_blocks_bound_peak_memory():
    fe = FeatureExtractor(feature_size=128)
    x = _signal(16000 * 120)  # 2 minutes = 12,000 frames
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        _upstream()(fe, x)
        _, upstream_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        mel_blocks.blockwise_log_mel(fe, x, block_frames=1000)
        _, block_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Upstream holds ~6 frame-sized arrays (> 4 MB/s of audio); blocks hold the
    # padded input, the output and one block.
    assert block_peak * 3 < upstream_peak, (block_peak, upstream_peak)


hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies


@hypothesis.settings(max_examples=40, deadline=None)
@hypothesis.given(
    n=st.integers(min_value=500, max_value=16000 * 8),
    block=st.integers(min_value=1, max_value=900),
    padding=st.sampled_from([0, 160, 401]),
    seed=st.integers(min_value=0, max_value=2**16),
)
def test_property_blocks_equal_upstream(n, block, padding, seed):
    fe = FeatureExtractor(feature_size=80)
    x = _signal(n, seed)
    want = _upstream()(fe, x, padding=padding)
    got = mel_blocks.blockwise_log_mel(fe, x, padding=padding, block_frames=block)
    assert got.shape == want.shape
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-5)
