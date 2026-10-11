"""Atomic writers flush the temp file to disk before os.replace swaps it in.

Without the fsync a power loss right after the rename can leave the target empty on some
file systems: the rename is on disk, the data is not yet.
"""
from __future__ import annotations

import os
from collections.abc import Callable

import pytest

from app.dialogs import viewer_exports
from app.services import integrations_service
from core import convert, yt_dlp_update
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


def test_yt_dlp_state_file_fsyncs_before_the_replace(tmp_path, events, monkeypatch):
    state = tmp_path / "state" / "yt_dlp_state.json"
    monkeypatch.setattr(yt_dlp_update, "_state_path", lambda: state)
    yt_dlp_update._save_state({"active": "bundled"})
    assert state.read_text(encoding="utf-8").strip().startswith("{")
    assert "fsync" in events[:events.index("replace")], events
