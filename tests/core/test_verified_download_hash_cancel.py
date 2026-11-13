"""Cancellation stops checksum I/O before consuming the rest of an archive."""
from __future__ import annotations

import builtins
import contextlib
import hashlib
import threading

import pytest

from core import verified_download as vd
from tests.core._fake_file_server import FakeFileServer


PAYLOAD = b"runtime archive payload\n" * 150_000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.mark.parametrize("phase", ["cached", "cached_after_lock", "resumed", "fresh"])
def test_cancel_during_checksum_stops_after_current_block(tmp_path, monkeypatch, phase):
    destination = tmp_path / "runtime.zip"
    partial = vd.part_path(destination)
    watched = destination if phase.startswith("cached") else partial
    if phase == "cached":
        destination.write_bytes(PAYLOAD)
    elif phase == "resumed":
        partial.write_bytes(PAYLOAD)
    if phase == "cached_after_lock":
        lock = vd.exclusive_lock

        @contextlib.contextmanager
        def completed_by_previous_holder(*args, **kwargs):
            with lock(*args, **kwargs):
                destination.write_bytes(PAYLOAD)
                yield

        monkeypatch.setattr(vd, "exclusive_lock", completed_by_previous_holder)
    cancel = threading.Event()
    reads = []
    closed = []

    class ChecksumReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()
            closed.append(self.stream.closed)

        def read(self, size):
            chunk = self.stream.read(size)
            reads.append(len(chunk))
            if chunk:
                cancel.set()
            return chunk

    def open_observed(path, mode="r", *args, **kwargs):
        stream = builtins.open(path, mode, *args, **kwargs)
        return ChecksumReader(stream) if path == watched and mode == "rb" else stream

    monkeypatch.setattr(vd, "open", open_observed, raising=False)
    server = FakeFileServer()
    server.state.payload = PAYLOAD
    try:
        with pytest.raises(vd.DownloadCancelled):
            vd.download_verified(server.url(), destination, size=len(PAYLOAD), sha256=SHA,
                                 what="the runtime", cancel_event=cancel)
        assert reads == [1 << 20], "Cancel must stop before reading the remaining archive"
        assert closed == [True]
        assert watched.read_bytes() == PAYLOAD
        assert server.state.requests == (1 if phase == "fresh" else 0)
        if not phase.startswith("cached"):
            assert not destination.exists()
        requests = server.state.requests
        monkeypatch.setattr(vd, "open", builtins.open)
        cancel.clear()
        assert vd.download_verified(server.url(), destination, size=len(PAYLOAD), sha256=SHA,
                                    what="the runtime", cancel_event=cancel) == destination
        assert destination.read_bytes() == PAYLOAD
        assert server.state.requests == requests
    finally:
        server.close()


def test_checksum_helper_without_cancellation_keeps_its_existing_contract(tmp_path):
    path = tmp_path / "payload"
    path.write_bytes(PAYLOAD)
    assert vd.file_sha256(path, 997) == SHA
    assert vd.is_verified(path, len(PAYLOAD), SHA)
    assert not vd.is_verified(path, len(PAYLOAD), "0" * 64)


def test_cancel_before_cache_check_reads_nothing(tmp_path, monkeypatch):
    destination = tmp_path / "runtime.zip"
    destination.write_bytes(PAYLOAD)
    cancel = threading.Event()
    cancel.set()

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("already-cancelled request read a file")

    monkeypatch.setattr(vd, "open", unexpected_read, raising=False)
    with pytest.raises(vd.DownloadCancelled):
        vd.download_verified("http://127.0.0.1:1/unused", destination, size=len(PAYLOAD),
                             sha256=SHA, what="the runtime", cancel_event=cancel)
