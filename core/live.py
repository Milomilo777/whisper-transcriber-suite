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
        # An offset into the buffer: the bytes before the cut are gone, so it moves with them.
        self._last_quiet_offset = max(0, self._last_quiet_offset - split_at)
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


# ---------------------------------------------------------------- resampling


class RateConverter:
    """Streaming resampler for mono int16 PCM (any rate -> ``dst_rate``).

    The segmenter, the event times and the chunk WAVs all count samples
    at ``SegmenterConfig.sample_rate``, but system-audio capture (and a
    microphone opened at its native rate) delivers 44.1/48 kHz. Feeding
    that straight in made chunks ~3x too short and event times ~3x too
    large, so every captured block goes through one of these first.

    Linear interpolation, with a moving-average pre-filter over the
    decimation factor when downsampling, so 8-24 kHz content does not
    fold back into the speech band at full strength. State carries across
    blocks, so how the capture backend slices the stream changes nothing
    but float rounding (at most 1 LSB on a few samples): no clicks, gaps
    or drift at block edges. numpy is used when present; the pure-Python
    path computes the same values (same positions, same rounding).
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        if int(src_rate) <= 0 or int(dst_rate) <= 0:
            raise ValueError(f"Bad sample rates: {src_rate} -> {dst_rate}")
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        self._step = self.src_rate / float(self.dst_rate)
        #: Moving-average length; 1 = no filter (same rate or upsampling).
        self._taps = max(1, int(round(self._step))) if self._step > 1.0 else 1
        #: Last ``_taps - 1`` raw samples, for the filter across blocks.
        self._hist: list[float] = [0.0] * (self._taps - 1)
        #: Filtered samples not yet fully consumed by the interpolator.
        self._carry: list[float] = []
        #: Position of the next output sample, in ``_carry`` coordinates.
        self._pos = 0.0
        self._odd = b""

    def convert(self, pcm: bytes) -> bytes:
        """Resample one block; returns whatever output is complete."""
        if self.src_rate == self.dst_rate:
            return pcm
        data = self._odd + pcm
        usable = len(data) - (len(data) % SAMPLE_WIDTH_BYTES)
        self._odd = data[usable:]
        if usable <= 0:
            return b""
        raw = array.array("h")
        raw.frombytes(data[:usable])
        try:
            import numpy as np  # type: ignore[import-not-found]
        except ImportError:
            return self._convert_pure(list(raw))
        return self._convert_numpy(np, raw)

    def _plan(self, n: int) -> int:
        """How many output samples ``n`` buffered inputs complete."""
        if n < 2 or self._pos > n - 2:
            return 0
        return int((n - 2 - self._pos) // self._step) + 1

    def _advance(self, buf: list[float], count: int) -> None:
        pos = self._pos + count * self._step
        drop = min(int(pos), len(buf))
        self._carry = buf[drop:]
        self._pos = pos - drop

    def _convert_pure(self, raw: list[int]) -> bytes:
        taps = self._taps
        if taps > 1:
            seq = self._hist + [float(v) for v in raw]
            filtered = [sum(seq[i:i + taps]) / taps for i in range(len(raw))]
            self._hist = seq[len(seq) - (taps - 1):]
        else:
            filtered = [float(v) for v in raw]
        buf = self._carry + filtered
        count = self._plan(len(buf))
        out = array.array("h")
        for k in range(count):
            pos = self._pos + k * self._step
            i = int(pos)
            frac = pos - i
            value = buf[i] + (buf[i + 1] - buf[i]) * frac
            out.append(max(-32768, min(32767, int(round(value)))))
        self._advance(buf, count)
        return out.tobytes()

    def _convert_numpy(self, np: Any, raw: "array.array[int]") -> bytes:
        taps = self._taps
        samples = np.asarray(raw, dtype=np.float64)
        if taps > 1:
            seq = np.concatenate([np.asarray(self._hist, dtype=np.float64), samples])
            # Shifted adds, left to right: the same float sums in the same
            # order as the pure path's sum(), so both round identically.
            filtered = seq[0:len(samples)].copy()
            for j in range(1, taps):
                filtered = filtered + seq[j:len(samples) + j]
            filtered = filtered / taps
            self._hist = seq[len(seq) - (taps - 1):].tolist()
        else:
            filtered = samples
        buf = self._carry + filtered.tolist()
        count = self._plan(len(buf))
        if count:
            arr = np.asarray(buf, dtype=np.float64)
            pos = self._pos + np.arange(count, dtype=np.float64) * self._step
            idx = pos.astype(np.int64)
            frac = pos - idx
            values = arr[idx] + (arr[idx + 1] - arr[idx]) * frac
            out = np.clip(np.rint(values), -32768, 32767).astype(np.int16).tobytes()
        else:
            out = b""
        self._advance(buf, count)
        return out


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
    #: Keep ``live-session.wav`` after the session. Off by default: the
    #: full-session recording is 115-345 MB per hour and used to pile up
    #: in the cache forever. See :meth:`finish_recording`.
    keep_recording: bool = False
    config: SegmenterConfig = field(default_factory=SegmenterConfig)
    #: Bounded so a slow machine drops audio visibly instead of growing
    #: an unbounded backlog and drifting further behind reality.
    max_pending_chunks: int = 8
    #: Failed chunks in a row before the session reports itself dead with
    #: one ``fatal`` event (a crashed or wedged worker fails every chunk;
    #: one bad chunk among good ones is not that).
    max_consecutive_errors: int = 3
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
    _discard: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    #: Set once the tail is queued: the consumer exits when this is set
    #: and the queue is empty, so the sentinel is only a wake-up call and
    #: losing it (full queue, drop-oldest) can never strand the consumer.
    _capture_done: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    _stopped_emitted: bool = False
    #: Chunks queued but not yet picked up, plus one while transcribing.
    _queued: int = 0
    _busy: bool = False
    _seq: int = 0
    _elapsed_bytes: int = 0
    _resampler: Optional[RateConverter] = field(default=None, repr=False)
    _consecutive_errors: int = 0
    _fatal_emitted: bool = False
    #: time.monotonic() of start(), of the last block and of the last
    #: block holding any non-zero sample (0.0 = never).
    _started_at: float = 0.0
    _last_frames_at: float = 0.0
    _last_signal_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._segmenter = Segmenter(config=self.config)
        self._chunks = queue.Queue(maxsize=max(1, self.max_pending_chunks))

    # ---------- lifecycle -------------------------------------------

    def start(self) -> None:
        """Begin capturing and transcribing. Raises if the backend is missing."""
        if self._recorder is not None:
            raise RuntimeError("LiveSession already started")
        os.makedirs(self.work_dir, exist_ok=True)
        self.recording_path = os.path.join(self.work_dir, "live-session.wav")
        self._stopping.clear()
        self._capture_done.clear()
        self._started_at = time.monotonic()
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
            self._capture_done.set()
            self._put_sentinel()
            raise
        self._recorder = rec
        self._emit(LiveEvent(kind="state", detail="started"))

    def stop(self, *, timeout: float = 10.0) -> str:
        """Stop capture, transcribe the tail, and return the recording path.

        Blocking teardown (app exit): waits at most ``timeout`` for the
        backlog. The Stop button uses :meth:`stop_capture` +
        :meth:`wait_drained` instead, so a slow model finishes every
        chunk rather than losing them after a fixed timeout.
        """
        self.stop_capture()
        self.wait_drained(timeout=timeout)
        return self.recording_path

    def stop_capture(self) -> str:
        """Stop the microphone now and queue the tail; returns immediately.

        Chunks already queued keep transcribing on the consumer thread;
        follow with :meth:`wait_drained` (and optionally
        :meth:`discard_pending`).
        """
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
        self._capture_done.set()
        self._put_sentinel()
        if rec is not None and rec.last_error:
            self._emit(LiveEvent(kind="error", detail=rec.last_error))
        return self.recording_path

    def wait_drained(self, timeout: float | None = None) -> bool:
        """Block until every queued chunk is transcribed (or discarded).

        Returns True once the consumer has finished; False on timeout.
        Emits the single "stopped" state event when it finishes.
        """
        consumer = self._consumer
        if consumer is not None and consumer.is_alive():
            consumer.join(timeout=timeout)
            if consumer.is_alive():
                return False
        with self._lock:
            if self._stopped_emitted:
                return True
            self._stopped_emitted = True
        self._emit(LiveEvent(kind="state", detail="stopped"))
        return True

    def discard_pending(self) -> int:
        """Drop every chunk still waiting; returns how many were dropped.

        The chunk being transcribed right now is not interrupted here --
        the caller stops the worker for that -- but its failure is then
        swallowed rather than reported as an error.
        """
        self._discard.set()
        dropped = 0
        while True:
            try:
                item = self._chunks.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                dropped += 1
                with self._lock:
                    self._queued = max(0, self._queued - 1)
        self._put_sentinel()
        return dropped

    def pending_chunks(self) -> int:
        """Chunks not yet transcribed, including the one in progress."""
        with self._lock:
            return self._queued + (1 if self._busy else 0)

    def _put_sentinel(self) -> None:
        """Wake the consumer so it notices ``_capture_done``. Never blocks.

        A full queue needs no sentinel: the consumer is about to take a
        real chunk and checks the flag when the queue runs dry. Blocking
        here froze the window at exit when the consumer sat in a slow
        chunk (``stop_capture`` runs on the Tk thread then).
        """
        try:
            self._chunks.put_nowait(None)
        except queue.Full:
            pass

    def is_running(self) -> bool:
        rec = self._recorder
        return rec is not None and rec.is_running()

    @property
    def last_error(self) -> Optional[str]:
        """The capture backend's last error (None while all is well)."""
        rec = self._recorder
        return rec.last_error if rec is not None else None

    def capture_error(self) -> str:
        """Why capture ended on its own, or "" while it runs / after Stop.

        A microphone that cannot be opened, or one unplugged mid-session,
        ends the capture thread; nothing else tells the UI, which kept
        showing "Listening..." over a flat meter. The tab polls this.
        """
        rec = self._recorder
        if rec is None or self._stopping.is_set() or rec.is_running():
            return ""
        return rec.last_error or "The audio device stopped sending sound."

    def input_signal_state(self, *, grace_s: float = 5.0,
                           now: Optional[float] = None) -> str:
        """``"ok"``, ``"no_audio"`` (no blocks at all) or ``"silent"``.

        ``"silent"`` = only exact digital zeros for ``grace_s``: a muted
        device, or an OS that denied microphone access and delivers
        silence instead of an error. A real microphone always has some
        noise. Microphone only: silence on system audio is normal, and
        WASAPI loopback delivers nothing at all while nothing plays.
        """
        if self.mode != "mic" or not self.is_running():
            return "ok"
        now = time.monotonic() if now is None else now
        with self._lock:
            started = self._started_at
            last_frames = self._last_frames_at
            last_signal = self._last_signal_at
        if now - started < grace_s:
            return "ok"
        if not last_frames:
            return "no_audio"
        if now - (last_signal or started) >= grace_s:
            return "silent"
        return "ok"

    def finish_recording(self) -> str:
        """Delete this session's audio files unless the recording is kept.

        Returns the kept recording's path, else "". Leftover chunk WAVs
        always go. Only files this session wrote are touched, then the
        folder if it is empty. While the capture thread still runs (a
        WASAPI loopback read can block ~49 s when nothing plays) or the
        consumer still transcribes a chunk, nothing is touched now: a
        background thread waits up to ``defer_s`` for both to end and
        cleans up then (a kept recording's path is still returned).
        """
        if self._threads_alive():
            threading.Thread(
                target=self._finish_when_idle, name="live-cleanup", daemon=True
            ).start()
            if self.keep_recording and os.path.isfile(self.recording_path):
                return self.recording_path
            return ""
        return self._finish_now()

    #: How long a deferred :meth:`finish_recording` waits for the threads.
    defer_s: float = 300.0

    def _threads_alive(self) -> bool:
        rec = self._recorder
        consumer = self._consumer
        return bool((rec is not None and rec.is_running())
                    or (consumer is not None and consumer.is_alive()))

    def _finish_when_idle(self) -> None:
        deadline = time.monotonic() + self.defer_s
        while self._threads_alive():
            if time.monotonic() >= deadline:
                logger.warning("Live threads still running; keeping %s", self.work_dir)
                return
            time.sleep(0.25)
        kept = self._finish_now()
        if kept:
            logger.info("Live session audio kept at %s", kept)

    def _finish_now(self) -> str:
        work = self.work_dir
        try:
            names = os.listdir(work)
        except OSError:
            return ""
        for name in names:
            if name.startswith("chunk-") and name.endswith(".wav"):
                _remove_quietly(os.path.join(work, name))
        kept = ""
        if self.recording_path and os.path.isfile(self.recording_path):
            if self.keep_recording:
                kept = self.recording_path
            else:
                _remove_quietly(self.recording_path)
        if not kept:
            try:
                os.rmdir(work)
            except OSError:
                pass  # not empty (foreign files) or already gone
        return kept

    # ---------- capture side (runs on the recorder's thread) ---------

    def _on_frames(self, pcm: bytes, rate: int) -> None:
        if self._stopping.is_set():
            return
        rate = int(rate) or self.config.sample_rate
        meter = self.on_meter
        if meter is not None and pcm:
            try:
                meter(pcm, rate)
            except Exception:  # noqa: BLE001
                logger.exception("Live meter sink raised; continuing capture")
        now = time.monotonic()
        # Any non-zero byte means real signal; a muted or permission-
        # denied device delivers exact zeros (see input_signal_state).
        has_signal = bool(pcm.strip(b"\x00"))
        with self._lock:
            self._last_frames_at = now
            if has_signal:
                self._last_signal_at = now
            # Everything downstream counts samples at config.sample_rate:
            # resample a 44.1/48 kHz device once, here.
            conv = self._resampler
            if conv is None or conv.src_rate != rate:
                conv = self._resampler = RateConverter(rate, self.config.sample_rate)
            chunks = self._segmenter.feed(conv.convert(pcm))
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
        item = (seq, pcm, start_s, self.config.sample_rate)
        try:
            self._chunks.put_nowait(item)
            with self._lock:
                self._queued += 1
            return
        except queue.Full:
            pass
        # Behind real time. Drop the OLDEST pending chunk: the newest
        # audio is what the user is watching for, and silently growing
        # the backlog would drift further behind with every chunk.
        try:
            if self._chunks.get_nowait() is not None:
                self.dropped_chunks += 1
                with self._lock:
                    self._queued = max(0, self._queued - 1)
        except queue.Empty:
            pass
        try:
            self._chunks.put_nowait(item)
            with self._lock:
                self._queued += 1
        except queue.Full:
            self.dropped_chunks += 1
            return
        self._emit(LiveEvent(
            kind="warning",
            detail=(
                f"Transcription is behind the audio; {self.dropped_chunks} "
                f"chunk(s) skipped. Pick a faster model in the Model list."
            ),
        ))

    # ---------- transcribe side (its own thread) ---------------------

    def _consume(self) -> None:
        while True:
            try:
                item = self._chunks.get(timeout=0.25)
            except queue.Empty:
                item = None
            if item is None:
                # Sentinel or idle tick: end once capture is over and the
                # backlog is empty, never earlier (the tail may still be
                # on its way in).
                if self._capture_done.is_set() and self._chunks.empty():
                    return
                continue
            with self._lock:
                self._queued = max(0, self._queued - 1)
                self._busy = True
            try:
                self._consume_one(item)
            finally:
                with self._lock:
                    self._busy = False

    def _consume_one(self, item: tuple[int, bytes, float, int]) -> None:
        seq, pcm, start_s, rate = item
        if self._discard.is_set():
            return
        path = os.path.join(self.work_dir, f"chunk-{seq:06d}.wav")
        try:
            write_wav(path, pcm, rate)
        except OSError as e:
            self._chunk_failed(f"Chunk write failed: {e}")
            return
        try:
            result = self.transcribe_chunk(path)
        except Exception as e:  # noqa: BLE001
            if self._discard.is_set():
                # The user chose to discard the rest; the worker was
                # stopped under this chunk on purpose.
                return
            # One failed chunk must not end the session.
            logger.exception("Live chunk transcription failed: %s", e)
            self._chunk_failed(str(e))
            return
        finally:
            _remove_quietly(path)
        self._consecutive_errors = 0
        text, language = _result_text(result)
        if not text:
            return
        self._emit(LiveEvent(
            kind="text",
            text=text,
            start=start_s,
            end=start_s + (len(pcm) / float(self.config.bytes_per_second())),
            language=language,
        ))

    def _chunk_failed(self, detail: str) -> None:
        """Report one failed chunk; after too many in a row, report death.

        A dead or wedged worker fails every chunk (the wedged one only
        after the per-chunk timeout), and the status line kept saying
        "Listening..." through all of it. The ``fatal`` event is sent
        once; the UI stops the session and shows ``detail``.
        """
        self._emit(LiveEvent(kind="error", detail=detail))
        self._consecutive_errors += 1
        if (self._consecutive_errors >= max(1, self.max_consecutive_errors)
                and not self._fatal_emitted):
            self._fatal_emitted = True
            self._emit(LiveEvent(kind="fatal", detail=detail))

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


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)


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
    import uuid

    from .config import user_cache_dir

    # The random suffix keeps two sessions started within one second (a
    # Stop then a quick Start) out of each other's folder.
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    return str(user_cache_dir() / "live" / name)
