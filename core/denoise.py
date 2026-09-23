"""Adaptive audio denoise pre-process (ffmpeg-only, no new dependency).

Noise is the single biggest driver of Whisper hallucination and WER on
real-world material (field recordings, phone audio, low-bitrate
downloads, HVAC hum, mic hiss). This module cleans the signal *before*
the ASR backend sees it.

Unlike a fixed "denoise level 0-2" knob, the pipeline here is
**measure -> decide -> apply -> verify**:

  1. :func:`analyze`  samples the source with ffmpeg ``astats`` and
     estimates the speech-to-noise ratio. Long files are sampled at
     three positions rather than scanned end-to-end, so the cost is
     bounded regardless of duration.
  2. :func:`decide_level` maps that SNR onto ``off/light/medium/strong``.
     **Audio that measures clean is left completely untouched** — this
     matters, because Whisper was trained on noisy web audio and
     over-denoising a clean file introduces artefacts the model has
     never heard and makes transcripts *worse*.
  3. :func:`build_filter_chain` parameterises the filters with the
     *measured* noise floor instead of a hard-coded guess.
  4. :func:`verdict` re-measures the result and **reverts to the
     original audio** if the filter ate speech instead of noise.

Why step 4 exists: a naive implementation grades itself with SNR, which
an over-aggressive filter can trivially fake — driving the noise floor
to digital silence scores "infinite SNR" while gutting the signal. The
guards below therefore watch *speech-band energy* and *entropy*, and the
allowance scales with the measured input SNR (removing genuine noise
from a genuinely noisy file legitimately lowers total energy; removing
it from a clean file does not).

Behaviour contract, mirroring :mod:`core.separator`:

  * disabled, ffmpeg missing, analysis failed, filter failed, or the
    result failed verification  ->  return the input path unchanged.
  * Never raises. The caller always gets a usable audio path.

Cached outputs live under ``user_cache_dir()/denoise`` with a byte
budget, same eviction shape as the demucs stem cache.

Tuning provenance
-----------------
Every threshold below was calibrated against measured ffmpeg output
(synthetic tone sweeps *and* real speech at seven noise levels), not
picked by feel. See ``docs/DENOISE.md`` for the measurements.

.. warning::
   Do **not** add ``anlmdn`` to any chain. It segfaults
   non-deterministically in the bundled ffmpeg build (identical
   arguments crash one run and succeed the next); with it removed the
   strong chain survived 20/20 repeats. ``tests/core/test_denoise.py``
   guards against it being reintroduced.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ._liveness_tick import liveness_tick
from ._proc import new_session_kwargs
from .config import user_cache_dir
from .paths import bundled_binary

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- constants

LEVELS: tuple[str, ...] = ("off", "light", "medium", "strong")
LEVEL_CHOICES: tuple[str, ...] = ("auto",) + LEVELS

#: SNR at or above which audio is treated as already clean and left alone.
SNR_CLEAN_DB = 30.0
#: SNR boundaries for the light / medium bands (below medium -> strong).
SNR_LIGHT_DB = 20.0
SNR_MEDIUM_DB = 10.0

#: ``afftdn``'s ``nf`` (noise floor) parameter only accepts this range.
NF_MIN_DB = -80.0
NF_MAX_DB = -20.0
#: Fallback when the measured floor is unusable (pristine/digital silence).
NF_FALLBACK_DB = -50.0

#: Verification guards. A denoised result is rejected when it loses more
#: speech-band energy than removing the *measured* noise could explain,
#: or when its entropy collapses (the signature of gating rather than
#: denoising — gating barely moves total RMS, so RMS alone misses it).
BAND_TOLERANCE_DB = 0.8
ENTROPY_TOLERANCE = 0.12

#: Speech band used by the verification measurement (telephone band).
SPEECH_BAND_LOW_HZ = 300
SPEECH_BAND_HIGH_HZ = 3400

#: Files at or under this length are analysed in full; longer ones are
#: sampled, so analysis cost does not grow with duration.
FULL_SCAN_MAX_S = 180.0
SAMPLE_WINDOW_S = 30.0
SAMPLE_POSITIONS: tuple[float, ...] = (0.15, 0.50, 0.80)

_DEFAULT_CACHE_BUDGET_MB = 1024

#: A render written / used this recently may be mid-read by another
#: concurrent worker process (the app can run several transcription
#: workers at once), so it is never evicted even when the budget is
#: exceeded. Same protection as the demucs stem cache.
_CACHE_IN_USE_GRACE_S = 300

_ANALYSIS_TIMEOUT_S = 300.0
_MIN_FILTER_TIMEOUT_S = 600.0

#: A denoised output smaller than this is treated as degenerate.
_MIN_OUTPUT_BYTES = 1024


class DenoiseUnavailable(RuntimeError):
    """Raised only by :func:`require_ffmpeg`; the public API never raises."""


# ------------------------------------------------------------ data classes


@dataclass(frozen=True)
class AudioStats:
    """One ffmpeg ``astats`` "Overall" block, in dB (or dimensionless)."""

    rms_level: float = float("nan")
    rms_peak: float = float("nan")
    rms_trough: float = float("nan")
    peak_level: float = float("nan")
    noise_floor: float = float("nan")
    entropy: float = float("nan")
    flat_factor: float = float("nan")

    @classmethod
    def from_metrics(cls, m: dict[str, float]) -> "AudioStats":
        # ffmpeg spells the trough metric "RMS through dB" — an upstream
        # typo, not ours. Accept both spellings so a future fix upstream
        # does not silently blank the field.
        return cls(
            rms_level=m.get("rms_level", float("nan")),
            rms_peak=m.get("rms_peak", float("nan")),
            rms_trough=m.get("rms_through", m.get("rms_trough", float("nan"))),
            peak_level=m.get("peak_level", float("nan")),
            noise_floor=m.get("noise_floor", float("nan")),
            entropy=m.get("entropy", float("nan")),
            flat_factor=m.get("flat_factor", float("nan")),
        )


@dataclass(frozen=True)
class NoiseProfile:
    """Result of :func:`analyze` — what the source audio actually is."""

    full: AudioStats
    speech_band: AudioStats | None
    snr_db: float
    windows: int = 1
    #: The ``(start_s, length_s)`` these numbers were measured over.
    #: Verification MUST re-measure this exact window on the render:
    #: loudness varies hugely along a real recording (13.5 dB between
    #: sampled windows on a test file, against a ~1 dB tolerance), so
    #: comparing two different windows produces a meaningless verdict.
    window: tuple[float, float] = (0.0, 0.0)

    @property
    def noise_floor_db(self) -> float:
        return self.full.noise_floor

    def describe(self) -> str:
        snr = "clean (no measurable noise floor)" if _is_pristine(self.snr_db) \
            else f"{self.snr_db:.1f} dB"
        return (
            f"speech/noise {snr}, noise floor "
            f"{_fmt_db(self.full.noise_floor)}, RMS {_fmt_db(self.full.rms_level)}"
        )


# ------------------------------------------------------------- pure helpers


def _fmt_db(v: float) -> str:
    if v != v:  # NaN
        return "n/a"
    if v == float("-inf"):
        return "-inf dB"
    return f"{v:.1f} dB"


def _is_pristine(snr_db: float) -> bool:
    """True when SNR carries no usable number (NaN / +inf)."""
    return snr_db != snr_db or snr_db == float("inf")


# ``Peak level dB: -21.465412`` / ``Entropy: 0.694376`` / ``Noise floor dB: -inf``
_METRIC_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z][A-Za-z ]*?)(?:\s+dB)?:\s*"
    r"(?P<val>-?(?:inf|\d+(?:\.\d+)?))\s*$"
)


def parse_astats_blocks(stderr: str) -> list[dict[str, float]]:
    """Extract every ``astats`` "Overall" block from ffmpeg's stderr.

    Returns one dict of ``snake_case metric -> float`` per block, in the
    order ffmpeg printed them. Unparseable lines are skipped rather than
    raising: ffmpeg's log format is not a stable API.
    """
    blocks: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for line in stderr.splitlines():
        if "Parsed_astats" not in line:
            continue
        body = line.split("] ", 1)[-1]
        if body.strip() == "Overall":
            current = {}
            blocks.append(current)
            continue
        if current is None:
            continue
        m = _METRIC_RE.match(body)
        if not m:
            continue
        raw = m.group("val")
        try:
            value = float("-inf") if raw == "-inf" else float(raw)
        except ValueError:  # pragma: no cover — regex already constrains this
            continue
        current[m.group("key").strip().lower().replace(" ", "_")] = value
    return blocks


def split_full_and_band(
    blocks: list[dict[str, float]],
) -> tuple[AudioStats | None, AudioStats | None]:
    """Assign the two analysis blocks to (full-band, speech-band).

    Band-passing can only *remove* energy, so the speech-band block can
    never have a higher RMS than the full-band one. That invariant — not
    the print order — decides which is which, so a future ffmpeg that
    reorders its filter teardown cannot silently swap them.
    """
    if not blocks:
        return None, None
    if len(blocks) == 1:
        return AudioStats.from_metrics(blocks[0]), None
    a = AudioStats.from_metrics(blocks[0])
    b = AudioStats.from_metrics(blocks[1])
    if _rms_or(b, float("-inf")) > _rms_or(a, float("-inf")):
        return b, a
    return a, b


def _rms_or(stats: AudioStats, default: float) -> float:
    v = stats.rms_level
    return default if v != v else v


def estimate_snr_db(stats: AudioStats) -> float:
    """Speech level minus noise floor, in dB.

    The numerator is ``max(rms_level, rms_peak - 10)``: on continuous
    speech the overall RMS *is* the speech level, but on sparse speech
    (a long file that is mostly silence) overall RMS understates it and
    would over-trigger denoising. ``rms_peak`` is the loudest short
    window, so the ``- 10 dB`` backs off from a one-off transient.

    Returns ``+inf`` for a source with no measurable noise floor and
    ``NaN`` when the measurement is unusable.
    """
    rms = stats.rms_level
    peak = stats.rms_peak
    floor = stats.noise_floor
    candidates = [v for v in (rms, peak - 10.0 if peak == peak else peak) if v == v]
    if not candidates or floor != floor:
        return float("nan")
    speech = max(candidates)
    if floor == float("-inf"):
        return float("inf")
    return speech - floor


def decide_level(snr_db: float, requested: str = "auto") -> str:
    """Resolve the effective level.

    An explicit ``light``/``medium``/``strong`` is honoured as-is — the
    user overriding the measurement is the point of the setting. Only
    ``auto`` consults ``snr_db``. An unusable measurement (NaN) means
    "do nothing": never denoise on a guess.
    """
    req = (requested or "auto").strip().lower()
    if req in LEVELS:
        return req
    if req != "auto":
        logger.warning("Unknown denoise level %r; treating as 'auto'.", requested)
    if _is_pristine(snr_db):
        return "off"
    if snr_db >= SNR_CLEAN_DB:
        return "off"
    if snr_db >= SNR_LIGHT_DB:
        return "light"
    if snr_db >= SNR_MEDIUM_DB:
        return "medium"
    return "strong"


def clamp_noise_floor(noise_floor_db: float) -> float:
    """Clamp a measured floor into ``afftdn``'s accepted ``nf`` range."""
    if noise_floor_db != noise_floor_db or noise_floor_db == float("-inf"):
        return NF_FALLBACK_DB
    if noise_floor_db == float("inf"):
        return NF_FALLBACK_DB
    return max(NF_MIN_DB, min(NF_MAX_DB, noise_floor_db))


def build_filter_chain(level: str, noise_floor_db: float) -> str:
    """ffmpeg ``-af`` chain for a level, parameterised by measured floor.

    Each level is a high-pass (rumble / HVAC / handling noise, well below
    the speech fundamental) plus ``afftdn`` spectral denoise with noise
    tracking (``tn=1``) so a *changing* noise bed is followed rather than
    assumed stationary.

    ``nr`` (reduction depth) stays at or below 24 dB on purpose: deeper
    settings start producing musical noise — isolated spectral artefacts
    that hurt ASR more than the noise they removed.
    """
    lvl = (level or "off").strip().lower()
    if lvl not in LEVELS or lvl == "off":
        return ""
    nf = clamp_noise_floor(noise_floor_db)
    highpass_hz, nr = {
        "light": (70, 10),
        "medium": (80, 16),
        "strong": (90, 24),
    }[lvl]
    return (
        f"highpass=f={highpass_hz}:poles=2,"
        f"afftdn=nr={nr}:nf={nf:.1f}:tn=1"
    )


def analysis_filter_complex() -> str:
    """Filtergraph measuring full-band and speech-band stats in one pass."""
    return (
        "asplit=2[a][b];"
        "[a]astats=measure_perchannel=none[a1];"
        f"[b]highpass=f={SPEECH_BAND_LOW_HZ}:poles=2,"
        f"lowpass=f={SPEECH_BAND_HIGH_HZ}:poles=2,"
        "astats=measure_perchannel=none[b1];"
        "[a1][b1]amix=inputs=2"
    )


def sample_windows(duration_s: float) -> list[tuple[float, float]]:
    """Windows to analyse, as ``(start_s, length_s)``; length 0 = to EOF.

    Short files are scanned whole. Longer ones are sampled at three
    positions so a music intro, a silent gap or a single noisy passage
    cannot dominate the estimate, and so analysis cost stays flat as
    duration grows.
    """
    if duration_s != duration_s or duration_s <= 0.0:
        return [(0.0, 0.0)]
    if duration_s <= FULL_SCAN_MAX_S:
        return [(0.0, 0.0)]
    windows: list[tuple[float, float]] = []
    for frac in SAMPLE_POSITIONS:
        start = duration_s * frac - SAMPLE_WINDOW_S / 2.0
        start = max(0.0, min(start, duration_s - SAMPLE_WINDOW_S))
        windows.append((round(start, 3), SAMPLE_WINDOW_S))
    return windows


def allowed_band_drop_db(snr_db: float) -> float:
    """How much speech-band energy loss the measured noise can explain.

    At SNR *s* the noise carries ``10**(-s/10)`` of the total power, so
    perfectly removing it lowers measured energy by
    ``10*log10(1 + 10**(-s/10))``. A clean file (high SNR) may therefore
    lose almost nothing before we call it damage, while a genuinely
    noisy file is allowed a large, *expected* drop. Without this scaling
    a fixed threshold rejects exactly the heavy-noise cases the feature
    exists for — verified: at 1.2 dB SNR a legitimate pass drops 2.0 dB.
    """
    if _is_pristine(snr_db):
        return BAND_TOLERANCE_DB
    bounded = max(-20.0, min(60.0, snr_db))
    expected = 10.0 * math.log10(1.0 + 10.0 ** (-bounded / 10.0))
    return expected + BAND_TOLERANCE_DB


def verdict(before: NoiseProfile, after: NoiseProfile) -> tuple[bool, str]:
    """Decide whether a denoised result is safe to use.

    Returns ``(keep, reason)``. Deliberately asymmetric: a wrong
    "revert" costs one wasted ffmpeg pass, a wrong "keep" costs
    transcript quality on every segment. When the measurement is
    inconclusive we keep the *original*.

    A render whose measured SNR is *worse* than the input's is rejected:
    the band/entropy guards can miss a filter that adds spectral
    artefacts without gating speech, whereas a measured regression is
    direct evidence the source got noisier.
    """
    b_band = before.speech_band
    a_band = after.speech_band
    if b_band is None or a_band is None:
        return False, "verification unavailable (speech-band measurement missing)"

    b_rms, a_rms = b_band.rms_level, a_band.rms_level
    if b_rms != b_rms or a_rms != a_rms:
        return False, "verification unavailable (speech-band RMS unreadable)"

    band_drop = b_rms - a_rms
    allowed = allowed_band_drop_db(before.snr_db)
    if band_drop > allowed:
        return False, (
            f"speech-band energy fell {band_drop:.2f} dB, more than the "
            f"{allowed:.2f} dB the measured noise explains"
        )

    b_ent, a_ent = before.full.entropy, after.full.entropy
    if b_ent == b_ent and a_ent == a_ent:
        ent_drop = b_ent - a_ent
        if ent_drop > ENTROPY_TOLERANCE:
            return False, (
                f"signal entropy collapsed by {ent_drop:.3f} "
                f"(> {ENTROPY_TOLERANCE}) — filter gated speech, not noise"
            )

    gain = after.snr_db - before.snr_db
    if gain == gain and gain != float("inf"):
        if gain < 0.0:
            return False, (
                f"speech/noise regressed by {abs(gain):.1f} dB — the filter "
                "left the audio noisier than the original"
            )
        return True, f"speech/noise improved by {gain:.1f} dB"
    return True, "noise floor no longer measurable"


# ------------------------------------------------------------------ cache


def cache_dir() -> Path:
    return user_cache_dir() / "denoise"


def _cache_budget_mb() -> int:
    try:
        from .config import load_config
        return max(0, int(load_config().get("denoise_cache_mb",
                                            _DEFAULT_CACHE_BUDGET_MB)))
    except Exception:  # noqa: BLE001
        return _DEFAULT_CACHE_BUDGET_MB


def _cache_key(audio_path: str, level: str) -> str:
    """Stable key from path + size + mtime + level.

    Hashing content would be correct but slow on multi-GB input; size +
    mtime catches the edit-then-re-transcribe case. ``level`` is in the
    key so switching strength does not reuse the previous render.
    """
    try:
        st = os.stat(audio_path)
        token = f"{audio_path}|{st.st_size}|{int(st.st_mtime)}|{level}"
    except OSError:
        token = f"{audio_path}|missing|{level}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]


def _cached_path(audio_path: str, level: str) -> Path:
    return cache_dir() / f"{_cache_key(audio_path, level)}_denoised.wav"


def _cache_hit(path: Path) -> bool:
    """True when ``path`` is a usable cached render; refreshes its mtime.

    Mirrors :mod:`core.separator`'s hit path: the ``exists()``/``stat()``
    pair races a concurrent prune, so ``OSError`` means "miss", never a
    raise.  A hit refreshes mtime so the in-use grace in
    :func:`prune_cache` treats the render as active (use-based LRU, not
    write-based) — without this a popular but old render loses its
    mid-read protection the moment the grace expires.
    """
    try:
        if not (path.exists() and path.stat().st_size >= _MIN_OUTPUT_BYTES):
            return False
    except OSError:
        # A concurrent prune removed the render between exists() and
        # stat() — treat as a miss and regenerate it.
        return False
    try:
        os.utime(path, None)
    except OSError:
        pass
    return True


def prune_cache(budget_mb: int | None = None, *, keep: str | None = None) -> int:
    """Evict oldest renders until the cache fits its byte budget.

    Returns the number of files removed. ``keep`` is never evicted, and
    neither is a render touched within the last ``_CACHE_IN_USE_GRACE_S``
    seconds — another worker may be mid-read. A budget <= 0 disables
    eviction. Never raises.
    """
    budget = _cache_budget_mb() if budget_mb is None else max(0, budget_mb)
    if budget <= 0:
        return 0
    try:
        # Resolving the directory can itself fail (user_cache_dir() on a
        # read-only / unresolvable home — the exact trigger fixed at the
        # entry points), so it must sit inside the same guard as the glob
        # it feeds: the docstring promises this sweep never raises.
        d = cache_dir()
        files = [p for p in d.glob("*_denoised.wav") if p.is_file()]
    except Exception:  # noqa: BLE001
        return 0

    def _mtime_or_zero(p: Path) -> float:
        # A concurrent worker may delete a render mid-sort; one vanishing
        # file must not abort the whole sweep.
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    try:
        files.sort(key=_mtime_or_zero, reverse=True)  # newest first
    except OSError:
        return 0
    budget_bytes = budget * 1024 * 1024
    keep_norm = os.path.normcase(os.path.abspath(keep)) if keep else None
    now = time.time()
    total = 0
    removed = 0
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        size = st.st_size
        is_keeper = bool(keep_norm) and (
            os.path.normcase(os.path.abspath(str(p))) == keep_norm
        )
        in_use = (now - st.st_mtime) < _CACHE_IN_USE_GRACE_S
        if total + size <= budget_bytes or is_keeper or in_use:
            total += size
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def clear_cache() -> None:
    """Remove the whole denoise cache directory. Never raises."""
    try:
        # ignore_errors covers rmtree's own failures, not cache_dir()
        # raising before the call — an unresolvable user_cache_dir()
        # must not escape this contract either.
        shutil.rmtree(cache_dir(), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------- availability

_FFMPEG_OK: bool | None = None


def is_available() -> bool:
    """True when the bundled/PATH ffmpeg can actually be executed.

    Cached: this shells out once per process, and the transcriber calls
    it per file.
    """
    global _FFMPEG_OK
    cached = _FFMPEG_OK
    if cached is not None:
        return cached
    ok = False
    try:
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 30,
        }
        kwargs.update(new_session_kwargs())
        rc = subprocess.run(
            [bundled_binary("ffmpeg"), "-hide_banner", "-version"],
            **kwargs,  # type: ignore[arg-type]
        ).returncode
        ok = rc == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _FFMPEG_OK = ok
    return ok


def availability_reason() -> str:
    if is_available():
        return ""
    return "ffmpeg not available — audio denoise pre-processing is disabled."


def require_ffmpeg() -> str:
    if not is_available():
        raise DenoiseUnavailable(availability_reason())
    return bundled_binary("ffmpeg")


# ------------------------------------------------------------------ ffmpeg


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    kwargs.update(new_session_kwargs())
    return subprocess.run(cmd, **kwargs)  # type: ignore[arg-type,return-value]


def _measure(
    path: str,
    *,
    start_s: float = 0.0,
    length_s: float = 0.0,
) -> tuple[AudioStats | None, AudioStats | None]:
    """Measure one window. Returns ``(full_band, speech_band)``."""
    cmd = [bundled_binary("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "info"]
    if start_s > 0.0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", path]
    if length_s > 0.0:
        cmd += ["-t", f"{length_s:.3f}"]
    cmd += ["-vn", "-filter_complex", analysis_filter_complex(), "-f", "null", "-"]
    try:
        result = _run(cmd, _ANALYSIS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        logger.info("Denoise analysis failed for %s: %s", path, e)
        return None, None
    if result.returncode != 0:
        logger.info(
            "Denoise analysis exited %s for %s", result.returncode, path
        )
        return None, None
    return split_full_and_band(parse_astats_blocks(result.stderr or ""))


def analyze(
    path: str,
    *,
    duration_s: float = 0.0,
    window: tuple[float, float] | None = None,
    log: Callable[[str], None] | None = None,
) -> NoiseProfile | None:
    """Measure the source and estimate its speech-to-noise ratio.

    ``window`` forces a single ``(start_s, length_s)`` measurement
    instead of sampling. Verification uses it to re-measure the exact
    span the "before" profile came from — see :attr:`NoiseProfile.window`.

    Returns ``None`` when ffmpeg is unavailable or every window failed to
    measure — the caller then leaves the audio alone.
    """
    if not is_available():
        if log:
            log(f"Denoise skipped: {availability_reason()}")
        return None

    windows = [window] if window is not None else sample_windows(duration_s)
    measured: list[tuple[float, AudioStats, AudioStats | None, tuple[float, float]]] = []
    # Each window is a separate short-lived ffmpeg; nothing is emitted
    # between them, so on a slow disk / network mount the parent's
    # 120 s liveness watchdog could declare the worker wedged mid-scan.
    with liveness_tick(log, "Audio analysis"):
        for start_s, length_s in windows:
            full, band = _measure(path, start_s=start_s, length_s=length_s)
            if full is None:
                continue
            measured.append(
                (estimate_snr_db(full), full, band, (start_s, length_s))
            )

    usable = [m for m in measured if m[0] == m[0]]  # drop NaN measurements
    if not usable:
        if log:
            log("Denoise: could not measure the audio; leaving it untouched.")
        return None

    # Median window, not mean: one window landing on a music bed, a
    # silent gap or a single burst of noise must not steer the decision.
    snrs = sorted(m[0] for m in usable)
    median_snr = statistics.median(snrs)
    # Select a window AT the median. Plain abs(snr - median) breaks when
    # both are +inf (a pristine / digital-silence window): inf - inf is
    # NaN, NaN loses every min() comparison, and the first measured
    # window won instead -- letting a lone noisy window steer the level
    # on a majority-pristine file, exactly what the median exists to
    # prevent. Testing equality first makes inf == inf select 0.
    chosen = min(
        usable,
        key=lambda m: 0.0 if m[0] == median_snr else abs(m[0] - median_snr),
    )
    return NoiseProfile(
        full=chosen[1],
        speech_band=chosen[2],
        snr_db=chosen[0],
        windows=len(usable),
        window=chosen[3],
    )


def _apply_chain(
    src: str,
    dst: str,
    chain: str,
    *,
    duration_s: float,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Render ``src`` through ``chain`` to a 16 kHz mono WAV at ``dst``.

    16 kHz mono is exactly what every ASR backend resamples to anyway,
    so this replaces a decode rather than adding one, and keeps the
    cache small.
    """
    cmd = [
        bundled_binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-vn",
        "-af", chain,
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-f", "wav",
        "-y", dst,
    ]
    timeout = max(_MIN_FILTER_TIMEOUT_S, float(duration_s or 0.0) * 1.5)
    try:
        # Long files hold the GIL-free subprocess for minutes; keep the
        # parent's worker-liveness watchdog fed.
        with liveness_tick(log, "Audio denoise"):
            result = _run(cmd, timeout)
    except (OSError, subprocess.SubprocessError) as e:
        logger.info("Denoise filter failed for %s: %s", src, e)
        return False
    if result.returncode != 0:
        # ffmpeg can also die on a signal here (negative/large return
        # code). Either way the original audio is still good.
        logger.info(
            "Denoise filter exited %s for %s: %s",
            result.returncode, src, (result.stderr or "").strip()[:300],
        )
        return False
    try:
        return os.path.getsize(dst) >= _MIN_OUTPUT_BYTES
    except OSError:
        return False


# ------------------------------------------------------------- entry point


def denoise_audio(
    audio_path: str,
    *,
    enabled: bool = True,
    level: str = "auto",
    duration_s: float = 0.0,
    cache: bool = True,
    work_dir: Path | str | None = None,
    log: Callable[[str], None] | None = None,
) -> str:
    """Return a path to denoised audio, or ``audio_path`` untouched.

    Every failure mode — disabled, ffmpeg missing, unmeasurable audio,
    "already clean", ffmpeg crash, failed verification — returns the
    input path. The caller never needs a fallback branch and this
    function never raises.

    ``cache=False`` writes beside ``work_dir`` instead of the shared
    cache; use it for transient inputs (e.g. an already-sliced clip)
    whose cache entry could never be reused. The caller owns deleting a
    returned path that differs from its input.
    """
    if not enabled:
        return audio_path
    try:
        return _denoise_audio_inner(
            audio_path,
            level=level,
            duration_s=duration_s,
            cache=cache,
            work_dir=work_dir,
            log=log,
        )
    except Exception as e:  # noqa: BLE001
        # Belt and braces: a denoise failure must never cost the user
        # their transcription.
        logger.exception("Denoise pre-process failed: %s", e)
        if log:
            try:
                log(f"Denoise failed ({e}); using the original audio.")
            except Exception:  # noqa: BLE001
                # This handler IS the "never raises" safety net; a dead
                # UI callback must not throw its own exception back out
                # of the net and take the transcription down anyway.
                logger.exception("Denoise log callback failed")
        return audio_path


def _denoise_audio_inner(
    audio_path: str,
    *,
    level: str,
    duration_s: float,
    cache: bool,
    work_dir: Path | str | None,
    log: Callable[[str], None] | None,
) -> str:
    if not is_available():
        if log:
            log(f"Denoise skipped: {availability_reason()}")
        return audio_path

    requested = (level or "auto").strip().lower()

    # An explicit "off" means off — do not pay for a measurement pass to
    # be told so. (This used to be reachable only on the cached path, so
    # a transient off still analysed the audio for nothing.)
    if requested == "off":
        return audio_path

    # A cache hit short-circuits the analysis pass too, but only for an
    # explicit level: under "auto" the level is not known until after the
    # measurement, so there is nothing to look up yet.
    if cache and requested in LEVELS:
        hit = _cached_path(audio_path, requested)
        if _cache_hit(hit):
            if log:
                log(f"Denoise cache hit ({requested}) -> {hit}")
            return str(hit)

    before = analyze(audio_path, duration_s=duration_s, log=log)
    if before is None:
        return audio_path

    effective = decide_level(before.snr_db, requested)
    if log:
        log(f"Denoise analysis: {before.describe()} "
            f"(sampled {before.windows} window(s)) -> level={effective}")
    if effective == "off":
        if log:
            log("Denoise: audio is already clean enough; leaving it untouched.")
        return audio_path

    if cache:
        target = _cached_path(audio_path, effective)
        if _cache_hit(target):
            if log:
                log(f"Denoise cache hit ({effective}) -> {target}")
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        # Never default to the source's own folder: it may be read-only,
        # or a media library the user does not want littered.
        base = Path(work_dir) if work_dir else cache_dir()
        base.mkdir(parents=True, exist_ok=True)
        target = base / (
            f"{Path(audio_path).stem}.{os.getpid()}."
            f"{_cache_key(audio_path, effective)}.denoised.wav"
        )

    chain = build_filter_chain(effective, before.noise_floor_db)
    if not chain:
        return audio_path

    # Render to a sibling temp then move into place, so a crash mid-write
    # can never leave a truncated file looking like a valid cache entry.
    # pid+thread in the name: two workers transcribing the SAME file
    # derive the same cache key, and a shared staging path would let them
    # interleave writes and then publish the mess as a valid entry.
    staging = target.with_suffix(
        f".{os.getpid()}-{threading.get_ident()}.part"
    )
    try:
        if not _apply_chain(audio_path, str(staging), chain,
                            duration_s=duration_s, log=log):
            if log:
                log("Denoise: ffmpeg could not process this audio; "
                    "using the original.")
            return audio_path

        # Re-measure the SAME window the "before" profile came from.
        # Sampling afresh would pick the median window of the *denoised*
        # file, which need not be the same span — and loudness varies far
        # more along a recording than the verdict's tolerance, so a
        # mismatched pair produces a meaningless verdict.
        after = analyze(
            str(staging),
            duration_s=duration_s,
            window=before.window,
            log=log,
        )
        if after is None:
            if log:
                log("Denoise: result could not be verified; using the original.")
            return audio_path

        keep, reason = verdict(before, after)
        if not keep:
            if log:
                log(f"Denoise reverted — {reason}. Using the original audio.")
            return audio_path

        try:
            os.replace(str(staging), str(target))
        except OSError as e:
            logger.info("Could not move denoised render into place: %s", e)
            return audio_path

        if log:
            log(f"Denoise applied ({effective}) — {reason}.")
    finally:
        # Any abandoned render must not survive as a stray ``.part``
        # file: it does not match the cache's ``*_denoised.wav`` glob, so
        # nothing would ever evict it.  After a successful ``os.replace``
        # the staging path no longer exists and this is a no-op.
        _unlink(staging)
    if cache:
        try:
            evicted = prune_cache(keep=str(target))
            if evicted and log:
                log(f"Denoise cache pruned: removed {evicted} old render(s).")
        except Exception:  # noqa: BLE001
            pass
    return str(target)


def _unlink(p: Path | str) -> None:
    try:
        os.unlink(str(p))
    except OSError:
        pass
