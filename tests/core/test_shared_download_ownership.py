"""Shared resume bytes require confirmed ownership before any transfer."""
from contextlib import ExitStack
import errno
import hashlib
import os
from types import SimpleNamespace

import pytest

from core import model_download as md, verified_download as vd
from tests.core._fake_file_server import FakeFileServer
from tests.core.test_model_download import Server, downloader, entry


@pytest.fixture(params=["verified", "manifest"])
def target(request, tmp_path, monkeypatch):
    data = b"complete verified model data\n" * 1024
    monkeypatch.setattr(vd.offline, "require_online", lambda *args: None)
    with ExitStack() as stack:
        if request.param == "verified":
            server = FakeFileServer()
            stack.callback(server.close)
            server.state.payload = data
            dest = tmp_path / "file.bin"
            run = lambda: vd.download_verified(server.url(), dest, size=len(data),
                                              sha256=hashlib.sha256(data).hexdigest(), what="test model")
            requests = lambda: server.state.requests
        else:
            server = stack.enter_context(Server(data=data))
            dest = tmp_path / "model.bin"
            run = lambda: downloader(server.url).download("fixture/tiny", tmp_path, entry(data))
            requests = lambda: len(server.gets) + len(server.heads)
        yield SimpleNamespace(data=data, dest=dest, part=vd.part_path(dest), run=run, requests=requests)


def block_native_lock(monkeypatch, error_number):
    def unavailable(*args):
        raise OSError(error_number, "Synthetic unavailable or denied lock")

    if os.name == "nt":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", unavailable)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", unavailable)


@pytest.mark.parametrize("error_number", [errno.EINVAL, errno.ENOLCK, errno.EACCES])
def test_unconfirmed_lock_cannot_rewrite_another_producers_prefix(target, monkeypatch, error_number):
    previous = b"another producer's resume bytes"
    target.part.write_bytes(previous)
    block_native_lock(monkeypatch, error_number)
    error = None
    try:
        target.run()
    except (vd.DownloadError, md.mm.HuggingFaceDownloadError) as caught:
        error = caught
    assert target.part.is_file(), "Lock failure must not delete another producer's prefix"
    assert target.part.read_bytes() == previous
    assert not target.dest.exists()
    assert target.requests() == 0
    assert error is not None


def test_confirmed_ownership_still_resumes_and_verifies(target):
    target.part.write_bytes(target.data[:513])
    target.run()
    assert target.dest.read_bytes() == target.data
    assert not target.part.exists() and target.requests() > 0


def test_an_already_verified_install_needs_no_write_lock(target, monkeypatch):
    target.dest.write_bytes(target.data)
    block_native_lock(monkeypatch, errno.ENOLCK)
    target.run()
    assert target.dest.read_bytes() == target.data and target.requests() == 0
