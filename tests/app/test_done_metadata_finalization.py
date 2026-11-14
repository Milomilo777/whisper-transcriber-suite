"""Optional done-event metadata cannot strand already-persisted transcripts."""
import json
import queue
import sqlite3
import time
from types import SimpleNamespace

import pytest

from app.services import transcription_service as ts
from core.history import HistoryDB
from core.task import TranscriptionTask


@pytest.fixture
def completion(tmp_path, monkeypatch):
    database = tmp_path / "history.db"
    history = HistoryDB(database)
    shown = []

    def show(task):
        # Another connection must see durable completion before UI delivery.
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT status, output_paths FROM transcriptions WHERE id=?",
                (task.history_id,),
            ).fetchone()
        assert row == ("finished", json.dumps(task.output_paths))
        shown.append(task)

    app = SimpleNamespace(
        worker_events=queue.Queue(), workers=[], queue=[],
        app_config={"output_formats": ["srt"], "telemetry_opt_in": False},
        after=lambda *a, **k: None, log=lambda *a: None,
        update_overall_progress=lambda: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, model_status=lambda *a: None,
        show_last_result=show, note_job_success=lambda: None, history=history,
    )
    service = ts.TranscriptionService(app)
    # Optional external delivery is outside this completion-boundary test.
    monkeypatch.setattr(service, "_post_usage_stats", lambda *a, **k: None)
    monkeypatch.setattr(service, "_run_finish_hooks", lambda *a: None)

    def new_job(number=1):
        source = tmp_path / f"clip-{number}.wav"
        output = source.with_suffix(".srt")
        content = b"1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n"
        output.write_bytes(content)
        task = TranscriptionTask(str(source))
        task.history_id = history.insert_transcription(str(source))
        task.task_id = f"h{task.history_id}"
        task.status = "running"
        task.start_time = time.time()
        task.output_formats = ["srt"]
        worker = {
            "id": number, "token": f"token-{number}", "task": task,
            "ready": True, "temporary": False,
            "process": SimpleNamespace(pid=100+number, poll=lambda: None),
            "last_event_at": time.monotonic(),
        }
        app.workers.append(worker)
        app.queue.append(task)
        event = {
            "event": "done", "_token": worker["token"], "task_id": task.task_id,
            "outputs": [str(output)], "word_count": 2, "audio_duration": 2.0,
            "speed_x": 3.0, "speed_audio_s": 2.0, "speed_seconds": 0.7,
        }
        return task, worker, event, output, content

    yield app, service, history, shown, new_job
    history.close()


@pytest.mark.parametrize("field,value", [
    ("word_count", float("inf")),
    ("word_count", float("-inf")),
    ("word_count", 10**400),
    ("audio_duration", 10**400),
    ("speed_x", 10**400),
    ("speed_audio_s", 10**400),
    ("speed_seconds", 10**400),
], ids=["count-inf", "count-negative-inf", "count-outside-history-range", "duration-overflow", "speed-overflow",
        "speed-audio-overflow", "speed-seconds-overflow"])
def test_bad_done_metadata_finishes_saved_work_and_drains_queue(completion, field, value):
    app, service, history, shown, new_job = completion
    task, worker, event, output, content = new_job()
    other, other_worker, other_event, _, _ = new_job(2)
    event[field] = value
    # Use only values which the real worker JSON line reader can deserialize.
    app.worker_events.put(json.loads(json.dumps(event)))
    app.worker_events.put(other_event)
    service._poll_once()
    assert task.status == other.status == "finished"
    assert worker["task"] is other_worker["task"] is None
    assert shown == [task, other]
    assert app.worker_events.empty()
    assert output.read_bytes() == content
    rows = history.list_transcriptions()
    assert len(rows) == 2 and all(row["status"] == "finished" for row in rows)


def test_speed_formatter_failure_cannot_withhold_durable_completion(completion, monkeypatch):
    app, service, history, shown, new_job = completion
    task, worker, event, output, content = new_job()

    def fail(*args):
        raise RuntimeError("synthetic optional speed presentation failure")

    monkeypatch.setattr(ts, "apply_final_speed", fail)
    app.worker_events.put(event)
    service._poll_once()
    assert task.status == "finished" and worker["task"] is None
    assert history.list_transcriptions()[0]["status"] == "finished"
    assert shown == [task] and output.read_bytes() == content


@pytest.mark.parametrize("field", ["word_count", "audio_duration"])
def test_older_malformed_numeric_fields_still_complete(completion, field):
    app, service, _history, shown, new_job = completion
    task, worker, event, _, _ = new_job()
    event[field] = "not a number"
    app.worker_events.put(event)
    service._poll_once()
    assert task.status == "finished" and worker["task"] is None
    assert shown == [task]
    if field == "word_count":
        assert task.audio_duration == 2.0
    else:
        assert task.word_count == 2


def test_normal_completion_keeps_valid_stats_and_speed(completion):
    app, service, history, shown, new_job = completion
    task, worker, event, _, _ = new_job()
    app.worker_events.put(event)
    service._poll_once()
    assert task.status == "finished" and task.progress == 100
    assert task.word_count == 2 and task.audio_duration == 2.0
    assert task.speed_x == 3.0 and task.speed_seconds == 0.7
    assert worker["task"] is None and shown == [task]
    row = history.list_transcriptions()[0]
    assert row["status"] == "finished" and row["word_count"] == 2


@pytest.mark.parametrize("count,expected", [
    (-1, 0), (1 << 63, 0), ((1 << 63) - 1, (1 << 63) - 1), (42, 42),
], ids=["negative-count", "too-large-count", "largest-history-count", "valid-worker-count"])
def test_count_boundary_keeps_history_writable_and_retains_valid_values(completion, count, expected):
    app, service, history, shown, new_job = completion
    task, worker, event, _, _ = new_job()
    event["word_count"] = count
    app.worker_events.put(event)
    service._poll_once()
    row = history.list_transcriptions()[0]
    assert row["status"] == "finished" and row["word_count"] == expected
    assert worker["task"] is None and shown == [task]


def test_stale_done_with_bad_metadata_cannot_finish_current_task(completion):
    app, service, history, shown, new_job = completion
    task, worker, event, _, _ = new_job()
    event.update(task_id="old-attempt", word_count=float("inf"))
    app.worker_events.put(event)
    service._poll_once()
    assert task.status == "running" and worker["task"] is task
    assert history.list_transcriptions()[0]["status"] == "running"
    assert shown == []


@pytest.mark.parametrize("no_speech", [False, True])
def test_late_cancel_keeps_complete_or_no_speech_result_with_bad_metadata(completion, no_speech):
    app, service, history, shown, new_job = completion
    task, worker, event, output, content = new_job()
    task.cancelled = True
    task.status = "cancelled"
    event.update(word_count=float("inf"), no_speech=no_speech)
    if no_speech:
        event["outputs"] = []
    app.worker_events.put(event)
    service._poll_once()
    assert task.status == "finished" and worker["task"] is None
    assert history.list_transcriptions()[0]["status"] == "finished"
    assert shown == [task] and output.read_bytes() == content
    assert task.output_paths == event["outputs"]


@pytest.mark.parametrize("field,value", [
    ("word_count", float("inf")), ("word_count", 10**400),
    ("audio_duration", 10**400), ("speed_x", 10**400),
    ("speed_audio_s", 10**400), ("speed_seconds", 10**400),
], ids=["count-inf", "count-outside-history-range", "duration-overflow", "speed-overflow",
        "speed-audio-overflow", "speed-seconds-overflow"])
def test_shutdown_settlement_keeps_same_optional_metadata_boundary(completion, field, value):
    _app, service, history, shown, new_job = completion
    task, _worker, event, output, content = new_job()
    event[field] = value
    assert service._settle_one_done(history, task, json.loads(json.dumps(event))) is True
    row = history.list_transcriptions()[0]
    assert row["status"] == "finished" and row["output_paths"] == [str(output)]
    assert output.read_bytes() == content and shown == []


def test_shutdown_settlement_does_not_hide_actual_history_failure(completion, monkeypatch):
    _app, service, history, _shown, new_job = completion
    task, _worker, event, output, content = new_job()

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic actual terminal history failure")

    monkeypatch.setattr(history, "mark_transcription_finished_after_exit", fail)
    event["speed_x"] = 10**400
    with pytest.raises(sqlite3.OperationalError, match="actual terminal history failure"):
        service._settle_one_done(history, task, event)
    assert history.list_transcriptions()[0]["status"] == "running"
    assert output.read_bytes() == content


def test_shutdown_event_drain_records_saved_result_with_invalid_count(completion):
    app, service, history, shown, new_job = completion
    task, worker, event, output, content = new_job()
    event.update(word_count=float("inf"), _worker_id=worker["id"])
    app.worker_events.put(event)
    app.worker_events.put({"event": "worker_exit", "_worker_id": worker["id"]})
    assert service.settle_done_on_exit(wait_s=0.5) == 1
    assert history.list_transcriptions()[0]["status"] == "finished"
    assert output.read_bytes() == content and shown == []
