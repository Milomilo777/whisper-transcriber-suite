"""Server job robustness (card C2.63): outputs, secrets, clean-up, downloads.

Fakes only: no network, no real yt-dlp, no real engine.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import types

import pytest

from core import server
from core.server import jobs as J
from core.server.jobs import (
    DownloadCancelled,
    DownloadLimits,
    JobManager,
    STATUS_CANCELLED,
    STATUS_FINISHED,
    public_error_text,
    strip_url_secrets,
    webhook_payload,
)


def _manager(tmp_path, transcribe=None, **kw):
    kw.setdefault("record_history", False)
    mgr = JobManager(transcribe or (lambda *a, **k: None),
                     jobs_root=str(tmp_path / "server_jobs"), **kw)
    return mgr


def _wait(mgr, job_id, states=(STATUS_FINISHED, STATUS_CANCELLED, "error"),
          timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        job = mgr.get(job_id)
        if job is not None and job.status in states:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach " + repr(states))


# --- C1: two requested keys with one extension -----------------------------

@pytest.mark.parametrize("formats, names, want", [
    (["docx", "smtv_docx"], ["x.docx", "x -Transcription.docx"],
     [("docx", "x.docx"), ("smtv_docx", "x -Transcription.docx")]),
    (["smtv_docx", "docx"], ["x -Transcription.docx", "x.docx"],
     [("smtv_docx", "x -Transcription.docx"), ("docx", "x.docx")]),
])
def test_docx_and_smtv_docx_are_both_surfaced(tmp_path, formats, names, want):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", formats, "en", "x.wav")
    paths = []
    for n in names:
        p = os.path.join(job.work_dir, n)
        with open(p, "w") as f:
            f.write("x")
        paths.append(p)
    task = types.SimpleNamespace(output_paths=paths)
    got = [(k, os.path.basename(p)) for k, p in mgr._collect_outputs(job, task)]
    assert got == want
    job.outputs = mgr._collect_outputs(job, task)
    assert os.path.basename(mgr.output_path(job.job_id, "smtv_docx")) == (
        "x -Transcription.docx")


# --- C2 / C3: tokens never leave the server --------------------------------

_SIGNED_URL = "https://host.example/v.mp4?k=neutral-value-A&s=neutral-value-B#frag"


def test_strip_url_secrets():
    assert strip_url_secrets(_SIGNED_URL) == "https://host.example/v.mp4"
    userinfo = "name" + ":" + "other" + "@"  # built in parts, not a literal
    assert strip_url_secrets(f"https://{userinfo}host.example:8443/a/b?x=1") == (
        "https://host.example:8443/a/b")
    assert strip_url_secrets("not a url") == "not a url"


def test_job_list_and_webhook_hide_the_url_query():
    job = J.Job(job_id="1", kind="url", formats=["srt"], source=_SIGNED_URL)
    assert job.list_dict()["source"] == "https://host.example/v.mp4"
    assert webhook_payload(job)["source"] == "https://host.example/v.mp4"
    up = J.Job(job_id="2", kind="upload", formats=["srt"], source="clip.wav")
    assert up.list_dict()["source"] == "clip.wav"


def test_error_text_drops_url_tokens():
    text = public_error_text(RuntimeError(
        "yt-dlp failed for " + _SIGNED_URL + " at C:\\Users\\Someone\\x.mp4"))
    assert "neutral-value-A" not in text and "neutral-value-B" not in text
    assert "https://host.example/v.mp4" in text


# --- C11: a file that vanishes during the scan ------------------------------

def test_scan_skips_a_file_that_vanished(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "en", "x.wav")
    job.media_path = os.path.join(job.work_dir, "m.wav")
    with open(os.path.join(job.work_dir, "a.srt"), "w") as f:
        f.write("x")
    real = os.listdir
    monkeypatch.setattr(
        os, "listdir",
        lambda p: real(p) + ["gone.srt"] if p == job.work_dir else real(p))
    assert [os.path.basename(p) for _, p in mgr._collect_outputs_by_scan(job)] == [
        "a.srt"]


# --- item 3: purge and a durable history copy -------------------------------

def test_start_removes_old_job_folders_only(tmp_path, monkeypatch):
    root = tmp_path / "server_jobs"
    root.mkdir()
    old = root / ("a" * 32)
    young = root / ("b" * 32)
    other = root / "keep-me"
    for d in (old, young, other):
        d.mkdir()
        (d / "f.wav").write_bytes(b"x")
    long_ago = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    mgr = _manager(tmp_path)
    mgr.start()
    try:
        assert not old.exists()
        assert young.exists()
        assert other.exists()  # not named like a job id: never touched
    finally:
        mgr.stop()


def test_history_gets_a_durable_copy_of_each_output(tmp_path):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "en", "x.wav")
    src = os.path.join(job.work_dir, "x.srt")
    with open(src, "w") as f:
        f.write("hello")
    job.outputs = [("srt", src)]
    kept = mgr._archive_outputs(job)
    assert len(kept) == 1 and kept[0] != src
    assert not kept[0].startswith(str(tmp_path / "server_jobs"))
    mgr.discard(job.job_id)  # deletes the job folder
    assert not os.path.exists(src)
    with open(kept[0]) as f:
        assert f.read() == "hello"


def test_finished_job_history_row_points_outside_the_job_folder(
        tmp_path, monkeypatch):
    rows: dict = {}

    class _FakeHistory:
        def insert_transcription(self, *a, **k):
            return 7

        def finish_transcription(self, rid, status, **k):
            rows.update(k, status=status)

        def close(self):
            pass

    monkeypatch.setattr("core.history.HistoryDB", _FakeHistory)

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        out = os.path.splitext(task.file_path)[0] + ".srt"
        with open(out, "w") as f:
            f.write("1")
        task.output_paths = [out]

    mgr = _manager(tmp_path, transcribe, record_history=True)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        assert _wait(mgr, job_id).status == STATUS_FINISHED
    finally:
        mgr.stop()
    (kept,) = rows["output_paths"]
    assert os.path.isfile(kept)
    assert not os.path.abspath(kept).startswith(
        os.path.abspath(str(tmp_path / "server_jobs")))


# --- item 4: cancel / limits while DOWNLOADING ------------------------------

def test_cancel_stops_a_download_in_progress(tmp_path):
    started = threading.Event()

    def download(url, dest, limits):
        started.set()
        while not limits.cancelled():
            time.sleep(0.01)
        raise DownloadCancelled()

    mgr = _manager(tmp_path, download_fn=download)
    mgr.start()
    try:
        job_id = mgr.submit_url("http://192.0.2.10/a.mp4", ["srt"])
        assert started.wait(5)
        assert mgr.cancel(job_id)
        job = _wait(mgr, job_id)
        assert job.status == STATUS_CANCELLED
        # The single worker is free again.
        assert mgr.submit_upload("b.wav", b"x", ["srt"])
    finally:
        mgr.stop()


def test_two_argument_download_functions_still_work(tmp_path):
    def download(url, dest):
        path = os.path.join(dest, "m.wav")
        with open(path, "wb") as f:
            f.write(b"x")
        return path

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        out = os.path.splitext(task.file_path)[0] + ".srt"
        with open(out, "w") as f:
            f.write("1")
        task.output_paths = [out]

    mgr = _manager(tmp_path, transcribe, download_fn=download)
    mgr.start()
    try:
        job_id = mgr.submit_url("http://192.0.2.10/a.mp4", ["srt"])
        assert _wait(mgr, job_id).status == STATUS_FINISHED
    finally:
        mgr.stop()


def test_limits_reach_a_three_argument_download(tmp_path):
    seen = {}

    def download(url, dest, limits):
        seen["limits"] = limits
        raise RuntimeError("stop here")

    mgr = _manager(tmp_path, download_fn=download,
                   max_download_bytes=123, download_timeout_s=45.0)
    mgr.start()
    try:
        job_id = mgr.submit_url("http://192.0.2.10/a.mp4", ["srt"])
        _wait(mgr, job_id)
    finally:
        mgr.stop()
    assert seen["limits"].max_bytes == 123
    assert seen["limits"].timeout_s == 45.0


# --- _download_url with a fake yt-dlp process -------------------------------

class _FakePopen:
    """A yt-dlp stand-in: ``hang`` keeps communicate() timing out."""

    hang = False
    returncode = 0
    stderr_text = ""
    last_cmd: list[str] = []
    killed = False

    def __init__(self, cmd, **kwargs):
        type(self).last_cmd = list(cmd)
        self.pid = 4242
        self.returncode = type(self).returncode

    def communicate(self, timeout=None):
        if type(self).hang and not type(self).killed:
            time.sleep(min(timeout or 0.05, 0.05))
            raise subprocess.TimeoutExpired("yt-dlp", timeout or 0)
        return "", type(self).stderr_text

    def poll(self):
        return None


@pytest.fixture
def fake_yt_dlp(monkeypatch, tmp_path):
    for name, value in (("hang", False), ("returncode", 0),
                        ("stderr_text", ""), ("killed", False)):
        monkeypatch.setattr(_FakePopen, name, value)
    monkeypatch.setattr(server.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])

    def _kill(process, force=False, timeout=5.0):
        _FakePopen.killed = True

    monkeypatch.setattr("core._proc.kill_process_tree", _kill)
    return tmp_path


def test_download_url_cancel_kills_the_process(fake_yt_dlp):
    _FakePopen.hang = True
    cancelled = {"v": False}
    threading.Timer(0.3, lambda: cancelled.update(v=True)).start()
    limits = DownloadLimits(cancelled=lambda: cancelled["v"])
    with pytest.raises(DownloadCancelled):
        server._download_url("https://example.com/v", str(fake_yt_dlp), limits)
    assert _FakePopen.killed


def test_download_url_times_out(fake_yt_dlp):
    _FakePopen.hang = True
    limits = DownloadLimits(cancelled=lambda: False, timeout_s=0.6)
    with pytest.raises(TimeoutError):
        server._download_url("https://example.com/v", str(fake_yt_dlp), limits)
    assert _FakePopen.killed


def test_download_url_failure_keeps_the_reason(fake_yt_dlp):
    _FakePopen.returncode = 1
    _FakePopen.stderr_text = "WARNING: x\nERROR: Video unavailable"
    with pytest.raises(subprocess.CalledProcessError) as info:
        server._download_url("https://example.com/v", str(fake_yt_dlp))
    assert "Video unavailable" in public_error_text(info.value)
    assert str(fake_yt_dlp) not in public_error_text(info.value)


def test_download_url_passes_the_size_cap(fake_yt_dlp):
    (fake_yt_dlp / "m.mp4").write_bytes(b"x")
    limits = DownloadLimits(cancelled=lambda: False, max_bytes=5000)
    server._download_url("https://example.com/v", str(fake_yt_dlp), limits)
    cmd = _FakePopen.last_cmd
    assert cmd[cmd.index("--max-filesize") + 1] == "5000"
    assert cmd.index("--max-filesize") < cmd.index("--")


# --- optional: the language is set before the job reads "finished" ----------

def test_detected_language_is_set_before_the_status_flips(tmp_path):
    seen = []

    class _Watch(JobManager):
        def _set_status(self, job, status):
            if status == STATUS_FINISHED:
                seen.append(job.detected_language)
            super()._set_status(job, status)

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        task.detected_language = "fa"

    mgr = _Watch(transcribe, jobs_root=str(tmp_path / "server_jobs"),
                 record_history=False)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"], "en")
        _wait(mgr, job_id)
    finally:
        mgr.stop()
    assert seen == ["fa"]
