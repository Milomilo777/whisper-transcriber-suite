import os
import urllib.error
import urllib.request

import pytest

from core.llm import download_default_model, RemoteLLMRunner, RemoteLLMConfig, RemoteLLMError


def test_download_default_model_fsync_defect(monkeypatch, tmp_path):
    fsync_called = False
    original_fsync = os.fsync
    def mock_fsync(fd):
        nonlocal fsync_called
        fsync_called = True
        return original_fsync(fd)
        
    monkeypatch.setattr(os, "fsync", mock_fsync)
    
    class MockResponse:
        def __init__(self, body): self.body = body
        def read(self, *a, **k):
            b = self.body
            self.body = b""
            return b
        def __enter__(self): return self
        def __exit__(self, *a): pass
        @property
        def headers(self): return {"content-length": "4"}
        
    def mock_urlopen(req, *args, **kwargs):
        return MockResponse(b'data')
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    dest = tmp_path / "model.gguf"
    download_default_model(dest=dest)
    
    assert dest.exists()
    assert fsync_called, "os.fsync was not called before os.replace"

def test_remote_llm_runner_httperror_leak(monkeypatch):
    runner = RemoteLLMRunner(RemoteLLMConfig("http://mock.com", "test"))
    
    close_called = False
    class MockHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("http://mock.com", 400, "Bad Request", {}, None)
        def read(self):
            return b"error body"
        def close(self):
            nonlocal close_called
            close_called = True
            
    def mock_urlopen(*args, **kwargs):
        raise MockHTTPError()
        
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    with pytest.raises(RemoteLLMError):
        runner._post_once("http://mock.com", urllib.request.Request("http://mock.com"))
        
    assert close_called, "HTTPError close() was not called"
