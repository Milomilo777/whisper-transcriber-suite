"""Microsoft Word ``.docx`` writer.

Produces a structured DOCX file:

  - Heading 1: audio basename
  - Subtitle paragraph: meta line (segment count, duration if known)
  - One paragraph per segment:
      [HH:MM:SS]  <bold speaker (if any)>:  segment text

Arabic-script and Hebrew paragraphs are marked right-to-left: ``w:bidi``
on the paragraph, ``w:rtl`` and a complex-script font on the runs that
hold RTL text. The timestamp stays an LTR run inside such a paragraph.

Requires ``python-docx`` (BSD-licensed, ~1 MB wheel). If the import
fails at runtime — e.g. user runs from a Python without python-docx
installed — the writer raises a clear RuntimeError instead of
crashing in the import.

The module also exposes the byte payload through ``write()``: unlike
the text-based writers which return ``str``, DOCX is binary, so this
module returns the raw zip bytes and ``_write_outputs`` in
``core.transcriber`` is taught to handle the binary case via the
small adapter at the bottom.
"""
from __future__ import annotations

import io
import os
from typing import Any

from .base import (
    coerce_seconds,
    fmt_srt_time,
    is_rtl_text,
    normalize_text,
    sanitize_for_xml,
)

# Complex-script font for RTL runs: ships with Windows and macOS and
# covers Arabic, Persian, Urdu and Hebrew. Word substitutes it elsewhere.
RTL_FONT = "Tahoma"


def _fmt_doc_time(seconds: float) -> str:
    """``HH:MM:SS`` — drops the millisecond fraction the SRT helper carries."""
    return fmt_srt_time(seconds).split(",")[0]


def _require_docx() -> Any:
    """Lazy-import python-docx; raise a clean error if absent."""
    try:
        import docx  # type: ignore
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "DOCX export requires the python-docx package. "
            "Install it via `pip install python-docx>=1.0`."
        ) from e
    return docx


# Elements that follow w:bidi inside w:pPr (ECMA-376 CT_PPrBase order).
_PPR_AFTER_BIDI = (
    "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
    "w:pPrChange",
)


def _set_paragraph_rtl(paragraph: Any) -> None:
    """Mark *paragraph* right-to-left. Under ``w:bidi`` Word reverses the
    meaning of a left/right ``w:jc`` (ECMA-376 17.3.1.13), so such an
    alignment is dropped and the paragraph starts at the right edge."""
    from docx.oxml import OxmlElement  # type: ignore
    from docx.oxml.ns import qn  # type: ignore

    ppr = paragraph._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.insert_element_before(OxmlElement("w:bidi"), *_PPR_AFTER_BIDI)
    jc = ppr.find(qn("w:jc"))
    if jc is not None and jc.get(qn("w:val")) in ("left", "right"):
        ppr.remove(jc)


def _set_run_rtl(run: Any) -> None:
    from docx.oxml.ns import qn  # type: ignore

    run.font.rtl = True
    run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), RTL_FONT)


def _add_run(paragraph: Any, text: str, bold: bool = False) -> Any:
    run = paragraph.add_run(text)
    if bold:
        run.bold = True
        # Word draws RTL text, and digits inside an RTL paragraph, with
        # the complex-script properties, which w:b alone does not set.
        run.font.cs_bold = True
    if is_rtl_text(text):
        _set_run_rtl(run)
    return run


def write_bytes(segments: list[dict], audio_path: str = "") -> bytes:
    """Build the docx and return its raw zip bytes."""
    docx = _require_docx()

    document = docx.Document()
    title = sanitize_for_xml(
        os.path.basename(audio_path) if audio_path else "Transcript"
    )
    heading = document.add_heading(title, level=1)
    if is_rtl_text(title):
        _set_paragraph_rtl(heading)
        for run in heading.runs:
            _set_run_rtl(run)

    nonempty = [s for s in segments if normalize_text(s.get("text", ""))]
    if nonempty:
        last_end = coerce_seconds(nonempty[-1].get("end"))
        duration = _fmt_doc_time(last_end)
        document.add_paragraph(
            f"{len(nonempty)} segment(s) · {duration} total",
            style="Intense Quote",
        )

    for seg in nonempty:
        ts = _fmt_doc_time(coerce_seconds(seg.get("start")))
        # Coerce speaker to str (a hand-edited JSON could put a
        # number here) and run it through sanitize_for_xml so a
        # control character in the label doesn't crash python-docx
        # with the XML-illegal-character ValueError.
        raw_speaker = seg.get("speaker")
        speaker = (
            sanitize_for_xml(str(raw_speaker).strip())
            if raw_speaker not in (None, "")
            else ""
        )
        text = sanitize_for_xml(normalize_text(seg.get("text", "")))

        para = document.add_paragraph()
        if is_rtl_text(text):
            _set_paragraph_rtl(para)
        # [HH:MM:SS]
        _add_run(para, f"[{ts}]  ", bold=True)
        # Optional speaker prefix
        if speaker:
            _add_run(para, f"{speaker}: ", bold=True)
        # Segment body
        _add_run(para, text)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def write(segments: list[dict], audio_path: str = "") -> str:
    """Return the docx bytes wrapped as a latin-1 string.

    Why latin-1? ``core.transcriber._write_outputs`` writes returned
    strings via ``open(path, "w", encoding="utf-8")``. A latin-1
    round-trip preserves every byte 0–255 unchanged through UTF-8
    encoding back into the original bytes — **only if** the receiver
    writes in binary mode. ``_write_outputs`` was extended to
    detect this writer by name and switch to a binary write; if the
    detection ever drops, this function fails fast rather than
    silently producing a corrupt DOCX.
    """
    raise RuntimeError(
        "core.writers.docx_writer must be invoked via write_bytes() — "
        "_write_outputs handles the binary path."
    )
