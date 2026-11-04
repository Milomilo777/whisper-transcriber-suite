"""POST /api/jobs URL jobs: a full queue is refused before the body is read.

Round-trip over a loopback socket with a real JobManager (stub transcribe,
``max_queued=0``): with the queue full, a client that stalls mid-body must
still get its 503 promptly — the server may not block on reading a body it
is going to refuse anyway. No model, no Tk, no network egress.
"""
from __future__ import annotations

import http.client
import json
import threading

from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager


def _stub_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    raise AssertionError("no job may run: the queue is full")


class _RunningServer:
    """Context manager: a JobHTTPServer whose queue is always full."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    def __enter__(self):
        self.manager = JobManager(
            _stub_transcribe,
            max_queued=0,
            record_history=False,
            jobs_root=str(self.tmp_path / "server_jobs"),
        )
        self.manager.start()
        self.server = JobHTTPServer(("127.0.0.1", 0), self.manager)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()


def test_full_queue_refuses_a_url_job_before_reading_its_body(tmp_path):
    with _RunningServer(tmp_path) as srv:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=15)
        try:
            conn.putrequest("POST", "/api/jobs")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", "1048576")
            conn.endheaders()
            # Only a fragment of the declared body is sent: a server that
            # insists on the whole body first blocks until its read budget
            # runs out instead of answering 503.
            conn.send(b'{"url": "https://example.invalid/v"}')
            resp = conn.getresponse()
            assert resp.status == 503, resp.read()
            assert resp.getheader("Retry-After") is not None
        finally:
            conn.close()
        assert srv.manager.list() == []


def test_full_queue_refuses_a_complete_url_job_with_503(tmp_path):
    with _RunningServer(tmp_path) as srv:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=15)
        try:
            body = json.dumps({"url": "https://example.invalid/v"}).encode()
            conn.request("POST", "/api/jobs", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 503, resp.read()
        finally:
            conn.close()
        assert srv.manager.list() == []
