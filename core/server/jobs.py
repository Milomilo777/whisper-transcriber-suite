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

import inspect
import ipaddress
import json
import logging
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from core import __version__, offline
from core.config import PROJECT_FILE_NAME, user_cache_dir, user_data_dir

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
DownloadFn = Callable[..., str]


class DownloadCancelled(Exception):
    """A URL download was stopped because its job was cancelled."""


@dataclass(frozen=True)
class DownloadLimits:
    """What a download function must honour while it runs.

    Passed as a third argument to download functions that accept one (a
    two-argument ``fn(url, dest_dir)`` still works and gets no limits).
    ``cancelled`` is polled; ``max_bytes`` / ``timeout_s`` of 0 mean no limit.
    """

    cancelled: Callable[[], bool]
    max_bytes: int = 0
    timeout_s: float = 0.0


def _accepts_limits(fn: Callable[..., Any]) -> bool:
    """True if ``fn`` can take a third positional ``limits`` argument."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return True
    return any(p.name == "limits" and p.kind is not p.KEYWORD_ONLY
               for p in params)


# Default bounds for one URL download: a server must not fill the disk or be
# held by a stalled transfer for ever.
_DEFAULT_MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024
_DEFAULT_DOWNLOAD_TIMEOUT_S = 2 * 60 * 60.0

# A job directory left by an earlier run (the job table is in memory only)
# is deleted at start-up once it is this old.
_STALE_JOB_DIR_AGE_S = 6 * 60 * 60.0
_JOB_DIR_NAME_RE = re.compile(r"^[0-9a-f]{32}$")
# Written into every job folder this version creates. Folders without it come
# from an older version, whose history rows may still point at their outputs,
# so the purge never touches them. The file names its owner (a JSON object
# with the server's process id, that process's start time and an instance id)
# so one server never purges a folder another server still uses.
_JOB_DIR_MARKER = ".wts-job"
# A marker with no readable owner (written by an older build) is purged only
# after this much longer idle time.
_LEGACY_JOB_DIR_AGE_S = 7 * 24 * 60 * 60.0
# Two start times this close (seconds) are the same process. Generous on
# purpose: on Linux a process start time is derived from the boot time,
# which moves when the system clock is stepped; a reused process id still
# differs by far more (the owner lived for hours, the folder is hours old).
_START_TIME_TOLERANCE_S = 60.0

# Written into a job folder whose outputs could not all be copied to
# outputs_root (disk full): a JSON list of the file names still to save. A
# folder holding it is deleted only after those files have a copy.
_KEEP_FILE = ".wts-keep"
# Removing the media of a finished job is retried this often (an engine or
# ffmpeg child may still hold the file open for a moment on Windows).
_KEEP_LIST_MAX_BYTES = 1024 * 1024
_MEDIA_REMOVE_ATTEMPTS = 4
_MEDIA_REMOVE_DELAY_S = 0.25
_UNSAVED_WARNING = (
    "The results could not be copied to the server's output folder (is the "
    "disk full?). Download them now; the server keeps this job's folder "
    "until they are copied.")

# What a cloud engine that died part-way leaves beside the media
# (core.transcriber._save_partial_subtitles): paid text, never deleted.
_PARTIAL_SUFFIX = ".partial.srt"
# The output key under which a failed job offers that file for download.
PARTIAL_OUTPUT_KEY = "partial_srt"

# Every JobManager by instance id, so a marker can be matched to a manager
# that is still running in THIS process. Weak: a dropped manager is gone.
_MANAGERS: "weakref.WeakValueDictionary[str, JobManager]" = (
    weakref.WeakValueDictionary())

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
    # Set once the job is ending (outputs being saved): a cancel is refused.
    settling: bool = False
    # A visible problem that does not fail the job (outputs not archived).
    warning: str = ""

    def public_dict(self) -> dict[str, Any]:
        """The JSON shape returned by ``GET /api/jobs/<id>``."""
        data: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "paused": self.paused,
            "outputs": [{"fmt": fmt, "name": os.path.basename(p)}
                        for fmt, p in self.outputs],
        }
        if self.warning:
            data["warning"] = self.warning
        return data

    def list_dict(self) -> dict[str, Any]:
        """The compact JSON shape returned by ``GET /api/jobs`` (list)."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "paused": self.paused,
            "source": self.public_source(),
            "formats": list(self.formats),
            "created_at": self.created_at,
        }

    def public_source(self) -> str:
        """The source as shown to clients: a URL job loses its query and
        user info (they often hold a token); an upload shows its file name."""
        return strip_url_secrets(self.source) if self.kind == "url" else self.source


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
      * ``checkpoint_failures`` (the periodic checkpoint writer's counter)
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
        # Read and updated by the engine's periodic checkpoint writer.
        self.checkpoint_failures: int = 0
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
        outputs_root: str | None = None,
        max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
        download_timeout_s: float = _DEFAULT_DOWNLOAD_TIMEOUT_S,
    ) -> None:
        self._transcribe = transcribe_fn
        self._download = download_fn
        self._max_download_bytes = max_download_bytes
        self._download_timeout_s = download_timeout_s
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
        # Finished outputs are copied here for the history row: the job
        # directory above is temporary (cap eviction, start-up purge).
        if outputs_root is not None:
            self._outputs_root = outputs_root
        elif jobs_root is not None:
            self._outputs_root = os.path.join(
                os.path.dirname(os.path.abspath(jobs_root)), "server_outputs")
        else:
            self._outputs_root = str(user_data_dir() / "server_outputs")
        self._instance_id = uuid.uuid4().hex
        _MANAGERS[self._instance_id] = self
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
            self._purge_stale_dirs_locked()
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._drain, name="server-job-worker", daemon=True
            )
            self._worker.start()

    def _purge_stale_dirs_locked(self) -> None:
        """Delete job directories an earlier run left behind.

        The job table lives in memory only, so after a restart nothing can
        reach the old ``<jobs_root>/<id>`` directories (uploads of up to
        several GB). Only directories named like a job id, not in this
        table, untouched for :data:`_STALE_JOB_DIR_AGE_S` and whose OWNER is
        provably gone go; finished outputs a history row points at were
        copied to ``outputs_root`` already. Servers in one or several
        processes share the folder (the GUI's web access, ``gui.py serve``, a
        second app window), so a job table that lacks a folder does not make
        it an orphan: the marker names the owning server (see
        :func:`_marker_owner_state`), and a live owner keeps its folders.
        """
        try:
            names = os.listdir(self._jobs_root)
        except OSError:
            return
        now = time.time()
        removed = 0
        for name in names:
            if name in self._jobs or not _JOB_DIR_NAME_RE.match(name):
                continue
            path = os.path.join(self._jobs_root, name)
            marker = os.path.join(path, _JOB_DIR_MARKER)
            try:
                if not os.path.isdir(path) or not os.path.isfile(marker):
                    continue
                state = _marker_owner_state(_read_text(marker))
                if state == "live":
                    continue
                limit = (_STALE_JOB_DIR_AGE_S if state == "gone"
                         else _LEGACY_JOB_DIR_AGE_S)
                if os.path.getmtime(path) > now - limit:
                    continue
            except OSError:
                continue
            except Exception:  # noqa: BLE001 - one odd folder never stops start
                logger.exception("server: could not judge job folder %s", name)
                continue
            if self._discard_dir(path):
                removed += 1
        if removed:
            logger.info("server: removed %d old job folder(s)", removed)

    def _marker_text(self) -> str:
        """The content of this server's job-folder marker (its identity)."""
        return json.dumps({
            "v": 1, "pid": os.getpid(),
            "started": _process_start_time(os.getpid()),
            "instance": self._instance_id,
        })

    def _discard_dir(self, work_dir: str, job: Job | None = None) -> bool:
        """Delete a job folder, unless it holds results not saved elsewhere.

        Persist first: the job's outputs and the engine's partial subtitles
        (see :meth:`_protected_files`) are copied to ``outputs_root`` before
        the folder goes; if a copy fails the folder stays and ``False`` is
        returned. ``job`` is the job that owns the folder; the start-up
        purge has none, and then only what the folder itself proves counts.
        """
        if not work_dir:
            return True
        if not self._save_protected(work_dir, job):
            logger.warning(
                "server: kept job folder %s: its results could not be "
                "copied", os.path.basename(work_dir))
            if job is not None:
                # The job is leaving the table: its input is of no use any
                # more and can be gigabytes, whatever happens to the results.
                self._drop_input_media(job)
            return False
        _rmtree_quiet(work_dir)
        return True

    def _protected_files(self, work_dir: str, job: Job | None) -> list[str]:
        """Files of ``work_dir`` that must have a durable copy before it goes.

        * the job's outputs and the engine's own ``<media>.partial.srt``
          (never the media: a client may upload a file that ends in
          ``.partial.srt``, and copying client data would let it fill the
          output folder);
        * the names in the folder's keep list (a failed archive wrote it);
        * without a job (start-up purge), a ``X.partial.srt`` with a media
          file ``X.<ext>`` beside it: a run that died before it could settle.
          A lone ``big.partial.srt`` is a client's upload, not a partial.
        """
        work = os.path.normcase(os.path.abspath(work_dir))
        media = (os.path.normcase(os.path.abspath(job.media_path))
                 if job is not None and job.media_path else "")
        found: dict[str, str] = {}

        def add(path: str, *, is_output: bool = False) -> None:
            if not path or not os.path.isfile(path):
                return
            key = os.path.normcase(os.path.abspath(path))
            if os.path.dirname(key) != work or (key == media and not is_output):
                return
            found.setdefault(key, path)

        if job is not None:
            for _fmt, out in job.outputs:
                add(out, is_output=True)
            add(self._partial_file(job))
        try:
            names = os.listdir(work_dir)
        except OSError:
            return list(found.values())
        if _KEEP_FILE in names:
            listed = _read_keep_list(os.path.join(work_dir, _KEEP_FILE))
            for name in listed or []:
                if name in names:
                    add(os.path.join(work_dir, name))
        if job is None:
            for name in names:
                if not name.lower().endswith(_PARTIAL_SUFFIX):
                    continue
                stem = name[:-len(_PARTIAL_SUFFIX)]
                if any(other != name and not other.startswith(".")
                       and not other.lower().endswith(_PARTIAL_SUFFIX)
                       and os.path.splitext(other)[0] == stem
                       for other in names):
                    add(os.path.join(work_dir, name))
        return list(found.values())

    def _save_protected(self, work_dir: str, job: Job | None) -> bool:
        """Give every protected file of ``work_dir`` a copy; True if all have one."""
        dest_dir = os.path.join(
            self._outputs_root, os.path.basename(os.path.normpath(work_dir))[:12])
        saved = True
        keep = os.path.join(work_dir, _KEEP_FILE)
        if os.path.exists(keep) and _read_keep_list(keep) is None:
            # The list of unsaved files cannot be trusted (cut short or
            # damaged): unreadable never means "nothing to protect".
            logger.error("server: the keep list of job folder %s is "
                         "unreadable; the folder is kept",
                         os.path.basename(work_dir))
            saved = False
        for src in self._protected_files(work_dir, job):
            dest = os.path.join(dest_dir, os.path.basename(src))
            try:
                if (os.path.isfile(dest)
                        and os.path.getsize(dest) == os.path.getsize(src)):
                    continue
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(src, dest)
            except OSError as e:
                logger.warning("server: could not keep %s: %s",
                               os.path.basename(src), e)
                saved = False
        return saved

    def _write_keep_file(self, job: Job, paths: list[str]) -> None:
        """Record which files of the job folder still lack a durable copy.

        Written as real UTF-8 (not ``\\uXXXX`` escapes): Persian titles would
        otherwise grow six-fold. If even this write fails, the names go to
        the log at error level, the last trace of where the results are.
        """
        names = sorted({os.path.basename(p) for p in paths})
        try:
            with open(os.path.join(job.work_dir, _KEEP_FILE), "w",
                      encoding="utf-8") as f:
                json.dump(names, f, ensure_ascii=False)
        except OSError as e:
            logger.error(
                "server: could not write the keep list of job %s (%s); "
                "results without a copy in %s: %s",
                job.job_id, e, job.work_dir, ", ".join(names))

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the worker to exit, wait briefly, reclaim work_dirs.

        Before joining, flip every non-terminal job to ``cancelled=True`` /
        ``paused=False`` (exactly what :meth:`cancel` does). A PAUSED in-flight
        job otherwise leaves the worker parked forever inside the engine's
        ``while task.paused and not task.cancelled`` spin: that loop never
        inspects ``self._stop``, so without un-pausing + cancelling it the
        worker would not exit, ``join`` would time out, and the worker thread
        (pinning the open media handle + the ~3 GB model) would leak — blocking
        a clean in-process restart and the per-job work_dir deletion on Windows.

        After the join, every job the worker will never finish is marked
        CANCELLED and its work_dir reclaimed: a job still queued when
        ``_stop`` is set is never dequeued (``_drain`` exits without draining
        the queue), and a job whose engine ignored the cancel past ``timeout``
        would otherwise keep its media dir forever. An in-flight job the
        worker is still winding down is left alone — ``_run_one``/``_drain``
        set its status and clean up as soon as the engine returns. FINISHED
        jobs are untouched: their work_dir still backs ``output_path``
        downloads. ``_rmtree_quiet`` tolerates the open media handle a
        still-running engine may briefly hold on Windows.
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

        worker_alive = w is not None and w.is_alive()
        leftovers: list[Job] = []
        with self._lock:
            for job in self._jobs.values():
                if job.status in _TERMINAL:
                    continue
                if worker_alive and job.status != STATUS_QUEUED:
                    # Still in flight; _run_one/_drain will finish it.
                    continue
                job.cancelled = True
                job.paused = False
                self._set_status(job, STATUS_CANCELLED)
                leftovers.append(job)
        for job in leftovers:
            self._discard_dir(job.work_dir, job)

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
        try:
            with open(os.path.join(work_dir, _JOB_DIR_MARKER), "w",
                      encoding="utf-8") as f:
                f.write(self._marker_text())
        except OSError:
            pass  # without the marker the folder is simply never purged
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
            self._discard_dir(job.work_dir, job)

    def submit_url(self, url: str, formats: list[str],
                   language: str = "", *,
                   options: dict[str, Any] | None = None,
                   clip_start: float | None = None,
                   clip_end: float | None = None) -> str:
        """Register a URL job; return job_id. Scheme is validated here."""
        if offline.is_offline():
            # Before is_safe_url, which looks the host name up.
            raise ValueError(offline.refused("a link job"))
        if not is_safe_url(url):
            # is_safe_url also refuses loopback / link-local / cloud-metadata
            # hosts (SSRF guard); say so, instead of claiming a plain
            # http://127.0.0.1/... link is not http.
            raise ValueError(
                "only http(s) URLs to a public or LAN host are accepted "
                "(this computer's own / link-local addresses are refused)"
            )
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
            # A failed job's partial subtitles are only offered under their
            # own key, never as the complete ?fmt=srt.
            for f, p in job.outputs:
                if f == PARTIAL_OUTPUT_KEY:
                    continue
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
            if job.status in _TERMINAL or job.settling:
                # Ending jobs are past the point where a cancel can apply:
                # the client must not see "cancelled" for a finished job.
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
            self._discard_dir(victim.work_dir, victim)

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
                    self._discard_dir(job.work_dir, job)
                continue
            self._run_one(job)
            # Path B reclaim: a job that ended CANCELLED (cancelled mid-run)
            # or ERROR (engine raised) owns no downloadable output, so its
            # work_dir is dead weight. FINISHED work_dirs are deliberately
            # kept — ``output_path`` serves client downloads straight out of
            # them; ``_evict_locked`` reclaims those once the table fills. An
            # ERROR job that kept a partial subtitle file has it as an
            # output, so its folder stays too; ``_discard_dir`` also saves
            # any partial a cancelled job left before deleting.
            if job.status in (STATUS_CANCELLED, STATUS_ERROR) and not job.outputs:
                self._discard_dir(job.work_dir, job)

    def _run_one(self, job: Job) -> None:
        history_db = None
        history_id = None
        started = time.time()
        try:
            if job.kind == "url":
                self._set_status(job, STATUS_DOWNLOADING)
                if self._download is None:
                    raise RuntimeError("URL downloads are not configured")
                # A job queued before Work offline was turned on.
                offline.require_online("downloading this link")
                if _accepts_limits(self._download):
                    job.media_path = self._download(
                        job.source, job.work_dir,
                        DownloadLimits(
                            cancelled=lambda: job.cancelled,
                            max_bytes=self._max_download_bytes,
                            timeout_s=self._download_timeout_s))
                else:
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

            # Set before the status flips: a client polling for "finished"
            # (the OpenAI-compatible route) must never read the old value.
            job.detected_language = (
                getattr(task, "detected_language", "") or job.language)
            with self._lock:
                cancelled = job.cancelled
                job.settling = True  # from here a cancel() is refused
            if cancelled:
                self._settle(job, STATUS_CANCELLED, history_db, history_id,
                             time.time() - started, job.detected_language)
            else:
                job.outputs = self._collect_outputs(job, task)
                job.progress = 100
                self._settle(job, STATUS_FINISHED, history_db, history_id,
                             time.time() - started, job.detected_language)
            self._fire_webhook(job)
        except DownloadCancelled:
            self._set_status(job, STATUS_CANCELLED)
        except Exception as e:  # noqa: BLE001
            logger.exception("job %s failed", job.job_id)
            # job.error reaches web clients and the webhook: no local paths
            # or command lines there. The local log and history keep it all.
            job.error = public_error_text(e)
            with self._lock:
                job.settling = True
            # A paid cloud run that died part-way left its finished text in
            # a partial subtitle file: offer it as the job's output.
            partial = self._partial_file(job)
            if partial:
                job.outputs = [(PARTIAL_OUTPUT_KEY, partial)]
            self._settle(job, STATUS_ERROR, history_db, history_id,
                         time.time() - started, job.language, error=str(e))
            self._fire_webhook(job)

    def _partial_file(self, job: Job) -> str:
        """Path of the ``<media>.partial.srt`` a failed cloud run kept, or ""."""
        if not job.media_path:
            return ""
        path = os.path.splitext(job.media_path)[0] + _PARTIAL_SUFFIX
        return path if os.path.isfile(path) else ""

    def _settle(self, job: Job, status: str, db: Any, rid: int | None,
                duration_s: float, language: str, error: str = "") -> None:
        """End a job: persist first, report second.

        Outputs are copied out of the temporary folder and the history row is
        written BEFORE the job reads as terminal (a client polling for
        "finished" may act on it at once, and a terminal job can be evicted),
        then the server-owned input media is removed (also when a copy
        failed: the unsaved outputs are protected by the keep list and the
        folder is then never deleted). Never raises: the
        status is always set, whatever a step above did.
        """
        job.settling = True
        try:
            kept = self._archive_outputs(job)
        except Exception:  # noqa: BLE001
            logger.exception("server: could not archive outputs of job %s",
                             job.job_id)
            kept = [p for _fmt, p in job.outputs]
        # A path still inside the job folder is a copy that failed.
        work = os.path.normcase(os.path.abspath(job.work_dir))
        unsaved = [p for p in kept
                   if os.path.normcase(os.path.dirname(os.path.abspath(p))) == work]
        if unsaved:
            logger.error("server: %d result file(s) of job %s have no copy "
                         "outside the job folder", len(unsaved), job.job_id)
            job.warning = _UNSAVED_WARNING
            self._write_keep_file(job, unsaved)
        try:
            self._finish_history(db, rid, job, duration_s, language,
                                 error=error, status=status, output_paths=kept)
        except Exception:  # noqa: BLE001
            logger.exception("server: could not write history for job %s",
                             job.job_id)
        # The input is expendable even when a copy failed: the outputs are
        # what matters, and they stay protected (keep list, folder kept).
        try:
            self._drop_input_media(job)
        except Exception:  # noqa: BLE001
            logger.exception("server: could not remove the media of job %s",
                             job.job_id)
        self._set_status(job, status)

    def _drop_input_media(self, job: Job) -> None:
        """Delete the media the server itself stored for a finished job.

        An upload or a download lives in the job's own folder and can be up
        to several GB; without this it stays until cap eviction. A file
        anywhere else (a download function that returned some other path)
        is not the server's to delete. A file that cannot be removed (Windows
        keeps an open file) is logged and left for the folder's removal.
        """
        if not job.media_path or not job.work_dir:
            return
        media = os.path.normcase(os.path.abspath(job.media_path))
        work = os.path.normcase(os.path.abspath(job.work_dir))
        root = os.path.normcase(os.path.abspath(self._jobs_root))
        if os.path.dirname(media) != work or os.path.dirname(work) != root:
            return
        if any(os.path.normcase(os.path.abspath(p)) == media
               for _fmt, p in job.outputs):
            return
        for attempt in range(_MEDIA_REMOVE_ATTEMPTS):
            try:
                os.remove(job.media_path)
                return
            except FileNotFoundError:
                return
            except OSError as e:
                if attempt + 1 == _MEDIA_REMOVE_ATTEMPTS:
                    logger.warning(
                        "server: could not remove the media of job %s: %s",
                        job.job_id, e)
                else:
                    time.sleep(_MEDIA_REMOVE_DELAY_S)

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
            for key in job.formats:
                kl = key.lower()
                # txt + express_scribe: the plain "name.txt" is the txt
                # output whatever the request order ("name.express_scribe.txt"
                # is matched by its stem below). smtv_docx keeps its rule.
                if (
                    _FMT_EXTENSIONS.get(kl, kl).lower() == kl
                    and ext_to_key.get(kl) != "smtv_docx"
                ):
                    ext_to_key[kl] = kl
            for p in written:
                if not p:
                    continue
                ext = os.path.splitext(p)[1].lstrip(".").lower()
                # Only surface formats the caller asked for, so the
                # auto-chapters ``.chapters.json`` sidecar is not offered as
                # the "json" download when json wasn't requested.
                key = ext_to_key.get(ext)
                # Two keys can share an extension (txt / express_scribe);
                # the engine then writes the second as "name.<key>.<ext>".
                stem_lower = os.path.splitext(os.path.basename(p))[0].lower()
                for k in job.formats:
                    kl = k.lower()
                    if (
                        stem_lower.endswith("." + kl)
                        and _FMT_EXTENSIONS.get(kl, kl).lower() == ext
                    ):
                        key = kl
                        break
                if key and key in seen_keys:
                    # Two requested keys share this extension (docx and
                    # smtv_docx): the engine writes them in request order, so
                    # the next file belongs to the next unseen key.
                    key = next(
                        (k.lower() for k in job.formats
                         if _FMT_EXTENSIONS.get(k.lower(), k.lower()).lower() == ext
                         and k.lower() not in seen_keys),
                        None)
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
            dated: list[tuple[float, str]] = []
            for n in matches:
                try:
                    dated.append(
                        (os.path.getmtime(os.path.join(job.work_dir, n)), n))
                except OSError:
                    continue  # vanished since the listing
            if not dated:
                continue
            dated.sort(reverse=True)
            out.append((fmt, os.path.join(job.work_dir, dated[0][1])))
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
        if offline.is_offline():
            logger.info("server: webhook not sent (offline mode is on)")
            offline.skipped("the server's webhook")
            return
        payload = webhook_payload(job)
        url = self._webhook_url
        sender = self._webhook_sender

        def _run() -> None:
            try:
                sender(url, payload)
            except Exception:  # noqa: BLE001 - never affect job processing
                # The webhook URL often embeds a secret: log its origin only.
                logger.exception("server: webhook POST to %s failed",
                                 redact_url(url))

        try:
            threading.Thread(
                target=_run, name="server-webhook", daemon=True).start()
        except Exception:  # noqa: BLE001 - the job is already settled
            # Out of OS threads: the notification is lost, but this must not
            # reach _run_one, whose error handler would settle the finished
            # job as failed and fire again, killing the single worker.
            logger.exception("server: could not start the webhook thread for %s",
                             redact_url(url))

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

    def _archive_outputs(self, job: Job) -> list[str]:
        """Copy a job's outputs out of its temporary directory; return paths.

        The history row must not point into ``<jobs_root>/<id>``, which cap
        eviction and the start-up purge delete. A copy that fails keeps the
        original path (the row is then only as durable as before).
        """
        if not job.outputs:
            return []
        dest_dir = os.path.join(self._outputs_root, job.job_id[:12])
        paths: list[str] = []
        for _fmt, src in job.outputs:
            try:
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, os.path.basename(src))
                shutil.copy2(src, dest)
                paths.append(dest)
            except OSError as e:
                logger.warning("server: could not keep output %s of job %s: %s",
                               os.path.basename(src), job.job_id, e)
                paths.append(src)
        return paths

    def _finish_history(self, db: Any, rid: int | None, job: Job,
                        duration_s: float, language: str,
                        error: str = "", *, status: str | None = None,
                        output_paths: list[str] | None = None) -> None:
        """Close the job's history row (``status`` is the one it is about to
        get: the job's own status is set only after this returns)."""
        if db is None or rid is None:
            return
        status_map = {
            STATUS_FINISHED: "finished",
            STATUS_ERROR: "error",
            STATUS_CANCELLED: "cancelled",
        }
        try:
            db.finish_transcription(
                rid, status_map.get(status or job.status, "error"),
                output_paths=(output_paths if output_paths is not None
                              else self._archive_outputs(job)),
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
    # Windows also reserves COM and LPT with a superscript 1, 2 or 3.
    | {f"{dev}{chr(code)}" for dev in ("COM", "LPT") for code in (0xB9, 0xB2, 0xB3)}
)

# Length caps for a saved upload name (see _safe_filename). The per-job dir
# is about 100 characters on Windows; outputs append their own suffixes.
_MAX_UPLOAD_STEM = 100
_MAX_UPLOAD_EXT = 16

# An absolute path inside an error text: a Windows drive path, a UNC path or
# a POSIX path with at least one directory. A directory name may hold inner
# spaces ("John Smith") but may not start or end with one, and the last
# component holds none, so the match stops before ordinary prose ("copy
# /tmp/a to /tmp/b" is two paths). A POSIX path must not follow a word
# character, ":" or "/" (URL paths).
_ABS_PATH_RE = re.compile(
    r"(?<![\w])[A-Za-z]:[\\/]+"
    r"(?:[^\\/\s'\"<>|:*?](?:[^\\/\r\n'\"<>|:*?]*[^\\/\s'\"<>|:*?])?[\\/]+)*"
    r"[^\\/\s'\"<>|:*?]*"
    r"|(?<![\w\\])\\{2,}[^\\/\s'\"<>|]+(?:\\+[^\\/\s'\"<>|]+)+"
    r"|(?<![\w.:/~\\-])/"
    r"(?:[^/\s'\"<>|](?:[^/\r\n'\"<>|]*[^/\s'\"<>|])?/)+[^/\s'\"<>|:]*"
)

# Longest error text redact_paths() looks at (the public text is cut to 500
# characters afterwards anyway); keeps the regex work small on any input.
_MAX_ERROR_SCAN = 2000


def _last_path_part(path: str) -> str:
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    last = parts[-1] if parts else ""
    return "<path>" if not last or last.endswith(":") else last


def redact_paths(text: str) -> str:
    """Shorten every absolute path in ``text`` to its last component.

    Error texts reach web clients and the webhook; the full path would show
    the host's user name and folder layout. The file name alone stays, since
    it is what the client sent or asked for. Only the first
    :data:`_MAX_ERROR_SCAN` characters are kept.
    """
    return _ABS_PATH_RE.sub(lambda m: _last_path_part(m.group(0)),
                            text[:_MAX_ERROR_SCAN])


def _last_error_line(output: Any) -> str:
    """The most telling line of a helper program's stderr (or "")."""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    if not isinstance(output, str):
        return ""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.upper().startswith("ERROR")]
    line = (errors or lines or [""])[-1]
    return line[:300]


def public_error_text(exc: BaseException) -> str:
    """A job's failure as shown to web clients: no paths, no command lines.

    A failed helper program (yt-dlp) reports its name, exit code and last
    error line instead of the full command; an ``OSError`` reports its
    reason and the file's name instead of its path. The local log and the
    history keep the full text.
    """
    if isinstance(exc, subprocess.CalledProcessError):
        cmd = exc.cmd
        program = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        name = _last_path_part(str(program or "")).replace("<path>", "")
        text = f"{name or 'a helper program'} failed (exit code {exc.returncode})"
        detail = _last_error_line(exc.stderr)
        if detail:
            text += f": {detail}"
    elif isinstance(exc, OSError) and exc.strerror:
        text = str(exc.strerror)
        if exc.filename:
            text += f": {_last_path_part(str(exc.filename))}"
    else:
        text = str(exc) or type(exc).__name__
    return redact_paths(redact_urls_in_text(text[:_MAX_ERROR_SCAN]))[:500]


_URL_IN_TEXT_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def strip_url_secrets(url: str) -> str:
    """``url`` without user info, query string and fragment.

    Signed or token links carry their secret in those parts; the job list,
    the webhook and error texts show ``scheme://host[:port]/path`` only.
    A text that is not a URL is returned unchanged.
    """
    try:
        split = urllib.parse.urlsplit(str(url or "").strip())
        host = split.hostname or ""
        port = split.port
    except ValueError:
        return "<invalid URL>"
    if split.scheme not in ("http", "https") or not host:
        return str(url or "")
    if ":" in host:
        host = f"[{host}]"
    return f"{split.scheme}://{host}{f':{port}' if port else ''}{split.path}"


def redact_urls_in_text(text: str) -> str:
    """Apply :func:`strip_url_secrets` to every http(s) URL inside ``text``."""
    from core.logging_setup import redact_urls

    return redact_urls(text)


def redact_url(url: str) -> str:
    """``scheme://host[:port]/...`` of ``url`` for a log line.

    A webhook URL often carries its secret in the path, the query or the
    user info, so only the origin is logged.
    """
    try:
        split = urllib.parse.urlsplit(str(url or "").strip())
        host = split.hostname or ""
        port = split.port
    except ValueError:
        return "<invalid URL>"
    if not split.scheme or not host:
        return "<invalid URL>"
    if ":" in host:
        host = f"[{host}]"
    return f"{split.scheme}://{host}{f':{port}' if port else ''}/..."


def _safe_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe basename.

    Strips any directory components and rejects traversal so the media
    can only ever land inside the per-job dir. Falls back to a generic
    name when the input is empty or all-suspect.

    Also renames a Windows reserved DEVICE name (CON, PRN, AUX, NUL,
    COM1-9, LPT1-9 — with or without an extension) by prefixing an
    underscore, so the upload becomes an ordinary file instead of being
    routed to the device (which would silently discard the bytes).

    The name is capped (stem :data:`_MAX_UPLOAD_STEM` characters, extension
    :data:`_MAX_UPLOAD_EXT`) so the media and its outputs fit Windows' path
    limits under the per-job dir; a 300-character name used to fail the
    upload. Trailing dots and spaces go too: Windows drops them silently, so
    the file on disk would not match the recorded name.
    """
    # A client may send its whole Windows path ("C:\\Users\\me\\clip.wav"); on
    # POSIX ``os.path.basename`` does not split at a backslash, so the
    # separators would just be stripped below and the folders glued to the name.
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    # Drop anything that isn't a tame filename character; keep dots,
    # dashes, underscores, spaces, and alphanumerics.
    cleaned = "".join(
        c for c in base
        if c.isalnum() or c in (".", "-", "_", " ")
    ).strip()
    # Spaces again after the dots, so ". a.wav" does not keep a leading
    # space (and a second pass changes nothing).
    cleaned = cleaned.lstrip(". ") or ""
    stem, ext = os.path.splitext(cleaned)
    if len(ext) > _MAX_UPLOAD_EXT or " " in ext:
        # Not a real extension ("notes.from the meeting"): keep it whole.
        stem, ext = cleaned, ""
    cleaned = (stem[:_MAX_UPLOAD_STEM] + ext).rstrip(" .")
    if not cleaned:
        return f"upload-{uuid.uuid4().hex[:8]}.bin"
    # Reserved-name guard: if the part before the FIRST dot is a reserved
    # device name, prefix an underscore so it becomes a real file. Windows
    # treats "Con.Air.1997.mp4" and "CON .txt" as the device too.
    if cleaned.split(".", 1)[0].rstrip(" ").upper() in _WIN_RESERVED_NAMES:
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


def _read_text(path: str) -> str:
    """A small text file's content ("" if unreadable as UTF-8)."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(4096)
    except UnicodeDecodeError:
        return ""


def _process_start_time(pid: int) -> float:
    """Start time (epoch seconds) of process ``pid``; 0.0 when unknown."""
    try:
        import psutil  # type: ignore[import-not-found] # noqa: PLC0415
        return float(psutil.Process(pid).create_time())
    except Exception:  # noqa: BLE001 - unknown is a valid answer
        return 0.0


def _parse_marker(text: str) -> tuple[int, str, float] | None:
    """``(pid, instance, start time)`` of a marker, or None if it is damaged.

    Strict on purpose: a marker is a file in a shared folder, so anything that
    is not exactly a small JSON object with a plausible process id means
    "unknown owner" (the safe side), never an exception.
    """
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        pid = data["pid"]
        instance = data["instance"]
        started = data.get("started") or 0
        if (isinstance(pid, bool) or not isinstance(pid, int)
                or not 0 < pid < 2 ** 31 or not isinstance(instance, str)
                or isinstance(started, bool)
                or not isinstance(started, (int, float))):
            return None
        started = float(started)
        return pid, instance, (started if math.isfinite(started) else 0.0)
    except Exception:  # noqa: BLE001 - any damage means "unknown"
        return None


def _read_keep_list(path: str) -> list[str] | None:
    """The plain file names in a keep list, or None if it cannot be trusted.

    None (missing content, cut short, not UTF-8, not a list, over the size
    limit) must be treated as "protect everything": a truncated list is not
    an empty one. Individual entries that are not plain names are ignored.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(_KEEP_LIST_MAX_BYTES + 1)
        if len(raw) > _KEEP_LIST_MAX_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
        return None
    if not isinstance(data, list):
        return None
    return [n for n in data
            if isinstance(n, str) and n and os.path.basename(n) == n
            and n not in (".", "..", _JOB_DIR_MARKER, _KEEP_FILE)]


def _marker_owner_state(text: str) -> str:
    """Who owns a job folder, from its marker: "live", "gone" or "unknown".

    "unknown" is a marker without a readable owner (an older build's empty
    file). "gone" needs proof: the owning process no longer exists (or its
    process id now belongs to a newer process), or it is this process and
    that server is stopped or was dropped. Anything undecidable (no psutil, a
    process that cannot be inspected) counts as "live": a folder is kept
    rather than guessed away.
    """
    parsed = _parse_marker(text)
    if parsed is None:
        return "unknown"
    pid, instance, started = parsed
    if pid == os.getpid():
        owner = _MANAGERS.get(instance)
        return "live" if owner is not None and not owner.stopped else "gone"
    try:
        import psutil  # type: ignore[import-not-found] # noqa: PLC0415
    except ImportError:
        return "live"
    try:
        current = float(psutil.Process(pid).create_time())
    except psutil.NoSuchProcess:
        return "gone"
    except Exception:  # noqa: BLE001 - cannot inspect: never guess
        return "live"
    if started and abs(current - started) > _START_TIME_TOLERANCE_S:
        return "gone"  # the process id was reused by a newer process
    return "live"


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
        "source": job.public_source(),
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
        logger.warning("server: refusing webhook POST to unsafe URL %s",
                       redact_url(url))
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
