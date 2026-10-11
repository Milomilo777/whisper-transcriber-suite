import pytest
import json
import sqlite3
import shutil
from pathlib import Path

from core.config import load_config, save_config, config_path, load_project_overrides
from core.history import HistoryDB
from core.search import _open_db, SCHEMA_VERSION as SEARCH_SCHEMA_VERSION
from core._checkpoint import validate_checkpoint, SCHEMA_VERSION as CHECKPOINT_SCHEMA_VERSION

def test_config_preserves_unknown_keys_on_save():
    """
    Hypotheses: an unknown future key is dropped on save (a downgrade then loses data).
    Refuted: the deep merge combined with _leaf_changes ensures unknown keys read from disk stay untouched.
    ffplay_downloads is in _NON_PERSISTED_KEYS so it should be explicitly dropped.
    """
    cfg_file = Path(config_path())
    cfg_file.parent.mkdir(parents=True, exist_ok=True)

    fixture_path = Path(__file__).parent / "fixtures" / "upgrade" / "config_v1_6_0.json"
    shutil.copy(fixture_path, cfg_file)

    # Load config as normal
    loaded = load_config(fetch_online=False)

    # Modify a known key
    loaded["theme"] = "light"

    # Save it back over the file
    save_config(loaded)

    with open(cfg_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)

    assert saved_data["theme"] == "light", "Proves the file really was rewritten"
    assert "unknown_future_key" in saved_data, "Future keys must be preserved on save for downgrade compatibility"
    assert "ffplay_downloads" not in saved_data, "Keys in _NON_PERSISTED_KEYS must not be saved"

def test_project_overrides_filters_unknown_keys(tmp_path):
    """
    Project overrides validation drops anything outside PROJECT_ALLOWED_KEYS.
    """
    proj_file = tmp_path / ".whisperproject.json"
    fixture_path = Path(__file__).parent / "fixtures" / "upgrade" / "project_v1_6_0.json"
    shutil.copy(fixture_path, proj_file)

    overrides = load_project_overrides(tmp_path)
    assert "vad_enabled" in overrides
    assert "ffplay_downloads" not in overrides, "Removed keys must be dropped"
    assert "unknown_future_key" not in overrides, "Unknown keys must be dropped"

def test_history_migration_missing_columns(tmp_path):
    """
    Hypothesis: an older version history DB crashes list_transcriptions due to missing columns.
    Refuted: HistoryDB uses schema alter statements and defaults for absent columns cleanly.
    """
    db_file = tmp_path / "history.sqlite"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE downloads (id INTEGER PRIMARY KEY, status TEXT, url TEXT, format TEXT, started_at INTEGER, finished_at INTEGER, output_paths TEXT, detected_language TEXT, error TEXT)")
    conn.execute("INSERT INTO downloads (status, url) VALUES ('finished', 'http://foo.com')")
    conn.execute("CREATE TABLE transcriptions (id INTEGER PRIMARY KEY, status TEXT, file_path TEXT, model TEXT, started_at INTEGER, finished_at INTEGER, output_paths TEXT, duration_seconds REAL, language TEXT, error TEXT)")
    conn.execute("INSERT INTO transcriptions (status, file_path) VALUES ('finished', '/tmp/foo.mp3')")
    conn.commit()
    conn.close()

    with HistoryDB(db_file) as h:
        transcriptions = h.list_transcriptions()
        assert len(transcriptions) == 1
        t = transcriptions[0]

        # Check that added columns default correctly
        assert t["word_count"] == 0
        assert t["task"] == "transcribe"
        assert t["speed_x"] == 0.0
        assert t["device"] == ""

        # Prove that the migrated DB can also be written without error
        row_id = h.insert_transcription(file_path="/tmp/bar.mp3")
        assert row_id > 0
        updated = h.finish_transcription(row_id=row_id, status="finished", duration_seconds=5.0)
        assert updated is True

def test_search_index_migration(tmp_path):
    """
    Hypothesis: The search cache index crashes or fails to drop when schema changes.
    Refuted: _open_db correctly drops old tables and sets PRAGMA user_version to SCHEMA_VERSION.
    """
    db_file = tmp_path / "search.db"
    conn = sqlite3.connect(db_file)
    conn.execute(f"PRAGMA user_version = {SEARCH_SCHEMA_VERSION - 1}") # Old version
    conn.execute("CREATE TABLE indexed_files (json_path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    conn.execute("INSERT INTO indexed_files (json_path, mtime, size) VALUES ('foo.json', 0.0, 10)")
    conn.commit()
    conn.close()

    new_conn = _open_db(db_file)
    tables = [row[0] for row in new_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "segments_fts" in tables
    assert "indexed_files" in tables
    assert new_conn.execute("PRAGMA user_version").fetchone()[0] == SEARCH_SCHEMA_VERSION
    assert new_conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 0, "Table should have been recreated and empty"

    new_conn.execute("INSERT INTO indexed_files (json_path, mtime, size) VALUES ('bar.json', 1.0, 20)")
    new_conn.commit()
    new_conn.close()

    # Re-opening should keep the row
    re_conn = _open_db(db_file)
    assert re_conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 1, "Re-opening must keep row inserted after migration"
    re_conn.close()

@pytest.mark.parametrize("schema_version", [None, CHECKPOINT_SCHEMA_VERSION - 1, CHECKPOINT_SCHEMA_VERSION + 1])
def test_checkpoint_migration(tmp_path, schema_version):
    """
    Hypothesis: A checkpoint from an older version resumes with wrong segments instead of being rejected cleanly.
    Refuted: Checkpoints missing schema versions or with older/newer schema versions are cleanly rejected by validate_checkpoint without raising.
    """
    src = tmp_path / "foo.mp3"
    src.write_text("dummy audio")

    old_checkpoint = {
        "source_path": str(src),
        "source_size": len(src.read_bytes()),
        "source_mtime": src.stat().st_mtime,
        "backend": "foo",
        "model_name": "base",
        "cfg_fingerprint": "123",
        "last_end_time": 0.0,
        "segments": []
    }
    if schema_version is not None:
        old_checkpoint["schema_version"] = schema_version

    res = validate_checkpoint(old_checkpoint, backend="foo", model_name="base", cfg_fingerprint="123")
    assert isinstance(res, str) and res != "", "Should cleanly reject mismatched schema with a reason string"
    assert "schema_version" in res and "!= expected" in res, "Reason string should mention schema_version mismatch"
