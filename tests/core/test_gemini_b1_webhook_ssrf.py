"""Job-server defects from an external review pass (branch fix/gemini-b1).

* a failure to start the webhook thread escaped ``_fire_webhook`` and, through
  the error handler of ``_run_one``, killed the job worker;
* the SSRF guard is pinned for IPv4-mapped IPv6 literals (the stdlib already
  unwraps them on the supported Python builds; these tests catch a build where
  it does not).

Hermetic: fakes only, no network.
"""
from __future__ import annotations

import os
import threading
import time
import types

import pytest

from core.server import jobs as jobs_mod
from core.server.jobs import (
    STATUS_FINISHED,
    JobManager,
    is_safe_url,
)


# --- webhook thread start failure -----------------------------------------------

def _make_manager(tmp_path) -> JobManager:
    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("dummy srt")
        task.output_paths = [f"{base}.srt"]

    mgr = JobManager(
        transcribe, jobs_root=str(tmp_path / "server_jobs"),
        record_history=False, webhook_url="http://203.0.113.9/hook",
        webhook_sender=lambda url, payload: None)
    mgr.start()
    return mgr


def _threading_without_webhook_threads():
    real_thread = threading.Thread

    class FailingThread(real_thread):
        def start(self):  # noqa: D401
            if self.name == "server-webhook":
                raise RuntimeError("can't start new thread")
            super().start()

    stub = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading)
                                    if not k.startswith("__")})
    stub.Thread = FailingThread
    return stub


def _wait_status(mgr, job_id, wanted, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job is not None and job.status == wanted:
            return job
        time.sleep(0.02)
    return mgr.get(job_id)


def test_fire_webhook_survives_a_thread_that_cannot_start(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    try:
        job = jobs_mod.Job(job_id="j1", kind="upload", formats=["srt"],
                           source="a.wav", work_dir=str(tmp_path))
        job.status = STATUS_FINISHED
        monkeypatch.setattr(jobs_mod, "threading", _threading_without_webhook_threads())
        mgr._fire_webhook(job)  # must not raise
    finally:
        monkeypatch.undo()
        mgr.stop()


def test_worker_keeps_running_when_the_webhook_thread_cannot_start(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    try:
        monkeypatch.setattr(jobs_mod, "threading", _threading_without_webhook_threads())
        ids = [mgr.submit_upload(n, b"d", ["srt"]) for n in ("a.wav", "b.wav")]
        for job_id in ids:
            job = _wait_status(mgr, job_id, STATUS_FINISHED)
            assert job is not None and job.status == STATUS_FINISHED, job_id
        assert mgr._worker is not None and mgr._worker.is_alive()
    finally:
        monkeypatch.undo()
        mgr.stop()


# --- SSRF: IPv4-mapped IPv6 literals ----------------------------------------------

@pytest.mark.parametrize("url", [
    "http://[::ffff:169.254.169.254]/latest/meta-data/",
    "http://[::ffff:a9fe:a9fe]/latest/meta-data/",
    "http://[::ffff:127.0.0.1]/x",
    "http://[::ffff:0.0.0.0]/x",
])
def test_ipv4_mapped_ipv6_literals_of_blocked_addresses_are_refused(url):
    assert is_safe_url(url) is False


@pytest.mark.parametrize("url", [
    "http://[::ffff:192.168.1.50]/m.mp4",
    "http://[::ffff:93.184.216.34]/m.mp4",
])
def test_ipv4_mapped_ipv6_literals_of_ordinary_addresses_still_pass(url):
    assert is_safe_url(url) is True


def test_a_name_resolving_to_a_mapped_metadata_address_is_refused(monkeypatch):
    real = jobs_mod.socket.getaddrinfo

    def fake(host, *a, **k):
        if host == "mapped.test":
            return [(10, 1, 6, "", ("::ffff:169.254.169.254", 0, 0, 0))]
        return real(host, *a, **k)

    monkeypatch.setattr(jobs_mod.socket, "getaddrinfo", fake)
    assert is_safe_url("http://mapped.test/x") is False
