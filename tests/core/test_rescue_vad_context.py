"""Rescue speech checks use the configured VAD window and sensitivity."""
from types import ModuleType, SimpleNamespace
import sys

import numpy as np
import pytest

from core import collapse_rescue as rescue, transcriber as tr, vad_window
from core.backends import nvidia_asr


@pytest.mark.parametrize("seconds,threshold", [
    (0, 0.5), (7.5, 0.5), (30, 0.5), (0, 0.75), (7.5, 0.75),
])
@pytest.mark.parametrize("failure", [False, True], ids=["success", "vad-error"])
def test_rescue_speech_check_uses_current_vad_settings(monkeypatch, seconds, threshold, failure):
    seen, model_calls, restored = [], [], []
    vad = ModuleType("faster_whisper.vad")

    class Model:
        def __call__(self, audio, num_samples=512, context_size_samples=64):
            model_calls.append(len(audio))
            return np.zeros((len(audio) + 511) // 512, dtype=np.float32)

    def speech(audio, options):
        seen.append((vad_window._WINDOW_S.get(), options.threshold))
        vad.get_vad_model()(audio)
        if failure:
            raise RuntimeError("Synthetic VAD failure")
        return [{"start": 0, "end": rescue.SAMPLE_RATE}]

    vad.SileroVADModel = Model
    vad.get_vad_model = lambda: Model()
    vad.get_speech_timestamps = speech
    vad.VadOptions = lambda **kwargs: SimpleNamespace(**kwargs, **(
        {} if "threshold" in kwargs else {"threshold": 0.5}))
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", vad)
    monkeypatch.setattr(sys.modules["faster_whisper"], "vad", vad, raising=False)
    monkeypatch.setattr(tr, "config", {"vad_window_s": seconds, "vad_threshold": threshold})
    monkeypatch.setattr(tr, "MODEL", object())
    monkeypatch.setattr(tr, "_LM_RUNNER", SimpleNamespace(slot=None))
    monkeypatch.setattr(tr, "mixed_language_pair", lambda task: None)
    monkeypatch.setattr(tr, "_whisper_runner", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(nvidia_asr, "_decode_window", lambda *a: np.zeros(90 * rescue.SAMPLE_RATE))
    monkeypatch.setattr(rescue, "find_suspect_spans", lambda *a: [object()])
    original = [{"start": 0.0, "end": 1.0, "text": "saved first reading"}]

    def run(segments, duration, speech_in, transcribe_piece, **kwargs):
        assert speech_in(0.0, 90.0) == [(0.0, 1.0)]
        restored.append(vad_window._WINDOW_S.get())
        return segments, SimpleNamespace(lines=lambda: [], rescued=[], kept=[])

    monkeypatch.setattr(rescue, "rescue", run)
    outer = 3.0 if failure else 0.0
    with vad_window.windowed_vad(outer):
        result = tr._rescue_collapsed(SimpleNamespace(cancelled=False, file_path="synthetic.wav"),
                                    original, "synthetic.wav", {}, False, "en", 90.0, None)
        assert vad_window._WINDOW_S.get() == outer
    assert result is original
    assert seen == [(seconds, threshold)]
    assert restored == ([] if failure else [0.0])
    assert vad_window._WINDOW_S.get() == 0.0
    assert sum(model_calls) == 90 * rescue.SAMPLE_RATE
    assert (len(model_calls) == 1) is (seconds == 0)
