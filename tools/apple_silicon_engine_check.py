"""End-to-end check of the Apple-silicon (MLX) engine on a REAL M-series Mac.

Run by ``.github/workflows/apple-silicon-engine.yml`` on a GitHub arm64 macOS runner, or by hand
on any Apple-silicon Mac:

    python tools/apple_silicon_engine_check.py path/to/speech.wav [--model tiny] [--expect word ...]

It drives the app's own code, not MLX directly: the engine pick of ``load_config``, the model
download of ``core.model_manager.ensure_model``, and ``MlxWhisperBackend``. It fails (exit 1)
when the engine is not selected, nothing is transcribed, a segment or word time is wrong, the
expected words are missing, or ``torch`` got imported (mlx-whisper is installed with
``--no-deps``). It then prints the wall time next to faster-whisper (CPU, int8) on the same file.
The timing is information, never a gate.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import tempfile
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DEFAULT_EXPECT = ("quick", "brown", "fox", "lazy", "dog", "apple", "silicon", "engine")


def _fail(message: str) -> None:
    print(f"FAIL: {message}", flush=True)
    raise SystemExit(1)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


def _wav_seconds(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def check_mlx(audio: str, model: str, expect: tuple[str, ...], workdir: Path) -> dict:
    # A throwaway profile so the run never reads or writes a real config.json.
    os.environ["WTS_PROFILE_DIR"] = str(workdir / "profile")
    from core import config as cfgmod
    from core.backends import mlx_whisper_be as mlx
    from core.backends.availability import default_engine
    from core.model_manager import ensure_model

    if not mlx.is_apple_silicon():
        _fail(f"not an Apple-silicon Mac: {platform.system()} {platform.machine()}")
    if not mlx.package_importable():
        _fail(f"mlx_whisper does not import: {mlx.availability_reason()}")

    cfg = cfgmod.load_config(fetch_online=False)
    cfg["whisper_model"] = model
    cfg["hub_folder"] = str(workdir / "models")
    cfg["transcribe_backend"] = "faster_whisper"  # as a default install would load
    mlx.resolve_engine_choice(cfg)
    if cfg["transcribe_backend"] != "mlx_whisper":
        _fail(f"the engine was not auto-selected (backend={cfg['transcribe_backend']})")
    if default_engine(cfg) != "mlx_whisper":
        _fail("availability.default_engine disagrees with the config")
    if mlx.model_present(cfg):
        _fail("the model folder should be empty before the download")

    t0 = time.perf_counter()
    folder = ensure_model(cfg)  # the app's own download path, MLX branch
    download_s = time.perf_counter() - t0
    if not mlx.model_present(cfg):
        _fail(f"model not on disk after ensure_model ({folder})")

    backend = mlx.MlxWhisperBackend(config=cfg)
    t0 = time.perf_counter()
    if not backend.load():
        _fail(f"backend.load failed: {backend.get_error()}")
    load_s = time.perf_counter() - t0

    duration = _wav_seconds(audio)
    runs: list[float] = []
    segments: list[dict] = []
    info = None
    for _ in range(2):  # the 2nd run is the warm one
        t0 = time.perf_counter()
        segments, info = backend.transcribe_to_segments(
            audio, want_words=True, duration=duration, log_cb=print,
        )
        runs.append(time.perf_counter() - t0)

    text = " ".join(s["text"] for s in segments).strip()
    print(f"MLX text: {text!r}  language={info.language if info else ''}", flush=True)
    if not text:
        _fail("empty transcript")
    if not segments:
        _fail("no segments")
    last_end = 0.0
    for s in segments:
        if not (0.0 <= s["start"] < s["end"] <= duration + 1.0):
            _fail(f"bad segment times {s['start']}..{s['end']} for a {duration:.1f}s file")
        if s["start"] + 0.5 < last_end:
            _fail("segments overlap or run backwards")
        last_end = s["end"]
        if "words" not in s:
            _fail("segment without a words list")
    all_words = [w for s in segments for w in s["words"]]
    if not all_words:
        _fail("no word timestamps")
    prev = 0.0
    for w in all_words:
        if not (w["start"] <= w["end"] and w["start"] + 0.3 >= prev and w["word"].strip()):
            _fail(f"bad word entry {w}")
        prev = w["start"]
    found = sorted(_words(text) & set(expect))
    if len(found) < max(3, len(expect) // 2):
        _fail(f"expected words missing; found only {found} of {list(expect)}")
    if info is None or info.language != "en":
        _fail(f"language not detected as English: {info}")
    if "torch" in sys.modules:
        _fail("torch got imported; mlx-whisper must work with --no-deps")
    backend.unload()
    return {
        "text": text, "segments": len(segments), "words": len(all_words), "found": found,
        "download_s": round(download_s, 2), "load_s": round(load_s, 2),
        "cold_s": round(runs[0], 2), "warm_s": round(runs[1], 2), "audio_s": round(duration, 2),
    }


def time_faster_whisper(audio: str, model: str, workdir: Path) -> dict:
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    m = WhisperModel(model, device="cpu", compute_type="int8", download_root=str(workdir / "fw"))
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    segs, _info = m.transcribe(audio, word_timestamps=True)
    text = " ".join(s.text.strip() for s in segs).strip()
    run_s = time.perf_counter() - t0
    print(f"faster-whisper text: {text!r}", flush=True)
    return {"text": text, "load_s": round(load_s, 2), "run_s": round(run_s, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio")
    ap.add_argument("--model", default="tiny", help="catalog slug with an MLX twin (default tiny)")
    ap.add_argument("--expect", nargs="*", default=list(DEFAULT_EXPECT))
    args = ap.parse_args()
    if not Path(args.audio).is_file():
        _fail(f"audio file not found: {args.audio}")

    with tempfile.TemporaryDirectory(prefix="wts-mlx-") as tmp:
        work = Path(tmp)
        result = check_mlx(args.audio, args.model, tuple(args.expect), work)
        print("MLX engine: PASS", flush=True)
        try:
            fw = time_faster_whisper(args.audio, args.model, work)
        except Exception as e:  # noqa: BLE001 -- the comparison is information only
            fw = {"error": f"{type(e).__name__}: {e}"}
            print(f"faster-whisper comparison skipped: {fw['error']}", flush=True)

    summary = {"model": args.model, "mlx": result, "faster_whisper_cpu_int8": fw,
               "machine": f"{platform.system()} {platform.machine()} {platform.mac_ver()[0]}"}
    print(json.dumps(summary, indent=2), flush=True)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        lines = [
            f"### Apple-silicon engine, model `{args.model}` ({summary['machine']})",
            "",
            "| engine | load (s) | transcribe (s) | audio (s) |",
            "|---|---|---|---|",
            f"| MLX (cold first run) | {result['load_s']} | {result['cold_s']} | {result['audio_s']} |",
            f"| MLX (warm second run) | | {result['warm_s']} | {result['audio_s']} |",
        ]
        if "run_s" in fw:
            lines.append(f"| faster-whisper CPU int8 | {fw['load_s']} | {fw['run_s']} | {result['audio_s']} |")
        lines += ["", f"MLX text: `{result['text']}`", ""]
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
