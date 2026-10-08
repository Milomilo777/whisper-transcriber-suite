"""Text to Voice with ready-made voices: Kokoro (via sherpa-onnx).

The second engine of the Clone Your Voice / Text to Voice tab, next to
OmniVoice (``core.voice_clone``). OmniVoice clones or designs a voice
but is slow on a CPU; Kokoro has 53 ready-made voices and runs several
times faster than real time on an ordinary CPU.

Runs on ``sherpa-onnx``, which the app already ships for diarization, so
nothing is pip-installed on demand: only the model (Kokoro
multi-lang v1.0, ~350 MB, Apache-2.0) is downloaded the first time it is
used, into the user cache.

Tk-free; the tab calls :func:`generate` from a worker thread.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import tarfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# The full-precision model, not the int8 one (~130 MB): on a CPU without
# VNNI (e.g. an i7-6700) int8 ran at 2.3x real time, fp32 at 0.8x.
MODEL_NAME = "kokoro-multi-lang-v1_0"
_MODEL_FILE = "model.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    f"{MODEL_NAME}.tar.bz2"
)
APPROX_DOWNLOAD_MB = 350
SAMPLE_RATE = 24000


@dataclass(frozen=True)
class Voice:
    sid: int
    key: str        # Kokoro's own voice name, e.g. "af_heart"
    language: str   # display language
    lang_code: str  # espeak-ng language for sherpa-onnx's ``lang``
    gender: str

    @property
    def label(self) -> str:
        name = self.key.split("_", 1)[1].replace("_", " ").title()
        return f"{name} — {self.language}, {self.gender}"


# Speaker ids of kokoro-multi-lang-v1_0 (voices.bin order), per the
# sherpa-onnx model docs; spot-checked by pitch (af_heart ~190 Hz,
# am_adam ~120 Hz). The first letter of the key is the language,
# the second the gender -- Kokoro's own naming convention.
_KEYS = (
    "af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova "
    "af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam "
    "am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily "
    "bm_daniel bm_fable bm_george bm_lewis ef_dora em_alex ff_siwis hf_alpha "
    "hf_beta hm_omega hm_psi if_sara im_nicola jf_alpha jf_gongitsune "
    "jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa zf_xiaobei "
    "zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang "
    "em_santa"  # id 53, appended after the original 53 (model README)
).split()
_LANGS = {
    "a": ("US English", "en-us"), "b": ("UK English", "en-gb"),
    "e": ("Spanish", "es"), "f": ("French", "fr"), "h": ("Hindi", "hi"),
    "i": ("Italian", "it"), "j": ("Japanese", "ja"),
    "p": ("Portuguese", "pt-br"), "z": ("Chinese", "zh"),
}

VOICES: tuple[Voice, ...] = tuple(
    Voice(sid, key, _LANGS[key[0]][0], _LANGS[key[0]][1],
          "female" if key[1] == "f" else "male")
    for sid, key in enumerate(_KEYS)
)
#: Kokoro's best-rated voice; the tab's default.
DEFAULT_VOICE = "af_heart"

#: The Unicode scripts each voice language reads (the first word of a
#: character's Unicode name, after FULLWIDTH/HALFWIDTH).
_LANG_SCRIPTS = {
    "en-us": ("LATIN",), "en-gb": ("LATIN",), "es": ("LATIN",), "fr": ("LATIN",),
    "it": ("LATIN",), "pt-br": ("LATIN",), "hi": ("DEVANAGARI",),
    "ja": ("HIRAGANA", "KATAKANA", "KATAKANA-HIRAGANA", "CJK"), "zh": ("CJK",),
}
_READABLE_SCRIPTS = frozenset(s for v in VOICES for s in _LANG_SCRIPTS[v.lang_code])
#: "US English, UK English, Spanish, ... and Chinese" for messages.
LANGUAGE_NAMES = ", ".join(n for n, _c in list(_LANGS.values())[:-1]) + \
    f" and {list(_LANGS.values())[-1][0]}"


#: Letters whose Unicode name names no script (ordinal indicators, the
#: micro sign, the ideographic iteration mark, modifier letters): not counted.
_NO_SCRIPT = frozenset({"FEMININE", "MASCULINE", "MICRO", "IDEOGRAPHIC", "MODIFIER", ""})


@functools.lru_cache(maxsize=4096)
def _script_of(ch: str) -> str:
    import unicodedata

    words = unicodedata.name(ch, "").split()
    if len(words) > 1 and words[0] in ("FULLWIDTH", "HALFWIDTH"):
        return words[1]
    return words[0] if words else ""


def unsupported_script(text: str) -> "str | None":
    """The main script of *text* (e.g. "Arabic", "Cyrillic", "Hangul",
    "Thai") when fewer than half of its letters are in a script any Kokoro
    voice reads; None when Kokoro can read it (or it has no letters)."""
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isalpha():
            script = _script_of(ch)
            if script not in _NO_SCRIPT:
                counts[script] = counts.get(script, 0) + 1
    total = sum(counts.values())
    readable = sum(n for s, n in counts.items() if s in _READABLE_SCRIPTS)
    if not total or readable * 2 >= total:
        return None
    main = max((s for s in counts if s not in _READABLE_SCRIPTS), key=lambda s: counts[s])
    return main.title()


def voice_by_key(key: str) -> Voice:
    return next((v for v in VOICES if v.key == key),
                next(v for v in VOICES if v.key == DEFAULT_VOICE))


def model_dir() -> Path:
    from .config import user_cache_dir

    return user_cache_dir() / "tts" / MODEL_NAME


def is_downloaded() -> bool:
    d = model_dir()
    return (d / _MODEL_FILE).is_file() and (d / "voices.bin").is_file()


def download(
    progress_cb: "Callable[[int, int], None] | None" = None,
    cancel_event: "threading.Event | None" = None,
) -> Path:
    """Download + unpack the model into :func:`model_dir` (idempotent).

    Unpacks into a staging dir and renames it into place, so a cancelled
    or failed download never leaves a half-extracted model that
    :func:`is_downloaded` would accept. The archive is fetched into a
    ``.part`` file that a cancel or a network error keeps: the next try
    resumes it with an HTTP Range request instead of restarting ~350 MB.
    The ``.part`` goes once it is unpacked, or when it turns out not to be
    a readable archive.
    """
    import requests

    from core import offline

    target = model_dir()
    if is_downloaded():
        return target
    offline.require_online("downloading the Kokoro voice model")
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f"{MODEL_NAME}.tar.bz2.part"
    staging = target.parent / f"{MODEL_NAME}.staging"
    _fetch_archive(requests, archive, progress_cb, cancel_event)
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        damaged: BaseException | None = None
        try:
            with tarfile.open(archive, "r:bz2") as tar:
                tar.extractall(staging, filter="data")
        except OSError as e:
            if e.errno is not None:
                raise  # a disk / permission problem: the archive may be fine
            damaged = e  # bz2's "Invalid data stream"
        except (tarfile.TarError, EOFError) as e:
            damaged = e
        if damaged is not None:
            # A damaged archive would fail the same way on every retry.
            archive.unlink(missing_ok=True)
            raise RuntimeError(
                "The downloaded voice model archive is damaged; it was removed. "
                "Try the download again."
            ) from damaged
        inner = staging / MODEL_NAME
        src = inner if inner.is_dir() else staging
        shutil.rmtree(target, ignore_errors=True)
        os.replace(src, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if not is_downloaded():
        raise RuntimeError("The downloaded voice model is incomplete.")
    archive.unlink(missing_ok=True)
    return target


def _fetch_archive(
    requests: Any,
    archive: Path,
    progress_cb: "Callable[[int, int], None] | None",
    cancel_event: "threading.Event | None",
) -> None:
    """Fetch :data:`MODEL_URL` into ``archive``, resuming a partial file."""
    for _attempt in range(2):
        existing = archive.stat().st_size if archive.is_file() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        with requests.get(MODEL_URL, stream=True, timeout=(10, 60), headers=headers) as r:
            if existing and r.status_code == 416:
                # Nothing left to send: complete only when the server's
                # size matches the file, else the leftover is not this
                # archive and the download starts over.
                m = re.match(r"bytes \*/(\d+)$", r.headers.get("content-range") or "")
                if m and int(m.group(1)) == existing:
                    return
                archive.unlink(missing_ok=True)
                continue
            r.raise_for_status()
            resumed = bool(existing) and r.status_code == 206
            done = existing if resumed else 0
            length = int(r.headers.get("content-length") or 0)
            total = done + length if length else 0
            with open(archive, "ab" if resumed else "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Download cancelled.")
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
            if total and done < total:
                raise RuntimeError(
                    "The voice model download was cut off; try again to resume it."
                )
            return
    raise RuntimeError("The voice model server did not send the archive.")


_engine_lock = threading.Lock()
_engines: dict[str, Any] = {}


def _load(lang_code: str) -> Any:
    """Load (or reuse) the sherpa-onnx engine for one espeak language.

    ``lang`` is fixed per engine in sherpa-onnx, so non-English voices get
    their own engine; the common English case reuses one.
    """
    import sherpa_onnx  # type: ignore[import-not-found]

    key = lang_code
    with _engine_lock:
        eng = _engines.get(key)
        if eng is not None:
            return eng
        d = model_dir()
        english = "lexicon-gb-en.txt" if lang_code == "en-gb" else "lexicon-us-en.txt"
        lexicons = ",".join(
            str(d / name) for name in (english, "lexicon-zh.txt")
            if (d / name).is_file()
        )
        kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(d / _MODEL_FILE),
            voices=str(d / "voices.bin"),
            tokens=str(d / "tokens.txt"),
            lexicon=lexicons,
            data_dir=str(d / "espeak-ng-data"),
            dict_dir=str(d / "dict") if (d / "dict").is_dir() else "",
            # English + Chinese go through the lexicons; every other
            # language through espeak-ng with that language's voice.
            lang="" if lang_code in ("en-us", "en-gb", "zh") else lang_code,
        )
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=kokoro, num_threads=max(1, min(4, os.cpu_count() or 1)),
                provider="cpu",
            ),
            rule_fsts=",".join(
                str(p) for p in sorted(d.glob("*.fst"))
            ),
            max_num_sentences=1,
        )
        eng = sherpa_onnx.OfflineTts(config)
        _engines.clear()  # keep one engine resident, not one per language
        _engines[key] = eng
        return eng


@dataclass
class KokoroResult:
    output_path: str
    audio_seconds: float
    elapsed_seconds: float


def generate(
    text: str,
    voice_key: str,
    output_path: str,
    speed: float = 1.0,
    progress_cb: "Callable[[float], None] | None" = None,
    cancel_event: "threading.Event | None" = None,
) -> KokoroResult:
    """Speak *text* in a ready-made voice and write a WAV to *output_path*.

    One pass, at most ``core.tts_plan.MAX_PASS_CHARS`` characters:
    sherpa-onnx splits it into sentences itself and reports progress (0..1)
    through *progress_cb* after each one. Longer texts go through
    ``core.tts_job`` piece by piece.
    """
    import wave

    import numpy as np  # type: ignore[import-not-found]

    from .tts_plan import MAX_PASS_CHARS

    if not text.strip():
        raise ValueError("No text to speak.")
    if len(text) > MAX_PASS_CHARS:
        raise ValueError(
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {MAX_PASS_CHARS}."
        )
    voice = voice_by_key(voice_key)
    engine = _load(voice.lang_code)

    def _cb(_samples: Any, progress: float) -> int:  # noqa: ARG001
        if progress_cb:
            progress_cb(float(progress))
        return 0 if cancel_event is not None and cancel_event.is_set() else 1

    t0 = time.time()
    audio = engine.generate(text, sid=voice.sid, speed=float(speed), callback=_cb)
    elapsed = time.time() - t0
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Cancelled.")
    samples = np.asarray(audio.samples, dtype=np.float32)
    if samples.size == 0:
        raise RuntimeError("The voice model produced no audio for this text.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(output_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(audio.sample_rate))
        w.writeframes(pcm)
    from .synthetic_audio import tag_wav

    tag_wav(output_path)
    seconds = samples.size / float(audio.sample_rate)
    logger.info("kokoro generate: %.2fs audio in %.1fs (voice=%s)", seconds, elapsed, voice.key)
    return KokoroResult(output_path, seconds, elapsed)


def measure_speed(cancel_event: "threading.Event | None" = None) -> KokoroResult:
    """Speak ``core.tts_plan.CALIBRATION_TEXT`` once in the default voice
    and return its speech length and compute time (a few seconds on a CPU).

    The model must already be downloaded: this never starts a download.
    The WAV goes to a temporary file that is removed again. Raises
    ``RuntimeError`` when cancelled through *cancel_event*.
    """
    import tempfile

    from .tts_plan import CALIBRATION_TEXT

    if not is_downloaded():
        raise RuntimeError("The Kokoro voice model is not downloaded yet.")
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="kokoro_speed_")
    os.close(fd)
    try:
        return generate(CALIBRATION_TEXT, DEFAULT_VOICE, tmp, cancel_event=cancel_event)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
