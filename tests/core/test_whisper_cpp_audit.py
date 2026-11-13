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


# Downloads from separate windows must not share a writable staging file.
class _CppBytesResponse:
    def __init__(self, chunks, before_second=None, failure=None, on_first=None):
        self.chunks = list(chunks)
        self.total = sum(len(chunk) for chunk in chunks)
        self.before_second, self.failure, self.on_first = before_second, failure, on_first
        self.reads = 0

    def getheader(self, name):
        return str(self.total)

    def read(self, count):
        self.reads += 1
        if self.reads == 1 and self.on_first:
            self.on_first()
        if self.reads == 2:
            if self.before_second:
                self.before_second()
            if self.failure:
                raise self.failure
        return self.chunks.pop(0) if self.chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


@pytest.mark.parametrize("second_fails", [False, True])
def test_cpp_overlapping_downloads_keep_their_own_bytes(tmp_path, monkeypatch, second_fails):
    import threading

    dest = tmp_path / "ggml.bin"
    first_written, release_first = threading.Event(), threading.Event()
    results, failures = [], []
    first_bytes = b"A" * 32768

    def hold_first():
        first_written.set()
        if not release_first.wait(5):
            raise RuntimeError("synthetic download interleave timed out")

    def response(url, timeout):
        if url.endswith("first"):
            return _CppBytesResponse([first_bytes[:16384], first_bytes[16384:]], before_second=hold_first)
        return _CppBytesResponse([b"B" * 16384], failure=urllib.error.URLError("second download failed")
                                 if second_fails else None)

    def first_download():
        try:
            results.append(wc.download_default_model(dest=dest, url="https://model.invalid/first"))
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(wc.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(wc.urllib.request, "urlopen", response)
    worker = threading.Thread(target=first_download, name="wts-cpp-first")
    worker.start()
    try:
        assert first_written.wait(5)
        if second_fails:
            with pytest.raises(urllib.error.URLError, match="second download failed"):
                wc.download_default_model(dest=dest, url="https://model.invalid/second")
        else:
            assert wc.download_default_model(dest=dest, url="https://model.invalid/second") == str(dest)
    finally:
        release_first.set()
        worker.join(5)
    assert not worker.is_alive()
    assert failures == [] and results == [str(dest)]
    assert dest.read_bytes() == first_bytes
    assert not list(tmp_path.glob("*.part"))


def test_cpp_download_preserves_an_older_fixed_partial(tmp_path, monkeypatch):
    dest = tmp_path / "ggml.bin"
    older = tmp_path / "ggml.bin.part"
    original = b"retained previous download"
    older.write_bytes(original)
    monkeypatch.setattr(wc.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(wc.urllib.request, "urlopen", lambda *args, **kwargs: _CppBytesResponse([b"new model"]))
    assert wc.download_default_model(dest=dest) == str(dest)
    assert dest.read_bytes() == b"new model" and older.read_bytes() == original
    assert list(tmp_path.glob("*.part")) == [older]


@pytest.mark.parametrize("directory_races", [False, True])
def test_cpp_download_never_places_model_inside_destination_directory(tmp_path, monkeypatch, directory_races):
    dest = tmp_path / "ggml.bin"
    logs, requests = [], []

    def make_directory():
        dest.mkdir()
        (dest / "retained.txt").write_bytes(b"retained original")

    if not directory_races:
        make_directory()

    def response(*args, **kwargs):
        requests.append(True)
        return _CppBytesResponse([b"new model"], on_first=make_directory if directory_races else None)

    monkeypatch.setattr(wc.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(wc.urllib.request, "urlopen", response)
    with pytest.raises(OSError):
        wc.download_default_model(dest=dest, log=logs.append)
    assert (dest / "retained.txt").read_bytes() == b"retained original"
    assert sorted(path.name for path in dest.iterdir()) == ["retained.txt"]
    assert not list(tmp_path.glob("*.part"))
    assert not any(message.startswith("Done:") for message in logs)
    assert bool(requests) is directory_races


def test_cpp_sync_error_never_reports_a_ready_model(tmp_path, monkeypatch):
    from core import _checkpoint

    dest = tmp_path / "ggml.bin"
    logs = []
    monkeypatch.setattr(wc.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(wc.urllib.request, "urlopen", lambda *args, **kwargs: _CppBytesResponse([b"new model"]))

    def cannot_sync(stream):
        raise OSError("synthetic model sync failure")

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", cannot_sync)
    with pytest.raises(OSError, match="model sync failure"):
        wc.download_default_model(dest=dest, log=logs.append)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))
    assert not any(message.startswith("Done:") for message in logs)


@pytest.mark.parametrize("content_length", [None, "0"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("payload", [b"", b"complete synthetic model"])
def test_model_response_without_positive_length_must_not_install_empty_file(
    tmp_path, monkeypatch, content_length, existing, payload,
):
    import io

    dest = tmp_path / "downloaded-model.bin"
    original = b"retained previous model"
    if existing:
        dest.write_bytes(original)
    response = io.BytesIO(payload)
    response.headers = {} if content_length is None else {"content-length": content_length}
    response.getheader = lambda name: content_length
    logs = []
    monkeypatch.setattr(wc.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(wc.urllib.request, "urlopen", lambda *args, **kwargs: response)
    if payload:
        assert wc.download_default_model(dest=dest, log=logs.append) == str(dest)
        assert dest.read_bytes() == payload
    else:
        with pytest.raises(RuntimeError, match="empty"):
            wc.download_default_model(dest=dest, log=logs.append)
        assert dest.read_bytes() == original if existing else not dest.exists()
        assert not any("ready" in text.lower() or text.startswith("Done:") for text in logs)
    assert not list(tmp_path.glob("*.part"))
