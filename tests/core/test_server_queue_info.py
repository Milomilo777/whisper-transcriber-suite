"""Fast, offline HTTP round-trips against a real socket on 127.0.0.1:0.

Tests queue counts and 503 Retry-After headers.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager


class _BlockingTranscribe:
    def __init__(self):
        self.blocker = threading.Event()

    def __call__(self, task, progress_cb=None, log_cb=None, language_cb=None):
        self.blocker.wait(timeout=10.0)


class _RunningServer:
    def __init__(self, manager: JobManager, token: str = "secret") -> None:
        self.server = JobHTTPServer(
            ("127.0.0.1", 0), manager, token=token, max_sync_waits=1)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def get(self, path: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        return req

    def post(self, path: str, data: bytes, headers: dict[str, str] | None = None) -> urllib.request.Request:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        return req


@pytest.fixture
def manager(tmp_path):
    transcriber = _BlockingTranscribe()
    mgr = JobManager(
        transcriber,
        max_jobs=3,
        max_queued=2,
        jobs_root=str(tmp_path / "jobs"),
        outputs_root=str(tmp_path / "outputs"),
    )
    mgr.start()
    yield mgr, transcriber
    mgr.stop()


@pytest.fixture
def server(manager):
    mgr, _ = manager
    srv = _RunningServer(mgr)
    yield srv
    srv.stop()


def test_queue_counts_property(manager):
    mgr, transcriber = manager
    assert mgr.max_jobs == 3
    assert mgr.max_queued == 2
    assert mgr.queue_counts() == {"queued": 0, "running": 0, "finished": 0}

    job_id1, path1 = mgr.submit_upload_stream("test1.wav", ["srt"], "en")
    with open(path1, "w") as f:
        f.write("dummy")
    mgr.enqueue_upload(job_id1)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        counts = mgr.queue_counts()
        if counts["running"] == 1:
            break
        time.sleep(0.01)

    counts = mgr.queue_counts()
    assert counts["running"] == 1
    assert counts["queued"] == 0
    assert counts["finished"] == 0

    job_id2, path2 = mgr.submit_upload_stream("test2.wav", ["srt"], "en")
    with open(path2, "w") as f:
        f.write("dummy")
    mgr.enqueue_upload(job_id2)

    counts = mgr.queue_counts()
    assert counts["running"] == 1
    assert counts["queued"] == 1
    assert counts["finished"] == 0

    mgr.cancel(job_id2)

    transcriber.blocker.set()

    deadline = time.time() + 2.0
    while time.time() < deadline:
        counts = mgr.queue_counts()
        if counts["finished"] == 2:
            break
        time.sleep(0.01)

    counts = mgr.queue_counts()
    assert counts["running"] == 0
    assert counts["queued"] == 0
    assert counts["finished"] == 2


def test_health_queue_counts(server):
    req = server.get("/api/health", {"X-Auth-Token": "secret"})
    with urllib.request.urlopen(req) as response:
        assert response.status == HTTPStatus.OK
        data = json.loads(response.read())
        assert "queue" in data
        assert data["queue"] == {"queued": 0, "running": 0, "max_queued": 2}


def test_health_no_token(server):
    req = server.get("/api/health")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
    assert excinfo.value.code == HTTPStatus.UNAUTHORIZED


def test_retry_after_on_queue_full(server, manager):
    mgr, transcriber = manager

    # Fill the queue
    with mgr._lock:
        mgr._new_job("upload", ["srt"], "en", "source1")
        mgr._new_job("upload", ["srt"], "en", "source2")

    # Overfill should trigger QueueFull 503
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"test.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n"
        f"dummy\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = server.post(
        "/api/jobs",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Auth-Token": "secret"}
    )

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)

    assert excinfo.value.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert excinfo.value.headers.get("Retry-After") == "30"

    # Let tasks finish
    transcriber.blocker.set()


def _fill_queue(mgr: JobManager) -> None:
    with mgr._lock:
        mgr._new_job("upload", ["srt"], "en", "source1")
        mgr._new_job("upload", ["srt"], "en", "source2")


def test_retry_after_on_queue_full_url_job(server, manager):
    mgr, transcriber = manager
    _fill_queue(mgr)
    req = server.post(
        "/api/jobs",
        data=json.dumps({"url": "http://93.184.216.34/talk.mp3"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Auth-Token": "secret"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
    assert excinfo.value.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert excinfo.value.headers.get("Retry-After") == "30"
    transcriber.blocker.set()


def test_retry_after_on_queue_full_openai_route(server, manager):
    mgr, transcriber = manager
    _fill_queue(mgr)
    boundary = "----QueueFullBoundary"
    crlf = chr(13) + chr(10)
    body = crlf.join([
        f"--{boundary}",
        'Content-Disposition: form-data; name="file"; filename="test.wav"',
        "Content-Type: audio/wav",
        "",
        "dummy",
        f"--{boundary}--",
        "",
    ]).encode("utf-8")
    req = server.post(
        "/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Auth-Token": "secret"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
    assert excinfo.value.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert excinfo.value.headers.get("Retry-After") == "30"
    assert json.loads(excinfo.value.read())["error"]["type"] == "server_error"
    transcriber.blocker.set()
