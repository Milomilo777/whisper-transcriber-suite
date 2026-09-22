"""Audio recording — mic + system loopback (v0.8 Phase 2).

Two record modes the UI surfaces:

  * **Microphone** — captures from the default (or user-picked) input
    device via :mod:`sounddevice`. Falls back to a clean
    ``RecorderUnavailable`` raise when the package isn't installed.
  * **System audio (WASAPI loopback)** — captures whatever is playing
    on the default speakers via :mod:`pyaudiowpatch` (a fork of
    PyAudio that exposes Windows WASAPI loopback devices). Same
    fallback when missing.

Both modes write a mono 16-kHz int16 WAV next to the user's chosen
download folder (or a temp dir). The existing transcribe pipeline
takes the resulting WAV from there — no special path needed.

Design notes:

* No background services. Recording is started from the UI button,
  produces a single WAV when stopped, and that's it. The Live tab
  uses this module as the recorder; live-streaming transcription
  itself is a Phase 2 RealtimeSTT integration if/when that lands.
* The recorder runs in a daemon thread so the UI stays responsive.
  Stop is non-blocking — we set an event the recording loop polls.
* All numpy/IO errors surface via ``Recorder.last_error``; the UI
  surfaces them through the app log + a messagebox.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # int16


class RecorderUnavailable(RuntimeError):
    """Raised when the requested recording backend isn't installed."""


# ---------------------------------------------------------------- availability


def _import_failure(module_name: str) -> Optional[BaseException]:
    """Return the exception raised by importing ``module_name``, else None.

    Catches more than ImportError on purpose: a present-but-broken native
    backend raises OSError at import time — most notably sounddevice's
    documented "PortAudio library not found" (common on Linux without
    libportaudio2) and DLL-load failures for pyaudiowpatch on Windows.
    Both mean "this machine cannot record via that backend", so they must
    degrade to the same unavailable state as a missing package rather than
    escape into a UI callback as an unhandled exception.
    """
    try:
        __import__(module_name)
    except Exception as e:  # noqa: BLE001
        return e
    return None


def mic_available() -> bool:
    """True iff sounddevice imports cleanly."""
    return _import_failure("sounddevice") is None


def mic_availability_reason() -> str:
    if mic_available():
        return ""
    err = _import_failure("sounddevice")
    if err is not None and not isinstance(err, ImportError):
        return f"sounddevice could not be loaded: {err}"
    return (
        "sounddevice not installed — `pip install sounddevice` to "
        "enable microphone recording."
    )


def loopback_available() -> bool:
    """True iff pyaudiowpatch imports cleanly (Windows-only WASAPI loopback)."""
    if os.name != "nt":
        return False
    return _import_failure("pyaudiowpatch") is None


def loopback_availability_reason() -> str:
    if os.name != "nt":
        return "System-audio capture requires Windows (WASAPI loopback)."
    if loopback_available():
        return ""
    err = _import_failure("pyaudiowpatch")
    if err is not None and not isinstance(err, ImportError):
        return f"pyaudiowpatch could not be loaded: {err}"
    return (
        "pyaudiowpatch not installed — `pip install PyAudioWPatch` to "
        "enable system-audio (loopback) recording."
    )


# ---------------------------------------------------------------- devices


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float


def list_mic_devices() -> list[InputDevice]:
    """Enumerate available microphone input devices.

    Returns an empty list when sounddevice isn't installed (rather
    than raising) so the UI can fall back to "default device" mode.
    """
    if not mic_available():
        return []
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
        out: list[InputDevice] = []
        for idx, info in enumerate(sd.query_devices()):
            try:
                channels = int(info.get("max_input_channels", 0))
                if channels <= 0:
                    continue
                out.append(InputDevice(
                    index=idx,
                    name=str(info.get("name", f"Device {idx}")),
                    max_input_channels=channels,
                    default_samplerate=float(
                        info.get("default_samplerate", SAMPLE_RATE)
                    ),
                ))
            except (TypeError, ValueError):
                # One malformed entry (a driver reporting None for a
                # numeric field — seen on hot-unplug/virtual-cable
                # devices) must not hide every other working device.
                logger.debug("Skipping malformed device entry %r: %r", idx, info)
                continue
        return out
    except Exception as e:  # noqa: BLE001
        logger.exception("list_mic_devices failed: %s", e)
        return []


# ---------------------------------------------------------------- recorder


@dataclass
class Recorder:
    """Owns a single recording session.

    Construct one per session, ``start()`` to begin, ``stop()`` to
    flush + finalize. The output WAV path is in ``output_path``
    after stop() returns.
    """
    output_path: str
    mode: str = "mic"  # "mic" | "loopback"
    device_index: Optional[int] = None
    sample_rate: int = SAMPLE_RATE
    #: Optional tap on the live PCM stream, called ``(pcm_bytes, rate)``
    #: as each block arrives (mono int16). Added for the Live tab, which
    #: needs the audio *while* it is being captured rather than one WAV
    #: at the end. The WAV is still written exactly as before, so this is
    #: purely additive. Exceptions raised by the sink are swallowed and
    #: logged: a broken consumer must never kill the recording.
    on_frames: Optional[Callable[[bytes, int], None]] = field(
        default=None, repr=False
    )
    # ``_frames`` is retained ONLY as the fallback/empty-file writer path
    # (see _finalize_wav); real capture streams straight to disk so a
    # multi-hour recording no longer buffers the whole take in RAM (OOM).
    _frames: list[bytes] = field(default_factory=list, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _started_at: float = 0.0
    _stopped_at: float = 0.0
    _wrote_wave: bool = False
    last_error: Optional[str] = None

    def start(self) -> None:
        """Begin recording in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Recorder is already running")
        self._frames.clear()
        self._wrote_wave = False
        self._stop_event.clear()
        self.last_error = None
        self._started_at = time.time()
        self._stopped_at = 0.0
        if self.mode == "mic":
            if not mic_available():
                raise RecorderUnavailable(mic_availability_reason())
            target = self._mic_loop
        elif self.mode == "loopback":
            if not loopback_available():
                raise RecorderUnavailable(loopback_availability_reason())
            target = self._loopback_loop
        else:
            raise ValueError(f"Unknown recorder mode: {self.mode!r}")
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> str:
        """Stop the recording loop and finalize the WAV.

        Returns the path to the final WAV. Joins the recording
        thread with ``timeout`` so a wedged backend doesn't deadlock
        the UI. The capture loop streams + closes the WAV itself; if it
        never produced one (start failed, instant stop, no backend) we
        write a valid empty WAV here so the caller's "open this file"
        path doesn't crash.

        DATA-LOSS guard: ``_finalize_wav`` opens ``output_path`` with
        ``wave.open(..., "wb")``, which truncates the file. We must NEVER
        do that while the capture thread is *still alive* — a wedged
        backend that ignored the stop event can still own the same WAV
        handle, and truncating it here would corrupt the partial take
        and create two writers. So we only fall back to the empty-file
        writer once the thread has actually terminated. The read of
        ``_wrote_wave`` is likewise gated on the thread being dead, which
        removes the TOCTOU window where the loop is mid-close.
        """
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._stopped_at = time.time()
        # If the capture thread is wedged (still alive after join), leave
        # whatever it has streamed to disk untouched rather than racing it
        # for the same file handle. A partial WAV beats a truncated/empty
        # one and avoids the two-writer corruption.
        if thread is not None and thread.is_alive():
            return self.output_path
        if not self._wrote_wave or not os.path.isfile(self.output_path):
            try:
                self._finalize_wav()
            except Exception as e:  # noqa: BLE001
                # An unwritable output_path (read-only folder, disk
                # full, parent is a file) must not turn a recoverable
                # empty/no-capture take into stop() raising instead of
                # returning a path, per this method's own contract.
                self.last_error = str(e)
                logger.exception("Writing the fallback empty WAV failed")
        return self.output_path

    def duration_seconds(self) -> float:
        end = self._stopped_at or time.time()
        return max(0.0, end - self._started_at)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------- internals ------------------------------------------

    def _emit_frames(self, pcm: bytes, rate: int) -> None:
        """Hand a captured block to the optional live sink.

        Never propagates: the sink is a consumer bolted onto the capture
        loop, and a bug there must not abort the recording the user is
        relying on.
        """
        sink = self.on_frames
        if sink is None or not pcm:
            return
        try:
            sink(pcm, rate)
        except Exception:  # noqa: BLE001
            logger.exception("Recorder frame sink raised; continuing capture")

    def _open_wave(self, rate: int) -> "wave.Wave_write":
        """Open the output WAV for streaming (mono int16 at ``rate``)."""
        Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
        wf = wave.open(self.output_path, "wb")
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH_BYTES)
        wf.setframerate(rate)
        return wf

    def _mic_loop(self) -> None:
        wf: "wave.Wave_write | None" = None
        wrote_any_frames = False
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
            stream_kwargs: dict[str, Any] = {
                "samplerate": self.sample_rate,
                "channels": CHANNELS,
                "dtype": "int16",
                "blocksize": 1024,
            }
            if self.device_index is not None:
                stream_kwargs["device"] = self.device_index
            with sd.RawInputStream(**stream_kwargs) as stream:
                # The requested rate is a hint; a fixed-rate device (or a
                # future PortAudio that nearest-matches instead of
                # raising) can silently open at a different rate. Read
                # the stream's own negotiated rate back rather than
                # trusting the request, so the WAV header and the live
                # tap always agree with what was actually captured — a
                # LOCAL variable, never self.sample_rate, so this
                # session's negotiated rate can't leak into the next
                # session if this Recorder is reused (see _loopback_loop
                # for the same reasoning).
                actual_rate = int(getattr(stream, "samplerate", self.sample_rate)) \
                    or self.sample_rate
                # Stream straight to disk — never buffer the whole take in
                # memory (a multi-hour recording would OOM the app).
                wf = self._open_wave(actual_rate)
                while not self._stop_event.is_set():
                    data, _overflow = stream.read(1024)
                    block = bytes(data)
                    wf.writeframes(block)
                    wrote_any_frames = True
                    self._emit_frames(block, actual_rate)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Mic recording failed: %s", e)
        finally:
            if wf is not None:
                try:
                    wf.close()
                    self._wrote_wave = True
                except Exception:  # noqa: BLE001
                    logger.exception("Closing mic WAV failed")
                    if wrote_any_frames:
                        # Real audio already reached disk even though the
                        # header flush on close() failed (e.g. disk full).
                        # stop()'s empty-file fallback must never truncate
                        # a non-empty partial take.
                        self._wrote_wave = True

    def _loopback_loop(self) -> None:
        wf: "wave.Wave_write | None" = None
        wrote_any_frames = False
        try:
            import pyaudiowpatch as pya  # type: ignore[import-not-found]
            with pya.PyAudio() as p:
                try:
                    info = p.get_default_wasapi_loopback()
                except OSError:
                    self.last_error = "No default WASAPI loopback device available."
                    return
                device_idx = int(info["index"])
                # Native rate, in a LOCAL variable — never self.sample_rate.
                # That field is the caller's ORIGINAL request; mutating it
                # from the capture thread would silently change what the
                # next mic/loopback session on a reused Recorder expects
                # (the documented mono-16kHz contract) to whatever this
                # session's device happened to negotiate.
                actual_rate = int(info["defaultSampleRate"])
                channels = int(info["maxInputChannels"]) or 1
                stream = p.open(
                    format=pya.paInt16,
                    channels=channels,
                    rate=actual_rate,
                    frames_per_buffer=1024,
                    input=True,
                    input_device_index=device_idx,
                )
                try:
                    # wave-open (and everything after) is now INSIDE this
                    # try so the stream is always stopped/closed below,
                    # even if _open_wave raises (e.g. an unwritable output
                    # path) before a single frame is captured — it used to
                    # run before this try started, leaking the WASAPI
                    # stream handle on that failure.
                    wf = self._open_wave(actual_rate)
                    # The FIRST stream.read() here can block far longer than
                    # 1024 frames' worth of audio (~49s measured on real
                    # hardware with a silent output device) -- WASAPI only
                    # actively renders/delivers loopback data once something
                    # is actually playing. Reads after the first are normal
                    # (sub-second). See docs/LIVE.md's Limitations section.
                    while not self._stop_event.is_set():
                        data = stream.read(1024, exception_on_overflow=False)
                        mono = _downmix_to_mono_int16(data, channels)
                        wf.writeframes(mono)
                        wrote_any_frames = True
                        self._emit_frames(mono, actual_rate)
                finally:
                    # Each guarded independently: if stop_stream() raises
                    # (e.g. the device vanished), close() must still run
                    # rather than being skipped — and a stop_stream()
                    # failure must not mask whatever error stream.read()
                    # already raised above.
                    try:
                        stream.stop_stream()
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed to stop loopback stream")
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed to close loopback stream")
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Loopback recording failed: %s", e)
        finally:
            if wf is not None:
                try:
                    wf.close()
                    self._wrote_wave = True
                except Exception:  # noqa: BLE001
                    logger.exception("Closing loopback WAV failed")
                    if wrote_any_frames:
                        self._wrote_wave = True

    def _finalize_wav(self) -> None:
        """Fallback writer for the no-capture case.

        Real capture streams to disk via _open_wave + the loops; this only
        runs from stop() when the loop never produced a WAV (start failed /
        instant stop), writing a valid (usually 0-frame) file from any
        ``_frames`` that were injected. Kept so "open this file" never
        crashes on an empty take.
        """
        Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(self.output_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH_BYTES)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(self._frames))


def _downmix_to_mono_int16(data: bytes, channels: int) -> bytes:
    """Average ``channels`` int16 samples per frame to mono.

    Inputs from WASAPI loopback are typically stereo; the rest of the
    transcribe pipeline expects mono. We do the downmix here in pure
    Python (numpy-optional) so the recorder has no hard numpy
    dependency.
    """
    if channels <= 1:
        return data
    try:
        import numpy as np  # type: ignore[import-not-found]
        arr = np.frombuffer(data, dtype=np.int16)
        if arr.size % channels != 0:
            # Trim trailing partial frame so reshape is safe.
            arr = arr[: (arr.size // channels) * channels]
        frames = arr.reshape(-1, channels)
        mono = frames.mean(axis=1).astype(np.int16)
        return mono.tobytes()
    except Exception as e:  # noqa: BLE001
        # No numpy, numpy present-but-broken (missing MKL/DLL raises
        # OSError, not ImportError), or a corrupt/unexpected block this
        # block's reshape/mean choked on — any of these must degrade to
        # the pure-Python fallback below rather than abort the whole
        # take (this can run per-block in the capture loop).
        if not isinstance(e, ImportError):
            logger.debug("numpy downmix failed; using pure-Python fallback",
                         exc_info=True)
        # Fall back to interleaved pick of channel 0. Acceptable for
        # transcription where exact loudness doesn't matter as much as
        # content. Only a COMPLETE frame (all channels) counts — a
        # trailing stub shorter than sample_bytes is a partial frame,
        # not a valid sample, and must be dropped like the numpy path
        # does, not fabricated from a fraction of a frame.
        sample_bytes = SAMPLE_WIDTH_BYTES * channels
        frames = [data[i:i + sample_bytes] for i in range(0, len(data), sample_bytes)]
        return b"".join(f[:SAMPLE_WIDTH_BYTES] for f in frames if len(f) >= sample_bytes)
