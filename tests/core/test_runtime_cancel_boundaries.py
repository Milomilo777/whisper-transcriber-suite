"""Cancellation before publication retains verified bytes for a cheap retry."""
import hashlib
import os
import threading

import pytest

from core import llama_runtime as lr, verified_download as vd
from tests.core.test_llama_runtime import cache, server, _serve, _zip, _leftovers, EXE  # noqa: F401


@pytest.mark.parametrize("phase", ["sync", "checksum", "rename_retry"])
def test_cancel_after_payload_keeps_complete_partial(server, tmp_path, monkeypatch, phase):
    data = b"synthetic verified runtime bytes\n" * 1000
    server.state.payload = data
    dest = tmp_path / "archive.bin"
    part = vd.part_path(dest)
    cancel = threading.Event()
    def download():
        return vd.download_verified(server.url(), dest, size=len(data),
                                    sha256=hashlib.sha256(data).hexdigest(), what="test runtime",
                                    cancel_event=cancel)
    with monkeypatch.context() as patch:
        if phase == "sync":
            sync = os.fsync
            def synced(fd):
                sync(fd)
                if part.exists() and os.fstat(fd).st_ino == part.stat().st_ino:
                    cancel.set()
            patch.setattr(vd.os, "fsync", synced)
        elif phase == "checksum":
            checksum = vd.file_sha256
            def checked(path, *args, **kwargs):
                result = checksum(path, *args, **kwargs)
                if path == part:
                    cancel.set()
                return result
            patch.setattr(vd, "file_sha256", checked)
        else:
            replace = os.replace
            def busy(src, dst):
                if src == part and dst == dest and not cancel.is_set():
                    cancel.set()
                    raise PermissionError("synthetic busy destination")
                return replace(src, dst)
            patch.setattr(vd.os, "replace", busy)
            import time
            patch.setattr(time, "sleep", lambda _: None)
        with pytest.raises(vd.DownloadCancelled):
            download()
    assert not dest.exists()
    assert part.read_bytes() == data
    requests = server.state.requests
    cancel.clear()
    assert download() == dest
    assert dest.read_bytes() == data and server.state.requests == requests


def test_already_cancelled_verified_cache_does_not_report_a_new_success(server, tmp_path):
    data = b"synthetic verified cache"
    dest = tmp_path / "archive.bin"
    dest.write_bytes(data)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(vd.DownloadCancelled):
        vd.download_verified(server.url(), dest, size=len(data),
                             sha256=hashlib.sha256(data).hexdigest(), what="test runtime",
                             cancel_event=cancel)
    assert dest.read_bytes() == data and server.state.requests == 0


@pytest.mark.parametrize("phase", ["download", "extract", "dependencies"])
def test_runtime_cancel_before_publication_keeps_verified_archive(server, cache, monkeypatch, phase):
    data = _zip({EXE: b"synthetic executable"})
    asset = _serve(server, data, "llama-bX-bin-test.zip")
    cancel = threading.Event()
    with monkeypatch.context() as patch:
        if phase == "download":
            download = vd.download_verified
            def downloaded(*args, **kwargs):
                result = download(*args, **kwargs)
                cancel.set()
                return result
            patch.setattr(vd, "download_verified", downloaded)
        elif phase == "extract":
            extract = lr.extract_archive
            def extracted(*args, **kwargs):
                result = extract(*args, **kwargs)
                cancel.set()
                return result
            patch.setattr(lr, "extract_archive", extracted)
        else:
            def dependencies(_):
                cancel.set()
                return []
            patch.setattr(lr, "ensure_vc_runtime", dependencies)
        with pytest.raises(vd.DownloadCancelled):
            lr.install_runtime(base_url=server.base_url, asset=asset, cancel_event=cancel)
    assert lr.installed_server() is None and _leftovers(cache) == []
    archive = lr.runtime_root() / "downloads" / asset.name
    assert archive.read_bytes() == data
    requests = server.state.requests
    cancel.clear()
    assert lr.install_runtime(base_url=server.base_url, asset=asset).read_bytes() == b"synthetic executable"
    assert server.state.requests == requests


def test_cancel_after_publication_does_not_remove_completed_install(server, cache, monkeypatch):
    asset = _serve(server, _zip({EXE: b"synthetic executable"}), "llama-bX-bin-test.zip")
    cancel = threading.Event()
    publish = lr._move_into_place
    def published(*args, **kwargs):
        result = publish(*args, **kwargs)
        cancel.set()
        return result
    monkeypatch.setattr(lr, "_move_into_place", published)
    result = lr.install_runtime(base_url=server.base_url, asset=asset, cancel_event=cancel)
    assert result == lr.installed_server() and result.read_bytes() == b"synthetic executable"
