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

from .base import (
    coerce_seconds,
    escape_cue_separator,
    fmt_srt_time,
    normalize_text,
    speaker_prefix,
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
    out: list[str] = []
    i = 0
    for seg, translated in zip(segments, translations):
        original = escape_cue_separator(normalize_text(seg.get("text", "")))
        translated_line = escape_cue_separator(normalize_text(translated or ""))
        # An empty first line would end the cue in every SRT parser and
        # lose the translation, so write only the lines that have text,
        # and skip a cue with neither.
        lines = [ln for ln in (original, translated_line) if ln]
        if not lines:
            continue
        lines[0] = speaker_prefix(seg) + lines[0]
        # The viewer loads hand-edited JSON verbatim and passes it here;
        # a malformed timestamp must clamp rather than abort the export
        # (a missing "end" falls back to the start, an earlier end is
        # clamped to the start).
        start = coerce_seconds(seg.get("start"))
        end = max(coerce_seconds(seg.get("end"), start), start)
        i += 1
        out.append(f"{i}")
        out.append(f"{fmt_srt_time(start)} --> {fmt_srt_time(end)}")
        out.extend(lines)
        out.append("")
    return "\n".join(out)
