"""Tests for cross-transcript search (FTS5 + semantic)."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from core import search as sm


# ---------- availability -------------------------------------------------------


def test_semantic_available_false_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    assert sm.semantic_available() is False


def test_semantic_available_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); sentence-transformers pulls torch,
    same risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            sm.semantic_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


# ---------- BLOB pack ----------------------------------------------------------


def test_vector_blob_round_trip():
    vec = [1.0, -2.5, 3.25, 0.0, 1e-3]
    blob = sm._vector_to_blob(vec)
    out = sm._blob_to_vector(blob, len(vec))
    assert len(out) == len(vec)
    for a, b in zip(vec, out):
        assert abs(a - b) < 1e-5


def test_blob_to_vector_returns_empty_on_short_payload():
    assert sm._blob_to_vector(b"", 4) == []
    assert sm._blob_to_vector(b"\x00", 4) == []


# ---------- index_file ---------------------------------------------------------


def _write_transcript(path: Path, segments) -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def _open_db_at(tmp_path: Path):
    conn = sm._open_db(tmp_path / "search.db")
    return conn


def test_index_file_indexes_only_segments_with_text(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "Welcome back."},
        {"start": 1.0, "end": 2.0, "text": ""},
        {"start": 2.0, "end": 3.0, "text": "Second sentence."},
    ])
    conn = _open_db_at(tmp_path)
    try:
        n = sm.index_file(str(p), conn=conn)
        assert n == 2
        rows = conn.execute("SELECT text FROM segments_fts").fetchall()
        texts = sorted(r["text"] for r in rows)
        assert texts == ["Second sentence.", "Welcome back."]
    finally:
        conn.close()


def test_index_file_skips_unchanged_file(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "hello"}])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        # Second call must return 0 (no reindex needed).
        n = sm.index_file(str(p), conn=conn)
        assert n == 0
    finally:
        conn.close()


def test_index_file_reindexes_when_file_changes(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "old text"}])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        # Bump mtime + change content.
        _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "new text"}])
        import os, time
        new_mtime = p.stat().st_mtime + 10
        os.utime(str(p), (new_mtime, new_mtime))
        n = sm.index_file(str(p), conn=conn)
        assert n == 1
        rows = conn.execute("SELECT text FROM segments_fts").fetchall()
        assert rows[0]["text"] == "new text"
    finally:
        conn.close()


def test_index_file_handles_missing_json(tmp_path):
    conn = _open_db_at(tmp_path)
    try:
        # Should not raise.
        n = sm.index_file(str(tmp_path / "missing.json"), conn=conn)
        assert n == 0
    finally:
        conn.close()


def test_index_file_handles_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid", encoding="utf-8")
    conn = _open_db_at(tmp_path)
    try:
        n = sm.index_file(str(p), conn=conn)
        assert n == 0
    finally:
        conn.close()


def test_index_file_io_error_keeps_existing_index(tmp_path, monkeypatch):
    """A transient *read* failure (file briefly locked by AV, network hiccup)
    must not wipe the rows already indexed for that file. The old code
    treated OSError exactly like "no segments": it deleted the FTS rows,
    wrote the embeddings away and marked the file as up to date, so the
    transcript silently vanished from search until its mtime changed."""
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "hello world"}])
    conn = _open_db_at(tmp_path)
    try:
        assert sm.index_file(str(p), conn=conn) == 1
        # Force a reindex attempt, then fail the read itself.
        monkeypatch.setattr(sm, "_file_needs_reindex", lambda _c, _p: True)

        def _locked(*_a, **_k):
            raise OSError("file is locked by another process")

        monkeypatch.setattr(sm.json, "load", _locked)
        assert sm.index_file(str(p), conn=conn) == 0
        rows = conn.execute("SELECT text FROM segments_fts").fetchall()
        assert [r["text"] for r in rows] == ["hello world"], (
            "a transient read failure must not delete existing index rows"
        )
    finally:
        conn.close()


# ---------- FTS5 query ---------------------------------------------------------


def test_search_fts_finds_keyword(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "The cat sat on the mat."},
        {"start": 1.0, "end": 2.0, "text": "The dog ran fast."},
    ])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        hits = sm.search("cat", conn=conn)
        assert len(hits) == 1
        assert "cat" in hits[0].text
        assert hits[0].score > 0
        assert hits[0].segment_index == 0
    finally:
        conn.close()


def test_search_empty_query_returns_empty(tmp_path):
    conn = _open_db_at(tmp_path)
    try:
        assert sm.search("", conn=conn) == []
        assert sm.search("   ", conn=conn) == []
    finally:
        conn.close()


def test_search_no_match_returns_empty(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "hello world"}])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        assert sm.search("zebra", conn=conn) == []
    finally:
        conn.close()


def test_search_tolerates_punctuation_in_query(tmp_path):
    """FTS5 panics on raw `:` in MATCH; our wrapper must quote it."""
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "see also: nothing"}])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        # No assert on result content — just that the call doesn't raise.
        sm.search("see also:", conn=conn)
    finally:
        conn.close()


def test_search_multiword_query_matches_non_adjacent_words(tmp_path):
    """A two-word query must be an AND of terms, not an exact phrase.

    Typing "cat dog" should find a segment containing both words even when
    they are not adjacent; the old whole-query quoting turned it into the
    FTS5 phrase ``"cat dog"`` and returned nothing."""
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "the cat sat beside the dog"},
        {"start": 1.0, "end": 2.0, "text": "the cat sat alone"},
    ])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        hits = sm.search("cat dog", conn=conn)
        assert len(hits) == 1
        assert "dog" in hits[0].text
        # A word that appears in only one of the two is still a single term.
        assert len(sm.search("dog", conn=conn)) == 1
    finally:
        conn.close()


def test_search_fts_score_varies_with_match_quality(tmp_path):
    """bm25() is smaller-is-better AND negative; the old ``max(0.0, rank)``
    clamped every hit to exactly 1.0. Scores must actually differentiate."""
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "cat"},
        {"start": 1.0, "end": 2.0, "text": "the cat sat on the long mat"},
    ])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        hits = sm.search("cat", conn=conn)
        assert len(hits) == 2
        scores = [h.score for h in hits]
        assert len(set(scores)) > 1, (
            f"bm25 scores collapsed to a constant: {scores!r}"
        )
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 < s <= 1.0 for s in scores)
    finally:
        conn.close()


# ---------- semantic with mocked embedder --------------------------------------


class _FakeEmbedder:
    """Deterministic 4-d embedder for tests — returns one-hot vectors by keyword."""

    def __init__(self):
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        t = text.lower()
        if "cat" in t:
            return [1.0, 0.0, 0.0, 0.0]
        if "dog" in t:
            return [0.0, 1.0, 0.0, 0.0]
        if "car" in t:
            return [0.0, 0.0, 1.0, 0.0]
        return [0.0, 0.0, 0.0, 1.0]


def test_semantic_search_ranks_by_cosine(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "a cat sat there"},
        {"start": 1.0, "end": 2.0, "text": "the dog ran fast"},
        {"start": 2.0, "end": 3.0, "text": "a car drove past"},
    ])
    conn = _open_db_at(tmp_path)
    embedder = _FakeEmbedder()
    try:
        sm.index_file(str(p), conn=conn, embedder=embedder)
        hits = sm.search("a cat is friendly", conn=conn, embedder=embedder)
        assert len(hits) == 3
        # Top hit must be the "cat" segment (cosine 1.0 with embedder).
        assert "cat" in hits[0].text
        # Score ordering descending.
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)
    finally:
        conn.close()


def test_semantic_query_skips_dimension_mismatched_rows(tmp_path):
    """Regression: a stored embedding from a different model/dimension than
    the query embedder must be skipped, not silently truncated by zip()
    into a meaningless partial-dot-product score."""
    p = tmp_path / "t.json"
    _write_transcript(p, [
        {"start": 0.0, "end": 1.0, "text": "a cat sat there"},
        {"start": 1.0, "end": 2.0, "text": "stale row from a different model"},
    ])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)  # FTS rows only
        # Row 0: a 4-d embedding matching the current (fake) embedder.
        conn.execute(
            "INSERT INTO embeddings (json_path, segment_index, vector, dim) "
            "VALUES (?, 0, ?, 4)",
            (str(p), sm._vector_to_blob([1.0, 0.0, 0.0, 0.0])),
        )
        # Row 1: an 8-d embedding simulating a stale row indexed by a
        # previously-used, different-dimension model.
        conn.execute(
            "INSERT INTO embeddings (json_path, segment_index, vector, dim) "
            "VALUES (?, 1, ?, 8)",
            (str(p), sm._vector_to_blob([1.0] * 8)),
        )
        conn.commit()
        embedder = _FakeEmbedder()  # embeds every query as a 4-d vector
        hits = sm.search("a cat is friendly", conn=conn, embedder=embedder)
        assert len(hits) == 1
        assert "cat" in hits[0].text
    finally:
        conn.close()


def test_indexed_files_table_tracks_one_row_per_file(tmp_path):
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "x"}])
    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        sm.index_file(str(p), conn=conn)  # idempotent
        rows = conn.execute("SELECT * FROM indexed_files").fetchall()
        assert len(rows) == 1
        assert rows[0]["json_path"] == str(p)
    finally:
        conn.close()


def test_search_falls_back_to_fts_when_semantic_embedder_fails(tmp_path):
    """The module contract is "tries semantic first ... falls back to FTS5
    transparently". A semantic failure (model not installed / weights
    unreadable / encode() error) must not propagate to the caller — the
    keyword index still has the data."""
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "hello world"}])

    class _BrokenEmbedder:
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("model not loaded")

    conn = _open_db_at(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        hits = sm.search("hello", conn=conn, embedder=_BrokenEmbedder())
        assert len(hits) == 1
        assert "hello" in hits[0].text
    finally:
        conn.close()


def test_index_with_embedder_backfills_after_fts_only_index(tmp_path):
    """A file indexed FTS-only (no embedder available yet) must be picked
    up by the first semantic pass. The old code short-circuited on the
    mtime/size cache and never wrote the missing vectors, so semantic
    search stayed permanently empty for that file until it changed."""
    p = tmp_path / "t.json"
    _write_transcript(p, [{"start": 0.0, "end": 1.0, "text": "a cat sat there"}])
    conn = _open_db_at(tmp_path)
    embedder = _FakeEmbedder()
    try:
        sm.index_file(str(p), conn=conn)  # keyword pass first
        n = sm.index_file(str(p), conn=conn, embedder=embedder)
        assert n == 1
        rows = conn.execute("SELECT json_path FROM embeddings").fetchall()
        assert len(rows) == 1, "semantic pass did not backfill embeddings"
        hits = sm.search("a cat is friendly", conn=conn, embedder=embedder)
        assert len(hits) == 1
    finally:
        conn.close()


def test_reindex_all_history_isolates_one_bad_file(tmp_path, monkeypatch):
    """One unreadable/malformed transcript must not abort the whole reindex
    walk — the old code let the first index_file() exception propagate and
    every later transcript silently stayed unindexed."""
    good1 = tmp_path / "good1.json"
    bad = tmp_path / "bad.json"
    good2 = tmp_path / "good2.json"
    _write_transcript(good1, [{"start": 0.0, "end": 1.0, "text": "first"}])
    _write_transcript(bad, [{"start": 0.0, "end": 1.0, "text": "broken"}])
    _write_transcript(good2, [{"start": 0.0, "end": 1.0, "text": "last"}])

    class _FakeHistory:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def list_transcriptions(self, limit: int = 200):
            return [
                {"output_paths": [str(good1)]},
                {"output_paths": [str(bad)]},
                {"output_paths": [str(good2)]},
            ]

    monkeypatch.setattr("core.history.HistoryDB", _FakeHistory)
    monkeypatch.setattr(sm, "user_data_dir", lambda: tmp_path)

    real_index_file = sm.index_file

    def flaky(path, *, conn=None, embedder=None):
        if path == str(bad):
            raise TypeError("malformed segment data")
        return real_index_file(path, conn=conn, embedder=embedder)

    monkeypatch.setattr(sm, "index_file", flaky)
    total = sm.reindex_all_history()
    assert total == 2, "the two good transcripts must still be indexed"
