from __future__ import annotations
import os
import wave
import math
import pytest
from pathlib import Path
from core import tts_job

def test_split_text_long_no_space():
    long_text = "a" * 100
    pieces = tts_job.split_text(long_text, 10)
    assert "".join(pieces) == long_text
    assert all(len(p.strip()) <= 10 for p in pieces)

def test_split_text_rtl():
    text = "شسیب" * 10
    pieces = tts_job.split_text(text, 5)
    assert "".join(pieces) == text

def test_split_text_max_chars_validation():
    with pytest.raises(ValueError, match="must be at least 1"):
        tts_job.split_text("test", 0)

def test_job_key_handles_empty():
    key1 = tts_job.job_key("kokoro", "", {}, 1.0)
    assert len(key1) > 0

def test_wav_frames_malformed(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    with pytest.raises(wave.Error):
        tts_job._wav_frames(path)

def test_split_long_combining_chars():
    text = "a\u0301" * 10 
    pieces = tts_job._split_long(text, 5)
    assert "".join(pieces) == text
    assert "a\u0301" in pieces[0]

def test_wav_complete_false_on_short_file(tmp_path):
    path = tmp_path / "test.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00" * 32000)
    
    assert tts_job._wav_complete(path, 16000) is True
    
    with open(path, "rb+") as f:
        f.truncate(100)
    
    assert tts_job._wav_complete(path, 16000) is False

def test_write_json_atomic_has_fsync(tmp_path, monkeypatch):
    fsync_called = []
    original_fsync = os.fsync
    def mock_fsync(fd):
        fsync_called.append(fd)
        original_fsync(fd)
    monkeypatch.setattr(os, "fsync", mock_fsync)
    
    path = tmp_path / "progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tts_job._write_json_atomic(path, {"done": True})
    
    assert len(fsync_called) == 1
    assert path.is_file()

def test_split_long_empty_and_single_char():
    assert tts_job._split_long("", 10) == []
    assert tts_job._split_long("a", 10) == ["a"]

def test_job_lock_raises_job_busy(tmp_path):
    path = tmp_path / "lockfile"
    lock1 = tts_job._JobLock(path)
    lock1.acquire()
    
    lock2 = tts_job._JobLock(path)
    with pytest.raises(tts_job.JobBusy):
        lock2.acquire()
        
    lock1.release()
    lock2.acquire()
    lock2.release()

def test_job_key_handles_voice_variations():
    v1 = {"name": "voiceA", "param": 1.0}
    v2 = {"param": 1.0, "name": "voiceA"}
    assert tts_job.job_key("kokoro", "text", v1, 1.0) == tts_job.job_key("kokoro", "text", v2, 1.0)

def test_has_speech():
    assert tts_job.has_speech("Hello!")
    assert not tts_job.has_speech("   ")
    assert not tts_job.has_speech("!?.")
    assert not tts_job.has_speech("\u0301\u0302")
    assert tts_job.has_speech("مرحبا")

def test_is_unfinished_job_dir(tmp_path):
    job_dir = tmp_path / "job"
    parts_dir = job_dir / tts_job.PARTS_DIR
    parts_dir.mkdir(parents=True)
    
    assert not tts_job.is_unfinished_job_dir(job_dir)
    
    (parts_dir / tts_job.PROGRESS_FILE).write_text("{}")
    assert tts_job.is_unfinished_job_dir(job_dir)

def test_find_kept_references_none(tmp_path):
    root = tmp_path / "tts"
    assert tts_job.find_kept_references("kokoro", "test", {}, 1.0, root) is None
    

def test_open_job_handles_rtl(tmp_path, monkeypatch):
    root = tmp_path / "tts"
    monkeypatch.setattr(tts_job.tts_plan, "output_root", lambda: root)
    text = "مرحبا" * 5
    job = tts_job.open_job("kokoro", text, {}, 1.0)
    assert len(job.spoken()) > 0
    assert job.output_path.name == "output.wav"

def test_run_cancellation(tmp_path, monkeypatch):
    import threading
    root = tmp_path / "tts"
    monkeypatch.setattr(tts_job.tts_plan, "output_root", lambda: root)
    job = tts_job.open_job("kokoro", "test running cancellation", {}, 1.0)
    ev = threading.Event()
    ev.set() # cancelled immediately
    
    with pytest.raises(tts_job.Cancelled):
        tts_job.run(job, lambda text, path, prog: None, cancel_event=ev)

def test_job_pending(tmp_path):
    job = tts_job.Job(tmp_path, "key", "kokoro", ["a", "b", "c"])
    assert job.pending() == [0, 1, 2]
    job.done[1] = tts_job.PieceDone(100, 1.0, 1.0)
    assert job.pending() == [0, 2]
