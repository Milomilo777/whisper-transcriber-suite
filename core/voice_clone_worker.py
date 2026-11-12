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
     "device", "instruct"?, "language"?, "speed"?, "consent_record"?}``
     (empty reference_paths = voice design with ``instruct``, or the
     model's own voice without it; ``consent_record`` false = a piece of a
     long job, whose caller records consent for the joined file)
  - ``{"action": "shutdown"}``

Events (stdout):
  - ``ready``                                   : process listening
  - ``model_loading``                           : preparing reference text
                                                   or loading OmniVoice
  - ``model_ready``                             : model loaded, generating
  - ``model_error``    (message)                : model failed to load
  - ``started``        (id)                     : generation accepted
  - ``done``            (id, output_path, audio_seconds, elapsed_seconds,
                         warning: "" or a non-fatal problem to show)
  - ``error``           (id, message)
  - ``log``             (message)
  - ``heartbeat``       (ts)

There is no cooperative cancel: OmniVoice's ``generate()`` is one
blocking call with no interrupt hook. A caller that wants to give up
mid-generation kills the whole process (see
``app.services.voice_clone_service.VoiceCloneWorker.stop``), same as
how ``core.optional_deps.install`` handles an install-cancel.

stdin is read on its own thread, so the worker notices both a
``shutdown`` and the app going away (stdin EOF, or a broken stdout pipe)
while a generation is running: it then exits at once instead of
finishing a piece nobody will collect. ``voice_clone.generate`` writes
its WAV to a temporary name and renames it at the end, so an exit
mid-generation leaves no half-written piece.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import queue
import sys
import threading
import time
from contextlib import nullcontext
from typing import Any

from ._proc import parent_alive, parent_identity, wait_parent_gone
from .logging_setup import setup_logging

logger = logging.getLogger(__name__)

_emit_lock = threading.Lock()

HEARTBEAT_INTERVAL_SECONDS = 5.0

# Set while voice_clone.generate (or the model load) runs on the main
# thread. The main thread cannot look at stdin until that blocking call
# returns, so the stdin reader (or the heartbeat) ends the process itself
# when the app is gone meanwhile.
_busy = threading.Event()


def _hard_exit(code: int) -> None:
    """End the process at once (tests replace this)."""
    os._exit(code)


#: How long a closed pipe waits for the parent's process to be gone (a
#: pipe can close a moment before the dying app's process object ends).
PARENT_GONE_CONFIRM_S = 5.0


def _exit_if_orphaned(
    identity: "tuple[int, float] | None", reason: str, wait_s: float = 0.0
) -> None:
    """End a running generation whose app is gone: its piece would be
    written for nobody and could change under a later resumed job."""
    if not _busy.is_set():
        return
    gone = wait_parent_gone(identity, wait_s) if wait_s > 0 else not parent_alive(identity)
    if gone and _busy.is_set():
        logger.warning("The app went away (%s) mid-generation; exiting", reason)
        _hard_exit(0)


def emit(event: str, **payload: Any) -> None:
    payload["event"] = event
    try:
        line = json.dumps(payload)
    except (TypeError, ValueError) as e:
        safe = {}
        for k, v in payload.items():
            try:
                safe[k] = repr(v)
            except Exception as repr_e:  # noqa: BLE001 -- fallback is robust against completely broken objects
                safe[k] = f"<unrepresentable: {type(repr_e).__name__}>"
        safe["event"] = event
        safe["_emit_warning"] = f"payload not JSON-serialisable: {e}"
        line = json.dumps(safe)
    with _emit_lock:
        print(line, flush=True)


def _process_priority() -> str:
    """This process's CPU and I/O priority for the start log line, e.g.
    ``"cpu=BELOW_NORMAL_PRIORITY_CLASS, io=IOPRIO_LOW"`` ("unknown" when it
    cannot be read).

    The worker inherits both from whatever started the app. A low I/O
    priority (Windows gives it to programs started by a scheduled task) lets
    another program's reads on the same disk starve the model load for many
    minutes, which looks exactly like a hang; this line tells the two apart.
    """
    try:
        import psutil  # type: ignore[import-not-found] # noqa: PLC0415

        proc = psutil.Process()
        parts = [f"cpu={_priority_name(proc.nice())}"]
        ionice = getattr(proc, "ionice", None)  # absent on macOS
        if ionice is not None:
            parts.append(f"io={_priority_name(ionice())}")
        return ", ".join(parts)
    except Exception:  # noqa: BLE001
        logger.debug("could not read the process priority", exc_info=True)
        return "unknown"


def _priority_name(value: Any) -> str:
    # psutil returns enum members on Windows (named) and plain ints or an
    # (ioclass, value) tuple on POSIX.
    name = getattr(value, "name", None)
    return str(name) if name else str(value)


def main() -> int:
    # Work offline backstop: OmniVoice fetches its weights from Hugging Face.
    from . import offline
    offline.install_network_guard()
    try:
        setup_logging("INFO", filename=f"voiceclone-worker-{os.getpid()}.log")
    except Exception:  # noqa: BLE001
        # Logging is best-effort, as in core.worker: an unwritable or
        # AV-locked log folder must not kill the worker before its first
        # event (the protocol lives on stdout).
        pass
    try:
        from .optional_deps import activate as _activate_extras, extras_dir
        _activate_extras()
        # This dedicated process needs the runtime installed alongside
        # OmniVoice, rather than an older host torch ahead of that cache.
        # Keep the GUI/transcription process's bundled-first policy intact.
        # Give the cache priority only when both primary packages exist.
        runtime = extras_dir()
        if all(os.path.isfile(os.path.join(runtime, name, "__init__.py"))
               for name in ("omnivoice", "torch")):
            sys.path[:] = [runtime] + [p for p in sys.path if p != runtime]
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        # Adapted from MCP Python SDK (https://github.com/modelcontextprotocol/python-sdk/issues/2832) — pre-import before stdin reads.
        # SciPy's Fortran DLL initialization can wait on the stdin pipe.
        # Load it before another thread blocks reading that same pipe;
        # no model is loaded here. Missing optional SciPy is harmless.
        try:
            importlib.import_module("scipy.linalg")
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, ModuleNotFoundError) and e.name == "scipy"):
                logger.exception("Voice runtime initialization failed")
                emit("model_error", message=f"Voice runtime initialization failed: {e}")
                return 1
    logger.info("Voice-clone worker starting (pid=%d, priority %s)",
                os.getpid(), _process_priority())

    parent = parent_identity()
    heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                emit("heartbeat", ts=time.time())
            except OSError:
                # stdout is a pipe to the app: broken = the app is likely gone.
                _exit_if_orphaned(parent, "its output pipe is closed", PARENT_GONE_CONFIRM_S)
            except Exception:
                logger.exception("heartbeat emit failed")

    threading.Thread(target=_heartbeat, name="voiceclone-heartbeat", daemon=True).start()

    t_import = time.time()
    from . import voice_clone
    # This import pulls in the transcription stack (seconds on a quiet
    # disk); timed so a slow start is not mistaken for a slow model load.
    logger.info("Voice-clone worker listening (imports took %.1fs)", time.time() - t_import)

    # The model is loaded lazily (see module docstring) via
    # voice_clone.load_model, which caches it at module level -- a
    # session reuses it until a new reference needs ASR. Reference ASR
    # and OmniVoice never remain loaded together in this worker.
    model_loaded = False
    # Reuse one owned folder across long-job pieces; each preparation holds
    # its OS lock until generation finishes and removes its own frozen PCM.
    reference_scratch: str | None = None

    emit("ready")

    lines: "queue.Queue[str | None]" = queue.Queue()
    reader_done = threading.Event()
    _busy.clear()

    def _stdin_reader() -> None:
        try:
            for raw_line in sys.stdin:
                lines.put(raw_line)
        except (OSError, ValueError):
            logger.debug("stdin read failed", exc_info=True)
        finally:
            lines.put(None)
            reader_done.set()
            _exit_if_orphaned(parent, "its input pipe is closed", PARENT_GONE_CONFIRM_S)

    threading.Thread(target=_stdin_reader, name="voiceclone-stdin", daemon=True).start()

    while True:
        raw = lines.get()
        if raw is None:
            break
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
        instruct = command.get("instruct") or None
        language = command.get("language") or None
        speed = command.get("speed") or None
        consent_record = command.get("consent_record", True) is not False

        # Busy BEFORE looking at reader_done: either the reader sees the
        # flag at EOF, or this check sees the EOF (no gap between them).
        _busy.set()
        if reader_done.is_set():
            _exit_if_orphaned(parent, "its input pipe is closed")
        emit("started", id=req_id)
        model = None
        try:
            if reference_paths:
                # Preparation can decode speech and invalidate the TTS cache.
                # Tell the parent before either potentially slow operation.
                emit("model_loading")
                emit("log", message="Preparing reference audio and speech text.")
                model_loaded = False
                if consent_accepted and reference_scratch is None:
                    reference_scratch = voice_clone.session_work_dir()
            context = (voice_clone.prepare_reference(
                reference_paths, consent_accepted=consent_accepted,
                scratch_dir=reference_scratch,
            ) if reference_paths else nullcontext(None))
            with context as reference:
                # A changed reference releases the module's TTS cache before
                # ASR. No model from the previous command remains in this loop.
                if not model_loaded:
                    if not reference_paths:
                        emit("model_loading")
                    model_loaded = False
                    model = voice_clone.load_model(device)
                    model_loaded = True
                    emit("model_ready")
                else:
                    model = voice_clone.load_model(device)
                result = voice_clone.generate(
                    model, text, reference_paths, output_path,
                    consent_accepted=consent_accepted,
                    instruct=instruct, language=language, speed=speed,
                    consent_record=consent_record, prepared_reference=reference,
                )
            emit(
                "done", id=req_id, output_path=result.output_path,
                audio_seconds=result.audio_seconds,
                elapsed_seconds=result.elapsed_seconds,
                warning=result.warning,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Voice-clone generation failed")
            if not model_loaded:
                emit("model_error", message=str(e))
            emit("error", id=req_id, message=str(e))
        finally:
            # Cache ownership is intentional; a loop-local reference would
            # keep the previous TTS alive when next command unloads that cache.
            model = None
            _busy.clear()

    heartbeat_stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
