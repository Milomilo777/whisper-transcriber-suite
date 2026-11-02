"""Hermetic lifetime, worker, and public-entry regressions for diarization."""
import gc
import os
import subprocess
import sys
import types
import weakref

import numpy as np
import pytest

from core import _checkpoint, diarization as diar
from core.backends.base import LanguageInfo
from core.task import TranscriptionTask
from core.transcriber import _run_post_pipeline as real_post
from tests.core.test_diarize_crash import fake_worker  # noqa: F401
from tests.core.test_loop_guard_transcriber import Engine, Info, Seg, _wire, _write_prior_checkpoint, t  # noqa: F401


def test_decode_uses_file_output_and_one_owned_array(monkeypatch):
    expected = np.linspace(-1, 1, 16000, dtype=np.float32)

    def decode(cmd, **kwargs):
        assert kwargs["stdout"] != subprocess.PIPE
        assert kwargs["timeout"] == 600
        assert kwargs["check"] is True
        kwargs["stdout"].write(expected.tobytes())
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(diar.subprocess, "run", decode)
    samples, rate = diar._prepare_audio_16k_mono("fake.wav")
    assert rate == 16000
    assert samples.flags.owndata and samples.base is None
    np.testing.assert_array_equal(samples, expected)


@pytest.mark.parametrize("failure,match", [
    (subprocess.TimeoutExpired("ffmpeg", 600), "timed out"),
    (subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad audio"), "bad audio"),
    (FileNotFoundError("ffmpeg"), "not available"),
])
def test_decode_failures_keep_documented_exception(monkeypatch, failure, match):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(diar.subprocess, "run", fail)
    with pytest.raises(diar.DiarizationUnavailable, match=match):
        diar._prepare_audio_16k_mono("bad.wav")


def test_worker_releases_samples_caps_threads_and_cleans_clusters(monkeypatch):
    refs = []
    configs = {}

    def audio(_path):
        samples = np.zeros(16000, dtype=np.float32)
        refs.append(weakref.ref(samples))
        return samples, 16000

    class Result:
        def sort_by_start_time(self):
            assert refs[0]() is None, "decoded audio must be freed before result conversion"
            return [types.SimpleNamespace(start=0, end=100, speaker=0),
                    types.SimpleNamespace(start=101, end=102, speaker=1)]

    class Native:
        def __init__(self, config):
            pass
        def process(self, samples, callback):
            callback(1, 2)
            return Result()

    def capture(kind):
        def config(**kwargs):
            configs[kind] = kwargs
            return types.SimpleNamespace(validate=lambda: True)
        return config

    sherpa = types.SimpleNamespace(
        OfflineSpeakerDiarizationConfig=capture("all"),
        OfflineSpeakerSegmentationModelConfig=capture("segmentation"),
        OfflineSpeakerSegmentationPyannoteModelConfig=capture("pyannote"),
        SpeakerEmbeddingExtractorConfig=capture("embedding"),
        FastClusteringConfig=capture("clustering"), OfflineSpeakerDiarization=Native,
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    monkeypatch.setattr(diar, "availability_reason", lambda: "")
    monkeypatch.setattr(diar, "_prepare_audio_16k_mono", audio)
    seen = []
    result = diar._diarize_impl("fake.wav", progress_cb=seen.append)
    assert seen == [0.5]
    assert {s.speaker for s in result} == {"Speaker 00"}
    assert configs["segmentation"]["num_threads"] == 2
    assert configs["embedding"]["num_threads"] == 2
    assert configs["clustering"] == {"num_clusters": -1, "threshold": 0.5}


def test_worker_environment_caps_threads_without_changing_parent(fake_worker, monkeypatch, tmp_path):
    echo = tmp_path / "threads.txt"
    monkeypatch.setenv("OMP_NUM_THREADS", "13")
    fake_worker(f"""
        names = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']
        open({str(echo)!r}, 'w').write(','.join(os.environ[n] for n in names))
        emit({{"event": "done", "segments": []}})
    """)
    assert diar.diarize("fake.wav") == []
    assert echo.read_text() == "2,2,2,2"
    assert os.environ["OMP_NUM_THREADS"] == "13"


def test_heartbeat_continues_after_worker_progress(fake_worker, monkeypatch):
    fake_worker("""
        emit({"event": "progress", "fraction": 0.5})
        time.sleep(0.65)
        emit({"event": "done", "segments": []})
    """)
    monkeypatch.setattr(diar, "SEGMENTATION_HEARTBEAT_S", 0.1)
    seen = []
    diar.diarize("fake.wav", progress_cb=seen.append)
    after_progress = seen[seen.index(0.5):]
    assert len(after_progress) >= 3
    assert after_progress == [0.5] * len(after_progress)


def test_heartbeat_does_not_mask_worker_stall(fake_worker, monkeypatch):
    fake_worker("""
        emit({"event": "progress", "fraction": 0.5})
        time.sleep(5)
    """)
    monkeypatch.setattr(diar, "SEGMENTATION_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(diar, "WORKER_STALL_TIMEOUT_S", 0.4)
    monkeypatch.setattr(diar, "WORKER_MIN_TIMEOUT_S", 1.5)
    monkeypatch.setattr("core.transcriber.get_duration", lambda p: 0)
    seen = []
    with pytest.raises(diar.DiarizationUnavailable, match="no progress"):
        diar.diarize("fake.wav", progress_cb=seen.append)
    assert len(seen) >= 2


class HoldingIterator:
    """An exhausted iterator can still own ASR state until it is deleted."""
    def __init__(self, model):
        self.model = model
        self.done = False
    def __iter__(self):
        return self
    def __next__(self):
        if self.done:
            raise StopIteration
        self.done = True
        return Seg(0, 600, "hello")
    def close(self):
        pass


class HoldingModel:
    def __init__(self):
        self.audio = np.zeros(16000, dtype=np.float32)
        self.model = types.SimpleNamespace()
    def transcribe(self, *args, **kwargs):
        info = Info()
        info.audio = self.audio
        return HoldingIterator(self), info


@pytest.mark.parametrize("mode", ["fresh", "resume", "complete", "language", "batched", "mixed"])
def test_whisper_released_before_diarization_and_completion_saved(t, monkeypatch, tmp_path, mode):
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"audio")
    if mode in {"resume", "complete"}:
        task = _write_prior_checkpoint(t, audio, [{"start": 0, "end": 1, "text": "prior"}], 1)
        if mode == "complete":
            data = _checkpoint.load_checkpoint(str(audio))
            data["transcription_completed"] = True
            import json
            _checkpoint.checkpoint_path(str(audio)).write_text(json.dumps(data), encoding="utf-8")
    else:
        task = TranscriptionTask(str(audio))
    _slices, written = _wire(t, monkeypatch, tmp_path, HoldingModel(), batched=mode == "batched")
    model_ref = weakref.ref(t.MODEL)
    audio_ref = weakref.ref(t.MODEL.audio)
    if mode == "language":
        slot = t._WhisperLanguageModel("fake/model", "fake")
        slot.model = t.MODEL
        # A second monkeypatch.setattr would retain the old model itself.
        t.MODEL = None
        monkeypatch.setattr(t._LM_RUNNER, "slot", slot, raising=False)
        monkeypatch.setitem(t._LM_SLOT, "backend", slot)
        monkeypatch.setitem(t._LM_SLOT, "model_id", "fake/model")
    if mode == "mixed":
        task.languages = ("en", "fa")
    monkeypatch.setitem(t.config, "diarization_enabled", True)
    monkeypatch.setitem(t.config, "alignment", "none")
    monkeypatch.setitem(t.config, "auto_chapters_enabled", False)
    monkeypatch.setitem(t.config, "hallucination_detect_enabled", False)
    monkeypatch.setattr(t, "_run_post_pipeline", real_post)
    monkeypatch.setattr(diar, "is_available", lambda: True)
    # The collapsed-window rescue decodes audio with ffmpeg; keep the test independent of it
    # (a failure there would be kept alive by pytest's captured traceback).
    monkeypatch.setattr("core.backends.nvidia_asr._decode_window",
                        lambda *a, **k: np.zeros(0, dtype=np.float32))
    seen = []

    def diarize(*args, progress_cb, **kwargs):
        gc.collect()
        assert model_ref() is None and audio_ref() is None
        assert t.MODEL is None and t.PIPELINE is None and t.MODEL_READY
        saved = _checkpoint.load_checkpoint(str(audio))
        assert saved and saved["transcription_completed"]
        assert max(seen, default=0) <= 85
        for fraction in [0, 0.5, 0.1, 1]:
            progress_cb(fraction)
        return []

    monkeypatch.setattr(diar, "diarize", diarize)

    def on_progress(percent):
        if percent == 100:
            assert written and _checkpoint.load_checkpoint(str(audio)) is None
        seen.append(percent)

    if mode in {"resume", "complete"}:
        assert t.resume_transcription(task, on_progress)
    else:
        t.transcribe(task, on_progress)
    assert seen == sorted(seen)
    assert seen[-5:] == [85, 92, 92, 99, 100]
    assert task.speaker_labels_failed is False


def test_alternate_backend_uses_same_slices(t, monkeypatch, tmp_path):
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"audio")
    _slices, written = _wire(t, monkeypatch, tmp_path, Engine())
    monkeypatch.setitem(t.config, "diarization_enabled", True)
    seen = []

    class Backend:
        def transcribe_to_segments(self, *args, progress_cb, **kwargs):
            for percent in [100, 50, 100]:
                progress_cb(percent)
            return [{"start": 0, "end": 600, "text": "hello"}], LanguageInfo("en", 0.9)

    def post(task, segs, lang, log_cb, progress_cb):
        assert seen == [85, 85, 85]
        for fraction in [0, 0.5, 0.1, 1]:
            progress_cb(fraction)
        return 0

    monkeypatch.setattr(t, "_run_post_pipeline", post)
    t._transcribe_via_alt_backend("whisper_cpp", TranscriptionTask(str(audio)), seen.append,
                                  None, None, backend=Backend())
    assert written
    assert seen == [85, 85, 85, 85, 92, 92, 99, 100]
