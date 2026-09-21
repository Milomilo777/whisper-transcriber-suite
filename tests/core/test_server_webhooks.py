"""Outgoing completion webhooks: payload shape, SSRF refusal, fire-and-forget.

Hermetic: the only socket bound is a loopback listener, and it is used to
PROVE the SSRF guard refuses loopback (no request may reach it). Delivery
tests inject a ``webhook_sender``, so nothing leaves the machine.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import time
import urllib.error

import pytest

from core.server import jobs as jobs_mod
from core.server.jobs import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FINISHED,
    Job,
    JobManager,
    post_webhook,
    webhook_payload,
)


# --- helpers -----------------------------------------------------------------

def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    with open(f"{base}.srt", "w", encoding="utf-8") as f:
        f.write("dummy srt")
    task.output_paths = [f"{base}.srt"]
    if progress_cb:
        progress_cb(100)


def _make_manager(tmp_path, **kw) -> JobManager:
    mgr = JobManager(
        _writing_transcribe,
        jobs_root=str(tmp_path / "server_jobs"),
        record_history=False,
        **kw,
    )
    mgr.start()
    return mgr


def _wait_terminal(mgr: JobManager, job_id: str, timeout: float = 5.0) -> Job | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job is not None and job.status in (
            STATUS_FINISHED, STATUS_ERROR, STATUS_CANCELLED,
        ):
            return job
        time.sleep(0.02)
    return mgr.get(job_id)


def _start_recorder():
    """A loopback HTTP listener that records POSTed (path, body) pairs."""
    received: list[tuple[str, dict]] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length)
            try:
                parsed = json.loads(body.decode("utf-8"))
            except ValueError:
                parsed = {"raw": body.decode("utf-8", "replace")}
            received.append((self.path, parsed))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, received


class _Recorder:
    def __enter__(self):
        self.server, self.received = _start_recorder()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/hook"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


# --- payload -----------------------------------------------------------------

def test_webhook_payload_finished_shape():
    job = Job(
        job_id="abc", kind="upload", formats=["srt", "txt"], language="en",
        source="clip.mp4", status=STATUS_FINISHED, detected_language="fr",
        outputs=[("srt", "/tmp/x/clip.srt"), ("txt", "/tmp/x/clip.txt")],
        created_at=100.0, finished_at=200.0,
    )
    payload = webhook_payload(job)
    assert payload["event"] == "job.finished"
    assert payload["status"] == STATUS_FINISHED
    assert payload["job_id"] == "abc"
    assert payload["source"] == "clip.mp4"
    # Detected language wins over the requested one.
    assert payload["language"] == "fr"
    assert payload["formats"] == ["srt", "txt"]
    assert payload["outputs"] == [
        {"fmt": "srt", "name": "clip.srt"},
        {"fmt": "txt", "name": "clip.txt"},
    ]
    assert payload["error"] == ""
    assert payload["created_at"] == 100.0
    assert payload["finished_at"] == 200.0


def test_webhook_payload_error_shape():
    job = Job(job_id="x", kind="url", formats=["srt"], language="en",
              source="https://example.com/v", status=STATUS_ERROR,
              error="boom")
    payload = webhook_payload(job)
    assert payload["event"] == "job.error"
    assert payload["error"] == "boom"


# --- SSRF guard --------------------------------------------------------------

def test_post_webhook_refuses_loopback_target():
    with _Recorder() as rec:
        post_webhook(rec.url, {"event": "job.finished"})
        time.sleep(0.2)
        assert rec.received == [], "loopback webhook target must be refused"


def test_post_webhook_refuses_metadata_ip():
    # No listener involved: the guard rejects the literal address before any
    # connection attempt, so this must simply return.
    post_webhook("http://169.254.169.254/latest/meta-data/", {"x": 1})


def test_post_webhook_delivers_when_guard_allows(monkeypatch):
    with _Recorder() as rec:
        monkeypatch.setattr(jobs_mod, "is_safe_url", lambda url: True)
        post_webhook(rec.url, {"event": "job.finished", "job_id": "abc"})
        deadline = time.time() + 3
        while time.time() < deadline and not rec.received:
            time.sleep(0.02)
        assert rec.received == [
            ("/hook", {"event": "job.finished", "job_id": "abc"}),
        ]


def test_post_webhook_does_not_follow_redirects(monkeypatch):
    """A 30x must not bounce an allowed URL into an internal address."""
    with _Recorder() as target:
        redirects: list[int] = []

        class _RedirectHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or 0)
                self.rfile.read(length)
                redirects.append(1)
                self.send_response(302)
                self.send_header("Location", target.url)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):  # noqa: A002
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setattr(jobs_mod, "is_safe_url", lambda url: True)
            with pytest.raises(urllib.error.HTTPError):
                post_webhook(
                    f"http://127.0.0.1:{server.server_address[1]}/hook", {})
            time.sleep(0.2)
            assert redirects, "the first endpoint should have been hit"
            assert target.received == [], "redirect target must not be hit"
        finally:
            server.shutdown()
            server.server_close()


# --- JobManager integration --------------------------------------------------

def test_manager_fires_webhook_on_finish(tmp_path):
    calls: list[tuple[str, dict]] = []
    done = threading.Event()

    def sender(url, payload):
        calls.append((url, payload))
        done.set()

    mgr = _make_manager(
        tmp_path, webhook_url="https://example.com/hook",
        webhook_sender=sender)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, jid) is not None
        assert done.wait(3.0), "webhook was not delivered"
        assert calls[0][0] == "https://example.com/hook"
        assert calls[0][1]["event"] == "job.finished"
        assert calls[0][1]["job_id"] == jid
    finally:
        mgr.stop()


def test_manager_fires_webhook_on_error(tmp_path):
    def boom(task, progress_cb=None, log_cb=None, language_cb=None):
        raise RuntimeError("kaboom")

    calls: list[dict] = []
    done = threading.Event()

    def sender(url, payload):
        calls.append(payload)
        done.set()

    mgr = JobManager(
        boom, jobs_root=str(tmp_path / "server_jobs"),
        record_history=False, webhook_url="https://example.com/hook",
        webhook_sender=sender)
    mgr.start()
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, jid) is not None
        assert done.wait(3.0)
        assert calls[0]["event"] == "job.error"
        assert "kaboom" in calls[0]["error"]
    finally:
        mgr.stop()


def test_manager_does_not_fire_webhook_on_cancel(tmp_path):
    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        time.sleep(0.5)

    calls: list[dict] = []
    mgr = _make_manager(
        tmp_path, webhook_url="https://example.com/hook",
        webhook_sender=lambda url, payload: calls.append(payload))
    try:
        mgr.submit_upload("a.mp4", b"d", ["srt"])  # occupies the worker
        jid = mgr.submit_upload("b.mp4", b"d", ["srt"])
        assert mgr.cancel(jid) is True
        assert _wait_terminal(mgr, jid) is not None
        time.sleep(0.2)
        # The other (finished) job may fire; the cancelled one must not.
        assert all(c["job_id"] != jid for c in calls)
    finally:
        mgr.stop()


def test_manager_does_not_fire_when_no_url(tmp_path):
    calls: list[dict] = []
    mgr = _make_manager(
        tmp_path, webhook_sender=lambda url, payload: calls.append(payload))
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        assert _wait_terminal(mgr, jid) is not None
        time.sleep(0.2)
        assert calls == []
    finally:
        mgr.stop()


def test_webhook_sender_exception_is_swallowed(tmp_path):
    def sender(url, payload):
        raise RuntimeError("endpoint down")

    mgr = _make_manager(
        tmp_path, webhook_url="https://example.com/hook",
        webhook_sender=sender)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        assert job is not None and job.status == STATUS_FINISHED
    finally:
        mgr.stop()


def test_slow_webhook_does_not_block_job_completion(tmp_path):
    """A hanging endpoint must not stall the single job worker."""
    release = threading.Event()
    entered = threading.Event()

    def sender(url, payload):
        entered.set()
        release.wait(5.0)

    mgr = _make_manager(
        tmp_path, webhook_url="https://example.com/hook",
        webhook_sender=sender)
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
        job = _wait_terminal(mgr, jid)
        # The job reached its terminal state while the sender is still hung.
        assert job is not None and job.status == STATUS_FINISHED
        assert entered.wait(3.0)
        assert not release.is_set()
    finally:
        release.set()
        mgr.stop()


def test_manager_default_sender_refuses_loopback(tmp_path):
    """The production sender (no injection) must apply the SSRF guard."""
    with _Recorder() as rec:
        mgr = _make_manager(tmp_path, webhook_url=rec.url)
        try:
            jid = mgr.submit_upload("clip.mp4", b"d", ["srt"])
            assert _wait_terminal(mgr, jid) is not None
            time.sleep(0.3)
            assert rec.received == []
        finally:
            mgr.stop()
