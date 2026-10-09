"""Multipart parser defect from an external review pass (branch fix/gemini-b1).

The on-disk parser lost the CRLF in front of the file part's closing boundary
when that boundary started in the first two bytes of the trailing window, so
the saved media got two stray bytes.

Hermetic: temp files only.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from core.server.httpd import (
    _MULTIPART_HEADER_WINDOW,
    _MULTIPART_TAIL_WINDOW,
    JobRequestHandler,
)

_BOUNDARY = "----GeminiB1Boundary"


def _body_with_closing_boundary_at(payload: bytes, offset_in_tail: int) -> bytes:
    """Multipart body whose file-closing boundary starts ``offset_in_tail`` bytes
    into the trailing window (the last ``_MULTIPART_TAIL_WINDOW`` bytes).

    One big text field after the file part sets how many bytes follow the
    closing boundary; its length is solved for.
    """
    delim = b"--" + _BOUNDARY.encode("latin-1")
    head = (
        delim + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="clip.mp4"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        + payload + b"\r\n"
    )
    field_head = delim + b"\r\nContent-Disposition: form-data; name=\"options\"\r\n\r\n"
    closing = b"\r\n" + delim + b"--\r\n"
    wanted_after_boundary = _MULTIPART_TAIL_WINDOW - offset_in_tail
    value_len = wanted_after_boundary - len(field_head) - len(closing)
    assert value_len > 0
    return head + field_head + b"x" * value_len + closing


def _extract(body: bytes):
    fd, tmp = tempfile.mkstemp(prefix="gemini-b1-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        name, start, end, fields = JobRequestHandler._extract_upload_from_file(
            tmp, len(body), _BOUNDARY)
        with open(tmp, "rb") as f:
            f.seek(start)
            media = f.read(end - start)
        return name, media, fields
    finally:
        os.unlink(tmp)


@pytest.mark.parametrize("offset", [0, 1, 2, 3])
def test_closing_boundary_at_the_start_of_the_tail_window_keeps_media_exact(offset):
    payload = bytes(range(256)) * ((_MULTIPART_HEADER_WINDOW // 256) + 64)
    body = _body_with_closing_boundary_at(payload, offset)
    # The boundary really sits `offset` bytes into the window.
    tail = body[len(body) - _MULTIPART_TAIL_WINDOW:]
    assert tail.find(b"--" + _BOUNDARY.encode("latin-1")) == offset
    name, media, fields = _extract(body)
    assert name == "clip.mp4"
    assert media == payload
    assert fields.get("options", "").startswith("x")
