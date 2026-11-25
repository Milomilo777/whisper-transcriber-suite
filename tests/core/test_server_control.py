"""JobManager Stage 2/3 tests: list, pause/resume, per-job override file, and
outputs mapped from the engine's authoritative ``task.output_paths``.

Drives the manager with STUBBED transcribe callables — never the real model.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from core.config import PROJECT_FILE_NAME
from core.server.jobs import (
    STATUS_FINISHED,
    JobManager,
)


def _wait_terminal(mgr: JobManager, job_id: str, timeout: float = 5.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job is not None and job.status == STATUS_FINISHED:
            return job
        if job is not None and job.status in ("error", "cancelled"):
            return job
        time.sleep(0.02)
    return mgr.get(job_id)


def _make_manager(tmp_path, transcribe_fn, **kw) -> JobManager:
    mgr = JobManager(
        transcribe_fn,
        jobs_root=str(tmp_path / "server_jobs"),
        record_history=False,
        **kw,
    )
    mgr.start()
    return mgr


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    """Fake transcribe writing dummy outputs AND recording output_paths."""
    base, _ = os.path.splitext(task.file_path)
    written = []
    for fmt in (task.output_formats or ["srt"]):
        p = f"{base}.{fmt}"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
        written.append(p)
    # The engine sets this; mirror it so the manager maps from it.
    task.output_paths = written
    if progress_cb:
        progress_cb(100)


# --- GET /api/jobs list shape -------------------------------------------------

def test_list_returns_compact_rows(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt", "txt"], language="en")
        _wait_terminal(mgr, jid)
        rows = mgr.list()
        assert isinstance(rows, list) and len(rows) == 1
        row = rows[0]
        assert set(row) == {
            "job_id", "status", "progress", "paused", "source",
            "formats", "created_at",
        }
        assert row["job_id"] == jid
        assert row["source"] == "clip.mp4"
        assert row["formats"] == ["srt", "txt"]
        assert isinstance(row["created_at"], float)
    finally:
        mgr.stop()


def test_list_newest_first(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe)
    try:
        j1 = mgr.submit_upload("a.mp4", b"d", ["srt"])
        _wait_terminal(mgr, j1)
        time.sleep(0.01)
        j2 = mgr.submit_upload("b.mp4", b"d", ["srt"])
        _wait_terminal(mgr, j2)
        ids = [r["job_id"] for r in mgr.list()]
        assert ids[0] == j2  # newest first
    finally:
        mgr.stop()


# --- pause / resume state -----------------------------------------------------

def test_pause_resume_flips_job_and_task(tmp_path):
    """pause()/resume() flip Job.paused, and a live _ServerTask mirrors it.

    The engine's segment loop reads ``task.paused`` bare; a paused job must
    stall it. We assert the live task sees the flag via a transcribe fn that
    waits for resume.
    """
    saw_pause = threading.Event()
    release = threading.Event()

    def _slow(task, progress_cb=None, log_cb=None, language_cb=None):
        # Spin until the test pauses then resumes us, proving the bridge.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if task.paused:
                saw_pause.set()
            if release.wait(0.02):
                break
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("done")
        task.output_paths = [f"{base}.srt"]
        if progress_cb:
            progress_cb(100)

    mgr = _make_manager(tmp_path, _slow)
    try:
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"])
        # Wait until it is running.
        deadline = time.time() + 3
        while time.time() < deadline and (mgr.get(jid).status != "running"):
            time.sleep(0.02)
        assert mgr.pause(jid) is True
        job = mgr.get(jid)
        assert job is not None and job.paused is True
        assert saw_pause.wait(5), "the live task never observed the pause"
        assert mgr.resume(jid) is True
        assert mgr.get(jid).paused is False
        release.set()
        final = _wait_terminal(mgr, jid)
        assert final is not None and final.status == STATUS_FINISHED
        assert saw_pause.is_set()
    finally:
        release.set()
        mgr.stop()


def test_pause_resume_unknown_job_returns_false(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe)
    try:
        assert mgr.pause("nope") is False
        assert mgr.resume("nope") is False
    finally:
        mgr.stop()


def test_cancel_clears_paused_flag(tmp_path):
    def _slow(task, progress_cb=None, log_cb=None, language_cb=None):
        deadline = time.time() + 2
        while time.time() < deadline and not task.cancelled:
            time.sleep(0.02)

    mgr = _make_manager(tmp_path, _slow)
    try:
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"])
        deadline = time.time() + 3
        while time.time() < deadline and (mgr.get(jid).status != "running"):
            time.sleep(0.02)
        assert mgr.pause(jid) is True
        assert mgr.cancel(jid) is True
        # cancel must un-pause so the engine loop can see the cancel.
        assert mgr.get(jid).paused is False
    finally:
        mgr.stop()


# --- per-job override file ----------------------------------------------------

def test_override_file_written_with_validated_shape(tmp_path):
    """The per-job options land in work_dir/.whisperproject.json as JSON the
    engine's override mechanism reads. We capture the file content from inside
    the fake transcribe (before the work_dir is cleaned)."""
    captured = {}

    def _capture(task, progress_cb=None, log_cb=None, language_cb=None):
        work_dir = os.path.dirname(task.file_path)
        path = os.path.join(work_dir, PROJECT_FILE_NAME)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                captured.update(json.load(f))
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]
        if progress_cb:
            progress_cb(100)

    mgr = _make_manager(tmp_path, _capture)
    try:
        opts = {"vad_enabled": False, "diarization_enabled": True,
                "vad_threshold": 0.3}
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"], options=opts)
        _wait_terminal(mgr, jid)
        assert captured == opts
    finally:
        mgr.stop()


def test_no_override_file_when_no_options(tmp_path):
    saw = {"present": None}

    def _check(task, progress_cb=None, log_cb=None, language_cb=None):
        work_dir = os.path.dirname(task.file_path)
        saw["present"] = os.path.isfile(
            os.path.join(work_dir, PROJECT_FILE_NAME))
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]

    mgr = _make_manager(tmp_path, _check)
    try:
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"])  # no options
        _wait_terminal(mgr, jid)
        assert saw["present"] is False
    finally:
        mgr.stop()


def test_clip_window_reaches_task(tmp_path):
    seen = {}

    def _check(task, progress_cb=None, log_cb=None, language_cb=None):
        seen["start"] = task.clip_start
        seen["end"] = task.clip_end
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]

    mgr = _make_manager(tmp_path, _check)
    try:
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"],
                                clip_start=5.0, clip_end=20.0)
        _wait_terminal(mgr, jid)
        assert seen == {"start": 5.0, "end": 20.0}
    finally:
        mgr.stop()


# --- outputs mapped from task.output_paths -----------------------------------

def test_outputs_from_task_output_paths_not_mtime(tmp_path):
    """A real bug fix: the engine may leave a newer ``.chapters.json`` /
    partial-checkpoint ``.json`` in the dir. Mapping from ``task.output_paths``
    (authoritative) must pick the engine-written outputs, not the stray newest
    file by mtime."""
    def _fn(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        srt = f"{base}.srt"
        with open(srt, "w", encoding="utf-8") as f:
            f.write("real srt")
        # A stray, NEWER json that is NOT a requested output.
        time.sleep(0.01)
        with open(f"{base}.chapters.json", "w", encoding="utf-8") as f:
            f.write("{}")
        # The engine records ONLY the real outputs it wrote.
        task.output_paths = [srt]
        if progress_cb:
            progress_cb(100)

    mgr = _make_manager(tmp_path, _fn)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_FINISHED
        fmts = {f for f, _ in job.outputs}
        assert fmts == {"srt"}
        # The stray .chapters.json was NOT offered as a json output.
        assert all(not p.endswith(".chapters.json") for _, p in job.outputs)
    finally:
        mgr.stop()


def test_outputs_only_surface_requested_formats(tmp_path):
    """When json is NOT requested, a json the engine wrote internally must not
    appear as an output."""
    def _fn(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        srt, js = f"{base}.srt", f"{base}.json"
        for p in (srt, js):
            with open(p, "w", encoding="utf-8") as f:
                f.write("x")
        # Engine wrote both, but the job only requested srt.
        task.output_paths = [srt, js]
        if progress_cb:
            progress_cb(100)

    mgr = _make_manager(tmp_path, _fn)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert {f for f, _ in job.outputs} == {"srt"}
    finally:
        mgr.stop()


def test_outputs_fall_back_to_scan_when_no_output_paths(tmp_path):
    """If the engine recorded nothing on task.output_paths, fall back to the
    legacy dir-scan so older/alt paths still surface outputs."""
    def _fn(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        # Deliberately do NOT set task.output_paths.
        if progress_cb:
            progress_cb(100)

    mgr = _make_manager(tmp_path, _fn)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert {f for f, _ in job.outputs} == {"srt"}
    finally:
        mgr.stop()
