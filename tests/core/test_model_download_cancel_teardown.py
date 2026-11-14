"""A cancellation must survive locked restart-file cleanup."""
import hashlib
import threading
import time
from pathlib import Path
from core import model_download as md
from tests.core.test_verified_download_cancel_io import _Server, _stall


def test_cancel_survives_failing_restart_unlink(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "_FILE_RETRY_TIMEOUT", 3)
    real_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path.name.endswith(".restart"):
            raise PermissionError("synthetic scanner")
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    part = tmp_path / "f.part"
    part.write_bytes(b"d")
    info = md.FileInfo(4, hashlib.sha256(b"data").hexdigest())
    server = _Server([_stall(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nd")])
    cancel, errors = threading.Event(), []
    def work():
        try:
            md.ModelDownloader(hosts=[])._transfer(server.url, part, info, cancel)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    try:
        restart = tmp_path / ".f.part.restart"
        deadline = time.monotonic() + 2
        while not restart.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert restart.exists()
        cancel.set()
        thread.join(1)
        assert not thread.is_alive(), "cleanup retry held Cancel"
        assert len(errors) == 1 and isinstance(errors[0], md._Cancelled)
        assert server.peer_closed.wait(1)
        assert part.read_bytes() == b"d"
    finally:
        cancel.set()
        server.close()
        thread.join(4)


def test_rejected_restart_path_is_not_cleaned_up(tmp_path, monkeypatch):
    import contextlib
    from types import SimpleNamespace
    import pytest
    part = tmp_path / "f.part"
    part.write_bytes(b"d")
    restart = tmp_path / ".f.part.restart"
    restart.write_bytes(b"foreign path")
    actual_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == restart or actual_is_symlink(p))
    downloader = md.ModelDownloader(hosts=[])
    monkeypatch.setattr(downloader, "_open", lambda *a: contextlib.nullcontext(SimpleNamespace(status=200)))
    info = md.FileInfo(4, hashlib.sha256(b"data").hexdigest())
    with pytest.raises(md.mm.ModelDestinationNotWritable):
        downloader._fetch("https://example.invalid/file", part, info, None)
    assert restart.read_bytes() == b"foreign path"
    assert part.read_bytes() == b"d"
