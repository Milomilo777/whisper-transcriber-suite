"""Bilingual SubRip writer — original + translated line per cue.

NOT registered in ``core.writers.WRITERS``. Every other writer follows
the frozen ``write(segments, audio_path) -> str`` contract; this one
needs a second, per-segment ``translations`` list, which doesn't fit
that shape (the same reason ``smtv_docx`` gets a special case in
``core.transcriber._write_outputs`` instead of joining the plain
registry). Unlike smtv_docx this isn't a pipeline output-format
checkbox at all — it only ever runs on demand, after a translation
pass, from the transcript viewer's AI panel
(``app/dialogs/transcript_viewer.py``), which is the only caller.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import zipfile

from .base import (
    escape_cue_separator,
    fmt_srt_time,
    normalize_text,
    speaker_prefix,
    prepare_cues,
)


def write(
    segments: list[dict],
    translations: list[str],
    audio_path: str = "",
) -> str:
    """Build a bilingual .srt body: original text, then translated text.

    ``translations`` must be the same length as ``segments`` — one
    entry per segment, in order (see
    :func:`core.llm.translate_segments`, which produces exactly that
    shape). A blank translation at a given index still emits the cue
    with only the original line, rather than an empty second line; a
    blank original emits the translation alone, and a cue with neither
    is skipped.
    """
    if len(translations) != len(segments):
        raise ValueError(
            f"translations length ({len(translations)}) must match "
            f"segments length ({len(segments)})"
        )
    cues: list[dict] = []
    for seg, translated in zip(segments, translations):
        original = normalize_text(seg.get("text", ""))
        translated_line = normalize_text(translated or "")
        lines = [escape_cue_separator(line) for line in (original, translated_line) if line]
        if not lines:
            continue
        lines[0] = escape_cue_separator(speaker_prefix(seg)) + lines[0]
        body = "\n".join(lines)
        # Preserve the language boundary and source characters in identity;
        # rendered/escaped text can make distinct source pairs look identical.
        identity = json.dumps([original, translated_line], ensure_ascii=True)
        cues.append({**seg, "text": identity, "_bilingual_body": body})
    out: list[str] = []
    for index, (start_ms, end_ms, body) in enumerate(
        prepare_cues(cues, lambda cue: cue["_bilingual_body"]), start=1
    ):
        out.extend([str(index),
                    f"{fmt_srt_time(start_ms / 1000)} --> {fmt_srt_time(end_ms / 1000)}",
                    body, ""])
    return "\n".join(out)


class SavedBilingual(list[str]):
    """Translation list with the persisted result of its exact request."""

    def __init__(self, segments: list[dict], translations: list[str], *, source_json: str,
                 language: str, target: str, media_path: str = "") -> None:
        super().__init__(translations)
        self.segments = copy.deepcopy(segments)
        self.source_json = os.path.abspath(source_json)
        self.language = language
        self.target = target
        self.body = write(self.segments, self, media_path)
        self.saved_path: str | None = None
        self.recovery_path: str | None = None
        self.error: str | None = None
        self.recovery_error: str | None = None


def _save_recovery(result: SavedBilingual) -> str:
    """Strictly sync one self-contained, exclusively created recovery ZIP.

    An interrupted write may leave an incomplete ZIP; only a successful close
    and sync return a recovery path. Copies are never deleted or rotated.
    """
    from core import _checkpoint, config

    folder = config.user_data_dir() / "translation-recovery"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = result.body.encode("utf-8")
    metadata = {
        "version": 1, "source_json": result.source_json, "language": result.language,
        "translation_sha256": hashlib.sha256(body).hexdigest(),
        "segments_sha256": hashlib.sha256(json.dumps(
            result.segments, ensure_ascii=True, sort_keys=True,
        ).encode("utf-8")).hexdigest(),
    }
    fd, path = tempfile.mkstemp(prefix="bilingual-", suffix=".zip", dir=folder)
    # The descriptor is closed even when ZIP serialization or sync fails.
    with os.fdopen(fd, "w+b") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("translation.srt", body)
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=True).encode("utf-8"))
        _checkpoint._strict_sync(stream)
    return path


def _valid_recovery(result: SavedBilingual) -> bool:
    if result.recovery_path is None:
        return False
    try:
        with zipfile.ZipFile(result.recovery_path) as archive:
            body = result.body.encode("utf-8")
            if archive.getinfo("translation.srt").file_size != len(body) or (
                archive.getinfo("metadata.json").file_size
                > max(65536, 6 * (len(result.source_json) + len(result.language)) + 4096)
            ):
                return False
            metadata = json.loads(archive.read("metadata.json"))
            return (
                archive.read("translation.srt") == body
                and metadata["version"] == 1
                and metadata["translation_sha256"] == hashlib.sha256(body).hexdigest()
                and metadata["segments_sha256"] == hashlib.sha256(json.dumps(
                    result.segments, ensure_ascii=True, sort_keys=True,
                ).encode("utf-8")).hexdigest()
                and metadata["source_json"] == result.source_json
                and metadata["language"] == result.language
            )
    except Exception:  # noqa: BLE001 - a damaged/edited recovery copy cannot block saving
        return False


def retry_save(result: SavedBilingual) -> SavedBilingual:
    """Retry file delivery without asking the translation provider again."""
    from core import _checkpoint, convert

    result.saved_path, result.error = None, None
    if not _valid_recovery(result):
        result.recovery_path = None
        try:
            result.recovery_path = _save_recovery(result)
            result.recovery_error = None
        except Exception as error:  # noqa: BLE001 - still try the user's output folder
            result.recovery_error = str(error)
    try:
        output = convert._publish_new_output(result.target, result.body.encode("utf-8"))
        # Ordinary converter writes tolerate fsync errors. This result can be
        # expensive to reproduce: verify its actual bytes and strictly sync it
        # before reporting that the destination is saved.
        with open(output, "r+b") as stream:
            if stream.read() != result.body.encode("utf-8"):
                raise OSError("Bilingual output changed before delivery was verified")
            _checkpoint._strict_sync(stream)
        result.saved_path = output
    except Exception as error:  # noqa: BLE001 - caller retains this object for retry
        result.error = str(error)
    return result


def save_result(segments: list[dict], translations: list[str], *, source_json: str,
                language: str, target: str, media_path: str = "") -> SavedBilingual:
    """Save completed work before UI delivery; retain all recovery copies."""
    return retry_save(SavedBilingual(segments, translations, source_json=source_json,
                                    language=language, target=target, media_path=media_path))
