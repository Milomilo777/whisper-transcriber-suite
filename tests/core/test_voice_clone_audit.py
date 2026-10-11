import subprocess
import os
from core.voice_clone import (
    trim_reference_sample
)

def test_trim_reference_sample_fsync_defect(tmp_path, monkeypatch):
    
    fsync_called = False
    original_fsync = os.fsync
    def mock_fsync(fd):
        nonlocal fsync_called
        fsync_called = True
        return original_fsync(fd)
        
    monkeypatch.setattr(os, "fsync", mock_fsync)
    
    in_file = tmp_path / "in.wav"
    in_file.write_bytes(b"")
    out_file = tmp_path / "out.wav"
    
    def mock_run(*args, **kwargs):
        # Find the tmp_out argument
        tmp_out = args[0][-1]
        with open(tmp_out, "wb") as f:
            f.write(b"trimmed")
        return subprocess.CompletedProcess(args[0], 0, "", "")
    
    monkeypatch.setattr(subprocess, "run", mock_run)
    trim_reference_sample(str(in_file), str(out_file), 5.0)
    
    assert out_file.exists()
    assert fsync_called, "os.fsync was not called before os.replace"

