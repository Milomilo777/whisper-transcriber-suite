"""Hermetic regression test for the cloud-STT blob-cleanup fix.

DEFECT (LOW): on the Files-API path, ``_upload_file`` finalizes the
uploaded blob on Google's servers and then, when the file is not yet
ACTIVE, calls ``_wait_for_active`` BEFORE returning ``(file_uri,
file_name)``. If ``_wait_for_active`` raises (poll timeout, state
FAILED, or an HTTP / URL error), ``_upload_file`` never returns the
tuple, so the caller's ``finally: self._delete_file(file_name)`` never
runs (``file_name`` was never bound there) and the just-uploaded audio
blob is left on Google until its ~48 h auto-expiry — violating the
backend's "delete the uploaded blob on success OR failure" contract.

FIX: ``_upload_file`` now wraps the post-finalize wait-for-active so that
if it raises, ``self._delete_file(str(file_name))`` is attempted
best-effort before the exception is re-raised.

This test drives ``_upload_file`` directly with ``_wait_for_active`` and
``_delete_file`` stubbed, asserts the exception still propagates, and
asserts the blob was deleted with the uploaded file name. It FAILS on the
pre-fix code (no delete happens). NO network, NO API key beyond a fake
config value, NO model, NO Tk.
"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest

from core.backends import cloud_stt as cs


# ---------------------------------------------------------------- fakes


class _FakeResp:
    """Minimal context-manager stand-in for an http.client response."""

    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None):
        self._buf = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, n: int = -1) -> bytes:
        return self._buf.read() if n == -1 else self._buf.read(n)


def _make_urlopen(recorder: list[Any], responder):
    def _urlopen(req, timeout=None):  # noqa: ANN001
        recorder.append(req)
        return responder(req)

    return _urlopen


def _backend() -> cs.CloudSttBackend:
    b = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "SECRET-KEY-123", "cloud_stt_model": "m"}
    )
    assert b.load() is True
    return b


# ---------------------------------------------------------------- the fix


def test_upload_deletes_blob_when_wait_for_active_raises(monkeypatch, tmp_path):
    """If the post-finalize wait-for-active poll raises, the just-uploaded
    blob must be deleted best-effort and the error must still propagate."""
    flac = tmp_path / "big.flac"
    flac.write_bytes(b"x" * 64)
    num_bytes = flac.stat().st_size

    recorded: list[Any] = []

    def responder(req):  # noqa: ANN001
        url = req.full_url
        if url.endswith("/upload/v1beta/files"):
            # start: hand back the resumable upload session URL.
            return _FakeResp(b"", {"X-Goog-Upload-URL": "https://upload.example/session"})
        if url == "https://upload.example/session":
            # upload+finalize: blob is now on Google, but NOT yet ACTIVE,
            # so _upload_file proceeds to _wait_for_active.
            meta = {"file": {"uri": "https://files/leak", "name": "files/leak",
                             "state": "PROCESSING"}}
            return _FakeResp(json.dumps(meta).encode("utf-8"))
        raise AssertionError(f"unexpected request: {req.get_method()} {url}")

    monkeypatch.setattr(
        cs.urllib.request, "urlopen", _make_urlopen(recorded, responder)
    )

    b = _backend()

    # Make the wait-for-active poll fail the way a real timeout / FAILED state
    # / HTTP error would.
    def boom_wait(file_name: str) -> None:
        raise RuntimeError("Timed out waiting for Google to process the audio.")

    monkeypatch.setattr(b, "_wait_for_active", boom_wait)

    deleted: list[str | None] = []
    monkeypatch.setattr(b, "_delete_file", lambda name, log_cb=None: deleted.append(name))

    with pytest.raises(RuntimeError):
        b._upload_file(str(flac), num_bytes)

    assert deleted == ["files/leak"], (
        "the just-uploaded blob must be deleted when _wait_for_active raises"
    )


def test_upload_returns_tuple_and_does_not_delete_on_active(monkeypatch, tmp_path):
    """When the file IS already ACTIVE, _upload_file returns the tuple and
    does NOT pre-emptively delete (the caller owns cleanup on this path)."""
    flac = tmp_path / "big.flac"
    flac.write_bytes(b"x" * 64)
    num_bytes = flac.stat().st_size

    recorded: list[Any] = []

    def responder(req):  # noqa: ANN001
        url = req.full_url
        if url.endswith("/upload/v1beta/files"):
            return _FakeResp(b"", {"X-Goog-Upload-URL": "https://upload.example/session"})
        if url == "https://upload.example/session":
            meta = {"file": {"uri": "https://files/ok", "name": "files/ok",
                             "state": "ACTIVE"}}
            return _FakeResp(json.dumps(meta).encode("utf-8"))
        raise AssertionError(f"unexpected request: {req.get_method()} {url}")

    monkeypatch.setattr(
        cs.urllib.request, "urlopen", _make_urlopen(recorded, responder)
    )

    b = _backend()

    deleted: list[str | None] = []
    monkeypatch.setattr(b, "_delete_file", lambda name, log_cb=None: deleted.append(name))

    file_uri, file_name = b._upload_file(str(flac), num_bytes)
    assert file_uri == "https://files/ok"
    assert file_name == "files/ok"
    assert deleted == []  # no pre-emptive delete on the happy path
