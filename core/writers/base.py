"""Shared helpers for the writers package."""
from __future__ import annotations

import math
import unicodedata


def fmt_srt_time(seconds: float) -> str:
    """SRT-style ``HH:MM:SS,ms`` (comma decimal mark)."""
    if seconds is None or not isinstance(seconds, (int, float)):
        seconds = 0.0
    try:
        seconds = float(seconds)
    except (TypeError, ValueError, OverflowError):
        # An integer too large for a float (a hand-edited JSON can carry
        # one) raises OverflowError from float(); clamp like NaN/Inf.
        seconds = 0.0
    # NaN / Inf are valid floats but produce garbage in timestamps;
    # clamp to 0 so a buggy backend doesn't poison every downstream
    # parser.
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    sec, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{sec:02d},{ms:03d}"


def fmt_vtt_time(seconds: float) -> str:
    """WebVTT ``HH:MM:SS.ms`` (period decimal mark)."""
    return fmt_srt_time(seconds).replace(",", ".")


def fmt_lrc_time(seconds: float) -> str:
    """LRC ``[mm:ss.xx]`` lyric timestamp."""
    if seconds is None or not isinstance(seconds, (int, float)):
        seconds = 0.0
    try:
        seconds = float(seconds)
    except (TypeError, ValueError, OverflowError):
        seconds = 0.0
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    # Quantise to integer centiseconds *before* splitting into
    # minutes/seconds — mirroring fmt_srt_time. Rounding the float
    # remainder after divmod (the old approach) let a value just below a
    # whole minute, e.g. 59.996, keep minutes=0 and round the remainder
    # up to "60.00", emitting the illegal "[00:60.00]" (the ss field must
    # be 0-59). Carrying the carry through the divmod rolls it into the
    # next minute -> "[01:00.00]".
    total_cs = int(round(seconds * 100))
    minutes, rem_cs = divmod(total_cs, 6000)
    sec, cs = divmod(rem_cs, 100)
    return f"[{minutes:02d}:{sec:02d}.{cs:02d}]"


def normalize_text(text: object) -> str:
    """Trim and collapse internal whitespace runs to a single space.

    Non-string values are coerced with ``str()`` first (``None``/missing
    becomes ""): a hand-edited JSON can put a number in ``text``, and the
    bare ``.split()`` this used to call raised AttributeError on it,
    aborting the whole write for that format.
    """
    return " ".join(("" if text is None else str(text)).split())


def coerce_seconds(value: object, default: float = 0.0) -> float:
    """Best-effort second count from a possibly-malformed segment field.

    Transcript JSON is user-supplied (or hand-edited), so a segment's
    ``start`` / ``end`` may carry ``None``, a non-numeric string
    (``"abc"``), an integer too large for a float (``10**400``), or a
    non-finite float (NaN / Infinity). A bare ``float(...)`` at the
    segment read raised on all of those and dropped that format's whole
    output file, even though every timestamp formatter already clamps
    such values once they arrive as floats. Coerce to *default* instead,
    mirroring the transcript viewer's ``_seg_float``, so one malformed
    segment never takes the rest of the transcript down with it.
    """
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


# Control characters that are invalid in XML 1.0 (used by DOCX) plus
# the SRT/VTT cue-separator sequence ``-->`` that, when it appears in
# segment text, breaks downstream parsers that interpret it as a
# timecode line.
_XML_ILLEGAL_CHARS = "".join(
    chr(c) for c in list(range(0x00, 0x09)) + [0x0B, 0x0C]
    + list(range(0x0E, 0x20)) + [0x7F]
)
_XML_TRANSLATE = str.maketrans({c: None for c in _XML_ILLEGAL_CHARS})


def sanitize_for_xml(text: str) -> str:
    """Strip XML 1.0-illegal control characters from ``text``.

    Used by the DOCX writer (python-docx raises ValueError on these
    bytes) and by any writer that round-trips through an XML layer.
    """
    if not text:
        return ""
    return text.translate(_XML_TRANSLATE)


def escape_cue_separator(text: str) -> str:
    """Replace literal ``-->`` in segment text with a unicode arrow.

    SRT and WebVTT use ``-->`` as the cue-time separator on its own
    line; embedded occurrences in the cue payload confuse the parser
    (some treat the rest of the line as a malformed timecode). The
    unicode arrow ``→`` reads identically and is safe. Used by SRT only:
    SubRip has no escape syntax, so this is the one deliberate text change
    an SRT round trip makes. WebVTT escapes ``>`` instead
    (:func:`escape_vtt_text`) and keeps the text exact.
    """
    if not text:
        return ""
    return text.replace("-->", "→")


def karaoke_tokens(seg: dict) -> list[tuple[dict, str, bool]] | None:
    """Align the segment's ``words`` with its ``text`` for karaoke output.

    Returns ``(word, token, space_before)`` for every usable word, where
    ``token`` is the word's normalised text and ``space_before`` says
    whether the text has whitespace between this token and the previous
    one; or None when the words do not spell the text.

    The transcript viewer edits only ``text``; the per-word list it came
    with keeps the old wording. Writers that render words (VTT/ASS karaoke)
    must then fall back to ``text``, or the correction silently vanishes
    from those formats. Any change of letters, digits or punctuation is
    such an edit. A change of spacing only ("to day" -> "today") keeps the
    words usable: the writer takes its spaces from ``text``, which also
    keeps CJK text (words without spaces) unspaced.
    """
    words = seg.get("words") if isinstance(seg, dict) else None
    if not isinstance(words, list) or not words:
        return None
    text = normalize_text(seg.get("text"))
    pos = 0
    out: list[tuple[dict, str, bool]] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        token = normalize_text(w.get("word"))
        if not token:
            continue
        space = pos < len(text) and text[pos] == " "
        if space:
            pos += 1
        if not text.startswith(token, pos):
            return None
        out.append((w, token, space))
        pos += len(token)
    if not out or pos != len(text):
        return None
    return out


def words_match_text(seg: dict) -> bool:
    """True when the segment's ``words`` still spell its ``text``.

    Only spacing may differ (see :func:`karaoke_tokens`).
    """
    return karaoke_tokens(seg) is not None


def escape_vtt_text(text: str) -> str:
    """Escape ``&``, ``<`` and ``>`` for a WebVTT cue payload.

    WebVTT reads ``<`` as the start of a tag and ``&`` as the start of a
    character reference, so raw ones break the cue in browsers and are
    stripped by parsers. Escaping ``>`` as well also keeps a literal
    ``-->`` out of the payload, which the spec forbids.
    """
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def speaker_prefix(seg: dict) -> str:
    """Return ``"Speaker N: "`` when the segment carries one, else "".

    Coerces ``speaker`` to str defensively so numeric / non-string
    labels (which the diarisation result occasionally yields when the
    user has hand-edited the JSON) don't AttributeError on ``.strip``.
    """
    raw = seg.get("speaker") if isinstance(seg, dict) else None
    if raw is None or raw == "":
        return ""
    label = str(raw).strip()
    return f"{label}: " if label else ""


def is_rtl_text(text: str) -> bool:
    """True when the first strong character of *text* is right-to-left.

    This is the paragraph-direction rule of the Unicode bidi algorithm
    (UAX #9, rules P2/P3): Arabic-script and Hebrew text gives True,
    Latin, Cyrillic or CJK text gives False, and text with no strong
    character (digits, punctuation) counts as left-to-right.
    """
    for ch in text or "":
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return True
        if kind == "L":
            return False
    return False
