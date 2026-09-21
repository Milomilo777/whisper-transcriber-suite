"""Long-lived transcription worker.

Reads JSON commands from stdin, emits JSON events on stdout. The
protocol is intentionally frozen — adding fields is safe, renaming
or removing them breaks the parent UI.

Events emitted:
  - ``ready``  ([device, compute_type, requested_device, downgraded])
                                       : model loaded; accepting commands.
    The device fields are additive (R3) — they report which device the model
    actually loaded onto and whether a requested CUDA load self-healed onto
    CPU. Older parents that don't read them keep working unchanged.
  - ``startup_error``                  : model failed to load; exiting
  - ``log``       (message)             : free-text log line
  - ``progress``  (percent)             : current task progress 0–100
  - ``language_detected`` (language, probability, file_path)
  - ``started``   (file_path[, task_id])  : task accepted
  - ``done``      (file_path[, task_id])  : task finished writing outputs
  - ``error``     (message[, file_path][, task_id]): task or worker error
  - ``control_applied`` (action, task_id[, delayed])
                                          : a cancel/pause/resume was applied
  - ``control_unmatched`` (action, task_id, reason)
                                          : a control could not be applied

Commands accepted on stdin (one JSON object per line):
  - ``{"action": "shutdown"}``
  - ``{"action": "transcribe", "file_path": "...", "language": "...",
     "task_id": "<optional>"}``
  - ``{"action": "cancel", "task_id": "<optional>"}``
  - ``{"action": "pause",  "task_id": "<optional>"}``
  - ``{"action": "resume", "task_id": "<optional>"}``

cancel/pause/resume are *control* commands: a dedicated reader thread
applies them to the running task immediately, because the main thread is
blocked inside ``transcribe()`` and cannot read stdin itself. The
transcriber polls ``task.cancelled`` / ``task.paused`` between segments.

``task_id`` (add-only protocol field): an opaque correlation token chosen
by the parent, stable for one dispatched task on one worker and unique
among that worker's outstanding tasks (two different transcribes must
never reuse an id). When present on a control it must be present (and
identical) on the ``transcribe`` command of the task it targets. The
worker then applies the control ONLY to the task carrying that exact id:

  - id matches the in-flight task           -> applied immediately;
  - id matches a transcribe not yet
    registered (control overtook it on the
    pipe, or it is still queued)            -> parked (bounded) and applied
                                               when that transcribe registers;
  - no task with that id ever appears       -> after a bounded wait the
                                               control is ACKNOWLEDGED as
                                               ``control_unmatched`` instead
                                               of being silently swallowed.

An id-less control keeps the historical semantics byte for byte: applied
to whatever task is in flight, silent no-op when there is none. That keeps
old parents and ``tools/e2e_cancel_pause.py`` working unchanged, and no
new field is required of anyone.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Iterator, cast

from .config import load_config
from .logging_setup import setup_logging, worker_log_filename
from .task import TranscriptionTask
from .transcriber import (
    get_effective_device,
    get_model_error,
    load_existing_model,
    resume_transcription,
    transcribe,
)

logger = logging.getLogger(__name__)


# Audit A4: a per-worker session token assigned by the parent at
# spawn time via the WHISPER_WORKER_TOKEN env var. Attached to
# every emitted event so the parent can route correctly even if
# the OS recycles a PID between worker spawns. Empty when the
# env var is missing (older parents) — the parent falls back to
# matching by PID, preserving backwards compatibility.
_SESSION_TOKEN: str = os.environ.get("WHISPER_WORKER_TOKEN", "") or ""


# The task currently being transcribed, shared between the main thread
# (which runs transcribe()) and the stdin-reader thread (which applies
# cancel/pause/resume). Guarded by a lock; bool-flag writes on the task
# itself are atomic under the GIL, which is all the transcriber's
# between-segment poll needs.
_state_lock = threading.Lock()
_current_task: "TranscriptionTask | None" = None


# emit() is called from the main thread (transcribe loop), the stdin-reader
# thread (control acks / errors) and the heartbeat thread, all writing to the
# same stdout. print()'s write+flush is two operations on the underlying
# buffer; concurrent calls can interleave and corrupt a JSON line, which
# breaks the FROZEN one-JSON-object-per-line worker protocol. Serialise every
# emit under this module-level lock so each event is written + flushed
# atomically with respect to the others.
_emit_lock = threading.Lock()


def _set_current_task(task: "TranscriptionTask | None") -> None:
    global _current_task
    with _state_lock:
        _current_task = task


# How long an id-bearing control may wait for its transcribe command to be
# registered before the worker declares it unmatched. The parent's dispatch
# and control writes are two daemon threads racing for one stdin lock, so a
# control can validly arrive *milliseconds* before its transcribe; a few
# seconds absorbs even a temporarily blocked stdin writer, while a control
# that really has no task is acknowledged promptly instead of leaking.
CONTROL_PARK_TIMEOUT_S: float = 10.0

# Bound on the park table (see _parked_controls). Controls are user actions
# (one click each), so a legitimate burst is tiny; the cap exists so a
# misbehaving client cannot grow worker memory without bound.
_MAX_PARKED_CONTROLS = 64


class _ParkedControl:
    """An id-bearing control waiting for the transcribe it belongs to."""

    __slots__ = ("action", "task_id", "deadline", "timer")

    def __init__(
        self,
        action: str,
        task_id: str,
        deadline: float,
        timer: threading.Timer,
    ) -> None:
        self.action = action
        self.task_id = task_id
        self.deadline = deadline
        self.timer = timer


# Parked controls, keyed by task_id, guarded by _state_lock. _parked_order is
# the same entries in arrival order so a capacity overflow can evict the
# OLDEST one (a later pause/resume supersedes an earlier one; dropping the
# newest would leave the user's latest action unhonoured).
_parked_controls: dict[str, list[_ParkedControl]] = {}
_parked_order: deque[_ParkedControl] = deque()


def _normalise_task_id(value: Any) -> str:
    """Coerce an incoming task_id to the canonical string form.

    The parent sends a JSON string, but the protocol only promises "opaque
    token": an int/other scalar from some other client must compare equal on
    both the transcribe and the control side, so both sides go through here.
    """
    if value is None:
        return ""
    return str(value).strip()


def _apply_control_flag(task: "TranscriptionTask", action: str) -> bool:
    """Set the flag for *action* on *task*; return False for unknown actions."""
    if action == "cancel":
        task.cancelled = True
    elif action == "pause":
        task.paused = True
    elif action == "resume":
        task.paused = False
    else:
        return False
    return True


def _apply_control(action: str, task: "TranscriptionTask | None" = None) -> bool:
    """Apply an ID-LESS control command to the in-flight task, if any.

    Legacy semantics (unchanged): no-op when no task is running (a stray
    cancel/pause between tasks is harmless — each transcribe builds a fresh
    task with the flags clear). Returns True when a flag was actually set.
    """
    with _state_lock:
        if task is None:
            task = _current_task
        if task is None:
            return False
        return _apply_control_flag(task, action)


def _park_control_locked(action: str, task_id: str) -> list[_ParkedControl]:
    """Park one control. Caller holds ``_state_lock``.

    Returns the entries evicted to stay under the capacity bound; the caller
    acknowledges those AFTER releasing the lock (never emit while holding
    ``_state_lock``).
    """
    evicted: list[_ParkedControl] = []
    while _parked_order and len(_parked_order) >= _MAX_PARKED_CONTROLS:
        oldest = _parked_order.popleft()
        entries = _parked_controls.get(oldest.task_id)
        if entries:
            try:
                entries.remove(oldest)
            except ValueError:  # pragma: no cover - defensive
                pass
            if not entries:
                _parked_controls.pop(oldest.task_id, None)
        oldest.timer.cancel()
        evicted.append(oldest)

    timeout = CONTROL_PARK_TIMEOUT_S
    timer = threading.Timer(timeout, _expire_parked_controls)
    timer.daemon = True
    entry = _ParkedControl(action, task_id, time.monotonic() + timeout, timer)
    _parked_controls.setdefault(task_id, []).append(entry)
    _parked_order.append(entry)
    timer.start()
    return evicted


def _route_control(action: str, task_id: Any = "") -> None:
    """Dispatch one control command, id-aware.

    ID-less  -> legacy ``_apply_control`` (silent no-op when no task).
    With id  -> apply now when the in-flight task carries that exact id;
               otherwise park it for the matching transcribe (or ack it as
               unmatched once the park timeout expires).

    The match-or-park decision and the parked-list insertion happen under the
    same lock that ``_register_task`` uses to publish a task, so a control can
    never fall between "just parked" and "task already registered".
    """
    tid = _normalise_task_id(task_id)
    if not tid:
        _apply_control(action)
        return

    evicted: list[_ParkedControl] = []
    immediate = False
    with _state_lock:
        task = _current_task
        if task is not None and _normalise_task_id(getattr(task, "task_id", "")) == tid:
            immediate = _apply_control_flag(task, action)
        else:
            evicted = _park_control_locked(action, tid)

    for entry in evicted:
        emit(
            "control_unmatched",
            action=entry.action,
            task_id=entry.task_id,
            reason="capacity",
        )
    if immediate:
        emit("control_applied", action=action, task_id=tid, delayed=False)


def _register_task(task: "TranscriptionTask") -> list[_ParkedControl]:
    """Publish *task* as the in-flight task and take over its parked controls.

    The parked controls (if any) have their flags applied HERE, under the same
    lock that publishes the task, so they take effect before ``transcribe()``
    runs and can never be reordered against a control that arrives just after
    registration. The caller emits the ``control_applied`` acks after the lock
    is released.
    """
    global _current_task
    tid = _normalise_task_id(getattr(task, "task_id", ""))
    with _state_lock:
        _current_task = task
        if not tid:
            return []
        parked = _parked_controls.pop(tid, [])
        for entry in parked:
            try:
                _parked_order.remove(entry)
            except ValueError:  # pragma: no cover - defensive
                pass
            entry.timer.cancel()
            _apply_control_flag(task, entry.action)
        return parked


def _expire_parked_controls() -> None:
    """Acknowledge parked controls whose matching transcribe never arrived.

    Also the callback for every park timer: expired entries are removed and
    each emits one ``control_unmatched``. Entries already applied at
    registration (or evicted) are simply absent and produce nothing.
    """
    now = time.monotonic()
    expired: list[_ParkedControl] = []
    with _state_lock:
        for tid in list(_parked_controls.keys()):
            entries = _parked_controls[tid]
            keep: list[_ParkedControl] = []
            for entry in entries:
                if entry.deadline <= now:
                    expired.append(entry)
                    try:
                        _parked_order.remove(entry)
                    except ValueError:  # pragma: no cover - defensive
                        pass
                else:
                    keep.append(entry)
            if keep:
                _parked_controls[tid] = keep
            else:
                _parked_controls.pop(tid, None)
    for entry in expired:
        emit(
            "control_unmatched",
            action=entry.action,
            task_id=entry.task_id,
            reason="timeout",
        )


def _clear_parked_controls() -> None:
    """Drop every parked control (worker shutdown / stdin EOF)."""
    with _state_lock:
        for entries in _parked_controls.values():
            for entry in entries:
                entry.timer.cancel()
        _parked_controls.clear()
        _parked_order.clear()


def emit(event: str, **payload: Any) -> None:
    """Write a single JSON event line to stdout.

    json.dumps may raise on non-serialisable values (e.g. a passed-
    through exception object). Fall back to a stringified payload so
    the parent always sees *something* and the worker never silently
    swallows an event.
    """
    payload["event"] = event
    if _SESSION_TOKEN:
        payload["_token"] = _SESSION_TOKEN
    try:
        line = json.dumps(payload)
    except (TypeError, ValueError) as e:
        # Audit B4: log the actual encoding error before falling
        # back. Without this the parent sees ``_emit_warning`` but
        # the real TypeError ("Object of type Exception is not JSON
        # serializable", etc.) is lost — a bug magnet for future
        # maintainers.
        logger.exception(
            "Worker event payload not JSON-serialisable; coercing via repr. "
            "event=%s payload_types=%r",
            event,
            {k: type(v).__name__ for k, v in payload.items()},
        )
        safe = {k: repr(v) for k, v in payload.items()}
        safe["event"] = event
        safe["_emit_warning"] = (
            f"payload was not JSON-serialisable ({type(e).__name__}: {e}); "
            "coerced via repr()"
        )
        line = json.dumps(safe)
    # Atomic write+flush against other threads' emits (see _emit_lock).
    with _emit_lock:
        print(line, flush=True)


# Chunk size for the bounded stdin reader. Small enough that an overlong,
# newline-less line is never accumulated past the cap by more than one chunk.
_READ_CHUNK_CHARS = 65536


def _record_length(text: str) -> int:
    """Payload length of a record, excluding its framing newline.

    The terminating newline is framing, not payload: a record of exactly
    *max_chars* data plus its newline is AT the cap, not past it. Without
    this, a command whose JSON was exactly the 1 MB cap (plus the newline
    that always terminates it) was wrongly rejected as oversized.
    """
    return len(text) - 1 if text.endswith("\n") else len(text)


def read_capped_lines(stream: Any, max_chars: int) -> Iterator[tuple[str, bool]]:
    """Yield ``(line, oversize)`` per newline-delimited record from *stream*.

    Unlike iterating the stream directly (which buffers a whole line into
    memory *before* any length check — defeating the OOM guard), this reads
    in bounded chunks and enforces *max_chars* WHILE reading. Once a record
    exceeds the cap, accumulation stops immediately; the rest of that record
    (up to the next newline) is drained and discarded in bounded chunks, then
    the truncated text is yielded ONCE with ``oversize=True`` so the caller
    can reject it without ever holding the full oversized payload in memory.
    The drained tail is never yielded separately — one oversized record must
    produce exactly one rejection, not a second empty one the caller would
    report again as its own dropped command.

    *line* keeps the trailing newline when present (matching file-iteration
    semantics) so existing ``.strip()`` handling is unchanged.

    The chunked path needs a ``read(n)`` method (the real ``sys.stdin``
    TextIOWrapper has one). Streams that expose only iteration (some test
    stubs / pipes) fall back to line iteration, where the cap is still
    enforced — best effort — after each line is read. This keeps the
    production OOM guard active without breaking the frozen control-channel
    behaviour that other callers rely on.
    """
    # Prefer ``readline`` for real pipes. ``TextIOWrapper.read(n)`` on a
    # Windows pipe can wait for far more than a short JSON command, which
    # left the worker's stdin reader parked forever. ``readline(size)`` still
    # bounds each read, but it returns promptly on the newline the protocol
    # already uses.
    readline_attr = getattr(stream, "readline", None)
    if callable(readline_attr):
        readline = cast("Callable[[int], str]", readline_attr)
        dropping = False  # inside the tail of an oversized record we discard
        while True:
            raw = readline(max_chars + 1)
            if not raw:
                # EOF. An oversized record was already reported when its
                # prefix crossed the cap, so nothing more is yielded here.
                return
            if dropping:
                # Draining an already-reported oversized record's tail until
                # its newline. This tail is not a record of its own, so it is
                # never yielded: reporting it again produced a duplicate
                # "exceeds max length" error for a single bad command.
                if "\n" in raw:
                    dropping = False
                continue
            if _record_length(raw) > max_chars:
                yield raw, True
                dropping = not raw.endswith("\n")
                continue
            yield raw, False
        return

    read_attr = getattr(stream, "read", None)
    if not callable(read_attr):
        for raw in stream:
            yield raw, _record_length(raw) > max_chars
        return
    read = cast("Callable[[int], str]", read_attr)
    buf = ""
    dropping = False  # inside the tail of an oversized record we discard
    while True:
        chunk = read(_READ_CHUNK_CHARS)
        if not chunk:  # EOF
            if buf:
                # Unterminated trailing record still within the cap. An
                # oversized one was already reported, so nothing to add.
                yield buf, False
            return
        while chunk:
            nl = chunk.find("\n")
            if nl == -1:
                segment, rest = chunk, ""
            else:
                segment, rest = chunk[: nl + 1], chunk[nl + 1 :]
            if dropping:
                # Drain the remainder of an already-reported oversized record
                # without yielding it again (see the readline path).
                if nl != -1:
                    dropping = False
                chunk = rest
                continue
            buf += segment
            if _record_length(buf) > max_chars:
                # Cap exceeded. If this segment completed the record (had a
                # newline) the whole record is over the limit; flag it and
                # move on. Otherwise stop buffering and drain the unterminated
                # tail in bounded chunks so memory never grows past the cap.
                yield buf, True
                buf = ""
                dropping = nl == -1
            elif nl != -1:
                yield buf, False
                buf = ""
            chunk = rest


def main() -> int:
    # fetch_online=False: the worker only needs log_level here; skip the
    # network round-trip so worker spawn is never blocked on the online
    # config fetch (the parent App passes the effective per-task config).
    # Use a per-process log file (worker-<pid>.log) rather than sharing
    # the GUI's app.log: a RotatingFileHandler shared across processes
    # cannot roll over on Windows (renaming a file another process holds
    # open raises PermissionError), silently defeating the 5 MB x 3 cap.
    try:
        setup_logging(
            load_config(fetch_online=False).get("log_level", "INFO"),
            filename=worker_log_filename(),
        )
    except Exception:  # noqa: BLE001
        # Logging is best-effort: the protocol lives on stdout, and an
        # unwritable / AV-locked log directory must not kill the worker
        # before it has emitted a single event (the parent can only show
        # "model load was cancelled" for a bare worker_exit). Logging
        # falls back to its last-resort stderr handler, which the parent
        # already tolerates as a non-JSON log line.
        pass
    # Make on-demand-installed optional packages (stable-ts → torch)
    # importable; alignment runs in THIS worker process.
    try:
        from .optional_deps import activate as _activate_extras
        _activate_extras()
    except Exception:  # noqa: BLE001
        pass
    logger.info("Worker starting (pid=%d)", os.getpid())

    def log_cb(message: str) -> None:
        emit("log", message=message)

    def progress_cb(percent: float) -> None:
        emit("progress", percent=percent)

    # Audit D8: heartbeat thread. Without this the parent has no way
    # to distinguish "worker is mid-CPU-bound-transcribe" from
    # "worker silently wedged". We emit a tiny heartbeat every 5 s
    # so the parent can declare the worker dead if heartbeats stop.
    # Daemon thread — dies with the process; no shutdown signal
    # needed. Started BEFORE the model load: an alternative backend's
    # first load can silently download GBs (HF weights, ggml model,
    # even a pip install of transformers+torch) for far longer than
    # the parent's 120 s liveness timeout — the watchdog used to kill
    # the healthy worker mid-download and restart it in a loop.
    HEARTBEAT_INTERVAL_SECONDS = 5.0

    # Stoppable via .wait() rather than a bare time.sleep(): production
    # never needs this (the daemon thread just dies with the process), but
    # tests call main() many times in one interpreter, and an un-stoppable
    # thread would keep ticking for the rest of the whole pytest run,
    # printing stray "heartbeat" lines into whichever later test happens to
    # have capsys capturing stdout at the 5 s mark — a real, previously
    # unfixed source of CI flakiness (see docs/SESSION_HANDOFF_NEXT.md).
    heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                emit("heartbeat", ts=time.time())
            except Exception:
                logger.exception("heartbeat emit failed")

    threading.Thread(target=_heartbeat, name="worker-heartbeat",
                     daemon=True).start()

    try:
        model_loaded = load_existing_model(log_cb)
    except Exception as e:  # noqa: BLE001
        # A raise here (e.g. a bad model-path type slipping past the
        # config coercion, or a status_cb/emit failure) must still be
        # reported through the frozen protocol. The parent can only
        # release its loading modal / surface the real reason on
        # startup_error; a bare crash arrives as worker_exit and reads
        # as "model load was cancelled" with no explanation.
        logger.exception("load_existing_model raised; emitting startup_error")
        emit("startup_error", message=f"Model load failed ({type(e).__name__}): {e}")
        heartbeat_stop.set()
        return 1
    if not model_loaded:
        detail = get_model_error() or "Existing model failed to load in worker"
        emit("startup_error", message=detail)
        heartbeat_stop.set()
        return 1

    # R3: tell the parent which device the model actually loaded onto so the
    # UI can show a GPU/CPU badge and warn on a silent CUDA->CPU downgrade.
    # Strictly ADDITIVE to the frozen protocol — old parents ignore the extra
    # fields; new parents read them with .get() defaults. Guarded so a probe
    # failure never blocks the (essential) bare ``ready`` signal.
    try:
        eff = get_effective_device()
        emit(
            "ready",
            device=eff.device,
            compute_type=eff.compute_type,
            requested_device=eff.requested_device,
            downgraded=eff.downgraded,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not read effective device; emitting bare ready")
        emit("ready")

    # Reasonable max line size — a single JSON command should be
    # under a few KB. Anything past 1 MB is either a runaway parent
    # or an attempt to OOM the worker; reject loudly instead of
    # buffering up megabytes of garbage.
    MAX_COMMAND_BYTES = 1 << 20  # 1 MB

    # Transcribe/shutdown commands are handed to the main thread via this
    # queue; cancel/pause/resume are applied inline by the reader thread.
    cmd_queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def _stdin_reader() -> None:
        """Read stdin concurrently with transcription.

        The main thread blocks inside transcribe(), so it cannot read
        its own control commands. This thread does: it applies
        cancel/pause/resume to the in-flight task immediately and queues
        everything else (transcribe/shutdown) for the main loop. A None
        sentinel on stdin-close tells the main loop to exit.
        """
        try:
            for raw, oversize in read_capped_lines(sys.stdin, MAX_COMMAND_BYTES):
                if oversize:
                    # The cap was enforced WHILE reading: ``raw`` here is the
                    # truncated prefix (<= cap + one chunk), not the full
                    # oversized payload, so the OOM guard holds.
                    emit(
                        "error",
                        message=(
                            f"command exceeds max length (> "
                            f"{MAX_COMMAND_BYTES} bytes); dropped"
                        ),
                    )
                    continue
                line = raw.strip()
                if not line:
                    continue
                try:
                    command = json.loads(line)
                except json.JSONDecodeError as e:
                    emit("error", message=f"Invalid worker command: {e}")
                    continue
                # A line can be valid JSON yet not an object (e.g. 5,
                # "foo", [1,2], null). The protocol is "one JSON object
                # per line"; calling .get on a non-dict raises
                # AttributeError, which would escape this loop, hit the
                # finally (cmd_queue.put(None)) and tear the whole worker
                # down on a single malformed line. Ignore it loudly.
                if not isinstance(command, dict):
                    emit("error", message="worker command must be a JSON object")
                    continue
                if command.get("action") in ("cancel", "pause", "resume"):
                    # task_id is add-only/optional: an id-bearing control is
                    # matched (or parked) by id; an id-less one keeps the
                    # legacy apply-to-current semantics.
                    _route_control(
                        command["action"], command.get("task_id", "")
                    )
                else:
                    cmd_queue.put(command)
        finally:
            cmd_queue.put(None)

    threading.Thread(target=_stdin_reader, name="worker-stdin",
                     daemon=True).start()

    while True:
        command = cmd_queue.get()
        if command is None:  # stdin closed — parent gone
            heartbeat_stop.set()
            _clear_parked_controls()
            return 0

        action = command.get("action")
        if action == "shutdown":
            heartbeat_stop.set()
            _clear_parked_controls()
            return 0

        # Live tab: transcribe one short chunk and hand the text straight
        # back, writing no files and taking no checkpoint. A new ACTION
        # rather than a flag on "transcribe" — the protocol is add-only,
        # and an older parent that never sends this is unaffected.
        if action == "transcribe_live":
            chunk_path = command.get("file_path")
            chunk_id = command.get("id")
            if not chunk_path:
                emit("live_error", id=chunk_id, message="Missing chunk file")
                continue
            try:
                from .transcriber import transcribe_chunk_to_text

                result = transcribe_chunk_to_text(
                    chunk_path, language=command.get("language") or None
                )
                emit(
                    "live_result",
                    id=chunk_id,
                    file_path=chunk_path,
                    text=result["text"],
                    segments=result["segments"],
                    language=result["language"],
                    language_probability=result["language_probability"],
                )
            except Exception as e:  # noqa: BLE001
                # One bad chunk must not end the session; the parent logs
                # it and keeps feeding the next one.
                emit("live_error", id=chunk_id, file_path=chunk_path,
                     message=str(e))
            continue

        if action != "transcribe":
            emit("error", message=f"Unknown worker command: {action}")
            continue

        file_path = command.get("file_path")
        if not file_path:
            emit("error", message="Missing input file")
            continue
        task_id = _normalise_task_id(command.get("task_id"))

        try:
            task = TranscriptionTask(file_path)
            task.task_id = task_id
            forced_lang = command.get("language")
            if forced_lang:
                task.language = forced_lang
            # Resume-from-cancellation: when the parent flagged the
            # task as a resume, attempt the partial-checkpoint path
            # first. If it returns False (stale checkpoint, changed
            # model/config, ffmpeg slice failed, etc.) we fall back to
            # a full re-transcribe so the user always gets an output
            # rather than an error.
            task.resume = bool(command.get("resume", False))
            # Time-slice (Transcribe-tab time range): transcribe only this
            # span via clip_timestamps. None = whole file.
            task.clip_start = command.get("clip_start")
            task.clip_end = command.get("clip_end")
            # Per-task output formats (worker's config snapshot is stale).
            task.output_formats = command.get("output_formats")
            # A clipped run must NOT resume: the checkpoint is keyed to the
            # whole file with no clip marker, so resuming would transcribe
            # past clip_end. Clips are short — re-transcribe the slice fresh.
            if task.clip_start or task.clip_end:
                task.resume = False
            # Publish the task so the reader thread can cancel/pause it, and
            # take over any id-matched controls that were parked while this
            # transcribe was still in flight on the pipe (the race where the
            # control line overtakes the transcribe line) or still queued.
            # _register_task applies their flags under the same lock that
            # publishes the task, before transcribe() below can run.
            parked = _register_task(task)
            for entry in parked:
                emit(
                    "control_applied",
                    action=entry.action,
                    task_id=entry.task_id,
                    delayed=True,
                )
            emit("started", file_path=file_path, task_id=task_id)

            def language_cb(lang: str, prob: float) -> None:
                emit("language_detected", language=lang, probability=prob, file_path=file_path)

            try:
                did_resume = False
                if task.resume:
                    did_resume = resume_transcription(
                        task, progress_cb, log_cb, language_cb=language_cb
                    )
                if not did_resume:
                    transcribe(task, progress_cb, log_cb, language_cb=language_cb)
            finally:
                # Clear the in-flight slot BEFORE the done event goes out.
                # The parent only learns this task ended when it sees
                # "done", so it cannot dispatch the next task until after
                # this point — a cancel/pause/resume meant for that next
                # task can no longer arrive while this finished task is
                # still the current one and get swallowed by it.
                _set_current_task(None)
            emit(
                "done",
                file_path=file_path,
                task_id=task_id,
                outputs=getattr(task, "output_paths", None) or [],
                # Added fields (protocol is add-only): transcript stats
                # computed from the in-memory segments, so the parent
                # never needs a machine-readable output file to know
                # the word count (txt/docx/pdf-only runs recorded 0).
                word_count=int(getattr(task, "word_count", 0) or 0),
                audio_duration=float(
                    getattr(task, "audio_duration", 0.0) or 0.0
                ),
            )
        except Exception as e:  # noqa: BLE001
            emit("error", message=str(e), file_path=file_path, task_id=task_id)


if __name__ == "__main__":
    raise SystemExit(main())
