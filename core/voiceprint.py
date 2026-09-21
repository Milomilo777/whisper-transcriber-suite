"""Cross-file speaker fingerprint database (v0.8 Phase 3).

Enrolling a speaker once should let every future transcription
label that voice as the same person — instead of the per-file
``"SPEAKER_00"`` / ``"SPEAKER_01"`` placeholders the diariser
emits today.

The pipeline:

  1. **Enrol** — user picks a saved transcript + a segment that's
     "definitely Alice". :func:`enrol_speaker` extracts the audio
     for that segment, runs it through ``pyannote/embedding``
     (TDNN+SincNet, 512-d vector), and stores ``(name, vector)``
     in ``voices.db``.
  2. **Match** — after each diarisation pass, run every cluster
     centroid through the same embedder, compare via cosine
     similarity to all enrolled voices, and relabel matching
     clusters from ``"SPEAKER_NN"`` to ``"Alice"``.

When ``pyannote.audio`` isn't installed, every public entry point
either returns an empty list or raises :class:`VoiceprintUnavailable`
so the diariser keeps working without speaker names.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ._gc_import_guard import gc_disabled_import
from .config import user_data_dir

logger = logging.getLogger(__name__)


VOICES_DB_NAME = "voices.db"
DEFAULT_EMBEDDING_MODEL = "pyannote/embedding"
DEFAULT_MATCH_THRESHOLD = 0.65  # cosine similarity; tune as needed


# ---------------------------------------------------------------- availability


class VoiceprintUnavailable(RuntimeError):
    """Raised when pyannote.audio isn't installed."""


def runtime_available() -> bool:
    """True iff pyannote.audio imports cleanly.

    pyannote.audio pulls in torch, a heavy C-extension package -- see
    core/_gc_import_guard.py for why the import runs under a shared,
    process-wide GC-disable guard.
    """
    with gc_disabled_import():
        try:
            import pyannote.audio  # type: ignore[import-not-found] # noqa: F401
        except ImportError:
            return False
        else:
            return True


def runtime_availability_reason() -> str:
    if runtime_available():
        return ""
    return (
        "pyannote.audio not installed — `pip install pyannote.audio` to "
        "enable cross-file speaker fingerprinting. The diariser still "
        "produces per-file SPEAKER_NN labels without it."
    )


# ---------------------------------------------------------------- storage


def voices_db_path() -> Path:
    return user_data_dir() / VOICES_DB_NAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vector BLOB NOT NULL,
    dim INTEGER NOT NULL,
    source TEXT,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_voices_name ON voices(name);
"""


def _open_db(path: Path | None = None) -> sqlite3.Connection:
    p = path if path is not None else voices_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript(_SCHEMA)
    return conn


@dataclass(frozen=True)
class EnrolledVoice:
    id: int
    name: str
    vector: list[float]
    source: str = ""


def list_voices(*, conn: sqlite3.Connection | None = None) -> list[EnrolledVoice]:
    owns = conn is None
    conn = conn or _open_db()
    try:
        rows = conn.execute(
            "SELECT id, name, vector, dim, source FROM voices ORDER BY name"
        ).fetchall()
        return [
            EnrolledVoice(
                id=int(r["id"]),
                name=str(r["name"]),
                vector=_blob_to_vector(bytes(r["vector"]), int(r["dim"])),
                source=str(r["source"] or ""),
            )
            for r in rows
        ]
    finally:
        if owns:
            conn.close()


def delete_voice(voice_id: int, *, conn: sqlite3.Connection | None = None) -> None:
    owns = conn is None
    conn = conn or _open_db()
    try:
        with conn:
            conn.execute("DELETE FROM voices WHERE id=?", (voice_id,))
    finally:
        if owns:
            conn.close()


def enrol_with_vector(
    name: str,
    vector: list[float],
    *,
    source: str = "",
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist a pre-computed embedding under ``name``.

    Useful for tests + for callers that already have an embedding
    from another source. The full pipeline (:func:`enrol_speaker`)
    builds the vector via pyannote first.
    """
    if not name.strip():
        raise ValueError("Voice name must be non-empty")
    if not vector:
        raise ValueError("Vector must be non-empty")
    # A NaN/Inf embedding (pyannote on a corrupt or truncated clip)
    # would be stored as a permanently unmatchable row -- the user
    # would think the enrolment succeeded. Reject at the DB gate.
    try:
        finite = all(math.isfinite(x) for x in vector)
    except TypeError:
        raise ValueError("Vector must contain only finite values")
    if not finite:
        raise ValueError("Vector must contain only finite values")
    import time
    owns = conn is None
    conn = conn or _open_db()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO voices (name, vector, dim, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name.strip(), _vector_to_blob(vector), len(vector),
                 source, int(time.time())),
            )
            return int(cur.lastrowid or 0)
    finally:
        if owns:
            conn.close()


def enrol_speaker(
    name: str,
    audio_path: str,
    *,
    start_seconds: float = 0.0,
    end_seconds: float = 0.0,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Embed a clip + store it under ``name``.

    Raises :class:`VoiceprintUnavailable` when pyannote isn't
    installed; the UI surfaces that as a "feature off" message.
    """
    if not runtime_available():
        raise VoiceprintUnavailable(runtime_availability_reason())
    vector = _embed_audio_window(audio_path, start_seconds, end_seconds)
    return enrol_with_vector(name, vector, source=audio_path, conn=conn)


def _embed_audio_window(
    audio_path: str, start: float, end: float
) -> list[float]:
    """Run pyannote on a clip and return a 512-d vector."""
    from pyannote.audio import Inference  # type: ignore[import-not-found]
    inference = Inference(DEFAULT_EMBEDDING_MODEL, window="whole")
    if end > start:
        embedding = inference.crop(audio_path, {"start": start, "end": end})
    else:
        embedding = inference(audio_path)
    return [float(x) for x in (embedding.flatten().tolist()
                                if hasattr(embedding, "flatten") else embedding)]


# ---------------------------------------------------------------- matching


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in pure Python (no numpy dep)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def match_vector(
    vector: list[float],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    voices: Iterable[EnrolledVoice] | None = None,
    conn: sqlite3.Connection | None = None,
) -> EnrolledVoice | None:
    """Return the best-matching enrolled voice above ``threshold`` or None."""
    candidates = list(voices) if voices is not None else list_voices(conn=conn)
    best: EnrolledVoice | None = None
    best_score = -1.0
    for v in candidates:
        if len(v.vector) != len(vector):
            # Voices enrolled under a different embedding model (e.g.
            # a 512-d pyannote/embedding row vs a 256-d upgrade) are
            # not comparable. cosine() reports 0.0 for a dimension
            # mismatch, which at threshold <= 0 would "match" the
            # wrong person -- skip them rather than score them.
            logger.debug(
                "Skipping voice %r: embedding dim %d != query dim %d",
                v.name, len(v.vector), len(vector),
            )
            continue
        score = cosine(vector, v.vector)
        if score > best_score:
            best_score = score
            best = v
    if best is None or best_score < threshold:
        return None
    return best


def relabel_segments(
    segments: list[dict[str, Any]],
    *,
    cluster_vectors: dict[str, list[float]],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    voices: Iterable[EnrolledVoice] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Rewrite ``seg["speaker"]`` for every cluster that matches an enrolled voice.

    ``cluster_vectors`` maps the original cluster label (e.g.
    ``"SPEAKER_00"``) to a centroid vector for that cluster. We
    look up each cluster's best enrolled match; matching clusters
    have every segment relabelled in place. Unmatched clusters
    keep their original label.

    Returns the count of segments whose speaker label changed.
    """
    candidates = list(voices) if voices is not None else list_voices(conn=conn)
    if not candidates:
        return 0
    relabel_map: dict[str, str] = {}
    for cluster, vec in cluster_vectors.items():
        match = match_vector(vec, threshold=threshold, voices=candidates)
        if match is not None:
            relabel_map[cluster] = match.name
    if not relabel_map:
        return 0
    changed = 0
    for seg in segments:
        spk = (seg.get("speaker") or "").strip()
        if spk in relabel_map and relabel_map[spk] != spk:
            seg["speaker"] = relabel_map[spk]
            changed += 1
    return changed


# ---------------------------------------------------------------- BLOB pack


def _vector_to_blob(vec: Iterable[float]) -> bytes:
    return b"".join(struct.pack("<f", float(x)) for x in vec)


def _blob_to_vector(blob: bytes, dim: int) -> list[float]:
    if len(blob) < dim * 4:
        return []
    return list(struct.unpack(f"<{dim}f", blob[: dim * 4]))
