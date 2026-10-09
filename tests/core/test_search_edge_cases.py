"""Edge cases for the transcript search index (``core.search``).

Covers query words that look like FTS5 operators, a very long word, text
with bidi control characters, transcript files of the wrong shape or that
turn unparseable, and a history row whose ``output_paths`` is not valid
JSON. Hermetic: a throw-away index database under ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import search as sm


def _write(path: Path, segments) -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def _segment(text: str, start: float = 0.0, end: float = 1.0) -> dict:
    return {"text": text, "start": start, "end": end}


@pytest.fixture
def conn(tmp_path):
    connection = sm._open_db(tmp_path / "search.db")
    yield connection
    connection.close()


def _index(conn, path: Path, *texts: str) -> None:
    _write(path, [_segment(t, float(i), i + 1.0) for i, t in enumerate(texts)])
    sm.index_file(str(path), conn=conn)


# --- query words that look like FTS5 syntax ---------------------------------


def test_operator_words_in_a_query_are_ordinary_words(tmp_path, conn):
    _index(conn, tmp_path / "t.json", "cat is good", "tom said match OR here")

    # A literal "OR" / "NOT" word must be matched as text, never as an operator.
    assert sm.search("cat OR dog", conn=conn) == []
    assert sm.search("cat NOT dog", conn=conn) == []
    hits = sm.search("match OR here", conn=conn)
    assert [h.text for h in hits] == ["tom said match OR here"]


def test_a_very_long_word_is_indexed_and_found(tmp_path, conn):
    long_word = "a" * 10000
    _index(conn, tmp_path / "t.json", long_word)
    assert len(sm.search(long_word, conn=conn)) == 1


# --- bidi control characters -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("‏سلام‏ دنیا", "سلام"),
        ("‫دنیا‬ سلام", "دنیا"),
        ("‫English‬ words", "english"),
        ("hello‎world", "world"),
    ],
)
def test_bidi_marks_in_the_text_do_not_hide_a_word(tmp_path, conn, text, query):
    _index(conn, tmp_path / "t.json", text)
    assert len(sm.search(query, conn=conn)) == 1


# --- transcript files of an unexpected shape ---------------------------------


@pytest.mark.parametrize(
    "payload",
    ['{"hello": "world"}', '["a", "b"]', "123", "null", ""],
)
def test_a_transcript_that_is_not_a_list_of_segments_adds_nothing(
    tmp_path, conn, payload
):
    path = tmp_path / "t.json"
    path.write_text(payload, encoding="utf-8")
    assert sm.index_file(str(path), conn=conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM segments_fts").fetchone()[0] == 0


def test_items_that_are_not_objects_are_skipped_not_fatal(tmp_path, conn):
    path = tmp_path / "t.json"
    _write(path, ["stray", 7, None, _segment("kept words")])
    assert sm.index_file(str(path), conn=conn) == 1
    assert len(sm.search("kept", conn=conn)) == 1


def test_a_transcript_that_becomes_unparseable_drops_its_stale_hits(tmp_path, conn):
    path = tmp_path / "t.json"
    _index(conn, path, "cat")
    assert len(sm.search("cat", conn=conn)) == 1

    # A changed file (new mtime) that no longer parses must not keep old hits.
    path.write_text('{"text": "half written', encoding="utf-8")
    conn.execute("UPDATE indexed_files SET mtime = 0")
    conn.commit()
    sm.index_file(str(path), conn=conn)
    assert sm.search("cat", conn=conn) == []

    # A later valid rewrite is searchable again.
    _write(path, [_segment("dog")])
    conn.execute("UPDATE indexed_files SET mtime = 0")
    conn.commit()
    sm.index_file(str(path), conn=conn)
    assert len(sm.search("dog", conn=conn)) == 1


# --- reindexing from history -------------------------------------------------


def test_reindex_skips_a_history_row_with_unparseable_output_paths(
    tmp_path, monkeypatch
):
    good = tmp_path / "good.json"
    _write(good, [_segment("hello there")])

    class _FakeHistory:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def list_transcriptions(self, limit: int = 200):
            return [
                {"output_paths": "not a json string"},
                {"output_paths": None},
                {"output_paths": [str(good)]},
            ]

    monkeypatch.setattr("core.history.HistoryDB", _FakeHistory)
    monkeypatch.setattr(sm, "user_data_dir", lambda: tmp_path)

    assert sm.reindex_all_history() == 1
    assert len(sm.search("hello")) == 1


@pytest.mark.parametrize("damaged", [True, 123, 1.5, {"a": 1}])
def test_reindex_skips_a_history_row_whose_output_paths_is_not_a_list(
    tmp_path, monkeypatch, damaged
):
    """A damaged database cell parses to a bare JSON scalar; that one row
    must not abort the walk over every later transcript."""
    good = tmp_path / "good.json"
    _write(good, [_segment("hello there")])

    class _FakeHistory:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def list_transcriptions(self, limit: int = 200):
            return [{"output_paths": damaged}, {"output_paths": [str(good)]}]

    monkeypatch.setattr("core.history.HistoryDB", _FakeHistory)
    monkeypatch.setattr(sm, "user_data_dir", lambda: tmp_path)

    assert sm.reindex_all_history() == 1
    assert len(sm.search("hello")) == 1
