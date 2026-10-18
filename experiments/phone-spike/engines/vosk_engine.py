from pathlib import Path
import os
import json
import wave
from .engine_registry import Engine, EngineUnavailable, register

ROOT = Path(os.path.relpath(Path(__file__).parent.parent))


@register("vosk-small-fa")
class VoskEngine(Engine):
    def __init__(self):
        super().__init__("vosk-small-fa")
        self.model_dir = ROOT / "models/vosk-model-small-fa-0.42"

    def load(self, threads):
        if not self.model_dir.is_dir():
            raise EngineUnavailable(f"Missing Vosk model: {self.model_dir}")
        import vosk
        self.vosk = vosk
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(str(self.model_dir))
        self.threads = threads

    def transcribe(self, audio_path):
        # A recognizer carries decoder state; never reuse it across files/repeats.
        recognizer = self.vosk.KaldiRecognizer(self.model, 16000)
        segments = []
        with wave.open(str(audio_path), "rb") as audio:
            while data := audio.readframes(4000):
                if recognizer.AcceptWaveform(data):
                    segments.append(json.loads(recognizer.Result()).get("text", ""))
        segments.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(part for part in segments if part).strip()

    def get_info(self):
        size = sum(path.stat().st_size for path in self.model_dir.rglob("*") if path.is_file())
        return {"model_size_mb": size / (1024 * 1024),
                "runtime_license": "Apache-2.0", "model_license": "unknown (verify model archive)",
                "android_binding": "[Vosk Android](https://github.com/alphacep/vosk-android-demo)",
                "integration_notes": "Recognizer API has no per-instance thread control; 1/4 are environment limits",
                "decoding_settings": {"sample_rate": 16000, "grammar": None,
                    "words": False, "partial_words": False, "max_alternatives": 0,
                    "chunk_frames": 4000, "recognizer": "new per call",
                    "other_defaults": "vosk==0.3.45 KaldiRecognizer defaults",
                    "requested_threads": self.threads, "decoder_threads": "runtime default"}}
