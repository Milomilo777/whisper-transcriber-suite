import pytest
import urllib.request
import urllib.error

from core.backends import whisper_cpp as wc

def test_is_available(monkeypatch):
    import sys
    import types
    fake = types.ModuleType("pywhispercpp")
    monkeypatch.setitem(sys.modules, "pywhispercpp", fake)
    assert wc.is_available()

    monkeypatch.setitem(sys.modules, "pywhispercpp", None)
    assert not wc.is_available()

def test_download_model_already_exists(tmp_path, monkeypatch):
    dest = tmp_path / "ggml.bin"
    with open(dest, "wb") as f:
        f.truncate(100_000_001)

    logs = []
    def logger(msg): logs.append(msg)

    path = wc.download_default_model(log=logger, dest=dest)
    assert path == str(dest)
    assert any("already present" in msg for msg in logs)

def test_download_model_success(tmp_path, monkeypatch):
    dest = tmp_path / "ggml.bin"
    logs = []

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Length": "100"}
            self.data = [b"a" * 50, b"a" * 50]
        def getheader(self, k):
            return self.headers.get(k)
        def read(self, chunk):
            if self.data:
                return self.data.pop(0)
            return b""
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse())
    monkeypatch.setattr(wc.offline, "require_online", lambda *a: None)

    path = wc.download_default_model(log=lambda m: logs.append(m), dest=dest)
    assert path == str(dest)
    assert dest.exists()
    assert len(dest.read_bytes()) == 100

def test_download_model_truncated(tmp_path, monkeypatch):
    dest = tmp_path / "ggml.bin"

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Length": "100"}
            self.data = [b"a" * 50]
        def getheader(self, k):
            return self.headers.get(k)
        def read(self, chunk):
            if self.data:
                return self.data.pop(0)
            return b""
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse())
    monkeypatch.setattr(wc.offline, "require_online", lambda *a: None)

    with pytest.raises(RuntimeError, match="truncated"):
        wc.download_default_model(dest=dest)
    assert not dest.exists()
    assert not dest.with_suffix(".bin.part").exists()

def test_download_model_exception_cleans_up(tmp_path, monkeypatch):
    dest = tmp_path / "ggml.bin"

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Length": "100"}
        def getheader(self, k):
            return self.headers.get(k)
        def read(self, chunk):
            raise urllib.error.URLError("boom")
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse())
    monkeypatch.setattr(wc.offline, "require_online", lambda *a: None)

    with pytest.raises(urllib.error.URLError):
        wc.download_default_model(dest=dest)
    assert not dest.exists()
    assert not dest.with_suffix(".bin.part").exists()

def test_backend_load_not_available(monkeypatch):
    monkeypatch.setattr(wc, "is_available", lambda: False)
    b = wc.WhisperCppBackend()
    logs = []
    assert not b.load(status_cb=lambda m: logs.append(m))
    assert "unavailable" in logs[0]
    assert b.get_error()

def test_backend_load_missing_model(monkeypatch, tmp_path):
    monkeypatch.setattr(wc, "is_available", lambda: True)
    monkeypatch.setattr(wc, "default_model_path", lambda: tmp_path / "ggml.bin")
    b = wc.WhisperCppBackend()
    assert not b.load()
    assert "missing" in b.get_error()

def test_backend_load_success(monkeypatch, tmp_path):
    monkeypatch.setattr(wc, "is_available", lambda: True)
    dest = tmp_path / "ggml.bin"
    dest.write_bytes(b"a")
    monkeypatch.setattr(wc, "default_model_path", lambda: dest)

    import sys
    import types
    fake_mod = types.ModuleType("pywhispercpp")
    fake_mod2 = types.ModuleType("pywhispercpp.model")

    class MockModel:
        def __init__(self, *a, **k): pass
    fake_mod2.Model = MockModel
    fake_mod.model = fake_mod2

    monkeypatch.setitem(sys.modules, "pywhispercpp", fake_mod)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", fake_mod2)

    b = wc.WhisperCppBackend()
    assert b.load()
    assert b.is_ready()
    b.unload()
    assert not b.is_ready()

def test_backend_transcribe_checks_ready():
    b = wc.WhisperCppBackend()
    with pytest.raises(RuntimeError, match="not loaded"):
        b.transcribe_to_segments("dummy")

def test_backend_transcribe_inf_nan_duration_validation(monkeypatch):
    b = wc.WhisperCppBackend()
    b._ready = True
    class DummySeg:
        start = 0.0
        end = 1.0
        text = "hi"
    class DummyModel:
        def transcribe(self, *a, **k):
            return [DummySeg()] * 10
    b._model = DummyModel()

    # After the fix, duration will be set to 0.0, so prog will receive 10, 20, 30...
    logs = []
    b.transcribe_to_segments("dummy", duration=float('inf'), progress_cb=lambda x: logs.append(x))
    assert logs == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    logs.clear()
    b.transcribe_to_segments("dummy", duration=float('nan'), progress_cb=lambda x: logs.append(x))
    assert logs == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

def test_backend_transcribe_cancellation(monkeypatch):
    b = wc.WhisperCppBackend()
    b._ready = True
    class DummySeg:
        start = 0.0
        end = 1.0
        text = "hi"
    class DummyModel:
        def transcribe(self, *a, **k): return [DummySeg()] * 10
    b._model = DummyModel()

    cancel_flag = True
    logs = []
    res, _ = b.transcribe_to_segments("dummy", cancelled=lambda: cancel_flag, log_cb=lambda m: logs.append(m))
    assert len(res) == 0
    assert "cancelled" in "".join(logs).lower()
