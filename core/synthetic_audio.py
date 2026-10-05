"""Provenance for audio this app synthesises (Clone Your Voice / Text to Voice).

Two local, stdlib-only pieces:

* :func:`tag_wav` marks a finished WAV file as AI-generated with a RIFF
  ``LIST``/``INFO`` chunk: ``ICMT`` (comment) = :data:`AI_COMMENT` and
  ``ISFT`` (software) = app name + version. ffmpeg, Windows Explorer and
  most audio editors read this block. The chunk goes right before the
  ``data`` chunk (where ffmpeg's own WAV muxer puts it), and every other
  chunk, the audio frames included, is copied byte for byte.
* :func:`append_consent_record` appends one JSON line per voice-clone run
  that used reference audio to :func:`consent_log_path` in the user data
  dir. The log stays on this computer: nothing uploads it and it is not
  part of the usage statistics.

Both engines' writers (``core.voice_clone`` and ``core.tts_kokoro``) call
:func:`tag_wav` on every file they produce; the tab's Save button copies
that file unchanged, so a saved copy keeps the tag.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

#: ``ICMT`` text of every synthesised file. Machine-readable on purpose:
#: a fixed string a script can match, not a sentence that gets reworded.
AI_COMMENT = "AI-generated synthetic speech"
APP_DISPLAY_NAME = "Whisper Transcriber Suite"
CONSENT_LOG_NAME = "voice_clone_consent.jsonl"

_COPY_BUFFER = 1 << 20
_MAX_RIFF_SIZE = 0xFFFFFFFF
_REPLACE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8)


def software_name() -> str:
    """``ISFT`` value: app name and the running version."""
    from . import __version__

    return f"{APP_DISPLAY_NAME} {__version__}"


def _info_subchunk(chunk_id: bytes, text: str) -> bytes:
    data = text.encode("utf-8") + b"\x00"  # INFO strings are NUL-terminated
    pad = b"\x00" if len(data) % 2 else b""
    return chunk_id + struct.pack("<I", len(data)) + data + pad


def _parse_info_body(body: bytes) -> "list[tuple[bytes, bytes]]":
    """Split a ``LIST`` body that starts with ``INFO`` into (id, raw data)."""
    items: list[tuple[bytes, bytes]] = []
    pos = 4  # skip the b"INFO" list type
    while pos + 8 <= len(body):
        sub_id, size = struct.unpack("<4sI", body[pos:pos + 8])
        items.append((sub_id, body[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return items


def _scan_chunks(f: BinaryIO, file_size: int) -> "list[tuple[bytes, int, int]]":
    """(chunk id, header offset, body size) of every top-level chunk."""
    f.seek(0)
    header = f.read(12)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    chunks: list[tuple[bytes, int, int]] = []
    pos = 12
    while pos + 8 <= file_size:
        f.seek(pos)
        chunk_id, size = struct.unpack("<4sI", f.read(8))
        if pos + 8 + size > file_size:
            raise ValueError(f"truncated WAV: chunk {chunk_id!r} runs past the end of the file")
        chunks.append((chunk_id, pos, size))
        pos += 8 + size + (size & 1)
    if pos < file_size - 1:  # a lone trailing pad byte is tolerated
        raise ValueError("malformed WAV: trailing bytes after the last chunk")
    ids = [c[0] for c in chunks]
    if b"fmt " not in ids or b"data" not in ids:
        raise ValueError("malformed WAV: no fmt or data chunk")
    return chunks


def _copy_exact(src: BinaryIO, dst: BinaryIO, length: int) -> None:
    remaining = length
    while remaining > 0:
        block = src.read(min(_COPY_BUFFER, remaining))
        if not block:
            raise ValueError("unexpected end of file while copying a chunk")
        dst.write(block)
        remaining -= len(block)


def _replace_with_retry(src: str, dst: str) -> None:
    """``os.replace`` that rides out a short-lived Windows lock.

    A reader without FILE_SHARE_DELETE (antivirus, the search indexer,
    a player) briefly blocks the rename of a file it just opened; the
    last failure is raised unchanged.
    """
    for delay in _REPLACE_RETRY_DELAYS:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(src, dst)


def tag_wav(path: "str | os.PathLike[str]", comment: str = AI_COMMENT,
            software: "str | None" = None) -> None:
    """Add (or update) the ``LIST``/``INFO`` chunk of the WAV at *path*.

    Sets ``ICMT`` = *comment* and ``ISFT`` = *software* (default
    :func:`software_name`) and keeps any other ``INFO`` entries. Writes a
    temp file next to *path* and swaps it in with ``os.replace``, so a
    failure leaves the original file untouched. Raises ``ValueError`` for
    a file that is not a well-formed RIFF/WAVE file.
    """
    path = os.fspath(path)
    software = software_name() if software is None else software
    file_size = os.path.getsize(path)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tag-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    try:
        # fdopen first: if opening *path* fails, the temp's handle is
        # still closed, so the cleanup below can delete it on Windows.
        with os.fdopen(fd, "wb") as dst, open(path, "rb") as src:
            chunks = _scan_chunks(src, file_size)
            kept_info: list[tuple[bytes, bytes]] = []
            for chunk_id, offset, size in chunks:
                if chunk_id == b"LIST" and size >= 4:
                    src.seek(offset + 8)
                    body = src.read(size)
                    if body[:4] == b"INFO":
                        kept_info += [item for item in _parse_info_body(body)
                                      if item[0] not in (b"ICMT", b"ISFT")]
            info = b"INFO" + _info_subchunk(b"ISFT", software) + \
                _info_subchunk(b"ICMT", comment)
            for sub_id, data in kept_info:
                info += sub_id + struct.pack("<I", len(data)) + data + \
                    (b"\x00" if len(data) % 2 else b"")
            list_chunk = b"LIST" + struct.pack("<I", len(info)) + info

            dst.write(b"RIFF\x00\x00\x00\x00WAVE")
            for chunk_id, offset, size in chunks:
                if chunk_id == b"LIST" and size >= 4:
                    src.seek(offset + 8)
                    if src.read(4) == b"INFO":
                        continue  # replaced by list_chunk
                if chunk_id == b"data":
                    dst.write(list_chunk)
                src.seek(offset)
                _copy_exact(src, dst, 8 + size)
                if size & 1:
                    dst.write(b"\x00")
            riff_size = dst.tell() - 8
            if riff_size > _MAX_RIFF_SIZE:
                raise ValueError("WAV file too large to tag (over 4 GB)")
            dst.seek(4)
            dst.write(struct.pack("<I", riff_size))
        shutil.copymode(path, tmp_path)  # mkstemp makes it 0600 on POSIX
        _replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def read_info(path: "str | os.PathLike[str]") -> "dict[str, str]":
    """``INFO`` entries of the WAV at *path* (``{"ICMT": ..., ...}``)."""
    path = os.fspath(path)
    out: dict[str, str] = {}
    with open(path, "rb") as f:
        for chunk_id, offset, size in _scan_chunks(f, os.path.getsize(path)):
            if chunk_id != b"LIST" or size < 4:
                continue
            f.seek(offset + 8)
            body = f.read(size)
            if body[:4] != b"INFO":
                continue
            for sub_id, data in _parse_info_body(body):
                out[sub_id.decode("ascii", "replace")] = \
                    data.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return out


def sha256_file(path: "str | os.PathLike[str]") -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_COPY_BUFFER), b""):
            digest.update(block)
    return digest.hexdigest()


def consent_log_path() -> Path:
    from .config import user_data_dir

    return user_data_dir() / CONSENT_LOG_NAME


def append_consent_record(
    output_path: "str | os.PathLike[str]",
    reference_paths: "list[str]",
    *,
    consent_accepted: bool,
    engine: str,
    log_path: "Path | None" = None,
) -> "dict[str, Any]":
    """Append one JSON line for a generation that used *reference_paths*.

    Fields: ``time_utc``, ``output_file`` (absolute path), ``output_sha256``
    (of the finished, tagged file, so a saved copy can be matched to its
    record), ``reference_sha256`` (one per reference file, in order),
    ``consent_accepted``, ``engine`` and ``app_version``. Returns the
    record. Raises ``OSError`` when the log cannot be written.
    """
    from . import __version__

    if not reference_paths:
        raise ValueError("a consent record needs at least one reference file")
    record: dict[str, Any] = {
        "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_file": os.path.abspath(output_path),
        "output_sha256": sha256_file(output_path),
        "reference_sha256": [sha256_file(p) for p in reference_paths],
        "consent_accepted": bool(consent_accepted),
        "engine": engine,
        "app_version": __version__,
    }
    target = consent_log_path() if log_path is None else log_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
