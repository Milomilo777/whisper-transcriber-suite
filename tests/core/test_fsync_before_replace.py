"""Atomic writers flush the temp file to disk before os.replace swaps it in.

Without the fsync a power loss right after the rename can leave the target empty on some
file systems: the rename is on disk, the data is not yet.
"""
from __future__ import annotations

import os
import errno
from pathlib import Path
from collections.abc import Callable

import pytest

from app.dialogs import viewer_exports
from app.services import integrations_service
from core import convert, yt_dlp_update
from core import transcriber
from core.writers import html_transcript


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    got: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        got.append("fsync")
        real_fsync(fd)

    def replace(src, dst) -> None:
        got.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    return got


def _html(path: str) -> None:
    html_transcript.write_page([{"start": 0.0, "end": 1.0, "text": "Hello"}], "", out_path=path, audio="none")


WRITERS: dict[str, Callable[[str], object]] = {
    "viewer export": lambda p: viewer_exports.write_atomically(p, b"data"),
    "subtitle round trip": lambda p: integrations_service._write_text_atomic(p, "data"),
    "converted file": lambda p: convert._replace_atomically(p, b"data"),
    "HTML transcript": _html,
}


@pytest.mark.parametrize("name", list(WRITERS))
def test_writer_fsyncs_before_the_replace(name, tmp_path, events):
    target = str(tmp_path / "out.bin")
    WRITERS[name](target)
    assert os.path.getsize(target) > 0
    assert "replace" in events
    assert "fsync" in events[:events.index("replace")], events


@pytest.mark.parametrize("name", list(WRITERS))
def test_a_volume_that_rejects_fsync_still_gets_the_file(name, tmp_path, monkeypatch):
    # Some network shares, FUSE and USB file systems answer fsync with EINVAL/ENOTSUP; before
    # the fsync was added these saves worked there, so a refused sync must not fail them.
    def refuse(_fd: int) -> None:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(os, "fsync", refuse)
    target = str(tmp_path / "out.bin")
    WRITERS[name](target)
    assert os.path.getsize(target) > 0
    assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]


def test_yt_dlp_state_file_survives_a_refused_fsync(tmp_path, monkeypatch):
    def refuse(_fd: int) -> None:
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(os, "fsync", refuse)
    state = tmp_path / "state" / "yt_dlp_state.json"
    monkeypatch.setattr(yt_dlp_update, "_state_path", lambda: state)
    yt_dlp_update._save_state({"active": "bundled"})
    assert state.read_text(encoding="utf-8").strip().startswith("{")


def test_yt_dlp_state_file_fsyncs_before_the_replace(tmp_path, events, monkeypatch):
    state = tmp_path / "state" / "yt_dlp_state.json"
    monkeypatch.setattr(yt_dlp_update, "_state_path", lambda: state)
    yt_dlp_update._save_state({"active": "bundled"})
    assert state.read_text(encoding="utf-8").strip().startswith("{")
    assert "fsync" in events[:events.index("replace")], events


@pytest.mark.parametrize("name", list(WRITERS))
@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC, errno.EROFS, None])
def test_real_sync_failure_cannot_replace_the_previous_saved_output(name, code, tmp_path, monkeypatch):
    target = tmp_path / "previous.bin"
    previous = b"previous complete owner-edited output"
    target.write_bytes(previous)
    attempted = []

    def failed_sync(fd):
        attempted.append(fd)
        raise OSError(code, "synthetic real storage failure")

    monkeypatch.setattr(os, "fsync", failed_sync)
    error = None
    try:
        WRITERS[name](str(target))
    except OSError as failure:
        error = failure
    assert attempted, "test must reach the native sync boundary"
    assert target.read_bytes() == previous
    assert error is not None and error.errno == code
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC, errno.EROFS, None])
def test_real_sync_failure_keeps_previous_downloader_state(code, tmp_path, monkeypatch):
    state = tmp_path / "state" / "yt_dlp_state.json"
    monkeypatch.setattr(yt_dlp_update, "_state_path", lambda: state)
    yt_dlp_update._save_state({"active": "bundled"})
    previous = state.read_bytes()

    def fail_sync(fd):
        raise OSError(code, "synthetic downloader state sync failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError):
        yt_dlp_update._save_state({"active": "updated"})
    assert state.read_bytes() == previous


@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC])
def test_transcription_cannot_report_success_when_every_output_sync_fails(code, tmp_path, monkeypatch):
    previous = tmp_path / "clip.srt"
    previous.write_bytes(b"previous completed transcript")

    def fail_sync(fd):
        raise OSError(code, "synthetic transcription output sync failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(RuntimeError, match="All output writers failed") as raised:
        transcriber._write_outputs(str(tmp_path / "clip"),
                                   [{"start": 0.0, "end": 1.0, "text": "new completed words"}],
                                   "synthetic.wav", ["srt", "json"])
    assert isinstance(raised.value.__cause__, OSError) and raised.value.__cause__.errno == code
    assert previous.read_bytes() == b"previous completed transcript"
    assert list(tmp_path.glob("*.srt")) == [previous]
    assert not list(tmp_path.glob("*.json")) and not list(tmp_path.glob("*.part"))


def test_transcription_retains_formats_whose_sync_succeeded(tmp_path, monkeypatch):
    fsync = os.fsync
    calls = []

    def fail_only_first_output(fd):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError(errno.EIO, "synthetic first output sync failure")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_only_first_output)
    paths = transcriber._write_outputs(str(tmp_path / "clip"),
                                      [{"start": 0.0, "end": 1.0, "text": "new completed words"}],
                                      "synthetic.wav", ["srt", "json"])
    assert len(paths) == 1 and paths[0].endswith(".json")
    assert b"new completed words" in Path(paths[0]).read_bytes()
    assert not list(tmp_path.glob("*.srt")) and not list(tmp_path.glob("*.part"))
