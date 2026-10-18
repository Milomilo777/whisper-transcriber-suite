from pathlib import Path
import os
import wave
from .engine_registry import Engine, EngineUnavailable, register

ROOT = Path(os.path.relpath(Path(__file__).parent.parent))


class SherpaEngineBase(Engine):
    def __init__(self, name, model_name):
        super().__init__(name)
        self.model_name = model_name
        self.model_dir = ROOT / f"models/sherpa-onnx-whisper-{model_name}"

    def load(self, threads):
        encoder = self.model_dir / f"{self.model_name}-encoder.int8.onnx"
        decoder = self.model_dir / f"{self.model_name}-decoder.int8.onnx"
        tokens = self.model_dir / f"{self.model_name}-tokens.txt"
        if not tokens.exists():
            tokens = self.model_dir / "tokens.txt"
        for path in (encoder, decoder, tokens):
            if not path.is_file():
                raise EngineUnavailable(f"Missing sherpa-onnx model file: {path}")
        import sherpa_onnx
        import numpy
        self.numpy = numpy
        self.settings = {"num_threads": threads, "language": "fa", "task": "transcribe",
                         "provider": "cpu", "decoding_method": "greedy_search",
                         "sample_rate": 16000, "feature_dim": 80, "debug": False}
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(encoder), decoder=str(decoder), tokens=str(tokens), **self.settings)
        self.model_files = (encoder, decoder, tokens)

    def transcribe(self, audio_path):
        stream = self.recognizer.create_stream()
        with wave.open(str(audio_path), "rb") as audio:
            frames = audio.readframes(audio.getnframes())
        samples = self.numpy.frombuffer(frames, dtype="<i2").astype(self.numpy.float32) / 32768.0
        stream.accept_waveform(16000, samples)
        self.recognizer.decode_stream(stream)
        return stream.result.text

    def get_info(self):
        return {"model_size_mb": sum(p.stat().st_size for p in self.model_files) / (1024 * 1024),
                "runtime_license": "Apache-2.0", "model_license": "MIT (Whisper; verify export licence)",
                "android_binding": "[sherpa-onnx Android](https://github.com/k2-fsa/sherpa-onnx/tree/master/android)",
                "integration_notes": "ARM export/runtime and packaging require device validation",
                "decoding_settings": dict(self.settings,
                    other_defaults="sherpa-onnx==1.10.45 from_whisper defaults")}


@register("sherpa-whisper-tiny")
class SherpaTiny(SherpaEngineBase):
    def __init__(self):
        super().__init__("sherpa-whisper-tiny", "tiny")


@register("sherpa-whisper-base")
class SherpaBase(SherpaEngineBase):
    def __init__(self):
        super().__init__("sherpa-whisper-base", "base")
