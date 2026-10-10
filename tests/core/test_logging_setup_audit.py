import pytest
import os
import sys
from core import logging_setup
import subprocess
import logging

def test_open_log_folder_os_error(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(logging_setup, "user_log_dir", lambda: tmp_path)
    def raise_fnf(*args, **kwargs):
        raise OSError("no file manager found")
    monkeypatch.setattr(subprocess, "run", raise_fnf)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "name", "posix")
    
    with caplog.at_level(logging.WARNING):
        res = logging_setup.open_log_folder()
    
    assert res is None
    assert "no file manager found" in caplog.text
    assert str(tmp_path) in caplog.text

def test_open_log_folder_os_error_windows(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(logging_setup, "user_log_dir", lambda: tmp_path)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(sys, "platform", "win32")
    def raise_fnf(*args, **kwargs):
        raise OSError("no startfile configured")
    monkeypatch.setattr(os, "startfile", raise_fnf, raising=False)
    
    with caplog.at_level(logging.WARNING):
        res = logging_setup.open_log_folder()
        
    assert res is None
    assert "no startfile configured" in caplog.text
    assert str(tmp_path) in caplog.text

def test_redacting_formatter_redacts_exc_text():
    import logging
    formatter = logging_setup.RedactingFormatter(logging_setup.LOG_FORMAT)
    record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)
    
    try:
        raise ValueError("error http://user:pass@example.com/path?query=1")
    except ValueError as e:
        record.exc_info = (type(e), e, e.__traceback__)
        
    formatted = formatter.format(record)
    assert "user:pass" not in formatted
    assert "example.com/path?<redacted>" in formatted
