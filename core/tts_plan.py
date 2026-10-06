"""Planning a Text to Voice job before it starts.

The Clone Your Voice / Text to Voice tab runs two engines, Kokoro
(``core.tts_kokoro``) and OmniVoice (``core.voice_clone``). This module
holds what both share before a job starts:

* the length limits for one job and one generation pass
  (:data:`MAX_TEXT_CHARS`, :data:`MAX_PASS_CHARS`, :func:`text_limit`);
* the estimate shown before a long job: how long it takes on this computer,
  how long the speech is, how big the WAV file gets (:func:`estimate`);
* the free-disk check that refuses a job the disk cannot hold
  (:func:`check_disk`);
* the per-computer speed measurement ("calibration") the time estimate comes
  from, stored in ``<user cache>/tts/speed_calibration.json``.

A speed figure is stored per engine and device, with the engine version and
a hardware fingerprint. When either no longer matches, the stored figure is
ignored, so the next long job measures again. A figure comes from the short
measuring run the tab offers (Kokoro, a few seconds) or from any finished
real job with enough speech to measure (both engines). OmniVoice has no
separate measuring run: on a CPU even one short sentence takes over a
minute, so its first real job is its measurement.

Tk-free and model-free: the engines produce the numbers, this module does
the maths and the storage.
"""
from __future__ import annotations

import json
import logging
import math
import os
import platform
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The cap on how much text one job accepts, for both engines: about 90
#: minutes of speech (a WAV of about 265 MB). A long job is spoken piece by
#: piece (``core.tts_job``), so memory stays flat and a cancelled or
#: interrupted job continues where it stopped. The advanced setting
#: :data:`NO_LIMIT_KEY` lifts it.
MAX_TEXT_CHARS = 100_000

#: The cap on one generation pass (one call into an engine). Pieces of a
#: long job are far shorter; OmniVoice's voice design and own-voice modes
#: speak in a single pass, because every pass would pick a new voice.
MAX_PASS_CHARS = 5000

#: Local-only config key (``core.config.LOCAL_ONLY_KEYS``): True lifts
#: :data:`MAX_TEXT_CHARS`. The estimate, the free-disk check and the
#: piece-by-piece writer still apply.
NO_LIMIT_KEY = "tts_no_text_limit"

#: The largest file a WAV header can describe (4 GB, about 24 hours of speech).
MAX_WAV_BYTES = 0xFFFFFFFF

#: Both engines write 24 kHz, 16-bit, mono WAV files.
SAMPLE_RATE = 24000
BYTES_PER_AUDIO_SECOND = SAMPLE_RATE * 2
#: RIFF header plus the AI-generated LIST/INFO tag (core.synthetic_audio).
WAV_OVERHEAD_BYTES = 4096

#: Kept free on top of the file itself, so a long job never fills the disk
#: the system, the page file and other programs also write to.
DISK_MARGIN_BYTES = 500 * 1024 * 1024

#: Texts up to this many speech units (see :func:`speech_units`) never get
#: the confirm step; nor does any job whose high time estimate is under
#: :data:`CONFIRM_ABOVE_SECONDS`.
SHORT_TEXT_UNITS = 300
CONFIRM_ABOVE_SECONDS = 120.0

#: Speech units per second of audio at speed 1.0 before anything was
#: measured on this computer (English: Kokoro ~18, OmniVoice ~16-18).
DEFAULT_UNITS_PER_SECOND = 16.0

#: Spread of the speech length: speaking rate varies with the language,
#: the voice and the punctuation.
AUDIO_LOW_FACTOR = 0.8
AUDIO_HIGH_FACTOR = 1.25
#: Spread of the compute time: measured on this computer, or the
#: reference computer's figure when this one has not been measured yet.
MEASURED_TIME_FACTORS = (0.85, 1.25)
REFERENCE_TIME_FACTORS = (0.5, 2.5)

#: Text the measuring run speaks (about 10 s of speech).
CALIBRATION_TEXT = (
    "The library opens at nine in the morning and closes at six in the "
    "evening. Visitors can borrow up to five books at a time, and most of "
    "them come back within two weeks."
)

_STORE_VERSION = 1


@dataclass(frozen=True)
class EngineProfile:
    #: A generation pass shorter than this costs about as much as one this
    #: long: OmniVoice runs a fixed number of decoding steps per pass, so a
    #: one-word text still takes over a minute on a CPU.
    min_pass_seconds: float
    #: Compute seconds per second of speech on the reference computer (a
    #: 4-core / 8-thread desktop CPU), per device. A device without an
    #: entry has no figure until it is measured.
    reference_ratio: "dict[str, float]"


ENGINES: "dict[str, EngineProfile]" = {
    # fp32 model through sherpa-onnx: 0.62-0.66 s per second of speech.
    "kokoro": EngineProfile(min_pass_seconds=0.0, reference_ratio={"cpu": 0.7}),
    # 17.6-21.2 s per second of speech for passes of 4.9-9.9 s; a 1.8 s
    # pass took 81 s, about as long as a 4.9 s one.
    "omnivoice": EngineProfile(min_pass_seconds=4.0, reference_ratio={"cpu": 21.0}),
}


def text_limit(config: "dict | None") -> "int | None":
    """The job length limit under *config* (None: the advanced
    :data:`NO_LIMIT_KEY` setting is on, no limit)."""
    if config is not None and config.get(NO_LIMIT_KEY) is True:
        return None
    return MAX_TEXT_CHARS


def min_calibration_audio(engine: str) -> float:
    """Shortest speech (seconds) a run must produce to count as a measurement:
    shorter runs are dominated by fixed costs, not by speed."""
    return max(5.0, 2.0 * ENGINES[engine].min_pass_seconds)


# ------------------------------------------------------------------ text


def _unit_weight(ch: str) -> float:
    """How many Latin letters' worth of speech one character takes."""
    cp = ord(ch)
    if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2FFFF):
        return 3.0  # Han: one syllable per character
    if 0xAC00 <= cp <= 0xD7AF:
        return 2.5  # Hangul syllable block
    if 0x3040 <= cp <= 0x30FF:
        return 2.0  # Hiragana / Katakana: one mora per character
    return 1.0


def speech_units(text: str) -> float:
    """Length of *text* in Latin-letter equivalents.

    Runs of whitespace count once, so line breaks and indentation do not
    lengthen the estimate; Chinese, Japanese and Korean characters count
    more than one letter each, since each is a whole syllable or mora.
    """
    units = 0.0
    in_space = False
    for ch in text.strip():
        if ch.isspace():
            if not in_space:
                units += 1.0
            in_space = True
            continue
        in_space = False
        units += _unit_weight(ch)
    return units


# ------------------------------------------------------------------ calibration


@dataclass(frozen=True)
class Calibration:
    engine: str
    device: str
    engine_version: str
    hardware: str
    units: float
    audio_seconds: float
    compute_seconds: float
    speed: float
    #: "check" (the measuring run) or "run" (a finished real job).
    source: str
    measured_at: str

    @property
    def ratio(self) -> float:
        """Compute seconds per second of speech."""
        pass_seconds = max(self.audio_seconds, ENGINES[self.engine].min_pass_seconds)
        return self.compute_seconds / pass_seconds

    @property
    def units_per_second(self) -> float:
        """Speech units per second of audio at speed 1.0."""
        return self.units / (self.audio_seconds * self.speed)


def calibration_path() -> Path:
    from .config import user_cache_dir

    return user_cache_dir() / "tts" / "speed_calibration.json"


def _key(engine: str, device: str) -> str:
    return f"{engine}/{device}"


def _read_store(path: Path) -> "dict[str, dict]":
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable speed calibration file %s: %s", path, e)
        return {}
    if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _valid_number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def load_calibration(
    engine: str, device: str, engine_version: str, hardware: str,
    path: "Path | None" = None,
) -> "Calibration | None":
    """The stored speed figure for *engine* on *device*, or None when there
    is none, it is damaged, or it was measured with another engine version
    or on other hardware (so the next long job measures again)."""
    if engine not in ENGINES:
        return None
    raw = _read_store(path or calibration_path()).get(_key(engine, device))
    if not isinstance(raw, dict):
        return None
    try:
        cal = Calibration(**raw)
    except TypeError:
        return None
    if (cal.engine, cal.device) != (engine, device):
        return None
    if cal.engine_version != engine_version or cal.hardware != hardware:
        return None
    if not all(_valid_number(v) for v in
               (cal.units, cal.audio_seconds, cal.compute_seconds, cal.speed)):
        return None
    try:
        derived = (cal.ratio, cal.units_per_second)
    except (ZeroDivisionError, OverflowError):
        return None
    if not all(_valid_number(v) for v in derived):
        return None  # a hand-edited file with absurd numbers: measure again
    return cal


def record_measurement(
    engine: str, device: str, engine_version: str, hardware: str, *,
    units: float, audio_seconds: float, compute_seconds: float,
    speed: float = 1.0, source: str = "run", path: "Path | None" = None,
) -> "Calibration | None":
    """Store one measurement as the speed figure for *engine* on *device*.

    Returns the stored :class:`Calibration`, or None (nothing written) when
    the run was too short to measure speed (:func:`min_calibration_audio`)
    or a number is not usable. Raises ``OSError`` when the file cannot be
    written.
    """
    if engine not in ENGINES:
        return None
    if not all(_valid_number(v) for v in (units, audio_seconds, compute_seconds, speed)):
        return None
    if audio_seconds < min_calibration_audio(engine):
        return None
    cal = Calibration(
        engine=engine, device=device, engine_version=engine_version,
        hardware=hardware, units=float(units), audio_seconds=float(audio_seconds),
        compute_seconds=float(compute_seconds), speed=float(speed), source=source,
        measured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    target = path or calibration_path()
    entries = _read_store(target)
    entries[_key(engine, device)] = asdict(cal)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A unique temp name per writer, so two app windows never write the
    # same temp file; the replace keeps the store whole for every reader.
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": _STORE_VERSION, "entries": entries}, f,
                      indent=2, sort_keys=True)
        os.replace(tmp, target)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return cal


def hardware_fingerprint(device: str) -> str:
    """What a stored speed figure is only valid for: OS, CPU, thread count
    and, for a CUDA device, the graphics card."""
    parts = [platform.system(), platform.machine(), platform.processor() or "unknown CPU",
             f"{os.cpu_count() or 0} threads"]
    if device.startswith("cuda"):
        gpu = "unknown GPU"
        torch = sys.modules.get("torch")  # only asked once the engine imported it
        if torch is not None:
            try:
                gpu = str(torch.cuda.get_device_name(0))
            except Exception:  # noqa: BLE001 -- a broken CUDA setup still gets a fingerprint
                pass
        parts.append(gpu)
    return " / ".join(parts)


def engine_version(engine: str) -> str:
    """Model and library versions a speed figure depends on."""
    from importlib import metadata

    def ver(dist: str) -> str:
        try:
            return f"{dist} {metadata.version(dist)}"
        except metadata.PackageNotFoundError:
            return f"{dist} missing"
        except Exception:  # noqa: BLE001 -- a broken install still gets a stable string
            return f"{dist} unknown"

    if engine == "kokoro":
        from .tts_kokoro import MODEL_NAME

        return f"{MODEL_NAME}; {ver('sherpa-onnx')}"
    if engine == "omnivoice":
        from . import optional_deps

        optional_deps.activate()  # OmniVoice and torch may live in the extras dir
        return f"{ver('omnivoice')}; {ver('torch')}"
    raise ValueError(f"Unknown engine: {engine}")


# ------------------------------------------------------------------ estimate


@dataclass(frozen=True)
class Estimate:
    units: float
    audio_low: float
    audio_high: float
    #: None: no figure for this engine and device until a run measures it.
    time_low: "float | None"
    time_high: "float | None"
    #: True when the time comes from this computer, False for the
    #: reference computer's figure (or no figure at all).
    measured: bool
    size_low: int
    size_high: int


def _compute_seconds(audio_seconds: float, ratio: float, profile: EngineProfile) -> float:
    return max(audio_seconds, profile.min_pass_seconds) * ratio


def estimate(
    text: str, engine: str, device: str,
    calibration: "Calibration | None" = None, speed: float = 1.0,
) -> Estimate:
    """Speech length, compute time and WAV size for speaking *text*."""
    profile = ENGINES[engine]
    speed = speed if _valid_number(speed) else 1.0
    units = speech_units(text)
    ups = calibration.units_per_second if calibration is not None else DEFAULT_UNITS_PER_SECOND
    audio_mid = units / ups / speed
    audio_low = audio_mid * AUDIO_LOW_FACTOR
    audio_high = audio_mid * AUDIO_HIGH_FACTOR
    if calibration is not None:
        ratio: "float | None" = calibration.ratio
        lo, hi = MEASURED_TIME_FACTORS
    else:
        ratio = profile.reference_ratio.get(device.split(":", 1)[0])
        lo, hi = REFERENCE_TIME_FACTORS
    time_low = time_high = None
    if ratio is not None:
        time_low = _compute_seconds(audio_low, ratio, profile) * lo
        time_high = _compute_seconds(audio_high, ratio, profile) * hi
    return Estimate(
        units=units, audio_low=audio_low, audio_high=audio_high,
        time_low=time_low, time_high=time_high, measured=calibration is not None,
        size_low=int(audio_low * BYTES_PER_AUDIO_SECOND) + WAV_OVERHEAD_BYTES,
        size_high=int(math.ceil(audio_high * BYTES_PER_AUDIO_SECOND)) + WAV_OVERHEAD_BYTES,
    )


def needs_confirm(est: Estimate) -> bool:
    """True when a job is long enough to show the confirm step first."""
    if est.units <= SHORT_TEXT_UNITS:
        return False
    return est.time_high is None or est.time_high >= CONFIRM_ABOVE_SECONDS


# ------------------------------------------------------------------ disk


@dataclass(frozen=True)
class DiskCheck:
    folder: str
    free_bytes: int
    need_bytes: int
    margin_bytes: int

    @property
    def ok(self) -> bool:
        return self.free_bytes >= self.need_bytes + self.margin_bytes


def output_root() -> Path:
    """Where the tab writes its WAV files (``core.voice_clone.session_work_dir``)."""
    from .config import user_cache_dir

    return user_cache_dir() / "voice_clone"


def free_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def check_disk(est: Estimate, folder: "str | os.PathLike[str] | None" = None,
               need_bytes: "int | None" = None) -> DiskCheck:
    """Free space where the output goes against the largest file *est* allows
    (or *need_bytes*) plus :data:`DISK_MARGIN_BYTES`. Asks the nearest
    existing parent when the folder does not exist yet."""
    target = Path(folder) if folder is not None else output_root()
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return DiskCheck(folder=str(target), free_bytes=free_bytes(probe),
                     need_bytes=est.size_high if need_bytes is None else int(need_bytes),
                     margin_bytes=DISK_MARGIN_BYTES)


def piece_job_need_bytes(est: Estimate, remaining_fraction: float = 1.0) -> int:
    """Free disk a piece-by-piece job needs at its peak: the pieces still to
    write, plus the joined file and its tagged copy, which both exist next to
    all the pieces for a moment before the pieces are removed."""
    return int(math.ceil(est.size_high * (2.0 + max(0.0, min(1.0, remaining_fraction)))))


# ------------------------------------------------------------------ wording


def _minutes(seconds: float) -> int:
    return max(1, int(round(seconds / 60.0)))


def _hours(seconds: float) -> str:
    h = seconds / 3600.0
    return f"{h:.0f}" if h >= 10 else f"{h:.1f}".rstrip("0").rstrip(".")


def format_duration_range(low: float, high: float) -> str:
    """'under a minute', '12-18 minutes', '1.5-3 hours', '40 minutes to 2 hours'."""
    if high < 60:
        return "under a minute"
    lo_m = _minutes(low)
    minutes = "minute" if lo_m == 1 else "minutes"
    if high < 3600:
        hi_m = _minutes(high)
        if lo_m >= hi_m:
            return f"about {hi_m} minute{'s' if hi_m != 1 else ''}"
        return f"{lo_m}–{hi_m} minutes"
    hi_h = _hours(high)
    hours = "hour" if hi_h == "1" else "hours"
    if low >= 3600 or lo_m >= 60:
        lo_h = _hours(low)
        return f"about {hi_h} {hours}" if lo_h == hi_h else f"{lo_h}–{hi_h} {hours}"
    return f"{lo_m} {minutes} to {hi_h} {hours}"


_UNDER_1_MB = "less than 1 MB"


def format_size(num_bytes: float) -> str:
    mb = num_bytes / (1024 * 1024)
    if mb < 1:
        return _UNDER_1_MB
    if mb < 1000:
        return f"{mb:.0f} MB"
    return f"{mb / 1024:.1f} GB"


def format_size_range(low: float, high: float) -> str:
    lo, hi = format_size(low), format_size(high)
    if hi == _UNDER_1_MB:
        return hi
    if lo == _UNDER_1_MB:
        return f"up to {hi}"
    if lo == hi:
        return f"about {hi}"
    if lo.endswith(" MB") and hi.endswith(" MB"):
        return f"{lo[:-3]}–{hi}"
    return f"{lo} to {hi}"
