"""Regression checks for the automatic clue's closed-vocabulary boundary."""
from __future__ import annotations

import errno
import hashlib
import io
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

from core import failure_clue as clue, stats
from tests.core.test_stderr_recovery_regressions import start_reader
from tests.core.test_telemetry_v2 import assert_closed
from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

ROOT = Path(__file__).resolve().parents[2]
EMPTY_HASH = hashlib.sha256(b"").hexdigest()[:12]
HEADER = "Traceback (most recent call last):"
LIBRARY_FRAME = '  File "C:/libs/faster_whisper/transcribe.py", line 15, in generate_segments'


@pytest.mark.parametrize("message,baseline", [
    ("Cannot open user's file 'memory model audio device'", "Cannot open user's file ''"),
    ("Failed to decode stream Memory Model Audio Device", "Failed to decode stream "),
    ("failed on my memory folder/secret_file", "failed on my  folder/secret_file"),
])
def test_confirmed_private_titles_have_the_empty_shape(message, baseline):
    assert clue.shape_hash(message) == clue.shape_hash(baseline) == EMPTY_HASH


@pytest.mark.parametrize("placement", ["quoted", "unquoted", "apostrophe", "relative_path"])
def test_allowlisted_title_property(placement):
    from hypothesis import given, settings, strategies as st
    from core.diagnostic_vocab import VOCABULARY

    def message(title):
        return {
            "quoted": f"Cannot open file '{title}'",
            "unquoted": f"Failed to decode stream {title}",
            "apostrophe": f"Cannot open user's file '{title}'",
            "relative_path": f"failed on my {title} folder/secret_file",
        }[placement]

    @settings(max_examples=100, deadline=None, database=None, derandomize=True)
    @given(st.lists(st.sampled_from(sorted(VOCABULARY)), min_size=1, max_size=20))
    def invariant(words):
        assert clue.shape_hash(message(" ".join(words))) == clue.shape_hash(message(""))

    invariant()


def test_closed_shapes_ignore_template_parameters_and_reject_extra_text():
    first = "Unable to allocate 2 GiB for an array with shape (20, 4) and data type float32"
    second = "Unable to allocate 512 MiB for an array with shape (1, 8) and data type float64"
    assert clue.shape_hash(first) == clue.shape_hash(second) != EMPTY_HASH
    for message in (first + " memory model", "memory model " + first,
                    "std::bad_alloc\x00memory", "std::bad_alloc\nprivate",
                    "invalid memory cuda error allocation failed network reset disk full file model extra",
                    "CUDA failed with error out of memory" + " " * 32768):
        assert clue.shape_hash(message) == EMPTY_HASH


@pytest.mark.parametrize("code,messages", [
    ("ct2_bad_alloc", ["std::bad_alloc", "bad allocation"]),
    ("cuda_out_of_memory", ["CUDA failed with error out of memory"]),
    ("cublas_missing", ["Library cublas64_12.dll is not found or cannot be loaded",
                        "Library libcublas.so.11 is not found or cannot be loaded"]),
    ("cudnn_missing", ["Library cudnn64_9.dll is not found or cannot be loaded",
                       "Library libcudnn_ops.so.8 is not found or cannot be loaded"]),
    ("tokenizer_error", ["Error while loading tokenizer", "Unable to load tokenizer",
                         "Tokenizer vocabulary is invalid"]),
])
def test_closed_shapes_hash_only_the_template_id(code, messages):
    expected = hashlib.sha256(code.encode("ascii")).hexdigest()[:12]
    for message in messages:
        assert clue.shape_hash(message) == expected != EMPTY_HASH
        for suffix in (" memory model audio device", "\u200b", "\x00", "\n"):
            assert clue.shape_hash(message + suffix) == EMPTY_HASH


@pytest.mark.parametrize("lines", [
    ["MemoryError: std::bad_alloc"],
    ['File "/fake/faster_whisper/transcribe.py"', "MemoryError: std::bad_alloc"],
    [LIBRARY_FRAME, "MemoryError: std::bad_alloc"],
    ["ConnectionResetError: private endpoint"],
    [HEADER, "MemoryError: std::bad_alloc"],
    [HEADER, LIBRARY_FRAME, "unrelated log", "MemoryError: std::bad_alloc"],
    [HEADER, LIBRARY_FRAME, "RuntimeError: CUDA failed with error out of memory", "later log"],
    [HEADER, LIBRARY_FRAME, "x" * 2049, "MemoryError: std::bad_alloc"],
])
def test_stderr_requires_a_complete_terminal_traceback(lines):
    row = clue.stderr_clue(lines)
    assert row["observed_code"] == "none"
    assert row["exception_family"] == "other"
    assert "top_frame" not in row and "shape_hash" not in row
    assert_closed(row)


def test_stderr_accepts_real_frames_source_and_caret_at_tail_end():
    row = clue.stderr_clue([
        "earlier unrelated log", HEADER,
        f'  File "{ROOT / "core/transcriber.py"}", line 123, in transcribe',
        "    generate_segments(audio)", "    ~~~~~~~~~~~~~~~~~^^^^^^^",
        LIBRARY_FRAME, "    raise RuntimeError(message)",
        "RuntimeError: CUDA failed with error out of memory",
    ])
    assert row["exception_family"] == "RuntimeError"
    assert row["observed_code"] == "cuda_out_of_memory"
    assert row["top_frame"] == "core.transcriber:transcribe:123"
    assert_closed(row)


def test_stderr_accepts_a_python_formatted_traceback(tmp_path):
    path = tmp_path / "faster_whisper" / "transcribe.py"
    path.parent.mkdir()
    source = 'def generate_segments():\n    raise RuntimeError("std::bad_alloc")\n'
    path.write_text(source, encoding="utf-8")
    scope = {}
    exec(compile(source, str(path), "exec"), scope)
    try:
        scope["generate_segments"]()
    except RuntimeError as exc:
        # Format the library frame, without the test harness's outer frame.
        lines = "".join(traceback.format_exception(exc.with_traceback(exc.__traceback__.tb_next))).splitlines()
    else:
        raise AssertionError("The test function did not fail")
    row = clue.stderr_clue(lines)
    assert row["exception_family"] == "RuntimeError" and row["observed_code"] == "ct2_bad_alloc"


@pytest.mark.parametrize("native", [
    ["terminate called after throwing an instance of 'std::bad_alloc'", "  what():  std::bad_alloc"],
    ["Invalid data found when processing input"],
    ["Decoder (h264) not found"],
    ["Encoder (aac) not found"],
])
def test_stderr_native_patterns_are_exact_and_terminal(native):
    assert clue.stderr_clue(native)["observed_code"] != "none"
    for lines in ([*native, "later log"], [*native[:-1], native[-1] + " private title"],
                  [*native[:-1], "private title " + native[-1]]):
        assert clue.stderr_clue(lines)["observed_code"] == "none"


@pytest.mark.parametrize("code", [1, 0xC0000005, 0xC0000409, 0xC000001D, -1073741819])
@pytest.mark.parametrize("synthesised", [False, True])
@pytest.mark.parametrize("stderr", [[], ["private log\n"]])
def test_real_exit_code_survives_stderr_defaults_and_reaches_stats(monkeypatch, code, synthesised, stderr):
    monkeypatch.setattr(clue.sys, "platform", "win32")
    monkeypatch.setattr(clue, "peak_memory_mb", lambda pid=None: 0)
    task = SimpleNamespace(status="running", recovery_note="", error_reason="")
    if synthesised:
        app = _app()
        service = _svc(app)
        worker = {"id": 1, "token": "tok1", "ready": True, "task": task,
                  "process": SimpleNamespace(pid=4242, poll=lambda: code), "device": "cpu",
                  "last_event_at": 0, "dead_since": 1, "stderr_clue": clue.stderr_clue(stderr)}
        app.workers = [worker]
        service._expire_dead_workers(100)
    else:
        worker, events = start_reader(monkeypatch, stderr, return_code=code)
        app = _app(workers=[worker])
        service = _svc(app)
        worker.update(task=task, ready=True, device="cpu", last_event_at=0)
        worker["process"] = _Alive()
        for event in events:
            app.worker_events.put(event)
    service.finish_task = lambda *args, **kwargs: None
    service._are_outputs_complete = lambda task: False
    service.poll()
    assert task.status == "error"
    assert task.failure_clue["exit_code"] == str(clue.normalise_exit_code(code, "win32"))
    row = stats.build_stats_payload(model="base", language="en", audio_duration=0,
                                    transcription_time=0, status="error", failure_clue=task.failure_clue)
    assert row["exit_code"] == task.failure_clue["exit_code"]


@pytest.mark.parametrize("message", [
    "Permission denied", "Zugriff verweigert",
    "\u062f\u0633\u062a\u0631\u0633\u06cc \u0631\u062f \u0634\u062f",
    "std::bad_alloc",
])
@pytest.mark.parametrize("number", [None, errno.EACCES])
def test_os_error_grouping_ignores_localised_text(monkeypatch, message, number):
    monkeypatch.setattr(clue, "context_clue", lambda *a, **kw: {})
    monkeypatch.setattr(clue, "peak_memory_mb", lambda *a: 0)
    exc = PermissionError(message) if number is None else PermissionError(number, message, "private.wav")
    origin = PermissionError("") if number is None else PermissionError(number, "", "another.wav")
    row = clue.worker_clue(exc)
    baseline = clue.worker_clue(origin)
    assert row["shape_hash"] == baseline["shape_hash"] == EMPTY_HASH
    assert row["fingerprint"] == baseline["fingerprint"]
    assert row["exception_family"] == "PermissionError" and row["os_error"] == str(number or 0)
    assert_closed(row)


def test_os_error_fingerprint_retains_numeric_error_evidence(monkeypatch):
    monkeypatch.setattr(clue, "context_clue", lambda *a, **kw: {})
    monkeypatch.setattr(clue, "peak_memory_mb", lambda *a: 0)
    assert clue.worker_clue(OSError(errno.EIO, ""))["fingerprint"] != clue.worker_clue(
        OSError(errno.EINVAL, ""))["fingerprint"]


@pytest.mark.parametrize("raw", [
    b"Error in C:\\Users\\\xb2\xe2\xca\xd4\\model.bin\xff\xfe\n",
    b"Error in C:\\Users\\Andr\xe9\\memory model.wav\n",
    (HEADER + "\n" + LIBRARY_FRAME + "\nMemoryError: std::bad_alloc").encode(),
    b"MemoryError: invalid mem",
])
def test_worker_tail_handles_hostile_bytes_and_partial_lines(monkeypatch, raw):
    from app.services import transcription_service as ts
    from core import _threads

    app = _app()
    service = ts.TranscriptionService(app)

    def popen(*args, **kwargs):
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding=kwargs["encoding"], errors=kwargs["errors"])
        return SimpleNamespace(pid=4242, stdout=stream, wait=lambda: 1)

    monkeypatch.setattr(ts.subprocess, "Popen", popen)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kw: target())
    monkeypatch.setattr(service, "_engine_snapshot", lambda: {})
    service.start_worker()
    events = []
    while not app.worker_events.empty():
        events.append(app.worker_events.get_nowait())
    exited = next(event for event in events if event["event"] == "worker_exit")
    row = clue.parent_clue("parent.worker_exit", exit_code=exited["return_code"], event=exited)
    assert row["exception_family"] == "other" and row["observed_code"] == "worker_exit_unclassified"
    assert "shape_hash" not in row and "top_frame" not in row
    assert_closed(row)


@pytest.mark.parametrize("code,expected", [
    (0xC0000005, "native_access_violation"), (0xC0000409, "stack_overflow"),
    (0xC000001D, "illegal_instruction"),
])
def test_empty_stderr_retains_native_exit_evidence(monkeypatch, code, expected):
    monkeypatch.setattr(clue.sys, "platform", "win32")
    row = clue.parent_clue("parent.worker_exit", exit_code=code, event=clue.stderr_clue([]))
    assert row["exit_code"] == str(code) and row["observed_code"] == expected
    assert_closed(row)


@pytest.mark.parametrize("supplied", [None, [], "bad", {}])
def test_missing_or_corrupt_clue_only_defaults_an_existing_error_row(monkeypatch, supplied):
    def no_post(*args, **kwargs):
        raise AssertionError("Building or sanitising a clue must not send anything")

    monkeypatch.setattr(stats, "_post", no_post)
    clean = clue.sanitise_clue(supplied)
    assert clean == clue.sanitise_clue()
    assert set(clean) == clue.LEGACY_FIELDS
    for status in ("error", "finished", "cancelled"):
        row = stats.build_stats_payload(model="base", language="en", audio_duration=0,
                                        transcription_time=0, status=status, failure_clue=supplied)
        assert row["status"] == status
        if status == "error":
            assert row["failure_site"] == "other" and row["observed_code"] == "none"
        else:
            assert not (clue.LEGACY_FIELDS - {"classifier_version"}).intersection(row)
        assert_closed(row)


def test_real_peak_memory_producers_supply_integer_buckets(monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "Process", lambda pid=None: SimpleNamespace(
        memory_info=lambda: SimpleNamespace(peak_pagefile=512 * 1024**2)))
    monkeypatch.setattr(clue, "context_clue", lambda *a, **kw: {})
    assert type(clue.peak_memory_mb()) is int
    assert type(clue.log_memory_bucket(clue.peak_memory_mb())) is int
    for row in (clue.worker_clue(RuntimeError()), clue.parent_clue("parent.watchdog", pid=42)):
        assert row["peak_mem_mb"] == "512"
        payload = stats.build_stats_payload(model="base", language="en", audio_duration=0,
                                            transcription_time=0, status="error", failure_clue=row)
        assert payload["peak_mem_mb"] == "512"
    # A float in a corrupted record is outside the integer registry contract.
    assert clue.sanitise_clue({"peak_mem_mb": 512.0})["peak_mem_mb"] == "0"
