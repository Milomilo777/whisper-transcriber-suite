"""core.watcher.is_transcribable: what the Transcribe button and a multi-file drop accept.

A known media extension is accepted without running ffprobe; any other file is accepted
only when ffprobe finds an audio stream in it (formats the extension list does not name),
so a README picked by mistake is turned away instead of queued as a job that fails.
"""
from __future__ import annotations

import pytest

from core import burn_subs, watcher


@pytest.fixture
def probes(monkeypatch):
    seen: list[str] = []

    def fake_probe(path, timeout=60.0):
        seen.append(path)
        codec = "amr_nb" if path.endswith(".amr") else ""
        return burn_subs.MediaInfo(3.0 if codec else 0.0, None if not codec else False, codec)

    monkeypatch.setattr(burn_subs, "probe_media", fake_probe)
    watcher._probe_has_audio.cache_clear()
    yield seen
    watcher._probe_has_audio.cache_clear()


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
    watcher.is_transcribable(path)
    watcher.is_transcribable(path)
    assert len(probes) == 1
    _touch(tmp_path, "README.md", b"longer now")
    watcher.is_transcribable(path)
    assert len(probes) == 2
