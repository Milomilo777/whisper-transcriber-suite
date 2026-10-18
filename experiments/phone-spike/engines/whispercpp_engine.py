"""CLI adapter: record and subtract the CLI's reported model-load time.

The CLI reloads on every call. This is explicitly not a resident-model benchmark;
see README before comparing it with resident Vosk or sherpa-onnx runners.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import threading
from .engine_registry import Engine, EngineUnavailable, register
from runtime import windows_peak_rss_mb

ROOT = Path(os.path.relpath(Path(__file__).parent.parent))


def find_binary(name):
    suffix = ".exe" if sys.platform == "win32" else ""
    aliases = (name, "main" if name == "whisper-cli" else "quantize")
    for folder in ("build/bin/Release", "build/bin", "Release", "."):
        for alias in aliases:
            path = ROOT / "build/whisper.cpp" / folder / (alias + suffix)
            if path.is_file():
                return path
    raise EngineUnavailable(f"Missing whisper.cpp {name}; run setup.py --build explicitly")


class WhisperCppEngine(Engine):
    def __init__(self, name, model_name, quant):
        super().__init__(name)
        self.model_path = ROOT / "models" / f"ggml-{model_name}-{quant}.bin"
        self.child_peak_rss_mb = None

    def load(self, threads):
        self.threads = threads
        self.binary = find_binary("whisper-cli")
        if not self.model_path.is_file():
            raise EngineUnavailable(f"Missing whisper.cpp model: {self.model_path}")

    def command(self, audio_path):
        return [str(self.binary), "-m", str(self.model_path), "-f", str(audio_path),
                "-l", "fa", "-t", str(self.threads), "-nt", "-mc", "0",
                "-bs", "1", "-bo", "1", "-tp", "0", "-tpi", "0", "-nf", "-ng"]

    def transcribe(self, audio_path):
        stop = threading.Event()
        with subprocess.Popen(self.command(audio_path), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as process:
            def monitor():
                while not stop.is_set():
                    try:
                        rss = windows_peak_rss_mb(process._handle)
                        self.child_peak_rss_mb = max(self.child_peak_rss_mb or 0.0, rss)
                    except OSError:
                        pass
                    stop.wait(0.01)
            monitor_thread = None
            if sys.platform == "win32":
                monitor_thread = threading.Thread(target=monitor, daemon=True)
                monitor_thread.start()
            try:
                stdout, stderr = process.communicate()
            finally:
                stop.set()
                if monitor_thread:
                    monitor_thread.join()
        text = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            raise RuntimeError(f"whisper.cpp exit {process.returncode}: {text.strip()}")
        load = re.search(r"load time\s*=\s*([0-9.]+)\s*ms", text)
        if not load:
            raise RuntimeError("whisper.cpp did not report model load time; refusing misleading RTF")
        self.last_timing = {"model_load_s": float(load.group(1)) / 1000}
        return stdout.decode("utf-8", errors="replace").strip()

    def get_info(self):
        return {"model_size_mb": self.model_path.stat().st_size / (1024 * 1024),
                "runtime_license": "MIT", "model_license": "MIT (Whisper)",
                "model_load_is_deferred": True,
                "timing_notes": "CLI reload per repetition; reported load time subtracted; other process overhead remains",
                "android_binding": "[whisper.cpp Android](https://github.com/ggerganov/whisper.cpp/tree/master/examples/whisper.android)",
                "integration_notes": "CLI process peak; Android NDK/JNI and resident timing unverified",
                "decoding_settings": {"release": "v1.7.1", "language": "fa", "threads": self.threads,
                    "strategy": "greedy", "beam_size": 1, "best_of": 1, "temperature": 0,
                    "temperature_increment": 0, "temperature_fallback": False,
                    "timestamps": False, "max_context": 0, "gpu": False,
                    "argv_template": self.command("{audio}"),
                    "other_defaults": "whisper.cpp v1.7.1 CLI defaults"}}


def _register_models():
    for model in ("tiny", "base", "small", "large-v3-turbo"):
        quants = ("q5_0",) if model == "large-v3-turbo" else ("q5_1", "q8_0")
        for quant in quants:
            name = f"whisper.cpp-{model}-{quant}"
            # Bind defaults now so each registry entry retains its own model.
            def factory(name=name, model=model, quant=quant):
                return WhisperCppEngine(name, model, quant)
            register(name)(factory)


_register_models()
