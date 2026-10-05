"""Score the app's local Whisper models per language on public FLEURS speech (CPU).

Data: Google FLEURS (CC-BY-4.0, no account), test split, read straight from the
Hugging Face dataset repo ``google/fleurs``. Transcription goes through the app's own
``FasterWhisperBackend`` (``load`` -> ``transcribe_to_segments``), the same calls the
worker makes. Scoring is a stdlib Levenshtein: WER on words, CER on characters for
languages written without spaces (zh, ja, th). No third-party package is needed beyond
what the app already requires.

Utterance choice is deterministic: the tar archive lists files in sorted-name order, so
the script takes the first N files (in that order) whose sentence id has not been taken
yet. Only the start of the archive is downloaded, never the whole file.

Usage:
    python tools/benchmark_multilingual.py --languages fa --models tiny base -n 10

Output: one CSV row per (language, model, utterance) in ``--out``
(default ``docs/evaluations/benchmark-v1/results.csv``). Audio and model files go to a
cache outside the repository (``--cache``, default ``<app cache>/benchmark``).
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import tarfile
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
FLEURS_BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"

# language code (Whisper) -> FLEURS folder, scoring metric
LANGUAGES: dict[str, tuple[str, str]] = {
    "fa": ("fa_ir", "wer"),
    "ar": ("ar_eg", "wer"),
    "zh": ("cmn_hans_cn", "cer"),
    "ja": ("ja_jp", "cer"),
    "ru": ("ru_ru", "wer"),
    "hi": ("hi_in", "wer"),
    "es": ("es_419", "wer"),
    "tr": ("tr_tr", "wer"),
}

CSV_FIELDS = [
    "language", "model", "utterance_id", "metric", "score",
    "ref_len", "errors", "audio_s", "decode_s", "rtf",
]

_UTTERANCE_FILE = re.compile(r"^test/(\d+)\.wav$")

# Arabic harakat, superscript alef, tatweel: dropped before scoring (Persian and Arabic
# references are written without them; Whisper output sometimes adds them).
_ARABIC_MARKS = {chr(c) for c in range(0x064B, 0x0660)} | {"\u0670", "\u0640"}
# Apostrophes are deleted, not turned into a space, so "T\u00fcrkiye'de" stays one word.
_APOSTROPHES = {"'", "\u2019", "\u02bc"}
_FOLD = {
    "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
    "\u0649": "\u06cc",  # alef maksura -> Persian yeh
    "\u0643": "\u06a9",  # Arabic kaf -> Persian kaf
    "\u200c": " ",       # zero-width non-joiner counts as a word break
    "\u200d": "",        # zero-width joiner is dropped
}


def normalize(text: str, language: str = "") -> str:
    """Normalise text for scoring (applied identically to reference and hypothesis).

    NFC, case folding (Turkish I/i handled before ``casefold``), digits of any script to
    ASCII, Arabic marks / tatweel dropped, Arabic yeh/kaf folded to the Persian letters,
    ZWNJ read as a space, apostrophes and invisible format characters (zero-width space,
    LRM/RLM, BOM) deleted, other punctuation and symbols removed, whitespace collapsed.
    Hindi vowel signs and other combining marks are kept (they carry the letters).
    """
    text = unicodedata.normalize("NFC", text)
    if language == "tr":
        text = text.replace("I", "\u0131").replace("\u0130", "i")
    text = text.casefold()
    out: list[str] = []
    for ch in text:
        if ch in _ARABIC_MARKS or ch in _APOSTROPHES:
            continue
        ch = _FOLD.get(ch, ch)
        cat = unicodedata.category(ch[:1]) if ch else ""
        if cat == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        elif cat == "Cf":
            continue  # zero-width space, LRM/RLM, BOM: invisible, never part of a word
        elif cat and cat[0] in "PS":
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def edit_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """Levenshtein distance (insert, delete, substitute all cost 1), two-row DP."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (x != y),
            ))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class Score:
    metric: str
    errors: int
    ref_len: int

    @property
    def value(self) -> float:
        """Error rate. An empty reference scores 0.0 for an empty hypothesis, else 1.0."""
        if self.ref_len == 0:
            return 0.0 if self.errors == 0 else 1.0
        return self.errors / self.ref_len


def score(reference: str, hypothesis: str, metric: str, language: str = "") -> Score:
    """WER (``metric='wer'``, words) or CER (``'cer'``, characters without spaces)."""
    if metric not in ("wer", "cer"):
        raise ValueError(f"metric must be 'wer' or 'cer', not {metric!r}")
    ref = normalize(reference, language)
    hyp = normalize(hypothesis, language)
    if metric == "cer":
        ref_units: list[str] = list(ref.replace(" ", ""))
        hyp_units: list[str] = list(hyp.replace(" ", ""))
    else:
        ref_units, hyp_units = ref.split(), hyp.split()
    return Score(metric, edit_distance(ref_units, hyp_units), len(ref_units))


def read_tsv(raw: str) -> dict[str, tuple[str, str]]:
    """Map ``<id>.wav`` -> (sentence id, raw transcription) from a FLEURS TSV."""
    rows: dict[str, tuple[str, str]] = {}
    for row in csv.reader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(row) >= 3 and row[1].endswith(".wav"):
            rows[row[1]] = (row[0], row[2])
    return rows


def _get(url: str):
    return urllib.request.urlopen(url, timeout=120)  # noqa: S310 - fixed https host


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file and rename, so a killed run never leaves a partial cache file."""
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def _wav_complete(path: Path) -> bool:
    """True when a cached wav exists and holds as many data bytes as its header declares."""
    if not path.exists():
        return False
    try:
        _rate, declared, present = _wav_header(path.read_bytes())
    except ValueError:
        return False
    return declared > 0 and present >= declared


def fetch_utterances(language: str, count: int, cache: Path) -> list[tuple[str, Path, str]]:
    """Return ``count`` (utterance id, wav path, reference text), downloading as needed."""
    folder = LANGUAGES[language][0]
    lang_dir = cache / "fleurs" / folder
    lang_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = lang_dir / "test.tsv"
    if not tsv_path.exists():
        _write_atomic(tsv_path, _get(f"{FLEURS_BASE}/{folder}/test.tsv").read())
    rows = read_tsv(tsv_path.read_text(encoding="utf-8"))

    picked: list[tuple[str, Path, str]] = []
    seen_sentences: set[str] = set()
    resp = _get(f"{FLEURS_BASE}/{folder}/audio/test.tar.gz")
    try:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for member in tar:
                m = _UTTERANCE_FILE.match(member.name)
                if not m or not member.isfile():
                    continue
                name = f"{m.group(1)}.wav"
                if name not in rows or rows[name][0] in seen_sentences:
                    continue
                seen_sentences.add(rows[name][0])
                wav_path = lang_dir / name
                if not _wav_complete(wav_path):
                    fh = tar.extractfile(member)
                    if fh is None:
                        raise RuntimeError(f"cannot read {member.name} from the archive")
                    _write_atomic(wav_path, fh.read())
                picked.append((m.group(1), wav_path, rows[name][1]))
                if len(picked) >= count:
                    break
    finally:
        resp.close()
    if len(picked) < count:
        raise RuntimeError(f"{language}: only {len(picked)} of {count} utterances found")
    return picked


def _wav_header(data: bytes) -> tuple[int, int, int]:
    """Return (byte rate, declared data size, bytes actually present after the data header)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, byte_rate = 12, 0
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if chunk_id == b"fmt ":
            byte_rate = int.from_bytes(data[pos + 16:pos + 20], "little")
        elif chunk_id == b"data":
            if byte_rate <= 0:
                raise ValueError("data chunk before fmt chunk")
            return byte_rate, size, len(data) - pos - 8
        pos += 8 + size + (size & 1)
    raise ValueError("no data chunk")


def wav_seconds(data: bytes) -> float:
    """Duration of a RIFF/WAVE file from its header (also IEEE-float WAVs, which the
    stdlib ``wave`` module refuses; FLEURS ships 32-bit float files)."""
    byte_rate, declared, present = _wav_header(data)
    return min(declared, present) / byte_rate


def audio_seconds(wav_path: Path) -> float:
    seconds = wav_seconds(wav_path.read_bytes())
    if seconds <= 0:
        raise RuntimeError(f"{wav_path.name} holds no audio")
    return seconds


def load_backend(slug: str, cache: Path):
    """Build the app's faster-whisper backend for ``slug`` on CPU, models under ``cache``."""
    sys.path.insert(0, str(ROOT))
    import copy

    from core import config as app_config
    from core.backends import faster_whisper_be
    from core.hub import model_folder_for
    from core.model_manager import resolve_model_entry

    entry = resolve_model_entry(slug)
    if entry is None:
        raise SystemExit(f"unknown model slug: {slug}")
    hub = cache / "models"
    cfg = copy.deepcopy(app_config.DEFAULT_CONFIG)
    cfg["model"] = entry
    cfg["hub_folder"] = str(hub)
    cfg["model_path"] = str(model_folder_for(hub, entry["name"]))
    cfg["device"] = "cpu"
    cfg["compute_type"] = "int8"
    # The backend reads its settings through load_config(); hand it this private dict so
    # the benchmark never reads or writes the user's real config file.
    faster_whisper_be.load_config = lambda *a, **k: copy.deepcopy(cfg)  # type: ignore[assignment]
    backend = faster_whisper_be.FasterWhisperBackend()
    t0 = time.perf_counter()
    backend.load()
    return backend, time.perf_counter() - t0


def run(languages: Iterable[str], models: Iterable[str], count: int, cache: Path,
        out: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    utterances = {lang: fetch_utterances(lang, count, cache) for lang in languages}
    out.parent.mkdir(parents=True, exist_ok=True)
    # Rows are written as they are produced, so an interrupted run keeps what it measured.
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for slug in models:
            backend, load_s = load_backend(slug, cache)
            print(f"model {slug}: loaded in {load_s:.1f} s", flush=True)
            try:
                for lang, items in utterances.items():
                    metric = LANGUAGES[lang][1]
                    for uid, wav, reference in items:
                        dur = audio_seconds(wav)
                        t0 = time.perf_counter()
                        segments, _info = backend.transcribe_to_segments(
                            str(wav), language=lang, duration=dur)
                        decode_s = time.perf_counter() - t0
                        hypothesis = " ".join(s["text"] for s in segments)
                        sc = score(reference, hypothesis, metric, lang)
                        row = {
                            "language": lang, "model": slug, "utterance_id": uid,
                            "metric": metric, "score": f"{sc.value:.4f}",
                            "ref_len": sc.ref_len, "errors": sc.errors,
                            "audio_s": f"{dur:.2f}", "decode_s": f"{decode_s:.2f}",
                            "rtf": f"{decode_s / dur:.3f}",
                        }
                        rows.append(row)
                        writer.writerow(row)
                        fh.flush()
                        print(f"  {lang} {slug} {uid}: {metric} {sc.value:.3f} "
                              f"rtf {decode_s / dur:.2f}", flush=True)
            finally:
                backend.unload()
    return rows


def summarise(rows: Sequence[dict[str, object]]) -> str:
    """One line per (language, model): corpus-level error rate and RTF (total decode time
    over total audio time, the figure the README table uses)."""
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for r in rows:
        groups.setdefault((str(r["language"]), str(r["model"])), []).append(r)
    lines = []
    for (lang, model), items in groups.items():
        errors = sum(int(str(r["errors"])) for r in items)
        ref_len = sum(int(str(r["ref_len"])) for r in items)
        audio = sum(float(str(r["audio_s"])) for r in items)
        decode = sum(float(str(r["decode_s"])) for r in items)
        rate = errors / ref_len if ref_len else 0.0
        rtf = decode / audio if audio else 0.0
        lines.append(f"{lang} {model}: {items[0]['metric']} {rate:.3f} "
                     f"({errors}/{ref_len}) rtf {rtf:.2f} n={len(items)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--languages", nargs="+", default=["fa"], choices=sorted(LANGUAGES))
    ap.add_argument("--models", nargs="+", default=["tiny", "base"])
    ap.add_argument("-n", "--count", type=int, default=10, help="utterances per language")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "docs" / "evaluations" / "benchmark-v1" / "results.csv")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing --out file (refused by default)")
    ap.add_argument("--cache", type=Path, default=None,
                    help="audio + model cache outside the repo")
    args = ap.parse_args(argv)
    cache = args.cache
    if cache is None:
        sys.path.insert(0, str(ROOT))
        from core.hub import default_hub_folder
        cache = default_hub_folder().parent / "benchmark"
    if ROOT in cache.resolve().parents or cache.resolve() == ROOT:
        raise SystemExit("--cache must be outside the repository")
    if args.out.exists() and not args.force:
        raise SystemExit(f"{args.out} exists; pass --force to overwrite it or choose --out")
    rows = run(args.languages, args.models, args.count, cache, args.out)
    print(summarise(rows))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
