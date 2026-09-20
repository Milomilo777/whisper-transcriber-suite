"""Bounded, single-worker transcription job manager for the LAN server.

This module is intentionally Tk-free and imports nothing from ``app/``.
It owns a small in-memory job table and a SINGLE background worker thread
that processes queued jobs one at a time. Sequential processing is a
deliberate design choice, not a limitation:

  * ``core.transcriber`` keeps the ~3 GB Whisper model in a module-global
    (``MODEL`` / ``PIPELINE``). Loading it once and reusing it keeps the
    model HOT across jobs.
  * Running ``transcribe()`` concurrently against that shared global is
    unsafe; one worker thread naturally bounds concurrency to 1.

Each job's media is written into a per-job temp dir under
``user_cache_dir()/server_jobs/<uuid>/``. ``core.transcriber.transcribe``
writes its outputs NEXT TO the input file (the beside-input contract), so
the outputs land in that same per-job dir with no path-traversal risk.

A job is one of:

  * an UPLOAD — raw media bytes the handler streamed into the per-job dir,
  * a URL — an http(s) link downloaded with yt-dlp into the per-job dir
    first, then transcribed.

The transcribe driver is injected (``transcribe_fn``) so tests can run the
whole state machine against a fake that just writes dummy output files —
never the real model.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import queue
import shutil
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from core import __version__
from core.config import PROJECT_FILE_NAME, user_cache_dir

logger = logging.getLogger(__name__)


# --- public types ------------------------------------------------------------

# Status values a job moves through. Terminal states are "finished",
# "error", and "cancelled".
STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

_TERMINAL = frozenset({STATUS_FINISHED, STATUS_ERROR, STATUS_CANCELLED})


class TranscribeFn(Protocol):
    """The transcribe callable the manager drives.

    Mirrors ``core.transcriber.transcribe`` (task, progress_cb, log_cb,
    language_cb) so the real engine can be passed straight through, while
    tests inject a fake that writes dummy outputs.
    """

    def __call__(
        self,
        task: Any,
        progress_cb: Callable[[int], None] | None = None,
        log_cb: Callable[[str], None] | None = None,
        language_cb: Callable[[str, float], None] | None = None,
    ) -> None: ...


# A callable that downloads an http(s) URL into ``dest_dir`` and returns the
# saved media path. Injected so tests don't hit the network.
DownloadFn = Callable[[str, str], str]

# A callable that delivers one outgoing webhook payload. Injected so tests
# can capture deliveries without a network round-trip; the default is
# :func:`post_webhook`, which applies the SSRF gate.
WebhookFn = Callable[[str, dict[str, Any]], None]


@dataclass
class Job:
    """One transcription request and its live state."""

    job_id: str
    kind: str  # "upload" | "url"
    formats: list[str]
    language: str = ""
    # Source description for history / logging (filename or URL).
    source: str = ""
    status: str = STATUS_QUEUED
    progress: int = 0
    error: str = ""
    # Language the engine detected (falls back to the requested language).
    # Surfaced in the OpenAI-compatible verbose_json response and in the
    # outgoing webhook payload.
    detected_language: str = ""
    # The media file to transcribe (set once an upload lands or a URL is
    # downloaded). Outputs are written beside it.
    media_path: str = ""
    # Per-job working directory; deleted on cleanup.
    work_dir: str = ""
    # Written output files, as (fmt, absolute_path) pairs.
    outputs: list[tuple[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    # Cooperative-cancel flag; the transcribe task object mirrors this.
    cancelled: bool = False
    # Cooperative-pause flag; the transcribe task object mirrors this so the
    # engine's ``while task.paused`` loop stalls the segment loop. The web
    # gets the same per-task pause/resume the desktop Queue has.
    paused: bool = False
    # Optional clip window (seconds) applied to the task; map onto the
    # _ServerTask.clip_start / clip_end attributes the engine already reads.
    clip_start: float | None = None
    clip_end: float | None = None
    # Validated per-job advanced options (vad/diarization/etc.). Written into
    # ``work_dir/.whisperproject.json`` before transcribe so they take effect
    # for THIS job only via the audited per-folder override mechanism.
    options: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        """The JSON shape returned by ``GET /api/jobs/<id>``."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "paused": self.paused,
            "outputs": [{"fmt": fmt, "name": os.path.basename(p)}
                        for fmt, p in self.outputs],
        }

    def list_dict(self) -> dict[str, Any]:
        """The compact JSON shape returned by ``GET /api/jobs`` (list)."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "paused": self.paused,
            "source": self.source,
            "formats": list(self.formats),
            "created_at": self.created_at,
        }


class _ServerTask:
    """The task object passed to ``transcribe_fn`` for EVERY server job.

    Despite the lean shape, this is NOT a cancel-only helper: it is the one
    task duck-type the engine sees for all LAN/web jobs. It MUST mirror every
    attribute ``core.transcriber.transcribe`` (and ``resume_transcription``)
    reads off a task, or the engine raises ``AttributeError`` mid-run and the
    job dies with no output. Currently read by the engine:

      * ``file_path``, ``language``, ``output_formats`` (inputs)
      * ``output_paths``, ``detected_language``, ``language_probability``
        (written back by the engine)
      * ``resume``, ``clip_start``, ``clip_end``, ``history_id`` (inputs)
      * the cooperative ``cancelled`` flag AND the ``paused`` flag, both read
        bare inside the segment loop (``while task.paused and not
        task.cancelled``). Both are bridged to the owning ``Job`` so the
        web's pause/resume/cancel routes flip the live task: setting
        ``job.paused`` stalls the engine's segment loop, ``job.cancelled``
        ends it. They must EXIST or the loop raises.

    Using a plain object keeps this module free of any ``app/`` task import
    while still satisfying the engine's duck-typed access. Keep this in sync
    with the attributes ``core.transcriber.transcribe`` reads.
    """

    def __init__(self, job: Job) -> None:
        self.file_path: str = job.media_path
        self.language: str | None = job.language or None
        self.output_formats: list[str] | None = list(job.formats) or None
        self.output_paths: list[str] | None = None
        self.detected_language: str = ""
        self.language_probability: float = 0.0
        self.resume: bool = False
        # Clip window is set from the job (validated on submit); the engine
        # reads clip_start/clip_end off the task via getattr.
        self.clip_start: float | None = job.clip_start
        self.clip_end: float | None = job.clip_end
        self.history_id: int = 0
        self._job = job

    @property
    def cancelled(self) -> bool:
        return self._job.cancelled

    @cancelled.setter
    def cancelled(self, value: bool) -> None:
        self._job.cancelled = bool(value)

    @property
    def paused(self) -> bool:
        return self._job.paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._job.paused = bool(value)


class JobManager:
    """Bounded queue + single worker thread driving transcriptions.

    Thread-safe. The handler thread(s) call :meth:`submit_upload` /
    :meth:`submit_url` / :meth:`get` / :meth:`cancel`; one private worker
    thread runs :meth:`_drain`.
    """

    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        *,
        download_fn: DownloadFn | None = None,
        max_jobs: int = 100,
        max_queued: int = 50,
        record_history: bool = True,
        jobs_root: str | None = None,
        webhook_url: str = "",
        webhook_sender: WebhookFn | None = None,
    ) -> None:
        self._transcribe = transcribe_fn
        self._download = download_fn
        self._max_jobs = max_jobs
        self._max_queued = max_queued
        self._record_history = record_history
        # Outgoing completion webhook (empty = disabled). ``webhook_sender``
        # is a test seam; the default ``post_webhook`` applies the SSRF gate.
        self._webhook_url = (webhook_url or "").strip()
        self._webhook_sender = webhook_sender or post_webhook
        self._jobs_root = (
            jobs_root if jobs_root is not None
            else str(user_cache_dir() / "server_jobs")
        )
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    # --- lifecycle -----------------------------------------------------------

    @property
    def stopped(self) -> bool:
        """True once :meth:`stop` has been signalled.

        Polled by long-lived HTTP handlers (the OpenAI-compatible route
        waits for its job) so they don't hang on a server that is shutting
        down with the job still queued.
        """
        return self._stop.is_set()

    def start(self) -> None:
        """Start the background worker thread (idempotent)."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            os.makedirs(self._jobs_root, exist_ok=True)
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._drain, name="server-job-worker", daemon=True
            )
            self._worker.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the worker to exit and wait briefly for it.

        Before joining, flip every non-terminal job to ``cancelled=True`` /
        ``paused=False`` (exactly what :meth:`cancel` does). A PAUSED in-flight
        job otherwise leaves the worker parked forever inside the engine's
        ``while task.paused and not task.cancelled`` spin: that loop never
        inspects ``self._stop``, so without un-pausing + cancelling it the
        worker would not exit, ``join`` would time out, and the worker thread
        (pinning the open media handle + the ~3 GB model) would leak — blocking
        a clean in-process restart and the per-job work_dir deletion on Windows.
        """
        self._stop.set()
        with self._lock:
            for job in self._jobs.values():
                if job.status not in _TERMINAL:
                    job.cancelled = True
                    job.paused = False
        # Unblock a waiting get().
        self._queue.put("")
        w = self._worker
        if w is not None:
            w.join(timeout=timeout)

    # --- submission ----------------------------------------------------------

    def _new_job(self, kind: str, formats: list[str], language: str,
                 source: str, *, options: dict[str, Any] | None = None,
                 clip_start: float | None = None,
                 clip_end: float | None = None) -> Job:
        """Create + register a job, enforcing the total-jobs cap.

        Caller must hold ``self._lock``.
        """
        if len(self._queued_ids()) >= self._max_queued:
            raise QueueFull("too many queued jobs; try again later")
        # Evict the oldest terminal job(s) once we exceed the total cap so a
        # long-lived server doesn't grow unbounded.
        self._evict_locked()
        if len(self._jobs) >= self._max_jobs:
            raise QueueFull("server is at capacity; try again later")
        job_id = uuid.uuid4().hex
        work_dir = os.path.join(self._jobs_root, job_id)
        os.makedirs(work_dir, exist_ok=True)
        job = Job(
            job_id=job_id, kind=kind, formats=list(formats),
            language=language, source=source, work_dir=work_dir,
            options=dict(options or {}),
            clip_start=clip_start, clip_end=clip_end,
        )
        self._jobs[job_id] = job
        self._order.append(job_id)
        return job

    def submit_upload(self, filename: str, data: bytes, formats: list[str],
                      language: str = "", *,
                      options: dict[str, Any] | None = None,
                      clip_start: float | None = None,
                      clip_end: float | None = None) -> str:
        """Register an upload job from already-read bytes; return job_id."""
        safe = _safe_filename(filename)
        with self._lock:
            job = self._new_job("upload", formats, language, safe,
                                options=options, clip_start=clip_start,
                                clip_end=clip_end)
            media_path = os.path.join(job.work_dir, safe)
            with open(media_path, "wb") as f:
                f.write(data)
            job.media_path = media_path
            self._queue.put(job.job_id)
            return job.job_id

    def submit_upload_stream(
        self, filename: str, formats: list[str], language: str = "", *,
        options: dict[str, Any] | None = None,
        clip_start: float | None = None,
        clip_end: float | None = None,
    ) -> tuple[str, str]:
        """Register an upload job and return ``(job_id, media_path)``.

        The handler writes the streamed bytes to ``media_path`` itself
        (so a large file never has to sit fully in RAM) and then calls
        :meth:`enqueue_upload` to start processing. This is the LIVE upload
        path the request handler uses — bytes never sit whole in RAM.
        """
        safe = _safe_filename(filename)
        with self._lock:
            job = self._new_job("upload", formats, language, safe,
                                options=options, clip_start=clip_start,
                                clip_end=clip_end)
            job.media_path = os.path.join(job.work_dir, safe)
            return job.job_id, job.media_path

    def enqueue_upload(self, job_id: str) -> None:
        """Queue a streamed-upload job once its bytes are on disk."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
        self._queue.put(job_id)

    def discard(self, job_id: str) -> None:
        """Remove a never-enqueued job + its dir (streamed upload failed).

        Used by the handler when a streamed upload aborts before it could be
        enqueued, so a half-written work dir doesn't linger.
        """
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return
            if job_id in self._order:
                self._order.remove(job_id)
        if job is not None:
            _rmtree_quiet(job.work_dir)

    def submit_url(self, url: str, formats: list[str],
                   language: str = "", *,
                   options: dict[str, Any] | None = None,
                   clip_start: float | None = None,
                   clip_end: float | None = None) -> str:
        """Register a URL job; return job_id. Scheme is validated here."""
        if not is_safe_url(url):
            raise ValueError("only http(s) URLs are accepted")
        with self._lock:
            job = self._new_job("url", formats, language, url,
                                options=options, clip_start=clip_start,
                                clip_end=clip_end)
            job.media_path = ""  # filled in after the download
            self._queue.put(job.job_id)
            return job.job_id

    # --- queries -------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def output_path(self, job_id: str, fmt: str) -> str | None:
        """Absolute path of a finished job's output for ``fmt``, or None.

        Matches first on the stored format KEY (e.g. ``smtv_docx``), then
        falls back to the on-disk EXTENSION so a plain ``?fmt=docx`` also
        downloads an output stored under a registry key like ``smtv_docx``.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            want = fmt.lower()
            for f, p in job.outputs:
                if f.lower() == want:
                    return p
            # Extension fallback: ?fmt=docx -> the smtv_docx file on disk.
            for _f, p in job.outputs:
                if os.path.splitext(p)[1].lstrip(".").lower() == want:
                    return p
        return None

    def list(self) -> list[dict[str, Any]]:
        """Snapshot of every job for ``GET /api/jobs``, newest first.

        Reads under the lock so a concurrent worker mutation can't tear a
        row. Returns the compact :meth:`Job.list_dict` shape.
        """
        with self._lock:
            jobs = [self._jobs[jid] for jid in self._order
                    if jid in self._jobs]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.list_dict() for j in jobs]

    def cancel(self, job_id: str) -> bool:
        """Flag a job for cooperative cancellation. Returns True if found."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in _TERMINAL:
                return False
            job.cancelled = True
            # A paused job must un-pause so the engine's segment loop can see
            # the cancel and exit instead of spinning on ``while task.paused``.
            job.paused = False
            return True

    def pause(self, job_id: str) -> bool:
        """Flag a non-terminal job paused. Returns True if it was flippable.

        The owning :class:`_ServerTask` bridges ``paused`` to the job, so the
        engine's ``while task.paused`` loop stalls the live segment loop.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL:
                return False
            job.paused = True
            return True

    def resume(self, job_id: str) -> bool:
        """Clear a job's paused flag. Returns True if it was flippable."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL:
                return False
            job.paused = False
            return True

    def _queued_ids(self) -> list[str]:
        return [jid for jid, j in self._jobs.items()
                if j.status == STATUS_QUEUED]

    def _evict_locked(self) -> None:
        """Drop + clean up oldest terminal jobs once over the total cap.

        Caller holds ``self._lock``. Only terminal jobs are evicted so an
        in-flight job is never deleted out from under the worker.
        """
        while len(self._jobs) >= self._max_jobs:
            victim_id = next(
                (jid for jid in self._order
                 if jid in self._jobs and self._jobs[jid].status in _TERMINAL),
                None,
            )
            if victim_id is None:
                return  # nothing terminal to evict; the cap check will reject
            victim = self._jobs.pop(victim_id)
            self._order.remove(victim_id)
            _rmtree_quiet(victim.work_dir)

    # --- worker --------------------------------------------------------------

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._stop.is_set():
                break
            if not job_id:
                continue
            job = self.get(job_id)
            if job is None or job.cancelled:
                if job is not None:
                    self._set_status(job, STATUS_CANCELLED)
                    _rmtree_quiet(job.work_dir)
                continue
            self._run_one(job)

    def _run_one(self, job: Job) -> None:
        history_db = None
        history_id = None
        started = time.time()
        try:
            if job.kind == "url":
                self._set_status(job, STATUS_DOWNLOADING)
                if self._download is None:
                    raise RuntimeError("URL downloads are not configured")
                job.media_path = self._download(job.source, job.work_dir)
            if job.cancelled:
                self._set_status(job, STATUS_CANCELLED)
                return
            if not job.media_path or not os.path.isfile(job.media_path):
                raise RuntimeError("no media file to transcribe")

            history_db, history_id = self._open_history(job)
            # Write the per-job advanced options into a .whisperproject.json
            # in the job's work_dir BEFORE transcribe. The engine's
            # _runtime_overrides_scope calls load_project_overrides(
            # task.file_path) at the start of each transcribe() and restores
            # config after, so these options apply to THIS job only and the
            # single-threaded worker stays race-free. The media lives in the
            # SAME work_dir, so find_project_file walks up to this file.
            self._write_override_file(job)
            self._set_status(job, STATUS_RUNNING)
            task = _ServerTask(job)

            def _progress(p: int) -> None:
                job.progress = max(0, min(100, int(p)))

            self._transcribe(task, _progress, None, None)

            if job.cancelled:
                self._set_status(job, STATUS_CANCELLED)
            else:
                job.outputs = self._collect_outputs(job, task)
                job.progress = 100
                self._set_status(job, STATUS_FINISHED)
            job.detected_language = (
                getattr(task, "detected_language", "") or job.language)
            self._finish_history(
                history_db, history_id, job, time.time() - started,
                job.detected_language,
            )
            self._fire_webhook(job)
        except Exception as e:  # noqa: BLE001
            logger.exception("job %s failed", job.job_id)
            job.error = str(e)
            self._set_status(job, STATUS_ERROR)
            self._finish_history(
                history_db, history_id, job, time.time() - started,
                job.language, error=str(e),
            )
            self._fire_webhook(job)

    def _write_override_file(self, job: Job) -> None:
        """Drop the job's validated options into ``work_dir/.whisperproject.json``.

        The engine's per-folder override mechanism
        (``core.config.load_project_overrides`` →
        ``core.transcriber._runtime_overrides_scope``) reads this file at the
        start of transcribe() and restores ``config`` after, so the options
        apply to THIS job only. The media file lives in the same work_dir, so
        ``find_project_file`` walks up from ``task.file_path`` and finds it.
        Never fatal: a write failure just means the job runs with the
        server-level config (a worse result, not a crash).
        """
        if not job.options or not job.work_dir:
            return
        path = os.path.join(job.work_dir, PROJECT_FILE_NAME)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(job.options, f)
        except OSError as e:
            logger.warning("could not write override file for job %s: %s",
                           job.job_id, e)

    def _collect_outputs(self, job: Job, task: Any) -> list[tuple[str, str]]:
        """Map the files the engine wrote to their formats.

        The engine records every written path on ``task.output_paths`` (the
        authoritative list). We map each path's extension back to a requested
        format — far more reliable than re-globbing ``work_dir`` by mtime,
        which can mis-pick the ``.chapters.json`` / partial-checkpoint ``.json``
        a newer write left behind. Falls back to the legacy dir-scan only when
        the engine recorded nothing (e.g. an alt path that didn't set it).

        The requested ``job.formats`` are registry KEYS (e.g. ``smtv_docx``),
        but the engine writes their real on-disk EXTENSION (e.g. ``docx``).
        We map each requested key through ``core.transcriber._FMT_EXTENSIONS``
        and match the file by that extension, then surface it under the
        requested key so a ``?fmt=smtv_docx`` download resolves (a plain
        ``?fmt=docx`` also resolves via the extension fallback in
        ``output_path``). Without this map, smtv_docx files were written but
        never surfaced (job finished, outputs=[], ?fmt=smtv_docx -> 404).
        """
        written = getattr(task, "output_paths", None)
        if written:
            try:
                from core.transcriber import _FMT_EXTENSIONS
            except Exception:  # noqa: BLE001 - never let an import break collection
                _FMT_EXTENSIONS = {}
            out: list[tuple[str, str]] = []
            seen_keys: set[str] = set()
            # Build ext -> registry-key so the on-disk file maps back to the
            # key the caller asked for (e.g. "docx" -> "smtv_docx").
            ext_to_key: dict[str, str] = {}
            for key in job.formats:
                kl = key.lower()
                ext = _FMT_EXTENSIONS.get(kl, kl).lower()
                # First requested key for an extension wins; this keeps a
                # plain "docx" request distinct from "smtv_docx" when both
                # are asked for (different on-disk files anyway).
                ext_to_key.setdefault(ext, kl)
            for p in written:
                if not p:
                    continue
                ext = os.path.splitext(p)[1].lstrip(".").lower()
                # Only surface formats the caller asked for, so the
                # auto-chapters ``.chapters.json`` sidecar is not offered as
                # the "json" download when json wasn't requested.
                key = ext_to_key.get(ext)
                if key and key not in seen_keys and os.path.isfile(p):
                    out.append((key, p))
                    seen_keys.add(key)
            if out:
                return out
        return self._collect_outputs_by_scan(job)

    def _collect_outputs_by_scan(self, job: Job) -> list[tuple[str, str]]:
        """Legacy fallback: find outputs by globbing the per-job dir.

        Used only when the engine recorded no ``task.output_paths``. Match by
        extension against the requested formats; newest by mtime wins (the
        "(1)" re-run case).
        """
        out: list[tuple[str, str]] = []
        try:
            names = os.listdir(job.work_dir)
        except OSError:
            return out
        media_name = os.path.basename(job.media_path)
        for fmt in job.formats:
            ext = f".{fmt.lower()}"
            matches = [n for n in names
                       if n.lower().endswith(ext) and n != media_name]
            if not matches:
                continue
            matches.sort(
                key=lambda n: os.path.getmtime(os.path.join(job.work_dir, n)),
                reverse=True,
            )
            out.append((fmt, os.path.join(job.work_dir, matches[0])))
        return out

    def _set_status(self, job: Job, status: str) -> None:
        job.status = status
        if status in _TERMINAL:
            job.finished_at = time.time()

    # --- outgoing webhook ----------------------------------------------------

    def _fire_webhook(self, job: Job) -> None:
        """POST a completion payload on a daemon thread (fire-and-forget).

        Only ``finished`` / ``error`` fire — a cancelled job is neither a
        success nor a failure. The send runs on its own daemon thread so a
        slow or hanging endpoint can never stall the single job worker or
        keep the process alive at exit. ``post_webhook`` applies the SSRF
        gate; any transport failure is logged and swallowed.
        """
        if not self._webhook_url:
            return
        if job.status not in (STATUS_FINISHED, STATUS_ERROR):
            return
        payload = webhook_payload(job)
        url = self._webhook_url
        sender = self._webhook_sender

        def _run() -> None:
            try:
                sender(url, payload)
            except Exception:  # noqa: BLE001 - never affect job processing
                logger.exception("server: webhook POST to %s failed", url)

        threading.Thread(
            target=_run, name="server-webhook", daemon=True).start()

    # --- history (optional, never fatal) -------------------------------------

    def _open_history(self, job: Job) -> tuple[Any, int | None]:
        if not self._record_history:
            return None, None
        try:
            from core.history import HistoryDB
            db = HistoryDB()
            rid = db.insert_transcription(
                job.media_path or job.source, model="", language=job.language,
            )
            return db, rid
        except Exception as e:  # noqa: BLE001
            logger.warning("history.db unavailable for job %s: %s",
                           job.job_id, e)
            return None, None

    def _finish_history(self, db: Any, rid: int | None, job: Job,
                        duration_s: float, language: str,
                        error: str = "") -> None:
        if db is None or rid is None:
            return
        status_map = {
            STATUS_FINISHED: "finished",
            STATUS_ERROR: "error",
            STATUS_CANCELLED: "cancelled",
        }
        try:
            db.finish_transcription(
                rid, status_map.get(job.status, "error"),
                output_paths=[p for _, p in job.outputs],
                duration_seconds=duration_s, language=language, error=error,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("could not finish history row for job %s: %s",
                           job.job_id, e)
        finally:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


class QueueFull(Exception):
    """Raised when the server is at its job/queue cap (HTTP 503)."""


# --- pure helpers (unit-testable) --------------------------------------------

# Windows reserved DEVICE names. A file named after one of these (with or
# without an extension) is not a real file: opening it talks to the device,
# so e.g. ``NUL.wav`` discards every byte written and the job later dies with
# a misleading "no media file" error. Compared case-insensitively against the
# extension-stripped stem.
_WIN_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _safe_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe basename.

    Strips any directory components and rejects traversal so the media
    can only ever land inside the per-job dir. Falls back to a generic
    name when the input is empty or all-suspect.

    Also renames a Windows reserved DEVICE name (CON, PRN, AUX, NUL,
    COM1-9, LPT1-9 — with or without an extension) by prefixing an
    underscore, so the upload becomes an ordinary file instead of being
    routed to the device (which would silently discard the bytes).
    """
    base = os.path.basename(name or "").strip()
    # Drop anything that isn't a tame filename character; keep dots,
    # dashes, underscores, spaces, and alphanumerics.
    cleaned = "".join(
        c for c in base
        if c.isalnum() or c in (".", "-", "_", " ")
    ).strip()
    cleaned = cleaned.lstrip(".") or ""
    if not cleaned:
        return f"upload-{uuid.uuid4().hex[:8]}.bin"
    # Reserved-name guard: split off the extension and, if the stem is a
    # reserved device name, prefix an underscore so it becomes a real file.
    stem, ext = os.path.splitext(cleaned)
    if stem.upper() in _WIN_RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned


def _parse_legacy_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Parse ``inet_aton``-style legacy numeric IPv4 forms.

    :mod:`ipaddress` only accepts the dotted-decimal form, but the stacks
    that actually fetch a URL (libc resolvers, yt-dlp, ffmpeg, browsers)
    historically also accept a single decimal/hex integer
    (``2130706433`` == ``127.0.0.1``), octal parts (``0177.0.0.1``), hex
    parts (``0x7f.0.0.1``), and short forms (``127.1``). Without this, such
    a literal sails past the :func:`ipaddress` check below and — on a host
    whose own ``getaddrinfo`` also rejects the form — falls through the
    fail-open DNS path as "allowed", even though the fetch layer may still
    interpret it as loopback. Returns the address, or ``None`` when ``host``
    is not a numeric form at all (ordinary DNS names always land here).
    """
    if not host or len(host) > 64:
        return None
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return None
    parts = host.split(".")
    if len(parts) > 4:
        return None
    nums: list[int] = []
    for part in parts:
        if not part or len(part) > 18:
            return None
        try:
            if part[:2].lower() == "0x":
                digits = part[2:]
                if not digits or any(
                    c not in "0123456789abcdefABCDEF" for c in digits
                ):
                    return None
                nums.append(int(digits, 16))
            elif len(part) > 1 and part.startswith("0"):
                # Leading-zero means octal to inet_aton — and "08"/"09" are
                # simply invalid there (not decimal 8/9).
                if any(c not in "01234567" for c in part):
                    return None
                nums.append(int(part, 8))
            elif part.isascii() and part.isdigit():
                nums.append(int(part, 10))
            else:
                return None
        except ValueError:
            return None
    # inet_aton range rules: every part but the last must fit in one byte;
    # the last part fills all remaining bytes (e.g. "127.1" -> 127.0.0.1).
    width = (1,) * (len(nums) - 1) + (5 - len(nums),)
    value = 0
    for num, size in zip(nums, width):
        if num >= 1 << (8 * size):
            return None
        value = (value << (8 * size)) | num
    try:
        return ipaddress.IPv4Address(value)
    except ValueError:
        return None


def is_safe_url(url: str) -> bool:
    """True iff ``url`` is an http(s) URL with a host that is not an obvious
    internal / cloud-metadata target.

    Rejects ``file://``, ``ftp://``, bare paths, and anything without a
    network location (the scheme gate). On top of that it applies a MINIMAL
    SSRF guard: a host that is — or resolves to — a loopback, link-local
    (including the ``169.254.169.254`` cloud-metadata address), unspecified,
    or otherwise reserved / multicast address is rejected, so a client who can
    reach ``POST /api/jobs`` cannot make the server fetch its own loopback
    services or the cloud instance-metadata endpoint.

    Deliberately NOT blocked: ordinary RFC-1918 private ranges (10.x,
    172.16-31.x, 192.168.x). This server is documented to run on a trusted
    LAN where fetching from a private media server is a legitimate use, so
    blocking those would break the normal case. DNS resolution is best-effort:
    a name that fails to resolve is allowed through (yt-dlp will surface the
    real fetch error) rather than rejected, but a name that DOES resolve to a
    dangerous address is rejected. yt-dlp still follows its own redirects, so
    this gate is a first line of defence, not a complete fix — keep URL jobs
    on a trusted network. The static page carries the same warning.
    """
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
    except (ValueError, AttributeError):
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    try:
        host = parsed.hostname or ""
    except ValueError:
        return False
    if not host:
        return False

    def _addr_blocked(
        ip: "ipaddress.IPv4Address | ipaddress.IPv6Address",
    ) -> bool:
        # Block loopback (127.0.0.0/8, ::1), link-local (169.254/16 incl. the
        # cloud-metadata IP, fe80::/10), unspecified (0.0.0.0, ::), multicast,
        # and reserved. Private RFC-1918 ranges are intentionally allowed.
        return bool(
            ip.is_loopback or ip.is_link_local or ip.is_unspecified
            or ip.is_multicast or ip.is_reserved
        )

    # A literal-IP host: decide directly, no DNS. Besides strict
    # dotted-decimal, also catch legacy inet_aton numeric forms (a fetch
    # stack may treat "2130706433" as 127.0.0.1 even where getaddrinfo
    # does not — see _parse_legacy_ipv4).
    literal = host.strip("[]")
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        ip = None
    if ip is None:
        legacy = _parse_legacy_ipv4(literal)
        if legacy is not None:
            return not _addr_blocked(legacy)
    if ip is not None:
        return not _addr_blocked(ip)

    # A name: resolve best-effort and reject only on a confirmed dangerous
    # address. A resolution failure is allowed through (the fetch layer will
    # report the real error) so transient DNS issues don't block normal URLs.
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return True
    for info in infos:
        sockaddr = info[4]
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _addr_blocked(resolved):
            return False
    return True


def _rmtree_quiet(path: str) -> None:
    if not path:
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


# --- outgoing webhooks -------------------------------------------------------

_WEBHOOK_TIMEOUT_S = 10.0
_WEBHOOK_MAX_RESPONSE_BYTES = 64 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects for webhook POSTs.

    The SSRF gate validates the configured URL, not wherever a 30x points
    next, so following a redirect could bounce a public URL into a loopback /
    metadata address. Returning ``None`` makes urllib treat the redirect as
    an unhandled error instead of fetching the new location.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def webhook_payload(job: Job) -> dict[str, Any]:
    """The JSON body POSTed when a job finishes (success or failure).

    Pure: no I/O, so it is unit-testable. Outputs are reported by basename
    only — the webhook consumer does not need (and should not receive) the
    host's internal file paths.
    """
    return {
        "event": ("job.finished" if job.status == STATUS_FINISHED
                  else "job.error"),
        "job_id": job.job_id,
        "status": job.status,
        "source": job.source,
        "language": job.detected_language or job.language,
        "formats": list(job.formats),
        "outputs": [{"fmt": fmt, "name": os.path.basename(p)}
                    for fmt, p in job.outputs],
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


def post_webhook(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = _WEBHOOK_TIMEOUT_S,
) -> None:
    """POST ``payload`` as JSON to ``url``, gated by the SSRF guard.

    Reuses :func:`is_safe_url` — the same loopback / link-local /
    cloud-metadata / reserved-address refusal the inbound URL-job path
    applies — so a webhook cannot be pointed at the host's own loopback
    services or the cloud instance-metadata endpoint. Redirects are not
    followed (see :class:`_NoRedirectHandler`). An unsafe URL is logged and
    skipped; transport errors propagate to the caller, which in production
    is the fire-and-forget sender that logs and drops them.
    """
    if not is_safe_url(url):
        logger.warning("server: refusing webhook POST to unsafe URL %s", url)
        return
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"WhisperTranscriberSuite/{__version__}",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler)
    with opener.open(request, timeout=timeout) as response:
        # Bounded read so a hostile endpoint can't stream forever.
        response.read(_WEBHOOK_MAX_RESPONSE_BYTES)
