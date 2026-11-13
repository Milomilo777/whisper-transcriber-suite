"""A late response cannot destroy another download's accepted model."""
from __future__ import annotations

import pytest
import errno
import io
import sys
import subprocess
import time
from pathlib import Path
import threading

from core import llm
from core.backends import whisper_cpp


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
@pytest.mark.parametrize("already_present", [False, True], ids=["late-publication", "initial-model"])
def test_unknown_length_response_preserves_concurrently_completed_model(
    tmp_path, monkeypatch, provider, already_present,
):
    dest = tmp_path / "model.bin"
    accepted_size = 100_000_001
    signature = b"previously completed model"
    requests = []

    def publish_completed():
        with dest.open("wb") as stream:
            stream.write(signature)
            stream.truncate(accepted_size)

    class Response:
        headers = {}

        def __enter__(self):
            # The first attempt completes after this attempt's entry check.
            publish_completed()
            return self

        def __exit__(self, *args):
            pass

        def getheader(self, name):
            return None

        def read(self, size):
            if requests[-1]:
                requests[-1] = False
                return b"bad"
            return b""

    def response(*args, **kwargs):
        requests.append(True)
        return Response()

    if already_present:
        publish_completed()
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(provider.urllib.request, "urlopen", response)
    try:
        provider.download_default_model(dest=dest, url="https://models.example.invalid/model")
    except RuntimeError:
        pass  # Rejecting an unverifiable response is also safe.

    assert bool(requests) is not already_present
    assert dest.stat().st_size == accepted_size
    with dest.open("rb") as stream:
        assert stream.read(len(signature)) == signature
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
def test_unavailable_publication_lock_preserves_previous_file(tmp_path, monkeypatch, provider):
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"previous partial model")
    logs = []

    class Response(io.BytesIO):
        headers = {"content-length": "3"}

        def getheader(self, name):
            return self.headers.get(name.lower())

    def unavailable(*args):
        raise OSError(errno.ENOSYS, "Synthetic unavailable lock")

    if sys.platform == "win32":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", unavailable)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", unavailable)
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response(b"bad"))
    with pytest.raises(RuntimeError, match="lock"):
        provider.download_default_model(dest=dest, log=logs.append)
    assert dest.read_bytes() == b"previous partial model"
    assert not list(tmp_path.glob("*.part"))
    assert not any(v.startswith(("Done:", "LLM model ready")) for v in logs)


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
def test_publication_respects_an_actual_other_process_lock(tmp_path, monkeypatch, provider):
    dest = tmp_path / "model.bin"
    ready, release = tmp_path / "ready", tmp_path / "release"
    children = []
    script = """
from pathlib import Path
import sys,time
from core.verified_download import exclusive_lock
dest,ready,release=map(Path,sys.argv[1:])
with exclusive_lock(dest.with_name(dest.name+'.lock'),'busy'):
    with dest.open('wb') as stream:
        stream.write(b'completed by another process')
        stream.truncate(100000001)
    ready.write_text('ready')
    deadline=time.monotonic()+15
    while not release.exists():
        if time.monotonic()>deadline:raise RuntimeError('test release timed out')
        time.sleep(.01)
"""

    class Response(io.BytesIO):
        headers = {"content-length": "3"}

        def getheader(self, name):
            return self.headers.get(name.lower())

        def __enter__(self):
            child = subprocess.Popen([sys.executable, "-c", script, str(dest), str(ready), str(release)],
                                     cwd=Path(__file__).resolve().parents[2],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(child)
            deadline = time.monotonic() + 8
            while not ready.exists():
                assert child.poll() is None, child.communicate()[1].decode(errors="replace")
                assert time.monotonic() < deadline
                time.sleep(.01)
            return self

    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response(b"bad"))
    try:
        with pytest.raises(RuntimeError, match="published"):
            provider.download_default_model(dest=dest)
        assert dest.stat().st_size == 100_000_001
        with dest.open("rb") as stream:
            assert stream.read(28) == b"completed by another process"
        assert not list(tmp_path.glob("*.part"))
    finally:
        release.write_text("release", encoding="utf-8")
        for child in children:
            _out, error = child.communicate(timeout=20)
            assert child.returncode == 0, error.decode(errors="replace")


@pytest.mark.parametrize("cancel_at", ["eof", "flush"])
def test_gguf_cancel_before_publication_preserves_previous_file(tmp_path, monkeypatch, cancel_at):
    from core import _checkpoint

    dest = tmp_path / "model.gguf"
    dest.write_bytes(b"previous partial")
    cancelled = threading.Event()

    class Response(io.BytesIO):
        headers = {"content-length": "3"}

        def read(self, size=-1):
            chunk = super().read(size)
            if not chunk and cancel_at == "eof":
                cancelled.set()
            return chunk

    flush = _checkpoint._flush_to_disk

    def finish_flush(stream):
        flush(stream)
        if cancel_at == "flush":
            cancelled.set()

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", finish_flush)
    monkeypatch.setattr(llm.offline, "require_online", lambda *a: None)
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: Response(b"new"))
    with pytest.raises(RuntimeError, match="cancelled"):
        llm.download_default_model(dest=dest, cancel_event=cancelled)
    assert dest.read_bytes() == b"previous partial"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
def test_two_completed_download_calls_preserve_the_first_accepted_model(tmp_path, monkeypatch, provider):
    dest = tmp_path / "model.bin"
    waiting, release = threading.Event(), threading.Event()
    results, errors = [], []
    accepted_size = 100_000_001

    class Response:
        def __init__(self, first):
            self.first = first
            self.remaining = 3 if first else accepted_size
            self.headers = {"content-length": str(self.remaining)}

        def getheader(self, name):
            return self.headers.get(name.lower())

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            if not self.remaining:
                if self.first:
                    waiting.set()
                    assert release.wait(10), "Competing transfer did not finish"
                return b""
            length = min(size, self.remaining)
            self.remaining -= length
            return (b"A" if self.first else b"B") * length

    def response(request, **kwargs):
        url = getattr(request, "full_url", request)
        return Response(url.endswith("first"))

    def first_download():
        try:
            results.append(provider.download_default_model(dest=dest, url="https://models.example.invalid/first"))
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(provider.offline, "require_online", lambda *a: None)
    monkeypatch.setattr(provider.urllib.request, "urlopen", response)
    first = threading.Thread(target=first_download)
    first.start()
    try:
        assert waiting.wait(5)
        results.append(provider.download_default_model(dest=dest, url="https://models.example.invalid/second"))
    finally:
        release.set()
        first.join(15)
    assert not first.is_alive() and errors == []
    assert results == [str(dest), str(dest)]
    assert dest.stat().st_size == accepted_size
    with dest.open("rb") as stream:
        assert stream.read(32) == b"B" * 32
    assert not list(tmp_path.glob("*.part"))
