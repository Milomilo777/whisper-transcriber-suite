import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave

import pytest

from engines import REGISTRY
from engines.engine_registry import EngineUnavailable
from engines import vosk_engine, sherpa_engine, whispercpp_engine


def test_vosk_keeps_finalized_segments_and_resets_each_call(monkeypatch, tmp_path):
    instances = []
    class Recognizer:
        def __init__(self, model, rate):
            self.chunks = 0
            instances.append(self)
            assert rate == 16000
        def AcceptWaveform(self, chunk):
            self.chunks += 1
            return self.chunks == 1
        def Result(self):
            return json.dumps({"text": "first segment"})
        def FinalResult(self):
            return json.dumps({"text": "last segment"})
    engine = vosk_engine.VoskEngine()
    engine.vosk = SimpleNamespace(KaldiRecognizer=Recognizer)
    engine.model = object()
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(struct.pack("<h", 1) * 8000)
    assert engine.transcribe(path) == "first segment last segment"
    assert engine.transcribe(path) == "first segment last segment"
    assert len(instances) == 2 and instances[0] is not instances[1]


def test_sherpa_int8_files_and_cpu_defaults_are_explicit(monkeypatch, tmp_path):
    model = tmp_path / "sherpa"
    model.mkdir()
    for filename in ("tiny-encoder.int8.onnx", "tiny-decoder.int8.onnx", "tiny-tokens.txt"):
        (model / filename).write_bytes(b"123")
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_whisper=factory)))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    engine = sherpa_engine.SherpaTiny()
    engine.model_dir = model
    engine.load(4)
    assert captured["encoder"].endswith("tiny-encoder.int8.onnx")
    assert captured["decoder"].endswith("tiny-decoder.int8.onnx")
    assert captured["tokens"].endswith("tiny-tokens.txt")
    assert {key: captured[key] for key in engine.settings} == {
        "num_threads": 4, "language": "fa", "task": "transcribe", "provider": "cpu",
        "decoding_method": "greedy_search", "sample_rate": 16000, "feature_dim": 80, "debug": False}
    assert engine.get_info()["model_size_mb"] == 9/(1024*1024)


def test_missing_models_are_unavailable_before_optional_imports(tmp_path, monkeypatch):
    for engine in (vosk_engine.VoskEngine(), sherpa_engine.SherpaBase()):
        engine.model_dir = tmp_path / "missing"
        with pytest.raises(EngineUnavailable, match="Missing"):
            engine.load(1)


def test_whisper_registry_retains_each_model_and_quant():
    for size in ("tiny", "base", "small"):
        for quant in ("q5_1", "q8_0"):
            name = f"whisper.cpp-{size}-{quant}"
            engine = REGISTRY[name]()
            assert engine.name == name
            assert engine.model_path.name == f"ggml-{size}-{quant}.bin"
    assert REGISTRY["whisper.cpp-large-v3-turbo-q5_0"]().model_path.name == "ggml-large-v3-turbo-q5_0.bin"


def test_whisper_cpu_greedy_flags_and_load_timing(monkeypatch, tmp_path):
    engine = REGISTRY["whisper.cpp-tiny-q5_1"]()
    engine.binary = Path("mock-cli")
    engine.threads = 4
    engine.model_path = tmp_path / "model.bin"
    engine.model_path.write_bytes(b"weights")
    command = engine.command("test.wav")
    for flag, value in (("-l", "fa"), ("-t", "4"), ("-bs", "1"), ("-bo", "1"), ("-tp", "0"), ("-tpi", "0")):
        assert command[command.index(flag) + 1] == value
    assert {"-nt", "-nf", "-ng"}.issubset(command)
    assert "--no-prints" not in command
    class Process:
        _handle = 0
        returncode = 0
        def __init__(self, args, **kwargs):
            assert args == command
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def communicate(self):
            return b"transcript\n", b"whisper_print_timings: load time = 25.00 ms\n"
    monkeypatch.setattr(whispercpp_engine.subprocess, "Popen", Process)
    monkeypatch.setattr(whispercpp_engine, "windows_peak_rss_mb", lambda handle: 12)
    assert engine.transcribe("test.wav") == "transcript"
    assert engine.last_timing == {"model_load_s": .025}
    info = engine.get_info()
    assert info["model_load_is_deferred"]
    assert info["model_size_mb"] == 7/(1024*1024)
    assert info["decoding_settings"]["strategy"] == "greedy"


def test_posix_rss_units_and_nested_cli_peak(monkeypatch):
    import runtime
    fake_resource = SimpleNamespace(RUSAGE_SELF=0, RUSAGE_CHILDREN=1,
                                    getrusage=lambda who: SimpleNamespace(ru_maxrss=4096 if who else 2048))
    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setattr(sys, "platform", "linux")
    assert runtime.peak_rss_mb()[0] == 4
    monkeypatch.setattr(sys, "platform", "darwin")
    assert runtime.peak_rss_mb()[0] == 4096/(1024*1024)
