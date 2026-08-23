"""Fast, offline HTTP round-trips against a real socket on 127.0.0.1:0.

No model loads (a stub transcribe is injected), no network egress. Binds an
ephemeral loopback port, exercises the health / formats / 404 / auth / job
lifecycle over real HTTP, and tears down.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from core import __version__
from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    for fmt in (task.output_formats or ["srt"]):
        with open(f"{base}.{fmt}", "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
    if progress_cb:
        progress_cb(100)


class _RunningServer:
    """Context manager: a JobHTTPServer serving on an ephemeral port."""

    def __init__(self, tmp_path, token="", max_upload_mb=512):
        self.tmp_path = tmp_path
        self.token = token
        self.max_upload_mb = max_upload_mb

    def __enter__(self):
        self.manager = JobManager(
            _writing_transcribe,
            jobs_root=str(self.tmp_path / "server_jobs"),
            record_history=False,
        )
        self.manager.start()
        self.server = JobHTTPServer(
            ("127.0.0.1", 0), self.manager,
            token=self.token, max_upload_mb=self.max_upload_mb,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_health_round_trip(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, body = _get(srv.url("/api/health"))
        assert status == 200
        assert body["status"] == "ok"
        assert body["version"] == __version__
        assert "srt" in body["formats"]


def test_formats_endpoint(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, body = _get(srv.url("/api/formats"))
        assert status == 200
        assert "json" in body["formats"]


def test_root_serves_html(tmp_path):
    with _RunningServer(tmp_path) as srv:
        with urllib.request.urlopen(srv.url("/"), timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type", "").startswith("text/html")
            body = resp.read().decode("utf-8")
            assert "Whisper Transcriber Suite" in body


def test_unknown_route_is_404(tmp_path):
    with _RunningServer(tmp_path) as srv:
        try:
            _get(srv.url("/api/nope"))
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404


def test_auth_required_when_token_set(tmp_path):
    with _RunningServer(tmp_path, token="s3cret") as srv:
        try:
            _get(srv.url("/api/health"))
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        # With the token it passes.
        status, body = _get(
            srv.url("/api/health"), headers={"X-Auth-Token": "s3cret"})
        assert status == 200
        # ...or via query param.
        status, _ = _get(srv.url("/api/health?token=s3cret"))
        assert status == 200


def test_upload_lifecycle_over_http(tmp_path):
    with _RunningServer(tmp_path) as srv:
        boundary = "----testboundary"
        parts = [
            f"--{boundary}",
            'Content-Disposition: form-data; name="formats"',
            "", "srt,txt",
            f"--{boundary}",
            'Content-Disposition: form-data; name="file"; filename="clip.mp4"',
            "Content-Type: video/mp4",
            "", "RAWMEDIA",
            f"--{boundary}--", "",
        ]
        body = "\r\n".join(parts).encode("utf-8")
        req = urllib.request.Request(
            srv.url("/api/jobs"), data=body, method="POST",
            headers={"Content-Type":
                     f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 202
            job_id = json.loads(resp.read().decode("utf-8"))["job_id"]

        # Poll until finished.
        deadline = time.time() + 5
        final = None
        while time.time() < deadline:
            status, body_json = _get(srv.url(f"/api/jobs/{job_id}"))
            if body_json["status"] in ("finished", "error", "cancelled"):
                final = body_json
                break
            time.sleep(0.05)
        assert final is not None and final["status"] == "finished"
        fmts = {o["fmt"] for o in final["outputs"]}
        assert fmts == {"srt", "txt"}

        # Download one output.
        with urllib.request.urlopen(
            srv.url(f"/api/jobs/{job_id}/result?fmt=srt"), timeout=5
        ) as resp:
            assert resp.status == 200
            disp = resp.headers.get("Content-Disposition", "")
            assert "attachment" in disp
            assert resp.read() == b"dummy srt"


def test_url_job_via_json(tmp_path):
    with _RunningServer(tmp_path) as srv:
        # No download_fn -> URL job errors, but we assert the JSON path
        # accepts the body and creates a job (202).
        body = json.dumps({"url": "https://example.com/v",
                           "formats": ["srt"]}).encode("utf-8")
        req = urllib.request.Request(
            srv.url("/api/jobs"), data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 202
            assert "job_id" in json.loads(resp.read().decode("utf-8"))


def test_bad_url_scheme_rejected_over_http(tmp_path):
    with _RunningServer(tmp_path) as srv:
        body = json.dumps({"url": "file:///etc/passwd"}).encode("utf-8")
        req = urllib.request.Request(
            srv.url("/api/jobs"), data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400


def test_upload_size_cap_returns_413(tmp_path):
    # 1 MB cap; send a body that declares more.
    with _RunningServer(tmp_path, max_upload_mb=1) as srv:
        big = b"x" * (2 * 1024 * 1024)
        req = urllib.request.Request(
            srv.url("/api/jobs"), data=big, method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 413"
        except urllib.error.HTTPError as e:
            assert e.code == 413
