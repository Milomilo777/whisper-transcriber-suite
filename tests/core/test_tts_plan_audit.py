import pytest
import os
import sys
import logging
from core import tts_plan
import pathlib

def test_hardware_fingerprint_no_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    fp = tts_plan.hardware_fingerprint("cuda")
    assert "unknown GPU" in fp

def test_hardware_fingerprint_cpu():
    fp = tts_plan.hardware_fingerprint("cpu")
    assert "threads" in fp

def test_hardware_fingerprint_torch_crash(monkeypatch):
    class FakeTorch:
        @property
        def cuda(self):
            raise RuntimeError("CUDA initialization failed")
    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    fp = tts_plan.hardware_fingerprint("cuda")
    assert "unknown GPU" in fp

def test_free_bytes_os_error_contract(monkeypatch):
    import shutil
    def raise_oserror(*args, **kwargs):
        raise OSError("Drive not found")
    monkeypatch.setattr(shutil, "disk_usage", raise_oserror)
    with pytest.raises(OSError, match="Drive not found"):
        tts_plan.free_bytes("Z:\\does_not_exist")
        
def test_check_disk_catches_os_error_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(tts_plan, "free_bytes", lambda x: (_ for _ in ()).throw(OSError("Drive missing")))
    est = tts_plan.Estimate(
        units=1.0,
        audio_low=1.0, 
        audio_high=2.0, 
        time_low=1.0,
        time_high=2.0,
        measured=False,
        size_low=1, 
        size_high=100
    )
    
    with caplog.at_level(logging.WARNING):
        dc = tts_plan.check_disk(est)
        
    assert not dc.ok
    assert "Failed to check free disk space" in caplog.text
