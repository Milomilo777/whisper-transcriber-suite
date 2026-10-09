"""The speed meter wired into core.transcriber, core.worker and the app side.

The engine is faked and the meter gets a fake clock that the fake segment
stream advances, so the golden numbers are exact: 120 s of audio decoded in
10 s of clock is 12.0x whatever pauses happen in between.
"""
from __future__ import annotations

import sqlite3
import sys
import time
import types
from dataclasses import dataclass
from typing import Any

import pytest

from core import speed_meter as sm


class FakeClock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def t(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake)
    import core._checkpoint as cp
    import core.config as cfg
    import core.transcriber as tr

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    for key, value in (
        ("transcribe_backend", "faster_whisper"), ("demucs_enabled", False),
        ("denoise_enabled", False), ("word_timestamps", False),
        ("loop_guard_repeats", 0),
    ):
        monkeypatch.setitem(tr.config, key, value)
    monkeypatch.setattr(tr, "PIPELINE", None, raising=False)
    monkeypatch.setattr(tr, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(tr, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(tr, "require_audio_stream", lambda p: None)
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(tr, "_write_chapter_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(tr, "_write_outputs", lambda *a, **k: [])
    clock = FakeClock()

    class _Meter(sm.SpeedMeter):
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, clock=clock, **k)

    monkeypatch.setattr(tr._speed_meter, "SpeedMeter", _Meter)
    tr._test_clock = clock  # type: ignore[attr-defined]
    return tr


@dataclass
class Seg:
    start: float
    end: float
    text: str = "words"


@dataclass
class Info:
    language: str = "en"
    language_probability: float = 0.9


class Engine:
    def __init__(self, stream) -> None:
        self.stream = stream

    def transcribe(self, audio_path, **kwargs):  # noqa: ARG002
        return self.stream, Info()


def _stream(clock, ends, step=1.0, before=None):
    for i, end in enumerate(ends):
        clock.t += step
        if before is not None:
            before(i)
        yield Seg(max(0.0, end - 10.0), end)


def _audio(tmp_path):
    path = tmp_path / "talk.wav"
    path.write_bytes(b"\0" * 16)
    return str(path)


def _run(t, monkeypatch, tmp_path, stream, duration=120.0):
    from core.task import TranscriptionTask

    monkeypatch.setattr(t, "get_duration", lambda p: duration)
    monkeypatch.setattr(t, "MODEL", Engine(stream))
    task = TranscriptionTask(_audio(tmp_path))
    seen: list[tuple[int, Any, Any]] = []
    t.transcribe(
        task,
        lambda p: seen.append((p, task.live_speed_x, task.live_eta_s)),
        lambda m: None,
    )
    return task, seen


def test_main_path_golden_12x(t, monkeypatch, tmp_path):
    clock = t._test_clock
    ends = [10.0 * (i + 1) for i in range(12)]
    task, seen = _run(t, monkeypatch, tmp_path, _stream(clock, ends, step=10 / 12))
    assert task.speed_x == pytest.approx(12.0)
    assert task.speed_audio_s == pytest.approx(120.0)
    assert task.speed_seconds == pytest.approx(10.0)
    # Before 30 s of audio: no number; afterwards a live speed + time left.
    assert seen[0][1] is None and seen[0][2] is None
    live = [s for s in seen if s[2] is not None]
    assert live and live[0][1] == pytest.approx(12.0)
    # 40 s of audio is the first sample past both gates (30 s audio, 3 s clock).
    assert live[0][2] == pytest.approx((120.0 - 40.0) / 12.0)
    # The last event (100 %) carries the final speed and no time left.
    assert seen[-1][0] == 100 and seen[-1][2] == 0.0


def test_main_path_pause_is_not_counted(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask  # noqa: F401

    clock = t._test_clock
    holder: dict[str, Any] = {}

    def before(i):
        if i == 5:
            holder["task"].paused = True

    def fake_sleep(dt):  # the pause loop's sleep: 10 minutes pass, then resume
        clock.t += 600.0
        holder["task"].paused = False

    real_transcribe = t.transcribe

    def transcribe(task, *a, **k):
        holder["task"] = task
        return real_transcribe(task, *a, **k)

    monkeypatch.setattr(t, "transcribe", transcribe)
    monkeypatch.setattr(t.time, "sleep", fake_sleep)
    ends = [10.0 * (i + 1) for i in range(12)]
    task, _ = _run(t, monkeypatch, tmp_path, _stream(clock, ends, 10 / 12, before))
    assert task.speed_seconds == pytest.approx(10.0)
    assert task.speed_x == pytest.approx(12.0)


def test_silent_tail_uses_probed_duration(t, monkeypatch, tmp_path):
    clock = t._test_clock
    ends = [8.0 * (i + 1) for i in range(10)]  # speech stops at 80 s of 120 s
    task, _ = _run(t, monkeypatch, tmp_path, _stream(clock, ends, step=1.0))
    assert task.speed_audio_s == pytest.approx(120.0)
    assert task.speed_x == pytest.approx(12.0)


def test_cancelled_run_reports_no_final_speed(t, monkeypatch, tmp_path):
    clock = t._test_clock
    holder: dict[str, Any] = {}

    def before(i):
        if i == 3:
            holder["task"].cancelled = True

    real_transcribe = t.transcribe

    def transcribe(task, *a, **k):
        holder["task"] = task
        return real_transcribe(task, *a, **k)

    monkeypatch.setattr(t, "transcribe", transcribe)
    task, _ = _run(t, monkeypatch, tmp_path, _stream(clock, [10, 20, 30, 40, 50], 1.0, before))
    assert task.speed_x == 0.0


def test_resume_measures_only_the_tail(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = _audio(tmp_path)
    task = TranscriptionTask(audio)
    with t._runtime_overrides_scope(task):
        fp = _checkpoint.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) or str(
            t.config.get("whisper_model", "")
        )
    _checkpoint.write_checkpoint(
        audio, backend="faster_whisper", model_name=model_name, language="en",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=300.0,
        segments=[{"start": 0.0, "end": 300.0, "text": "first half"}],
        checkpoint_time=time.time(),
    )
    clock = t._test_clock
    # Tail of 300 s (slice timeline 0..300) in 30 s of clock = 10x.
    tail = _stream(clock, [30.0 * (i + 1) for i in range(10)], step=3.0)
    monkeypatch.setattr(t, "MODEL", Engine(tail))
    monkeypatch.setattr(t, "get_duration", lambda p: 600.0)
    slice_path = tmp_path / "slice.wav"
    slice_path.write_bytes(b"\0")
    monkeypatch.setattr(t, "_slice_audio_from", lambda *a, **k: str(slice_path))
    seen: list[Any] = []
    assert t.resume_transcription(
        task, lambda p: seen.append((task.live_speed_x, task.live_eta_s)), lambda m: None
    ) is True
    assert task.speed_resumed is True
    assert task.speed_audio_s == pytest.approx(300.0)
    assert task.speed_x == pytest.approx(10.0)
    live = [s for s in seen if s[1] is not None]
    # The first tail segment is the baseline; 60 s in at 10x, 240 s left = 24 s.
    assert live[0] == (pytest.approx(10.0), pytest.approx(24.0))


def test_alt_backend_final_average_without_pause(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    clock = t._test_clock

    class _Lang:
        language = "en"
        probability = 0.9

    class _Backend:
        def transcribe_to_segments(self, path, *, paused, **kwargs):  # noqa: ARG002
            clock.t += 4.0
            task.paused = True
            assert paused() is True
            clock.t += 1000.0  # paused: not decode time
            task.paused = False
            assert paused() is False
            clock.t += 6.0
            return [{"start": 0.0, "end": 100.0, "text": "x"}], _Lang()

    monkeypatch.setitem(t.config, "transcribe_backend", "whisper_cpp")
    monkeypatch.setattr(t, "_get_alt_backend", lambda name, log_cb: _Backend())
    monkeypatch.setattr(t, "get_duration", lambda p: 100.0)
    task = TranscriptionTask(_audio(tmp_path))
    t.transcribe(task, lambda p: None, lambda m: None)
    assert task.speed_seconds == pytest.approx(10.0)
    assert task.speed_x == pytest.approx(10.0)
    assert task.speed_live is False


def test_queue_cell_for_engines_without_live_speed():
    from core.task import TranscriptionTask

    task = TranscriptionTask("x.wav")
    task.status = "running"
    sm.apply_live_speed(task, {"percent": 30, "speed_live": False})
    assert sm.speed_cell(task) == "shown when done"
    sm.reset_speed(task)
    sm.apply_live_speed(task, {"percent": 30})
    assert sm.speed_cell(task) == "measuring speed..."


# -- worker protocol --------------------------------------------------------


def test_worker_speed_fields(monkeypatch):
    import core.worker as w
    from core.task import TranscriptionTask

    task = TranscriptionTask("x.wav")
    assert w._speed_fields(task) == {}
    task.speed_x, task.speed_audio_s, task.speed_seconds = 11.5, 2520.0, 219.13
    fields = w._speed_fields(task)
    assert fields["speed_x"] == 11.5
    assert fields["speed_audio_s"] == 2520.0
    assert fields["speed_seconds"] == 219.13
    assert fields["speed_resumed"] is False
    assert "model" in fields and "device" in fields


# -- app side ---------------------------------------------------------------


def test_events_to_task_and_cells():
    from core.task import TranscriptionTask

    task = TranscriptionTask("x.wav")
    task.status = "running"
    assert sm.speed_cell(task) == "measuring speed..."
    sm.apply_live_speed(task, {"percent": 40, "speed_x": 4.83, "eta_s": 360.0})
    assert sm.speed_cell(task) == "about 4.8x, 6 min left"
    sm.apply_live_speed(task, {"percent": 41, "speed_x": "bad", "eta_s": -5})
    assert task.live_speed_x is None and task.live_eta_s is None
    task.status = "paused"
    assert sm.speed_cell(task) == "paused"
    sm.apply_final_speed(task, {
        "speed_x": 11.5, "speed_audio_s": 2520.0, "speed_seconds": 219.13,
        "model": "small", "device": "cpu",
    })
    task.status = "finished"
    assert sm.speed_cell(task) == "11.5x"
    assert sm.task_summary_line(task) == (
        "42 min of audio transcribed in 3 min 39 s (11.5x) with small on CPU"
    )
    sm.reset_speed(task)
    assert task.speed_x == 0.0 and sm.task_summary_line(task) == ""
    # An older worker sends none of the fields: nothing breaks, nothing shown.
    sm.apply_final_speed(task, {"outputs": []})
    assert sm.speed_cell(task) == "" and sm.task_summary_line(task) == ""


def test_history_stores_speed_model_device(tmp_path):
    from core.history import HistoryDB

    db = HistoryDB(tmp_path / "h.db")
    row = db.insert_transcription("a.wav", model="base")
    assert db.finish_transcription(
        row, "finished", speed_x=4.8, device="cpu", model="small"
    )
    rec = db.list_transcriptions()[0]
    assert rec["speed_x"] == pytest.approx(4.8)
    assert rec["device"] == "cpu"
    assert rec["model"] == "small"
    # No model reported: the insert-time model stays.
    row2 = db.insert_transcription("b.wav", model="base")
    assert db.finish_transcription(row2, "cancelled")
    rec2 = db.list_transcriptions()[0]
    assert rec2["model"] == "base" and rec2["speed_x"] == 0


def test_history_migrates_an_old_database(tmp_path):
    from core.history import HistoryDB

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE transcriptions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " file_path TEXT NOT NULL, model TEXT, status TEXT NOT NULL,"
        " started_at INTEGER, finished_at INTEGER, duration_seconds REAL,"
        " language TEXT, output_paths TEXT, error TEXT);"
        "INSERT INTO transcriptions (file_path, model, status)"
        " VALUES ('old.wav', 'tiny', 'finished');"
    )
    conn.commit()
    conn.close()
    db = HistoryDB(path)
    rec = db.list_transcriptions()[0]
    assert rec["file_path"] == "old.wav"
    assert rec["speed_x"] == 0 and rec["device"] == ""


# -- time ranges (found in review: the meter's end ignored the real length) --


def _run_clip(t, monkeypatch, tmp_path, duration, clip_start, clip_end, slice_len, secs):
    from core.task import TranscriptionTask

    clock = t._test_clock
    slice_path = tmp_path / "clip.wav"
    slice_path.write_bytes(b"\0")
    monkeypatch.setattr(t, "_slice_audio_from", lambda *a, **k: str(slice_path))
    monkeypatch.setattr(t, "get_duration", lambda p: duration)
    # Segments on the slice's own timeline; the transcriber shifts them back.
    ends = [slice_len * (i + 1) / 10 for i in range(10)]
    monkeypatch.setattr(t, "MODEL", Engine(_stream(clock, ends, step=secs / 10)))
    task = TranscriptionTask(_audio(tmp_path))
    task.clip_start, task.clip_end = clip_start, clip_end
    t.transcribe(task, lambda p: None, lambda m: None)
    return task


def test_clip_with_start_only_measures_to_the_real_end(t, monkeypatch, tmp_path):
    task = _run_clip(t, monkeypatch, tmp_path, 1000.0, 600.0, None, 400.0, 40.0)
    assert task.speed_audio_s == pytest.approx(400.0)
    assert task.speed_x == pytest.approx(10.0)


def test_clip_end_past_the_file_is_capped(t, monkeypatch, tmp_path):
    task = _run_clip(t, monkeypatch, tmp_path, 100.0, 0.0001, 3600.0, 100.0, 10.0)
    assert task.speed_audio_s == pytest.approx(100.0, abs=0.01)
    assert task.speed_x == pytest.approx(10.0, rel=1e-3)
