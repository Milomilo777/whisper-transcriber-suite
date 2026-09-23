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

import logging
import os
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
    :func:`is_downloaded` would accept.
    """
    import requests

    target = model_dir()
    if is_downloaded():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f"{MODEL_NAME}.tar.bz2.part"
    staging = target.parent / f"{MODEL_NAME}.staging"
    try:
        with requests.get(MODEL_URL, stream=True, timeout=(10, 60)) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(archive, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Download cancelled.")
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(staging, filter="data")
        inner = staging / MODEL_NAME
        src = inner if inner.is_dir() else staging
        shutil.rmtree(target, ignore_errors=True)
        os.replace(src, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            archive.unlink()
        except OSError:
            pass
    if not is_downloaded():
        raise RuntimeError("The downloaded voice model is incomplete.")
    return target


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

    Long text is fine: sherpa-onnx splits it into sentences itself and
    reports progress (0..1) through *progress_cb* after each one.
    """
    import wave

    import numpy as np  # type: ignore[import-not-found]

    if not text.strip():
        raise ValueError("No text to speak.")
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
    seconds = samples.size / float(audio.sample_rate)
    logger.info("kokoro generate: %.2fs audio in %.1fs (voice=%s)", seconds, elapsed, voice.key)
    return KokoroResult(output_path, seconds, elapsed)
