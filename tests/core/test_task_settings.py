"""Per-task settings snapshot: a long-lived worker must follow the UI.

The bug (macOS-13 finding D1, platform independent): ``core.transcriber``
loads ``config`` once, when the worker process starts. The parent never
restarts that worker on a settings change, so a later "Identify speakers"
untick (and every other post-spawn change of a per-task option) was ignored
until the app was restarted. The fix: the parent stamps a snapshot of the
per-task options on each task at dispatch, the command carries it, and the
worker applies it for that task only (and restores ``config`` afterwards).

These tests drive the REAL worker protocol (``core.worker.main`` over a fake
stdin) and the REAL ``core.transcriber.transcribe`` with a fake engine, so
they fail on the old behaviour: the worker's stale spawn-time config wins.

Hermetic: no subprocess, no model, no Tk, no network.
"""
from __future__ import annotations

import ast
import io
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import core.transcriber as tr
from core import worker
from core.task import TranscriptionTask


@dataclass
class _Seg:
    start: float
    end: float
    text: str
    words: Any = None


@dataclass
class _Info:
    language: str = "en"
    language_probability: float = 0.99


class _Engine:
    """Fake WhisperModel: records the kwargs of every transcribe() call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio_path: str, **kwargs: Any):
        self.calls.append(dict(kwargs))
        return iter([_Seg(0.0, 2.0, "hello there"), _Seg(2.0, 4.0, "general")]), _Info()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A worker whose spawn-time config is deliberately the OLD settings."""
    import core._checkpoint as cp
    import core.config as cfg
    import core.diarization as diar

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)

    # What the worker read from config.json when it was spawned.
    spawn_time = {
        "transcribe_backend": "faster_whisper",
        "demucs_enabled": False,
        "denoise_enabled": False,
        "word_timestamps": False,
        "vad_enabled": True,
        "diarization_enabled": True,
        "diarization_num_speakers": 2,
        "auto_chapters_enabled": True,
        "hallucination_detect_enabled": False,
        "alignment": "none",
        "ai_enabled": False,
    }
    for key, value in spawn_time.items():
        monkeypatch.setitem(tr.config, key, value)

    engine = _Engine()
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "PIPELINE", None, raising=False)
    monkeypatch.setattr(tr, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(tr, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(tr, "get_duration", lambda p: 60.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda p: None)
    monkeypatch.setattr(tr, "_write_chapter_sidecar", lambda *a, **k: None)

    written: list[dict[str, Any]] = []

    def fake_write(base, segs, src, formats, **kw):
        written.append({"speaker_count": kw.get("speaker_count"),
                        "chapters": kw.get("chapters"), "segs": list(segs)})
        return []

    monkeypatch.setattr(tr, "_write_outputs", fake_write)

    diarize_calls: list[dict[str, Any]] = []

    def fake_diarize(path, **kwargs):
        diarize_calls.append(dict(kwargs))
        return [types.SimpleNamespace(speaker="Speaker 01")]

    monkeypatch.setattr(diar, "is_available", lambda: True)
    monkeypatch.setattr(diar, "diarize", fake_diarize)
    monkeypatch.setattr(diar, "assign_speakers_to_segments", lambda s, d: None)

    chapter_calls: list[dict[str, Any]] = []

    def fake_chapters(segs, **kwargs):
        chapter_calls.append(dict(kwargs))
        return []

    import core.chapters as chapters
    monkeypatch.setattr(chapters, "build_chapters", fake_chapters)

    return types.SimpleNamespace(
        engine=engine, written=written, diarize=diarize_calls,
        chapters=chapter_calls, tmp=tmp_path,
    )


def _command(tmp_path: Path, name: str, settings: dict[str, Any] | None,
             task_id: str) -> dict[str, Any]:
    audio = tmp_path / name
    audio.write_bytes(b"\0" * 16)
    cmd: dict[str, Any] = {
        "action": "transcribe", "file_path": str(audio), "task_id": task_id,
        "language": None, "output_formats": ["srt"],
    }
    if settings is not None:
        cmd["settings"] = settings
    return cmd


def _run_worker(monkeypatch, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "emit", lambda ev, **p: events.append({"event": ev, **p}))
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    payload = "".join(json.dumps(c) + "\n" for c in commands)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert worker.main() == 0
    return events


def _errors(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["event"] == "error"]


# ------------------------------------------------------------ the finding (D1)


def test_unticked_diarization_is_honoured_by_a_long_lived_worker(env, monkeypatch):
    """Task 1 has "Identify speakers" ticked, task 2 was queued after the user
    unticked it. The worker (same process, spawn-time config says ON) must
    diarise task 1 only."""
    cmds = [
        _command(env.tmp, "one.wav", {"diarization_enabled": True,
                                      "diarization_num_speakers": 3}, "h1"),
        _command(env.tmp, "two.wav", {"diarization_enabled": False,
                                      "diarization_num_speakers": 3}, "h2"),
    ]
    events = _run_worker(monkeypatch, cmds)

    assert _errors(events) == []
    assert [e["task_id"] for e in events if e["event"] == "done"] == ["h1", "h2"]
    assert len(env.diarize) == 1, "task 2 was diarised although the setting was off"
    assert [w["speaker_count"] for w in env.written] == [1, 0]


def test_ticked_diarization_applies_to_a_worker_spawned_with_it_off(env, monkeypatch):
    """The opposite direction: spawned with the box unticked, ticked later."""
    monkeypatch.setitem(tr.config, "diarization_enabled", False)
    cmds = [
        _command(env.tmp, "one.wav", {"diarization_enabled": False}, "h1"),
        _command(env.tmp, "two.wav", {"diarization_enabled": True,
                                      "diarization_num_speakers": 4}, "h2"),
    ]
    _run_worker(monkeypatch, cmds)

    assert len(env.diarize) == 1
    assert env.diarize[0]["num_speakers"] == 4  # the speaker count follows too
    assert [w["speaker_count"] for w in env.written] == [0, 1]


def test_vad_toggle_between_tasks_reaches_the_engine(env, monkeypatch):
    cmds = [
        _command(env.tmp, "one.wav", {"vad_enabled": False}, "h1"),
        _command(env.tmp, "two.wav", {"vad_enabled": True, "vad_threshold": 0.7,
                                      "vad_min_silence_ms": 900}, "h2"),
    ]
    _run_worker(monkeypatch, cmds)

    first, second = env.engine.calls
    assert first["vad_filter"] is False
    assert second["vad_filter"] is True
    assert second["vad_parameters"]["threshold"] == pytest.approx(0.7)
    assert second["vad_parameters"]["min_silence_duration_ms"] == 900


def test_word_timestamps_and_chapter_length_follow_each_task(env, monkeypatch):
    cmds = [
        _command(env.tmp, "one.wav", {"word_timestamps": True,
                                      "auto_chapters_enabled": True,
                                      "chapter_min_seconds": 120.0}, "h1"),
        _command(env.tmp, "two.wav", {"word_timestamps": False,
                                      "auto_chapters_enabled": False}, "h2"),
    ]
    _run_worker(monkeypatch, cmds)

    first, second = env.engine.calls
    assert first["word_timestamps"] is True
    assert second["word_timestamps"] is False
    assert len(env.chapters) == 1  # task 2 had chapters switched off
    assert env.chapters[0]["min_chapter_seconds"] == pytest.approx(120.0)


def test_settings_do_not_leak_into_the_worker_config_afterwards(env, monkeypatch):
    before = dict(tr.config)
    _run_worker(monkeypatch, [
        _command(env.tmp, "one.wav", {"diarization_enabled": False,
                                      "vad_enabled": False,
                                      "word_timestamps": True}, "h1"),
    ])
    assert dict(tr.config) == before


def test_a_command_without_settings_keeps_the_old_behaviour(env, monkeypatch):
    """Old parents (and the Live/e2e tools) send no snapshot: the worker's own
    config applies exactly as before."""
    _run_worker(monkeypatch, [_command(env.tmp, "one.wav", None, "h1")])
    assert len(env.diarize) == 1
    assert env.engine.calls[0]["vad_filter"] is True


def test_project_file_still_beats_the_task_snapshot(env, monkeypatch):
    """Precedence: app settings < per-folder project file."""
    import core.config as cfg
    monkeypatch.setattr(
        cfg, "load_project_overrides",
        lambda _p: {"diarization_enabled": False},
    )
    _run_worker(monkeypatch, [
        _command(env.tmp, "one.wav", {"diarization_enabled": True}, "h1"),
    ])
    assert env.diarize == []


def test_snapshot_cannot_reach_load_time_or_unknown_keys(env, monkeypatch):
    """Only per-task options travel. A forged/odd snapshot must not switch the
    engine, point at another model folder or inject arbitrary keys."""
    seen: dict[str, Any] = {}
    real = tr._runtime_overrides_scope

    def spy(task):
        with real(task) as cfg_:
            seen["backend"] = tr.config.get("transcribe_backend")
            seen["model_path"] = tr.config.get("model_path", "<unset>")
            seen["junk"] = tr.config.get("junk", "<unset>")
            yield cfg_

    import contextlib
    monkeypatch.setattr(tr, "_runtime_overrides_scope", contextlib.contextmanager(spy))
    _run_worker(monkeypatch, [
        _command(env.tmp, "one.wav", {
            "transcribe_backend": "cloud_stt", "model_path": "C:/evil",
            "junk": 1, "diarization_enabled": False,
        }, "h1"),
    ])
    assert seen == {"backend": "faster_whisper", "model_path": tr.config.get(
        "model_path", "<unset>"), "junk": "<unset>"}
    assert env.diarize == []  # the one legitimate key still applied


@pytest.mark.parametrize("bad", ["yes", 5, ["a"], None])
def test_a_malformed_settings_payload_is_ignored_not_fatal(env, monkeypatch, bad):
    cmd = _command(env.tmp, "one.wav", None, "h1")
    cmd["settings"] = bad
    events = _run_worker(monkeypatch, [cmd])
    assert _errors(events) == []
    assert [e["event"] for e in events if e["event"] == "done"] == ["done"]


# ----------------------------------------------- parent side: stamp + command


def _service_with(app_config: dict[str, Any], tasks: list[Any], monkeypatch):
    from app.services.transcription_service import TranscriptionService

    class _Alive:
        pid = 1

        def poll(self):
            return None

    worker_ = {"id": 1, "process": _Alive(), "task": None, "ready": True,
               "last_event_at": 0.0, "token": "", "temporary": False}
    app = types.SimpleNamespace(
        queue=tasks, workers=[worker_], parallel_workers=1,
        app_config=app_config,
        history=types.SimpleNamespace(insert_transcription=lambda **k: 1),
        update_overall_progress=lambda: None, log=lambda m: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "_dispatch_command_async",
                        lambda w, t, cmd: sent.append(cmd))
    return svc, worker_, sent


def test_dispatch_stamps_the_live_settings_and_the_command_carries_them(monkeypatch):
    live = {"model": {"name": "m"}, "output_formats": ["srt"],
            "diarization_enabled": True, "diarization_num_speakers": 2,
            "vad_enabled": True, "word_timestamps": False}
    t1 = TranscriptionTask("a.wav")
    svc, w, sent = _service_with(live, [t1], monkeypatch)
    svc.dispatch_waiting()

    # The user unticks "Identify speakers", then the next file is dispatched.
    live["diarization_enabled"] = False
    live["word_timestamps"] = True
    w["task"] = None
    t2 = TranscriptionTask("b.wav")
    svc.app.queue.append(t2)
    svc.dispatch_waiting()

    assert [c["file_path"] for c in sent] == ["a.wav", "b.wav"]
    assert sent[0]["settings"]["diarization_enabled"] is True
    assert sent[1]["settings"]["diarization_enabled"] is False
    assert sent[1]["settings"]["word_timestamps"] is True
    json.dumps(sent[1])  # it is written to the worker's stdin as JSON


def test_a_running_tasks_snapshot_is_not_restamped_on_redispatch(monkeypatch):
    live = {"model": {"name": "m"}, "output_formats": ["srt"],
            "diarization_enabled": True}
    t1 = TranscriptionTask("a.wav")
    svc, w, sent = _service_with(live, [t1], monkeypatch)
    svc.dispatch_waiting()
    live["diarization_enabled"] = False
    t1.status = "waiting"
    w["task"] = None
    svc.dispatch_waiting()
    assert [c["settings"]["diarization_enabled"] for c in sent] == [True, True]


def test_snapshot_never_contains_secrets_or_load_time_keys():
    from core import task_settings

    cfg = {"llm_remote_api_key": "dummy-credential-A", "model_path": "x",
           "transcribe_backend": "faster_whisper", "device": "cpu",
           "compute_type": "int8", "whisper_model": "large-v3",
           "model": {"name": "m"}, "diarization_enabled": True,
           "cloud_api_key": "dummy-credential-B"}
    snap = task_settings.snapshot(cfg)
    assert snap == {"diarization_enabled": True, "alignment": "none"}
    assert "dummy-credential" not in json.dumps(snap)


def test_snapshot_is_detached_from_the_live_config():
    from core import task_settings

    cfg = {"hotwords": "a", "diarization_enabled": True}
    snap = task_settings.snapshot(cfg)
    cfg["diarization_enabled"] = False
    assert snap["diarization_enabled"] is True


def test_resumed_task_inherits_the_original_snapshot(monkeypatch):
    """Resume must continue with the settings the run started with, not with
    whatever the UI shows now (the checkpoint fingerprint covers them)."""
    from core import task_settings

    old = TranscriptionTask("a.wav")
    old.task_settings = {"vad_enabled": False, "diarization_enabled": True}
    new = TranscriptionTask("a.wav")
    task_settings.inherit(new, old)
    assert new.task_settings == old.task_settings
    new.task_settings["vad_enabled"] = True  # copy, not alias
    assert old.task_settings["vad_enabled"] is False

    # A task that was never dispatched has nothing to inherit.
    fresh = TranscriptionTask("b.wav")
    other = TranscriptionTask("b.wav")
    task_settings.inherit(other, fresh)
    assert other.task_settings is None


def test_app_resume_paths_use_inherit():
    """The four App sites that rebuild a task: resume ones inherit, re-run ones
    do not (a re-run after the user fixed a setting must pick it up)."""
    src = (Path(__file__).resolve().parents[2] / "app" / "app.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    inherits: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "_bulk_rerun", "_bulk_resume", "_rerun_task", "resume_task"):
            inherits[node.name] = "task_settings.inherit" in ast.get_source_segment(
                src, node)
    assert inherits == {"_bulk_rerun": False, "_bulk_resume": True,
                        "_rerun_task": False, "resume_task": True}


def test_ui_toggle_reaches_the_worker_through_dispatch_and_command(env, monkeypatch):
    """The whole chain: live app config -> dispatch stamp -> command JSON ->
    worker -> engine, with the box unticked between the two files."""
    live = {"model": {"name": "m"}, "output_formats": ["srt"],
            "diarization_enabled": True, "vad_enabled": True,
            "word_timestamps": False}
    t1 = TranscriptionTask(str(env.tmp / "one.wav"))
    (env.tmp / "one.wav").write_bytes(b"\0" * 16)
    (env.tmp / "two.wav").write_bytes(b"\0" * 16)
    svc, w, sent = _service_with(live, [t1], monkeypatch)
    svc.dispatch_waiting()
    live["diarization_enabled"] = False
    live["vad_enabled"] = False
    w["task"] = None
    svc.app.queue.append(TranscriptionTask(str(env.tmp / "two.wav")))
    svc.dispatch_waiting()

    # The commands cross a pipe as JSON lines.
    wire = [json.loads(json.dumps(c)) for c in sent]
    _run_worker(monkeypatch, wire)

    assert [w_["speaker_count"] for w_ in env.written] == [1, 0]
    assert [c["vad_filter"] for c in env.engine.calls] == [True, False]


def test_remote_llm_key_is_read_fresh_and_never_snapshotted(monkeypatch):
    seen: dict[str, Any] = {}
    import core.llm as llm

    monkeypatch.setattr(llm, "build_runner_from_config",
                        lambda cfg: seen.update(cfg) or None)
    monkeypatch.setitem(tr.config, "ai_enabled", True)
    monkeypatch.setitem(tr.config, "llm_provider", "remote")
    monkeypatch.setitem(tr.config, "llm_remote_api_key", "dummy-credential-A")
    monkeypatch.setattr(
        tr, "load_config",
        lambda *a, **k: {"llm_remote_api_key": "dummy-credential-B"})
    assert tr._maybe_get_llm_runner() is None
    assert seen["llm_remote_api_key"] == "dummy-credential-B"
    assert tr.config["llm_remote_api_key"] == "dummy-credential-A"  # untouched


def test_resume_uses_the_settings_the_run_started_with(env, monkeypatch):
    """A resume that inherits the original snapshot validates against the
    checkpoint and decodes the tail with the ORIGINAL options, although the
    worker's start-up config (and the UI) now say something else. A resume
    under different options is refused and falls back to a full run."""
    import core._checkpoint as cp

    audio = env.tmp / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    started_with = {"vad_enabled": False, "word_timestamps": True}

    first = TranscriptionTask(str(audio))
    first.task_settings = dict(started_with)
    with tr._runtime_overrides_scope(first):
        fp = cp.config_fingerprint(tr.config)
        backend, model_name = tr._current_backend_and_model()
    cp.write_checkpoint(
        str(audio), backend=backend, model_name=model_name, language="en",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=10.0,
        segments=[{"start": 0.0, "end": 10.0, "text": "early"}],
        checkpoint_time=1.0,
    )
    slice_ = env.tmp / "slice.wav"
    slice_.write_bytes(b"\0")
    monkeypatch.setattr(tr, "_slice_audio_from", lambda *a, **k: str(slice_))
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)

    # Different options (e.g. the user changed VAD meanwhile): refused.
    other = TranscriptionTask(str(audio))
    other.task_settings = {"vad_enabled": True, "word_timestamps": True}
    assert tr.resume_transcription(other) is False
    assert env.engine.calls == []
    assert cp.load_checkpoint(str(audio)) is None  # stale partial dropped

    cp.write_checkpoint(
        str(audio), backend=backend, model_name=model_name, language="en",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=10.0,
        segments=[{"start": 0.0, "end": 10.0, "text": "early"}],
        checkpoint_time=1.0,
    )
    resumed = TranscriptionTask(str(audio))
    task_settings_mod = __import__("core.task_settings", fromlist=["inherit"])
    task_settings_mod.inherit(resumed, first)
    assert tr.resume_transcription(resumed) is True
    assert env.engine.calls[0]["vad_filter"] is False
    assert env.engine.calls[0]["word_timestamps"] is True
    assert [s["text"] for s in env.written[-1]["segs"]][0] == "early"


# ------------------------------------------------- checkpoint fingerprint


def test_fingerprint_follows_the_tasks_settings_and_not_the_stale_config(
        env, monkeypatch):
    """Checkpoints are written and validated inside the task scope, so the
    fingerprint reflects the settings the task runs with. A resume carrying
    the original snapshot therefore matches; a changed snapshot does not."""
    import core._checkpoint as cp

    def fp_in_scope(settings):
        task = TranscriptionTask(str(env.tmp / "x.wav"))
        task.task_settings = settings
        monkeypatch.setattr(tr, "load_config", lambda *a, **k: {})
        with tr._runtime_overrides_scope(task):
            return cp.config_fingerprint(tr.config)

    stale = cp.config_fingerprint(tr.config)
    original = fp_in_scope({"vad_enabled": False, "word_timestamps": True})
    assert original != stale
    assert fp_in_scope({"vad_enabled": False, "word_timestamps": True}) == original
    assert fp_in_scope({"vad_enabled": True, "word_timestamps": True}) != original
    assert cp.config_fingerprint(tr.config) == stale  # scope restored


# ---------------------------------------- completeness: nothing falls through


def _is_config_receiver(node: ast.AST, names: tuple[str, ...]) -> bool:
    """``config`` / ``cfg`` / ``disk_cfg`` ... or a direct ``load_config(...)``."""
    if isinstance(node, ast.Name):
        return node.id in names
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "load_config")


def _config_keys_read(
    path: Path,
    names: tuple[str, ...] = ("config", "runtime_cfg", "disk_cfg"),
) -> set[str]:
    """Literal keys read through ``<name>.get("k")`` / ``<name>["k"]`` /
    ``load_config(...).get("k")``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and _is_config_receiver(node.func.value, names)
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            keys.add(node.args[0].value)
        if (isinstance(node, ast.Subscript)
                and _is_config_receiver(node.value, names)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            keys.add(node.slice.value)
    return keys


def test_every_config_key_the_transcriber_reads_is_classified():
    """A new ``config.get("x")`` in core/transcriber.py must be decided on:
    per-task (refreshed for each task) or load-time (fixed for the worker's
    life, a settings change restarts the worker). Forgetting is how D1 shipped."""
    from core import task_settings

    root = Path(__file__).resolve().parents[2]
    read = _config_keys_read(root / "core" / "transcriber.py")
    # Helpers that receive the transcriber's whole ``config`` dict.
    for helper in ("vad_window.py", "loop_guard.py", "llm.py"):
        read |= _config_keys_read(root / "core" / helper, ("config", "cfg"))
    # Modules the transcriber calls that read config.json themselves.
    for helper in ("denoise.py", "separator.py"):
        read |= _config_keys_read(root / "core" / helper, ())
    classified = (set(task_settings.PER_TASK_KEYS)
                  | set(task_settings.LOAD_TIME_KEYS)
                  | set(task_settings.OTHER_KEYS)
                  | set(task_settings.SECRET_KEYS)
                  | set(task_settings.FRESH_READ_KEYS))
    assert read - classified == set(), (
        f"unclassified config keys read by the transcriber: {sorted(read - classified)}")
    # the classes do not overlap
    assert not set(task_settings.PER_TASK_KEYS) & set(task_settings.LOAD_TIME_KEYS)


def test_key_scanner_positive_control(tmp_path):
    """The scanner finds both access styles (so an empty result means something)."""
    src = tmp_path / "m.py"
    src.write_text(
        'x = config.get("a_key")\ny = config["b_key"]\nz = other.get("c")\n'
        'w = load_config().get("d_key")\nv = disk_cfg.get("e_key")\n'
        'u = runtime_cfg["f_key"]\nt = load_config(fetch_online=False)["g_key"]\n',
        encoding="utf-8")
    assert _config_keys_read(src) == {
        "a_key", "b_key", "d_key", "e_key", "f_key", "g_key"}


def test_per_task_keys_exist_in_the_default_config():
    """A typo in the key list would silently never match anything."""
    from core import task_settings
    from core.config import DEFAULT_CONFIG

    missing = [k for k in task_settings.PER_TASK_KEYS
               if k not in DEFAULT_CONFIG and k not in task_settings.FALLBACKS]
    assert missing == []


# ----------------------------------------------- review follow-ups (round 2)

_DUMMY = "dummy-value-A"  # neutral stand-in for a credential


def _url(userinfo: str = "", query: str = "") -> str:
    """Built from parts: the test source holds no credential-shaped URL."""
    host = "host.example/v1"
    return "https://" + (userinfo + "@" if userinfo else "") + host + (
        "?" + query if query else "")


def test_hand_edited_no_ui_keys_are_merged_from_disk_at_dispatch(monkeypatch):
    """Keys without a UI control are edited in config.json by hand while the
    app is open; the in-memory app config never sees that edit. Exactly those
    keys are taken from disk when the snapshot is stamped; keys that have a
    UI control keep the live in-memory value."""
    from core import task_settings

    on_disk = {
        "batch_size": 8, "chapter_min_seconds": 30.0, "chapter_gap_seconds": 1.5,
        "loop_guard_repeats": 4, "vad_window_s": 0,
        "output_filename_template": "{base}-x.{ext}",
        "diarization_enabled": True,  # UI key: the disk value must be ignored
    }
    monkeypatch.setattr(task_settings, "load_config", lambda **k: dict(on_disk))
    live = {"batch_size": 16, "chapter_min_seconds": 60.0, "chapter_gap_seconds": 2.5,
            "loop_guard_repeats": 3, "vad_window_s": 30,
            "output_filename_template": "{base}.{ext}", "diarization_enabled": False}
    task = TranscriptionTask("a.wav")
    snap = task_settings.stamp(task, live)
    assert snap is not None
    for key in task_settings.NO_UI_KEYS:
        assert snap[key] == on_disk[key], key
    assert snap["diarization_enabled"] is False
    assert set(task_settings.NO_UI_KEYS) == {
        "chapter_min_seconds", "chapter_gap_seconds", "loop_guard_repeats",
        "vad_window_s", "output_filename_template", "batch_size"}


def test_unreadable_disk_config_falls_back_to_the_live_values(monkeypatch):
    from core import task_settings

    def boom(**kwargs):
        raise OSError("locked")

    monkeypatch.setattr(task_settings, "load_config", boom)
    snap = task_settings.stamp(TranscriptionTask("a.wav"), {"batch_size": 16})
    assert snap is not None and snap["batch_size"] == 16


@pytest.mark.parametrize("url", [
    _url(userinfo="alice:" + _DUMMY),
    _url(query="token=" + _DUMMY),
    _url(userinfo=_DUMMY),
])
def test_remote_base_url_with_credentials_stays_out_of_the_snapshot(url):
    from core import task_settings

    snap = task_settings.snapshot({"llm_remote_base_url": url, "ai_enabled": True})
    assert "llm_remote_base_url" not in snap
    assert _DUMMY not in json.dumps(snap)
    clean = task_settings.snapshot({"llm_remote_base_url": _url()})
    assert clean["llm_remote_base_url"] == _url()


def test_credentialed_base_url_is_read_fresh_by_the_worker(monkeypatch):
    seen: dict[str, Any] = {}
    import core.llm as llm

    monkeypatch.setattr(llm, "build_runner_from_config",
                        lambda cfg: seen.update(cfg) or None)
    monkeypatch.setitem(tr.config, "ai_enabled", True)
    monkeypatch.setitem(tr.config, "llm_provider", "remote")
    monkeypatch.setitem(tr.config, "llm_remote_base_url", "https://old.example/v1")
    fresh_url = _url(userinfo="alice:" + _DUMMY)
    monkeypatch.setattr(tr, "load_config", lambda *a, **k: {
        "llm_remote_api_key": "dummy-credential-B",
        "llm_remote_base_url": fresh_url})
    tr._maybe_get_llm_runner()
    assert seen["llm_remote_base_url"] == fresh_url

    # A clean URL travels in the snapshot; the in-scope value is kept.
    seen.clear()
    monkeypatch.setattr(tr, "load_config", lambda *a, **k: {
        "llm_remote_api_key": "", "llm_remote_base_url": "https://disk.example/v1"})
    tr._maybe_get_llm_runner()
    assert seen["llm_remote_base_url"] == "https://old.example/v1"


def test_snapshot_converts_paths_and_warns_about_other_values(caplog):
    from pathlib import PurePosixPath
    from core import task_settings

    with caplog.at_level("WARNING", logger="core.task_settings"):
        snap = task_settings.snapshot({
            "ai_model_path": PurePosixPath("/m/q.gguf"),
            "hotwords": ["a", PurePosixPath("b")],
            "initial_prompt": object(),
        })
    assert snap["ai_model_path"] == "/m/q.gguf"
    assert snap["hotwords"] == ["a", "b"]
    assert "initial_prompt" not in snap
    assert any("initial_prompt" in r.getMessage() and "keeps" in r.getMessage()
               for r in caplog.records)
    json.dumps(snap)


def test_resume_says_it_kept_the_original_settings(env, monkeypatch):
    import core._checkpoint as cp

    audio = env.tmp / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    first = TranscriptionTask(str(audio))
    first.task_settings = {"vad_enabled": False}
    with tr._runtime_overrides_scope(first):
        fp = cp.config_fingerprint(tr.config)
        backend, model_name = tr._current_backend_and_model()
    cp.write_checkpoint(
        str(audio), backend=backend, model_name=model_name, language="en",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=10.0,
        segments=[{"start": 0.0, "end": 10.0, "text": "early"}], checkpoint_time=1.0)
    slice_ = env.tmp / "slice.wav"
    slice_.write_bytes(b"\0")
    monkeypatch.setattr(tr, "_slice_audio_from", lambda *a, **k: str(slice_))
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)
    resumed = TranscriptionTask(str(audio))
    resumed.task_settings = {"vad_enabled": False}
    logs: list[str] = []
    assert tr.resume_transcription(resumed, None, logs.append) is True
    line = ("Resumed with the settings it started with; "
            "use Re-run to apply new settings")
    assert sum(line in m for m in logs) == 1

    # A fresh (non-resume) run never prints it.
    logs.clear()
    fresh = TranscriptionTask(str(audio))
    fresh.task_settings = {"vad_enabled": False}
    tr.transcribe(fresh, None, logs.append)
    assert not any(line in m for m in logs)
