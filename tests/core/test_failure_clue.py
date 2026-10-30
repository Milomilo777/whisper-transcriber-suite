"""The clue is closed, observable, additive and never needed for job completion."""
from __future__ import annotations

import errno
import json
import random
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import failure_clue as clue
from core import stats

ROOT = Path(__file__).resolve().parents[2]


def injected(module: str, function: str, exc: BaseException) -> BaseException:
    scope = {"__name__": module, "exc": exc}
    exec(f"def {function}():\n    raise exc\n", scope)  # fixed function names from this test
    try:
        scope[function]()
    except BaseException as caught:
        return caught
    raise AssertionError("fault did not fire")


@pytest.mark.parametrize("module,function,site", [
    ("faster_whisper.audio", "decode_audio", "worker.decode"),
    ("faster_whisper.vad", "get_speech_timestamps", "worker.vad"),
    ("core.mel_blocks", "extract", "worker.features"),
    ("faster_whisper.transcribe", "detect_language", "worker.language"),
    ("faster_whisper.transcribe", "generate_segments", "worker.segments"),
    ("core.loop_guard", "guard_repeats", "worker.postprocess"),
    ("core.transcriber", "_write_outputs", "worker.output"),
    ("core.transcriber", "get_duration", "worker.prepare"),
    ("core.transcriber", "_ensure_default_backend_loaded", "worker.model"),
])
def test_fault_at_worker_site(module, function, site):
    exc = injected(module, function, RuntimeError("injected"))
    assert clue.worker_clue(exc)["failure_site"] == site


def test_nested_frame_wins_and_unmapped_frames_use_phase():
    exc = injected("unmapped", "run", ValueError("x"))
    task = SimpleNamespace(_failure_site="worker.segments")
    assert clue.worker_clue(exc, task)["failure_site"] == "worker.segments"
    exc = injected("core.transcriber", "_write_outputs", exc)
    assert clue.worker_clue(exc, task)["failure_site"] == "worker.output"


@pytest.mark.parametrize("message,code,module,exc_type", [
    ("Unable to allocate 2.00 GiB for an array with shape (123, 456) and data type float32", "numpy_alloc_failed", "core.mel_blocks", MemoryError),
    ("std::bad_alloc", "ct2_bad_alloc", "ctranslate2.models.whisper", RuntimeError),
    ("CUDA failed with error out of memory", "cuda_out_of_memory", "faster_whisper.transcribe", RuntimeError),
    ("Library cublas64_12.dll is not found or cannot be loaded", "cublas_missing", "ctranslate2.models.whisper", RuntimeError),
    ("Library cudnn64_9.dll is not found or cannot be loaded", "cudnn_missing", "ctranslate2.models.whisper", RuntimeError),
])
def test_anchored_library_patterns(message, code, module, exc_type):
    assert clue.observed_code(injected(module, "run", exc_type(message))) == code
    assert clue.observed_code(exc_type(message)) == "none"  # no library frame
    for text in ("C:/talks/" + message + ".wav", message + "/private.mp3", "prefix " + message):
        assert clue.observed_code(injected(module, "run", exc_type(text))) == "none"


def test_app_probe_patterns_require_the_originating_frame():
    no_audio = RuntimeError("cuda_oom_recording.wav has no audio track, so there is nothing to transcribe.")
    assert clue.observed_code(injected("core.transcriber", "require_audio_stream", no_audio)) == "no_audio_stream"
    assert clue.observed_code(RuntimeError(str(no_audio))) == "none"
    timeout = RuntimeError("ffprobe timed out for C:/talks/Out of memory podcast.mp3")
    timeout.__cause__ = subprocess.TimeoutExpired("ffprobe", 60)
    assert clue.observed_code(injected("core.transcriber", "get_duration", timeout)) == "probe_timeout"
    assert clue.observed_code(timeout.__cause__) == "none"


@pytest.mark.parametrize("error,code", [
    (OSError(errno.ENOSPC, "cuda_oom_recording.wav"), "disk_full"),
    (OSError(errno.EACCES, "C:/talks/Out of memory podcast.mp3"), "access_denied"),
    (FileNotFoundError(errno.ENOENT, "std::bad_alloc"), "file_not_found"),
])
def test_os_errors_only_use_the_error_number(error, code):
    assert clue.observed_code(error) == code
    assert clue.os_error(error) == error.errno


def test_windows_error_number_takes_precedence():
    error = OSError("failure")
    error.winerror = 112
    assert clue.os_error(error) == 112
    assert clue.observed_code(error) == "disk_full"
    error.winerror = 5
    assert clue.observed_code(error) == "access_denied"


def test_av_invalid_data_is_a_family_not_message_matching():
    invalid = type("InvalidDataError", (Exception,), {"__module__": "av.error"})
    error = invalid("private file")
    assert clue.exception_family(error) == "av.InvalidDataError"
    assert clue.observed_code(error) == "av_invalid_data"


def test_random_and_hostile_messages_never_trigger_a_code():
    rng = random.Random(129)
    alphabet = "abcdefghijklmnopqrstuvwxyz /_\\0123456789.:"
    for _ in range(1000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 120)))
        assert clue.observed_code(injected("faster_whisper.transcribe", "run", RuntimeError(text))) == "none"
    for text in ("cuda_oom_recording.wav", "C:/talks/Out of memory podcast.mp3",
                 "cublas_missing.wav", "numpy_alloc_failed.wav", "std::bad_alloc.wav"):
        assert clue.observed_code(injected("faster_whisper.transcribe", "run", RuntimeError(text))) == "none"


def test_parent_clues_and_windows_exit_normalisation(monkeypatch):
    monkeypatch.setattr(clue, "peak_memory_mb", lambda pid=None: 1024)
    assert clue.normalise_exit_code(-1073741819, "win32") == 0xC0000005
    assert clue.normalise_exit_code(-9, "linux") == -9
    watchdog = clue.parent_clue("parent.watchdog", device="cuda", exit_code=-9, pid=12)
    assert watchdog["failure_site"] == "parent.watchdog"
    assert watchdog["peak_mem_mb"] == "1024" and watchdog["exit_code"] == "0"
    exited = clue.parent_clue("parent.worker_exit", device="cpu", exit_code=-9)
    assert exited["failure_site"] == "parent.worker_exit" and exited["peak_mem_mb"] == "0"
    from app.services.transcription_service import _remember_failure_clue
    task = SimpleNamespace()
    _remember_failure_clue(task, {"device": "cuda"}, site="parent.watchdog", pid=12)
    assert task.failure_clue == watchdog


def test_peak_memory_is_bucketed_and_unavailable_is_zero(monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "Process", lambda pid=None: SimpleNamespace(
        memory_info=lambda: SimpleNamespace(peak_pagefile=770 * 1024 * 1024)))
    assert clue.peak_memory_mb(123) == 768
    monkeypatch.setattr(psutil, "Process", lambda pid=None: SimpleNamespace(
        memory_info=lambda: SimpleNamespace()))
    assert clue.peak_memory_mb(123) == 0


def test_failure_payload_obeys_the_existing_gates(monkeypatch):
    from core import offline

    sent = []
    monkeypatch.setattr(stats, "_post", lambda *args: sent.append(args))
    monkeypatch.setattr(offline, "skipped", lambda *_: None)
    payload = {"status": "error", **clue.sanitise_clue()}
    config = {"telemetry_opt_in": False, "stats_url": "https://example.invalid"}
    assert not stats.post_stats_async(config, payload)
    config["telemetry_opt_in"] = True
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    assert not stats.post_stats_async(config, payload)
    assert sent == []


def test_error_payload_is_closed_and_nonerrors_have_no_clue(monkeypatch):
    monkeypatch.setattr(stats, "public_model_name", lambda _: "model")
    monkeypatch.setattr(stats, "region_country", lambda: "")
    common = dict(model="x", language="en", audio_duration=0, transcription_time=0)
    fields = set(clue.registry()["fields"])
    hostile = {"failure_site": "C:/private.wav", "exception_family": "my-secret",
               "observed_code": "my-secret", "device": "private", "peak_mem_mb": 257}
    result = stats.build_stats_payload(**common, status="error", failure_clue=hostile)
    assert set(result) >= fields
    assert result["failure_site"] == "other" and result["peak_mem_mb"] == "0"
    assert "private" not in str(result) and "secret" not in str(result)
    for status in ("finished", "cancelled"):
        assert not fields.intersection(stats.build_stats_payload(**common, status=status, failure_clue=hostile))


def test_registry_and_documentation_are_identical():
    registry = clue.registry()
    assert registry["version"] == 1
    doc = (ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    table = doc.split("| Failure clue field | Allowed values |", 1)[1].split("\n\n", 1)[0]
    rows = {name: re.findall(r"`([^`]+)`", text) for name, text in
            re.findall(r"\| `([^`]+)` \| ([^\n]+?) \|", table)}
    assert set(rows) == set(registry["fields"])
    for field, spec in registry["fields"].items():
        expected = spec["values"] if spec["type"] == "enum" else [str(spec["min"]), str(spec["max"]), str(spec.get("step", 1))]
        assert rows[field] == expected


def test_clue_failure_is_swallowed_in_stats(monkeypatch):
    monkeypatch.setattr(clue, "registry", lambda: (_ for _ in ()).throw(RuntimeError("broken")))
    monkeypatch.setattr(stats, "public_model_name", lambda _: "model")
    payload = stats.build_stats_payload(model="m", language="", audio_duration=0,
                                        transcription_time=0, status="error")
    assert payload["status"] == "error"


def test_worker_error_event_contains_clue_and_builder_failure_does_not_block_it(monkeypatch, capsys):
    from core import worker
    from tests.core.test_worker_error_outputs import _run

    monkeypatch.setattr(worker, "get_effective_device", lambda: SimpleNamespace(
        device="cuda", compute_type="float16", requested_device="cuda", downgraded=False))

    def fail(task, progress_cb, log_cb, language_cb=None):
        clue.phase(task, "worker.segments")
        raise RuntimeError("private file content")

    event = next(e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error")
    assert event["failure_site"] == "worker.segments"
    assert event["exception_family"] == "RuntimeError" and event["device"] == "cuda"
    assert event["observed_code"] == "none"
    assert "private" not in str({k: event[k] for k in clue.registry()["fields"]})

    def broken(*args, **kwargs):
        raise RuntimeError("clue builder broke")

    monkeypatch.setattr(clue, "worker_clue", broken)
    event = next(e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error")
    assert event["message"] == "private file content"


def test_worker_startup_exception_is_a_model_clue(monkeypatch, capsys):
    from core import worker

    def fail(_callback):
        raise MemoryError("private model location")

    monkeypatch.setattr(worker, "load_existing_model", fail)
    assert worker.main() == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    event = next(e for e in events if e["event"] == "startup_error")
    assert event["failure_site"] == "worker.model"
    assert event["exception_family"] == "MemoryError" and event["observed_code"] == "none"


def test_parent_watchdog_and_exit_paths_record_clues(monkeypatch):
    from app.services import transcription_service as service
    from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

    monkeypatch.setattr(clue, "peak_memory_mb", lambda pid=None: 512)
    app = _app()
    svc = _svc(app)
    task = SimpleNamespace(status="running", recovery_note="", error_reason="")
    w = {"id": 1, "token": "tok1", "ready": True, "task": task,
         "process": _Alive(), "device": "cuda", "last_event_at": 0}
    app.workers = [w]
    svc.finish_task = lambda *args, **kwargs: None
    svc.restart_worker = lambda *args: None
    svc._restart_wedged_worker(w, 200)
    assert task.status == "error" and task.failure_clue["failure_site"] == "parent.watchdog"
    assert task.failure_clue["peak_mem_mb"] == "512"

    task.status = "running"
    w["ready"] = True
    svc._are_outputs_complete = lambda _: False
    app.worker_events.put({"event": "worker_exit", "return_code": -9, "_pid": 4242,
                           "_worker_id": 1, "_token": "tok1"})
    svc.poll()
    assert task.status == "error" and task.failure_clue["failure_site"] == "parent.worker_exit"
    assert int(task.failure_clue["exit_code"]) == clue.normalise_exit_code(-9)


def test_worker_event_reaches_the_error_stats_payload(monkeypatch):
    from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

    app = _app()
    svc = _svc(app)
    task = SimpleNamespace(status="running", file_path="private.wav", start_time=None,
                           recovery_note="", error_reason="", detected_language="en")
    w = {"id": 1, "token": "tok1", "ready": True, "task": task,
         "process": _Alive(), "device": "cuda", "last_event_at": 0}
    app.workers = [w]
    svc.finish_task = lambda *args, **kwargs: None
    svc._engine_snapshot = lambda: {"spawn_backend": "faster_whisper", "model_name": "test"}
    app.worker_events.put({"event": "error", "message": "private detail", "_pid": 4242,
                           "_worker_id": 1, "_token": "tok1", "failure_site": "worker.features",
                           "exception_family": "MemoryError", "observed_code": "numpy_alloc_failed",
                           "classifier_version": "1", "device": "unknown", "peak_mem_mb": "1024"})
    svc.poll()
    assert task.status == "error" and task.failure_clue["failure_site"] == "worker.features"
    posted = []
    monkeypatch.setattr(stats, "post_stats_async", lambda config, payload: posted.append(payload))
    monkeypatch.setattr(stats, "public_model_name", lambda _: "model")
    monkeypatch.setattr(stats, "install_id_for", lambda _: "")
    svc._post_usage_stats(task, 0, 0.0, w, status="error")
    assert len(posted) == 1
    assert posted[0]["failure_site"] == "worker.features"
    assert posted[0]["observed_code"] == "numpy_alloc_failed"
    assert posted[0]["device"] == "cuda" and posted[0]["peak_mem_mb"] == "1024"
    assert "private" not in str(posted[0])


@pytest.mark.parametrize("spec", ["whisper_project_onefile.spec", "whisper_project_onedir.spec",
                                 "platform/macos/pyinstaller/whisper_project_mac.spec"])
def test_specs_bundle_registry_and_module(spec):
    content = (ROOT / spec).read_text(encoding="utf-8")
    assert "'core.failure_clue'" in content
    assert "'telemetry_registry.json'" in content or "'core/telemetry_registry.json'" in content


@pytest.mark.parametrize("target,site", [
    ("model", "worker.model"), ("model_wait", "worker.model"), ("prepare", "worker.prepare"),
    ("decode", "worker.decode"), ("vad", "worker.vad"),
    ("features", "worker.features"), ("language", "worker.language"),
    ("segments", "worker.segments"), ("postprocess", "worker.postprocess"),
    ("output", "worker.output"),
])
def test_real_transcriber_phase_faults(monkeypatch, tmp_path, target, site):
    from core import transcriber as tr
    from core.task import TranscriptionTask

    def fail(*args, **kwargs):
        raise RuntimeError("injected fault")

    frames = {"decode": ("faster_whisper.audio", "decode_audio"),
              "vad": ("faster_whisper.vad", "get_speech_timestamps"),
              "features": ("core.mel_blocks", "extract"),
              "language": ("faster_whisper.transcribe", "detect_language")}

    class Engine:
        def transcribe(self, *args, **kwargs):
            if target in frames:
                module, function = frames[target]
                raise injected(module, function, RuntimeError("injected fault"))
            if target == "segments":
                def generator():
                    fail()
                    yield None
                return generator(), SimpleNamespace(language="en", language_probability=0.9)
            return iter(()), SimpleNamespace(language="en", language_probability=0.9)

    monkeypatch.setattr(tr, "_runtime_overrides_scope", lambda task: nullcontext({}))
    monkeypatch.setattr(tr, "_protect_existing_checkpoint", lambda *a: None)
    monkeypatch.setattr(tr, "_note_run_identity", lambda *a: None)
    monkeypatch.setattr(tr, "_checked_whisper_task", lambda *a: None)
    monkeypatch.setattr(tr, "_ensure_default_backend_loaded", fail if target == "model" else lambda *a: None)
    monkeypatch.setattr(tr, "get_duration", fail if target == "prepare" else lambda *a: 10.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda *a: None)
    monkeypatch.setattr(tr, "_run_post_pipeline", fail if target == "postprocess" else lambda *a: 0)
    monkeypatch.setattr(tr, "_write_outputs", fail if target == "output" else lambda *a, **k: [])
    monkeypatch.setattr(tr, "MODEL", Engine())
    monkeypatch.setattr(tr, "MODEL_READY", target != "model_wait")
    monkeypatch.setattr(tr, "MODEL_ERROR", "load failed" if target == "model_wait" else None)
    monkeypatch.setattr(tr, "PIPELINE", None)
    monkeypatch.setattr(tr, "config", {"transcribe_backend": "faster_whisper"})
    task = TranscriptionTask(str(tmp_path / "hostile_cuda_oom.wav"))
    task.keep_empty_outputs = True
    with pytest.raises(RuntimeError) as caught:
        tr.transcribe(task)
    assert clue.worker_clue(caught.value, task)["failure_site"] == site
