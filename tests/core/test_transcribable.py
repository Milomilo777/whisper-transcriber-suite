"""core.watcher.is_transcribable: what the Transcribe button and a multi-file drop accept.

A known media extension is accepted without running ffprobe; any other file is accepted
only when ffprobe finds an audio stream in it (formats the extension list does not name),
so a README picked by mistake is turned away instead of queued as a job that fails. When
ffprobe cannot answer, the file is accepted and that non-answer is not remembered.
"""
from __future__ import annotations

import subprocess

import pytest

from core import watcher


@pytest.fixture
def probes(monkeypatch):
    seen: list[str] = []
    answers: dict[str, bool | None] = {".amr": True, ".md": False, ".txt": False, ".bin": None}

    def fake_probe(path):
        seen.append(path)
        return answers[path[path.rfind("."):]]

    monkeypatch.setattr(watcher, "_ffprobe_has_audio", fake_probe)
    watcher._probe_cache.clear()
    yield seen
    watcher._probe_cache.clear()


def _touch(tmp_path, name, data=b"x"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_known_media_needs_no_probe(tmp_path, probes):
    assert watcher.is_transcribable(_touch(tmp_path, "talk.mp3"))
    assert probes == []


def test_a_text_file_is_refused(tmp_path, probes):
    path = _touch(tmp_path, "README.md", b"# notes\n")
    assert not watcher.is_transcribable(path)
    assert probes == [path]


def test_other_audio_formats_pass_the_probe(tmp_path, probes):
    assert watcher.is_transcribable(_touch(tmp_path, "call.amr"))


def test_a_missing_file_is_refused_without_a_probe(tmp_path, probes):
    assert not watcher.is_transcribable(str(tmp_path / "gone.amr"))
    assert probes == []


def test_the_answer_is_cached_until_the_file_changes(tmp_path, probes):
    path = _touch(tmp_path, "README.md", b"a")
    assert not watcher.is_transcribable(path)
    assert not watcher.is_transcribable(path), "the cached answer is the probe's answer"
    assert len(probes) == 1
    _touch(tmp_path, "README.md", b"longer now")
    watcher.is_transcribable(path)
    assert len(probes) == 2


def test_no_answer_accepts_the_file_and_asks_again_next_time(tmp_path, probes):
    path = _touch(tmp_path, "locked.bin")
    assert watcher.is_transcribable(path)
    assert watcher.is_transcribable(path)
    assert len(probes) == 2, "a failed probe must not be cached"


@pytest.mark.parametrize("error", [
    FileNotFoundError("ffprobe"), subprocess.TimeoutExpired("ffprobe", 5.0),
])
def test_ffprobe_that_cannot_run_gives_no_answer(monkeypatch, tmp_path, error):
    def boom(*a, **k):
        raise error

    monkeypatch.setattr(watcher.subprocess, "run", boom)
    assert watcher._ffprobe_has_audio(_touch(tmp_path, "x.amr")) is None


@pytest.mark.parametrize("returncode, stdout, expected", [
    (0, b"audio\n", True), (0, b"", False), (1, b"audio\n", False),
])
def test_ffprobe_answers(monkeypatch, tmp_path, returncode, stdout, expected):
    monkeypatch.setattr(
        watcher.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=stdout),
    )
    assert watcher._ffprobe_has_audio(_touch(tmp_path, "x.amr")) is expected
