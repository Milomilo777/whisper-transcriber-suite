"""core.vad_window: fresh Silero VAD state per window on long files.

Regression for a field report: on a 62-minute lecture with long music
examples, faster-whisper's single VAD pass (state carried over the whole
file) found 512 s of speech; a fresh state every 30 s found 1,615 s. The
fake model below reproduces the mechanism deterministically: once it has
"heard" enough music in one call it reports no speech for the rest of that
call, the way the carried LSTM state did.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest

from core import vad_window

SR = 16000
FRAME = 512
MUSIC = 0.25    # sample value the fake model treats as music
SPEECH = 0.75   # sample value the fake model treats as speech


class LockingVad:
    """Fake ``SileroVADModel``: per call, a fresh state like the real one.

    A frame is speech (prob 0.9) when its first sample is SPEECH, unless the
    call has already seen ``lock_after`` music frames: then every later frame
    of that call scores 0.05 (the stuck state).
    """

    def __init__(self, lock_after: int = 100) -> None:
        self.lock_after = lock_after
        self.calls: list[int] = []

    def __call__(self, audio, num_samples=512, context_size_samples=64):
        assert audio.shape[0] % num_samples == 0
        self.calls.append(int(audio.shape[0]))
        frames = audio.reshape(-1, num_samples)[:, 0]
        out = np.zeros((frames.shape[0], 1), dtype=np.float32)
        music_seen = 0
        for i, first in enumerate(frames):
            if music_seen >= self.lock_after:
                out[i] = 0.05
                continue
            if first == MUSIC:
                music_seen += 1
            out[i] = 0.9 if first == SPEECH else 0.05
        return out


def _signal(*parts: tuple[float, float]) -> np.ndarray:
    """Concatenate (value, seconds) blocks; length padded to whole frames."""
    audio = np.concatenate(
        [np.full(int(sec * SR), val, dtype=np.float32) for val, sec in parts]
    )
    return np.pad(audio, (0, (-audio.shape[0]) % FRAME))


def _speech_seconds(probs: np.ndarray, start_s: float, end_s: float) -> float:
    lo, hi = int(start_s * SR) // FRAME, int(end_s * SR) // FRAME
    return float((probs.reshape(-1)[lo:hi] >= 0.5).sum()) * FRAME / SR


# ---- config value ---------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 0.0), ("abc", 0.0), (-5, 0.0), (float("nan"), 0.0),
        (float("inf"), 0.0), (0, 0.0), ("45", 45.0), (12.5, 12.5),
        (True, 30.0), (False, 0.0),
    ],
)
def test_window_seconds_parses_config(raw, expected):
    assert vad_window.window_seconds({"vad_window_s": raw}) == expected


def test_window_seconds_default_when_missing():
    assert vad_window.window_seconds({}) == vad_window.DEFAULT_WINDOW_S == 30.0


def test_config_default_is_on():
    from core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["vad_window_s"] == 30


# ---- the wrapper ----------------------------------------------------------

def test_single_pass_misses_speech_after_music_windowed_finds_it():
    # 60 s of music, then 60 s of speech: the stuck state hides all of it.
    audio = _signal((MUSIC, 60.0), (SPEECH, 60.0))
    inner = LockingVad(lock_after=50)
    model = vad_window.WindowedVadModel(inner)

    single = model(audio)  # no window set: upstream single pass
    assert _speech_seconds(single, 60, 120) == 0.0

    with vad_window.windowed_vad(30):
        windowed = model(audio)
    assert windowed.shape == single.shape
    # every 30-s window from 60 s on starts fresh and is pure speech
    assert _speech_seconds(windowed, 60, 120) == pytest.approx(60.0, abs=0.1)
    assert _speech_seconds(windowed, 0, 60) == 0.0


def test_windows_cover_the_audio_in_whole_frames():
    audio = _signal((SPEECH, 95.3))
    inner = LockingVad()
    with vad_window.windowed_vad(30):
        out = vad_window.WindowedVadModel(inner)(audio)
    window = 30 * SR // FRAME * FRAME
    assert inner.calls[:-1] == [window] * (len(inner.calls) - 1)
    assert sum(inner.calls) == audio.shape[0]
    assert all(n % FRAME == 0 for n in inner.calls)
    assert out.shape[0] == audio.shape[0] // FRAME


def test_audio_shorter_than_a_window_is_one_untouched_call():
    audio = _signal((SPEECH, 10.0), (MUSIC, 10.0))
    inner = LockingVad()
    with vad_window.windowed_vad(30):
        out = vad_window.WindowedVadModel(inner)(audio)
    assert inner.calls == [audio.shape[0]]
    np.testing.assert_array_equal(out, LockingVad()(audio))


def test_zero_window_keeps_the_single_pass():
    audio = _signal((SPEECH, 70.0))
    inner = LockingVad()
    with vad_window.windowed_vad(0):
        vad_window.WindowedVadModel(inner)(audio)
    assert inner.calls == [audio.shape[0]]


def test_window_setting_is_scoped_to_the_context_and_thread():
    audio = _signal((SPEECH, 70.0))
    seen: list[int] = []

    def other_thread():
        inner = LockingVad()
        vad_window.WindowedVadModel(inner)(audio)
        seen.append(len(inner.calls))

    with vad_window.windowed_vad(30):
        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
    inner_after = LockingVad()
    vad_window.WindowedVadModel(inner_after)(audio)
    assert seen == [1]                 # another thread: single pass
    assert len(inner_after.calls) == 1  # after the context: single pass


def test_caller_array_is_not_written_by_the_model():
    class ZeroesItsInput(LockingVad):
        def __call__(self, audio, num_samples=512, context_size_samples=64):
            out = super().__call__(audio, num_samples, context_size_samples)
            audio[-64:] = 0  # what faster-whisper's model does to its input
            return out

    audio = _signal((SPEECH, 70.0))
    before = audio.copy()
    with vad_window.windowed_vad(30):
        vad_window.WindowedVadModel(ZeroesItsInput())(audio)
    np.testing.assert_array_equal(audio, before)


def test_faster_whisper_1_1_batch_shape_is_windowed():
    """1.1 calls model(audio.reshape(1, -1)) and gets (1, frames) back."""

    class BatchShaped:
        def __init__(self):
            self.inner = LockingVad(lock_after=50)

        def __call__(self, audio, num_samples=512, context_size_samples=64):
            assert audio.ndim == 2 and audio.shape[0] == 1
            return self.inner(audio[0], num_samples).reshape(1, -1)

    audio = _signal((MUSIC, 60.0), (SPEECH, 60.0)).reshape(1, -1)
    model = vad_window.WindowedVadModel(BatchShaped())
    single = model(audio)
    with vad_window.windowed_vad(30):
        windowed = model(audio)
    assert windowed.shape == single.shape == (1, audio.shape[1] // FRAME)
    assert _speech_seconds(single[0], 60, 120) == 0.0
    assert _speech_seconds(windowed[0], 60, 120) == pytest.approx(60.0, abs=0.1)


def test_faster_whisper_1_0_chunk_calls_pass_through_untouched():
    """1.0 calls model(chunk, state, context, sr) and get_initial_states()."""
    calls: list[tuple] = []

    class ChunkModel:
        def get_initial_states(self, batch_size):
            return ("state", batch_size)

        def __call__(self, x, state, context, sr):
            calls.append((x.shape, state, context, sr))
            return 0.9, state, context

    model = vad_window.WindowedVadModel(ChunkModel())
    chunk = np.zeros(512 * 2000, dtype=np.float32)  # longer than a window
    with vad_window.windowed_vad(30):
        assert model.get_initial_states(batch_size=1) == ("state", 1)
        assert model(chunk, "s", "c", 16000) == (0.9, "s", "c")
    assert calls == [(chunk.shape, "s", "c", 16000)]


# ---- through faster-whisper's own get_speech_timestamps ------------------

@pytest.fixture
def fw_vad():
    fw = pytest.importorskip("faster_whisper.vad")
    if not hasattr(fw, "get_speech_timestamps"):
        pytest.skip("faster_whisper.vad stub in this session")
    return fw


def test_install_wraps_faster_whisper_and_is_idempotent(fw_vad, monkeypatch):
    fake = LockingVad(lock_after=50)
    monkeypatch.setattr(fw_vad, "get_vad_model", lambda: fake)
    assert vad_window.install() is True
    wrapped = fw_vad.get_vad_model
    assert vad_window.install() is True
    assert fw_vad.get_vad_model is wrapped  # not wrapped twice
    assert isinstance(wrapped(), vad_window.WindowedVadModel)
    assert wrapped().inner is fake


def test_speech_timestamps_recovered_end_to_end(fw_vad, monkeypatch):
    fake = LockingVad(lock_after=50)
    monkeypatch.setattr(fw_vad, "get_vad_model", lambda: fake)
    vad_window.install()
    audio = _signal((MUSIC, 90.0), (SPEECH, 40.0), (MUSIC, 5.0))
    opts = fw_vad.VadOptions(min_silence_duration_ms=500)

    single = fw_vad.get_speech_timestamps(audio, opts)
    with vad_window.windowed_vad(30):
        windowed = fw_vad.get_speech_timestamps(audio, opts)

    assert single == []
    # one region covering the speech (90-130 s, plus padding), not cut at
    # the 120-s window edge
    assert len(windowed) == 1
    start_s, end_s = windowed[0]["start"] / SR, windowed[0]["end"] / SR
    assert 89.0 <= start_s <= 90.5 and 129.5 <= end_s <= 131.0


def test_install_refuses_a_faster_whisper_1_0_style_model(fw_vad, monkeypatch):
    class OldSilero:
        def __call__(self, x, state, context, sr: int):
            return x

    plain = lambda: OldSilero()  # noqa: E731 - stands in for the cached getter
    monkeypatch.setattr(fw_vad, "SileroVADModel", OldSilero)
    monkeypatch.setattr(fw_vad, "get_vad_model", plain)
    assert vad_window.install() is False
    assert fw_vad.get_vad_model is plain


def test_install_leaves_an_unexpected_faster_whisper_alone(fw_vad, monkeypatch):
    monkeypatch.delattr(fw_vad, "get_vad_model")
    assert vad_window.install() is False
    assert not hasattr(fw_vad, "get_vad_model")


def test_real_silero_model_unchanged_below_one_window(fw_vad):
    """With the real ONNX model, windowing changes nothing on short audio."""
    original = getattr(fw_vad.get_vad_model, "__wrapped__", fw_vad.get_vad_model)
    try:
        real = original()
    except Exception as e:  # noqa: BLE001 - onnxruntime missing in this env
        pytest.skip(f"Silero model unavailable: {e}")
    rng = np.random.default_rng(7)
    audio = (rng.standard_normal(20 * SR) * 0.1).astype(np.float32)
    audio = np.pad(audio, (0, (-audio.shape[0]) % FRAME))
    with vad_window.windowed_vad(30):
        windowed = vad_window.WindowedVadModel(real)(audio)
    np.testing.assert_array_equal(windowed, real(audio))
