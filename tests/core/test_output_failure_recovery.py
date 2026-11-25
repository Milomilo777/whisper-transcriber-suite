"""Finished text remains recoverable when its normal destination cannot save."""
import errno
import json
from pathlib import Path

import pytest

from core import _checkpoint
from core import transcriber as tr


SEGMENTS = [{"start": 30.0, "end": 32.0, "text": "Completed clipped transcript",
             "speaker": "S1", "words": [{"start": 30.0, "end": 31.0, "word": "Completed"}]}]


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")


def recovery_files():
    return list((_checkpoint.user_data_dir() / "transcript-recovery").glob("output-*.json"))


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, OSError])
def test_task_exports_to_recovery_folder_when_destination_fails(tmp_path, monkeypatch, caplog, failure):
    from core.task import TranscriptionTask

    destination = tmp_path / "exports"
    destination.mkdir()
    source = str(destination / "音声.wav")
    base = str(destination / "音声")
    replace = tr.os.replace
    code = {FileNotFoundError: errno.ENOENT, PermissionError: errno.EACCES, OSError: errno.ENOSPC}[failure]

    def refuse(src, dst):
        if Path(dst).parent == destination:
            raise failure(code, "synthetic output refusal")
        return replace(src, dst)

    monkeypatch.setattr(tr.os, "replace", refuse)
    task = TranscriptionTask(source)
    caplog.set_level("INFO", logger=tr.__name__)
    saved = tr._write_task_outputs(task, base, SEGMENTS, source, ["srt", "json"])

    assert saved == task.output_paths
    assert {Path(path).suffix for path in saved} == {".srt", ".json"}
    folder = Path(saved[0]).parent
    assert folder.parent == _checkpoint.user_data_dir() / "transcript-recovery"
    assert str(folder) in caplog.text and "saved" in caplog.text
    assert "Completed clipped transcript" in Path(saved[0]).read_text(encoding="utf-8")
    assert isinstance(json.loads(Path(saved[1]).read_text(encoding="utf-8")), list)
    assert json.loads(recovery_files()[0].read_text(encoding="utf-8"))["segments"] == SEGMENTS
    assert not list(destination.iterdir())


def test_task_recovers_when_a_file_blocks_the_output_directory(tmp_path):
    from core.task import TranscriptionTask

    blocked = tmp_path / "exports"
    blocked.write_bytes(b"keep this file")
    source = str(tmp_path / "audio.wav")
    task = TranscriptionTask(source)
    written = tr._write_task_outputs(task, str(blocked / "audio"), SEGMENTS, source, ["srt"])
    assert Path(written[0]).is_file()
    assert blocked.read_bytes() == b"keep this file"


def test_task_retries_the_failed_format_without_moving_successful_outputs(tmp_path, monkeypatch):
    from core.task import TranscriptionTask

    source = str(tmp_path / "audio.wav")
    base = str(tmp_path / "audio")
    replace = tr.os.replace

    def refuse(src, dst):
        if Path(dst) == tmp_path / "audio.json":
            raise PermissionError(errno.EACCES, "synthetic publication refusal")
        return replace(src, dst)

    monkeypatch.setattr(tr.os, "replace", refuse)
    task = TranscriptionTask(source)
    saved = tr._write_task_outputs(task, base, SEGMENTS, source, ["srt", "json"])
    assert saved == task.output_paths
    assert len(saved) == 2
    assert Path(saved[0]) == tmp_path / "audio.srt"
    assert Path(saved[1]).parent.parent == _checkpoint.user_data_dir() / "transcript-recovery"
    assert json.loads(Path(saved[1]).read_text(encoding="utf-8"))[0]["text"] == SEGMENTS[0]["text"]
    assert not (tmp_path / "audio.json").exists()


@pytest.mark.parametrize("phase", ["claim", "publish", "writer", "config"])
def test_failed_outputs_keep_full_transcript_separate_from_success(tmp_path, monkeypatch, phase):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic source identity")
    destination = tmp_path / "exports"
    if phase == "claim":
        destination.write_bytes(b"existing unrelated file blocks directory")
    else:
        destination.mkdir()
    base = str(destination / "clip")
    formats = ["srt", "json"]
    if phase == "publish":
        replace = tr.os.replace
        def refuse(src, dst):
            if Path(dst).parent == destination:
                raise PermissionError(errno.EACCES, "synthetic output refusal")
            return replace(src, dst)
        monkeypatch.setattr(tr.os, "replace", refuse)
    elif phase == "writer":
        def fail(*args):
            raise OSError(errno.ENOSPC, "synthetic writer storage failure")
        monkeypatch.setattr(tr, "get_writer", lambda name: fail)
    elif phase == "config":
        formats = ["unsupported-synthetic-format"]
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(base, SEGMENTS, str(source), formats, lang="en")
    copies = recovery_files()
    assert len(copies) == 1, "completed text must survive in a separate profile recovery file"
    saved = json.loads(copies[0].read_text(encoding="utf-8"))
    assert saved["segments"] == SEGMENTS
    assert saved["source_path"] == str(source)
    assert saved["language"] == "en"
    assert str(copies[0]) in str(caught.value)
    assert not getattr(caught.value, "output_paths", None)
    assert not _checkpoint.has_checkpoint(str(source)), "recovery must not impersonate whole-file resume"
    if phase == "claim":
        assert destination.read_bytes() == b"existing unrelated file blocks directory"


def broken_writer(monkeypatch):
    failure = OSError(errno.ENOSPC, "synthetic original writer failure")
    def fail(*args):
        raise failure
    monkeypatch.setattr(tr, "get_writer", lambda name: fail)
    return failure


def test_recovery_opens_in_converter_without_losing_words_or_speakers(tmp_path, monkeypatch):
    from core.convert import parse_to_segments, convert_file
    broken_writer(monkeypatch)
    with pytest.raises(RuntimeError):
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt"])
    kept, = recovery_files()
    segments = parse_to_segments(str(kept))
    assert segments == SEGMENTS
    target = convert_file(str(kept), "srt", out_path=str(tmp_path / "recovered.srt"))
    assert "00:00:30,000 --> 00:00:32,000" in Path(target).read_text(encoding="utf-8")
    assert "Completed clipped transcript" in Path(target).read_text(encoding="utf-8")


def test_profile_failure_preserves_original_os_cause_without_false_recovery(tmp_path, monkeypatch):
    failure = broken_writer(monkeypatch)
    blocked = tmp_path / "blocked-profile"
    blocked.write_bytes(b"keep this unrelated file")
    monkeypatch.setattr(_checkpoint, "user_data_dir", lambda: blocked)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt"])
    assert caught.value.__cause__ is failure
    assert "Recovery data:" not in str(caught.value)
    assert blocked.read_bytes() == b"keep this unrelated file"


def test_recovery_sync_failure_is_not_advertised_and_keeps_new_artifact(tmp_path, monkeypatch):
    failure = broken_writer(monkeypatch)
    def fail_sync(stream):
        raise OSError(errno.EIO, "synthetic recovery sync failure")
    monkeypatch.setattr(_checkpoint, "_strict_sync", fail_sync)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt"])
    assert caught.value.__cause__ is failure
    assert "Recovery data:" not in str(caught.value)
    kept, = recovery_files()
    assert json.loads(kept.read_text(encoding="utf-8"))["segments"] == SEGMENTS


def test_recovery_never_replaces_older_copy_and_sweep_does_not_remove_it(tmp_path, monkeypatch):
    import os
    import uuid
    from types import SimpleNamespace
    broken_writer(monkeypatch)
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="fixed-test-id"))
    folder = _checkpoint.user_data_dir() / "transcript-recovery"
    folder.mkdir(parents=True)
    previous = folder / "output-fixed-test-id.output-recovery.json"
    previous.write_bytes(b"existing owner edited recovery")
    with pytest.raises(RuntimeError):
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt"])
    assert previous.read_bytes() == b"existing owner edited recovery"
    copies = [path for path in recovery_files() if path != previous]
    assert len(copies) == 1
    os.utime(copies[0], (1, 1))
    _checkpoint.sweep_partials(max_age_days=0, slice_max_age_minutes=0)
    assert copies[0].exists()
    assert json.loads(copies[0].read_text(encoding="utf-8"))["segments"] == SEGMENTS


def test_partial_export_success_does_not_create_recovery(tmp_path, monkeypatch):
    original = tr.get_writer
    def writer(name):
        if name == "json":
            def fail(*args):
                raise OSError(errno.ENOSPC, "synthetic single-format failure")
            return fail
        return original(name)
    monkeypatch.setattr(tr, "get_writer", writer)
    outputs = tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt", "json"])
    assert len(outputs) == 1 and outputs[0].endswith(".srt")
    assert not recovery_files()


def test_unrelated_whole_file_checkpoint_survives_failed_clipped_export(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"original source")
    partial = _checkpoint.write_checkpoint(str(source), backend="faster_whisper", model_name="tiny",
        language="en", language_probability=1.0, cfg_fingerprint="synthetic", last_end_time=10.0,
        segments=[{"start": 0.0, "end": 10.0, "text": "whole-file partial"}], checkpoint_time=1.0)
    original = partial.read_bytes()
    broken_writer(monkeypatch)
    with pytest.raises(RuntimeError):
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, str(source), ["srt"])
    assert partial.read_bytes() == original
    assert _checkpoint.load_checkpoint(str(source))["segments"][0]["text"] == "whole-file partial"
    assert len(recovery_files()) == 1


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_wrapped_writer_oom_does_not_allocate_a_recovery_copy(tmp_path, monkeypatch, depth):
    original = MemoryError("synthetic writer allocation failure")
    failure = original
    for _ in range(depth):
        wrapper = RuntimeError("synthetic nested writer error")
        wrapper.__cause__ = failure
        failure = wrapper
    def fail(*args):
        raise failure
    attempts = []
    def no_recovery(*args):
        attempts.append(True)
        raise AssertionError("a large recovery allocation must not follow OOM")
    monkeypatch.setattr(tr, "get_writer", lambda name: fail)
    monkeypatch.setattr(tr, "_keep_output_recovery", no_recovery)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt"])
    assert attempts == []
    cause = caught.value
    while cause.__cause__ is not None:
        cause = cause.__cause__
    assert cause is original
    assert not list(tmp_path.iterdir())


def test_one_writer_oom_keeps_another_successful_format_without_recovery(tmp_path, monkeypatch):
    writer = tr.get_writer
    def choose(name):
        if name == "srt":
            def fail(*args):
                raise MemoryError("synthetic individual format OOM")
            return fail
        return writer(name)
    attempts = []
    monkeypatch.setattr(tr, "get_writer", choose)
    monkeypatch.setattr(tr, "_keep_output_recovery", lambda *args: attempts.append(True))
    outputs = tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt", "json"])
    assert len(outputs) == 1 and outputs[0].endswith(".json")
    assert attempts == []


@pytest.mark.parametrize("oom_format", ["srt", "vtt"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_all_failed_writers_retain_earlier_oom_before_disk_error(tmp_path, monkeypatch, oom_format, wrapped):
    original = MemoryError("synthetic allocation failure")
    failure = original
    if wrapped:
        failure = RuntimeError("wrapped allocation failure")
        failure.__cause__ = original
    def choose(name):
        def fail(*args):
            if name == oom_format:
                raise failure
            raise OSError("synthetic storage failure")
        return fail
    attempts = []
    monkeypatch.setattr(tr, "get_writer", choose)
    monkeypatch.setattr(tr, "_keep_output_recovery", lambda *args: attempts.append(True))
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "clip"), SEGMENTS, "input.wav", ["srt", "vtt"])
    assert attempts == [], "Recovery allocated after one of the failed writers ran out of memory"
    error = caught.value
    while error.__cause__ is not None:
        error = error.__cause__
    assert error is original
    assert not list(tmp_path.iterdir())
