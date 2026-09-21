from __future__ import annotations

from typing import Any


class TranscriptionTask:
    def __init__(self, file_path: str) -> None:
        self.file_path: str = file_path
        self.status: str = "waiting"
        self.progress: int = 0
        self.start_time: float | None = None
        # Frozen wall-clock for a terminal task. Set once by the
        # service / app cancel path when the task transitions to
        # finished / cancelled / error. Without this the Elapsed
        # column in the Queue tab kept ticking after the worker
        # had already returned, so the user never saw "this file
        # took 1m 22s" — they only saw a number that kept growing
        # while their attention had moved on.
        self.end_time: float | None = None
        self.paused: bool = False
        self.cancelled: bool = False
        # Phase 2a additions
        self.detected_language: str = ""
        self.language_probability: float = 0.0
        self.language: str | None = None
        # Phase 3a — primary key in core.history.HistoryDB.transcriptions
        self.history_id: int = 0
        # Correlation id for the JSON worker protocol (add-only field).
        # The parent stamps the same value on the ``transcribe`` command and
        # on every later cancel/pause/resume for this task, so the worker can
        # attribute a control to exactly one task instead of guessing "the
        # current one". Empty = no id (legacy behaviour). See
        # app.services.transcription_service.task_correlation_id and the
        # design notes in core/worker.py.
        self.task_id: str = ""
        # Resume-from-cancellation: when True the worker dispatches
        # ``resume_transcription`` instead of ``transcribe`` so the
        # partial checkpoint on disk is reused. Falls back to a fresh
        # transcribe automatically if the partial is stale (different
        # source mtime, changed model/config, etc.).
        self.resume: bool = False
        # Set by the app when this task was auto-spawned from a finished
        # download. Holds the originating VideoDownloadTask so the
        # Download row can mirror "transcribing" + progress and flip back
        # to "finished" when this task ends. Typed Any to keep core free
        # of an app-layer import.
        self.source_download: Any = None
        # Optional transcription time-slice (Transcribe-tab time range).
        # Wall-clock seconds into the source; both None = the whole file.
        # The span is pre-sliced to a temp WAV via ffmpeg and the results
        # are shifted back onto the original timeline — deliberately NOT
        # passed to faster-whisper as clip_timestamps, which decodes the
        # whole file and hung on multi-hour input (see core/transcriber.py).
        self.clip_start: float | None = None
        self.clip_end: float | None = None
        # Output formats for THIS task (srt/json/docx/pdf/...). Set at
        # dispatch from the live config so the long-lived worker writes the
        # formats the user currently has selected — its import-time
        # config snapshot would otherwise be stale (the docx-never-written
        # bug). None = fall back to the worker's config default.
        self.output_formats: list[str] | None = None
        # The actual files written by the last (re)transcribe, as
        # reported by the worker in its "done" event. The UI uses these
        # for the history record + the "Last result" card instead of
        # re-deriving names from config (which missed docx/pdf and the
        # de-duped "name (1).srt" form). None until a run completes.
        self.output_paths: list[str] | None = None
        # Transcript stats computed by the worker from the in-memory
        # segments (word total; last segment end as the duration lower
        # bound) and carried back in its "done" event. The parent's
        # history/usage-stats path prefers these over re-parsing an
        # output file, which is impossible when the user's selected
        # formats include no machine-readable transcript (txt/docx/pdf
        # only) — that case used to record word_count=0.
        self.word_count: int = 0
        self.audio_duration: float = 0.0
