"""Offline ASR benchmark controller. No optional engine imports or network IO."""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

from metrics import cer_edits, normalize_fa, repeated_ngrams, wer_edits, word_error_counts
from runtime import audio_duration, environment_info, write_json

RUNNER = Path(os.path.relpath(Path(__file__).with_name("runner.py")))
SCORE_KEYS = ("wer", "cer", "wer_edits", "wer_words", "cer_edits", "cer_chars",
              "wer_zwnj_space", "wer_zwnj_edits", "wer_zwnj_words")


def read_refs(path):
    if path is None:
        return None
    refs = {}
    with open(path, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if not {"id", "duration_s", "reference"}.issubset(reader.fieldnames or ()):
            raise ValueError("Refs TSV requires id, duration_s, reference columns")
        for row in reader:
            key = row["id"]
            if not key or key in refs:
                raise ValueError(f"Empty or duplicate reference id: {key}")
            refs[key] = row["reference"]
    return refs


def score_file(result, ref, long_form=False):
    result["ref"] = ref
    w, words = wer_edits(ref, result["hyp"])
    c, chars = cer_edits(ref, result["hyp"])
    z, zwords = wer_edits(ref, result["hyp"], zwnj_to_space=True)
    result.update(wer=w / words, cer=c / chars, wer_edits=w, wer_words=words,
                  cer_edits=c, cer_chars=chars, wer_zwnj_space=z / zwords,
                  wer_zwnj_edits=z, wer_zwnj_words=zwords)
    if long_form:
        counts = word_error_counts(ref, result["hyp"])
        result.update(word_deletions=counts["deletions"], word_insertions=counts["insertions"],
                      word_substitutions=counts["substitutions"],
                      ref_repeated_ngrams=repeated_ngrams(ref))


def check_sanity(run):
    short = [v for key, v in run["files"].items() if key != "long_form" and "hyp" in v]
    hyps = [normalize_fa(item["hyp"]) for item in short]
    if not hyps or not any(hyps):
        return "All hypotheses were empty"
    if len(hyps) > 1 and len(set(hyps)) == 1:
        return "All hypotheses were identical"
    return None


def run_engine(engine, threads, files, durations, refs, timeout):
    run = {"files": {}, "info": None, "failed": False, "status": "OK"}
    command = [sys.executable] + (["-S"] if sys.flags.no_site else [])
    command += [str(RUNNER), "--engine", engine, "--threads", str(threads)]
    errors = []
    try:
        proc = subprocess.run(command, input=json.dumps({"files": [str(p) for p in files]}),
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout)
        output, stderr = proc.stdout, proc.stderr
        if proc.returncode:
            errors.append(f"Runner exit code {proc.returncode}")
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        errors.append(f"Runner timed out after {timeout:g} seconds")
    except OSError as error:
        output, stderr = "", ""
        errors.append(str(error))
    ready = done = False
    by_path = {str(p): p for p in files}
    for line in output.splitlines():
        try:
            msg = json.loads(line)
            status = msg.get("status")
            if status == "ready":
                ready = True
                run.update(info=msg["info"], load_s=msg["load_s"], pid=msg["pid"])
            elif status == "warmup_complete":
                run["warmup"] = {"audio": msg["audio"], "calls": msg["calls"]}
            elif status == "file":
                path = by_path[msg["audio"]]
                result = {key: value for key, value in msg.items() if key not in ("status", "audio")}
                result["audio_s"] = durations[path.stem]
                if "error" in result:
                    errors.append(f"{path.name}: {result['error']}")
                else:
                    result["rtf"] = result["wall_s"] / result["audio_s"]
                    if path.stem == "long_form":
                        result["repeated_ngrams"] = repeated_ngrams(result["hyp"])
                        result["ngram_size"] = 3
                    if refs is not None:
                        try:
                            score_file(result, refs[path.stem], path.stem == "long_form")
                        except ValueError as error:
                            result["error"] = str(error)
                            errors.append(f"{path.name}: {error}")
                run["files"][path.stem] = result
            elif status == "done":
                done = True
                run.update({key: value for key, value in msg.items() if key != "status"})
            elif "error" in msg:
                errors.append(msg["error"])
                run["status"] = status
            else:
                errors.append(f"Unexpected runner message: {line}")
        except (ValueError, TypeError, KeyError) as error:
            errors.append(f"Invalid runner response: {error}")
    if not ready or not done:
        errors.append("Runner did not complete the ready/done protocol")
    for path in files:
        if path.stem not in run["files"]:
            run["files"][path.stem] = {"audio_s": durations[path.stem],
                                      "error": errors[0] if errors else "Runner omitted file"}
    if not errors:
        sanity = check_sanity(run)
        if sanity:
            errors.append(sanity)
    for result in run["files"].values():
        result["peak_rss_mb"] = run.get("peak_rss_mb")
    if (run.get("info") or {}).get("model_load_is_deferred"):
        run["setup_s"] = run.pop("load_s", None)
        loads = [v["model_load_s"] for v in run["files"].values() if "model_load_s" in v]
        run["load_s"] = statistics.median(loads) if loads else None
    if errors:
        run["failed"] = True
        if run["status"] != "UNAVAILABLE":
            run["status"] = "FAILED"
        run["error"] = "; ".join(errors)
        # A5: keep evidence/hypotheses and timing, but never publish failed scores.
        for result in run["files"].values():
            for key in SCORE_KEYS:
                result.pop(key, None)
    if stderr.strip():
        run["stderr"] = stderr.strip()
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--refs")
    parser.add_argument("--engines", required=True, help="Comma-separated registry names")
    parser.add_argument("--threads", default="1,4")
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=float, default=3600, help="Seconds per engine/thread job")
    args = parser.parse_args()
    try:
        engines = list(dict.fromkeys(name.strip() for name in args.engines.split(",") if name.strip()))
        threads = list(dict.fromkeys(int(item) for item in args.threads.split(",")))
        if not engines or not threads or min(threads) < 1 or args.timeout <= 0:
            raise ValueError("Engines, positive threads and positive timeout are required")
        files = sorted(Path(args.audio_dir).glob("*.wav"))
        if not files:
            raise ValueError("No WAV files found")
        durations = {path.stem: audio_duration(path) for path in files}
        refs = read_refs(args.refs)
        if refs is not None:
            missing = [p.stem for p in files if p.stem not in refs]
            if missing:
                raise ValueError("Missing reference ids: " + ", ".join(missing))
    except (OSError, ValueError, EOFError) as error:
        parser.error(str(error))
    results = {"env": environment_info()}
    write_json(args.out, results)
    for engine in engines:
        results[engine] = {}
        for thread_count in threads:
            results[engine][str(thread_count)] = run_engine(
                engine, thread_count, files, durations, refs, args.timeout)
            # Persist each completed job before any success/progress notification.
            write_json(args.out, results)
    print(f"Saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
