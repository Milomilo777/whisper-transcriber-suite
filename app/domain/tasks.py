"""Task models for the queues."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.task import TranscriptionTask  # re-exported for callers

__all__ = ["TranscriptionTask", "VideoDownloadTask"]


class VideoDownloadTask:
    """A single yt-dlp download job tracked in the Download Videos queue."""

    def __init__(
        self,
        url: str,
        folder: str,
        format_label: str,
        format_info: dict[str, Any],
        title: str = "",
        subtitles_enabled: bool = False,
        subtitle_lang: str = "",
        detected_language: str = "",
        section_start: float | None = None,
        section_end: float | None = None,
        caption_only: bool = False,
        caption_kind: str = "",
    ) -> None:
        self.url = url
        self.folder = folder
        self.format_label = format_label
        self.format_info = format_info
        self.title = title
        self.status = "waiting"
        self.progress: float = 0
        # R2 — download "pause" is stop-and-continue (yt-dlp has no live
        # pause signal): pause tears down the process like cancel but keeps
        # the partial .part file and flips status to "paused"; resume
        # re-enqueues the SAME task and yt-dlp continues via -c/--continue.
        # Distinct from ``cancelled`` so the teardown path can tell which
        # terminal status to land on.
        self.paused: bool = False
        self.start_time: float | None = None
        # Frozen wall-clock for terminal downloads (finished /
        # cancelled / error) — same role as on TranscriptionTask.
        self.end_time: float | None = None
        self.process: Any = None
        self.cancelled = False
        self.subtitles_enabled = subtitles_enabled
        self.subtitle_lang = subtitle_lang
        self.detected_language = detected_language
        # Phase 3a — primary key in core.history.HistoryDB.downloads
        self.history_id: int = 0
        # v1.0.3 — optional time-range slice (yt-dlp --download-sections).
        # Wall-clock seconds from the start of the source video. Either
        # bound may be None (open-ended on that side). Both None means
        # the full video is downloaded. SMTV downloads ignore these
        # (the SMTV CDN does no server-side slicing); the download
        # service logs a WARN line and proceeds with the full clip.
        # These intentionally do NOT collide with the existing
        # ``start_time`` / ``end_time`` fields above, which are *wall-
        # clock timestamps of the running task* used by the Elapsed
        # column.
        self.section_start: float | None = section_start
        self.section_end: float | None = section_end
        # "Use captions instead" shortcut (see
        # DownloadService.enqueue_caption_only_from_form): when True, the
        # worker fetches only the existing captions and converts them to
        # the configured output formats -- it never downloads media or
        # queues a transcription. caption_kind ("manual"/"auto") is
        # captured at enqueue time from the format lookup's already-
        # fetched caption info and decides whether the rolling-caption
        # dedup pass runs (see core.convert.dedupe_rolling_captions).
        self.caption_only: bool = caption_only
        self.caption_kind: str = caption_kind
        # Full path of the finished download (set by DownloadService._finish)
        # so the Download tab can offer a one-click "Open file".
        self.saved_path: str | None = None
        # When auto-transcribe-after-download is on, the spawned
        # TranscriptionTask is linked here so the Download row can show
        # "transcribing" + the live transcription progress (instead of
        # looking idle at 100%). Cleared when that transcription ends.
        self.transcription_task: Any = None

    def time_range_label(self) -> str | None:
        """Short human-readable badge for the Queue row.

        Returns e.g. ``"0:51 -> 1:25"``, ``"start -> 1:25"``,
        ``"0:51 -> end"``. ``None`` when neither bound is set so the
        caller can skip the badge entirely.
        """
        if self.section_start is None and self.section_end is None:
            return None

        def _fmt(seconds: float | None, *, fallback: str) -> str:
            if seconds is None:
                return fallback
            total = int(seconds)
            hours, rem = divmod(total, 3600)
            minutes, secs = divmod(rem, 60)
            if hours:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"

        return f"{_fmt(self.section_start, fallback='start')} -> {_fmt(self.section_end, fallback='end')}"
