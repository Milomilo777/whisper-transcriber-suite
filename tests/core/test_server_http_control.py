"""HTTP round-trips for the Stage 1-3 routes + the keep-alive body-drain fix.

Binds a real ThreadingHTTPServer on 127.0.0.1:0 with a STUBBED transcribe (no
model, no network) and exercises GET /api/options, GET /api/jobs (list),
pause/resume/outputs, the per-job options flowing end-to-end, the 401-body
drain that keeps HTTP/1.1 keep-alive in sync, and the streaming upload cap.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time

from core.config import PROJECT_FILE_NAME
from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    written = []
    for fmt in (task.output_formats or ["srt"]):
        p = f"{base}.{fmt}"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
        written.append(p)
    task.output_paths = written
    if progress_cb:
        progress_cb(100)


class _RunningServer:
    def __init__(self, tmp_path, token="", max_upload_mb=512,
                 transcribe_fn=_writing_transcribe):
        self.tmp_path = tmp_path
        self.token = token
        self.max_upload_mb = max_upload_mb
        self.transcribe_fn = transcribe_fn

    def __enter__(self):
        self.manager = JobManager(
            self.transcribe_fn,
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

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()


def _get_json(srv, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body.decode("utf-8")) if body else None
    finally:
        conn.close()


def _multipart_body(boundary, fields, filename, file_bytes):
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode() + b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        .encode())
    parts.append(b"Content-Type: video/mp4\r\n\r\n")
    parts.append(file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def _submit_upload(srv, fields, filename="clip.mp4", file_bytes=b"RAWMEDIA"):
    boundary = "----b0undary"
    body = _multipart_body(boundary, fields, filename, file_bytes)
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        conn.request("POST", "/api/jobs", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return resp.status, data
    finally:
        conn.close()


def _wait_finished(srv, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = _get_json(srv, f"/api/jobs/{job_id}")
        if body and body["status"] in ("finished", "error", "cancelled"):
            return body
        time.sleep(0.04)
    return None


# --- GET /api/options ---------------------------------------------------------

def test_options_endpoint_shape(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, body = _get_json(srv, "/api/options")
        assert status == 200
        assert "srt" in body["formats"]
        assert "" in body["languages"] and "en" in body["languages"]
        assert body["backend_switchable"] is False
        assert "diarization_available" in body


# --- GET /api/jobs (list) -----------------------------------------------------

def test_jobs_list_endpoint(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, data = _submit_upload(srv, {"formats": "srt,txt"})
        assert status == 202
        jid = data["job_id"]
        _wait_finished(srv, jid)
        status, body = _get_json(srv, "/api/jobs")
        assert status == 200
        assert "jobs" in body and len(body["jobs"]) == 1
        row = body["jobs"][0]
        assert row["job_id"] == jid
        assert set(row) == {
            "job_id", "status", "progress", "paused", "source",
            "formats", "created_at",
        }


# --- options flow end-to-end into the override file --------------------------

def test_upload_options_written_to_override_file(tmp_path):
    captured = {}

    def _capture(task, progress_cb=None, log_cb=None, language_cb=None):
        path = os.path.join(os.path.dirname(task.file_path), PROJECT_FILE_NAME)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                captured.update(json.load(f))
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]
        if progress_cb:
            progress_cb(100)

    with _RunningServer(tmp_path, transcribe_fn=_capture) as srv:
        status, data = _submit_upload(srv, {
            "formats": "srt",
            "language": "en-US",          # must normalize to "en"
            "vad_enabled": "false",
            "diarization_enabled": "true",
            "vad_threshold": "0.3",
            "transcribe_backend": "cloud_stt",  # must be dropped
        })
        assert status == 202
        _wait_finished(srv, data["job_id"])
        assert captured == {
            "vad_enabled": False,
            "diarization_enabled": True,
            "vad_threshold": 0.3,
        }
        # The cloud backend override must NOT have leaked in.
        assert "transcribe_backend" not in captured


# --- pause / resume / outputs over HTTP --------------------------------------

def test_pause_resume_over_http(tmp_path):
    release = []

    def _slow(task, progress_cb=None, log_cb=None, language_cb=None):
        deadline = time.time() + 3
        while time.time() < deadline and not release:
            time.sleep(0.02)
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]
        if progress_cb:
            progress_cb(100)

    with _RunningServer(tmp_path, transcribe_fn=_slow) as srv:
        try:
            _, data = _submit_upload(srv, {"formats": "srt"})
            jid = data["job_id"]
            # Wait until running.
            deadline = time.time() + 3
            while time.time() < deadline:
                _, b = _get_json(srv, f"/api/jobs/{jid}")
                if b and b["status"] == "running":
                    break
                time.sleep(0.03)

            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            conn.request("POST", f"/api/jobs/{jid}/pause")
            assert conn.getresponse().status == 200
            conn.close()

            _, b = _get_json(srv, f"/api/jobs/{jid}")
            assert b["paused"] is True

            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            conn.request("POST", f"/api/jobs/{jid}/resume")
            assert conn.getresponse().status == 200
            conn.close()

            _, b = _get_json(srv, f"/api/jobs/{jid}")
            assert b["paused"] is False
        finally:
            release.append(True)


def test_pause_unknown_job_is_404(tmp_path):
    with _RunningServer(tmp_path) as srv:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        conn.request("POST", "/api/jobs/nope/pause")
        assert conn.getresponse().status == 404
        conn.close()


def test_outputs_endpoint(tmp_path):
    with _RunningServer(tmp_path) as srv:
        _, data = _submit_upload(srv, {"formats": "srt,txt"})
        jid = data["job_id"]
        _wait_finished(srv, jid)
        status, body = _get_json(srv, f"/api/jobs/{jid}/outputs")
        assert status == 200
        fmts = {o["fmt"] for o in body["outputs"]}
        assert fmts == {"srt", "txt"}


# --- 401 on POST drains the body so keep-alive stays in sync -----------------

def test_unauthed_post_drains_body_and_keeps_connection_usable(tmp_path):
    """Historical bug: a 401 on POST that didn't read the body desynced
    HTTP/1.1 keep-alive. Send a POST with a real body on an unauthed
    connection, then reuse the SAME connection for a second request — it must
    parse cleanly (the server drained the first body / closed correctly)."""
    with _RunningServer(tmp_path, token="s3cret") as srv:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            payload = json.dumps({"url": "https://example.com/v"}).encode()
            conn.request("POST", "/api/jobs", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 401
            resp.read()  # consume
            # Reuse the connection for an authed request. If the body wasn't
            # drained / the connection wasn't closed cleanly, this desyncs.
            conn.request("GET", "/api/health?token=s3cret")
            resp2 = conn.getresponse()
            assert resp2.status == 200
            resp2.read()
        finally:
            conn.close()


# --- streaming upload cap returns 413 ----------------------------------------

def test_streaming_upload_cap_413(tmp_path):
    with _RunningServer(tmp_path, max_upload_mb=1) as srv:
        boundary = "----b0undary"
        big = b"x" * (2 * 1024 * 1024)
        body = _multipart_body(boundary, {"formats": "srt"}, "big.mp4", big)
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("POST", "/api/jobs", body=body, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            resp = conn.getresponse()
            assert resp.status == 413
            resp.read()
        finally:
            conn.close()


def test_streaming_upload_under_cap_succeeds(tmp_path):
    """A normal-sized upload streams to disk and runs."""
    with _RunningServer(tmp_path, max_upload_mb=8) as srv:
        status, data = _submit_upload(
            srv, {"formats": "srt"}, file_bytes=b"A" * (256 * 1024))
        assert status == 202
        body = _wait_finished(srv, data["job_id"])
        assert body is not None and body["status"] == "finished"
