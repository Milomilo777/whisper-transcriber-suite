"""Long Text to Voice jobs, written piece by piece.

A long text is split at sentence boundaries into pieces (:func:`split_text`).
Each finished piece is written as its own WAV file into a work folder next to
the final file, and a small progress file records which pieces are done. A
job that is cancelled, crashes or loses power therefore continues where it
stopped: the next run with the same text, voice and speed (:func:`job_key`)
skips the finished pieces. The final file is joined from the pieces only at
the end, tagged as AI-generated and checked; only then are the pieces removed
(finished work is on disk before anything reports "done").

Layout, under ``core.tts_plan.output_root()``::

    job-<key>/output.wav                      the final file (after the join)
    job-<key>/output.parts/progress.json      which pieces are done
    job-<key>/output.parts/piece-0001.wav     one WAV per finished piece

Tk-free and engine-free: :func:`run` takes a ``speak(text, path, progress)``
function from the caller (the tab wraps Kokoro or the OmniVoice worker).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import synthetic_audio, tts_plan

logger = logging.getLogger(__name__)

#: Largest piece (characters, outer spaces not counted) per engine. Kokoro
#: is fast (a 2,000-character piece is about two minutes of speech and a
#: minute or two of compute on a CPU). OmniVoice on a CPU needs about 20 s
#: per second of speech, so its pieces stay short: a crash or a Cancel loses
#: at most one piece (500 characters, about 30 s of speech).
PIECE_CHARS = {"kokoro": 2000, "omnivoice": 500}

#: Unfinished job folders are kept this long after their last finished piece
#: (finished outputs follow ``core.voice_clone.SCRATCH_MAX_AGE_DAYS``).
UNFINISHED_MAX_AGE_DAYS = 30.0

PARTS_DIR = "output.parts"
PROGRESS_FILE = "progress.json"
OUTPUT_FILE = "output.wav"
_PROGRESS_VERSION = 1
_COPY_FRAMES = 1 << 16
_MAX_RIFF_BYTES = 0xFFFFFFFF


# ------------------------------------------------------------------ splitting

# Sentence ends: final punctuation (Latin, Arabic, Devanagari, Urdu,
# Ethiopic, ...) plus closing quotes/brackets, followed by spaces; CJK
# full-width ends need no space; a line break always ends a segment.
_SENTENCE_END = re.compile(
    "(?:[.!?\u2026\u203c\u2047-\u2049\u061f\u0964\u0965\u06d4\u1362\u1367]+"
    "[\"'\u201d\u2019\u00bb)\\]}]*\\s+"
    "|[\u3002\uff01\uff1f]+[\"'\u201d\u2019\u300d\u300f)\uff09]*\\s*"
    "|\\n\\s*)"
)
# Clause punctuation a long sentence may be cut after.
_CLAUSE_END = re.compile("[,;:\u060c\u061b\u3001\uff0c\uff1b](?=\\s)|[\u3001\uff0c\uff1b]")


def _segments(text: str) -> "list[str]":
    """*text* cut after every sentence end; joining them gives *text* back."""
    out: list[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        if m.end() > start:
            out.append(text[start:m.end()])
            start = m.end()
    if start < len(text):
        out.append(text[start:])
    return out


def _continues_cluster(ch: str) -> bool:
    """True for a character that belongs to the one before it (a combining
    mark, a joiner, a variation selector, an emoji skin tone, a Hangul vowel
    or final jamo): a piece never starts with one."""
    cp = ord(ch)
    return (unicodedata.category(ch) in ("Mn", "Mc", "Me")
            or ch in ("\u200c", "\u200d")
            or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF
            or 0x1F3FB <= cp <= 0x1F3FF or 0x1160 <= cp <= 0x11FF
            or 0xD7B0 <= cp <= 0xD7FF)


def _joins_next(ch: str) -> bool:
    """True for a character that binds the NEXT one to it (a virama, which
    forms a conjunct, or a zero-width joiner): no cut right after it."""
    return ch == "\u200d" or unicodedata.combining(ch) == 9


def _hard_cut(rest: str, lead: int, limit: int) -> int:
    """The last position in (lead, limit] to cut a run with no space at:
    first one that splits no cluster or conjunct, else one that at least
    starts no piece with a mark, else *limit* (nothing but marks)."""
    for strict in (True, False):
        for i in range(limit, lead, -1):
            if not _continues_cluster(rest[i]) and not (strict and _joins_next(rest[i - 1])):
                return i
    return limit


def _split_long(seg: str, max_chars: int) -> "list[str]":
    """Cut one over-long segment after clause punctuation, else after a
    space, else (no space at all) at *max_chars* without splitting a
    character from its marks."""
    out: list[str] = []
    rest = seg
    while len(rest.strip()) > max_chars:
        lead = len(rest) - len(rest.lstrip())
        limit = lead + max_chars  # rest[lead:limit] is the most one piece holds
        cut = 0
        for m in _CLAUSE_END.finditer(rest, lead, limit):
            cut = m.end()
        if not cut:
            for j in range(min(limit, len(rest) - 1), lead, -1):
                if rest[j].isspace():
                    cut = j
                    break
        if not cut:
            cut = _hard_cut(rest, lead, limit)
        while cut < len(rest) and rest[cut].isspace():
            cut += 1  # spaces stay with the piece before them
        out.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        out.append(rest)
    return out


def split_text(text: str, max_chars: int) -> "list[str]":
    """Split *text* into pieces of at most *max_chars* characters each
    (outer spaces not counted), cut at sentence ends where possible.

    Lossless: ``"".join(split_text(t, n)) == t`` for every text. Spaces stay
    with the piece before them, so no piece is only spaces unless the whole
    text is.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    parts: list[str] = []
    for seg in _segments(text):
        parts.extend(_split_long(seg, max_chars))
    pieces: list[str] = []
    cur = ""
    for part in parts:
        if cur.strip() and part.strip() and len((cur + part).strip()) > max_chars:
            pieces.append(cur)
            cur = part
        else:
            cur += part
    if cur:
        pieces.append(cur)
    return pieces


# ------------------------------------------------------------------ identity


def job_key(engine: str, text: str, voice: "dict[str, object]", speed: float) -> str:
    """Identity of a job: the same text, engine, voice settings and speed
    give the same key, so the next run can continue an unfinished job."""
    payload = json.dumps(
        {"v": _PROGRESS_VERSION, "engine": engine, "text": text, "voice": voice,
         "speed": round(float(speed), 3), "piece_chars": PIECE_CHARS[engine]},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ the job


@dataclass(frozen=True)
class PieceDone:
    frames: int
    audio_seconds: float
    compute_seconds: float


def _wav_frames(path: Path) -> "tuple[int, tuple[int, int, int]]":
    """Frame count and (channels, sample width, rate) of a WAV file."""
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), (w.getnchannels(), w.getsampwidth(), w.getframerate())


def _write_json_atomic(path: Path, data: object) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        synthetic_audio._replace_with_retry(tmp, str(path))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


class Job:
    """One long text, its pieces and which of them are already on disk."""

    def __init__(self, root: "str | os.PathLike[str]", key: str, engine: str,
                 pieces: "list[str]") -> None:
        if not pieces:
            raise ValueError("a job needs at least one piece")
        self.key = key
        self.engine = engine
        self.pieces = list(pieces)
        self.folder = Path(root) / f"job-{key[:16]}"
        self.parts_dir = self.folder / PARTS_DIR
        self.progress_path = self.parts_dir / PROGRESS_FILE
        self.output_path = self.folder / OUTPUT_FILE
        self.units = [tts_plan.speech_units(p) for p in self.pieces]
        self.done: dict[int, PieceDone] = {}
        self._load()

    # ---------------------------------------------------------- progress

    def piece_path(self, index: int) -> Path:
        return self.parts_dir / f"piece-{index + 1:04d}.wav"

    def _load(self) -> None:
        """Take over the finished pieces of an earlier run of this job. A
        piece counts only when the progress file lists it and its WAV file
        is still there with the recorded length."""
        try:
            data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning("Ignoring an unreadable job progress file %s: %s", self.progress_path, e)
            return
        if (not isinstance(data, dict) or data.get("version") != _PROGRESS_VERSION
                or data.get("key") != self.key
                or data.get("pieces") != [_text_hash(p) for p in self.pieces]):
            return
        done = data.get("done")
        if not isinstance(done, dict):
            return
        for raw_index, raw in done.items():
            try:
                index = int(raw_index)
                rec = PieceDone(int(raw["frames"]), float(raw["audio_seconds"]),
                                float(raw["compute_seconds"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= index < len(self.pieces) or rec.frames <= 0:
                continue
            try:
                frames, _params = _wav_frames(self.piece_path(index))
            except (OSError, EOFError, wave.Error):
                continue
            if frames == rec.frames:
                self.done[index] = rec

    def _save(self) -> None:
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.progress_path, {
            "version": _PROGRESS_VERSION,
            "key": self.key,
            "engine": self.engine,
            "pieces": [_text_hash(p) for p in self.pieces],
            "done": {str(i): {"frames": d.frames, "audio_seconds": d.audio_seconds,
                              "compute_seconds": d.compute_seconds}
                     for i, d in sorted(self.done.items())},
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def record(self, index: int, compute_seconds: float) -> PieceDone:
        """Mark piece *index* as finished once its WAV file is on disk.
        Raises ``ValueError`` when the file holds no audio."""
        frames, (_ch, _width, rate) = _wav_frames(self.piece_path(index))
        if frames <= 0 or rate <= 0:
            raise ValueError(f"piece {index + 1} produced no audio")
        rec = PieceDone(frames, frames / float(rate), max(0.0, float(compute_seconds)))
        self.done[index] = rec
        self._save()
        return rec

    def pending(self) -> "list[int]":
        return [i for i in range(len(self.pieces)) if i not in self.done]

    @property
    def done_units(self) -> float:
        return sum(self.units[i] for i in self.done)

    @property
    def done_compute(self) -> float:
        return sum(d.compute_seconds for d in self.done.values())

    @property
    def total_units(self) -> float:
        return sum(self.units)

    def discard(self) -> None:
        """Forget the finished pieces (Start over)."""
        self.done.clear()
        shutil.rmtree(self.parts_dir, ignore_errors=True)

    # ---------------------------------------------------------- join

    def join(self) -> Path:
        """Join every piece into :attr:`output_path`, tag it as AI-generated,
        check its length, and only then remove the pieces. Raises when a
        piece is missing or differs in format; the pieces stay on disk."""
        if self.pending():
            raise RuntimeError(f"{len(self.pending())} piece(s) are not finished yet")
        params = None
        total_frames = 0
        for i in range(len(self.pieces)):
            frames, p = _wav_frames(self.piece_path(i))
            if frames != self.done[i].frames:
                raise RuntimeError(f"piece {i + 1} changed on disk")
            if params is None:
                params = p
            elif p != params:
                raise RuntimeError(f"piece {i + 1} has another audio format than piece 1")
            total_frames += frames
        assert params is not None
        channels, width, rate = params
        for stale in (*self.folder.glob(".join-*.wav"), *self.folder.glob(".tag-*.tmp")):
            try:  # left by a join that was killed half-way
                stale.unlink()
            except OSError:
                pass
        if total_frames * channels * width + 8192 > _MAX_RIFF_BYTES:
            raise RuntimeError("The speech is too long for one WAV file (over 4 GB). "
                               f"The finished pieces are kept in {self.parts_dir}.")
        fd, tmp = tempfile.mkstemp(prefix=".join-", suffix=".wav", dir=self.folder)
        os.close(fd)
        try:
            with wave.open(tmp, "wb") as out:
                out.setnchannels(channels)
                out.setsampwidth(width)
                out.setframerate(rate)
                for i in range(len(self.pieces)):
                    with wave.open(str(self.piece_path(i)), "rb") as src:
                        while True:
                            block = src.readframes(_COPY_FRAMES)
                            if not block:
                                break
                            out.writeframes(block)
            synthetic_audio.tag_wav(tmp)
            frames, _p = _wav_frames(Path(tmp))
            if frames != total_frames:
                raise RuntimeError(f"joined file has {frames} frames, expected {total_frames}")
            if synthetic_audio.read_info(tmp).get("ICMT") != synthetic_audio.AI_COMMENT:
                raise RuntimeError("joined file lost its AI-generated tag")
            synthetic_audio._replace_with_retry(tmp, str(self.output_path))
            with open(self.output_path, "rb+") as f:
                os.fsync(f.fileno())  # on disk before the pieces go
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        # The final file is complete and checked: the pieces can go.
        shutil.rmtree(self.parts_dir, ignore_errors=True)
        return self.output_path


def open_job(engine: str, text: str, voice: "dict[str, object]", speed: float,
             root: "str | os.PathLike[str] | None" = None) -> Job:
    """The job for this text, voice and speed, with the pieces an earlier run
    already finished (none for a new job)."""
    key = job_key(engine, text, voice, speed)
    return Job(root if root is not None else tts_plan.output_root(), key, engine,
               split_text(text, PIECE_CHARS[engine]))


def is_unfinished_job_dir(folder: Path) -> bool:
    return (folder / PARTS_DIR / PROGRESS_FILE).is_file()


# ------------------------------------------------------------------ running


@dataclass(frozen=True)
class Progress:
    pieces_done: int
    pieces_total: int
    #: Share of the job's speech units finished, 0..1.
    fraction: float
    #: Seconds left from the speed measured so far (None: nothing measured yet).
    seconds_left: "float | None"


@dataclass(frozen=True)
class RunResult:
    output_path: str
    #: Speech length of the whole final file.
    audio_seconds: float
    #: What this run did (earlier runs of a continued job not included).
    pieces_run: int
    units_run: float
    audio_seconds_run: float
    compute_seconds_run: float


class Cancelled(RuntimeError):
    """The job was cancelled between pieces; finished pieces are kept."""


#: ``speak(text, path, on_fraction) -> compute seconds``: write one piece's
#: WAV to *path*; *on_fraction* takes 0..1 progress within the piece.
SpeakFn = Callable[[str, str, Callable[[float], None]], float]


def seconds_left(job: Job, piece_units: float = 0.0, piece_fraction: float = 0.0,
                 piece_elapsed: float = 0.0,
                 fallback_per_unit: "float | None" = None) -> "float | None":
    """Time left from the speed measured so far on this job: compute seconds
    per speech unit of the finished pieces (and the running one), times the
    units still to speak. *fallback_per_unit* is used until a piece is done."""
    units = job.done_units + piece_units * piece_fraction
    compute = job.done_compute + piece_elapsed
    remaining = max(0.0, job.total_units - units)
    if job.done and units > 0 and compute > 0:
        return remaining * compute / units
    if fallback_per_unit is not None:
        return remaining * fallback_per_unit
    return None


def run(job: Job, speak: SpeakFn, *,
        cancel_event: "threading.Event | None" = None,
        on_progress: "Callable[[Progress], None] | None" = None,
        fallback_per_unit: "float | None" = None,
        clock: Callable[[], float] = time.monotonic) -> RunResult:
    """Speak every unfinished piece of *job*, then join the final file.

    Each piece is recorded in the progress file as soon as its WAV is on
    disk. Raises :class:`Cancelled` when *cancel_event* is set between
    pieces; any error from *speak* propagates. Either way the finished
    pieces stay for the next run.
    """
    def is_cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def report(index: "int | None" = None, frac: float = 0.0, elapsed: float = 0.0) -> None:
        if on_progress is None:
            return
        piece_units = job.units[index] if index is not None else 0.0
        total = job.total_units or 1.0
        on_progress(Progress(
            pieces_done=len(job.done), pieces_total=len(job.pieces),
            fraction=min(1.0, (job.done_units + piece_units * frac) / total),
            seconds_left=seconds_left(job, piece_units, frac, elapsed, fallback_per_unit)))

    pieces_run = 0
    units_run = audio_run = compute_run = 0.0
    report()
    for index in job.pending():
        if is_cancelled():
            raise Cancelled(f"{len(job.done)} of {len(job.pieces)} pieces finished")
        path = job.piece_path(index)
        path.parent.mkdir(parents=True, exist_ok=True)
        t0 = clock()

        def on_fraction(frac: float, _i: int = index, _t0: float = t0) -> None:
            report(_i, max(0.0, min(1.0, float(frac))), clock() - _t0)

        # Outer spaces carry no speech, and a long run of blank lines must
        # not push a piece past the engine's one-pass limit.
        compute = speak(job.pieces[index].strip(), str(path), on_fraction)
        # A piece that came back whole is kept even when Cancel was pressed
        # meanwhile: the check at the top of the loop stops the next one.
        rec = job.record(index, compute)
        pieces_run += 1
        units_run += job.units[index]
        audio_run += rec.audio_seconds
        compute_run += rec.compute_seconds
        report()
    total_audio = sum(d.audio_seconds for d in job.done.values())
    output = job.join()
    return RunResult(str(output), total_audio, pieces_run, units_run, audio_run, compute_run)
