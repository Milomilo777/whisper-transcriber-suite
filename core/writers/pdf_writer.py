"""PDF writer powered by reportlab.

Lays out:
  - Title (audio basename), centered
  - One paragraph per segment with [HH:MM:SS] prefix and an optional
    bold Speaker label
  - Auto-paginates on letter-sized pages with 0.75" margins

Like the DOCX writer, PDFs are binary so this module exposes
``write_bytes`` and is registered in core.writers.__init__ under
BINARY_WRITERS. ``write`` raises so the text-writer surface stays
sane.
"""
from __future__ import annotations

import io
import os
from typing import Any

from .base import coerce_seconds, fmt_srt_time, normalize_text


def _fmt_pdf_time(seconds: float) -> str:
    return fmt_srt_time(seconds).split(",")[0]


def _require_reportlab() -> Any:
    try:
        from reportlab.lib.pagesizes import letter  # type: ignore[import-not-found]  # noqa: F401
        from reportlab.platypus import SimpleDocTemplate  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "PDF export requires the reportlab package. "
            "Install it via `pip install reportlab>=4.0`."
        ) from e


def write_bytes(segments: list[dict], audio_path: str = "") -> bytes:
    _require_reportlab()
    from reportlab.lib.pagesizes import letter  # type: ignore[import-not-found]
    from reportlab.lib.colors import HexColor  # type: ignore[import-not-found]
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore[import-not-found]
    from reportlab.lib.units import inch  # type: ignore[import-not-found]
    from reportlab.platypus import (  # type: ignore[import-not-found]
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )
    from xml.sax.saxutils import escape as xml_escape  # stdlib

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=os.path.basename(audio_path) if audio_path else "Transcript",
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    meta_style = ParagraphStyle(
        name="Meta",
        parent=styles["Italic"],
        textColor=HexColor("#666666"),
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        name="Body", parent=styles["BodyText"], spaceAfter=6, leading=14
    )

    story: list[Any] = []
    title = os.path.basename(audio_path) if audio_path else "Transcript"
    story.append(Paragraph(xml_escape(title), title_style))
    nonempty = [s for s in segments if normalize_text(s.get("text", ""))]
    if nonempty:
        last_end = coerce_seconds(nonempty[-1].get("end"))
        story.append(
            Paragraph(
                f"{len(nonempty)} segment(s) &middot; "
                f"{_fmt_pdf_time(last_end)} total",
                meta_style,
            )
        )
        story.append(Spacer(1, 6))

    for seg in nonempty:
        ts = _fmt_pdf_time(coerce_seconds(seg.get("start")))
        # Defensive str-cast: a hand-edited JSON could put a number
        # here, and (None or "").strip() worked but `123.strip()` did
        # not — used to crash with AttributeError on int.
        raw_speaker = seg.get("speaker")
        speaker = (
            str(raw_speaker).strip()
            if raw_speaker not in (None, "") else ""
        )
        text = xml_escape(normalize_text(seg.get("text", "")))
        if speaker:
            line = f"<b>[{ts}] {xml_escape(speaker)}:</b> {text}"
        else:
            line = f"<b>[{ts}]</b> {text}"
        story.append(Paragraph(line, body_style))

    doc.build(story)
    return buf.getvalue()


def write(segments: list[dict], audio_path: str = "") -> str:
    raise RuntimeError(
        "core.writers.pdf_writer must be invoked via write_bytes() — "
        "_write_outputs handles the binary path."
    )
