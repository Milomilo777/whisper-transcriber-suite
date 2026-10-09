"""Transcription-format CONVERSION via the faster-whisper JSON middle format.

Parse an existing transcript file into the universal segment list — a list of
``{start, end, text, ...}`` dicts, the same shape this app's JSON writer emits
and every ``core.writers`` text writer consumes — then re-emit it in any target
text format through the existing writers registry.

PARSE (input) formats, auto-detected by extension then content:

  * ``.json`` — this app's JSON output (a list of segment dicts).
  * ``.srt``  — SubRip.
  * ``.vtt``  — WebVTT.
  * ``.ass`` / ``.ssa`` — Advanced SubStation Alpha (and legacy SSA):
    ``[Events]`` ``Dialogue:`` lines, with the column order read from the
    section's own ``Format:`` header. Override blocks (``{\\k42}``,
    ``{\\an8}``) are styling and are stripped; the ``Name`` column is
    carried through as the speaker.
  * ``.tsv``  — the ``start<TAB>end<TAB>text`` table this app's TSV writer emits
    (start/end in MILLISECONDS), tolerant of a header row.
  * ``.otr``  — oTranscribe (imported via
    :mod:`core.integrations.otranscribe`).
  * ``.eaf``  — ELAN Annotation Format (XML): ``TIME_ORDER``/``TIME_SLOT``s
    resolved against each tier's ``ALIGNABLE_ANNOTATION``s.
  * ``.inqscr`` / InqScribe-style ``.txt`` — inline ``[hh:mm:ss.ff]``
    (or ``[hh:mm:ss]``) timestamps; each timestamp starts a new segment and
    the next timestamp's start becomes the previous segment's end.

Plain TXT (without inline timestamps) is OUTPUT-ONLY: it carries no
timestamps, so it cannot be parsed back into segments (``parse_to_segments``
raises ``ConvertError`` for a ``.txt`` with no recognisable cues).

EMIT (output) formats: any text writer in ``core.writers.WRITERS``
(srt / vtt / tsv / txt / json / lrc / md / otr / elan / inqscribe /
express_scribe), plus ``smtv_docx`` as a binary target (see
``CONVERT_TARGETS``). The other binary writers (docx / pdf) are still NOT
offered here — they need extra context this generic converter cannot
recover from an arbitrary transcript file. ``smtv_docx`` is filled with
``work_title`` derived from the input file's stem and an EMPTY detected
language (a generic transcript file carries no language metadata), so the
template's language placeholders fall back to their neutral labels —
matching the writer's own "no language detected" behaviour.
``express_scribe`` is EXPORT-ONLY (whole-second ``[hh:mm:ss]`` cues are too
lossy to round-trip) and is therefore NOT in ``PARSE_FORMATS``.

Stdlib only except for ``smtv_docx`` (needs python-docx, lazily imported by
the writer itself); Tk-free. The two public seams are pure and testable:

    parse_to_segments(path) -> list[dict]
    convert_file(in_path, out_format, out_path=None) -> out_path
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from . import writers as _writers
from .integrations import otranscribe as _otr
from .writers.base import normalize_text as _normalize_text

logger = logging.getLogger(__name__)

__all__ = [
    "ConvertError",
    "PARSE_FORMATS",
    "OUTPUT_FORMATS",
    "CONVERT_TARGETS",
    "output_extension_for",
    "parse_to_segments",
    "dedupe_rolling_captions",
    "convert_file",
]


class ConvertError(ValueError):
    """Raised when an input cannot be parsed or a target format is unknown."""


# Formats we can PARSE into segments (input side). Plain TXT is deliberately
# absent (no timestamps); ``express_scribe`` is also absent (export-only —
# whole-second cues are too lossy to round-trip). "elan" / "inqscribe" match
# the OUTPUT_FORMATS writer-registry keys for the same formats, even though
# their on-disk extensions (.eaf / .inqscr) differ from the registry key.
PARSE_FORMATS: tuple[str, ...] = (
    "json", "srt", "vtt", "ass", "tsv", "otr", "elan", "inqscribe",
)

# Formats we can EMIT — the text writers in the registry (output side).
OUTPUT_FORMATS: tuple[str, ...] = tuple(sorted(_writers.WRITERS.keys()))

# The one binary target this generic converter also offers (see the module
# docstring for why the other binary writers — docx / pdf — are not here).
_SMTV_DOCX = "smtv_docx"

# Every target ``convert_file`` accepts, text + the one binary exception.
# This is what UI format pickers should enumerate (see app.app._ask_convert_format).
CONVERT_TARGETS: tuple[str, ...] = OUTPUT_FORMATS + (_SMTV_DOCX,)

# Registry-key -> on-disk extension overrides for the default output path:
# the transcriber's own table (core.writers.FORMAT_EXTENSIONS), so a converted
# file gets the same extension a transcription writes (elan -> .eaf,
# inqscribe -> .inqscr, express_scribe -> .txt, smtv_docx -> .docx).
_EXT_OVERRIDES: dict[str, str] = dict(_writers.FORMAT_EXTENSIONS)


def output_extension_for(fmt: str) -> str:
    """The on-disk extension (no dot) *fmt* actually produces.

    For most ``CONVERT_TARGETS`` entries the registry key already IS the
    extension; the handful of exceptions live in ``_EXT_OVERRIDES``. UI
    format pickers use this to show the real file extension next to each
    format name (see app.app._ask_convert_format) instead of the bare
    internal registry key, which is opaque for entries like ``elan`` or
    ``smtv_docx``.
    """
    return _EXT_OVERRIDES.get(fmt.lower(), fmt.lower())


# --- timestamp parsing ------------------------------------------------------

# HH:MM:SS,mmm or HH:MM:SS.mmm (SRT uses comma, VTT uses period); the hour
# field is optional in WebVTT (MM:SS.mmm), so allow a 2- or 3-field clock.
# The fraction is optional too: hand-made files write "00:00:01 --> ...",
# and those cues used to be dropped without a word. A timing line starts
# with the clock (WebVTT cue settings may follow the end time); fraction
# digits past milliseconds are ignored.
_CUE = re.compile(
    r"\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d+))?\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d+))?(?![\d:])"
)
# Invisible marks some editors leave in front of a timing line (a BOM in
# the middle of a concatenated file, zero-width space, LRM / RLM).
_LEADING_INVISIBLE = "".join(chr(c) for c in (0xFEFF, 0x200B, 0x200E, 0x200F))


def _timing(line: str) -> re.Match[str] | None:
    return _CUE.match(line.lstrip().lstrip(_LEADING_INVISIBLE))


def _clock_to_seconds(
    h: str | None, m: str, s: str, frac: str | None
) -> float:
    hours = int(h) if h else 0
    # Right-pad the fractional part to milliseconds (".5" -> 500ms).
    ms = int(((frac or "") + "000")[:3])
    return hours * 3600 + int(m) * 60 + int(s) + ms / 1000.0


# --- per-format parsers (return list of {start, end, text}) -----------------

def _parse_json(text: str, path: str) -> list[dict]:
    """Parse this app's JSON output — a list of segment dicts.

    Each entry must be an object; ``start``/``end`` coerce to float (missing
    end falls back to start), ``text`` is stripped. Per-word lists and
    ``speaker`` are carried through so a JSON->JSON / JSON->VTT round-trip
    keeps karaoke timing and speaker labels.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as e:
        raise ConvertError(f"{path} is not valid JSON: {e}") from e
    # OpenAI / Whisper "verbose_json" (and this app's HTTP API) wrap the
    # list as {"text": ..., "segments": [...]}.
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        data = data["segments"]
    if not isinstance(data, list):
        raise ConvertError(
            f"{path} JSON must be a list of segments, got {type(data).__name__}"
        )
    segments: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry.get("start", 0.0))
        except (TypeError, ValueError, OverflowError):
            # OverflowError: an integer too large for a float.
            start = 0.0
        try:
            end = float(entry.get("end", start))
        except (TypeError, ValueError, OverflowError):
            end = start
        # A hand-edited JSON can put a non-string (e.g. a number) in
        # "text"; ``(value or "").strip()`` raised AttributeError (not a
        # ConvertError) and crashed the whole conversion.
        raw_text = entry.get("text")
        body = ("" if raw_text is None else str(raw_text)).strip()
        if not body:
            continue
        seg: dict[str, Any] = {"start": start, "end": end, "text": body}
        speaker = entry.get("speaker")
        if speaker not in (None, ""):
            seg["speaker"] = str(speaker)
        words = entry.get("words")
        if isinstance(words, list):
            # Carry through only dict word entries. A non-dict element
            # (a bare string / number from hand-edited or externally
            # produced JSON) would make the downstream writers' w.get(...)
            # raise AttributeError and abort the whole conversion.
            valid_words = [w for w in words if isinstance(w, dict)]
            if valid_words:
                seg["words"] = valid_words
        segments.append(seg)
    return segments


# Markup that is styling, not words. Only these known tags are removed, so
# text such as "if a < b and c > d" survives. WebVTT: class, italic, bold,
# underline, voice, language and ruby spans plus karaoke timestamps
# (<00:00:01.000>). SubRip: the HTML-like tags players understand.
# Both also drop the HTML tags other tools put into subtitles (font, span,
# strong, em); a <br> line break becomes a space first (_BR_TAG).
_VTT_TAG = re.compile(
    r"</?(?:c|i|b|u|v|lang|ruby|rt|font|span|strong|em)(?:\.[^\s<>]*)?(?:\s[^<>]*)?>"
    r"|<(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}>",
    re.IGNORECASE,
)
_SRT_TAG = re.compile(
    r"</?(?:i|b|u|s|font|span|strong|em)(?:\s[^<>]*)?>", re.IGNORECASE
)
_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
# A complete character reference (the trailing ";" is required, so a bare
# "AT&T" stays as written).
_VTT_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")


def _decode_vtt_entities(text: str) -> str:
    """Decode ``&amp;`` / ``&lt;`` / ``&#8203;`` ... in a WebVTT payload."""
    return _VTT_ENTITY.sub(lambda m: html.unescape(m.group(0)), text)


def _parse_cue_format(text: str, path: str, *, vtt: bool = False) -> list[dict]:
    """Parse SRT or WebVTT cues.

    A cue starts at a timing line (``start --> end``) and its payload runs
    to the next blank line or the next timing line. Whitespace-only lines
    BEFORE the text are skipped, not treated as the end: YouTube's VTT puts
    a single space on a cue's first payload line, and splitting there cut
    the cue's text off its timing. A line holding only digits right before
    the next timing line is that cue's SRT number, not text. Lines outside cues (the SRT number, the
    ``WEBVTT`` header, ``NOTE`` / ``STYLE`` blocks, cue identifiers) are
    skipped.

    Only known styling tags are removed (see ``_SRT_TAG`` / ``_VTT_TAG``);
    for WebVTT (*vtt*) character references are then decoded, the pair of
    the VTT writer's escaping. SubRip has no escape syntax, so SRT text is
    kept as written. A line that contains ``-->`` but is not a readable
    timing line starts a cue that cannot be placed: it is skipped and
    counted in a warning.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tag_re = _VTT_TAG if vtt else _SRT_TAG
    segments: list[dict] = []
    skipped = 0
    i, n = 0, len(lines)
    while i < n:
        m = _timing(lines[i])
        if not m:
            if "-->" in lines[i]:
                skipped += 1
                while i < n and lines[i].strip() != "":
                    i += 1
            i += 1
            continue
        g = m.groups()
        start = _clock_to_seconds(g[0], g[1], g[2], g[3])
        end = _clock_to_seconds(g[4], g[5], g[6], g[7])
        body_lines: list[str] = []
        i += 1
        while i < n and lines[i] != "":
            if not lines[i].strip():
                if body_lines:
                    break  # a whitespace-only separator after the text
                i += 1  # YouTube's " " before the text
                continue
            if _timing(lines[i]):
                if body_lines and body_lines[-1].strip().isdigit():
                    body_lines.pop()
                break
            body_lines.append(lines[i])
            i += 1
        body = _BR_TAG.sub(" ", " ".join(ln.strip() for ln in body_lines))
        body = " ".join(tag_re.sub("", body).split())
        if vtt:
            body = _decode_vtt_entities(body).strip()
        if body:
            segments.append({"start": start, "end": end, "text": body})
    if skipped:
        logger.warning(
            "%s: skipped %d cue(s) with an unreadable timing line",
            os.path.basename(path), skipped,
        )
    return segments


def _parse_tsv(text: str, path: str) -> list[dict]:
    """Parse the app's TSV (``start<TAB>end<TAB>text``; start/end in ms).

    A header row (non-numeric first field, e.g. the ``start`` literal this
    app's writer emits) is skipped. Rows with fewer than three tab fields or a
    non-numeric time are ignored rather than aborting the whole parse.
    """
    segments: list[dict] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        start_raw, end_raw = parts[0].strip(), parts[1].strip()
        body = parts[2].strip()
        try:
            start = float(start_raw) / 1000.0
            end = float(end_raw) / 1000.0
        except (TypeError, ValueError, OverflowError):
            # Header row or malformed line — skip silently.
            continue
        if body:
            segments.append({"start": start, "end": end, "text": body})
    return segments


def _parse_otr(path: str) -> list[dict]:
    """Import an oTranscribe ``.otr`` by round-tripping through its SRT helper.

    ``core.integrations.otranscribe.otr_to_srt`` already infers end times from
    the next segment's start, so reusing it keeps a single source of truth for
    that contract.
    """
    srt_text = _otr.otr_to_srt(path)
    return _parse_cue_format(srt_text, path)


def _safe_fromstring(text: str) -> ET.Element:
    """``ET.fromstring`` that refuses a DOCTYPE in an ``.eaf`` being imported.

    Stdlib ``ElementTree``/expat has no built-in limit on entity expansion,
    so an attacker-crafted ``.eaf`` with a DOCTYPE can mount a "billion
    laughs" (or XXE) attack. Both require a literal ``<!DOCTYPE`` token (the
    XML grammar's ``doctypedecl`` production is case-sensitive), so a plain
    substring check rejects both without adding a ``defusedxml`` dependency
    or reaching into expat internals whose exposure differs across Python's
    C-accelerated vs. pure-Python ``ElementTree.XMLParser``.
    """
    if "<!DOCTYPE" in text:
        raise ET.ParseError("DOCTYPE declarations are not allowed in .eaf input")
    # S314: a DOCTYPE (the only way to declare an entity) was refused above, so
    # no entity expansion is possible; expat also bounds the rest.
    return ET.fromstring(text)  # noqa: S314


def _parse_eaf(text: str, path: str) -> list[dict]:
    """Parse an ELAN ``.eaf`` (XML): TIME_ORDER slots + ALIGNABLE_ANNOTATIONs.

    Reads every ``TIME_SLOT`` in ``TIME_ORDER`` into a ``{id: seconds}`` map,
    then walks every ``TIER`` / ``ANNOTATION`` / ``ALIGNABLE_ANNOTATION``,
    resolving ``TIME_SLOT_REF1``/``REF2`` against that map. An annotation
    whose referenced slot is missing (malformed file) or whose
    ``ANNOTATION_VALUE`` is empty is skipped rather than aborting the whole
    parse. ``REF_ANNOTATION`` (un-aligned, tier-linked) annotations carry no
    direct time slots and are skipped too — only ``ALIGNABLE_ANNOTATION``
    is time-aligned in EAF.
    """
    try:
        root = _safe_fromstring(text)
    except ET.ParseError as e:
        raise ConvertError(f"{path} is not valid XML: {e}") from e

    slots: dict[str, float] = {}
    for slot in root.iter("TIME_SLOT"):
        slot_id = slot.get("TIME_SLOT_ID")
        value = slot.get("TIME_VALUE")
        if not slot_id or value is None:
            continue
        try:
            slots[slot_id] = float(value) / 1000.0
        except (TypeError, ValueError, OverflowError):
            continue

    segments: list[dict] = []
    for annotation in root.iter("ALIGNABLE_ANNOTATION"):
        ref1 = annotation.get("TIME_SLOT_REF1")
        ref2 = annotation.get("TIME_SLOT_REF2")
        if ref1 not in slots or ref2 not in slots:
            continue
        start = slots[ref1]
        end = slots[ref2]
        value_el = annotation.find("ANNOTATION_VALUE")
        body = (value_el.text or "").strip() if value_el is not None else ""
        if not body:
            continue
        segments.append({"start": start, "end": end, "text": body})
    return segments


# [hh:]mm:ss[.ff] inline timestamp, e.g. "[00:01:02.50]" or "[1:02]".
_INQSCRIBE_TS = re.compile(
    r"\[(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?\]"
)


def _backslashes_before(text: str, pos: int) -> int:
    count = 0
    while pos - count - 1 >= 0 and text[pos - count - 1] == "\\":
        count += 1
    return count


def _unescape_inqscribe(body: str) -> str:
    """Halve the backslash run in front of each literal timestamp.

    Counted by hand rather than with a ``\\\\+`` regex group, which is
    quadratic on a long run of backslashes.
    """
    out: list[str] = []
    last = 0
    for m in _INQSCRIBE_TS.finditer(body):
        run = _backslashes_before(body, m.start())
        if not run:
            continue
        out.append(body[last:m.start() - run])
        out.append("\\" * (run // 2))
        last = m.start()
    out.append(body[last:])
    return "".join(out)


def _parse_inqscribe(text: str, path: str) -> list[dict]:
    """Parse InqScribe inline ``[hh:mm:ss.ff]`` (or ``[hh:mm:ss]``) timestamps.

    Each timestamp starts a new segment; its text runs to the next
    timestamp (across line breaks). The last segment's end is its own
    start plus a small default duration (no following cue to bound it).
    Text with no recognisable timestamp at all raises :class:`ConvertError`
    (matches the plain-TXT "output only" contract for un-timestamped text).

    A timestamp behind an odd run of backslashes is literal text (the
    writer's escape, see :mod:`core.writers.inqscribe`): it does not start
    a segment, and the run is halved back to what the text held.
    """
    matches = [
        m for m in _INQSCRIBE_TS.finditer(text)
        if _backslashes_before(text, m.start()) % 2 == 0
    ]
    if not matches:
        raise ConvertError(
            f"{path}: no [hh:mm:ss] timestamps found; cannot import as InqScribe."
        )

    segments: list[dict] = []
    for i, m in enumerate(matches):
        h, mm, ss, frac = m.groups()
        # Right-pad the fractional part to centiseconds (InqScribe's own
        # unit); ".5" -> 50cs, ".50" -> 50cs, ".500" -> 50cs (truncate to 2).
        cs = int((frac + "00")[:2]) if frac else 0
        start = (int(h) if h else 0) * 3600 + int(mm) * 60 + int(ss) + cs / 100.0
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = _unescape_inqscribe(" ".join(text[body_start:body_end].split()))
        if not body:
            continue
        segments.append({"start": start, "text": body})

    # Resolve end times: next segment's start, last gets +5s (matches the
    # otr_to_srt convention for an open-ended final cue).
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            seg["end"] = segments[i + 1]["start"]
        else:
            seg["end"] = seg["start"] + 5.0
    return segments


# --- public API -------------------------------------------------------------

_EXT_TO_PARSE_FORMAT: dict[str, str] = {
    "eaf": "elan",
    "inqscr": "inqscribe",
    # Legacy SubStation Alpha. We only WRITE v4.00+ (.ass), but old .ssa
    # files exist in the wild and parse through the same Dialogue lines.
    "ssa": "ass",
}


# ``Dialogue: 0,0:00:01.00,0:00:03.50,Default,Speaker,0,0,0,,text``
# Only the first nine commas are field separators; everything after them
# is the payload, which is allowed to contain commas of its own.
_ASS_DIALOGUE = re.compile(r"^\s*Dialogue\s*:\s*(.*)$", re.IGNORECASE)
_ASS_TIME = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})[.,](\d{1,3})$")


def _ass_time_to_seconds(value: str) -> float | None:
    m = _ASS_TIME.match((value or "").strip())
    if not m:
        return None
    h, mm, ss, frac = m.groups()
    # ASS centiseconds are 2 digits; pad so ".5" reads as 0.50s, and a
    # 3-digit millisecond value from a non-standard writer still works.
    scale = 10 ** len(frac)
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(frac) / scale


def _strip_ass_markup(text: str) -> str:
    """Turn a Dialogue payload back into plain text.

    Drops override blocks (including the ``\\k`` karaoke tags this app
    writes), unescapes the literal brace/backslash escapes, and turns
    ``\\N``/``\\n`` line breaks and ``\\h`` hard spaces back into
    ordinary whitespace.

    One left-to-right pass, the exact inverse of
    :func:`core.writers.ass.escape_ass_text`: running the replacements one
    after another (strip ``{...}`` first, unescape later) read the escaped
    brace in ``\\{\\\\k5\\}`` as the start of an override block, and turned
    the escaped backslash of ``C:\\\\new`` into a line break.
    """
    if not text:
        return ""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in "\\{}":
                out.append(nxt)
                i += 2
                continue
            if nxt in "Nnh":
                out.append(" ")
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if ch == "{":
            close = text.find("}", i + 1)
            if close != -1:
                i = close + 1
                continue
        out.append(ch)
        i += 1
    return " ".join("".join(out).split())


def _looks_like_ass(sniff: str) -> bool:
    """True for an ASS/SSA script.

    Must be tested BEFORE the JSON check: an ASS file opens with
    ``[Script Info]``, so the bare "starts with [" heuristic would hand
    it to the JSON parser and report it as malformed JSON.
    """
    head = (sniff or "")[:400].lower()
    return "[script info]" in head or "scripttype:" in head


def _parse_ass(text: str, path: str) -> list[dict]:
    """Parse ASS (v4.00+) or legacy SSA (v4.00) Dialogue lines.

    Reads the ``[Events]`` ``Format:`` header rather than assuming column
    order: SSA and ASS differ (SSA leads with ``Marked``, ASS with
    ``Layer``), and a file may legitimately declare its own order. Falls
    back to the ASS default when no header is present.

    Comment lines are skipped — they are editor notes, not subtitles.
    """
    fields = ["Layer", "Start", "End", "Style", "Name",
              "MarginL", "MarginR", "MarginV", "Effect", "Text"]
    segments: list[dict] = []
    in_events = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = line.lower().startswith("[events")
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            declared = [p.strip() for p in line.split(":", 1)[1].split(",")]
            if declared:
                fields = declared
            continue
        m = _ASS_DIALOGUE.match(line)
        if not m:
            continue
        # Split on the first len(fields)-1 commas only; the Text field is
        # last and keeps every comma it contains.
        parts = m.group(1).split(",", max(0, len(fields) - 1))
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        start = _ass_time_to_seconds(row.get("Start", ""))
        end = _ass_time_to_seconds(row.get("End", ""))
        if start is None:
            continue
        if end is None or end < start:
            end = start
        body = _strip_ass_markup(row.get("Text", ""))
        if not body:
            continue
        seg: dict[str, Any] = {"start": start, "end": end, "text": body}
        speaker = (row.get("Name") or "").strip()
        if speaker:
            seg["speaker"] = speaker
        segments.append(seg)
    return segments


def _detect_format(path: str, text: str | None) -> str:
    """Return one of ``PARSE_FORMATS`` for *path*, by extension then content.

    The extension is authoritative when recognised: ``.eaf`` => elan,
    ``.inqscr`` => inqscribe, etc (via ``_EXT_TO_PARSE_FORMAT`` for the
    extensions that differ from their ``PARSE_FORMATS`` name). ``.txt`` is
    ambiguous between "no timestamps" (output-only) and InqScribe's inline
    ``[hh:mm:ss.ff]`` style, so it is content-sniffed for an InqScribe
    timestamp before raising. An unknown / missing extension falls back to
    content sniffing: a leading ``[``/``{`` => json, a ``WEBVTT`` header =>
    vtt, a ``-->`` line => srt, a tab-delimited numeric table => tsv, an
    ``<ANNOTATION_DOCUMENT`` root => elan, an inline ``[hh:mm:ss]`` cue =>
    inqscribe.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "txt":
        sniff_txt = (text or "").lstrip()
        if _INQSCRIBE_TS.search(sniff_txt):
            return "inqscribe"
        raise ConvertError(
            "TXT has no timestamps and cannot be converted FROM; it is an "
            "output-only format. Pick an .srt / .vtt / .tsv / .json / .otr / "
            ".eaf / .inqscr source instead."
        )
    if ext in _EXT_TO_PARSE_FORMAT:
        return _EXT_TO_PARSE_FORMAT[ext]
    if ext in PARSE_FORMATS:
        return ext

    sniff = (text or "").lstrip()
    if not sniff:
        raise ConvertError(f"{path}: empty or unreadable input.")
    if _looks_like_ass(sniff):
        return "ass"
    if sniff[0] in "[{":
        return "json"
    if sniff.startswith("<?xml") or sniff.lstrip("<").startswith("ANNOTATION_DOCUMENT"):
        return "elan"
    head = sniff[:64].upper()
    if head.startswith("WEBVTT"):
        return "vtt"
    if "-->" in sniff:
        return "srt"
    if "\t" in sniff.split("\n", 1)[0]:
        return "tsv"
    if _INQSCRIBE_TS.search(sniff):
        return "inqscribe"
    raise ConvertError(
        f"{path}: could not auto-detect the transcript format. Supported "
        f"inputs: {', '.join(PARSE_FORMATS)}."
    )


def _utf16_without_bom(raw: bytes) -> str | None:
    """``utf-16-le`` / ``utf-16-be`` when *raw* looks like BOM-less UTF-16.

    Subtitle text is mostly ASCII digits, colons and spaces, which UTF-16
    stores as one zero byte and one non-zero byte; the side the zeros sit
    on gives the byte order.
    """
    sample = raw[:4096]
    if len(sample) < 4 or b"\x00" not in sample:
        return None
    even_zeros = sample[0::2].count(0)
    odd_zeros = sample[1::2].count(0)
    half = len(sample) // 2
    if odd_zeros > half * 0.3 and even_zeros < odd_zeros / 4:
        return "utf-16-le"
    if even_zeros > half * 0.3 and odd_zeros < even_zeros / 4:
        return "utf-16-be"
    return None


def _decode_text(raw: bytes, path: str) -> str:
    """Decode a transcript file: UTF-8 (BOM optional) or UTF-16.

    Windows editors save "Unicode" subtitles as UTF-16 (often with a BOM),
    which the plain UTF-8 read rejected with a byte-offset error. A legacy
    code page (Windows-1256 for Persian / Arabic, Windows-1252, ...) cannot
    be told apart reliably and is not guessed: the error says how to fix
    the file instead.
    """
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = _utf16_without_bom(raw) or "utf-8"
    name = os.path.basename(path)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as e:
        if encoding.startswith(("utf-16", "utf-32")):
            raise ConvertError(
                f"{name} looks like {encoding.upper()} text but could not "
                f"be decoded: {e}"
            ) from e
        raise ConvertError(
            f"{name} is not UTF-8 text. It was probably saved in an older "
            "encoding such as Windows-1256 (Persian / Arabic) or "
            "Windows-1252. Open it in a text or subtitle editor and save it "
            "as UTF-8, then convert it again."
        ) from e
    if "\x00" in text:
        # Valid UTF-8 never holds NUL in a text file; this is UTF-16/32
        # without a byte-order mark that the sniff above could not place
        # (little ASCII in it). Parsing it would silently find nothing.
        raise ConvertError(
            f"{name} contains NUL bytes: it is probably UTF-16 text without "
            "a byte-order mark. Save it as UTF-8 (or UTF-16 with a BOM), "
            "then convert it again."
        )
    return text


def parse_to_segments(path: str) -> list[dict]:
    """Parse a transcript file into the universal segment list.

    Auto-detects the format by extension then content. Returns a list of
    ``{start, end, text, ...}`` dicts (possibly empty for a header-only or
    cue-less file). Raises :class:`ConvertError` for an unreadable file, an
    unsupported / undetectable format, or a ``.txt`` input (output-only).
    """
    if not path or not os.path.isfile(path):
        raise ConvertError(f"Input file not found: {path!r}")

    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "otr":
        try:
            return _parse_otr(path)
        except (OSError, ValueError) as e:
            raise ConvertError(f"Could not import .otr {path}: {e}") from e

    try:
        with open(path, "rb") as fb:
            raw = fb.read()
    except OSError as e:
        raise ConvertError(f"Could not read {path}: {e}") from e
    text = _decode_text(raw, path)

    fmt = _detect_format(path, text)
    if fmt == "json":
        return _parse_json(text, path)
    if fmt in ("srt", "vtt"):
        is_vtt = fmt == "vtt" or text.lstrip().upper().startswith("WEBVTT")
        return _parse_cue_format(text, path, vtt=is_vtt)
    if fmt == "ass":
        return _parse_ass(text, path)
    if fmt == "tsv":
        return _parse_tsv(text, path)
    if fmt == "elan":
        return _parse_eaf(text, path)
    if fmt == "inqscribe":
        return _parse_inqscribe(text, path)
    # _detect_format only returns members of PARSE_FORMATS; otr handled above.
    raise ConvertError(f"{path}: unsupported input format {fmt!r}.")


def _default_out_path(in_path: str, out_format: str) -> str:
    base = os.path.splitext(in_path)[0]
    fmt = out_format.lower()
    ext = _EXT_OVERRIDES.get(fmt, fmt)
    return f"{base}.{ext}"


def _same_file(a: str, b: str) -> bool:
    """True if *a* and *b* name the same file.

    Prefers ``os.path.samefile`` (st_dev/st_ino), which reflects the real
    filesystem semantics on every platform — including case-insensitive macOS
    (APFS) and Windows volumes where ``Movie.SRT`` and ``Movie.srt`` are the
    SAME file. ``os.path.normcase`` only folds case on Windows; on POSIX
    (incl. macOS) it is the identity function, so the old normcase compare
    silently missed case-only collisions on macOS and let the converter
    overwrite the source in place. ``samefile`` needs both paths to exist; when
    one does not (the usual case for a not-yet-written output target) we fall
    back to the normalized-string compare — and on a case-insensitive FS the
    target's case variant already resolves to the existing source, so
    ``os.path.exists`` is True and ``samefile`` still catches the collision.
    """
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return (
        os.path.normcase(os.path.realpath(a))
        == os.path.normcase(os.path.realpath(b))
    )


def dedupe_rolling_captions(segments: list[dict]) -> list[dict]:
    """Strip YouTube's rolling-auto-caption overlap from parsed cues.

    YouTube's automatic-caption VTT shows captions as a rolling window: the
    tail of one cue reappears verbatim as the head of the next (e.g. cue A
    ends "...to the show today", cue B starts "to the show today we will").
    Left alone, converting such a file straight to text (or any other
    format) prints every overlapping word twice. This trims, from each
    cue's text, the longest run of leading words that exactly matches the
    previous (already-trimmed) cue's trailing words. A cue whose words are
    entirely consumed by the overlap is dropped (it added nothing new).

    Comparison is case-insensitive; matching is a contiguous word sequence,
    not a bag-of-words, so ordinary manually-authored subtitles -- which
    don't have this rolling-window artifact -- pass through unchanged
    (a false match would require two consecutive cues to repeat the exact
    same multi-word phrase across their boundary, which real dialogue
    essentially never does). Only feed this genuinely auto-generated
    captions; a manual/creator-provided track should skip it.
    """
    cleaned: list[dict] = []
    prev_words: list[str] = []
    for seg in segments:
        # normalize_text maps a null text to "" (str(None) was the word "None").
        words = _normalize_text(seg.get("text")).split()
        overlap = _prefix_suffix_overlap(prev_words, words)
        prev_words = words
        kept = words[overlap:]
        if not kept:
            continue
        new_seg = dict(seg)
        new_seg["text"] = " ".join(kept)
        cleaned.append(new_seg)
    return cleaned


def _prefix_suffix_overlap(prev: list[str], cur: list[str]) -> int:
    """Longest k such that ``prev[-k:] == cur[:k]`` (case-insensitive)."""
    if not prev or not cur:
        return 0
    max_k = min(len(prev), len(cur))
    prev_lower = [w.lower() for w in prev[-max_k:]]
    cur_lower = [w.lower() for w in cur[:max_k]]
    for k in range(max_k, 0, -1):
        if prev_lower[len(prev_lower) - k:] == cur_lower[:k]:
            return k
    return 0


def convert_file(
    in_path: str, out_format: str, out_path: str | None = None,
    *, segments: list[dict] | None = None, overwrite: bool = False,
) -> str:
    """Convert *in_path* to *out_format*, writing beside the input by default.

    Parses *in_path* into segments (the faster-whisper JSON middle format) then
    emits *out_format* via the matching ``core.writers`` text writer. Returns
    the path written. When *out_path* is None the output is written next to the
    input with the new extension; if that would overwrite the input itself
    (e.g. re-emitting an .srt as .srt in place) the path is suffixed with
    ``.converted`` to avoid clobbering the source. When that default target
    already exists it is kept and the output goes to ``name (1).ext`` (the
    first free name) unless *overwrite* is True; an explicit *out_path* is
    always the caller's choice. The file is written to a temp sibling and
    moved into place, so a failed write never leaves a truncated target.

    *segments*, when given, is used as-is instead of re-parsing *in_path* --
    lets a caller parse once (optionally running it through
    :func:`dedupe_rolling_captions` first) and reuse the result across
    several output formats.

    Raises :class:`ConvertError` for an unknown target format or a parse
    failure, and lets the writer's own ``OSError`` surface on a write failure.
    """
    fmt = (out_format or "").lower().lstrip(".")
    if fmt != _SMTV_DOCX and fmt not in _writers.WRITERS:
        raise ConvertError(
            f"Unknown output format {out_format!r}. "
            f"Choose one of: {', '.join(CONVERT_TARGETS)}."
        )

    segments = segments if segments is not None else parse_to_segments(in_path)
    if not segments:
        # Emitting nothing would replace an existing target with an empty
        # shell (an existing .vtt became the 7-byte "WEBVTT\n") and report
        # success.
        raise ConvertError(
            f"{os.path.basename(in_path)} has no subtitle cues to convert."
        )

    target = out_path or _default_out_path(in_path, fmt)
    if _same_file(target, in_path):
        base, ext = os.path.splitext(target)
        target = f"{base}.converted{ext}"
    if out_path is None and not overwrite and os.path.exists(target):
        target = _free_out_path(target)

    parent = os.path.dirname(os.path.abspath(target))
    if parent:
        os.makedirs(parent, exist_ok=True)

    if fmt == _SMTV_DOCX:
        # No language metadata survives a generic transcript file, so this
        # is filled the same way the writer treats "no language detected"
        # (neutral cue labels; see core.writers.smtv_docx_writer). work_title
        # mirrors the transcription pipeline's own convention (source stem).
        from .writers import smtv_docx_writer

        payload = smtv_docx_writer.write_bytes(
            segments, in_path, language="", work_title=Path(in_path).stem
        )
        _replace_atomically(target, payload)
        return target

    # No media file is known here: the transcript's own name would land in
    # the .otr "media" field, the ELAN media link and the Markdown title.
    body = _writers.get_writer(fmt)(segments, "")
    # Written byte-for-byte as UTF-8 with the writers' own '\n' line endings
    # (matching transcriber.py and _checkpoint.py); text mode would turn
    # them into '\r\n' on Windows, diverging documented-stable formats
    # (SRT, TSV) by OS.
    _replace_atomically(target, body.encode("utf-8"))
    return target


def _free_out_path(path: str) -> str:
    """``name (1).ext``, ``name (2).ext``, ... — the first name not on disk."""
    root, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{root} ({n}){ext}"):
        n += 1
    return f"{root} ({n}){ext}"


def _replace_atomically(target: str, payload: bytes) -> None:
    """Write *payload* to a temp sibling of *target*, then move it into place."""
    tmp = f"{target}.{os.getpid()}.part"
    try:
        with open(tmp, "wb") as fb:
            fb.write(payload)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
