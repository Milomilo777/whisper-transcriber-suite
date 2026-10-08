"""JobManager state-machine tests.

Drives the manager with a STUBBED transcribe callable (writes dummy output
files) and a STUBBED download callable — never the real ~3 GB model and
never the network. Asserts the create -> queue -> run -> finish lifecycle,
the upload-size / queue caps, URL scheme validation, cancellation, output
collection, and per-job cleanup.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pytest

from core.server import jobs as jobs_mod
from core.server.jobs import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FINISHED,
    JobManager,
    QueueFull,
)


def _wait_terminal(mgr: JobManager, job_id: str, timeout: float = 5.0) -> Any:
    """Poll until the job reaches a terminal state or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job is not None and job.status in (
            STATUS_FINISHED, STATUS_ERROR, STATUS_CANCELLED,
        ):
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


def _writing_transcribe(formats=("srt", "txt")):
    """A fake transcribe that writes a dummy output per requested format."""
    def _fn(task, progress_cb=None, log_cb=None, language_cb=None):
        # The real engine reads these bare off the task inside its segment
        # loop; touch them here so a future missing attribute fails the
        # hermetic suite instead of only crashing a live server job.
        assert hasattr(task, "paused")
        assert hasattr(task, "cancelled")
        _ = task.paused
        _ = task.cancelled
        if progress_cb:
            progress_cb(50)
        base, _ = os.path.splitext(task.file_path)
        wanted = task.output_formats or list(formats)
        for fmt in wanted:
            with open(f"{base}.{fmt}", "w", encoding="utf-8") as f:
                f.write(f"dummy {fmt}")
        if progress_cb:
            progress_cb(100)
    return _fn


# --- the server task object mirrors what the engine reads --------------------

def test_server_task_mirrors_engine_read_attributes():
    """Regression: _ServerTask must carry every attribute the engine reads.

    The engine reads ``task.paused`` and ``task.cancelled`` bare inside its
    segment loop (``while task.paused and not task.cancelled``). A missing
    ``paused`` used to raise AttributeError on EVERY LAN/web job, swallowed
    into job.error with no output. Assert the full duck-type here so a
    dropped attribute fails the hermetic suite, not a live server job.
    """
    class _FakeJob:
        media_path = "/tmp/x.mp4"
        language = "en"
        formats = ["srt", "txt"]
        cancelled = False
        paused = False
        clip_start = None
        clip_end = None

    task = jobs_mod._ServerTask(_FakeJob())  # type: ignore[arg-type]
    for attr in (
        "file_path", "language", "output_formats", "output_paths",
        "detected_language", "language_probability", "paused", "cancelled",
        "resume", "clip_start", "clip_end", "history_id", "checkpoint_failures",
    ):
        assert hasattr(task, attr), f"_ServerTask missing {attr!r}"
    # paused must read as a real bool the loop can short-circuit on.
    assert task.paused is False
    assert task.cancelled is False
    assert task.language_probability == 0.0
    # cancelled is a property bridged to the job; it must round-trip.
    task.cancelled = True
    assert task.cancelled is True


# --- upload happy path -------------------------------------------------------

def test_upload_job_runs_and_collects_outputs(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        jid = mgr.submit_upload("clip.mp4", b"\x00\x01\x02",
                                ["srt", "txt"], language="en")
        job = _wait_terminal(mgr, jid)
        assert job is not None
        assert job.status == STATUS_FINISHED
        assert job.progress == 100
        fmts = {f for f, _ in job.outputs}
        assert fmts == {"srt", "txt"}
        for _, p in job.outputs:
            assert os.path.isfile(p)
        # The uploaded media landed inside the per-job dir.
        assert os.path.dirname(job.media_path) == job.work_dir
    finally:
        mgr.stop()


def test_upload_writes_media_into_per_job_dir(tmp_path):
    seen: dict[str, Any] = {}
    inner = _writing_transcribe()

    def transcribe(task, *args, **kwargs):
        # The engine reads the media while it runs; the server removes it
        # once the outputs are archived (see test_server_jobs_c266.py).
        with open(task.file_path, "rb") as f:
            seen["data"] = f.read()
        seen["dir"] = os.path.dirname(task.file_path)
        inner(task, *args, **kwargs)

    mgr = _make_manager(tmp_path, transcribe)
    try:
        jid = mgr.submit_upload("a.mp4", b"DATA", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_FINISHED
        assert seen["data"] == b"DATA"
        assert seen["dir"] == job.work_dir
    finally:
        mgr.stop()


# --- URL path ----------------------------------------------------------------

def test_url_job_downloads_then_transcribes(tmp_path):
    def fake_download(url, dest_dir):
        path = os.path.join(dest_dir, "downloaded.mp4")
        with open(path, "wb") as f:
            f.write(b"video")
        return path

    mgr = _make_manager(tmp_path, _writing_transcribe(),
                        download_fn=fake_download)
    try:
        jid = mgr.submit_url("https://example.com/v", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None
        assert job.status == STATUS_FINISHED
        assert os.path.basename(job.media_path) == "downloaded.mp4"
        assert any(f == "srt" for f, _ in job.outputs)
    finally:
        mgr.stop()


def test_url_job_rejects_non_http_scheme(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        with pytest.raises(ValueError):
            mgr.submit_url("file:///etc/passwd", ["srt"])
    finally:
        mgr.stop()


def test_url_job_errors_when_no_downloader_configured(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())  # no download_fn
    try:
        jid = mgr.submit_url("https://example.com/v", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_ERROR
        assert "download" in job.error.lower()
    finally:
        mgr.stop()


# --- error propagation -------------------------------------------------------

def test_transcribe_exception_becomes_error_status(tmp_path):
    def boom(task, progress_cb=None, log_cb=None, language_cb=None):
        raise RuntimeError("kaboom")

    mgr = _make_manager(tmp_path, boom)
    try:
        jid = mgr.submit_upload("x.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None
        assert job.status == STATUS_ERROR
        assert "kaboom" in job.error
    finally:
        mgr.stop()


# --- caps --------------------------------------------------------------------

def test_queued_cap_rejects_with_queuefull(tmp_path):
    # A transcribe that blocks so jobs pile up in the queue.
    gate = []

    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        while not gate:
            time.sleep(0.01)

    mgr = _make_manager(tmp_path, slow, max_queued=2)
    try:
        # First is picked up by the worker (running); the next two queue.
        mgr.submit_upload("a.mp4", b"d", ["srt"])
        time.sleep(0.1)
        mgr.submit_upload("b.mp4", b"d", ["srt"])
        mgr.submit_upload("c.mp4", b"d", ["srt"])
        with pytest.raises(QueueFull):
            mgr.submit_upload("d.mp4", b"d", ["srt"])
    finally:
        gate.append(True)  # release the blocked worker
        mgr.stop()


def test_total_jobs_cap_evicts_oldest_terminal(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe(), max_jobs=2)
    try:
        j1 = mgr.submit_upload("a.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, j1) is not None
        j2 = mgr.submit_upload("b.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, j2) is not None
        j3 = mgr.submit_upload("c.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, j3) is not None
        # Oldest terminal job evicted to honour the cap.
        assert mgr.get(j1) is None
        assert mgr.get(j3) is not None
    finally:
        mgr.stop()


# --- cancellation ------------------------------------------------------------

def test_cancel_before_run_marks_cancelled(tmp_path):
    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        time.sleep(0.5)

    mgr = _make_manager(tmp_path, slow)
    try:
        # Fill the worker with one job, queue a second, cancel the second.
        mgr.submit_upload("a.mp4", b"d", ["srt"])
        jid = mgr.submit_upload("b.mp4", b"d", ["srt"])
        assert mgr.cancel(jid) is True
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_CANCELLED
    finally:
        mgr.stop()


def test_cancel_unknown_job_returns_false(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        assert mgr.cancel("does-not-exist") is False
    finally:
        mgr.stop()


# --- output_path lookup ------------------------------------------------------

def test_output_path_resolves_finished_format(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt", "txt"])
        _wait_terminal(mgr, jid)
        srt = mgr.output_path(jid, "srt")
        assert srt is not None and srt.endswith(".srt") and os.path.isfile(srt)
        assert mgr.output_path(jid, "vtt") is None  # not produced
        assert mgr.output_path("nope", "srt") is None
    finally:
        mgr.stop()


# --- smtv_docx: registry-key vs on-disk-extension --------------------------

def _smtv_writing_transcribe():
    """Fake transcribe writing a ``.docx`` for the ``smtv_docx`` registry key.

    Mirrors the engine: the requested format KEY is ``smtv_docx`` but the file
    on disk carries the real EXTENSION ``docx``. The engine records the file
    on ``task.output_paths`` (the authoritative list the manager reads).
    """
    def _fn(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        written = []
        for fmt in (task.output_formats or []):
            ext = "docx" if fmt == "smtv_docx" else fmt
            path = f"{base}.{ext}"
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"dummy {fmt}")
            written.append(path)
        # An auto-chapters sidecar the manager must NOT surface as "json".
        sidecar = f"{base}.chapters.json"
        with open(sidecar, "w", encoding="utf-8") as f:
            f.write("[]")
        task.output_paths = written
    return _fn


def test_smtv_docx_output_is_surfaced_and_downloadable(tmp_path):
    """Regression (HIGH-2): smtv_docx files were written but never surfaced.

    ``_collect_outputs`` compared the on-disk extension ("docx") against the
    raw requested KEYS ({"smtv_docx"}) -> no match -> outputs=[] and
    ?fmt=smtv_docx 404'd. The fix maps the key through _FMT_EXTENSIONS.
    """
    mgr = _make_manager(tmp_path, _smtv_writing_transcribe())
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["smtv_docx"], language="en")
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_FINISHED
        fmts = {f for f, _ in job.outputs}
        # Surfaced under the requested registry key.
        assert "smtv_docx" in fmts
        # The chapters sidecar must NOT leak in as a "json" output.
        assert "json" not in fmts
        # Both the registry key and the plain extension download it.
        by_key = mgr.output_path(jid, "smtv_docx")
        assert by_key is not None and by_key.endswith(".docx")
        assert os.path.isfile(by_key)
        by_ext = mgr.output_path(jid, "docx")
        assert by_ext == by_key
    finally:
        mgr.stop()


def test_collect_outputs_maps_smtv_docx_directly(tmp_path):
    """Unit-level: _collect_outputs maps the key -> extension for smtv_docx."""
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        base = str(tmp_path / "x")
        docx_path = f"{base}.docx"
        with open(docx_path, "w", encoding="utf-8") as f:
            f.write("d")

        class _Job:
            formats = ["smtv_docx"]
            work_dir = str(tmp_path)
            media_path = f"{base}.mp4"

        class _Task:
            output_paths = [docx_path, f"{base}.chapters.json"]

        out = mgr._collect_outputs(_Job(), _Task())  # type: ignore[arg-type]
        assert out == [("smtv_docx", docx_path)]
    finally:
        mgr.stop()


# --- streamed upload seam ----------------------------------------------------

def test_streamed_upload_path(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        jid, media_path = mgr.submit_upload_stream("big.mp4", ["srt"])
        with open(media_path, "wb") as f:
            f.write(b"streamed")
        mgr.enqueue_upload(jid)
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_FINISHED
        assert any(f == "srt" for f, _ in job.outputs)
    finally:
        mgr.stop()


def test_public_dict_shape(tmp_path):
    mgr = _make_manager(tmp_path, _writing_transcribe())
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        _wait_terminal(mgr, jid)
        job = mgr.get(jid)
        assert job is not None
        d = job.public_dict()
        assert set(d) == {
            "job_id", "status", "progress", "error", "paused", "outputs",
        }
        assert d["job_id"] == jid
        assert d["paused"] is False
        for o in d["outputs"]:
            assert set(o) == {"fmt", "name"}
    finally:
        mgr.stop()


def test_is_safe_url_module_level():
    assert jobs_mod.is_safe_url("https://x.test/a") is True
    assert jobs_mod.is_safe_url("file:///x") is False
