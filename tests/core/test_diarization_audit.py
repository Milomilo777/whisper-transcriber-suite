import core.diarization as diar
from core.diarization import DiarSegment

# Audit Tests for core/diarization.py

def test_assign_speakers_to_segments_handles_missing_start_or_end():
    transcript = [{"text": "no times"}, {"start": 0.0, "text": "no end"}]
    diar_segments = [DiarSegment(start=0.0, end=1.0, speaker="Speaker 00")]
    diar.assign_speakers_to_segments(transcript, diar_segments)
    assert "speaker" not in transcript[0]
    # start defaults to 0.0, end defaults to start (0.0). e <= s, so it's skipped.
    assert "speaker" not in transcript[1]

def test_assign_speakers_to_segments_handles_bad_start_or_end_types():
    transcript = [{"start": "invalid", "end": 1.0, "text": "bad start"}]
    diar_segments = [DiarSegment(start=0.0, end=1.0, speaker="Speaker 00")]
    diar.assign_speakers_to_segments(transcript, diar_segments)
    assert "speaker" not in transcript[0]

def test_diarize_maps_sherpa_items_to_labelled_segments(monkeypatch, tmp_path):
    monkeypatch.setattr(diar, "availability_reason", lambda: "")
    import sys, types
    import numpy as np
    
    sherpa = types.ModuleType("sherpa_onnx")
    
    class FakeConfig:
        def validate(self): return True
    
    class FakeDiarization:
        def __init__(self, config): pass
        def process(self, samples, callback):
            class FakeResultItem:
                def __init__(self, start, end, speaker):
                    self.start = start; self.end = end; self.speaker = speaker
            class FakeResult:
                def sort_by_start_time(self):
                    return [FakeResultItem(1.0, 2.0, 1), FakeResultItem(0.0, 1.0, 0)]
            return FakeResult()
            
    sherpa.OfflineSpeakerDiarizationConfig = lambda **k: FakeConfig()
    sherpa.OfflineSpeakerSegmentationModelConfig = lambda **k: None
    sherpa.OfflineSpeakerSegmentationPyannoteModelConfig = lambda **k: None
    sherpa.SpeakerEmbeddingExtractorConfig = lambda **k: None
    sherpa.FastClusteringConfig = lambda **k: None
    sherpa.OfflineSpeakerDiarization = FakeDiarization
    
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    monkeypatch.setattr(diar, "_prepare_audio_16k_mono", lambda p: (np.array([0.0]*16000, dtype=np.float32), 16000))
    
    # The mapping runs in the worker process (issue #7), i.e. in _diarize_impl.
    res = diar._diarize_impl(str(tmp_path / "audio.wav"))
    assert len(res) == 2
    assert res[0].start == 1.0
    assert res[0].speaker == "Speaker 01"
    assert res[1].start == 0.0
    assert res[1].speaker == "Speaker 00"


def _fake_sherpa_rejecting_paths(monkeypatch, folder):
    """sherpa-onnx whose config.validate() says False (as 1.13 does on Windows for a model path
    with non-ASCII letters, though the files exist and load), models under ``folder``."""
    import sys, types
    import numpy as np

    sherpa = types.ModuleType("sherpa_onnx")

    class FakeConfig:
        def validate(self): return False

    class FakeDiarization:
        def __init__(self, config): pass
        def process(self, samples, callback):
            class Item:
                start, end, speaker = 0.0, 1.0, 0
            class Result:
                def sort_by_start_time(self): return [Item()]
            return Result()

    sherpa.OfflineSpeakerDiarizationConfig = lambda **k: FakeConfig()
    sherpa.OfflineSpeakerSegmentationModelConfig = lambda **k: None
    sherpa.OfflineSpeakerSegmentationPyannoteModelConfig = lambda **k: None
    sherpa.SpeakerEmbeddingExtractorConfig = lambda **k: None
    sherpa.FastClusteringConfig = lambda **k: None
    sherpa.OfflineSpeakerDiarization = FakeDiarization
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    monkeypatch.setattr(diar, "availability_reason", lambda: "")
    monkeypatch.setattr(diar, "_model_path", lambda f: str(folder / f))
    monkeypatch.setattr(diar, "_prepare_audio_16k_mono",
                        lambda p: (np.zeros(16000, dtype=np.float32), 16000))


def test_a_non_ascii_install_folder_still_identifies_speakers(monkeypatch, tmp_path):
    # A Portable copy unpacked under C:\Users\Şükrü\...: the files exist (availability_reason
    # checked them), so the narrow-char check of sherpa-onnx must not turn speakers off.
    folder = tmp_path / "\u015e\u00fckr\u00fc_\u0130\u011fd\u0131r" / "diarization"
    _fake_sherpa_rejecting_paths(monkeypatch, folder)
    res = diar._diarize_impl(str(tmp_path / "audio.wav"))
    assert [s.speaker for s in res] == ["Speaker 00"]


def test_an_ascii_folder_rejected_by_sherpa_still_reports_why(monkeypatch, tmp_path):
    import pytest
    folder = tmp_path / "plain" / "diarization"
    if not str(folder).isascii():
        pytest.skip("temp folder itself is not ASCII")
    _fake_sherpa_rejecting_paths(monkeypatch, folder)
    with pytest.raises(diar.DiarizationUnavailable, match="rejected the model paths"):
        diar._diarize_impl(str(tmp_path / "audio.wav"))
