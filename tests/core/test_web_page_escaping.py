"""Static sink guards for the LAN web page (``core/server/static/index.html``).

The page is plain JavaScript that builds rows by string concatenation into
``innerHTML``, so every job-originating string must go through
``escapeHtml()`` and every numeric value used in a ``style="width:..."``
must go through ``Number()``. There is no JS test harness in this repo,
so these checks pin the exact sink patterns by source inspection.

Background: the 2026-07-18 hardening commit (099b759) fixed most sinks
but left two unguarded — the ``start()`` submit-failure error message and
``renderSubmit()``'s progress bar — even though its own commit message
claimed both classes were covered. See ``PROJECT_INDEX.md`` (Gotchas,
LAN web page) for the field-by-field rule.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PAGE = _REPO / "core" / "server" / "static" / "index.html"


def _page_text() -> str:
    return _PAGE.read_text(encoding="utf-8")


def test_progress_widths_go_through_number():
    text = _page_text()
    # renderSubmit(): j.progress arrives from GET /api/jobs/<id>; a job's
    # progress field must never land in style="width:..." uncoerced.
    assert "(j.progress || 0)" not in text, (
        "raw j.progress reaches a style=\"width:...\" sink; wrap it in Number()"
    )
    # One bar each in renderSubmit(), renderJobs(), renderRecent().
    assert text.count("Number(j.progress) || 0") == 3, (
        "expected all three progress bars (submit/jobs/recent) to coerce "
        "j.progress through Number()"
    )


def test_server_error_messages_are_escaped():
    text = _page_text()
    # Both fetch catch handlers render a server-provided error string
    # (start()'s POST /api/jobs catch and loadResult()'s GET catch).
    assert "escapeHtml(e.message)" in text
    assert "+ e.message" not in text, (
        "an error message reaches innerHTML without escapeHtml()"
    )


def test_known_untrusted_job_fields_are_escaped():
    text = _page_text()
    # Each sentinel is what the current code looks like when the field is
    # guarded; a regression that drops the wrapper fails here.
    for sentinel in (
        "escapeHtml(name)",                 # download-link display name
        "escapeHtml(j.source)",             # jobs + recent rows (title + text)
        "escapeHtml(j.error",               # failed-job message
        "escapeHtml(statusTxt)",            # job status cell
        "escapeHtml(String(seg.speaker))",  # transcript speaker label
        "escapeHtml(String(seg.text",       # transcript segment text
        ".map(escapeHtml)",                 # per-job formats list
    ):
        assert sentinel in text, f"missing escaping sink: {sentinel}"
