"""Worker plumbing for the Live tab.

Live chunks need a loaded Whisper model. Loading one in the GUI process
is not an option here: ``app/`` deliberately never imports faster-whisper
(the model lives in ``core.worker`` subprocesses), and an in-process model
would put ~1.5-3 GB in the Tk process and freeze the UI during inference.

So a live session gets its **own** worker subprocess, spawned on Start and
shut down on Stop. It is deliberately separate from
``TranscriptionService``'s pool: sharing that pool would make a live
session and a queued file fight over the same worker, and whichever lost
would stall. The cost is a second model resident while a live session runs
alongside a transcription, which the tab says out loud rather than hiding.

The worker speaks the same newline-delimited JSON protocol as always; this
adds only the ``transcribe_live`` action (add-only, see ``core/worker.py``).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable, Optional

from core._proc import kill_process_tree, new_session_kwargs

logger = logging.getLogger(__name__)

#: How long to wait for the model to load before giving up on Start.
MODEL_READY_TIMEOUT_S = 600.0
#: How long a single chunk may take before it is abandoned. Generous: a
#: large model on a weak CPU is slow, and abandoning early would silently
#: drop audio the user spoke.
CHUNK_TIMEOUT_S = 180.0
#: Auto-detect locks onto the first confident answer. Whisper's language
#: detection is a whole extra encoder pass per chunk -- measured on a
#: 4-core i7-6700 it doubled per-chunk time for every model size -- so
#: re-detecting a language that cannot change mid-sentence is pure cost.
LANGUAGE_LOCK_MIN_PROB = 0.7


class LiveWorkerError(RuntimeError):
    """The live worker could not be started or died mid-session."""


class LiveTranscriber:
    """Owns one worker subprocess and turns chunk WAVs into text.

    ``transcribe_chunk`` is what :class:`core.live.LiveSession` calls; it
    blocks on the live consumer thread (never the Tk thread).
    """

    def __init__(
        self,
        entry_file: str,
        *,
        language: Optional[str] = None,
        log: Optional[Callable[[str], None]] = None,
        model_slug: Optional[str] = None,
    ) -> None:
        self.entry_file = entry_file
        self.language = language
        #: Catalog slug for the worker to load instead of the main model.
        self.model_slug = model_slug
        #: Set when auto-detect locked onto a language this session.
        self.locked_language = ""
        self._log = log
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._dead = threading.Event()
        self._startup_error = ""
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._token = uuid.uuid4().hex

    # ---------- lifecycle -------------------------------------------

    def start(self, *, wait_ready: bool = True) -> None:
        if self._process is not None:
            raise RuntimeError("LiveTranscriber already started")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--worker"]
        else:
            cmd = [sys.executable, "-u", "-m", "core.worker"]
        env = os.environ.copy()
        env["WHISPER_WORKER_TOKEN"] = self._token
        from core.live_model import LIVE_MODEL_ENV

        if self.model_slug:
            env[LIVE_MODEL_ENV] = self.model_slug
        else:
            env.pop(LIVE_MODEL_ENV, None)
        kwargs: dict[str, Any] = {
            "cwd": os.path.dirname(os.path.abspath(self.entry_file)),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        kwargs.update(new_session_kwargs())
        try:
            self._process = subprocess.Popen(cmd, **kwargs)
        except OSError as e:
            raise LiveWorkerError(f"Could not start the live worker: {e}") from e
        self._reader = threading.Thread(
            target=self._read_loop, name="live-worker-reader", daemon=True
        )
        self._reader.start()
        if wait_ready:
            self.wait_ready()

    def wait_ready(self, timeout: float = MODEL_READY_TIMEOUT_S) -> None:
        """Block until the worker's model is loaded. Raises on failure."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ready.wait(timeout=0.2):
                return
            if self._dead.is_set():
                raise LiveWorkerError(
                    self._startup_error
                    or "The live worker exited while loading the model."
                )
        raise LiveWorkerError(
            "Timed out waiting for the speech model to load. "
            "Pick a faster model in the Live tab's Model list."
        )

    def stop(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        # Release anyone blocked on a chunk before tearing the pipe down.
        self._dead.set()
        self._fail_all_pending("Live session stopped.")
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=5.0)
            return
        except subprocess.TimeoutExpired:
            logger.info("Live worker ignored shutdown; terminating tree")
        kill_process_tree(proc, force=False)
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc, force=True)

    def is_running(self) -> bool:
        proc = self._process
        return proc is not None and proc.poll() is None

    # ---------- the call core.live.LiveSession makes ------------------

    def transcribe_chunk(self, wav_path: str) -> dict[str, Any]:
        """Send one chunk and block until its text comes back.

        Runs on the live consumer thread. Raises on worker death or
        timeout; :class:`core.live.LiveSession` catches that, reports it,
        and keeps the session alive for the next chunk.
        """
        proc = self._process
        if proc is None or proc.poll() is not None:
            raise LiveWorkerError("The live worker is not running.")
        chunk_id = uuid.uuid4().hex
        done = threading.Event()
        slot: dict[str, Any] = {"event": done, "result": None, "error": None}
        with self._lock:
            self._pending[chunk_id] = slot
        payload = {
            "action": "transcribe_live",
            "id": chunk_id,
            "file_path": wav_path,
            "language": self.language or None,
        }
        try:
            if proc.stdin is None:
                raise ValueError("live worker process has no stdin pipe")
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as e:
            with self._lock:
                self._pending.pop(chunk_id, None)
            raise LiveWorkerError(f"Live worker write failed: {e}") from e

        if not done.wait(timeout=CHUNK_TIMEOUT_S):
            with self._lock:
                self._pending.pop(chunk_id, None)
            raise LiveWorkerError(
                "The live worker did not answer in time; this machine may be "
                "too slow for the selected model."
            )
        if slot["error"]:
            raise LiveWorkerError(str(slot["error"]))
        result = slot["result"] or {"text": "", "language": ""}
        self._maybe_lock_language(result)
        return result

    def _maybe_lock_language(self, result: dict[str, Any]) -> None:
        """After auto-detect is confident once, stop re-detecting per chunk."""
        if self.language:
            return
        lang = str(result.get("language") or "")
        prob = float(result.get("language_probability") or 0.0)
        if not lang or not str(result.get("text") or "").strip():
            return
        if prob < LANGUAGE_LOCK_MIN_PROB:
            return
        self.language = lang
        self.locked_language = lang
        if self._log:
            self._log(
                f"Live: detected language '{lang}' ({prob:.0%}); using it for "
                f"the rest of this session."
            )

    # ---------- reader ------------------------------------------------

    def _read_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    # The worker also emits plain text on stderr->stdout;
                    # surface it as a log line rather than dropping it.
                    if self._log:
                        self._log(f"[live worker] {line}")
                    continue
                self._handle(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._dead.set()
            self._fail_all_pending("The live worker exited unexpectedly.")

    def _handle(self, msg: dict[str, Any]) -> None:
        event = str(msg.get("event") or "")
        if event == "ready":
            self._ready.set()
            return
        if event == "startup_error":
            self._startup_error = str(msg.get("message") or "")
            self._dead.set()
            return
        if event == "log":
            if self._log:
                self._log(str(msg.get("message") or ""))
            return
        if event in ("live_result", "live_error"):
            chunk_id = str(msg.get("id") or "")
            with self._lock:
                slot = self._pending.pop(chunk_id, None)
            if slot is None:
                return
            if event == "live_error":
                slot["error"] = msg.get("message") or "Unknown live error"
            else:
                try:
                    prob = float(msg.get("language_probability") or 0.0)
                except (TypeError, ValueError):
                    prob = 0.0
                slot["result"] = {
                    "text": str(msg.get("text") or ""),
                    "language": str(msg.get("language") or ""),
                    "language_probability": prob,
                    "segments": msg.get("segments") or [],
                }
            slot["event"].set()

    def _fail_all_pending(self, reason: str) -> None:
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _chunk_id, slot in pending:
            slot["error"] = reason
            slot["event"].set()
