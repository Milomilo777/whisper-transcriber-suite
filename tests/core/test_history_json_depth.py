"""An unreadable optional JSON field must not hide healthy history rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import history
from core.task import TranscriptionTask, apply_run_options


@pytest.mark.parametrize("field", ["output_paths", "run_options"])
def test_excessive_json_depth_does_not_hide_interrupted_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    # Use the portable decoder so this also exercises the recursion limit on
    # interpreters whose accelerated JSON scanner accepts deeper inputs.
    decoder = json.JSONDecoder()
    decoder.scan_once = json.scanner.py_make_scanner(decoder)
    monkeypatch.setattr(history.json, "loads", decoder.decode)
    excessive = "[" * 1100 + "0" + "]" * 1100
    with history.HistoryDB(tmp_path / "history.db") as db:
        good = db.insert_transcription("healthy.wav", run_options={"clip_start": 1})
        broken = db.insert_transcription("damaged.wav")
        with db._conn:
            # The column names are test constants, not external input.
            db._conn.execute(f"UPDATE transcriptions SET {field}=? WHERE id=?",
                             (excessive, broken))
        db.mark_interrupted()
        for rows in (db.list_transcriptions(), db.list_interrupted_transcriptions()):
            by_id = {row["id"]: row for row in rows}
            assert set(by_id) == {good, broken}
            assert by_id[good]["run_options"] == {"clip_start": 1}
            assert by_id[broken][field] == excessive
            task = TranscriptionTask("healthy.wav")
            apply_run_options(task, by_id[good]["run_options"])
            assert task.clip_start == 1
            if field == "run_options":
                task = TranscriptionTask("damaged.wav")
                apply_run_options(task, by_id[broken][field])
                assert task.clip_start is None
        # A read must preserve the original field for diagnosis or recovery.
        assert db._conn.execute(
            f"SELECT {field} FROM transcriptions WHERE id=?", (broken,),
        ).fetchone()[0] == excessive
