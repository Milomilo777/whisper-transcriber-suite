"""Deterministic fixtures; these do not measure ASR quality or speed."""
from pathlib import Path
import wave
from .engine_registry import Engine, register


@register("fake")
class FakeEngine(Engine):
    mode = "distinct"

    def __init__(self):
        super().__init__("fake")
        self.calls = 0

    def load(self, threads):
        self.threads = threads
        if self.mode == "fail":
            raise RuntimeError("Intentional fake load failure")

    def transcribe(self, audio_path):
        self.calls += 1
        with wave.open(str(audio_path), "rb") as audio:
            if not audio.readframes(1):
                raise ValueError("Fake engine received empty WAV")
        if self.mode == "empty":
            return ""
        if self.mode == "identical":
            return "constant hypothesis"
        return "fake " + Path(audio_path).stem

    def get_info(self):
        return {"model_size_mb": 0.0, "runtime_license": "test fixture",
                "model_license": "test fixture", "android_binding": "unknown",
                "integration_notes": "Synthetic fixture; never a phone candidate",
                "decoding_settings": {"mode": self.mode, "threads": self.threads}}


@register("fake-empty")
class EmptyEngine(FakeEngine):
    mode = "empty"


@register("fake-identical")
class IdenticalEngine(FakeEngine):
    mode = "identical"


@register("fake-fail")
class FailedEngine(FakeEngine):
    mode = "fail"
