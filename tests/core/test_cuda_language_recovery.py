"""Language checks cannot turn a recoverable CUDA runtime failure into a lost job."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import transcriber as tr
from core.task import TranscriptionTask
from tests.core.test_cuda_decode_recovery import Engine, decode, segment

APPLY_PRIOR = tr._apply_language_prior


@pytest.mark.parametrize("forced", [None, "fr"])
def test_language_stage_cuda_runtime_error_retries_on_cpu(decode, monkeypatch, forced):
    audio, written, _ = decode
    gpu = Engine([RuntimeError("CUDA error: an illegal memory access was encountered")])
    cpu = Engine([[segment(0, 2, "saved")]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "WhisperModel", lambda *a, **k: cpu)
    task = TranscriptionTask(audio)
    task.language = forced
    tr.transcribe(task)
    assert written[0][0]["text"] == "saved"
    assert tr.get_effective_device().device == "cpu"
    assert cpu.calls[0][1].get("language") == forced


@pytest.mark.parametrize("verification", [False, True])
def test_preflight_cuda_failure_moves_main_decode_to_cpu(decode, monkeypatch, verification):
    from core import history, language_prior

    audio, written, _ = decode

    class Detector(Engine):
        def detect_language(self, **kwargs):
            if not verification:
                raise RuntimeError("CUDA error: invalid device function")
            return "en", 0.9, [("en", 0.9), ("fr", 0.1)]

    gpu = Detector([[RuntimeError("CUDA error: device-side assert triggered")],
                    RuntimeError("CUDA error: device-side assert triggered")])
    cpu = Engine([[segment(0, 1, "verification")], [segment(0, 2, "saved")]], "cpu", "int8")
    cpu.detect_language = lambda **kwargs: ("en", 0.9, [("en", 0.9)])
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "WhisperModel", lambda *a, **k: cpu)
    monkeypatch.setattr(tr, "_apply_language_prior", APPLY_PRIOR)
    monkeypatch.setattr(tr, "_read_language_window", lambda *a, **k: [0.0] * 160)
    monkeypatch.setattr(history, "HistoryDB", lambda: SimpleNamespace(
        recent_finished_languages=lambda n: [], close=lambda: None))

    def prior(duration, plausible, detect, verify, **kwargs):
        detect(0, 1)
        if verification:
            list(verify(0, 1, "en"))
        else:
            cpu.scripts.pop(0)
        return language_prior.LanguageDecision(None, 0.0, "inconclusive", 1, {})

    monkeypatch.setattr(language_prior, "detect_with_prior", prior)
    tr.transcribe(TranscriptionTask(audio))
    assert tr.get_effective_device().device == "cpu"
    assert written[0][0]["text"] == "saved"
