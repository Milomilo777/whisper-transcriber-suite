"""Whisper's translate-to-English task (card C2.26): support rules, the call
into the engine, output names, the history record and checkpoint round trips.

The engine is faked; these tests check what the transcriber asks it for and
what it writes, not Whisper's own translation quality.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from core import translate_task as tt
from core import _checkpoint


# --- support rules ----------------------------------------------------------


def _cfg(slug: str = "small", backend: str = "faster_whisper", **model: Any) -> dict[str, Any]:
    return {
        "transcribe_backend": backend,
        "whisper_model": slug,
        "model": {"name": f"faster-whisper-{slug}", **model},
    }


def test_multilingual_faster_whisper_models_are_supported():
    for slug in ("tiny", "small", "medium", "large-v3"):
        assert tt.unsupported_reason(_cfg(slug)) == "", slug


def test_turbo_is_refused_with_a_reason():
    reason = tt.unsupported_reason(_cfg("large-v3-turbo"))
    assert "turbo" in reason and "translation" in reason
    # Also when only the model dict names it (custom catalog entry).
    assert tt.unsupported_reason(
        {"transcribe_backend": "faster_whisper", "model": {"name": "faster-whisper-large-v3-turbo"}}
    )


def test_english_only_models_are_refused():
    assert tt.unsupported_reason(_cfg("tiny.en"))
    assert tt.unsupported_reason(_cfg("distil-large-v3"))
    # ".en" only counts as a suffix, not inside another word.
    assert tt.unsupported_reason(_cfg("custom.english-multilingual")) == ""


def test_other_engines_are_refused():
    for backend in ("whisper_cpp", "nvidia_asr", "cloud_stt", "google_cloud_stt"):
        assert "Faster-Whisper" in tt.unsupported_reason(_cfg("small", backend=backend)), backend


def test_missing_backend_means_faster_whisper():
    assert tt.unsupported_reason({"whisper_model": "small"}) == ""


def test_normalise_task_only_accepts_translate():
    assert tt.normalise_task("translate") == "translate"
    assert tt.normalise_task(" Translate ") == "translate"
    for value in (None, "", "transcribe", "dubbing", 5):
        assert tt.normalise_task(value) == "transcribe"


def test_translated_base_inserts_the_marker_before_the_extension():
    assert tt.translated_base("/a/b/clip") + ".srt" == "/a/b/clip.en-translated.srt"


# --- the call into the engine ----------------------------------------------


@pytest.fixture
def t(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake)
    import core.config as cfg
    import core.transcriber as tr

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_checkpoint, "user_data_dir", lambda: tmp_path)
    for key, value in (
        ("transcribe_backend", "faster_whisper"), ("demucs_enabled", False),
        ("denoise_enabled", False), ("word_timestamps", False),
        ("whisper_model", "small"), ("model", {"name": "faster-whisper-small"}),
    ):
        monkeypatch.setitem(tr.config, key, value)
    monkeypatch.setattr(tr, "PIPELINE", None, raising=False)
    monkeypatch.setattr(tr, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(tr, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(tr, "get_duration", lambda p: 60.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda p: None)
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(tr, "_write_chapter_sidecar", lambda *a, **k: None)
    return tr


class _Seg:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start, self.end, self.text, self.words = start, end, text, []


class _Engine:
    def __init__(self, language: str = "fa") -> None:
        self.calls: list[dict[str, Any]] = []
        self._info = SimpleNamespace(language=language, language_probability=0.9)

    def transcribe(self, audio_path, **kwargs):
        self.calls.append({"path": audio_path, "kwargs": dict(kwargs)})
        return iter([_Seg(0, 2, "hello"), _Seg(2, 4, "world")]), self._info


def _wire(t, monkeypatch, engine):
    monkeypatch.setattr(t, "MODEL", engine)
    seen: dict[str, Any] = {}

    def fake_write(base, segs, audio, fmts, **kw):
        seen.update(base=base, segs=list(segs), lang=kw.get("lang"))
        return [f"{base}.srt"]

    monkeypatch.setattr(t, "_write_outputs", fake_write)
    return seen


def _task(tmp_path, task_name: str = "transcribe"):
    from core.task import TranscriptionTask

    audio = tmp_path / "clip.wav"
    if not audio.exists():  # a rewrite would change the mtime a checkpoint pins
        audio.write_bytes(b"\0" * 16)
    task = TranscriptionTask(str(audio))
    task.whisper_task = task_name
    return task


def test_kwargs_carry_the_task_only_for_translate(tmp_path):
    from core.transcriber import _build_transcribe_kwargs

    assert _build_transcribe_kwargs(_task(tmp_path, "translate"))["task"] == "translate"
    assert "task" not in _build_transcribe_kwargs(_task(tmp_path))


def test_translate_reaches_the_engine_and_names_the_outputs(t, monkeypatch, tmp_path):
    engine = _Engine()
    seen = _wire(t, monkeypatch, engine)
    task = _task(tmp_path, "translate")

    t.transcribe(task, lambda p: None, lambda m: None)

    assert engine.calls[0]["kwargs"]["task"] == "translate"
    assert seen["base"] == str(tmp_path / "clip") + ".en-translated"
    assert seen["lang"] == "en"
    assert [s["text"] for s in seen["segs"]] == ["hello", "world"]


def test_plain_run_is_unchanged(t, monkeypatch, tmp_path):
    engine = _Engine()
    seen = _wire(t, monkeypatch, engine)

    t.transcribe(_task(tmp_path), lambda p: None, lambda m: None)

    assert "task" not in engine.calls[0]["kwargs"]
    assert seen["base"] == str(tmp_path / "clip")
    assert seen["lang"] == "fa"


def test_translate_on_turbo_fails_loudly_before_any_decode(t, monkeypatch, tmp_path):
    engine = _Engine()
    _wire(t, monkeypatch, engine)
    monkeypatch.setitem(t.config, "whisper_model", "large-v3-turbo")
    monkeypatch.setitem(t.config, "model", {"name": "faster-whisper-large-v3-turbo"})

    with pytest.raises(RuntimeError, match="Translate to English is not available"):
        t.transcribe(_task(tmp_path, "translate"), lambda p: None, lambda m: None)
    assert engine.calls == []


def test_translate_on_another_engine_fails_loudly(t, monkeypatch, tmp_path):
    engine = _Engine()
    _wire(t, monkeypatch, engine)
    monkeypatch.setitem(t.config, "transcribe_backend", "whisper_cpp")

    with pytest.raises(RuntimeError, match="Faster-Whisper"):
        t.transcribe(_task(tmp_path, "translate"), lambda p: None, lambda m: None)
    assert engine.calls == []


def test_translate_skips_stable_ts_alignment(monkeypatch, tmp_path):
    import core.transcriber as tr

    monkeypatch.setitem(tr.config, "alignment", "stable_ts")
    monkeypatch.setitem(tr.config, "diarization_enabled", False)
    called: list[Any] = []
    import core.alignment as align

    monkeypatch.setattr(align, "refine_word_timestamps_in_place", lambda *a, **k: called.append(1))
    monkeypatch.setattr(align, "is_available", lambda: True)
    logs: list[str] = []

    tr._run_post_pipeline(_task(tmp_path, "translate"), [], "fa", logs.append)
    assert called == [] and any("translation" in m for m in logs)

    tr._run_post_pipeline(_task(tmp_path), [], "fa", logs.append)
    assert called == [1]  # a plain run still aligns


# --- checkpoints ------------------------------------------------------------


def test_fingerprint_is_unchanged_for_transcribe_and_differs_for_translate():
    cfg = {"model": "small", "vad_enabled": True}
    plain = _checkpoint.config_fingerprint(cfg)
    assert _checkpoint.config_fingerprint(cfg, "transcribe") == plain
    assert _checkpoint.config_fingerprint(cfg, "translate") != plain


def test_checkpoint_records_the_task(t, tmp_path):
    for name in ("translate", "transcribe"):
        task = _task(tmp_path, name)
        t._write_periodic_checkpoint(task, [{"start": 0.0, "end": 1.0, "text": "a"}], 1.0, "fa", 0.9, None)
        data = _checkpoint.load_checkpoint(task.file_path)
        assert data is not None and data["whisper_task"] == name


def test_resume_keeps_the_checkpoint_task(t, monkeypatch, tmp_path):
    """A translate checkpoint resumed by a task queued as transcribe still
    translates the tail and writes the .en-translated outputs."""
    engine = _Engine()
    seen = _wire(t, monkeypatch, engine)
    monkeypatch.setattr(t, "_slice_audio_from", lambda src, start, out_dir, end_seconds=None: str(tmp_path / "tail.wav"))
    (tmp_path / "tail.wav").write_bytes(b"\0")
    writer = _task(tmp_path, "translate")
    t._write_periodic_checkpoint(writer, [{"start": 0.0, "end": 10.0, "text": "first half"}], 10.0, "fa", 0.9, None)

    resumed = _task(tmp_path, "transcribe")
    resumed.resume = True
    assert t.resume_transcription(resumed, lambda p: None, lambda m: None) is True

    assert engine.calls[0]["kwargs"]["task"] == "translate"
    assert resumed.whisper_task == "translate"
    assert seen["base"].endswith(".en-translated")
    assert [s["text"] for s in seen["segs"]][0] == "first half"


def test_resume_of_a_transcribe_checkpoint_never_switches_to_translate(t, monkeypatch, tmp_path):
    engine = _Engine()
    seen = _wire(t, monkeypatch, engine)
    monkeypatch.setattr(t, "_slice_audio_from", lambda src, start, out_dir, end_seconds=None: str(tmp_path / "tail.wav"))
    (tmp_path / "tail.wav").write_bytes(b"\0")
    writer = _task(tmp_path, "transcribe")
    t._write_periodic_checkpoint(writer, [{"start": 0.0, "end": 10.0, "text": "first half"}], 10.0, "fa", 0.9, None)

    resumed = _task(tmp_path, "translate")
    resumed.resume = True
    assert t.resume_transcription(resumed, lambda p: None, lambda m: None) is True

    assert "task" not in engine.calls[0]["kwargs"]
    assert seen["base"] == str(tmp_path / "clip")


def test_checkpoint_from_before_the_option_still_resumes(t, monkeypatch, tmp_path):
    """No ``whisper_task`` field in the file (written by an older build)."""
    engine = _Engine()
    _wire(t, monkeypatch, engine)
    monkeypatch.setattr(t, "_slice_audio_from", lambda src, start, out_dir, end_seconds=None: str(tmp_path / "tail.wav"))
    (tmp_path / "tail.wav").write_bytes(b"\0")
    task = _task(tmp_path)
    t._write_periodic_checkpoint(task, [{"start": 0.0, "end": 10.0, "text": "old"}], 10.0, "fa", 0.9, None)
    path = _checkpoint.checkpoint_path(task.file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["whisper_task"]
    path.write_text(json.dumps(data), encoding="utf-8")

    task.resume = True
    assert t.resume_transcription(task, lambda p: None, lambda m: None) is True


# --- command, history -------------------------------------------------------


def test_command_carries_the_task():
    from app.services.transcription_service import transcribe_command

    base = dict(file_path="a.wav", language=None, resume=False, clip_start=None,
                clip_end=None, output_formats=None)
    assert transcribe_command(SimpleNamespace(**base, whisper_task="translate"))["whisper_task"] == "translate"
    assert transcribe_command(SimpleNamespace(**base))["whisper_task"] == "transcribe"


def test_history_records_the_task(tmp_path):
    from core.history import HistoryDB

    with HistoryDB(tmp_path / "h.db") as db:
        a = db.insert_transcription("/tmp/a.wav", task="translate")
        b = db.insert_transcription("/tmp/b.wav")
        rows = {r["id"]: r for r in db.list_transcriptions()}
    assert rows[a]["task"] == "translate"
    assert rows[b]["task"] == "transcribe"


def test_history_db_from_before_the_column_is_migrated(tmp_path):
    from core.history import HistoryDB

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE transcriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL,"
        " model TEXT, status TEXT NOT NULL, started_at INTEGER, finished_at INTEGER,"
        " duration_seconds REAL, language TEXT, output_paths TEXT, error TEXT)"
    )
    conn.execute("INSERT INTO transcriptions (file_path, status) VALUES ('/tmp/x.wav', 'finished')")
    conn.commit()
    conn.close()

    with HistoryDB(path) as db:
        rows = db.list_transcriptions()
        assert rows[0]["task"] == "transcribe"  # old rows read as transcribe
        rid = db.insert_transcription("/tmp/y.wav", task="translate")
        assert db.finish_transcription(rid, "finished")


# --- the Transcribe tab option ----------------------------------------------


def _app_double(**cfg: Any):
    from app.app import App

    ns = SimpleNamespace(app_config={"transcribe_backend": "faster_whisper", "whisper_model": "small", **cfg},
                         logs=[])
    ns.log = ns.logs.append
    ns._translate_unsupported_reason = lambda: App._translate_unsupported_reason(ns)
    ns._selected_transcribe_language = lambda: App._selected_transcribe_language(ns)
    return ns


def test_option_off_by_default_leaves_the_task_alone():
    from app.app import App
    from core.task import TranscriptionTask

    task = TranscriptionTask("a.wav")
    App._apply_task_options(_app_double(), task)
    assert task.whisper_task == "transcribe"


def test_option_on_marks_the_task_translate():
    from app.app import App
    from core.task import TranscriptionTask

    task = TranscriptionTask("a.wav")
    App._apply_task_options(_app_double(translate_to_english=True), task)
    assert task.whisper_task == "translate"


def test_option_on_with_turbo_is_skipped_and_logged():
    from app.app import App
    from core.task import TranscriptionTask

    task = TranscriptionTask("a.wav")
    ns = _app_double(translate_to_english=True, whisper_model="large-v3-turbo")
    App._apply_task_options(ns, task)
    assert task.whisper_task == "transcribe"
    assert any("English translation skipped" in m for m in ns.logs)


def test_option_default_is_off_in_the_config_defaults():
    from core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["translate_to_english"] is False
