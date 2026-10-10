import os

import pytest

import core._checkpoint as cp
import core.transcriber as tr

def test_transcriber_write_outputs_oserror_safety(tmp_path, monkeypatch):
    base = str(tmp_path / "talk")
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    audio = str(tmp_path / "talk.mp3")
    (tmp_path / "talk.mp3").write_bytes(b"")

    def mock_fsync_raise(fd: int) -> None:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(os, "fsync", mock_fsync_raise)
    
    written = tr._write_outputs(base, segments, audio, formats=["srt", "json"])
    
    assert len(written) == 2
    assert any(w.endswith(".srt") for w in written)
    assert any(w.endswith(".json") for w in written)
    assert (tmp_path / "talk.srt").exists()
    assert (tmp_path / "talk.json").exists()

def test_checkpoint_write_oserror_safety(tmp_path, monkeypatch):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"data")

    def mock_fsync_raise(fd: int) -> None:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(os, "fsync", mock_fsync_raise)
    
    path = cp.write_checkpoint(
        str(source),
        backend="dummy",
        model_name="dummy",
        language="en",
        language_probability=0.9,
        cfg_fingerprint="dummy",
        last_end_time=0.0,
        segments=[],
        checkpoint_time=0.0
    )
    assert path.exists()

def test_write_outputs_ordering(tmp_path, monkeypatch):
    base = str(tmp_path / "talk")
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    audio = str(tmp_path / "talk.mp3")
    (tmp_path / "talk.mp3").write_bytes(b"")

    events = []

    original_fsync = os.fsync
    original_replace = os.replace

    def mock_fsync(fd: int) -> None:
        # We can't easily map fd to filename here, but we record the event
        events.append(("fsync", fd))
        original_fsync(fd)

    def mock_replace(src, dst) -> None:
        events.append(("replace", str(src), str(dst)))
        original_replace(src, dst)

    monkeypatch.setattr(os, "fsync", mock_fsync)
    monkeypatch.setattr(os, "replace", mock_replace)

    pytest.importorskip("docx")
        
    formats = ["srt", "docx"]

    tr._write_outputs(base, segments, audio, formats=formats, chapters=[{"start":0, "end":1, "title": "Intro"}])

    # Validate that for each output, fsync happened before replace
    fsync_count = sum(1 for e in events if e[0] == "fsync")
    replace_count = sum(1 for e in events if e[0] == "replace")
    
    # We wrote SRT, DOCX, and sidecar. So 3 formats.
    expected_files = 3
    assert fsync_count == expected_files
    assert replace_count == expected_files

    # They should happen in pairs (fsync, then replace) for each file written.
    for i in range(expected_files):
        assert events[i*2][0] == "fsync"
        assert events[i*2+1][0] == "replace"

def test_checkpoint_write_ordering(tmp_path, monkeypatch):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"")

    events = []
    original_fsync = os.fsync
    original_replace = os.replace

    def mock_fsync(fd: int) -> None:
        events.append("fsync")
        original_fsync(fd)

    def mock_replace(src, dst) -> None:
        events.append("replace")
        original_replace(src, dst)

    monkeypatch.setattr(os, "fsync", mock_fsync)
    monkeypatch.setattr(os, "replace", mock_replace)
    
    cp.write_checkpoint(
        str(source),
        backend="dummy",
        model_name="dummy",
        language="en",
        language_probability=0.9,
        cfg_fingerprint="dummy",
        last_end_time=0.0,
        segments=[],
        checkpoint_time=0.0
    )

    assert events == ["fsync", "replace"]

def test_save_partial_subtitles_ordering(tmp_path, monkeypatch):
    class MockTask:
        file_path = str(tmp_path / "talk.mp3")
        
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]

    events = []
    original_fsync = os.fsync
    original_replace = os.replace

    def mock_fsync(fd: int) -> None:
        events.append("fsync")
        original_fsync(fd)

    def mock_replace(src, dst) -> None:
        events.append("replace")
        original_replace(src, dst)

    monkeypatch.setattr(os, "fsync", mock_fsync)
    monkeypatch.setattr(os, "replace", mock_replace)

    tr._save_partial_subtitles(MockTask(), segments, None)

    assert events == ["fsync", "replace"]


def test_save_partial_subtitles_unbound_local_error(tmp_path, monkeypatch):
    class MockTask:
        file_path = str(tmp_path / "talk.mp3")
        
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]

    def mock_get_writer(fmt):
        def writer(*args, **kwargs):
            raise ValueError("broken writer")
        return writer

    monkeypatch.setattr(tr, "get_writer", mock_get_writer)
    
    # Should not raise UnboundLocalError
    tr._save_partial_subtitles(MockTask(), segments, None)
    
    part_files = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    assert len(part_files) == 0

