from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from core import synthetic_audio as sa


def create_mock_wav(path: str | Path, chunks: list[tuple[bytes, bytes]]) -> None:
    # chunk is (id, data)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        # size will be calculated
        body = b"WAVE"
        for chunk_id, data in chunks:
            body += chunk_id + struct.pack("<I", len(data)) + data
            if len(data) % 2:
                body += b"\x00"
        f.write(struct.pack("<I", len(body)))
        f.write(body)

def test_tag_wav_raises_on_truncated_file(tmp_path):
    wav_path = tmp_path / "test.wav"
    create_mock_wav(wav_path, [(b"fmt ", b"1234"), (b"data", b"1234")])
    # truncate it
    with open(wav_path, "ab") as f:
        f.truncate(16)
    with pytest.raises(ValueError, match="malformed WAV: trailing bytes|runs past the end"):
        sa.tag_wav(wav_path)

def test_tag_wav_calls_fsync(tmp_path, monkeypatch):
    wav_path = tmp_path / "fsync.wav"
    create_mock_wav(wav_path, [(b"fmt ", b"\x01" + b"\x00"*15), (b"data", b"\x00" * 10)])
    fsyncs = []
    monkeypatch.setattr(os, "fsync", lambda fd: fsyncs.append(fd))
    sa.tag_wav(wav_path)
    assert len(fsyncs) == 1
