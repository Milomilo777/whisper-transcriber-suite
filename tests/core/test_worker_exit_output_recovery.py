"""Crash recovery identifies fresh output sets without guessing from index order."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import time
from types import SimpleNamespace
import unicodedata

import pytest

from app.services import transcription_service as ts
from core import transcriber as tr
from core.history import HistoryDB
from core.task import TranscriptionTask


@pytest.fixture(autouse=True)
def default_names(monkeypatch):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")


def _write(source: Path, text: str) -> list[str]:
    return tr._write_outputs(
        str(source.with_suffix("")), [{"start": 0., "end": 1., "text": text}],
        str(source), ["srt", "json"],
    )


def _seed_hole(folder: Path, index: int, stem: str = "clip"):
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / f"{stem}.wav"
    source.write_bytes(b"synthetic source; the writers do not decode it")
    sets = [_write(source, f"older {i}") for i in range(index + 2)]
    old_time = time.time() - 600
    for paths in sets:
        for path in paths:
            os.utime(path, (old_time, old_time))
    for path in sets[index]:
        assert Path(path).parent == folder
        Path(path).unlink()  # Only reproducible fixture outputs.
    hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
              for i, paths in enumerate(sets) if i != index for p in paths}
    return source, hashes


def _task(source: Path, **extra):
    values = dict(file_path=str(source), start_time=time.time() - 5,
                  output_formats=["srt", "json"], output_paths=None,
                  status="running", cancelled=False, no_speech=False)
    values.update(extra)
    return SimpleNamespace(**values)


def _service():
    return ts.TranscriptionService(SimpleNamespace(app_config={"output_formats": ["srt", "json"]}))


def _same_outputs(actual, expected):
    assert len(actual) == len(expected)
    assert all(any(os.path.samefile(a, b) for b in expected) for a in actual)


@pytest.mark.parametrize("gap,stem", [
    (0, "clip"), (1, "clip"),
    (0, unicodedata.normalize("NFD", "گزارش café [draft] (x)")), (0, "CLIP"),
])
def test_real_writer_reuses_gap_and_crash_recovery_finds_that_set(tmp_path, gap, stem):
    source, older = _seed_hole(tmp_path / "café folder", gap, stem)
    current = _write(source, "current transcript")
    alias = source.with_name(source.name.lower()) if os.name == "nt" else source
    task = _task(alias)
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, current)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in older.items())


@pytest.mark.parametrize("index", [7, 10000])
def test_fresh_set_after_missing_indices_is_found(tmp_path, index):
    source = tmp_path / "clip.wav"
    source.touch()
    expected = []
    for ext in ("srt", "json"):
        path = tmp_path / f"clip ({index}).{ext}"
        path.write_text("fresh output", encoding="utf-8")
        expected.append(str(path))
    task = _task(source)
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, expected)


def test_multiple_fresh_sets_are_ambiguous_without_reported_paths(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    _write(source, "first concurrent result")
    _write(source, "second concurrent result")
    task = _task(source)
    assert not _service()._are_outputs_complete(task)
    assert task.output_paths is None


def test_new_partial_set_never_falls_back_to_recent_complete_older_set(tmp_path):
    source, older = _seed_hole(tmp_path, 0)
    start = time.time()
    # This complete set is still inside the filesystem timestamp tolerance.
    for path in older:
        os.utime(path, (start - 1, start - 1))
    (tmp_path / "clip.srt").write_text("only the new subtitle was saved", encoding="utf-8")
    task = _task(source, start_time=start)
    assert not _service()._are_outputs_complete(task)
    assert task.output_paths is None


@pytest.mark.parametrize("suffix", [" (10001)", " (01)"])
def test_unrecognised_indices_are_not_claimed_as_outputs(tmp_path, suffix):
    source = tmp_path / "clip.wav"
    source.touch()
    for ext in ("srt", "json"):
        (tmp_path / f"clip{suffix}.{ext}").write_text("not a writer index", encoding="utf-8")
    assert not _service()._are_outputs_complete(_task(source))


def test_scan_failure_is_safe_but_reported_paths_need_no_scan(tmp_path, monkeypatch):
    source = tmp_path / "clip.wav"
    source.touch()
    paths = _write(source, "known result")
    def denied(*args, **kwargs):
        raise PermissionError("fixture directory listing denied")
    monkeypatch.setattr(ts.os, "scandir", denied)
    assert not _service()._are_outputs_complete(_task(source))
    assert _service()._are_outputs_complete(_task(source, output_paths=paths))
    assert all(Path(p).is_file() for p in paths)


def test_empty_directory_snapshot_cannot_bypass_candidate_verification(tmp_path, monkeypatch):
    source = tmp_path / "clip.wav"
    source.touch()
    paths = _write(source, "known result")
    monkeypatch.setattr(ts.os, "scandir", lambda folder: nullcontext(iter(())))
    assert not _service()._are_outputs_complete(_task(source))
    assert _service()._are_outputs_complete(_task(source, output_paths=paths))


def test_legacy_task_without_start_time_keeps_its_existing_numbered_fallback(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    _write(source, "first")
    newest = _write(source, "second")
    task = _task(source, start_time=0.)
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, newest)


def test_reported_paths_win_even_when_other_fresh_sets_exist(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    known = _write(source, "known result")
    _write(source, "another result")
    task = _task(source, output_paths=known)
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, known)


@pytest.mark.parametrize("start", [float("nan"), float("inf"), float("-inf")])
def test_invalid_run_timestamp_cannot_identify_a_fresh_output_set(tmp_path, start):
    source = tmp_path / "clip.wav"
    source.touch()
    _write(source, "result")
    assert not _service()._are_outputs_complete(_task(source, start_time=start))


def test_duplicate_extension_plan_is_not_mistaken_for_two_outputs(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    (tmp_path / "clip.txt").write_text("one format only", encoding="utf-8")
    task = _task(source, output_formats=["txt", "express_scribe"])
    assert not _service()._are_outputs_complete(task)


def test_custom_template_never_attaches_unrelated_default_named_outputs(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    unrelated = _write(source, "another default-named run")
    custom = []
    for ext in ("srt", "json"):
        path = tmp_path / f"clip-custom.{ext}"
        path.write_text("this custom-named run", encoding="utf-8")
        custom.append(str(path))
    task = _task(source, task_settings={"output_filename_template": "{base}-custom.{ext}"})
    assert not _service()._are_outputs_complete(task)
    task.output_paths = custom
    assert _service()._are_outputs_complete(task)
    assert all(Path(p).is_file() for p in unrelated)


@pytest.mark.parametrize("other_name", ["clip (7).wav", "clip (7).mp3", "clip.mp3"])
def test_another_source_owns_its_matching_output_namespace(tmp_path, other_name):
    source = tmp_path / "clip.wav"
    source.touch()
    other = tmp_path / other_name
    other.touch()
    foreign = _write(other, "another source's result")
    task = _task(source)
    assert not _service()._are_outputs_complete(task)
    assert task.output_paths is None
    assert all(Path(p).is_file() for p in foreign)


@pytest.mark.parametrize("future_ext", ["srt", "json"])
def test_future_dated_set_is_not_evidence_of_this_run(tmp_path, future_ext):
    source = tmp_path / "clip.wav"
    source.touch()
    future = time.time() + 3600
    for ext in ("srt", "json"):
        path = tmp_path / f"clip (7).{ext}"
        path.write_text("copied output with a future timestamp", encoding="utf-8")
        if ext == future_ext:
            os.utime(path, (future, future))
    assert not _service()._are_outputs_complete(_task(source))


def test_unreadable_candidate_metadata_does_not_select_another_run(tmp_path, monkeypatch):
    source = tmp_path / "clip.wav"
    source.touch()
    known = _write(source, "one plausible run")
    for ext in ("srt", "json"):
        (tmp_path / f"clip (7).{ext}").write_text("another plausible run", encoding="utf-8")
    real_mtime = os.path.getmtime
    def denied(path):
        if "(7)" in str(path):
            raise PermissionError("fixture metadata denied")
        return real_mtime(path)
    monkeypatch.setattr(ts.os.path, "getmtime", denied)
    assert not _service()._are_outputs_complete(_task(source))
    assert _service()._are_outputs_complete(_task(source, output_paths=known))


def test_directories_are_not_a_completed_output_set(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    for ext in ("srt", "json"):
        (tmp_path / f"clip.{ext}").mkdir()
    assert not _service()._are_outputs_complete(_task(source))


def test_case_insensitive_volume_works_without_ntpath_normcase(tmp_path, monkeypatch):
    source = tmp_path / "CLIP.wav"
    source.touch()
    alias = tmp_path / "clip.wav"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem")
    expected = []
    for ext in ("srt", "json"):
        path = tmp_path / f"CLIP (7).{ext}"
        path.write_text("fresh result", encoding="utf-8")
        expected.append(str(path))
    # macOS os.path.normcase is identity even on a case-insensitive volume.
    monkeypatch.setattr(ts.os.path, "normcase", lambda path: str(path))
    task = _task(alias)
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, expected)


def test_case_only_neighbour_is_distinct_only_on_a_case_sensitive_volume(tmp_path):
    source = tmp_path / "clip.wav"
    source.touch()
    other = tmp_path / "CLIP.mp3"
    other.touch()
    current = _write(source, "this source")
    _write(other, "other source")
    case_sensitive = not (tmp_path / "CLIP.wav").exists()
    task = _task(source)
    recovered = _service()._are_outputs_complete(task)
    assert recovered is case_sensitive
    if recovered:
        _same_outputs(task.output_paths, current)


def test_unrelated_media_do_not_require_per_file_identity_probes(tmp_path, monkeypatch):
    source = tmp_path / "clip.wav"
    source.touch()
    _write(source, "current result")
    for index in range(20):
        (tmp_path / f"unrelated-{index}.wav").touch()
    real_same = ts._same_file
    unrelated = []
    def same(first, second):
        if Path(first).name.startswith("unrelated-"):
            unrelated.append(first)
        return real_same(first, second)
    monkeypatch.setattr(ts, "_same_file", same)
    assert _service()._are_outputs_complete(_task(source))
    assert unrelated == []


def _write_mode(source: Path, text: str, translate: bool = False) -> list[str]:
    task = SimpleNamespace(file_path=str(source), whisper_task="translate" if translate else "transcribe")
    return tr._write_outputs(
        tr._task_output_base(task), [{"start": 0., "end": 1., "text": text}],
        str(source), ["srt", "json"], lang="en",
    )


def _inverse_case(folder: Path, kind: str):
    origin = folder / "clip.wav"
    origin.write_bytes(b"origin input")
    names = {"numbered": "clip (7)", "translated": "clip.en-translated",
             "both": "clip.en-translated (7)", "case-alias": "clip.EN-TRANSLATED"}
    literal = folder / f"{names[kind]}.wav"
    literal.write_bytes(b"different input")
    outputs = []
    for _ in range(8 if kind in ("numbered", "both") else 1):
        outputs.append(_write_mode(origin, "foreign transcript", kind != "numbered"))
    old = time.time() - 600
    for paths in outputs[:-1]:
        for path in paths:
            os.utime(path, (old, old))
    return literal, outputs


@pytest.mark.parametrize("kind", ["numbered", "translated", "both", "case-alias"])
def test_inverse_namespace_does_not_attach_another_sources_real_outputs(tmp_path, kind):
    literal, outputs = _inverse_case(tmp_path, kind)
    hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for paths in outputs for p in paths}
    task = _task(literal, whisper_task="transcribe")
    assert not _service()._are_outputs_complete(task)
    assert task.output_paths is None
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes.items())


@pytest.mark.parametrize("kind", ["numbered", "translated"])
def test_inverse_namespace_worker_exit_records_error_not_a_foreign_result(tmp_path, monkeypatch, kind):
    from tests.core.test_worker_lifecycle_c251b import _app
    literal, _outputs = _inverse_case(tmp_path, kind)
    history, shown = HistoryDB(tmp_path / "history.db"), []
    app = _app(history=history, app_config={"output_formats": ["srt", "json"]},
               show_last_result=shown.append, note_job_success=lambda: None)
    service = ts.TranscriptionService(app)
    monkeypatch.setattr(service, "_post_usage_stats", lambda *a, **k: None)
    monkeypatch.setattr(service, "_run_finish_hooks", lambda *a, **k: None)
    task = TranscriptionTask(str(literal))
    task.status, task.start_time = "running", time.time() - 5
    task.history_id = history.insert_transcription(str(literal))
    task.output_formats = ["srt", "json"]
    class Dead:
        pid = 4242
        def poll(self):
            return 1
    worker = {"id": 1, "token": "inverse", "process": Dead(), "ready": True,
              "task": task, "temporary": False, "last_event_at": time.monotonic()}
    app.workers.append(worker)
    app.worker_events.put({"event": "worker_exit", "return_code": 1,
                           "_pid": 4242, "_worker_id": 1, "_token": "inverse"})
    service.poll()
    row = history.list_transcriptions()[0]
    assert task.status == row["status"] == "error"
    assert row["output_paths"] == []
    assert shown == []


@pytest.mark.parametrize("stem,translate", [
    ("clip (7)", False), ("clip (7)", True),
    ("clip.en-translated", True), ("clip (7) (1)", False),
    ("clip.en-translated.en-translated", False),
])
def test_inverse_ancestors_do_not_reject_unique_higher_sets(tmp_path, stem, translate):
    (tmp_path / "clip.wav").write_bytes(b"possible ancestor input")
    literal = tmp_path / f"{stem}.wav"
    literal.write_bytes(b"this input")
    old_paths = _write_mode(literal, "older literal run", translate)
    old = time.time() - 600
    for path in old_paths:
        os.utime(path, (old, old))
    current = _write_mode(literal, "current literal run", translate)
    task = _task(literal, whisper_task="translate" if translate else "transcribe")
    assert _service()._are_outputs_complete(task)
    _same_outputs(task.output_paths, current)


@pytest.mark.parametrize("case_sensitive_identity", [False, True])
def test_inverse_translation_suffix_uses_native_output_identity(tmp_path, monkeypatch, case_sensitive_identity):
    origin = tmp_path / "clip.wav"
    origin.touch()
    literal = tmp_path / "clip.EN-TRANSLATED.wav"
    literal.touch()
    current = _write(literal, "literal uppercase input")
    if case_sensitive_identity:
        real_same = os.path.samefile
        def sensitive(first, second):
            a, b = os.path.abspath(first), os.path.abspath(second)
            if a != b and a.casefold() == b.casefold():
                return False
            return real_same(first, second)
        monkeypatch.setattr(ts.os.path, "samefile", sensitive)
    canonical = Path(tr._task_output_base(SimpleNamespace(file_path=str(origin), whisper_task="translate")) + ".srt")
    alias = canonical.exists() and os.path.samefile(canonical, current[0])
    task = _task(literal, whisper_task="transcribe")
    recovered = _service()._are_outputs_complete(task)
    assert recovered is (not alias)
    if recovered:
        _same_outputs(task.output_paths, current)


_CHILD_WRITER = r'''
import json,os,sys
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
source,marker=Path(sys.argv[2]),Path(sys.argv[3])
import platformdirs
with ExitStack() as stack:
    for name in ('user_config_dir','user_cache_dir','user_log_dir','user_data_dir','user_state_dir'):
        stack.enter_context(patch.object(platformdirs,name,lambda *a,**k:str(marker.parent)))
    from core import transcriber
    transcriber.config['output_filename_template']='{base}.{ext}'
    paths=transcriber._write_outputs(str(source.with_suffix('')),[{'start':0.,'end':1.,'text':'current result'}],str(source),['srt','json'])
    marker.write_text(json.dumps(paths),encoding='utf-8')
os._exit(1)  # Abrupt exit after real durable writes, without a done event.
'''


def test_real_child_exit_one_recovers_history_before_showing_result(tmp_path, monkeypatch):
    source, older = _seed_hole(tmp_path / "Unicode café space", 0)
    history = HistoryDB(tmp_path / "history.db")
    shown = []
    app = SimpleNamespace(
        workers=[], worker_events=Queue(), queue=[], next_worker_id=1,
        app_config={"output_formats": ["srt", "json"]}, history=history,
        entry_file=str(Path(ts.__file__).resolve().parents[2] / "gui.py"),
        status_var=SimpleNamespace(set=lambda value: None),
        after=lambda *a, **k: None, post_to_main=lambda fn: fn(),
        log=lambda message: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, update_overall_progress=lambda: None,
        model_status=lambda message: None, note_job_success=lambda: None,
        show_last_result=lambda task: shown.append((task, history.list_transcriptions()[0])),
        parallel_workers=1, model_loading=False, worker_ready=False, model_ready=False,
    )
    service = ts.TranscriptionService(app)
    monkeypatch.setattr(service, "_post_usage_stats", lambda *a, **k: None)
    monkeypatch.setattr(service, "_run_finish_hooks", lambda *a, **k: None)
    monkeypatch.setattr(service, "_engine_snapshot", lambda: {"spawn_backend": "faster_whisper", "model_name": "fixture"})
    import core.hardware
    monkeypatch.setattr(core.hardware, "transcription_worker_env", lambda: dict(os.environ, PYTHONUTF8="1"))
    task = TranscriptionTask(str(source))
    task.history_id = history.insert_transcription(str(source))
    task.task_id = f"h{task.history_id}"
    task.start_time, task.status = time.time(), "running"
    task.output_formats = ["srt", "json"]
    marker = tmp_path / "writer-completed.json"
    root = Path(ts.__file__).resolve().parents[2]
    real_popen = subprocess.Popen
    children = []
    def spawn(cmd, **kwargs):
        child = real_popen([sys.executable, "-B", "-c", _CHILD_WRITER, str(root), str(source), str(marker)], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(ts.subprocess, "Popen", spawn)
    try:
        service.start_worker()
        worker = app.workers[0]
        worker["task"] = task
        deadline, events = time.monotonic() + 40, []
        while time.monotonic() < deadline:
            try:
                event = app.worker_events.get(timeout=.1)
            except Empty:
                continue
            events.append(event)
            if event.get("event") == "worker_exit":
                break
        assert events and events[-1]["event"] == "worker_exit"
        assert events[-1]["return_code"] == 1
        assert all(e.get("event") != "done" for e in events)
        assert marker.is_file(), "child must finish the real writers before its deliberate exit"
        expected = json.loads(marker.read_text(encoding="utf-8"))
        for event in events:
            app.worker_events.put(event)
        service.poll()
        row = history.list_transcriptions()[0]
        assert task.status == row["status"] == "finished"
        _same_outputs(row["output_paths"], expected)
        assert shown and shown[0][1]["status"] == "finished"
        _same_outputs(shown[0][1]["output_paths"], expected)
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in older.items())
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()  # Only this test's own captured child.
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
