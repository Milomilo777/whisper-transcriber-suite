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

from app import desktop_alert
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


def rising_chain_progress(dl: Any, stage_percent: float) -> float:
    """The row percent of a chained download, never lower than shown before
    (yt-dlp reports the video and the audio stream each from 0 to 100)."""
    if dl.status not in ("running", "transcribing", "burning", "finished"):
        return float(dl.progress or 0)
    value = max(float(getattr(dl, "chain_percent", 0.0) or 0.0),
                chain_progress(dl.status, stage_percent))
    dl.chain_percent = value
    return value


def subbed_output_path(media_path: str) -> str:
    """Reserve ``<stem>-subbed.mp4`` beside the media (``... (N).mp4`` if
    taken) as an empty placeholder, so two chains of one title never share
    a name; the burn replaces it, a failure removes it."""
    stem = os.path.splitext(media_path)[0]
    return burn_subs.reserve_output_path(stem + SUBBED_SUFFIX + ".mp4")


# The check before the transcription runs on the Tk thread, so it is short;
# an unanswered probe lets the chain go on and the burn itself refuses a file
# without a picture (burn_subs.burn probes again, on its own thread).
_QUICK_PROBE_S = 5.0


def has_no_video(path: str, timeout: float = _QUICK_PROBE_S) -> bool:
    """True only when ffprobe read *path* and found no video stream."""
    return burn_subs.probe_media(path, timeout=timeout).has_video is False


NO_VIDEO_ERROR = "The downloaded file has no video picture; no subtitled video was made."


def refuse_without_video(app: Any, dl: Any, media: str) -> str:
    """Before the transcription: the error text when the download has no
    picture (the row is set to "error" and the log says why), else ""."""
    if not has_no_video(media):
        return ""
    dl.status = "error"
    app.log(f"Subtitled video not made: {NO_VIDEO_ERROR} The downloaded file is kept.")
    return NO_VIDEO_ERROR


def after_transcription(app: Any, dl: Any, tr: Any, finished: bool) -> None:
    """The transcription stage of *dl* ended (Tk thread): burn, or stop.

    *finished* is False for a failed or cancelled transcription; the row then
    ends as "error" / "cancelled" with the download and any transcript kept.
    """
    if not finished:
        status = "cancelled" if getattr(tr, "cancelled", False) else "error"
        reason = "was cancelled" if status == "cancelled" else "failed"
        end_chain(app, dl, status, error=f"The transcription {reason}; no subtitled video was made.")
        return
    if getattr(tr, "no_speech", False):
        end_chain(app, dl, "error", error="No speech was found; no subtitled video was made.")
        return
    srt = task_output_with_ext(tr, ".srt")
    if srt is None:
        end_chain(app, dl, "error", error="The transcription wrote no .srt file; no subtitled video was made.")
        return
    start_burn(app, dl, srt)


def start_burn(app: Any, dl: Any, srt_path: str) -> None:
    """Burn *srt_path* into the download's file on a background thread."""
    from core._threads import safe_thread

    media = dl.saved_path
    if not media or not os.path.isfile(media):
        end_chain(app, dl, "error", error="The downloaded file is gone; no subtitled video was made.")
        return
    try:
        out_path = subbed_output_path(media)
    except OSError as e:
        # A folder that refuses new files, a name the system cannot hold:
        # the download and the transcript are already saved, so the row ends
        # as an error with the reason instead of failing silently.
        logger.warning("Subtitle burn: could not reserve the output name beside %s", media, exc_info=True)
        end_chain(app, dl, "error", error=f"The subtitled video file could not be created: {e}")
        return
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
                placeholder=out_path,
            )
        except burn_subs.BurnCancelled:
            burn_subs.release_reserved_path(out_path)
            app.post_to_main(lambda: end_chain(app, dl, "cancelled"))
        except Exception as e:  # noqa: BLE001 - reported on the row and in the log
            burn_subs.release_reserved_path(out_path)
            logger.exception("Subtitle burn failed: file=%s out=%s", media, out_path)
            msg = f"Burning the subtitles failed: {e}"
            app.post_to_main(lambda: end_chain(app, dl, "error", error=msg))
        else:
            app.post_to_main(lambda: end_chain(app, dl, "finished", burned=out_path))
        finally:
            dl.process = None

    try:
        dl.status = "burning"
        dl.burn_progress = 0.0
        app.log(f"-> Burning subtitles into {os.path.basename(out_path)}")
        app.refresh_download_queue()
        safe_thread(_worker, name="burn-subs-chain")
    except Exception as e:  # noqa: BLE001 - the placeholder must not outlive a burn that never ran
        burn_subs.release_reserved_path(out_path)
        logger.exception("Subtitle burn: could not start the burn thread")
        end_chain(app, dl, "error", error=f"The subtitle burn could not start: {e}")


def fail_unstarted_burn(app: Any, dl: Any, exc: BaseException) -> None:
    """``after_transcription`` raised: close the row as an error with a reason.

    A burn that already started reports itself (its thread ends the chain), so
    only a row that is not "burning" is closed here.
    """
    if getattr(dl, "status", "") == "burning":
        return
    try:
        end_chain(app, dl, "error", error=f"The subtitle burn could not start: {exc}")
    except Exception:  # noqa: BLE001 - last resort: the row must not stay "transcribing"
        logger.exception("Could not close the chained row after a failed burn start")
        dl.status = "error"


def end_chain(app: Any, dl: Any, status: str, *, error: str = "", burned: str = "") -> None:
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
        desktop_alert.burn_done(app, burned)
    elif status == "cancelled":
        app.log(f"Subtitled video cancelled: {os.path.basename(media or '')} and its transcript are kept.")
    else:
        app.log(f"Subtitled video not made: {error} The downloaded file and any transcript are kept.")
        desktop_alert.chain_failed(app, dl, error)
    app.refresh_download_queue()
