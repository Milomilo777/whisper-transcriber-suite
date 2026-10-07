"""Format writers for transcribed segments.

Each text writer exposes ``write(segments, audio_path) -> str``
returning the file body. Segments are dicts with at least
``{start, end, text}`` and optionally
``{words: [{start, end, word, probability}, ...], speaker: "Speaker 1"}``.

The ``docx`` writer is binary; it exposes ``write_bytes(segments,
audio_path) -> bytes`` instead. ``BINARY_WRITERS`` carries the
binary set so callers know whether to use ``"wb"`` mode.

The ``smtv_docx`` writer is also binary and fills the transcription
team's bundled template. It needs the detected language and the work
title beyond the frozen ``(segments, audio_path)`` contract, so
``core.transcriber._write_outputs`` special-cases it; the registry
entry below still satisfies ``supported_formats`` / ``is_binary`` so the
Advanced dialog auto-shows a checkbox.

Use :func:`get_writer` for text writers, :func:`get_binary_writer`
for binary writers, and :func:`is_binary` to disambiguate.
"""
from __future__ import annotations

from typing import Callable

from . import (
    ass,
    bilingual_srt,
    docx_writer,
    elan,
    express_scribe,
    inqscribe,
    json_writer,
    lrc,
    md,
    otr,
    pdf_writer,
    smtv_docx_writer,
    srt,
    tsv,
    txt,
    vtt,
)

# bilingual_srt is deliberately NOT in WRITERS/BINARY_WRITERS below: every
# other entry follows the frozen ``write(segments, audio_path) -> str``
# contract, but a bilingual cue needs a second, per-segment translations
# list that doesn't fit that shape (see core/writers/bilingual_srt.py's
# docstring). It's imported here only so it's a proper package member;
# the transcript viewer's AI panel calls bilingual_srt.write() directly.

WriterFn = Callable[[list[dict], str], str]
BinaryWriterFn = Callable[[list[dict], str], bytes]

WRITERS: dict[str, WriterFn] = {
    "srt": srt.write,
    "ass": ass.write,
    "vtt": vtt.write,
    "tsv": tsv.write,
    "txt": txt.write,
    "json": json_writer.write,
    "lrc": lrc.write,
    "md": md.write,
    "otr": otr.write,
    "elan": elan.write,
    "inqscribe": inqscribe.write,
    "express_scribe": express_scribe.write,
}

BINARY_WRITERS: dict[str, BinaryWriterFn] = {
    "docx": docx_writer.write_bytes,
    "pdf": pdf_writer.write_bytes,
    # The SMTV writer's real entry point takes extra keyword args
    # (language / work_title); this 2-arg adapter raises so a caller
    # that bypasses _write_outputs' special case fails loudly rather
    # than silently dropping the language/title.
    "smtv_docx": smtv_docx_writer.write,  # type: ignore[dict-item]
}


def get_writer(name: str) -> WriterFn:
    """Look up a text writer by short format name; raises ``KeyError`` if unknown."""
    return WRITERS[name.lower()]


def get_binary_writer(name: str) -> BinaryWriterFn:
    """Look up a binary writer by short format name; raises ``KeyError`` if unknown."""
    return BINARY_WRITERS[name.lower()]


def is_binary(name: str) -> bool:
    """True iff the named format must be written in binary mode."""
    return name.lower() in BINARY_WRITERS


def supported_formats() -> list[str]:
    return sorted(list(WRITERS.keys()) + list(BINARY_WRITERS.keys()))


# Registry key -> on-disk extension, for the keys whose name is not the
# extension the target tool opens. Every other format is written as
# ``.<key>``. The one table both the transcriber and core.convert use.
#   * elan           -> eaf    (ELAN opens .eaf)
#   * inqscribe      -> inqscr (InqScribe's own extension; plain .txt has
#                               no timestamps)
#   * express_scribe -> txt    (Express Scribe transcripts are plain .txt)
#   * smtv_docx      -> docx   (a ".smtv_docx" file is not a Word document)
FORMAT_EXTENSIONS: dict[str, str] = {
    "elan": "eaf",
    "inqscribe": "inqscr",
    "express_scribe": "txt",
    "smtv_docx": "docx",
}


def extension_for(name: str) -> str:
    """The on-disk extension (no dot) the format *name* is written with."""
    key = name.lower()
    return FORMAT_EXTENSIONS.get(key, key)
