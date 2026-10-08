"""Link -> subtitled video: the burn stage of a chained download.

A download queued with "Make subtitled video" runs three stages on the
existing queues: the download itself, the auto-transcription that the
download hands off to (``enqueue_transcription_from_download``), and a burn
of the transcription's own SRT into ``<title>-subbed.mp4``. The Download row
shows every stage ("running", "transcribing", "burning") with one rising
percent, and its Cancel stops whichever stage is active.

Finished files are never removed: a failure or Cancel at any stage keeps the
download and the transcript, and only ever drops the burn's own temp file.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.domain.task_outputs import task_output_with_ext
from core import burn_subs

logger = logging.getLogger(__name__)

SUBBED_SUFFIX = "-subbed"

# Share of the row's percent each stage covers (download, transcribe, burn).
_DOWNLOAD_END = 40.0
_TRANSCRIBE_END = 85.0


def chain_progress(status: str, stage_percent: float) -> float:
    """One rising percent for a chained row, from its stage and that stage's %."""
    p = min(100.0, max(0.0, float(stage_percent or 0)))
    if status == "transcribing":
        return _DOWNLOAD_END + (_TRANSCRIBE_END - _DOWNLOAD_END) * p / 100.0
    if status == "burning":
        return _TRANSCRIBE_END + (100.0 - _TRANSCRIBE_END) * p / 100.0
    if status == "finished":
        return 100.0
    return _DOWNLOAD_END * p / 100.0


def subbed_output_path(media_path: str) -> str:
    """``<stem>-subbed.mp4`` beside the media, or ``... (N).mp4`` if taken."""
    stem = os.path.splitext(media_path)[0]
    return burn_subs.free_output_path(stem + SUBBED_SUFFIX + ".mp4")


def after_transcription(app: Any, dl: Any, tr: Any, finished: bool) -> None:
    """The transcription stage of *dl* ended (Tk thread): burn, or stop.

    *finished* is False for a failed or cancelled transcription; the row then
    ends as "error" / "cancelled" with the download and any transcript kept.
    """
    if not finished:
        status = "cancelled" if getattr(tr, "cancelled", False) else "error"
        reason = "was cancelled" if status == "cancelled" else "failed"
        _end(app, dl, status, error=f"The transcription {reason}; no subtitled video was made.")
        return
    if getattr(tr, "no_speech", False):
        _end(app, dl, "error", error="No speech was found; no subtitled video was made.")
        return
    srt = task_output_with_ext(tr, ".srt")
    if srt is None:
        _end(app, dl, "error", error="The transcription wrote no .srt file; no subtitled video was made.")
        return
    start_burn(app, dl, srt)


def start_burn(app: Any, dl: Any, srt_path: str) -> None:
    """Burn *srt_path* into the download's file on a background thread."""
    from core._threads import safe_thread

    media = dl.saved_path
    if not media or not os.path.isfile(media):
        _end(app, dl, "error", error="The downloaded file is gone; no subtitled video was made.")
        return
    out_path = subbed_output_path(media)
    dl.status = "burning"
    dl.burn_progress = 0.0
    app.log(f"-> Burning subtitles into {os.path.basename(out_path)}")
    app.refresh_download_queue()
    shown = [-1]

    def _progress(pct: float) -> None:
        dl.burn_progress = pct
        if int(pct) != shown[0]:
            shown[0] = int(pct)
            app.post_to_main(app.refresh_download_queue)

    def _on_process(proc: Any) -> None:
        # The row's Cancel (App.cancel_download) tree-kills task.process.
        dl.process = proc

    def _worker() -> None:
        try:
            burn_subs.burn(
                media, srt_path, out_path,
                progress_cb=_progress,
                cancel_check=lambda: bool(getattr(dl, "cancelled", False)),
                on_process=_on_process,
            )
        except burn_subs.BurnCancelled:
            app.post_to_main(lambda: _end(app, dl, "cancelled"))
        except Exception as e:  # noqa: BLE001 - reported on the row and in the log
            logger.exception("Subtitle burn failed: file=%s out=%s", media, out_path)
            msg = f"Burning the subtitles failed: {e}"
            app.post_to_main(lambda: _end(app, dl, "error", error=msg))
        else:
            app.post_to_main(lambda: _end(app, dl, "finished", burned=out_path))
        finally:
            dl.process = None

    safe_thread(_worker, name="burn-subs-chain")


def _end(app: Any, dl: Any, status: str, *, error: str = "", burned: str = "") -> None:
    """Close the chained row: history first, then the row and the log."""
    media = getattr(dl, "saved_path", None)
    paths = [p for p in (media, burned) if p]
    if burned:
        dl.burned_path = burned
    service = getattr(app, "download_service", None)
    if service is not None:
        service._finish_history(dl, status, paths, error=error)
    # A Cancel that landed after the encode finished keeps the finished file.
    if burned or dl.status != "cancelled":
        dl.status = status
    if status == "finished":
        dl.progress = 100
        app.log(f"✓ Subtitled video: {burned}")
    elif status == "cancelled":
        app.log(f"Subtitled video cancelled: {os.path.basename(media or '')} and its transcript are kept.")
    else:
        app.log(f"Subtitled video not made: {error} The downloaded file and any transcript are kept.")
    app.refresh_download_queue()
