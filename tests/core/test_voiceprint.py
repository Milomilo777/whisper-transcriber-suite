"""Tests for the cross-file speaker fingerprint DB."""
from __future__ import annotations

import sys

import pytest

from core import voiceprint as vp


# ---------- availability -------------------------------------------------------


def test_runtime_available_false_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    assert vp.runtime_available() is False
    assert "pyannote" in vp.runtime_availability_reason()


def test_runtime_available_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); pyannote.audio pulls torch, same
    risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            vp.runtime_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_enrol_speaker_raises_when_pyannote_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "runtime_available", lambda: False)
    with pytest.raises(vp.VoiceprintUnavailable):
        vp.enrol_speaker("Alice", str(tmp_path / "audio.wav"))


# ---------- BLOB pack ----------------------------------------------------------


def test_vector_blob_round_trip():
    vec = [1.0, -2.5, 3.25, 0.0, 1e-3]
    blob = vp._vector_to_blob(vec)
    out = vp._blob_to_vector(blob, len(vec))
    assert len(out) == len(vec)
    for a, b in zip(vec, out):
        assert abs(a - b) < 1e-5


# ---------- cosine -------------------------------------------------------------


def test_cosine_identical_vectors_is_one():
    a = [0.1, 0.2, 0.3, -0.4]
    assert vp.cosine(a, a) == pytest.approx(1.0, abs=1e-6)


def test_cosine_orthogonal_vectors_is_zero():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert vp.cosine(a, b) == pytest.approx(0.0, abs=1e-6)


def test_cosine_opposite_vectors_is_minus_one():
    a = [1.0, 2.0, 3.0]
    b = [-1.0, -2.0, -3.0]
    assert vp.cosine(a, b) == pytest.approx(-1.0, abs=1e-6)


def test_cosine_empty_returns_zero():
    assert vp.cosine([], []) == 0.0
    assert vp.cosine([1.0], []) == 0.0


def test_cosine_mismatched_dim_returns_zero():
    assert vp.cosine([1.0, 2.0], [1.0]) == 0.0


# ---------- enrol_with_vector + list_voices -----------------------------------


def _conn(tmp_path):
    return vp._open_db(tmp_path / "voices.db")


def test_enrol_with_vector_persists(tmp_path):
    conn = _conn(tmp_path)
    try:
        vid = vp.enrol_with_vector("Alice", [1.0, 0.0, 0.0], conn=conn)
        assert vid > 0
        voices = vp.list_voices(conn=conn)
        assert len(voices) == 1
        assert voices[0].name == "Alice"
        assert voices[0].vector[0] == pytest.approx(1.0)
    finally:
        conn.close()


def test_enrol_rejects_empty_name(tmp_path):
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            vp.enrol_with_vector("   ", [1.0, 0.0], conn=conn)
    finally:
        conn.close()


def test_enrol_rejects_empty_vector(tmp_path):
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            vp.enrol_with_vector("Alice", [], conn=conn)
    finally:
        conn.close()


def test_enrol_rejects_non_finite_vector(tmp_path):
    """A NaN/Inf embedding is permanently unmatchable -- persisting it
    would silently tell the user the enrolment succeeded."""
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            vp.enrol_with_vector("Alice", [1.0, float("nan")], conn=conn)
        with pytest.raises(ValueError):
            vp.enrol_with_vector("Bob", [float("inf"), 0.0], conn=conn)
        assert vp.list_voices(conn=conn) == []
    finally:
        conn.close()


def test_delete_voice_removes_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        vid = vp.enrol_with_vector("Bob", [0.0, 1.0, 0.0], conn=conn)
        vp.delete_voice(vid, conn=conn)
        assert vp.list_voices(conn=conn) == []
    finally:
        conn.close()


# ---------- match_vector -------------------------------------------------------


def test_match_vector_returns_best_above_threshold(tmp_path):
    conn = _conn(tmp_path)
    try:
        vp.enrol_with_vector("Alice", [1.0, 0.0, 0.0], conn=conn)
        vp.enrol_with_vector("Bob", [0.0, 1.0, 0.0], conn=conn)
        # Query close to Alice's vector.
        m = vp.match_vector([0.9, 0.1, 0.0], conn=conn, threshold=0.5)
        assert m is not None
        assert m.name == "Alice"
    finally:
        conn.close()


def test_match_vector_returns_none_below_threshold(tmp_path):
    conn = _conn(tmp_path)
    try:
        vp.enrol_with_vector("Alice", [1.0, 0.0, 0.0], conn=conn)
        # Orthogonal query: cosine 0.0 < threshold 0.5.
        assert vp.match_vector([0.0, 1.0, 0.0], conn=conn, threshold=0.5) is None
    finally:
        conn.close()


def test_match_vector_with_no_enrolled_voices_returns_none(tmp_path):
    conn = _conn(tmp_path)
    try:
        assert vp.match_vector([1.0, 0.0], conn=conn) is None
    finally:
        conn.close()


def test_match_vector_ignores_dimension_mismatched_voices(tmp_path):
    """Vectors from a different embedding model must never match.

    cosine() returns 0.0 for a dimension mismatch, so at a threshold
    of 0.0 the old code returned the mismatched voice as a "match" --
    the exact wrong-name failure this module exists to avoid."""
    conn = _conn(tmp_path)
    try:
        vp.enrol_with_vector("Alice", [1.0, 0.0], conn=conn)  # 2-d row
        # 3-d query against a 2-d-only DB: no match, not Alice.
        assert vp.match_vector([1.0, 0.0, 0.0], conn=conn, threshold=0.0) is None
        # Same-dimension matching still works at the same threshold.
        vp.enrol_with_vector("Bob", [1.0, 0.0, 0.0], conn=conn)
        m = vp.match_vector([1.0, 0.0, 0.0], conn=conn, threshold=0.0)
        assert m is not None
        assert m.name == "Bob"
    finally:
        conn.close()


# ---------- relabel_segments ---------------------------------------------------


def test_relabel_segments_renames_matching_clusters(tmp_path):
    conn = _conn(tmp_path)
    try:
        vp.enrol_with_vector("Alice", [1.0, 0.0, 0.0], conn=conn)
        vp.enrol_with_vector("Bob", [0.0, 1.0, 0.0], conn=conn)
        segs = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "text": "b", "speaker": "SPEAKER_01"},
            {"start": 2.0, "end": 3.0, "text": "c", "speaker": "SPEAKER_00"},
        ]
        clusters = {
            "SPEAKER_00": [1.0, 0.0, 0.0],   # Alice
            "SPEAKER_01": [0.0, 1.0, 0.0],   # Bob
        }
        changed = vp.relabel_segments(segs, cluster_vectors=clusters,
                                       threshold=0.5, conn=conn)
        assert changed == 3
        assert segs[0]["speaker"] == "Alice"
        assert segs[1]["speaker"] == "Bob"
        assert segs[2]["speaker"] == "Alice"
    finally:
        conn.close()


def test_relabel_segments_leaves_unknown_clusters_alone(tmp_path):
    conn = _conn(tmp_path)
    try:
        vp.enrol_with_vector("Alice", [1.0, 0.0, 0.0], conn=conn)
        segs = [
            {"speaker": "SPEAKER_00"},
            {"speaker": "SPEAKER_99"},
        ]
        clusters = {
            "SPEAKER_00": [1.0, 0.0, 0.0],   # → Alice
            "SPEAKER_99": [0.0, 0.0, 1.0],   # orthogonal → no match
        }
        changed = vp.relabel_segments(segs, cluster_vectors=clusters,
                                       threshold=0.5, conn=conn)
        assert changed == 1
        assert segs[0]["speaker"] == "Alice"
        assert segs[1]["speaker"] == "SPEAKER_99"
    finally:
        conn.close()


def test_relabel_segments_with_no_enrolled_voices_is_noop(tmp_path):
    conn = _conn(tmp_path)
    try:
        segs = [{"speaker": "SPEAKER_00"}]
        clusters = {"SPEAKER_00": [1.0, 0.0]}
        changed = vp.relabel_segments(segs, cluster_vectors=clusters, conn=conn)
        assert changed == 0
        assert segs[0]["speaker"] == "SPEAKER_00"
    finally:
        conn.close()
