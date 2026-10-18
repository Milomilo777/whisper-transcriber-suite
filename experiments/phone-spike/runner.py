"""One isolated engine/threads job. Stdout is a UTF-8 JSON-lines protocol."""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import statistics
import sys
import time

from engines import REGISTRY
from engines.engine_registry import EngineUnavailable
from runtime import audio_duration, peak_rss_mb


def emit(message):
    print(json.dumps(message, ensure_ascii=False, allow_nan=False), flush=True)


def timed_transcribe(engine, audio):
    started = time.perf_counter()
    with redirect_stdout(sys.stderr):
        hyp = engine.transcribe(audio)
    total = time.perf_counter() - started
    if not isinstance(hyp, str):
        raise TypeError("Engine hypothesis must be a string")
    load = engine.last_timing.get("model_load_s", 0.0)
    if not 0 <= load <= total:
        raise ValueError("Invalid model load timing")
    return {"hyp": hyp, "wall_s": total - load, "total_wall_s": total,
            "model_load_s": load}


def run_job(engine_name, threads, job):
    engine = None
    calls = 0
    try:
        for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[variable] = str(threads)
        if engine_name not in REGISTRY:
            raise EngineUnavailable(f"Unknown engine: {engine_name}")
        engine = REGISTRY[engine_name]()
        started = time.perf_counter()
        with redirect_stdout(sys.stderr):
            engine.load(threads)
            info = engine.get_info()
        load_s = time.perf_counter() - started
        emit({"status": "ready", "pid": os.getpid(), "load_s": load_s, "info": info})
        files = job["files"]
        if not files:
            raise ValueError("No WAV files")
        # Exactly one extra call, never a measured repetition or an output row.
        audio_duration(files[0])
        timed_transcribe(engine, files[0])
        calls += 1
        emit({"status": "warmup_complete", "audio": files[0], "calls": 1})
        for audio in files:
            try:
                audio_duration(audio)
                runs = []
                for _ in range(3):
                    run = timed_transcribe(engine, audio)
                    calls += 1
                    runs.append(run)
                median_run = sorted(runs, key=lambda item: item["wall_s"])[1]
                emit({"status": "file", "audio": audio, "hyp": median_run["hyp"],
                      "wall_s": median_run["wall_s"], "runs": runs,
                      "model_load_s": statistics.median(item["model_load_s"] for item in runs)})
            except Exception as error:
                emit({"status": "file", "audio": audio, "error": f"{type(error).__name__}: {error}"})
        rss, source = peak_rss_mb()
        # CLI engines also monitor their nested process on Windows.
        nested_rss = getattr(engine, "child_peak_rss_mb", None)
        if nested_rss is not None:
            rss = max(rss or 0.0, nested_rss)
            source += " (max runner and CLI child)"
        emit({"status": "done", "pid": os.getpid(), "peak_rss_mb": rss,
              "rss_source": source, "transcribe_calls": calls, "repeats": 3})
        return 0
    except Exception as error:
        unavailable = isinstance(error, (EngineUnavailable, ImportError))
        emit({"status": "UNAVAILABLE" if unavailable else "FAILED",
              "error": f"{type(error).__name__}: {error}", "pid": os.getpid()})
        return 2
    finally:
        if engine is not None:
            with redirect_stdout(sys.stderr):
                engine.unload()


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--threads", required=True, type=int)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    try:
        job = json.load(sys.stdin)
    except (ValueError, OSError) as error:
        emit({"status": "FAILED", "error": str(error)})
        return 2
    return run_job(args.engine, args.threads, job)


if __name__ == "__main__":
    raise SystemExit(main())
