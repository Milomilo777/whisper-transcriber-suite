"""Local storage latency must not consume a model mirror's network budgets."""
from __future__ import annotations

import contextlib
import hashlib
import io
import socket
import time

import pytest

from core import model_download as md


@pytest.mark.parametrize("operation,delay", [("none", 0), ("open", 40),
                                             ("write", 40), ("write", 130)])
def test_ready_payload_survives_local_storage_wait(tmp_path, monkeypatch, operation, delay):
    data = b"model payload across multiple reads"
    real_clock = time.monotonic
    elapsed = [0.0]
    clock = lambda: real_clock() + elapsed[0]
    monkeypatch.setattr(md.time, "monotonic", clock)
    client = md.ModelDownloader(hosts=[], chunk_size=4)
    client._rate_clock = clock
    client._rate = md._MinimumRate(clock)
    original = md.verified.open_part
    waits = []

    class SlowStorage:
        def __init__(self, stream):
            self.stream = stream

        def fileno(self):
            return self.stream.fileno()

        def write(self, chunk):
            result = self.stream.write(chunk)
            if operation == "write":
                elapsed[0] += delay
                waits.append(delay)
            return result

        def flush(self):
            self.stream.flush()

    @contextlib.contextmanager
    def open_storage(*args, **kwargs):
        with original(*args, **kwargs) as stream:
            if operation == "open":
                elapsed[0] += delay
                waits.append(delay)
            yield SlowStorage(stream)

    monkeypatch.setattr(md.verified, "open_part", open_storage)
    receiver, sender = socket.socketpair()
    receiver.settimeout(3)
    try:
        sender.sendall(data)
        sender.shutdown(socket.SHUT_WR)
        raw = md._SocketReader(receiver, None, 30, None, client._rate)
        with io.BufferedReader(raw) as body:
            class Response:
                download_reader = raw
                read1 = body.read1

            part = tmp_path / "model.bin.part"
            info = md.FileInfo(len(data), hashlib.sha256(data).hexdigest())
            assert client._receive(Response(), part, 0, info, None) == info.sha256
        assert part.read_bytes() == data
        if delay:
            assert waits and sum(waits) >= delay
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("rate", [False, True])
def test_actual_network_wait_still_exhausts_its_budget(tmp_path, monkeypatch, rate):
    real_clock = time.monotonic
    elapsed = [0.0]
    clock = lambda: real_clock() + elapsed[0]
    monkeypatch.setattr(md.time, "monotonic", clock)
    client = md.ModelDownloader(hosts=[], chunk_size=4)
    client._rate_clock = clock
    client._rate = md._MinimumRate(clock)
    receiver, sender = socket.socketpair()
    receiver.settimeout(3)
    try:
        sender.sendall(b"payload")
        raw = md._SocketReader(receiver, None, 1000 if rate else 30, None, client._rate)
        with io.BufferedReader(raw) as body:
            class Response:
                download_reader = raw

                @staticmethod
                def read1(size):
                    elapsed[0] += 130 if rate else 40
                    return body.read1(size)

            expected = md._HostUnavailable if rate else md._Stalled
            with pytest.raises(expected):
                client._receive(Response(), tmp_path / "model.bin.part", 0,
                                md.FileInfo(7, hashlib.sha256(b"payload").hexdigest()), None)
    finally:
        receiver.close()
        sender.close()


def test_storage_wait_does_not_reset_accumulated_network_time(tmp_path, monkeypatch):
    real_clock = time.monotonic
    elapsed = [0.0]
    clock = lambda: real_clock() + elapsed[0]
    monkeypatch.setattr(md.time, "monotonic", clock)
    client = md.ModelDownloader(hosts=[], chunk_size=4)
    client._rate_clock = clock
    client._rate = md._MinimumRate(clock)
    original = md.verified.open_part
    writes = []

    class Storage:
        def __init__(self, stream):
            self.stream = stream

        def fileno(self):
            return self.stream.fileno()

        def write(self, chunk):
            self.stream.write(chunk)
            elapsed[0] += 130
            writes.append(chunk)

        def flush(self):
            self.stream.flush()

    @contextlib.contextmanager
    def open_storage(*args, **kwargs):
        with original(*args, **kwargs) as stream:
            yield Storage(stream)

    monkeypatch.setattr(md.verified, "open_part", open_storage)
    receiver, sender = socket.socketpair()
    receiver.settimeout(3)
    try:
        sender.sendall(b"partial payload")
        sender.shutdown(socket.SHUT_WR)
        raw = md._SocketReader(receiver, None, 1000, None, client._rate)
        with io.BufferedReader(raw) as body:
            class Response:
                download_reader = raw

                @staticmethod
                def read1(size):
                    elapsed[0] += 70
                    return body.read1(size)

            with pytest.raises(md._HostUnavailable, match="repeated download stalls"):
                client._receive(Response(), tmp_path / "model.bin.part", 0,
                                md.FileInfo(15, hashlib.sha256(b"partial payload").hexdigest()), None)
        assert writes == [b"part"]
        assert elapsed[0] == 270  # 140 network seconds plus 130 storage seconds.
    finally:
        receiver.close()
        sender.close()


def test_public_download_publishes_after_slow_storage(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    data = b"pinned model payload for a real HTTP transfer"
    real_clock = time.monotonic
    elapsed = [0.0]
    clock = lambda: real_clock() + elapsed[0]
    monkeypatch.setattr(md.time, "monotonic", clock)
    original = md.verified.open_part

    class Storage:
        def __init__(self, stream):
            self.stream = stream

        def fileno(self):
            return self.stream.fileno()

        def write(self, chunk):
            result = self.stream.write(chunk)
            elapsed[0] += 130
            return result

        def flush(self):
            self.stream.flush()

    @contextlib.contextmanager
    def open_storage(*args, **kwargs):
        with original(*args, **kwargs) as stream:
            yield Storage(stream)

    monkeypatch.setattr(md.verified, "open_part", open_storage)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()

        def do_GET(self):
            self.do_HEAD()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = md.ModelDownloader(hosts=[f"http://127.0.0.1:{server.server_port}"],
                                    retry_delays=(), max_stalls=1, chunk_size=4)
        client._rate_clock = clock
        info = md.FileInfo(len(data), hashlib.sha256(data).hexdigest())
        entry = md.ManifestEntry("a" * 40, {"model.bin": info})
        assert client.download("fixture/tiny", tmp_path, entry)
        assert (tmp_path / "model.bin").read_bytes() == data
        assert not (tmp_path / "model.bin.part").exists()
        assert not client.unavailable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
