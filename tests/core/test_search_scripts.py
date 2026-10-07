"""Transcript search across scripts and odd rows (card C2.57).

Covers: CJK words, Arabic/Persian letter forms, ZWNJ, deleted files, odd
segment fields, BOM transcripts, index schema version.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from core import search as sm


def _write(path: Path, segments, *, encoding: str = "utf-8") -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding=encoding)


def _db(tmp_path: Path) -> sqlite3.Connection:
    return sm._open_db(tmp_path / "search.db")


def _index(tmp_path: Path, name: str, texts) -> tuple[sqlite3.Connection, Path]:
    p = tmp_path / name
    _write(p, [{"start": float(i), "end": i + 1.0, "text": t} for i, t in enumerate(texts)])
    conn = _db(tmp_path)
    sm.index_file(str(p), conn=conn)
    return conn, p


# ---------------------------------------------------------------- CJK


@pytest.mark.parametrize("query", ["天气", "公园", "天", "今天天气", "气很"])
def test_cjk_words_inside_a_sentence_are_found(tmp_path, query):
    conn, _ = _index(tmp_path, "t.json", ["今天天气很好我们去公园散步", "another line"])
    try:
        hits = sm.search(query, conn=conn)
        assert [h.segment_index for h in hits] == [0]
    finally:
        conn.close()


def test_cjk_query_that_is_absent_finds_nothing(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["今天天气很好"])
    try:
        assert sm.search("公园", conn=conn) == []
        assert sm.search("公园 天气", conn=conn) == []
    finally:
        conn.close()


def test_japanese_and_korean_substrings_are_found(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["私は東京へ行きます", "저는 서울에 갑니다"])
    try:
        assert [h.segment_index for h in sm.search("東京", conn=conn)] == [0]
        assert [h.segment_index for h in sm.search("서울", conn=conn)] == [1]
    finally:
        conn.close()


def test_mixed_short_and_long_tokens_are_anded(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["hello 世界 again", "hello there"])
    try:
        assert [h.segment_index for h in sm.search("hello 世界", conn=conn)] == [0]
    finally:
        conn.close()


def test_query_with_like_and_quote_characters_is_literal(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ['100% sure "quoted" a_b'])
    try:
        assert len(sm.search("100%", conn=conn)) == 1
        assert len(sm.search('"quoted"', conn=conn)) == 1
        assert len(sm.search("a_b", conn=conn)) == 1
        assert sm.search("a_c", conn=conn) == []
    finally:
        conn.close()


# ---------------------------------------------------------------- Persian / Arabic


def test_arabic_kaf_and_yeh_match_persian_forms(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["این کتاب خیلی خوب است"])
    try:
        # Arabic kaf U+0643 and Arabic yeh U+064A typed instead of U+06A9 / U+06CC.
        assert len(sm.search("كتاب", conn=conn)) == 1
        assert len(sm.search("خيلي", conn=conn)) == 1
        # Alef maksura U+0649 also folds to Persian yeh.
        assert len(sm.search("خىلى", conn=conn)) == 1
    finally:
        conn.close()


def test_persian_query_matches_arabic_letters_in_the_transcript(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["اين كتاب خيلي"])
    try:
        assert len(sm.search("کتاب", conn=conn)) == 1
        assert len(sm.search("خیلی", conn=conn)) == 1
    finally:
        conn.close()


def test_zwnj_form_and_plain_form_match_each_other(tmp_path):
    with_zwnj = "می‌روم"
    without = "میروم"
    conn, _ = _index(tmp_path, "t.json", [f"من {with_zwnj} خانه", f"او {without} مدرسه"])
    try:
        assert sorted(h.segment_index for h in sm.search(without, conn=conn)) == [0, 1]
        assert sorted(h.segment_index for h in sm.search(with_zwnj, conn=conn)) == [0, 1]
    finally:
        conn.close()


def test_arabic_diacritics_and_tatweel_are_ignored(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["مُحَمَّد"])
    try:
        assert len(sm.search("محمد", conn=conn)) == 1
        assert len(sm.search("محـمد", conn=conn)) == 1
    finally:
        conn.close()


def test_latin_case_and_accents_fold(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["Café Münster in Zürich"])
    try:
        assert len(sm.search("cafe", conn=conn)) == 1
        assert len(sm.search("MUNSTER", conn=conn)) == 1
        assert len(sm.search("zurich", conn=conn)) == 1
    finally:
        conn.close()


def test_hit_text_keeps_the_original_characters(tmp_path):
    original = "اين كتاب می‌روم"
    conn, _ = _index(tmp_path, "t.json", [original])
    try:
        hits = sm.search("کتاب", conn=conn)
        assert hits[0].text == original
    finally:
        conn.close()


def test_normalize_is_idempotent():
    for s in ["Café", "كتاب‌ها", "天气", "ＡＢＣ", "", "  x  "]:
        once = sm.normalize_search_text(s)
        assert sm.normalize_search_text(once) == once


# ---------------------------------------------------------------- deleted files


def test_deleted_transcript_is_pruned_from_every_table(tmp_path):
    conn, p = _index(tmp_path, "t.json", ["alpha beta gamma"])
    conn.execute(
        "INSERT INTO embeddings (json_path, segment_index, vector, dim) VALUES (?, 0, ?, 1)",
        (str(p), sm._vector_to_blob([1.0])),
    )
    conn.commit()
    assert len(sm.search("alpha", conn=conn)) == 1
    p.unlink()
    removed = sm.prune_missing_files(conn)
    try:
        assert removed == 1
        assert sm.search("alpha", conn=conn) == []
        for table in ("segments_fts", "embeddings", "indexed_files"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n == 0, table
    finally:
        conn.close()


def test_prune_keeps_files_that_still_exist(tmp_path):
    conn, _ = _index(tmp_path, "t.json", ["alpha beta gamma"])
    try:
        assert sm.prune_missing_files(conn) == 0
        assert len(sm.search("alpha", conn=conn)) == 1
    finally:
        conn.close()


def test_reindex_all_history_prunes_deleted_files(tmp_path, monkeypatch):
    p = tmp_path / "gone.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": "vanishing words"}])

    class _History:
        rows: list = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def list_transcriptions(self, limit=200):
            del limit
            return type(self).rows

    monkeypatch.setattr("core.history.HistoryDB", _History)
    monkeypatch.setattr(sm, "user_data_dir", lambda: tmp_path)
    _History.rows = [{"output_paths": [str(p)]}]
    sm.reindex_all_history()
    assert len(sm.search("vanishing")) == 1
    p.unlink()
    sm.reindex_all_history()
    assert sm.search("vanishing") == []


# ---------------------------------------------------------------- odd rows


def test_null_start_does_not_stop_the_file_from_being_indexed(tmp_path):
    p = tmp_path / "t.json"
    _write(p, [{"start": None, "end": 1.0, "text": "null start"},
               {"start": 2.0, "end": 3.0, "text": "good row"}])
    conn = _db(tmp_path)
    try:
        assert sm.index_file(str(p), conn=conn) == 2
        hits = sm.search("start", conn=conn)
        assert hits[0].start_seconds == 0.0
        assert len(sm.search("good", conn=conn)) == 1
    finally:
        conn.close()


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", '"abc"', '"1,5"', "null", "[]", "{}", "true"])
def test_odd_start_and_end_values_are_coerced(tmp_path, bad):
    p = tmp_path / "t.json"
    p.write_text(
        '[{"start": %s, "end": %s, "text": "odd timing row"}]' % (bad, bad),
        encoding="utf-8",
    )
    conn = _db(tmp_path)
    try:
        assert sm.index_file(str(p), conn=conn) == 1
        hits = sm.search("odd", conn=conn)
        assert len(hits) == 1
        assert isinstance(hits[0].start_seconds, float)
        assert hits[0].start_seconds == hits[0].start_seconds  # not NaN
        assert hits[0].start_seconds not in (float("inf"), float("-inf"))
        assert hits[0].end_seconds == hits[0].end_seconds
    finally:
        conn.close()


def test_nan_start_is_never_stored_as_null(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('[{"start": NaN, "end": 1.0, "text": "nan row"}]', encoding="utf-8")
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        row = conn.execute("SELECT start_seconds, end_seconds FROM segments_fts").fetchone()
        assert row["start_seconds"] is not None
        assert row["end_seconds"] is not None
    finally:
        conn.close()


def test_old_null_start_row_is_read_back_as_zero(tmp_path):
    conn, p = _index(tmp_path, "t.json", ["legacy row"])
    try:
        conn.execute("UPDATE segments_fts SET start_seconds = NULL, end_seconds = NULL")
        conn.commit()
        hits = sm.search("legacy", conn=conn)
        assert hits[0].start_seconds == 0.0
        assert hits[0].end_seconds == 0.0
    finally:
        conn.close()


@pytest.mark.parametrize("text", [123, 1.5, ["a"], {"k": 1}, True])
def test_non_string_text_does_not_raise(tmp_path, text):
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": text},
               {"start": 1.0, "end": 2.0, "text": "still indexed"}])
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        assert len(sm.search("indexed", conn=conn)) == 1
    finally:
        conn.close()


def test_numeric_text_is_searchable(tmp_path):
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": 12345}])
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        assert len(sm.search("12345", conn=conn)) == 1
    finally:
        conn.close()


def test_bom_transcript_is_indexed_and_keeps_rows(tmp_path):
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": "first version"}])
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        assert len(sm.search("first", conn=conn)) == 1
        _write(p, [{"start": 0.0, "end": 1.0, "text": "second version"}], encoding="utf-8-sig")
        new_mtime = p.stat().st_mtime + 10
        os.utime(str(p), (new_mtime, new_mtime))
        assert sm.index_file(str(p), conn=conn) == 1
        assert len(sm.search("second", conn=conn)) == 1
        assert sm.search("first", conn=conn) == []
    finally:
        conn.close()


def test_undecodable_transcript_keeps_existing_rows_and_retries(tmp_path):
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": "kept words"}])
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        p.write_bytes(b'[{"text": "\xff\xfe\x00bad"}]')
        new_mtime = p.stat().st_mtime + 10
        os.utime(str(p), (new_mtime, new_mtime))
        assert sm.index_file(str(p), conn=conn) == 0
        assert len(sm.search("kept", conn=conn)) == 1
        # Not marked as indexed: the next pass tries again.
        assert sm._file_needs_reindex(conn, str(p)) is True
    finally:
        conn.close()


# ---------------------------------------------------------------- dialog helper


def test_fmt_hms_survives_non_finite_values():
    from app.dialogs.search_dialog import _fmt_hms

    assert _fmt_hms(float("inf")) == "00:00:00"
    assert _fmt_hms(float("-inf")) == "00:00:00"
    assert _fmt_hms(float("nan")) == "00:00:00"
    assert _fmt_hms(75.9) == "00:01:15"
    assert _fmt_hms(-5) == "00:00:00"


# ---------------------------------------------------------------- schema version


def test_schema_version_is_set_and_old_index_rebuilds_once(tmp_path):
    db = tmp_path / "search.db"
    # An index as the previous release created it.
    old = sqlite3.connect(str(db))
    old.executescript(
        """
        CREATE VIRTUAL TABLE segments_fts USING fts5(
            json_path UNINDEXED, segment_index UNINDEXED, text,
            start_seconds UNINDEXED, end_seconds UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2');
        CREATE TABLE embeddings (json_path TEXT NOT NULL, segment_index INTEGER NOT NULL,
            vector BLOB NOT NULL, dim INTEGER NOT NULL, PRIMARY KEY (json_path, segment_index));
        CREATE TABLE indexed_files (json_path TEXT PRIMARY KEY, mtime REAL, size INTEGER);
        """
    )
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": "今天天气很好"}])
    st = p.stat()
    old.execute("INSERT INTO indexed_files VALUES (?, ?, ?)", (str(p), st.st_mtime, st.st_size))
    old.execute(
        "INSERT INTO segments_fts (json_path, segment_index, text, start_seconds, end_seconds)"
        " VALUES (?, 0, '今天天气很好', 0, 1)", (str(p),))
    old.commit()
    old.close()

    conn = sm._open_db(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sm.SCHEMA_VERSION
        # The stale index is gone, so the file is picked up again ...
        assert conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 0
        assert sm.index_file(str(p), conn=conn) == 1
        assert len(sm.search("天气", conn=conn)) == 1
    finally:
        conn.close()

    # ... and a second open must NOT rebuild again.
    conn = sm._open_db(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 1
        assert sm.index_file(str(p), conn=conn) == 0
        assert len(sm.search("天气", conn=conn)) == 1
    finally:
        conn.close()


def test_fresh_database_gets_the_schema_version(tmp_path):
    conn = _db(tmp_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sm.SCHEMA_VERSION
    finally:
        conn.close()


# ---------------------------------------------------------------- no-trigram fallback


def test_search_works_when_trigram_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "_trigram_supported", lambda: False)
    p = tmp_path / "t.json"
    _write(p, [{"start": 0.0, "end": 1.0, "text": "今天天气很好我们去公园"},
               {"start": 1.0, "end": 2.0, "text": "Hello wide world"}])
    conn = _db(tmp_path)
    try:
        sm.index_file(str(p), conn=conn)
        assert [h.segment_index for h in sm.search("公园", conn=conn)] == [0]
        assert [h.segment_index for h in sm.search("wide", conn=conn)] == [1]
        assert sm.search("zzz", conn=conn) == []
    finally:
        conn.close()
