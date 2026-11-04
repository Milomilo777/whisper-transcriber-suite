"""Automatic reports contain only registered, bounded, closed material."""
from __future__ import annotations

import hashlib
import errno
import importlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from core import failure_clue as clue, stats
from tests.core.test_cuda_decode_recovery import Engine, OOM, decode, segment

ROOT = Path(__file__).resolve().parents[2]
NEW_FIELDS = set("run_id fingerprint top_frame shape_hash last_stage progress_pct elapsed_bucket recovered "
                 "gpu_vendor vram_bucket compute_type diarization vad language_mode input_kind input_container "
                 "input_duration_bucket input_size_bucket disk_free_bucket ram_free_bucket session_error_bucket "
                 "repeat_bucket build_kind".split())


def valid_value(name, value):
    spec = clue.registry()["fields"][name]
    if not isinstance(value, str):
        return False
    if spec["type"] == "enum":
        return value in spec["values"]
    if spec["type"] == "integer":
        return bool(re.fullmatch(r"-?[0-9]{1,12}", value)) and (
            spec["min"] <= int(value) <= spec["max"] and int(value) % spec.get("step", 1) == 0)
    if spec["type"] == "hex":
        return bool(re.fullmatch("[0-9a-f]{" + str(spec["length"]) + "}", value))
    if spec["type"] == "pattern":
        if len(value) > spec["max_length"] or not re.fullmatch(spec["pattern"], value):
            return False
        if name == "top_frame":
            module, function, _ = value.split(":")
            return module in spec["modules"] and bool(re.fullmatch(spec["function_pattern"], function))
        return True
    raise AssertionError(spec)


def assert_closed(row):
    assert set(row) <= set(clue.registry()["fields"])
    assert all(valid_value(k, v) for k, v in row.items()), row
    assert len(row) <= 64
    assert len(urlencode(row).encode("ascii")) <= 8192


def test_registry_v2_and_generated_modules():
    registry = clue.registry()
    assert registry["version"] == 2
    assert NEW_FIELDS <= registry["fields"].keys()
    assert registry["fields"]["classifier_version"]["values"] == ["1", "2"]
    modules = set()
    for package in ("core", "app"):
        for file in (ROOT / package).rglob("*.py"):
            parts = list(file.relative_to(ROOT).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            modules.add(".".join(parts))
    assert registry["fields"]["top_frame"]["modules"] == sorted(modules)
    raw = (ROOT / "core/telemetry_registry.json").read_bytes()
    # The line ending depends on the checkout; a file must not mix them.
    assert b"\r\n" not in raw or b"\n" not in raw.replace(b"\r\n", b"")


def test_structural_frames_and_line_independent_fingerprint():
    # A code object's source location is required; spoofing __name__ is insufficient.
    def error(filename, line):
        scope = {"__name__": "private_user", "error": RuntimeError("invalid memory")}
        exec(compile("\n" * line + "def fail():\n    raise error\nfail()", filename, "exec"), scope)

    reports = []
    for line in (1, 80):
        try:
            error(str(ROOT / "core/transcriber.py"), line)
        except RuntimeError as exc:
            reports.append(clue.worker_clue(exc))
    assert reports[0]["top_frame"].startswith("core.transcriber:fail:")
    assert reports[0]["top_frame"] != reports[1]["top_frame"]
    assert reports[0]["fingerprint"] == reports[1]["fingerprint"]
    try:
        error("C:/private_user/core/transcriber.py", 1)
    except RuntimeError as exc:
        assert "top_frame" not in clue.worker_clue(exc)


@pytest.mark.parametrize("value,platform,code", [
    (0xC0000005, "win32", "native_access_violation"),
    (-1073741819, "win32", "native_access_violation"),
    (0xC0000135, "win32", "dll_not_found"), (0xC0000139, "win32", "dll_not_found"),
    (0xC000001D, "win32", "illegal_instruction"),
    (0xC00000FD, "win32", "stack_overflow"), (0xC0000409, "win32", "stack_overflow"),
    (-4, "linux", "illegal_instruction"), (-9, "linux", "killed_by_signal"),
    (-15, "darwin", "killed_by_signal"), (1, "linux", "worker_exit_unclassified"),
])
def test_native_exit_codes(monkeypatch, value, platform, code):
    monkeypatch.setattr(clue.sys, "platform", platform)
    row = clue.parent_clue("parent.worker_exit", exit_code=value)
    assert row["observed_code"] == code
    assert int(row["exit_code"]) == clue.normalise_exit_code(value, platform)


def test_stderr_frames_come_from_worker_and_parent_does_not_replace_them():
    from app.services.transcription_service import _remember_failure_clue

    lines = ["Traceback (most recent call last):",
             f'  File "{ROOT / "core/transcriber.py"}", line 123, in transcribe',
             '  File "C:/private/faster_whisper/transcribe.py", line 10, in generate_segments',
             "RuntimeError: CUDA failed with error out of memory"]
    row = clue.stderr_clue(lines)
    task = SimpleNamespace()
    _remember_failure_clue(task, {"device": "cuda"}, event=row,
                           site="parent.worker_exit", exit_code=1)
    assert task.failure_clue["top_frame"] == "core.transcriber:transcribe:123"
    assert task.failure_clue["observed_code"] == "cuda_out_of_memory"
    assert task.failure_clue["exception_family"] == "RuntimeError"
    assert_closed(task.failure_clue)


def test_new_closed_library_codes_require_observed_evidence():
    from tests.core.test_failure_clue import injected

    assert clue.observed_code(OSError(errno.ECONNRESET, "private endpoint")) == "network_reset"
    missing = injected("subprocess", "_execute_child", FileNotFoundError(errno.ENOENT, "missing", "ffprobe"))
    missing = injected("core.transcriber", "get_duration", missing)
    assert clue.observed_code(missing) == "ffmpeg_missing"
    media = injected("core.transcriber", "get_duration", FileNotFoundError(errno.ENOENT, "missing", "ffprobe"))
    assert clue.observed_code(media) == "file_not_found"
    tokenizer = injected("faster_whisper.tokenizer", "__init__", RuntimeError("Unable to load tokenizer"))
    assert clue.observed_code(tokenizer) == "tokenizer_error"
    loader = injected("core.transcriber", "_ensure_default_backend_loaded", RuntimeError("load failed"))
    assert clue.worker_clue(loader)["observed_code"] == "model_load_failed"
    unsupported = type("DecoderNotFoundError", (OSError,), {"__module__": "av.error"})
    assert clue.observed_code(unsupported("private codec")) == "codec_unsupported"
    assert clue.stderr_clue(["Invalid data found when processing input"])["observed_code"] == "corrupt_media"
    assert clue.stderr_clue([
        "Traceback (most recent call last):",
        '  File "C:/private/input.py", line 10, in process',
        "ConnectionResetError: private endpoint",
    ])["observed_code"] == "network_reset"


@pytest.mark.parametrize("literal", [
    r'C:\private\invalid memory\cuda error.mp4', '/home/private/invalid_memory/cuda_error.wav',
    'private/invalid memory/cuda error.mp4',
    'https://private.invalid/invalid/memory?title=cuda+error', 'cuda.error@memory.invalid',
    '<invalid.memory@cuda.error>', '<cuda@memory>',
    r'C:\private\cuda@error.invalid\invalid memory cuda error.mp4',
    '"invalid memory cuda error"', "'invalid memory cuda error'", 'invalid_memory_cuda_error.mp4',
    '"invalid memory cuda error video title"', '192.168.12.55', '+61 412 345 678',
    '123456789', '\u062e\u0635\u0648\u0635\u06cc',
])
def test_shape_hash_excludes_private_material_and_free_tokens(literal):
    baseline = clue.shape_hash("allocation failed")
    assert clue.shape_hash("allocation failed " + literal) == baseline
    tokens = "invalid memory cuda error allocation failed network reset disk full file model extra"
    # Even a message made entirely of allow-listed words is unsupported free text.
    assert clue.shape_hash(tokens) == hashlib.sha256(b"").hexdigest()[:12]
    assert clue.shape_hash("CUDA failed with error out of memory") == hashlib.sha256(
        b"cuda_out_of_memory").hexdigest()[:12]


def test_failure_context_and_unknowns(tmp_path, monkeypatch):
    import psutil

    media = tmp_path / "private.wav"
    media.write_bytes(b"audio")
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=2 * 1024**3))
    monkeypatch.setattr(clue.shutil, "disk_usage", lambda _: SimpleNamespace(free=5 * 1024**3))
    task = SimpleNamespace(file_path=str(media), run_id="0123456789abcdef", progress=37,
                           start_time=100, _input_duration=61, _failure_site="worker.segments",
                           task_settings={"diarization_enabled": True, "vad_filter": False},
                           language=None, source_download=None, _failure_compute_type="int8",
                           _telemetry_recovery="cuda_batch_reduced")
    monkeypatch.setattr(clue.time, "time", lambda: 121)
    row = clue.worker_clue(ValueError("private name"), task, device="cpu")
    expected = {"run_id": task.run_id, "last_stage": "transcribe", "progress_pct": "30",
                "elapsed_bucket": "lt1m", "recovered": "failed_after_recovery",
                "compute_type": "int8", "diarization": "true", "vad": "false",
                "language_mode": "auto", "input_kind": "file", "input_container": "wav",
                "input_duration_bucket": "lt10m", "input_size_bucket": "lt100mb",
                "ram_free_bucket": "lt4gb", "disk_free_bucket": "lt16gb"}
    assert expected.items() <= row.items()
    assert row["gpu_vendor"] == "unknown"  # CPU execution does not prove no GPU exists.
    assert row["vram_bucket"] == "unknown"
    assert_closed(row)
    unknown = clue.worker_clue(ValueError("x"))
    assert not {"input_size_bucket", "progress_pct", "elapsed_bucket"} & unknown.keys()


def test_unprintable_error_never_raises():
    class Unprintable(RuntimeError):
        def __str__(self):
            raise ValueError("no")

    assert clue.worker_clue(Unprintable())["exception_family"] == "RuntimeError"


def test_finished_recovery_survives_protocol_and_sanitiser(monkeypatch, capsys):
    from core import worker
    from core.task import TranscriptionTask

    task = TranscriptionTask("private.wav")
    task._telemetry_recovery = "cpu_fallback"
    task.run_id = "0123456789abcdef"
    worker._emit_done(task, task.file_path, "task")
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["recovered"] == "cpu_fallback"
    row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=1,
                                    transcription_time=1, status="finished", failure_clue=event)
    assert row["recovered"] == "cpu_fallback" and row["run_id"] == task.run_id
    assert "failure_site" not in row
    assert_closed(row)
    failed = clue.sanitise_clue({"recovered": "cpu_fallback"}, status="error")
    assert failed["recovered"] == "failed_after_recovery"


@pytest.mark.parametrize("recovery", ["cuda_batch_reduced", "cpu_fallback", "failed_after_recovery"])
def test_real_decode_recovery_state_reaches_automatic_row(decode, monkeypatch, capsys, recovery):
    from core import transcriber as tr, worker
    from core.task import TranscriptionTask

    audio, _, _ = decode
    engine = Engine([[segment(0, 2, "saved"), RuntimeError(OOM)], [segment(0, 1, "tail")]])
    monkeypatch.setattr(tr, "MODEL", engine)
    if recovery == "cuda_batch_reduced":
        monkeypatch.setattr(tr, "PIPELINE", engine)
    else:
        monkeypatch.setattr(tr, "compute_type", "int8_float16")
        cpu = Engine([[segment(0, 1, "tail")]] if recovery == "cpu_fallback" else [ValueError("decode failed")], "cpu", "int8")
        monkeypatch.setattr(tr, "WhisperModel", lambda *a, **k: cpu)
    task = TranscriptionTask(audio)
    if recovery == "failed_after_recovery":
        with pytest.raises(ValueError) as caught:
            tr.transcribe(task)
        event = clue.worker_clue(caught.value, task)
        status = "error"
    else:
        tr.transcribe(task)
        worker._emit_done(task, audio, "task")
        event = json.loads(capsys.readouterr().out.splitlines()[-1])
        status = "finished"
    row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=0,
                                    transcription_time=0, status=status, failure_clue=event)
    assert row["recovered"] == recovery
    assert row["run_id"] == task.run_id
    assert_closed(row)


def test_worker_records_progress_at_failure_and_random_run_id(monkeypatch, capsys):
    from core import worker
    from tests.core.test_worker_error_outputs import _run

    def fail(task, progress_cb, log_cb, **kwargs):
        clue.phase(task, "worker.segments")
        progress_cb(37)
        raise ValueError("private title")

    events = _run(monkeypatch, capsys, fail)
    error = next(event for event in events if event["event"] == "error")
    assert error["progress_pct"] == "30"
    assert re.fullmatch(r"[0-9a-f]{16}", error["run_id"])


def test_registry_failure_cannot_prevent_a_successful_job(monkeypatch, capsys):
    from tests.core.test_worker_error_outputs import _run

    def unavailable(*args, **kwargs):
        raise OSError("registry unavailable")

    def complete(task, *args, **kwargs):
        task.output_paths = ["kept.srt"]

    monkeypatch.setattr(clue, "sanitise_clue", unavailable)
    events = _run(monkeypatch, capsys, complete)
    done = [event for event in events if event["event"] == "done"]
    assert done and done[0]["outputs"] == ["kept.srt"]


def test_run_id_entropy_failure_does_not_break_task_creation(monkeypatch):
    import uuid
    from core.task import TranscriptionTask

    monkeypatch.setattr(uuid, "uuid4", lambda: (_ for _ in ()).throw(OSError("random unavailable")))
    task = TranscriptionTask("private.wav")
    assert task.run_id == "" and task.file_path == "private.wav"


def test_parent_context_does_not_probe_files_on_ui_thread(monkeypatch):
    monkeypatch.setattr(Path, "stat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("UI filesystem I/O")))
    task = SimpleNamespace(file_path="private.wav", start_time=None, progress=34)
    row = clue.context_clue(task, probe=False)
    assert row["progress_pct"] == 30 and row["input_container"] == "wav"
    assert "disk_free_bucket" not in row and "ram_free_bucket" not in row


def test_parent_uses_worker_run_context_for_native_exit(monkeypatch):
    from core.task import TranscriptionTask
    from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

    app = _app()
    service = _svc(app)
    task = TranscriptionTask("PrivateUnique.wav")
    task.status = "running"
    worker = {"id": 1, "token": "tok1", "ready": True, "task": task,
              "process": _Alive(), "device": "cuda", "last_event_at": 0}
    app.workers = [worker]
    service.finish_task = lambda *a, **k: None
    service._are_outputs_complete = lambda task: False
    service._engine_snapshot = lambda: {"spawn_backend": "faster_whisper", "model_name": "large-v3"}
    for run, stage in ((task.run_id, "vad"), ("0" * 16, "write")):
        app.worker_events.put({"event": "heartbeat", "_worker_id": 1, "_token": "tok1", "run_id": run,
                               "last_stage": stage, "compute_type": "int8", "input_duration_bucket": "lt1h",
                               "private_extra": "PrivateUnique"})
    app.worker_events.put({"event": "worker_exit", "_worker_id": 1, "_token": "tok1", "return_code": 1})
    service.poll()
    assert task.failure_clue["last_stage"] == "vad"
    posted = []
    monkeypatch.setattr(stats, "post_stats_async", lambda config, row: posted.append(row))
    monkeypatch.setattr(stats, "install_id_for", lambda config: "")
    service._post_usage_stats(task, 0, 0, worker, status="error")
    assert posted[0]["last_stage"] == "vad" and posted[0]["compute_type"] == "int8"
    assert posted[0]["input_duration_bucket"] == "lt1h"
    assert "PrivateUnique" not in json.dumps(posted[0]) and "top_frame" not in posted[0]
    assert_closed(posted[0])


def test_download_origin_is_kept_when_worker_only_knows_a_file(monkeypatch):
    from app.services.transcription_service import TranscriptionService
    from core.task import TranscriptionTask

    task = TranscriptionTask("private.wav")
    task.status = "error"
    task.source_download = SimpleNamespace()
    task.failure_clue = {"input_kind": "file"}
    service = TranscriptionService(SimpleNamespace(app_config={"telemetry_opt_in": True}))
    service._engine_snapshot = lambda: {"spawn_backend": "faster_whisper", "model_name": "large-v3"}
    posted = []
    monkeypatch.setattr(stats, "post_stats_async", lambda config, row: posted.append(row))
    monkeypatch.setattr(stats, "install_id_for", lambda config: "")
    service._post_usage_stats(task, 0, 0, status="error")
    assert posted[0]["input_kind"] == "download"


def test_post_gate_runs_limiter_off_thread_and_revalidates(monkeypatch, tmp_path):
    import threading
    from core import config

    monkeypatch.setattr(config, "config_path", lambda: str(tmp_path / "config.json"))
    calls = []
    ready = threading.Event()
    main = threading.get_ident()
    original = stats.limit_error_row

    def limit(*args, **kwargs):
        assert threading.get_ident() != main
        return original(*args, **kwargs)

    def sent(url, row, timeout):
        calls.append(row)
        ready.set()

    monkeypatch.setattr(stats, "limit_error_row", limit)
    monkeypatch.setattr(stats, "_post", sent)
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats",
           "install_id": "00000000-0000-4000-8000-000000000000"}
    row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=0,
                                    transcription_time=0, status="error")
    row["private_extra"] = "private title"
    assert stats.post_stats_async(cfg, row)
    assert ready.wait(5)
    assert len(calls) == 1 and calls[0]["session_error_bucket"] == "1"
    assert_closed(calls[0])


def test_rate_limit_persists_deduplicates_and_expires(tmp_path):
    path = tmp_path / "telemetry-errors.json"
    install = "00000000-0000-4000-8000-000000000000"

    def admit(fingerprint, now=1000):
        return stats.limit_error_row({"status": "error", "fingerprint": fingerprint},
                                     install, path=path, now=now)

    assert admit("000000000000")["repeat_bucket"] == "0"
    assert admit("000000000000") is None
    importlib.reload(stats)  # A new process must not reset the quota or duplicates.
    assert admit("000000000000") is None
    assert admit("000000000001")["repeat_bucket"] == "1-2"
    for i in (2, 3, 4):
        assert admit(f"{i:012x}") is not None
    assert admit("000000000005") is None
    assert admit("000000000000", 4601) is not None
    assert path.stat().st_size <= 16384
    assert install not in path.read_text()  # State stores a hash, not another copy of the id.


def test_rate_limit_corruption_and_io_failure_never_raise(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("not json")
    row = {"status": "error", "fingerprint": "0123456789ab"}
    assert stats.limit_error_row(row, "install", path=path, now=1000) is not None
    monkeypatch.setattr(Path, "replace", lambda *a: (_ for _ in ()).throw(OSError("full")))
    assert stats.limit_error_row(row, "other-install", path=path, now=1001) is None


def test_rate_limit_survives_real_process_restarts(tmp_path):
    path = tmp_path / "telemetry-errors.json"
    script = ("from pathlib import Path; import sys; from core.stats import limit_error_row; "
              "row={'status':'error','fingerprint':sys.argv[2]}; "
              "print('sent' if limit_error_row(row,'install',path=Path(sys.argv[1]),now=1000) else 'dropped')")
    for index in range(6):
        result = subprocess.run([sys.executable, "-c", script, str(path), f"{index:012x}"],
                                cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
        assert result.stdout.strip() == ("sent" if index < 5 else "dropped")
    assert len(json.loads(path.read_text())["sent"]) == 5


def test_new_rows_coarsen_memory_without_mutating_old_clue(monkeypatch):
    monkeypatch.setattr(stats.psutil, "virtual_memory", lambda: SimpleNamespace(total=17 * 1024**3 + 124))
    original = {"peak_mem_mb": "768"}
    row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=0,
                                    transcription_time=0, status="error", failure_clue=original)
    assert row["mem_total"] == str(16 * 1024**3)
    assert row["peak_mem_mb"] == "1024"
    assert original == {"peak_mem_mb": "768"}


def hostile_cases():
    values = [r'C:\Users\PrivateUnique\invalid memory.mp4', '/home/PrivateUnique/cuda.wav',
              'https://private.invalid/cuda', 'PrivateUnique@example.invalid', '192.168.22.101',
              '+61 412 345 678', 'PrivateUnique', '\u0645\u062a\u0646 \u062e\u0635\u0648\u0635\u06cc', 'X' * 10240,
              '"invalid memory cuda video title"']
    fields = list(clue.registry()["fields"])
    for value in values:
        for name in fields:
            yield name, value
    rng = random.Random(182)
    for _ in range(150):
        yield rng.choice(fields), ''.join(rng.choice('abc :/\\@123۴۵۶\u202e') for _ in range(80))


def check_hostile_payloads():
    for name, hostile in hostile_cases():
        failure = clue.worker_clue(RuntimeError(hostile))
        assert_closed(failure)
        assert hostile not in json.dumps(failure)
        row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=0,
                                        transcription_time=0, status="error",
                                        failure_clue={name: hostile, "private_extra": hostile})
        assert_closed(row)
        assert hostile not in json.dumps(row)


@pytest.fixture
def stable_host(monkeypatch):
    # Repeated privacy inputs need no repeated native OS/hardware probes.
    monkeypatch.setattr(stats, "public_model_name", lambda value: "large-v3")
    monkeypatch.setattr(stats, "region_country", lambda: "")
    monkeypatch.setattr(stats, "psutil", SimpleNamespace(cpu_count=lambda: 4,
                                                        virtual_memory=lambda: SimpleNamespace(total=16 * 1024**3)))
    for method, value in (("system", "Windows"), ("release", "10"), ("version", "10.0.12345"),
                          ("machine", "AMD64"), ("processor", "Intel")):
        monkeypatch.setattr(stats.platform, method, lambda value=value: value)
    monkeypatch.setattr(clue, "peak_memory_mb", lambda *args: 0)
    monkeypatch.setattr(clue, "_build_kind", lambda: "source")


def test_hostile_input_fuzz(stable_host):
    check_hostile_payloads()


def test_ablation_proves_hostile_fuzz_needs_sanitiser(monkeypatch, stable_host):
    monkeypatch.setattr(clue, "sanitise_clue", lambda value=None, **kwargs:
                        {str(k): str(v) for k, v in (value or {}).items()})
    with pytest.raises(AssertionError):
        check_hostile_payloads()


def test_integer_step_hex_pattern_cross_fields_and_caps():
    for value in (11, -10, 110, True, 1.2, "NaN", "10 private"):
        assert "progress_pct" not in clue.sanitise_clue({"progress_pct": value})
    for field, value in (("run_id", "x" * 16), ("fingerprint", "A" * 12),
                         ("top_frame", "private.module:run:2"),
                         ("top_frame", "core.transcriber:123name:2")):
        assert field not in clue.sanitise_clue({field: value})
    row = clue.sanitise_clue({"gpu_vendor": "none", "vram_bucket": "8_12gb",
                              **{f"private_{i}": "x" * 10000 for i in range(100)}})
    assert row["vram_bucket"] in ("none", "unknown")
    assert_closed(row)


def test_sanitiser_hard_caps_even_if_registry_grows(monkeypatch):
    fields = {f"field{i}": {"type": "enum", "values": ["value"]} for i in range(65)}
    monkeypatch.setattr(clue, "registry", lambda: {"fields": fields})
    assert clue.sanitise_clue(dict.fromkeys(fields, "value")) == {}
    fields = {f"field{i}": {"type": "pattern", "pattern": "^[ ]{256}$", "max_length": 256} for i in range(60)}
    assert clue.sanitise_clue(dict.fromkeys(fields, " " * 256)) == {}


def test_error_row_keys_are_exhaustively_registered():
    supplied = {k: (s["values"][0] if s["type"] == "enum" else "invalid")
                for k, s in clue.registry()["fields"].items()}
    row = stats.build_stats_payload(model="large-v3", language="en", audio_duration=0,
                                    transcription_time=0, status="error", failure_clue=supplied)
    assert_closed(row)


def test_registry_docs_contract():
    doc = (ROOT / "docs/CONFIG.md").read_text(encoding="utf-8")
    assert clue.registry()["fields"]["top_frame"]["function_pattern"] in doc
    assert "../core/telemetry_registry.json" in doc
    table = doc.split("| Failure clue field | Allowed values |", 1)[1].split("\n\n", 1)[0]
    rows = {name: re.findall(r"`([^`]+)`", text) for name, text in
            re.findall(r"\| `([^`]+)` \| ([^\n]+?) \|", table)}
    assert set(rows) == set(clue.registry()["fields"])
    for name, spec in clue.registry()["fields"].items():
        if spec["type"] == "enum":
            expected = spec["values"]
        elif spec["type"] == "integer":
            expected = [str(spec["min"]), str(spec["max"]), str(spec.get("step", 1))]
        elif spec["type"] == "hex":
            expected = [str(spec["length"])]
        else:
            expected = [spec["pattern"], str(spec["max_length"])]
        assert rows[name] == expected, name


def test_private_registry_byte_contract_when_copy_is_supplied():
    # The private counterpart is unavailable here. A supplied copy must stay
    # inside this worktree; never follow an environment path into another repo.
    supplied = os.environ.get("TELEMETRY_WORKER_REGISTRY_COPY")
    if not supplied:
        pytest.skip("No private registry copy supplied in this worktree")
    path = Path(supplied).resolve()
    assert path.is_relative_to(ROOT), "Supply the registry copy inside the worktree"
    assert path.read_bytes() == (ROOT / "core/telemetry_registry.json").read_bytes()


def test_hypothesis_valid_roundtrips_and_arbitrary_payloads():
    from hypothesis import given, settings, strategies as st

    fields = clue.registry()["fields"]

    @settings(max_examples=120, deadline=None, database=None)
    @given(st.sampled_from(list(fields)), st.text(max_size=200), st.integers())
    def arbitrary(name, text, integer):
        for value in (text, integer, None, True, [text], {text: integer}):
            assert_closed(clue.sanitise_clue({name: value, text: value}))

    @settings(max_examples=120, deadline=None, database=None)
    @given(st.sampled_from([(k, v) for k, s in fields.items() if s["type"] == "enum"
                           for v in s["values"]]), st.integers(0, 10))
    def valid(pair, progress):
        name, value = pair
        # Check fields independently so deliberately inconsistent pairs do not hide validation.
        row = clue.sanitise_clue({name: value, "progress_pct": progress * 10})
        assert row[name] == value
        assert row["progress_pct"] == str(progress * 10)
        assert_closed(row)

    arbitrary()
    valid()

    options = []
    for name, spec in fields.items():
        if spec["type"] == "enum":
            values = st.sampled_from(spec["values"])
        elif spec["type"] == "integer":
            step = spec.get("step", 1)
            values = st.integers(-(-spec["min"] // step), spec["max"] // step).map(lambda n, step=step: str(n * step))
        elif spec["type"] == "hex":
            values = st.text(alphabet="0123456789abcdef", min_size=spec["length"], max_size=spec["length"])
        elif name == "top_frame":
            values = st.integers(1, 999999).map(lambda n: f"core.transcriber:transcribe:{n}")
        else:
            values = st.from_regex(spec["pattern"], fullmatch=True)
        options.append(st.tuples(st.just(name), values))

    @settings(max_examples=200, deadline=None, database=None)
    @given(st.one_of(options))
    def all_types(pair):
        name, value = pair
        row = clue.sanitise_clue({name: value, "failure_site": "parent.worker_exit"}
                                 if name != "failure_site" else {name: value})
        assert row[name] == value
        assert_closed(row)

    all_types()
