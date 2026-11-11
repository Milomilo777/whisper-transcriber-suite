"""Output failures retain closed OS clues without risking earlier transcripts."""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.transcriber as tr
from core.failure_clue import worker_clue


@pytest.fixture(autouse=True)
def output_config(monkeypatch):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")
    monkeypatch.setattr(tr, "get_writer", lambda name: lambda segments, audio: "new transcript\n")


def assert_cause(error, code, number):
    assert isinstance(error.__cause__, OSError)
    assert error.__cause__.errno == number
    clue = worker_clue(error, SimpleNamespace(_failure_site="worker.output"), device="cpu")
    assert clue["failure_site"] == "worker.output"
    assert clue["observed_code"] == code
    assert clue["os_error"] == str(number)
    assert clue["exception_family"] == ("PermissionError" if number == errno.EACCES else "OSError")


@pytest.mark.parametrize("number,code,expected_attempts", [
    (errno.EACCES, "access_denied", 2),
    (errno.ENOSPC, "disk_full", 1),
    (errno.EROFS, "none", 1),
    (errno.EIO, "none", 1),
])
def test_claim_failure_keeps_os_cause_and_releases_earlier_claim(tmp_path, monkeypatch, number, code, expected_attempts):
    real_open = os.open
    attempts = []

    def failing_open(path, flags, *args, **kwargs):
        if str(path).endswith(".json"):
            attempts.append(str(path))
            raise OSError(number, "private destination", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", failing_open)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["srt", "json"])
    assert_cause(caught.value, code, number)
    assert len(attempts) == expected_attempts
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase", ["flush", "replace"])
@pytest.mark.parametrize("number,code", [(errno.EACCES, "access_denied"), (errno.ENOSPC, "disk_full")])
def test_write_failure_keeps_os_cause_and_cleans_parts(tmp_path, monkeypatch, phase, number, code):
    error = OSError(number, "private destination", str(tmp_path / "secret"))

    def fail(*args, **kwargs):
        raise error

    if phase == "flush":
        monkeypatch.setattr(tr._checkpoint, "_flush_to_disk", fail)
    else:
        monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["srt", "json"],
                          chapters=[{"start": 0.0, "title": "One"}])
    assert caught.value.__cause__ is error
    assert_cause(caught.value, code, number)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only attributes enforce a real write denial")
def test_real_readonly_file_permission_failure_keeps_cause(tmp_path, monkeypatch):
    protected = tmp_path / "protected.txt"
    protected.write_text("keep", encoding="utf-8")
    protected.chmod(stat.S_IREAD)

    def denied_flush(stream):
        # Real filesystem PermissionError, not a constructed exception.
        with protected.open("w", encoding="utf-8") as target:
            target.write("must never be written")

    monkeypatch.setattr(tr._checkpoint, "_flush_to_disk", denied_flush)
    try:
        with pytest.raises(RuntimeError) as caught:
            tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["srt"])
        assert_cause(caught.value, "access_denied", errno.EACCES)
        assert protected.read_text(encoding="utf-8") == "keep"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["protected.txt"]
    finally:
        protected.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_one_writer_failure_keeps_other_completed_outputs(tmp_path, monkeypatch):
    previous = tmp_path / "talk.srt"
    previous.write_text("earlier transcript", encoding="utf-8")

    def writer(name):
        def write(segments, audio):
            if name == "json":
                raise OSError(errno.ENOSPC, "disk full")
            return "new transcript\n"
        return write

    monkeypatch.setattr(tr, "get_writer", writer)
    outputs = tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["srt", "json"])
    assert [Path(x).name for x in outputs] == ["talk (1).srt"]
    assert previous.read_text(encoding="utf-8") == "earlier transcript"
    assert (tmp_path / "talk (1).srt").read_text(encoding="utf-8") == "new transcript\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["talk (1).srt", "talk.srt"]


def test_existing_file_in_output_directory_is_not_a_filename_collision(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(blocked / "talk"), [], "input.wav", ["srt"])
    assert isinstance(caught.value.__cause__, OSError)
    assert caught.value.__cause__.errno in {errno.EEXIST, errno.ENOTDIR}
    assert blocked.read_text(encoding="utf-8") == "keep"
    assert list(tmp_path.iterdir()) == [blocked]


def deny_optional_writer_directory(tmp_path, monkeypatch, number):
    from core.writers import smtv_docx_writer

    target = tmp_path / "optional" / "export.docx"
    monkeypatch.setattr(tr, "_smtv_output_path", lambda *args: str(target))
    monkeypatch.setattr(smtv_docx_writer, "write_bytes", lambda *args, **kwargs: b"document")
    real_makedirs = os.makedirs

    def fail_directory(path, *args, **kwargs):
        if str(path) == str(target.parent):
            raise OSError(number, "denied destination", str(path))
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", fail_directory)
    return target


@pytest.mark.parametrize("number,code", [(errno.EACCES, "access_denied"), (errno.ENOSPC, "disk_full")])
def test_writer_directory_failure_keeps_original_cause(tmp_path, monkeypatch, number, code):
    deny_optional_writer_directory(tmp_path, monkeypatch, number)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["smtv_docx"])
    assert_cause(caught.value, code, number)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("formats", [["srt", "smtv_docx"], ["smtv_docx", "srt"]])
def test_writer_directory_failure_keeps_other_formats(tmp_path, monkeypatch, formats):
    deny_optional_writer_directory(tmp_path, monkeypatch, errno.EACCES)
    outputs = tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", formats)
    assert [Path(x).name for x in outputs] == ["talk.srt"]
    assert (tmp_path / "talk.srt").read_text(encoding="utf-8") == "new transcript\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["talk.srt"]
