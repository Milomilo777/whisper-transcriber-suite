"""Live transcription engine — microphone / system audio, as you speak.

Tk-free, like the rest of ``core/``. The Live tab drives this; the
engine itself knows nothing about widgets, subprocesses, or how a chunk
gets transcribed (that is injected), which is what makes it testable
without a model, a sound card, or a UI.

Pipeline::

    Recorder (capture thread)  --frames-->  Segmenter  --chunks-->
        bounded queue  --worker thread-->  transcribe_chunk()  -->  events

Three decisions worth knowing about:

**Chunks are cut at silence, not on a timer.** Slicing every N seconds
splits words in half, and half a word transcribes as either nothing or
the wrong word. The segmenter watches signal level and closes a chunk
during a pause, falling back to a forced cut only when an utterance runs
past ``max_chunk_s`` — and even then it prefers the quietest recent
moment over the exact deadline.

**Silence is never sent to the model.** A chunk with no voiced audio is
dropped rather than transcribed. Whisper hallucinates confidently on
silence — this is the single biggest source of junk lines in a live
transcript, and dropping the chunk costs nothing.

**Falling behind is visible, never silent.** If transcription is slower
than real time (a big model on a weak CPU), the bounded queue drops the
oldest pending chunk and counts it. ``LiveSession.dropped_chunks`` and a
``warning`` event surface that, because a live transcript that quietly
skips audio is worse than one that admits it.
"""
from __future__ import annotations

import array
import logging
import os
import queue
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import recorder as _rec

logger = logging.getLogger(__name__)

SAMPLE_WIDTH_BYTES = 2  # int16
_INT16_FULL_SCALE = 32768.0


# ------------------------------------------------------------- segmentation


@dataclass(frozen=True)
class SegmenterConfig:
    """Chunking policy. Defaults tuned for conversational speech."""

    sample_rate: int = 16_000
    #: Never emit a chunk shorter than this — Whisper needs context.
    min_chunk_s: float = 2.0
    #: Force a cut here even mid-sentence, so the transcript keeps moving.
    max_chunk_s: float = 12.0
    #: Trailing quiet needed to treat a pause as an utterance boundary.
    silence_hold_s: float = 0.45
    #: Normalised RMS (0..1) at or below which a block counts as silence.
    silence_rms: float = 0.012
    #: On a forced cut, look this far back for a quieter place to split.
    backtrack_s: float = 1.0

    def bytes_per_second(self) -> int:
        return int(self.sample_rate) * SAMPLE_WIDTH_BYTES


def block_rms(pcm: bytes) -> float:
    """Normalised RMS (0..1) of mono int16 PCM. Empty input -> 0.0.

    ``audioop`` would have been the obvious tool; it was removed in
    Python 3.13, and this project runs on 3.11-3.13+. numpy is used when
    present and a pure-stdlib path covers its absence, since numpy is not
    a hard dependency of the recorder.
    """
    if not pcm:
        return 0.0
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH_BYTES)
    if usable <= 0:
        return 0.0
    try:
        import numpy as np  # type: ignore[import-not-found]

        arr = np.frombuffer(pcm[:usable], dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(arr * arr)) / _INT16_FULL_SCALE)
    except ImportError:
        samples = array.array("h")
        samples.frombytes(pcm[:usable])
        if not samples:
            return 0.0
        total = 0
        for s in samples:
            total += s * s
        return (total / len(samples)) ** 0.5 / _INT16_FULL_SCALE


@dataclass
class Segmenter:
    """Splits a live PCM stream into utterance-sized chunks.

    Feed it whatever blocks the capture backend produces; it returns
    completed chunks. Pure and synchronous — no threads, no IO — so the
    cutting policy can be unit-tested against synthetic audio.
    """

    config: SegmenterConfig = field(default_factory=SegmenterConfig)
    _buf: bytearray = field(default_factory=bytearray, repr=False)
    #: Trailing silence, in bytes, at the end of ``_buf``.
    _silence_bytes: int = 0
    #: Whether ``_buf`` contains anything above the silence threshold.
    _voiced: bool = False
    #: Byte offset of the end of the most recent silent block.
    _last_quiet_offset: int = 0

    # ---------- properties ------------------------------------------

    @property
    def buffered_seconds(self) -> float:
        return len(self._buf) / float(self.config.bytes_per_second())

    def _seconds(self, n_bytes: int) -> float:
        return n_bytes / float(self.config.bytes_per_second())

    # ---------- feeding ---------------------------------------------

    def feed(self, pcm: bytes) -> list[bytes]:
        """Add captured audio; return any chunks that just completed."""
        if not pcm:
            return []
        cfg = self.config
        level = block_rms(pcm)
        self._buf.extend(pcm)
        if level <= cfg.silence_rms:
            self._silence_bytes += len(pcm)
            self._last_quiet_offset = len(self._buf)
        else:
            self._silence_bytes = 0
            self._voiced = True

        out: list[bytes] = []
        while True:
            chunk = self._maybe_cut()
            if chunk is None:
                break
            if chunk:
                out.append(chunk)
        return out

    def _maybe_cut(self) -> bytes | None:
        """Return a completed chunk, ``b""`` for a dropped one, else None.

        ``b""`` means "a cut happened but the audio was pure silence" —
        the caller must not transcribe it, and the loop in :meth:`feed`
        must keep going rather than treating it as end-of-input.
        """
        cfg = self.config
        buffered = self.buffered_seconds
        if buffered <= 0.0:
            return None

        pause_cut = (
            buffered >= cfg.min_chunk_s
            and self._seconds(self._silence_bytes) >= cfg.silence_hold_s
        )
        forced_cut = buffered >= cfg.max_chunk_s
        if not pause_cut and not forced_cut:
            return None

        split_at = len(self._buf)
        if forced_cut and not pause_cut:
            # Prefer a recent quiet moment over the hard deadline, so a
            # forced cut still lands between words when it can.
            backtrack_bytes = int(cfg.backtrack_s * cfg.bytes_per_second())
            earliest = max(0, len(self._buf) - backtrack_bytes)
            if (self._last_quiet_offset > earliest
                    and self._seconds(self._last_quiet_offset) >= cfg.min_chunk_s):
                split_at = self._last_quiet_offset

        chunk = bytes(self._buf[:split_at])
        del self._buf[:split_at]
        was_voiced = self._voiced
        # Whatever is left is the start of the next utterance.
        self._voiced = block_rms(bytes(self._buf)) > cfg.silence_rms
        self._silence_bytes = min(self._silence_bytes, len(self._buf))
        self._last_quiet_offset = min(self._last_quiet_offset, len(self._buf))
        if not was_voiced:
            # Pure silence: never hand it to the model. Whisper invents
            # text on silence, and that junk is the main thing that makes
            # a live transcript untrustworthy.
            return b""
        return chunk

    def flush(self, *, min_seconds: float = 0.4) -> bytes | None:
        """Return the trailing audio at stop, if it is worth transcribing."""
        if not self._voiced or self.buffered_seconds < min_seconds:
            self._buf.clear()
            self._voiced = False
            self._silence_bytes = 0
            self._last_quiet_offset = 0
            return None
        chunk = bytes(self._buf)
        self._buf.clear()
        self._voiced = False
        self._silence_bytes = 0
        self._last_quiet_offset = 0
        return chunk


def write_wav(path: str, pcm: bytes, sample_rate: int) -> str:
    """Write mono int16 PCM to ``path`` as a WAV. Returns ``path``."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_WIDTH_BYTES)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm)
    return path


# ----------------------------------------------------------------- events


@dataclass(frozen=True)
class LiveEvent:
    """Something the UI should react to. ``kind`` drives the handling."""

    kind: str          # "text" | "warning" | "error" | "state"
    text: str = ""
    start: float = 0.0     # seconds since session start
    end: float = 0.0
    language: str = ""
    detail: str = ""


# --------------------------------------------------------------- session


@dataclass
class LiveSession:
    """One live transcription run: capture -> chunk -> transcribe -> events.

    ``transcribe_chunk`` is injected: it takes a WAV path and returns the
    recognised text (or a dict with a ``text`` key). Keeping it out of
    this module means the engine can be tested with a stub, and the app
    can route chunks to the existing hot worker subprocess rather than
    loading a model in the GUI process.
    """

    transcribe_chunk: Callable[[str], Any]
    work_dir: str
    mode: str = "mic"                      # "mic" | "loopback"
    device_index: Optional[int] = None
    language: Optional[str] = None
    keep_recording: bool = True
    config: SegmenterConfig = field(default_factory=SegmenterConfig)
    #: Bounded so a slow machine drops audio visibly instead of growing
    #: an unbounded backlog and drifting further behind reality.
    max_pending_chunks: int = 8
    #: Optional live-meter tap ``(pcm_bytes, rate)`` called on the
    #: recorder's capture thread for every captured block. Added for the
    #: Live tab visualizer, which needs the audio *while* it is being
    #: captured. Purely additive: transcription never depends on it, and
    #: exceptions from the sink are swallowed and logged so a broken
    #: meter can never kill a session.
    on_meter: Optional[Callable[[bytes, int], None]] = field(
        default=None, repr=False
    )

    events: "queue.Queue[LiveEvent]" = field(
        default_factory=lambda: queue.Queue(maxsize=1000), repr=False
    )
    dropped_chunks: int = 0
    recording_path: str = ""

    _segmenter: Segmenter = field(init=False, repr=False)
    _chunks: "queue.Queue[tuple[int, bytes, float, int] | None]" = field(
        init=False, repr=False
    )
    _recorder: Optional[_rec.Recorder] = field(default=None, repr=False)
    _consumer: Optional[threading.Thread] = field(default=None, repr=False)
    _stopping: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    _seq: int = 0
    _elapsed_bytes: int = 0
    _rate: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._segmenter = Segmenter(config=self.config)
        self._chunks = queue.Queue(maxsize=max(1, self.max_pending_chunks))
        self._rate = self.config.sample_rate

    # ---------- lifecycle -------------------------------------------

    def start(self) -> None:
        """Begin capturing and transcribing. Raises if the backend is missing."""
        if self._recorder is not None:
            raise RuntimeError("LiveSession already started")
        os.makedirs(self.work_dir, exist_ok=True)
        self.recording_path = os.path.join(self.work_dir, "live-session.wav")
        self._stopping.clear()
        self._consumer = threading.Thread(
            target=self._consume, name="live-transcribe", daemon=True
        )
        self._consumer.start()
        rec = _rec.Recorder(
            output_path=self.recording_path,
            mode=self.mode,
            device_index=self.device_index,
            sample_rate=self.config.sample_rate,
            on_frames=self._on_frames,
        )
        try:
            rec.start()
        except Exception:
            # Never leave the consumer thread running behind a failed start.
            self._stopping.set()
            self._chunks.put(None)
            raise
        self._recorder = rec
        self._emit(LiveEvent(kind="state", detail="started"))

    def stop(self, *, timeout: float = 10.0) -> str:
        """Stop capture, transcribe the tail, and return the recording path."""
        if self._stopping.is_set():
            # Already stopped or stopping (e.g. the Stop button's worker
            # and the app-exit teardown both call this). Re-running the
            # teardown would queue a second sentinel with no consumer
            # left to drain it and emit duplicate "stopped"/error events.
            return self.recording_path
        self._stopping.set()
        rec = self._recorder
        if rec is not None:
            try:
                rec.stop()
            except Exception as e:  # noqa: BLE001
                logger.exception("Stopping the recorder failed: %s", e)
                self._emit(LiveEvent(kind="error", detail=str(e)))
        # Flush whatever was mid-utterance when the user hit stop. Guarded
        # by the same lock _on_frames takes around feed(): Segmenter has
        # no lock of its own, and a capture-thread call still in flight
        # when rec.stop()'s join times out (a wedged backend) would
        # otherwise race flush() over the same buffer.
        with self._lock:
            tail = self._segmenter.flush()
        if tail:
            self._submit(tail)
        self._chunks.put(None)   # sentinel: drain then exit
        consumer = self._consumer
        if consumer is not None and consumer.is_alive():
            consumer.join(timeout=timeout)
        if rec is not None and rec.last_error:
            self._emit(LiveEvent(kind="error", detail=rec.last_error))
        self._emit(LiveEvent(kind="state", detail="stopped"))
        return self.recording_path

    def is_running(self) -> bool:
        rec = self._recorder
        return rec is not None and rec.is_running()

    # ---------- capture side (runs on the recorder's thread) ---------

    def _on_frames(self, pcm: bytes, rate: int) -> None:
        if self._stopping.is_set():
            return
        with self._lock:
            self._rate = int(rate) or self.config.sample_rate
        meter = self.on_meter
        if meter is not None and pcm:
            try:
                meter(pcm, self._rate)
            except Exception:  # noqa: BLE001
                logger.exception("Live meter sink raised; continuing capture")
        with self._lock:
            chunks = self._segmenter.feed(pcm)
        for chunk in chunks:
            self._submit(chunk)

    def _submit(self, pcm: bytes) -> None:
        """Queue a chunk, dropping the oldest if the consumer is behind."""
        with self._lock:
            start_s = self._elapsed_bytes / float(
                self.config.bytes_per_second()
            )
            self._elapsed_bytes += len(pcm)
            self._seq += 1
            seq = self._seq
            rate = self._rate
        item = (seq, pcm, start_s, rate)
        try:
            self._chunks.put_nowait(item)
            return
        except queue.Full:
            pass
        # Behind real time. Drop the OLDEST pending chunk: the newest
        # audio is what the user is watching for, and silently growing
        # the backlog would drift further behind with every chunk.
        try:
            self._chunks.get_nowait()
            self.dropped_chunks += 1
        except queue.Empty:
            pass
        try:
            self._chunks.put_nowait(item)
        except queue.Full:
            self.dropped_chunks += 1
            return
        self._emit(LiveEvent(
            kind="warning",
            detail=(
                f"Transcription is behind the audio; {self.dropped_chunks} "
                f"chunk(s) skipped. Try a smaller model in Advanced."
            ),
        ))

    # ---------- transcribe side (its own thread) ---------------------

    def _consume(self) -> None:
        while True:
            item = self._chunks.get()
            if item is None:
                return
            seq, pcm, start_s, rate = item
            path = os.path.join(self.work_dir, f"chunk-{seq:06d}.wav")
            try:
                write_wav(path, pcm, rate)
            except OSError as e:
                self._emit(LiveEvent(kind="error", detail=f"Chunk write failed: {e}"))
                continue
            try:
                result = self.transcribe_chunk(path)
            except Exception as e:  # noqa: BLE001
                # One failed chunk must not end the session.
                logger.exception("Live chunk transcription failed: %s", e)
                self._emit(LiveEvent(kind="error", detail=str(e)))
                continue
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            text, language = _result_text(result)
            if not text:
                continue
            self._emit(LiveEvent(
                kind="text",
                text=text,
                start=start_s,
                end=start_s + (len(pcm) / float(self.config.bytes_per_second())),
                language=language,
            ))

    # ---------- events ----------------------------------------------

    def _emit(self, event: LiveEvent) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            # The UI is not draining; dropping a status line is better
            # than blocking the capture or transcribe thread.
            logger.warning("Live event queue full; dropped %s", event.kind)

    def drain_events(self, limit: int = 64) -> list[LiveEvent]:
        """Pop up to ``limit`` events. Called from the Tk main thread."""
        out: list[LiveEvent] = []
        for _ in range(max(0, limit)):
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out


def _result_text(result: Any) -> tuple[str, str]:
    """Normalise whatever ``transcribe_chunk`` returned to (text, language)."""
    if result is None:
        return "", ""
    if isinstance(result, str):
        return result.strip(), ""
    if isinstance(result, dict):
        return (
            str(result.get("text", "") or "").strip(),
            str(result.get("language", "") or ""),
        )
    return str(result).strip(), ""


# ------------------------------------------------------------ availability


def is_available(mode: str = "mic") -> bool:
    return _rec.loopback_available() if mode == "loopback" else _rec.mic_available()


def availability_reason(mode: str = "mic") -> str:
    if mode == "loopback":
        return _rec.loopback_availability_reason()
    return _rec.mic_availability_reason()


def list_input_devices() -> list[_rec.InputDevice]:
    return _rec.list_mic_devices()


def session_work_dir() -> str:
    """Per-run scratch dir for chunk WAVs and the session recording."""
    from .config import user_cache_dir

    base = user_cache_dir() / "live" / time.strftime("%Y%m%d-%H%M%S")
    return str(base)
