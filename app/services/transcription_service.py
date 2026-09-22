"""Transcription worker lifecycle.

Each worker is a long-lived subprocess of ``python -m core.worker`` (or
``<exe> --worker`` when frozen). The service owns spawning, restarting, and
draining stdout into the App's queue.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from queue import Empty
from typing import TYPE_CHECKING, Any

from core._proc import kill_process_tree, new_session_kwargs

if TYPE_CHECKING:
    import tkinter as tk

    from app.app import App
    from app.dialogs.model_loading import ModelLoadingDialog


logger = logging.getLogger(__name__)


def task_correlation_id(t: Any) -> str:
    """Return the worker-protocol correlation id for a transcription task.

    The id rides BOTH the ``transcribe`` command and every later
    cancel/pause/resume for that task, so the worker applies a control to
    exactly the task it belongs to — never to whichever task happens to be
    in flight (the bug where a control written ahead of its transcribe was
    silently swallowed).

    Reuses the task's own existing identity first:

    - an already-assigned ``task_id`` is returned unchanged, so the
      transcribe-command builder and the control-command builder always
      agree even though they may run on different threads;
    - otherwise the history-DB row id (``history_id``, assigned before
      dispatch) becomes ``"h<id>"``;
    - with no history row (``history_id`` is 0/absent — e.g. the history DB
      is unavailable), a per-task ``"u<uuid4>"`` fallback is generated,
      because ``"h0"`` would not be unique across tasks.

    Never raises. The cache relies on the task being a mutable object (every
    real transcription task is); if assignment somehow fails, callers that
    build both commands for one task on the same thread still agree, and the
    only effect elsewhere is an extra unmatched-control ack from the worker,
    never a misapplied control.
    """
    existing = str(getattr(t, "task_id", "") or "")
    if existing:
        return existing
    try:
        history_id = int(getattr(t, "history_id", 0) or 0)
    except (TypeError, ValueError):
        history_id = 0
    # id(t) rather than uuid.uuid4(): this fallback must be deterministic
    # per task even when the caching assignment below fails (a frozen/
    # tuple-like task object, the exact case the except anticipates) --
    # a fresh random uuid on every call meant transcribe_command and a
    # later send_control for the SAME such task silently generated two
    # DIFFERENT ids, so the worker could never match the control to its
    # transcribe. id(t) is stable for the object's entire lifetime, and
    # the object is guaranteed alive (referenced by the caller/worker
    # dict) for the whole window this id needs to stay consistent.
    cid = f"h{history_id}" if history_id > 0 else f"u{id(t):x}"
    try:
        t.task_id = cid
    except Exception:  # noqa: BLE001 - frozen/tuple-like task objects
        pass
    return cid


def transcribe_command(t: Any) -> dict[str, Any]:
    """Build the JSON command dispatched to a transcription worker.

    Pure + module-level so a test can assert that every field the worker
    needs (language / resume / clip bounds) actually crosses the process
    boundary. A field dropped here is invisible to helper-only tests and to
    the worker-side test — which is exactly how past "the value never
    reached the worker" bugs shipped.
    """
    return {
        "action": "transcribe",
        "file_path": t.file_path,
        "language": getattr(t, "language", None),
        # Resume-from-cancellation flag (App.resume_task / crash-resume).
        "resume": bool(getattr(t, "resume", False)),
        # Time-slice (Transcribe-tab range); the worker has its own task
        # object, so the bounds must cross the process boundary.
        "clip_start": getattr(t, "clip_start", None),
        "clip_end": getattr(t, "clip_end", None),
        # Output formats: the long-lived worker's config snapshot is frozen
        # at spawn time, so the user's saved docx/pdf/etc. selection must be
        # sent per task or it's silently ignored (the docx-never-written bug).
        "output_formats": getattr(t, "output_formats", None),
        # Correlation id (add-only protocol field): the worker echoes it on
        # the task's events and matches later cancel/pause/resume commands
        # against it. Optional for old workers — they ignore the extra key.
        "task_id": task_correlation_id(t),
    }


# How long the headless ensure_worker_ready path (crash-resume, watched
# folder) will wait for a freshly-spawned worker to emit its ``ready``
# event before giving up and aborting the enqueue. Generous — a cold
# faster-whisper load on CPU is ~10–15 s; on slow disks loading a
# 3 GB model can stretch past 60 s, especially on slow Mac
# environments (like virtual machines).
HEADLESS_READY_TIMEOUT_S: float = 1200.0 if sys.platform == "darwin" else 120.0


class TranscriptionService:
    def __init__(self, app: "App") -> None:
        self.app = app
        # Set by ensure_worker_ready while the modal is up; cleared
        # in poll() once a ``ready`` event is observed for the
        # awaited worker. Used to route ready events back to the
        # right dialog instance via the App's main-thread queue.
        self._pending_load_worker_id: int | None = None
        self._pending_load_dialog: "ModelLoadingDialog | None" = None
        self._pending_load_event: threading.Event | None = None
        # Single-owner guard for the poll() after()-chain. Without it every
        # start_worker() + every poll() re-arm started an independent
        # self-perpetuating 100 ms chain, so over a long session the number
        # of concurrent poll loops grew without bound (Audit P2-1).
        self._poll_scheduled: bool = False
        # Debounce for the alt-engine startup-error dialog: the worker
        # auto-restart path retries a few times in quick succession, and
        # each failed attempt emits its own startup_error — without this
        # the user got one stacked dialog per attempt.
        self._engine_error_dialog_at: float = 0.0

    def _ensure_poll_scheduled(self) -> None:
        """Schedule poll() at most once; coalesces all callers."""
        if self._poll_scheduled:
            return
        self._poll_scheduled = True
        self.app.after(100, self.poll)

    def _release_pending_load(self, worker: dict[str, Any], *, success: bool) -> None:
        """Release an ensure_worker_ready() waiter for ``worker``, if it is the
        one being awaited.

        Called from the ready / startup_error / worker_exit branches. On
        ``ready`` (success=True) it closes the modal with success; when the
        awaited worker dies first (startup_error / worker_exit) it cancels the
        modal (success stays False) so wait_window returns and
        ensure_worker_ready returns False instead of hanging forever with a
        spinning bar (Audit P1 — modal never closed on a failed load).
        """
        if (
            self._pending_load_worker_id is None
            or worker.get("id") != self._pending_load_worker_id
        ):
            return
        pending_dialog = self._pending_load_dialog
        pending_event = self._pending_load_event
        # Clear first so a later event for the same worker can't double-fire.
        self._pending_load_worker_id = None
        self._pending_load_dialog = None
        self._pending_load_event = None
        if pending_event is not None:
            pending_event.set()
        if pending_dialog is not None:
            self.app.post_to_main(
                pending_dialog.mark_success_and_close if success else pending_dialog.cancel
            )

    # Queries -----------------------------------------------------------------
    def active_workers(self) -> list[dict[str, Any]]:
        return [w for w in self.app.workers if w["process"] and w["process"].poll() is None]

    def ready_workers(self) -> list[dict[str, Any]]:
        return [w for w in self.active_workers() if w["ready"]]

    def idle_workers(self) -> list[dict[str, Any]]:
        return [w for w in self.ready_workers() if w["task"] is None]

    def update_model_state(self) -> None:
        ready_count = len(self.ready_workers())
        self.app.worker_ready = ready_count > 0
        self.app.model_ready = self.app.worker_ready
        self.app.model_loading = not self.app.worker_ready
        if ready_count:
            self.app.status_var.set(
                f"Model ready ({ready_count} worker{'s' if ready_count != 1 else ''})"
            )
        self._refresh_device_badge()

    def _refresh_device_badge(self) -> None:
        """Drive the GPU/CPU device badge + one-time CPU warning (R3).

        Reads the effective device of the ready workers (newest wins) and
        sets ``app.device_badge_var`` / ``device_badge_kind`` so the UI shows
        a green GPU badge, an amber CPU badge, or an amber downgrade badge.
        Defers the actual Tk text/colour update to the App (which owns the
        widgets) via ``app.apply_device_badge`` when present.
        """
        app = self.app
        ready = self.ready_workers()
        if not ready:
            return
        # Prefer a worker that reported real device info; among those, a
        # downgraded one is the most important to surface.
        informed = [w for w in ready if w.get("device")]
        chosen = None
        for w in informed:
            if w.get("downgraded"):
                chosen = w
                break
        if chosen is None and informed:
            chosen = informed[-1]
        if chosen is None:
            return

        device = str(chosen.get("device") or "").lower()
        compute_type = str(chosen.get("compute_type") or "")
        downgraded = bool(chosen.get("downgraded"))

        if device == "cuda":
            kind = "gpu"
            text = f"GPU - CUDA {compute_type}".strip()
        elif downgraded:
            kind = "cpu_downgraded"
            text = f"GPU unavailable, using CPU - {compute_type or 'int8'} (slower)"
        else:
            kind = "cpu"
            text = f"CPU - {compute_type or 'int8'} (slower)"

        apply = getattr(app, "apply_device_badge", None)
        if callable(apply):
            apply(text, kind, chosen)

        # One-time CPU warning: only when on CPU AND either a real downgrade
        # happened OR a GPU tier was detected-but-unusable. Never nag on a
        # genuine CPU-only box (nothing the user can act on).
        if device != "cuda":
            self._maybe_warn_cpu(downgraded, chosen)

    def _maybe_warn_cpu(self, downgraded: bool, worker: dict[str, Any]) -> None:
        """Show the one-time CPU warning the first time it's warranted.

        Gated by the ``cpu_warning_shown`` config flag so it never repeats.
        Only fires when the situation is actionable: a CUDA->CPU downgrade
        happened, or a GPU tier was detected on the host but is unusable. A
        plain CPU-only machine with no GPU at all is left alone.
        """
        app = self.app
        if app.app_config.get("cpu_warning_shown"):
            return
        gpu_detected_unusable = False
        if not downgraded:
            # Was a GPU tier detected on this host but not actually usable?
            try:
                from core import hardware as _hw
                tiers = _hw.probe_tiers()
                gpu_detected_unusable = any(
                    t.device == "cuda" for t in tiers
                ) and not _hw.cuda_load_ok()
            except Exception:  # noqa: BLE001
                gpu_detected_unusable = False
        if not (downgraded or gpu_detected_unusable):
            return
        warn = getattr(app, "warn_cpu_once", None)
        if callable(warn):
            warn(downgraded)
        app.app_config["cpu_warning_shown"] = True
        try:
            from core.config import save_config
            save_config(app.app_config)
        except Exception:  # noqa: BLE001
            logger.exception("Could not persist cpu_warning_shown flag")

    # Lifecycle ---------------------------------------------------------------
    def start_standby(self) -> None:
        """DEPRECATED: kept only for callers / tests that still poke it.

        Historically the App spawned a "standby" worker at launch so
        the first transcribe was instant. That cost ~1.5 GB of idle
        RAM and a CPU spike during startup even for users who never
        clicked Transcribe. v1.0.3 moves the load to first-transcribe
        via :meth:`ensure_worker_ready` so the trade-off is explicit.

        New code should NOT call this. It's preserved (a) so any
        third-party test still calling it doesn't blow up, and
        (b) so a future maintainer can rip it out in one obvious
        commit once the rest of the codebase is confirmed clean.
        """
        if not self.active_workers():
            self.start_worker(temporary=False)
        self.update_model_state()

    def ensure_worker_ready(
        self,
        parent_widget: "tk.Tk | tk.Toplevel",
        headless: bool = False,
    ) -> bool:
        """Make sure at least one worker is alive AND ready before dispatch.

        Replaces the v1.0.2 "preload at startup" behaviour. The
        worker is now spawned lazily on the first transcribe request.

        Parameters
        ----------
        parent_widget:
            Tk widget to parent the modal to (typically ``self.app``).
            Ignored when ``headless=True``.
        headless:
            False (default) — interactive path. If no ready worker
            exists, spawn one + show :class:`ModelLoadingDialog` and
            wait for either a ``ready`` event (return True) or the
            user clicking Cancel (kill the worker, return False).

            True — automation path (crash-resume, watched-folder).
            Same spawn behaviour but WITHOUT a modal. Wait
            synchronously up to :data:`HEADLESS_READY_TIMEOUT_S`
            for the ready event; on timeout, return False so the
            caller can abort the enqueue cleanly.

        Returns
        -------
        bool
            True when at least one worker is ready to receive a
            transcribe command. False when the user cancelled
            (interactive) or the wait timed out (headless).
        """
        # Fast path: already have a ready worker.
        if self.ready_workers():
            return True

        # Spawn a fresh worker. start_worker bumps next_worker_id
        # internally; capture the id we just created so the event
        # loop can route the ready event back to us specifically
        # (a parallel worker could go ready first if one was
        # already loading).
        before_ids = {w["id"] for w in self.app.workers}
        self.start_worker(temporary=False)
        after_ids = {w["id"] for w in self.app.workers}
        new_ids = after_ids - before_ids
        if not new_ids:
            # start_worker is a no-op when an alive worker already
            # exists for the supplied dict — but we passed
            # worker=None, so this shouldn't happen. Defend anyway.
            return bool(self.ready_workers())
        new_id = next(iter(new_ids))

        # Coordinate with poll(): when it sees the ready event for
        # `new_id`, it should set this Event AND (interactive only)
        # destroy the dialog.
        ready_event = threading.Event()
        self._pending_load_worker_id = new_id
        self._pending_load_event = ready_event

        if headless:
            # Background path — no UI. Off the Tk main thread a plain
            # blocking wait is fine (poll() keeps running on the main
            # thread and will set the event). ON the main thread it
            # deadlocks: the ONLY thing that can set the event is
            # poll(), itself scheduled via app.after(), which cannot
            # fire while this thread is blocked inside wait() — so a
            # pure wait() always burns the full HEADLESS_READY_TIMEOUT_S
            # then tears down the just-became-ready worker.
            self._pending_load_dialog = None
            try:
                if threading.current_thread() is threading.main_thread():
                    import time as _time

                    deadline = (
                        _time.monotonic() + HEADLESS_READY_TIMEOUT_S
                    )
                    ok = False
                    while True:
                        remaining = deadline - _time.monotonic()
                        if remaining <= 0:
                            break
                        if ready_event.wait(timeout=min(0.1, remaining)):
                            ok = True
                            break
                        # Pump the Tk event loop in small slices so the
                        # after()-scheduled poll() still runs and can
                        # observe the worker's ready/startup_error/exit.
                        # Tolerate fakes without update(); off-thread
                        # callers never reach this branch (Tk is
                        # main-thread-only).
                        try:
                            update = getattr(self.app, "update", None)
                            if callable(update):
                                update()
                        except Exception:  # noqa: BLE001 - pump best-effort
                            logger.debug(
                                "headless ready-pump update() failed",
                                exc_info=True,
                            )
                else:
                    ok = ready_event.wait(timeout=HEADLESS_READY_TIMEOUT_S)
            finally:
                self._pending_load_worker_id = None
                self._pending_load_event = None
            if not ok:
                logger.warning(
                    "ensure_worker_ready (headless): worker %s did not "
                    "become ready within %.0fs; aborting enqueue.",
                    new_id, HEADLESS_READY_TIMEOUT_S,
                )
                # Tear the dud worker down so we don't leak it.
                for w in list(self.app.workers):
                    if w["id"] == new_id:
                        self.retire_worker(w)
                        break
                return False
            return True

        # Interactive path — show the modal and pump the Tk loop
        # until either the ready event arrives (poll() destroys the
        # dialog) or the user clicks Cancel.
        from app.dialogs.model_loading import ModelLoadingDialog

        dialog = ModelLoadingDialog(parent_widget)
        self._pending_load_dialog = dialog
        try:
            self.app.wait_window(dialog)
        finally:
            self._pending_load_worker_id = None
            self._pending_load_dialog = None
            self._pending_load_event = None

        if dialog.success:
            return True

        # User cancelled — kill the just-spawned worker.
        logger.info(
            "ensure_worker_ready: user cancelled; tearing down worker %s",
            new_id,
        )
        for w in list(self.app.workers):
            if w["id"] == new_id:
                self.retire_worker(w)
                break
        return False

    def start_worker(self, worker: dict[str, Any] | None = None, temporary: bool = False) -> None:
        app = self.app
        if worker and worker["process"] and worker["process"].poll() is None:
            return

        if worker is None:
            import uuid as _uuid
            worker = {
                "id": app.next_worker_id,
                "process": None,
                "ready": False,
                "task": None,
                "temporary": temporary,
                # R3: effective device reported by the worker's "ready"
                # event. Defaults cover an OLD worker that omits the fields.
                "device": "",
                "compute_type": "",
                "requested_device": "",
                "downgraded": False,
                # Audit A4: per-worker UUID echoed back in every event
                # so PID recycling can't misroute an old event onto a
                # new worker.
                "token": _uuid.uuid4().hex,
                # Audit D8: monitored by poll(); updated on every event
                # the worker emits. If it lags by > LIVENESS_TIMEOUT_S
                # the worker is declared wedged and restarted.
                "last_event_at": 0.0,
                # Serialises stdin writes: a transcribe dispatch, a
                # cooperative cancel/pause/resume, and a shutdown can be
                # written from three different daemon threads — the lock
                # keeps their JSON lines from interleaving on the pipe.
                "stdin_lock": threading.Lock(),
            }
            app.next_worker_id += 1
            app.workers.append(worker)
        else:
            worker["temporary"] = temporary
            # Fresh token on every restart so stale events from the
            # dead instance can't survive.
            import uuid as _uuid
            worker["token"] = _uuid.uuid4().hex
            worker["last_event_at"] = 0.0

        app.model_loading = True
        worker["ready"] = False
        worker["task"] = None
        app.status_var.set(f"Loading model worker {worker['id']}...")

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--worker"]
        else:
            cmd = [sys.executable, "-u", "-m", "core.worker"]
        env = os.environ.copy()
        env["WHISPER_WORKER_TOKEN"] = worker["token"]
        kwargs: dict[str, Any] = {
            "cwd": os.path.dirname(os.path.abspath(app.entry_file)),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        # Isolate the worker so stop_worker can kill its whole tree later
        # (CREATE_NO_WINDOW on Windows; start_new_session on POSIX so the
        # worker leads a killable process group).
        kwargs.update(new_session_kwargs())

        process = subprocess.Popen(cmd, **kwargs)
        worker["process"] = process
        # Seed liveness timestamp at spawn so the watchdog grace
        # period covers initial model load.
        import time as _time
        worker["last_event_at"] = _time.time()
        # Capture the token THIS process was spawned with. restart_worker()
        # rewrites worker["token"] in place while this reader thread may
        # still be draining the old process's pipe; reading
        # worker.get("token") at exit time would stamp the dead process's
        # synthetic worker_exit with the NEW token, routing it onto the
        # freshly-restarted worker (clearing its live process handle /
        # its task). The token is a spawn-time constant, so snapshot it
        # like the process object itself.
        spawn_token = worker["token"]

        def reader() -> None:
            for line in process.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                event: dict[str, Any]
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"event": "log", "message": line}
                event["_pid"] = process.pid
                event["_worker_id"] = worker["id"]
                # Token is set by the worker if WHISPER_WORKER_TOKEN
                # was honoured (audit A4). Parent-side routing uses
                # it when present, falls back to PID otherwise.
                app.worker_events.put(event)
            return_code = process.wait()
            app.worker_events.put(
                {"event": "worker_exit", "return_code": return_code,
                 "_pid": process.pid, "_worker_id": worker["id"],
                 "_token": spawn_token}
            )

        from core._threads import safe_thread
        safe_thread(reader, name=f"worker-{worker['id']}-reader")
        self._ensure_poll_scheduled()

    def stop_worker(self, worker: dict[str, Any]) -> None:
        """Audit D5: structured three-step shutdown.

        1. Send {"action": "shutdown"} on stdin (in a daemon thread so
           a full pipe never blocks the Tk main thread — audit A1).
        2. Wait up to 5 s for the worker to exit on its own.
        3. terminate() — graceful Windows-level signal.
        4. If still alive after another 2 s, kill() it.

        Each step is logged so a wedged worker is debuggable from
        the log alone.
        """
        process = worker.get("process")
        if not (process and process.poll() is None):
            return

        worker_id = worker.get("id", "?")
        shutdown_msg = json.dumps({"action": "shutdown"}) + "\n"

        def _async_shutdown() -> None:
            try:
                self._locked_stdin_write(worker, shutdown_msg)
            except Exception:
                logger.debug(
                    "stop_worker: stdin shutdown write failed for worker %s",
                    worker_id, exc_info=True,
                )
        threading.Thread(
            target=_async_shutdown, name=f"shutdown-w{worker_id}", daemon=True,
        ).start()

        try:
            process.wait(timeout=5.0)
            return
        except subprocess.TimeoutExpired:
            logger.info("stop_worker: worker %s ignored shutdown; terminating",
                        worker_id)
        # Tree-terminate, not just process.terminate(): the worker may be
        # blocked inside a grandchild (ffmpeg/ffprobe/demucs) that
        # TerminateProcess would orphan on Windows. _proc walks the whole
        # tree (taskkill /T on Windows, killpg on POSIX).
        kill_process_tree(process, force=False)
        try:
            process.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            logger.warning(
                "stop_worker: worker %s ignored terminate(); killing", worker_id,
            )
        kill_process_tree(process, force=True)

    def stop_all(self) -> None:
        for w in self.active_workers():
            self.stop_worker(w)

    def restart_worker(self, worker: dict[str, Any]) -> None:
        live = worker.get("task")
        if live is not None:
            # Never silently drop a live task: every in-file call site
            # happens to call this only when the slot is already empty,
            # but a future caller must not be able to orphan a task with
            # zero cleanup by accident. Preserve an already-terminal
            # status (finish_task keeps it under keep_status=True).
            try:
                if getattr(live, "status", None) not in (
                    "finished", "error", "cancelled",
                ):
                    live.status = "error"
                self.finish_task(worker, keep_status=True)
            except Exception:  # noqa: BLE001 - teardown must not raise
                logger.exception(
                    "Failed to finish task on worker %s during restart",
                    worker.get("id", "?"),
                )
            # finish_task() retires (and un-registers) a temporary worker
            # when no waiting task is left — restarting such a removed
            # worker would orphan it (see the poll() watchdog guard), so
            # do not schedule a restart for it.
            if worker not in self.app.workers:
                return
        self.stop_worker(worker)
        worker["process"] = None
        worker["ready"] = False
        worker["task"] = None
        self.app.model_loading = True
        self.app.after(300, lambda: self.start_worker(worker, temporary=worker.get("temporary", False)))

    def retire_worker(self, worker: dict[str, Any]) -> None:
        live = worker.get("task")
        if live is not None:
            # Same guarantee as restart_worker: dropping worker["task"]
            # directly would leave a terminal status unset and a history
            # row open. finish_task (keep_status=True) closes both while
            # preserving an already-terminal status.
            try:
                if getattr(live, "status", None) not in (
                    "finished", "error", "cancelled",
                ):
                    live.status = "error"
                self.finish_task(worker, keep_status=True)
            except Exception:  # noqa: BLE001 - teardown must not raise
                logger.exception(
                    "Failed to finish task on worker %s during retire",
                    worker.get("id", "?"),
                )
            # finish_task() may already have retired (removed) a
            # temporary worker with nothing waiting; its retire already
            # stopped the process and refreshed state, so there is
            # nothing left to do.
            if worker not in self.app.workers:
                return
        self.stop_worker(worker)
        worker["process"] = None
        worker["ready"] = False
        worker["task"] = None
        if worker in self.app.workers:
            self.app.workers.remove(worker)
        self.update_model_state()

    # Routing -----------------------------------------------------------------
    def worker_for_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Match event → worker.

        Audit A4 — prefer token match when both sides carry one
        (worker spawned with WHISPER_WORKER_TOKEN). Fall back to
        PID + worker_id for the worker_exit synthetic event the
        reader fires when the subprocess dies (which can no longer
        echo its own token at that point if it hard-crashed).
        """
        token = event.get("_token")
        if token:
            for worker in self.app.workers:
                if worker.get("token") == token:
                    return worker
            # A token was present but matched no current worker: this
            # event belongs to an instance that has since been restarted
            # (start_worker assigns a fresh token, "so stale events from
            # the dead instance can't survive") or removed. Falling
            # through to the PID+worker-id match below would defeat
            # exactly the protection the token exists for -- Windows can
            # recycle a PID quickly enough that a dead worker's lingering
            # queued event matches the id+PID of its own freshly-
            # restarted replacement, crediting the live task with a dead
            # task's progress/done.
            return None
        # Legacy / synthetic path — only for events with no token at all
        # (an old worker binary spawned before WHISPER_WORKER_TOKEN, or a
        # parent that hasn't set the env var).
        for worker in self.app.workers:
            process = worker.get("process")
            if (
                worker["id"] == event.get("_worker_id")
                and process
                and process.pid == event.get("_pid")
            ):
                return worker
        return None

    def _is_stale_task_event(
        self, worker: dict[str, Any], event: dict[str, Any]
    ) -> bool:
        """True when ``event`` targets a DIFFERENT task than the one currently
        in ``worker["task"]``.

        ``worker_for_event`` only identifies the correct *worker*; when a
        worker slot is reused, a stale/duplicate event for an OLDER task (or
        a synthetic dispatch-failure that lands late) can otherwise be
        misapplied to the NEWER task now sitting in that slot. Only events
        that actually carry a non-empty ``task_id`` can be checked — id-less
        events (old workers, generic worker errors) keep the historical
        apply-to-current-task behaviour. Never raises.
        """
        try:
            event_id = event.get("task_id")
            if not event_id:
                return False
            task = worker.get("task")
            if task is None:
                return False
            expected = task_correlation_id(task)
            return str(event_id) != str(expected)
        except Exception:  # noqa: BLE001 - never break poll on a guard
            return False

    def _fail_tasks_and_clear_workers_on_startup_error(self) -> None:
        """Finish every in-flight task before discarding all worker dicts.

        ``startup_error`` handling tree-kills ALL workers via ``stop_all``
        (which genuinely targets every active worker, not just the failed
        one) and then clears ``app.workers``. Without this, healthy workers
        mid-transcribe on a DIFFERENT task have their ``worker["task"]``
        silently discarded: never finished, history never closed, status
        stuck at "running" forever with no owner. Mirrors the
        ``worker_exit`` pattern (status -> "error", ``finish_task`` with
        ``keep_status=True``) but preserves an already-terminal status
        instead of overwriting it. Per-task guards so one bad task cannot
        block the rest of the teardown.
        """
        for other in list(self.app.workers):
            otask = other.get("task")
            if otask is None:
                continue
            try:
                if getattr(otask, "status", None) not in (
                    "finished", "error", "cancelled",
                ):
                    otask.status = "error"
                self.finish_task(other, keep_status=True)
            except Exception:  # noqa: BLE001 - teardown must not wedge poll
                logger.exception(
                    "Failed to finish orphaned task on worker %s during "
                    "startup_error teardown",
                    other.get("id", "?"),
                )
        self.stop_all()
        self.app.workers = []

    # Audit D8: if a worker stops emitting events (including the
    # 5-second heartbeat) for this long, declare it wedged + restart.
    # 30 s easily covers a normal model load (~10 s on CPU) and any
    # one-segment Whisper transcribe burst, but catches a deadlocked
    # worker before the user has to kill the app.
    #
    # 1200 s (was 120 s) is defence-in-depth on top of the progress-
    # callback wiring through diarisation (see core/transcriber.py
    # _run_post_pipeline). Long files (3 h+) can momentarily have a
    # sherpa-onnx tick rate below one event per 30 s, even with the
    # progress callback connected; 1200 s keeps the watchdog useful
    # for genuinely wedged workers while no longer killing healthy
    # long-running diarisation passes mid-job, especially on slow
    # Mac environments (like virtual machines).
    LIVENESS_TIMEOUT_S: float = 1200.0 if sys.platform == "darwin" else 120.0

    def poll(self) -> None:
        app = self.app
        # This invocation consumes the scheduled slot; the re-arm at the end
        # (or a start_worker) will book exactly one more (Audit P2-1).
        self._poll_scheduled = False
        import time as _time
        now = _time.time()
        while True:
            try:
                event = app.worker_events.get_nowait()
            except Empty:
                break

            event_type = event.get("event")
            worker = self.worker_for_event(event)
            if not worker:
                # An unroutable event (worker restarted/removed since it
                # was queued, or a stale token) is silently dropped below
                # this point -- including "done", which can carry a
                # genuinely completed transcription's outputs/word_count.
                # A log line is the difference between recoverable-and-
                # visible and invisible data loss (contrast
                # control_unmatched, which was already logged).
                logger.warning(
                    "Dropping unroutable worker event %r (no matching "
                    "worker for worker_id=%r pid=%r token=%r)",
                    event_type, event.get("_worker_id"), event.get("_pid"),
                    bool(event.get("_token")),
                )
                continue

            # Audit D8: any event counts as liveness.
            worker["last_event_at"] = now
            if event_type == "heartbeat":
                # Pure liveness — already recorded above.
                continue

            try:
                if event_type == "log":
                    app.model_status(event.get("message", ""))
                elif event_type == "ready":
                    worker["ready"] = True
                    # R3: the worker's ready event additively carries the device
                    # it actually loaded onto. .get() defaults keep an OLD worker
                    # (no device fields) working — it just leaves these blank.
                    worker["device"] = str(event.get("device", "") or "")
                    worker["compute_type"] = str(event.get("compute_type", "") or "")
                    worker["requested_device"] = str(
                        event.get("requested_device", "") or ""
                    )
                    worker["downgraded"] = bool(event.get("downgraded", False))
                    self.update_model_state()
                    # If this is the worker an ensure_worker_ready() call is
                    # awaiting, unblock it (headless Event) and close its modal.
                    self._release_pending_load(worker, success=True)
                elif event_type == "startup_error":
                    worker["ready"] = False
                    app.log(event.get("message", "Existing model failed to load."))
                    # Release any ensure_worker_ready() waiter FIRST so its
                    # loading modal closes (with success=False) before we maybe
                    # open the download modal — otherwise the two modals stack
                    # and, because we clear app.workers below, poll() stops and
                    # the loading modal's ready-routing would be dead forever.
                    self._release_pending_load(worker, success=False)
                    # A startup failure on an ALTERNATIVE engine (whisper.cpp /
                    # cloud / NVIDIA) cannot be fixed by downloading the Whisper
                    # model — that flow both hid the real error behind a generic
                    # "model load was cancelled" line AND force-opened a
                    # mandatory ~3 GB download modal for a model the selected
                    # engine never uses. Surface the engine's own error instead.
                    from core.backends import availability as _eng
                    engine = _eng.normalise_engine(
                        app.app_config.get("transcribe_backend")
                    )
                    if engine != "faster_whisper":
                        self._fail_tasks_and_clear_workers_on_startup_error()
                        detail = str(
                            event.get("message") or "engine failed to start"
                        )
                        label = _eng.VALUE_TO_LABEL.get(engine, engine)
                        if now - self._engine_error_dialog_at > 10.0:
                            self._engine_error_dialog_at = now
                            try:
                                from app.widgets.error_dialog import show_error
                                show_error(
                                    app,
                                    "Transcription engine failed to start",
                                    f"The selected engine ({label}) could not "
                                    "start. Check its model/key settings in "
                                    "Advanced > Backend, or switch back to the "
                                    "default Faster-Whisper engine.",
                                    detail=detail,
                                )
                            except Exception:  # noqa: BLE001
                                pass
                    elif not app.model_setup_running:
                        app.log("Existing model failed to load. Starting required download.")
                        self._fail_tasks_and_clear_workers_on_startup_error()
                        # Defer so the loading modal is fully torn down (its
                        # cancel() runs on the next main-thread drain) before the
                        # download modal opens — no stacked modals.
                        app.after(0, lambda: app.ensure_model_with_modal(mandatory=True))
                elif event_type == "started":
                    pass
                elif event_type == "progress":
                    if worker["task"]:
                        if self._is_stale_task_event(worker, event):
                            logger.warning(
                                "Dropping stale progress event for task %r "
                                "on worker %s (current task %r)",
                                event.get("task_id"), worker.get("id"),
                                task_correlation_id(worker["task"]),
                            )
                        else:
                            p = event.get("percent", 0)
                            worker["task"].progress = p
                            app.update_overall_progress()
                            # Mirror progress onto the Download row when this task
                            # was auto-spawned from a download (it shows
                            # "transcribing" there); the download poll won't refresh
                            # on its own once the download itself has finished.
                            if getattr(worker["task"], "source_download", None) is not None:
                                app.refresh_download_queue()
                elif event_type == "language_detected":
                    if worker["task"]:
                        if self._is_stale_task_event(worker, event):
                            logger.warning(
                                "Dropping stale language_detected event for task %r "
                                "on worker %s (current task %r)",
                                event.get("task_id"), worker.get("id"),
                                task_correlation_id(worker["task"]),
                            )
                        else:
                            worker["task"].detected_language = event.get("language", "")
                            worker["task"].language_probability = event.get("probability", 0.0)
                            app.refresh()
                elif event_type == "done":
                    # The worker reports the files it actually wrote; store
                    # them so finish_task's history record + the Last-result
                    # card reflect reality (incl. docx/pdf and de-duped names)
                    # instead of re-deriving from config.
                    if worker["task"] is not None:
                        if self._is_stale_task_event(worker, event):
                            logger.warning(
                                "Dropping stale done event for task %r "
                                "on worker %s (current task %r)",
                                event.get("task_id"), worker.get("id"),
                                task_correlation_id(worker["task"]),
                            )
                        else:
                            outs = event.get("outputs")
                            if isinstance(outs, list):
                                worker["task"].output_paths = [str(p) for p in outs]
                            # Worker-computed transcript stats (absent from older
                            # workers) — the authoritative word count even when no
                            # machine-readable output format was selected.
                            try:
                                worker["task"].word_count = int(
                                    event.get("word_count") or 0
                                )
                                worker["task"].audio_duration = float(
                                    event.get("audio_duration") or 0.0
                                )
                            except (TypeError, ValueError):
                                pass
                            self.finish_task(worker)
                    else:
                        self.finish_task(worker)
                elif event_type == "error":
                    if worker["task"]:
                        if self._is_stale_task_event(worker, event):
                            logger.warning(
                                "Dropping stale error event for task %r "
                                "on worker %s (current task %r)",
                                event.get("task_id"), worker.get("id"),
                                task_correlation_id(worker["task"]),
                            )
                        else:
                            worker["task"].status = "error"
                            app.log(event.get("message", "Worker error"))
                            self.finish_task(worker, keep_status=True)
                    else:
                        app.log(event.get("message", "Worker error"))
                elif event_type == "control_applied":
                    # An id-bearing control was honoured. Delayed means the worker
                    # parked it briefly because it arrived before its transcribe
                    # was registered — the exact race this increment fixes; a
                    # debug line is all the parent needs.
                    if event.get("delayed"):
                        logger.debug(
                            "worker %s applied %s for task %s after parking it",
                            worker.get("id"),
                            event.get("action"),
                            event.get("task_id"),
                        )
                elif event_type == "control_unmatched":
                    # The worker never saw a transcribe with this task's id, so
                    # the control could not be honoured. Do not swallow that: log
                    # it for the user. UI state is not rewritten here — a failed
                    # dispatch is already reported by the dispatch-error path /
                    # worker_exit / the liveness watchdog.
                    reason = event.get("reason", "unknown")
                    logger.warning(
                        "worker %s could not apply %s for task %s (%s)",
                        worker.get("id"),
                        event.get("action"),
                        event.get("task_id"),
                        reason,
                    )
                    app.log(
                        f"Worker did not apply {event.get('action', 'control')} "
                        f"for task {event.get('task_id', '?')} ({reason}); no "
                        "matching in-flight task was found."
                    )
                elif event_type == "worker_exit":
                    worker["ready"] = False
                    worker["process"] = None
                    if worker["task"] is not None:
                        # Any live task pins its worker slot until it is
                        # finished: the old ("running", "paused") allowlist
                        # left e.g. a "cancelled"-but-unacknowledged task
                        # pinned forever with its history row open. Preserve
                        # an already-terminal status; anything else died
                        # with its worker, so it is an error.
                        if getattr(worker["task"], "status", None) not in (
                            "finished", "error", "cancelled",
                        ):
                            worker["task"].status = "error"
                            app.log(f"Transcription worker exited with code {event.get('return_code')}")
                        self.finish_task(worker, keep_status=True)
                    # A worker that dies before going ready would otherwise hang
                    # an ensure_worker_ready() modal forever — release it.
                    self._release_pending_load(worker, success=False)
                    self.update_model_state()
            except Exception:  # noqa: BLE001
                # One malformed/unexpected event must never wedge the whole
                # transcription pump: an uncaught exception here would abort
                # this while loop early, skipping both the liveness watchdog
                # below and the _ensure_poll_scheduled() re-arm -- with
                # _poll_scheduled already cleared at the top of poll(), no
                # future 100 ms tick would ever fire again, and every running
                # task's progress/done/error events would sit unprocessed
                # until something else happened to call start_worker().
                logger.exception(
                    "Transcription event handling failed for %r", event_type
                )

        # Audit D8: liveness watchdog. After draining the queue,
        # check every active worker. If one has been silent past the
        # threshold (heartbeat missed several times), restart it.
        for w in list(self.active_workers()):
            last = float(w.get("last_event_at") or 0.0)
            if last and now - last > self.LIVENESS_TIMEOUT_S:
                if w["task"]:
                    w["task"].status = "error"
                    self.finish_task(w, keep_status=True)
                # finish_task() retires (and un-registers) a temporary
                # worker when no waiting task is left. restart_worker()
                # assumes the dict is still tracked by the app: restarting
                # a removed worker spawns a replacement no worker_events
                # event can ever route to, so it loads the model into RAM
                # as an invisible orphan until app exit. Only restart a
                # worker that is still on the books.
                if w not in app.workers:
                    continue
                logger.warning(
                    "Worker %s missed heartbeats for %.1fs; restarting",
                    w.get("id", "?"), now - last,
                )
                app.log(
                    f"Worker {w.get('id', '?')} appears wedged; restarting."
                )
                self.restart_worker(w)

        if self.active_workers():
            self._ensure_poll_scheduled()

    def dispatch_waiting(self) -> None:
        """Spawn temporary workers as needed and hand them waiting tasks."""
        app = self.app
        # Don't spawn new workers once shutdown has begun (Audit P2-5).
        if getattr(app, "_closing", False):
            return
        if not app.queue:
            return
        waiting = [t for t in app.queue if t.status == "waiting"]
        if not waiting:
            return
        active_count = len(self.active_workers())
        idle_count = len(self.idle_workers())
        needed = min(len(waiting), app.parallel_workers) - idle_count
        for _ in range(max(0, needed)):
            if active_count >= app.parallel_workers:
                break
            self.start_worker(temporary=True)
            active_count += 1
        idle = self.idle_workers()
        if not idle:
            return
        import time as _time
        for worker, t in zip(idle, waiting):
            # Audit A3: insert the history row BEFORE marking the task
            # running and BEFORE telling the worker to start. If the
            # insert raises (locked DB, disk full), we abort the
            # dispatch — the task stays in `waiting` and the user can
            # retry; the alternative is a "running" task with no DB
            # record, which mark_interrupted() can't recover on
            # next launch.
            history = getattr(app, "history", None)
            if history is not None:
                try:
                    t.history_id = history.insert_transcription(
                        file_path=t.file_path,
                        model=str(app.app_config.get("model", {}).get("name", "")),
                        language=getattr(t, "language", "") or "",
                    )
                    # A retry gets a FRESH history_id but task_correlation_id
                    # caches task_id on first use — without this reset the
                    # second attempt would keep "h<old_id>", so a control
                    # parked from attempt 1 could misapply to attempt 2 and
                    # attempt 2's own worker-echoed events could never join
                    # back to its fresh history row. Clearing here (and ONLY
                    # here, at a fresh DISPATCH — never mid-attempt) forces
                    # the next task_correlation_id(t) to recompute from the
                    # fresh history_id; transcribe_command below re-caches
                    # it, so same-attempt command/control agreement is kept.
                    try:
                        t.task_id = ""
                    except Exception:  # noqa: BLE001 - frozen/tuple-like tasks
                        pass
                except Exception as e:
                    logger.exception(
                        "history insert failed for %s; deferring dispatch",
                        t.file_path,
                    )
                    app.log(f"Could not record task in history: {e}")
                    # Leave status='waiting' so the next dispatch
                    # tick picks it up again (transient DB locks
                    # are common on Windows with antivirus).
                    continue

            worker["task"] = t
            t.status = "running"
            t.progress = 0
            t.start_time = _time.time()
            # Clear any prior end_time (re-run path) so the freshly-
            # restarted task counter doesn't immediately freeze.
            t.end_time = None
            app.update_overall_progress()

            # Audit A1: stdin.write can block the Tk main thread when
            # the OS pipe buffer fills (~64 KB on Windows). Move the
            # write to a daemon thread — same pattern stop_worker
            # uses for its shutdown command. If the write fails OR
            # blocks > 5 s, we restart the worker.
            # Stamp the CURRENT output-format selection onto the task so the
            # long-lived worker writes what the user has now (its import-time
            # config is stale). None-safe default mirrors core.config.
            t.output_formats = list(
                self.app.app_config.get("output_formats") or ["srt", "json"]
            )
            command = transcribe_command(t)
            self._dispatch_command_async(worker, t, command)

    @staticmethod
    def _locked_stdin_write(worker: dict[str, Any], msg: str) -> None:
        """Write one line to a worker's stdin under its per-worker lock.

        Raises RuntimeError if the worker has no stdin (dead process).
        The lock serialises the three possible concurrent writers
        (dispatch / control / shutdown) so JSON lines never interleave.
        """
        process = worker.get("process")
        stdin = process.stdin if process else None
        if stdin is None:
            raise RuntimeError("worker stdin is None")
        lock = worker.get("stdin_lock")
        if lock is None:
            stdin.write(msg)
            stdin.flush()
            return
        with lock:
            stdin.write(msg)
            stdin.flush()

    def _dispatch_command_async(
        self,
        worker: dict[str, Any],
        task: Any,
        command: dict[str, Any],
    ) -> None:
        """Write ``command`` to the worker's stdin from a daemon thread.

        On failure (write raises OR times out via process death),
        mark the task as error + restart the worker. We can't
        observe a blocked write directly, but a long-blocked
        worker is the same observable thing as a dead one — it
        stops emitting events, so the next progress tick reveals
        the wedge.
        """
        app = self.app
        msg = json.dumps(command) + "\n"
        worker_id = worker.get("id", "?")

        def _worker_dispatch() -> None:
            try:
                self._locked_stdin_write(worker, msg)
            except Exception as e:
                logger.exception(
                    "Failed to dispatch task to worker %s: %s",
                    worker_id, e,
                )
                # Marshal the error back onto the worker_events
                # queue so the Tk poll loop handles cleanup on the
                # main thread (status flip + restart).
                try:
                    app.worker_events.put({
                        "event": "error",
                        "message": f"Failed to dispatch task: {e}",
                        "task_id": task_correlation_id(task),
                        "_pid": worker["process"].pid if worker.get("process") else 0,
                        "_worker_id": worker_id,
                    })
                except Exception:
                    logger.exception(
                        "Could not enqueue dispatch failure event"
                    )

        threading.Thread(
            target=_worker_dispatch,
            name=f"dispatch-w{worker_id}",
            daemon=True,
        ).start()

    def _send_command_async(
        self, worker: dict[str, Any], command: dict[str, Any]
    ) -> None:
        """Fire-and-forget a control command (cancel/pause/resume) to a
        worker's stdin from a daemon thread.

        Unlike _dispatch_command_async this does NOT mark the task as
        errored on a failed write: the caller has already set the UI
        state, and a dead worker is handled by the liveness watchdog /
        worker_exit event. We only log.
        """
        msg = json.dumps(command) + "\n"
        worker_id = worker.get("id", "?")

        def _send() -> None:
            try:
                self._locked_stdin_write(worker, msg)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "control %r to worker %s failed: %s",
                    command.get("action"), worker_id, e,
                )

        threading.Thread(
            target=_send,
            name=f"control-w{worker_id}",
            daemon=True,
        ).start()

    def send_control(self, task: Any, action: str) -> bool:
        """Send cancel/pause/resume to the worker running ``task``.

        Returns True if a worker was found and the command dispatched.
        The worker's reader thread applies it to the task whose correlation
        id matches (a control can never be applied to a different task),
        parking it until that task registers if the control overtook the
        transcribe on the pipe; a control with no matching task is reported
        back as ``control_unmatched`` instead of silently vanishing.
        The transcriber honours the flag at the next segment boundary
        (cancel also flushes a resumable checkpoint). Returns False when the
        task isn't on a worker yet (still ``waiting``) — nothing to signal.
        """
        for worker in self.app.workers:
            if worker.get("task") is task:
                # Same id the transcribe command carried (task_correlation_id
                # caches it on the task), so the worker pairs the two even if
                # this line wins the stdin-lock race.
                self._send_command_async(
                    worker,
                    {"action": action, "task_id": task_correlation_id(task)},
                )
                return True
        return False

    def finish_task(self, worker: dict[str, Any], keep_status: bool = False) -> None:
        task = worker["task"]
        if not task:
            return
        import time as _time
        # Freeze the Elapsed-column counter ASAP — irrespective of
        # which terminal status (finished / cancelled / error) the
        # task ended in. Before this, app.fmt_time kept incrementing
        # via time.time() - start_time forever.
        if getattr(task, "end_time", None) is None:
            task.end_time = _time.time()
        newly_finished = (
            not keep_status and not task.cancelled
        )
        # The status this run must be recorded/reported under. task.status
        # itself isn't flipped to "finished" until after the history write
        # below (see the ordering comment there) -- history must record
        # the REAL terminal status, not whatever task.status still held
        # from mid-run (e.g. "running") at the moment this call happens.
        terminal_status = "finished" if newly_finished else task.status
        # Phase 3a — finalise the history row BEFORE reporting success to
        # the UI. This used to run AFTER show_last_result below: the user
        # saw the "done, here are the files" card, and only THEN did the
        # history write happen -- so a write failure (a locked history.db
        # on Windows + antivirus is this module's own documented common
        # case) landed after success was already reported, silently
        # leaving the durable record in its pre-dispatch state forever.
        # The repo's own standing rule ("a completed transcription must
        # reach durable storage before the UI/worker reports success")
        # requires this ordering, not just the write eventually happening.
        app = self.app
        history = getattr(app, "history", None)
        # Best-effort word count + audio duration from the produced JSON
        # sidecar (computed once; reused by history + the usage-stats POST).
        word_count, audio_duration = self._derive_transcript_stats(task)
        if history is not None and getattr(task, "history_id", 0):
            import time as _time
            try:
                duration = (_time.time() - task.start_time) if task.start_time else 0.0
                # Prefer the worker-reported written paths (accurate for
                # docx/pdf + de-duped names); fall back to deriving from
                # config for older workers / interrupted runs.
                written = getattr(task, "output_paths", None)
                if written:
                    paths = list(written)
                else:
                    # os.path.splitext (not rsplit('.',1)) so a source like
                    # 'C:\my.media\clip' (dot in a folder, extensionless
                    # file) doesn't derive base='C:\my' and record bogus
                    # 'C:\my.srt' paths. Matches the base used everywhere
                    # the actual outputs are written (transcriber.py).
                    base = os.path.splitext(task.file_path)[0]
                    paths = [
                        f"{base}.{ext}"
                        for ext in (app.app_config.get("output_formats") or ["srt", "json"])
                    ]
                persisted = history.finish_transcription(
                    task.history_id,
                    status=terminal_status,
                    output_paths=paths,
                    duration_seconds=float(duration),
                    language=getattr(task, "detected_language", "") or "",
                    word_count=word_count,
                )
                if not persisted:
                    # Surfaced, not swallowed: the transcript FILES are
                    # still safely on disk (the worker wrote them before
                    # ever sending "done"), but the supplementary History/
                    # Stats DB record for this run did not persist -- the
                    # user should know, even though this alone doesn't
                    # withhold the success card below.
                    app.log(
                        f"History record for '{task.file_path}' was not "
                        "saved (no matching row); the transcript files "
                        "themselves are still on disk."
                    )
            except Exception as e:  # noqa: BLE001
                app.log(
                    f"History record update failed: {e}; the transcript "
                    "files themselves are still on disk."
                )
        if newly_finished:
            task.status = "finished"
            task.progress = 100
            # Surface the success on the Transcribe tab so the user
            # sees a real "this is done, here are the files" card
            # rather than just a Treeview row flipping to "finished".
            try:
                self.app.show_last_result(task)
            except Exception:  # noqa: BLE001
                pass
        # P4-4 — opt-in usage stats POST (best-effort, daemon thread, swallows
        # all errors). post_stats_async re-checks telemetry_opt_in + stats_url.
        # Only for a genuine successful completion: an error/cancelled task
        # never has a real word_count/audio_duration, so posting here used to
        # send a "0 words, 0:00" row indistinguishable from a real empty
        # transcription — e.g. every job that failed because the configured
        # backend had no valid key. history.finish_transcription() above
        # still records the real status locally regardless.
        if newly_finished:
            self._post_usage_stats(task, word_count, audio_duration)
        # If this task was auto-spawned from a download, the Download row
        # mirrored "transcribing" + live progress while it ran. It's
        # terminal now (finished / error / cancelled) — restore that row to
        # "finished" (the download itself succeeded) and unlink.
        dl = getattr(task, "source_download", None)
        # Only restore a row still showing "transcribing" — never clobber a
        # download the user cancelled/removed while it was transcribing.
        if dl is not None and getattr(dl, "status", None) == "transcribing":
            dl.status = "finished"
            dl.transcription_task = None
            dl.progress = 100
            task.source_download = None
            try:
                app.refresh_download_queue()
            except Exception:  # noqa: BLE001
                pass
        worker["task"] = None
        app.update_overall_progress()
        if worker.get("temporary") and not any(t.status == "waiting" for t in app.queue):
            self.retire_worker(worker)

    def _derive_transcript_stats(self, task: Any) -> tuple[int, float]:
        """Best-effort ``(word_count, audio_duration)`` from a produced
        output file. Prefers a JSON sidecar (cheapest to parse), but a user
        whose ``output_formats`` doesn't include "json" would otherwise
        always get ``word_count=0`` even though e.g. the .srt/.docx they DID
        write is full of real words — so this falls back to re-parsing
        whichever other produced transcript ``core.convert`` can read back
        into segments. Returns ``(0, 0.0)`` when nothing usable is found —
        never raises (stats are best-effort; the imports sit inside the
        try so even an ImportError degrades to (0, 0.0) instead of
        breaking the task-done handler)."""
        try:
            from core import convert as _convert
            from core import stats as _stats
            # Prefer the worker-computed numbers from the "done" event —
            # they exist regardless of which output formats were selected.
            # 0 words falls through to the file-based path so an older
            # worker (which never sends the fields) still gets counted.
            wc = int(getattr(task, "word_count", 0) or 0)
            if wc > 0:
                return wc, float(getattr(task, "audio_duration", 0.0) or 0.0)
            paths = list(getattr(task, "output_paths", None) or [])
            json_path = next(
                (p for p in paths if str(p).lower().endswith(".json")), ""
            )
            if not json_path and getattr(task, "file_path", ""):
                cand = os.path.splitext(task.file_path)[0] + ".json"
                if os.path.isfile(cand):
                    json_path = cand
            if json_path and os.path.isfile(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    segments = json.load(f)
                if isinstance(segments, list):
                    return (
                        _stats.count_words_in_segments(segments),
                        _stats.audio_duration_from_segments(segments),
                    )
            # No JSON sidecar (or it didn't parse as a list) — try any other
            # produced format core.convert knows how to read back. On-disk
            # extensions for PARSE_FORMATS, per core.convert's own mapping
            # (elan -> .eaf, inqscribe -> .inqscr; the rest match their name).
            parseable_exts = {"json", "srt", "vtt", "tsv", "otr", "eaf", "inqscr"}
            for p in paths:
                ext = os.path.splitext(str(p))[1].lower().lstrip(".")
                if ext not in parseable_exts or not os.path.isfile(p):
                    continue
                try:
                    segments = _convert.parse_to_segments(p)
                except _convert.ConvertError:
                    continue
                return (
                    _stats.count_words_in_segments(segments),
                    _stats.audio_duration_from_segments(segments),
                )
            return 0, 0.0
        except Exception as e:  # noqa: BLE001
            logger.debug("could not derive transcript stats: %s", e)
            return 0, 0.0

    def _post_usage_stats(
        self, task: Any, word_count: int, audio_duration: float
    ) -> None:
        """Fire the opt-in usage-stats POST (best-effort, off-thread).

        Gated inside ``core.stats.post_stats_async`` on
        ``telemetry_opt_in`` + a non-empty ``stats_url`` — a no-op otherwise.
        """
        app = self.app
        try:
            from core import stats as _stats
            import time as _time
            ai_time = (
                (_time.time() - task.start_time) if task.start_time else 0.0
            )
            # Report the model that actually transcribed. The config's
            # Whisper model name is only the truth for faster_whisper —
            # an alternative engine (whisper.cpp / cloud / NVIDIA) never
            # touches it, so those rows used to claim e.g.
            # "faster-whisper-large-v3" for an NVIDIA Parakeet run.
            from core.backends import availability as _eng
            backend = _eng.normalise_engine(
                app.app_config.get("transcribe_backend")
            )
            if backend == "faster_whisper":
                model = str(
                    (app.app_config.get("model") or {}).get("name")
                    or app.app_config.get("whisper_model")
                    or ""
                )
            elif backend == "nvidia_asr":
                from core.backends.nvidia_asr import DEFAULT_MODEL_ID
                model_id = str(
                    app.app_config.get("nvidia_asr_model_id") or ""
                ).strip() or DEFAULT_MODEL_ID
                model = f"{backend}:{model_id}"
            else:
                model = backend
            payload = _stats.build_stats_payload(
                file_name=getattr(task, "file_path", "") or "",
                model=model,
                language=getattr(task, "detected_language", "") or "",
                audio_duration=audio_duration,
                transcription_time=ai_time,
                status=getattr(task, "status", "") or "",
                word_count=word_count,
            )
            _stats.post_stats_async(app.app_config, payload)
        except Exception as e:  # noqa: BLE001
            logger.debug("usage stats wiring skipped: %s", e)
