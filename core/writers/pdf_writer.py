"""PDF writer powered by reportlab.

Lays out:
  - Title (audio basename), centered
  - One paragraph per segment with [HH:MM:SS] prefix and an optional
    bold Speaker label
  - Auto-paginates on letter-sized pages with 0.75" margins
  - Text in any script is drawn with the OS's own fonts (see
    ``pdf_fonts``); Arabic-script letters are joined and right-to-left
    lines put in visual order when arabic-reshaper and python-bidi are
    installed (see ``pdf_bidi``), else they stay unjoined

Like the DOCX writer, PDFs are binary so this module exposes
``write_bytes`` and is registered in core.writers.__init__ under
BINARY_WRITERS. ``write`` raises so the text-writer surface stays
sane.
"""
from __future__ import annotations

import io
import os
from typing import Any

from . import pdf_bidi, pdf_fonts
from .base import coerce_seconds, fmt_srt_time, normalize_text, replace_lone_surrogates


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
    from reportlab.lib.enums import TA_RIGHT  # type: ignore[import-not-found]
    from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore[import-not-found]
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore[import-not-found]
    from reportlab.lib.units import inch  # type: ignore[import-not-found]
    from reportlab.platypus import (  # type: ignore[import-not-found]
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=(replace_lone_surrogates(os.path.basename(audio_path))
               if audio_path else "Transcript"),
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
    chain = pdf_fonts.default_chain()
    markup = chain.markup
    base = chain.base
    if base is not None:
        title_style = ParagraphStyle(
            name="TitleText", parent=title_style, fontName=base.name
        )
        body_style.fontName = base.name
    rtl_style = ParagraphStyle(name="BodyRTL", parent=body_style, alignment=TA_RIGHT)
    by_name = {f.name: f for f in chain.fonts}
    # The frame's text width (6 pt padding on each side), less a little
    # slack so reportlab never re-wraps a line broken by pdf_bidi.
    line_width = doc.width - 12 - 2

    def measure(text: str, bold: bool, size: float) -> float:
        total = 0.0
        for name, chunk in chain.split_runs(text):
            if not name:
                face = "Helvetica-Bold" if bold else "Helvetica"
            else:
                face = by_name[name].bold_name if bold else name
            total += stringWidth(chunk, face, size)
        return total

    def bidi_markup(prefix: str, body: str, size: float, bold_body: bool) -> tuple[str, bool] | None:
        """Markup with pre-broken lines for text that needs shaping,
        or None to take the plain path."""
        if not pdf_bidi.needs_bidi(prefix + body):
            return None
        eng = pdf_bidi.engine()
        if eng is None:
            return None
        lines, rtl = pdf_bidi.layout(
            prefix, body, line_width,
            lambda t, b: measure(t, b or bold_body, size), eng,
        )
        rows = []
        for line in lines:
            parts = []
            for text, bold in line:
                if bold or bold_body:
                    parts.append(f"<b>{markup(text, bold=True)}</b>")
                else:
                    parts.append(markup(text))
            rows.append("".join(parts))
        return "<br/>".join(rows), rtl

    story: list[Any] = []
    title = (replace_lone_surrogates(os.path.basename(audio_path))
             if audio_path else "Transcript")
    shaped_title = bidi_markup("", title, title_style.fontSize, True)
    if shaped_title is not None:
        story.append(Paragraph(shaped_title[0], title_style))
    else:
        story.append(Paragraph(f"<b>{markup(title, bold=True)}</b>", title_style))
    nonempty = [s for s in segments if normalize_text(s.get("text", ""))]
    if nonempty:
        # A last segment without an end time counts up to its start.
        last_end = coerce_seconds(
            nonempty[-1].get("end"), coerce_seconds(nonempty[-1].get("start"))
        )
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
            replace_lone_surrogates(str(raw_speaker).strip())
            if raw_speaker not in (None, "") else ""
        )
        plain = normalize_text(seg.get("text", ""))
        prefix = f"[{ts}] {speaker}:" if speaker else f"[{ts}]"
        shaped = bidi_markup(prefix, plain, body_style.fontSize, False)
        if shaped is not None:
            story.append(Paragraph(shaped[0], rtl_style if shaped[1] else body_style))
            continue
        text = markup(plain)
        if speaker:
            line = f"<b>[{ts}] {markup(speaker, bold=True)}:</b> {text}"
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
