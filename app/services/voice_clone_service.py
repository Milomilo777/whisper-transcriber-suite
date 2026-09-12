"""Worker plumbing for the Clone Your Voice / Text to Voice tab.

Mirrors ``app.services.live_service.LiveTranscriber``'s shape (one
worker subprocess per session, a blocking call per request answered via
a threading.Event slot, graceful-then-forceful shutdown) but talks to
``core.voice_clone_worker`` -- its own, independent worker script and
protocol. See that module's docstring for why this isn't folded into
the shared transcription worker the way the Live tab's chunk action was.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from typing import Any, Callable, Optional

from core._proc import kill_process_tree, new_session_kwargs

logger = logging.getLogger(__name__)

#: A single generation call measured ~50-57x real-time on CPU in
#: pre-implementation testing; a few sentences can genuinely take the
#: better part of an hour. Generous on purpose -- the UI shows its own
#: estimate and lets the user cancel (which kills the process) rather
#: than this timeout firing first on a merely-slow machine.
GENERATE_TIMEOUT_S = 3600.0


class VoiceCloneWorkerError(RuntimeError):
    """The voice-clone worker could not be started, or died mid-session."""


class VoiceCloneWorker:
    """Owns one voice-clone worker subprocess for the tab's session."""

    def __init__(
        self,
        entry_file: str,
        *,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.entry_file = entry_file
        self._log = log
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._dead = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}

    # ---------- lifecycle -------------------------------------------

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("VoiceCloneWorker already started")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--voice-clone-worker"]
        else:
            cmd = [sys.executable, "-u", "-m", "core.voice_clone_worker"]
        kwargs: dict[str, Any] = {
            "cwd": os.path.dirname(os.path.abspath(self.entry_file)),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        kwargs.update(new_session_kwargs())
        try:
            self._process = subprocess.Popen(cmd, **kwargs)
        except OSError as e:
            raise VoiceCloneWorkerError(f"Could not start the voice-clone worker: {e}") from e
        self._reader = threading.Thread(
            target=self._read_loop, name="voiceclone-worker-reader", daemon=True
        )
        self._reader.start()

    def stop(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        self._dead.set()
        self._fail_all_pending("Voice-clone session stopped.")
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
            logger.info("Voice-clone worker ignored shutdown; terminating tree")
        # A generation in flight has no cooperative cancel (see
        # core.voice_clone_worker's docstring) -- killing the tree is
        # how the user gives up on a run that's taking too long.
        kill_process_tree(proc, force=False)
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc, force=True)

    def is_running(self) -> bool:
        proc = self._process
        return proc is not None and proc.poll() is None

    # ---------- the call the tab makes --------------------------------

    def generate(
        self,
        text: str,
        reference_paths: list[str],
        output_path: str,
        *,
        consent_accepted: bool,
        device: str = "cpu",
        on_model_loading: Optional[Callable[[], None]] = None,
    ) -> dict[str, Any]:
        """Send one generation request and block until it answers.

        Runs on the tab's own worker thread (never the Tk thread — a
        single call can take the better part of an hour on CPU, see
        GENERATE_TIMEOUT_S). Raises on worker death or timeout.
        """
        proc = self._process
        if proc is None or proc.poll() is not None or self._dead.is_set():
            raise VoiceCloneWorkerError("The voice-clone worker is not running.")
        req_id = uuid.uuid4().hex
        done = threading.Event()
        slot: dict[str, Any] = {
            "event": done, "result": None, "error": None,
            "on_model_loading": on_model_loading,
        }
        with self._lock:
            self._pending[req_id] = slot
        payload = {
            "action": "generate",
            "id": req_id,
            "text": text,
            "reference_paths": reference_paths,
            "output_path": output_path,
            "consent_accepted": consent_accepted,
            "device": device,
        }
        try:
            if proc.stdin is None:
                raise ValueError("voice-clone worker process has no stdin pipe")
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as e:
            with self._lock:
                self._pending.pop(req_id, None)
            raise VoiceCloneWorkerError(f"Voice-clone worker write failed: {e}") from e

        if not done.wait(timeout=GENERATE_TIMEOUT_S):
            with self._lock:
                self._pending.pop(req_id, None)
            raise VoiceCloneWorkerError(
                "The voice-clone worker did not answer in time."
            )
        if slot["error"]:
            raise VoiceCloneWorkerError(str(slot["error"]))
        return slot["result"] or {}

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
                    if self._log:
                        self._log(f"[voice-clone worker] {line}")
                    continue
                self._handle(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._dead.set()
            self._fail_all_pending("The voice-clone worker exited unexpectedly.")

    def _handle(self, msg: dict[str, Any]) -> None:
        event = str(msg.get("event") or "")
        if event in ("ready", "heartbeat"):
            return
        if event == "log":
            if self._log:
                self._log(str(msg.get("message") or ""))
            return
        if event == "model_loading":
            # Broadcast to every pending request -- there is at most one
            # in flight in practice (the tab serialises generate calls),
            # but this stays correct even if that ever changes.
            with self._lock:
                slots = list(self._pending.values())
            for slot in slots:
                cb = slot.get("on_model_loading")
                if cb:
                    try:
                        cb()
                    except Exception:  # noqa: BLE001
                        logger.exception("on_model_loading callback failed")
            return
        if event in ("model_ready", "started"):
            return
        if event in ("done", "error"):
            req_id = str(msg.get("id") or "")
            with self._lock:
                slot = self._pending.pop(req_id, None)
            if slot is None:
                return
            if event == "error":
                slot["error"] = msg.get("message") or "Unknown voice-clone error"
            else:
                slot["result"] = {
                    "output_path": str(msg.get("output_path") or ""),
                    "audio_seconds": float(msg.get("audio_seconds") or 0.0),
                    "elapsed_seconds": float(msg.get("elapsed_seconds") or 0.0),
                }
            slot["event"].set()
            return
        if event == "model_error":
            # A model_error usually accompanies an "error" event for the
            # same request; nothing extra to do beyond the log line above.
            return

    def _fail_all_pending(self, reason: str) -> None:
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _req_id, slot in pending:
            slot["error"] = reason
            slot["event"].set()
