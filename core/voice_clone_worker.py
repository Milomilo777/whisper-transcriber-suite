"""Clone Your Voice / Text to Voice -- dedicated worker subprocess.

A deliberately SEPARATE script from ``core.worker`` (the transcription
worker), not a new action bolted onto it, even though the Live tab set
that add-an-action precedent for ``transcribe_live``. Two reasons this
feature doesn't follow that precedent:

  * ``transcribe_live`` reuses the SAME already-loaded Whisper model the
    transcription worker exists to hold. Voice cloning needs a
    completely different model (OmniVoice, a different library
    entirely) -- sharing the script would force every voice-clone
    worker to also load a Whisper model it never uses, and vice versa.
  * This feature is meant to be completely independent end to end (a
    standalone opt-in tab, its own on-demand dependency, its own
    installer toggle) -- entangling its startup with the transcription
    worker's frozen, heavily-audited protocol would work against that.

Unlike ``core.worker``, the OmniVoice model is loaded LAZILY on the
first ``generate`` command, not at process startup: spawning this
worker (e.g. just because the tab was opened) must stay cheap, and
loading takes minutes the first time. ``ready`` here means "process is
listening", not "model loaded" -- watch for ``model_ready`` /
``model_error`` instead.

Protocol (newline-delimited JSON, one object per line -- same shape as
``core.worker``, but its own, independent contract):

Commands (stdin):
  - ``{"action": "generate", "id", "text", "reference_paths", "output_path",
     "device"}``
  - ``{"action": "shutdown"}``

Events (stdout):
  - ``ready``                                   : process listening
  - ``model_loading``                           : first generate call;
                                                   loading OmniVoice (slow)
  - ``model_ready``                             : model loaded, generating
  - ``model_error``    (message)                : model failed to load
  - ``started``        (id)                     : generation accepted
  - ``done``            (id, output_path, audio_seconds, elapsed_seconds)
  - ``error``           (id, message)
  - ``log``             (message)
  - ``heartbeat``       (ts)

There is no cooperative cancel: OmniVoice's ``generate()`` is one
blocking call with no interrupt hook. A caller that wants to give up
mid-generation kills the whole process (see
``app.services.voice_clone_service.VoiceCloneWorker.stop``), same as
how ``core.optional_deps.install`` handles an install-cancel.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any

from .logging_setup import setup_logging

logger = logging.getLogger(__name__)

_emit_lock = threading.Lock()

HEARTBEAT_INTERVAL_SECONDS = 5.0


def emit(event: str, **payload: Any) -> None:
    payload["event"] = event
    try:
        line = json.dumps(payload)
    except (TypeError, ValueError) as e:
        safe = {k: repr(v) for k, v in payload.items()}
        safe["event"] = event
        safe["_emit_warning"] = f"payload not JSON-serialisable: {e}"
        line = json.dumps(safe)
    with _emit_lock:
        print(line, flush=True)


def main() -> int:
    setup_logging("INFO", filename=f"voiceclone-worker-{os.getpid()}.log")
    try:
        from .optional_deps import activate as _activate_extras
        _activate_extras()
    except Exception:  # noqa: BLE001
        pass
    logger.info("Voice-clone worker starting (pid=%d)", os.getpid())

    heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                emit("heartbeat", ts=time.time())
            except Exception:
                logger.exception("heartbeat emit failed")

    threading.Thread(target=_heartbeat, name="voiceclone-heartbeat", daemon=True).start()

    from . import voice_clone

    # The model is loaded lazily (see module docstring) via
    # voice_clone.load_model, which caches it at module level -- a
    # session that generates several clips in this process only pays
    # the multi-minute first load once.
    model_loaded = False

    emit("ready")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError as e:
            emit("error", message=f"Invalid worker command: {e}")
            continue
        if not isinstance(command, dict):
            emit("error", message="worker command must be a JSON object")
            continue

        action = command.get("action")
        if action == "shutdown":
            heartbeat_stop.set()
            return 0

        if action != "generate":
            emit("error", message=f"Unknown worker command: {action}")
            continue

        req_id = command.get("id")
        text = command.get("text") or ""
        reference_paths = command.get("reference_paths") or []
        output_path = command.get("output_path") or ""
        consent_accepted = bool(command.get("consent_accepted"))
        device = command.get("device") or "cpu"

        emit("started", id=req_id)
        try:
            if not model_loaded:
                emit("model_loading")
                model = voice_clone.load_model(device)
                model_loaded = True
                emit("model_ready")
            else:
                model = voice_clone.load_model(device)
            result = voice_clone.generate(
                model, text, reference_paths, output_path,
                consent_accepted=consent_accepted,
            )
            emit(
                "done", id=req_id, output_path=result.output_path,
                audio_seconds=result.audio_seconds,
                elapsed_seconds=result.elapsed_seconds,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Voice-clone generation failed")
            if not model_loaded:
                emit("model_error", message=str(e))
            emit("error", id=req_id, message=str(e))

    heartbeat_stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
