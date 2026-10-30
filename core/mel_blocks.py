"""Log-mel features of a long file in blocks (bounded memory).

faster-whisper (checked on 1.2.1) computes the log-mel spectrogram of the
WHOLE speech-only audio in one go before it detects the language: the framed
and windowed signal (frames x 400 float32), its FFT (frames x 201 complex64),
a second copy of that FFT (``astype``), the squared magnitudes and the mel
product all live at once. At 100 frames per second that is several GB of
temporaries per hour of audio. Measured with ``small`` on a 16 GB Windows
laptop: the process peak commit before ``transcribe()`` returned was 4.8 GB for
a 1-hour file, 7.1 GB for 2 hours and 9.4 GB for 3 hours. On an 8 GB machine,
or with a large model loaded, a long file fails with ``MemoryError`` before
any text is produced.

:func:`install` replaces ``FeatureExtractor.__call__`` with a version that
computes the same frames block by block into one preallocated
``(n_mels, frames)`` array and then applies the same global log / clip /
``max - 8`` / scale steps, so the result equals upstream while the temporaries
stay at one block (about five minutes of audio). Inputs no longer than one
block take faster-whisper's own code path unchanged, which covers the batched
pipeline's 30-second chunks. :func:`install` first checks the block version
against upstream on a short noise signal (with tiny blocks, so the block edges
are exercised) and leaves faster-whisper untouched when they differ, for
example after an upstream change to the feature extractor.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Frames per block: 30,000 frames = 5 minutes at faster-whisper's 10 ms hop.
BLOCK_FRAMES = 30_000

_MARKER = "_wts_mel_blocks"


def blockwise_log_mel(
    extractor: Any,
    waveform: Any,
    padding: int = 160,
    chunk_length: int | None = None,
    block_frames: int = BLOCK_FRAMES,
) -> Any:
    """``FeatureExtractor.__call__`` computed in blocks of *block_frames*.

    Mirrors faster-whisper 1.1/1.2: optional ``chunk_length`` update, float32,
    ``padding`` zeros at the end, centred STFT (reflect padding of n_fft // 2)
    with a periodic Hann window, last frame dropped, power spectrum, mel
    filter bank, then ``log10(clip(., 1e-10))``, ``maximum(., max - 8)`` and
    ``(x + 4) / 4`` over the whole file.
    """
    import numpy as np

    if chunk_length is not None:
        extractor.n_samples = chunk_length * extractor.sampling_rate
        extractor.nb_max_frames = extractor.n_samples // extractor.hop_length
    n_fft = int(extractor.n_fft)
    hop = int(extractor.hop_length)
    half = n_fft // 2
    signal = np.asarray(waveform, dtype=np.float32)  # no copy when float32
    length = signal.shape[0] + (padding or 0)
    if length <= n_fft:
        # Tiny input: numpy's own padding (it reflects repeatedly if needed).
        if padding:
            signal = np.pad(signal, (0, padding))
        padded = np.pad(signal, (half, half), mode="reflect")
    else:
        # One buffer for both paddings: [reflection | signal | zeros | reflection],
        # equal to upstream's np.pad(np.pad(x, (0, padding)), half, "reflect").
        padded = np.empty(length + 2 * half, dtype=np.float32)
        padded[half:half + signal.shape[0]] = signal
        padded[half + signal.shape[0]:half + length] = 0.0
        padded[:half] = padded[2 * half:half:-1]
        padded[half + length:] = padded[half + length - 2:length - 2:-1]
    del signal
    n_frames = 1 + (padded.shape[0] - n_fft) // hop
    out_frames = n_frames - 1  # upstream drops the last frame
    window = np.hanning(n_fft + 1)[:-1].astype("float32")
    filters = extractor.mel_filters
    mel = np.empty((filters.shape[0], max(out_frames, 0)), dtype=np.float32)
    for start in range(0, out_frames, block_frames):
        stop = min(start + block_frames, out_frames)
        seg = padded[start * hop:(stop - 1) * hop + n_fft]
        # A bounds-checked view (unlike as_strided): a short slice fails here.
        frames = np.lib.stride_tricks.sliding_window_view(seg, n_fft)[::hop]
        if frames.shape[0] != stop - start:
            raise ValueError(f"mel blocks: {frames.shape[0]} frames, expected {stop - start}")
        spectrum = np.fft.rfft(frames * window, n=n_fft, axis=-1).astype("complex64")
        power = np.abs(spectrum) ** 2
        del spectrum
        mel[:, start:stop] = filters @ power.T
    del padded
    np.clip(mel, 1e-10, None, out=mel)
    np.log10(mel, out=mel)
    np.maximum(mel, mel.max() - 8.0, out=mel)
    mel += 4.0
    mel /= 4.0
    return mel


def _make_call(original: Callable[..., Any]) -> Callable[..., Any]:
    def __call__(self: Any, waveform: Any, padding: int = 160,
                 chunk_length: int | None = None) -> Any:
        ndim = getattr(waveform, "ndim", 0)
        length = waveform.shape[-1] if ndim else 0
        frames = (length + (padding or 0)) // max(int(self.hop_length), 1)
        if ndim != 1 or frames <= BLOCK_FRAMES:
            return original(self, waveform, padding=padding, chunk_length=chunk_length)
        return blockwise_log_mel(self, waveform, padding=padding,
                                 chunk_length=chunk_length)

    setattr(__call__, _MARKER, True)
    setattr(__call__, "__wrapped__", original)
    return __call__


def _matches_upstream(extractor_cls: Any, original: Callable[..., Any]) -> bool:
    """Compare the block version with upstream on 3 s of noise, 64-frame blocks.

    The last second is 30x louder, so the global ``max - 8`` floor differs
    from any single early block's.
    """
    import numpy as np

    rng = np.random.default_rng(1234)
    audio = (rng.standard_normal(48_000) * 0.01).astype(np.float32)
    audio[32_000:] *= 30
    for n_mels in (80, 128):
        fe = extractor_cls(feature_size=n_mels)
        want = original(fe, audio)
        got = blockwise_log_mel(fe, audio, block_frames=64)
        if got.shape != want.shape or got.dtype != want.dtype:
            logger.warning("mel blocks: shape/dtype %s %s differ from upstream %s %s",
                           got.shape, got.dtype, want.shape, want.dtype)
            return False
        diff = float(np.max(np.abs(got - want))) if want.size else 0.0
        if diff > 1e-5:
            logger.warning("mel blocks: differ from upstream by %g", diff)
            return False
    return True


def install() -> bool:
    """Route faster-whisper's feature extraction through the block version.

    Idempotent. Returns False and leaves faster-whisper alone when its
    feature extractor is missing, has another shape, or computes something
    the block version does not reproduce.
    """
    try:
        from faster_whisper import feature_extractor as fw_fe
    except Exception as e:  # noqa: BLE001 - optional engine, any import error
        logger.warning("mel blocks unavailable (faster_whisper.feature_extractor: %s)", e)
        return False
    cls = getattr(fw_fe, "FeatureExtractor", None)
    current = getattr(cls, "__call__", None) if cls is not None else None
    if cls is None or current is None:
        logger.warning("mel blocks unavailable: FeatureExtractor.__call__ missing")
        return False
    if getattr(current, _MARKER, False):
        return True
    try:
        ok = _matches_upstream(cls, current)
    except Exception as e:  # noqa: BLE001 - any upstream difference: keep upstream
        logger.warning("mel blocks not used: self-check failed (%s: %s)", type(e).__name__, e)
        return False
    if not ok:
        logger.warning("mel blocks not used: this faster-whisper's features differ")
        return False
    cls.__call__ = _make_call(current)
    return True
