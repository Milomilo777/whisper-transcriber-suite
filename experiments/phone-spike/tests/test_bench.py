import csv
import io
import json
import os
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import wave

import pytest

import bench
import runner
from engines import REGISTRY
from engines.engine_registry import Engine
from runtime import audio_duration, environment_info, peak_rss_mb
from summarize import build_summary

SPIKE = Path(os.path.relpath(Path(__file__).parent.parent))


def write_wav(path, frames=1600, channels=1, rate=16000):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(struct.pack("<h", 123) * frames * channels)


@pytest.fixture
def audio_fixture(tmp_path):
    audio = tmp_path / "audio with spaces"
    audio.mkdir()
    write_wav(audio / "one clip.wav", 1600)
    write_wav(audio / "دو.wav", 3200)
    refs = tmp_path / "refs.tsv"
    with refs.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t")
        writer.writerow(["id", "duration_s", "reference"])
        writer.writerow(["one clip", .1, "fake one clip"])
        writer.writerow(["دو", .2, "fake دو"])
    return audio, refs


def invoke_bench(audio, output, engines="fake", refs=None, threads="1,4"):
    command = [sys.executable, "-S", str(SPIKE / "bench.py"), "--audio-dir", str(audio),
               "--engines", engines, "--threads", threads, "--out", str(output), "--timeout", "30"]
    if refs is not None:
        command += ["--refs", str(refs)]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_bench_runner_two_wavs_end_to_end_with_failures(audio_fixture, tmp_path):
    audio, refs = audio_fixture
    output = tmp_path / "nested/results.json"
    complete = invoke_bench(audio, output, "fake-fail,fake,fake-empty,fake-identical,no-such-engine", refs)
    assert complete.returncode == 0, complete.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert set(data) == {"env", "fake-fail", "fake", "fake-empty", "fake-identical", "no-such-engine"}
    assert data["env"]["nproc"] == os.cpu_count()
    assert data["env"]["measurement"]["repeats"] == 3
    pids = []
    for threads in ("1", "4"):
        run = data["fake"][threads]
        assert run["status"] == "OK" and not run["failed"]
        assert run["pid"] != os.getpid()
        pids.append(run["pid"])
        assert run["info"]["decoding_settings"] == {"mode": "distinct", "threads": int(threads)}
        assert run["load_s"] >= 0
        assert run["info"]["model_size_mb"] == 0
        assert run["peak_rss_mb"] > 0
        assert run["rss_source"]
        assert run["warmup"] == {"audio": str(audio / "one clip.wav"), "calls": 1}
        assert run["transcribe_calls"] == 7
        assert run["repeats"] == 3
        assert set(run["files"]) == {"one clip", "دو"}
        for key, seconds in (("one clip", .1), ("دو", .2)):
            item = run["files"][key]
            assert item["hyp"] == item["ref"] == "fake " + key
            assert item["audio_s"] == seconds
            assert len(item["runs"]) == 3
            assert item["wall_s"] == statistics.median(r["wall_s"] for r in item["runs"])
            assert item["rtf"] == item["wall_s"] / seconds
            assert item["wer"] == item["cer"] == item["wer_zwnj_space"] == 0
            assert item["wer_edits"] == item["cer_edits"] == 0
            assert item["wer_words"] == (3 if key == "one clip" else 2)
            assert item["peak_rss_mb"] == run["peak_rss_mb"]
        for name, error in (("fake-fail", "Intentional fake load failure"),
                            ("fake-empty", "All hypotheses were empty"),
                            ("fake-identical", "All hypotheses were identical"),
                            ("no-such-engine", "Unknown engine")):
            failed = data[name][threads]
            assert failed["failed"]
            assert error in failed["error"]
            assert failed["status"] == ("UNAVAILABLE" if name == "no-such-engine" else "FAILED")
            assert set(failed["files"]) == {"one clip", "دو"}
            assert all("wer" not in item and "wer_edits" not in item and "cer" not in item
                       for item in failed["files"].values())
            if name in ("fake-empty", "fake-identical"):
                assert all("hyp" in item for item in failed["files"].values())
    assert pids[0] != pids[1]
    summary = build_summary(data)
    assert "fake-fail" in summary and "Intentional fake load failure" in summary
    assert "All hypotheses were identical" in summary
    assert "ref: fake دو; hyp: fake دو" in summary


def test_no_refs_keeps_hypotheses_speed_and_unknown_accuracy(audio_fixture, tmp_path):
    audio, _ = audio_fixture
    output = tmp_path / "private.json"
    result = invoke_bench(audio, output, threads="1")
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    run = data["fake"]["1"]
    assert not run["failed"]
    for item in run["files"].values():
        assert item["hyp"] and item["rtf"] >= 0
        assert not set(bench.SCORE_KEYS) & item.keys()
        assert "ref" not in item
    assert "Accuracy unknown: no scored references" in build_summary(data)


def test_runner_warmup_is_one_extra_call_and_median_selects_matching_hypothesis(monkeypatch, capsys):
    class ScriptedEngine(Engine):
        def __init__(self):
            super().__init__("scripted")
        def load(self, threads):
            pass
    engine = ScriptedEngine()
    monkeypatch.setitem(REGISTRY, "scripted", lambda: engine)
    calls = []
    times = iter([99, 9, 1, 5, 4, 8, 2])  # warmup; two deliberately unsorted triples
    def transcribe(instance, audio):
        calls.append(audio)
        value = next(times)
        return {"hyp": f"hyp {value}", "wall_s": value, "model_load_s": 0}
    monkeypatch.setattr(runner, "timed_transcribe", transcribe)
    monkeypatch.setattr(runner, "audio_duration", lambda path: 1)
    monkeypatch.setattr(runner, "peak_rss_mb", lambda: (7, "fixture RSS"))
    assert runner.run_job("scripted", 1, {"files": ["a.wav", "b.wav"]}) == 0
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    files = [message for message in messages if message["status"] == "file"]
    assert calls == ["a.wav"] * 4 + ["b.wav"] * 3
    assert [(v["hyp"], v["wall_s"]) for v in files] == [("hyp 5", 5), ("hyp 4", 4)]
    assert [len(v["runs"]) for v in files] == [3, 3]
    assert messages[-1]["status"] == "done"
    assert messages[-1]["transcribe_calls"] == 7
    assert messages[-1]["peak_rss_mb"] == 7


def test_model_load_time_is_separate_from_timed_wall(monkeypatch):
    class TimedEngine(Engine):
        def transcribe(self, path):
            self.last_timing = {"model_load_s": 3}
            return "hypothesis"
    values = iter([10, 18])
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(values))
    value = runner.timed_transcribe(TimedEngine("fixture"), "fake.wav")
    assert value == {"hyp": "hypothesis", "total_wall_s": 8, "wall_s": 5, "model_load_s": 3}


def test_runner_optional_dependency_is_unavailable(monkeypatch, capsys):
    class Missing(Engine):
        def load(self, threads):
            raise ModuleNotFoundError("fixture optional dependency missing")
    monkeypatch.setitem(REGISTRY, "missing", lambda: Missing("missing"))
    assert runner.run_job("missing", 1, {"files": []}) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "UNAVAILABLE"
    assert "fixture optional dependency missing" in response["error"]


def test_engine_stdout_logs_do_not_corrupt_protocol(monkeypatch, capsys):
    class LoggingEngine(Engine):
        def load(self, threads):
            print("loading engine")
        def transcribe(self, path):
            print("decoder log")
            return "hyp " + path
    monkeypatch.setitem(REGISTRY, "logging", lambda: LoggingEngine("logging"))
    monkeypatch.setattr(runner, "audio_duration", lambda path: 1)
    monkeypatch.setattr(runner, "peak_rss_mb", lambda: (1, "fixture"))
    assert runner.run_job("logging", 1, {"files": ["a.wav", "b.wav"]}) == 0
    captured = capsys.readouterr()
    messages = [json.loads(line) for line in captured.out.splitlines()]
    assert messages[0]["status"] == "ready" and messages[-1]["status"] == "done"
    assert "loading engine" in captured.err and captured.err.count("decoder log") == 7


def test_python_run_all_wrapper_produces_both_files_with_fake(audio_fixture, tmp_path):
    audio, refs = audio_fixture
    output = tmp_path / "all-results"
    result = subprocess.run([sys.executable, "-S", str(SPIKE / "run_all.py"),
                             "--audio-dir", str(audio), "--refs", str(refs),
                             "--engines", "fake", "--threads", "1", "--out-dir", str(output)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    data = json.loads((output / "fleurs-fa.json").read_text(encoding="utf-8"))
    assert not data["fake"]["1"]["failed"]
    assert (output / "SUMMARY.md").read_text(encoding="utf-8") == build_summary(data)


def test_imports_do_not_require_optional_packages():
    code = ("import builtins; original=builtins.__import__; "
            "exec('def blocked(name, *a, **kw):\\n"
            " if name.split(\\\".\\\")[0] in {\\\"vosk\\\",\\\"sherpa_onnx\\\",\\\"numpy\\\",\\\"scipy\\\",\\\"datasets\\\",\\\"soundfile\\\",\\\"librosa\\\"}: raise ImportError(name)\\n"
            " return original(name,*a,**kw)'); "
            "builtins.__import__=blocked; import bench,runner,summarize,engines,download_data,test_deps")
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=SPIKE,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_child_crash_preserves_completed_file_and_records_omitted_files(monkeypatch):
    output = "\n".join(json.dumps(item) for item in [
        {"status": "ready", "pid": 123, "load_s": .2, "info": {}},
        {"status": "file", "audio": "a.wav", "hyp": "completed", "wall_s": .1}])
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 9, output, "crash stderr"))
    result = bench.run_engine("fake", 1, [Path("a.wav"), Path("b.wav")], {"a": 1, "b": 2}, None, 10)
    assert result["failed"]
    assert "exit code 9" in result["error"]
    assert result["files"]["a"]["hyp"] == "completed"
    assert result["files"]["b"]["error"]
    assert result["stderr"] == "crash stderr"


def test_timeout_is_recorded(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 2, output=b"", stderr=b"stuck engine")
    monkeypatch.setattr(bench.subprocess, "run", timeout)
    result = bench.run_engine("fake", 1, [Path("a.wav")], {"a": 1}, None, 2)
    assert result["failed"] and "timed out after 2 seconds" in result["error"]
    assert result["files"]["a"]["error"]
    assert result["stderr"] == "stuck engine"


def test_long_form_scoring_counts_repeats_and_deletions():
    item = {"hyp": "a b c a b c a b c"}
    bench.score_file(item, "a b c a b c a b c d", long_form=True)
    assert item["wer_edits"] == item["word_deletions"] == 1
    assert item["wer_words"] == 10
    assert item["wer"] == .1
    assert item["word_insertions"] == item["word_substitutions"] == 0


@pytest.mark.parametrize("channels,rate,frames", [(2, 16000, 10), (1, 8000, 10), (1, 16000, 0)])
def test_invalid_wav_is_rejected(tmp_path, channels, rate, frames):
    path = tmp_path / "invalid.wav"
    write_wav(path, frames, channels, rate)
    with pytest.raises(ValueError):
        audio_duration(path)


def test_platform_memory_and_environment():
    rss, source = peak_rss_mb()
    assert rss > 0 and source
    env = environment_info()
    assert env["nproc"] == os.cpu_count()
    assert env["architecture"]
    if sys.platform == "win32":
        assert "Windows" in source
        assert env["ram_mb"] > 0
        assert env["governor"] == "unknown"
