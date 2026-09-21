"""OpenAI-compatible /v1 routes: pure helpers + real HTTP round-trips.

Hermetic: a stub transcribe writes a JSON segment sidecar (no model), and
the server binds an ephemeral loopback port. Nothing leaves the machine.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time

from core.server.httpd import (
    JobHTTPServer,
    OPENAI_RESPONSE_FORMATS,
    build_openai_verbose_json,
    openai_error_payload,
    openai_full_text,
    parse_route,
)
from core.server.jobs import JobManager


def _json_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    """Write a JSON segment sidecar (the engine's real output shape)."""
    base, _ = os.path.splitext(task.file_path)
    path = f"{base}.json"
    segments = [{
        "start": 0.0,
        "end": 1.5,
        "text": "Hello world",
        "words": [
            {"start": 0.0, "end": 0.7, "word": "Hello", "probability": 0.9},
            {"start": 0.7, "end": 1.5, "word": "world", "probability": 0.8},
        ],
    }]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f)
    task.output_paths = [path]
    task.detected_language = "en"
    if progress_cb:
        progress_cb(100)


class _RunningServer:
    def __init__(self, tmp_path, token="", transcribe_fn=_json_transcribe,
                 max_upload_mb=512):
        self.tmp_path = tmp_path
        self.token = token
        self.transcribe_fn = transcribe_fn
        self.max_upload_mb = max_upload_mb

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


def _multipart_body(boundary, fields, filename="clip.mp4",
                    file_bytes=b"RAWMEDIA"):
    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\n'.encode())
    parts.append(b"Content-Type: audio/mpeg\r\n\r\n")
    parts.append(file_bytes + b"\r\n")
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def _post_transcription(srv, fields, headers=None, filename="clip.mp4",
                        file_bytes=b"RAWMEDIA"):
    boundary = "----openai-boundary"
    body = _multipart_body(boundary, fields, filename, file_bytes)
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    try:
        conn.request("POST", "/v1/audio/transcriptions", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **(headers or {}),
        })
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read()
    finally:
        conn.close()


def _get_json(srv, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


# --- route parsing -----------------------------------------------------------

def test_parse_route_openai_paths():
    r = parse_route("POST", "/v1/audio/transcriptions")
    assert r.name == "openai_transcriptions"
    assert parse_route("POST", "/v1/audio/transcriptions/").name == \
        "openai_transcriptions"
    assert parse_route("GET", "/v1/models").name == "openai_models"


# --- pure helpers ------------------------------------------------------------

def test_openai_error_payload_shape():
    payload = openai_error_payload("bad thing", param="model")
    assert payload == {"error": {
        "message": "bad thing", "type": "invalid_request_error",
        "param": "model", "code": None,
    }}


def test_openai_full_text_joins_segments():
    segments = [{"text": " Hello "}, {"text": ""}, {"text": "world"}]
    assert openai_full_text(segments) == "Hello world"
    assert openai_full_text([]) == ""


def test_build_openai_verbose_json_shape():
    segments = [{
        "start": 0.0, "end": 2.0, "text": "Hi",
        "words": [{"word": "Hi", "start": 0.0, "end": 2.0}],
    }]
    out = build_openai_verbose_json(segments, language="en")
    assert out["task"] == "transcribe"
    assert out["language"] == "en"
    assert out["duration"] == 2.0
    assert out["text"] == "Hi"
    assert out["usage"] == {"type": "duration", "seconds": 2}
    seg = out["segments"][0]
    assert set(seg) == {
        "id", "seek", "start", "end", "text", "tokens", "temperature",
        "avg_logprob", "compression_ratio", "no_speech_prob",
    }
    assert seg["id"] == 0
    assert out["words"] == [{"word": "Hi", "start": 0.0, "end": 2.0}]


def test_build_openai_verbose_json_omits_words_when_absent():
    out = build_openai_verbose_json([{"start": 0, "end": 1, "text": "x"}])
    assert "words" not in out


# --- HTTP round-trips --------------------------------------------------------

def test_json_response(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "language": "en"})
        assert status == 200
        assert ctype.startswith("application/json")
        assert json.loads(body.decode("utf-8")) == {"text": "Hello world"}


def test_text_response(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "response_format": "text"})
        assert status == 200
        assert ctype.startswith("text/plain")
        assert body.decode("utf-8") == "Hello world"


def test_srt_response(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "response_format": "srt"})
        assert status == 200
        assert ctype.startswith("text/plain")
        text = body.decode("utf-8")
        assert "Hello world" in text
        assert "-->" in text


def test_vtt_response(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "response_format": "vtt"})
        assert status == 200
        assert body.decode("utf-8").startswith("WEBVTT")


def test_verbose_json_response(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "response_format": "verbose_json"})
        assert status == 200
        assert ctype.startswith("application/json")
        out = json.loads(body.decode("utf-8"))
        assert out["task"] == "transcribe"
        # The stub's detected language is what the response reports.
        assert out["language"] == "en"
        assert out["text"] == "Hello world"
        assert out["duration"] == 1.5
        assert len(out["segments"]) == 1
        assert out["segments"][0]["text"] == "Hello world"
        assert len(out["words"]) == 2


def test_missing_model_is_400(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ctype, body = _post_transcription(srv, {})
        assert status == 400
        err = json.loads(body.decode("utf-8"))["error"]
        assert "model" in err["message"]
        assert err["param"] == "model"


def test_bad_response_format_is_400(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ctype, body = _post_transcription(
            srv, {"model": "whisper-1", "response_format": "diarized_json"})
        assert status == 400
        err = json.loads(body.decode("utf-8"))["error"]
        assert err["param"] == "response_format"
        for fmt in OPENAI_RESPONSE_FORMATS:
            assert fmt in err["message"]


def test_missing_file_part_is_400(tmp_path):
    with _RunningServer(tmp_path) as srv:
        boundary = "----openai-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="model"\r\n\r\n'
            "whisper-1\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("POST", "/v1/audio/transcriptions", body=body, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            resp = conn.getresponse()
            assert resp.status == 400
            assert "file" in json.loads(
                resp.read().decode("utf-8"))["error"]["message"].lower()
        finally:
            conn.close()


def test_non_multipart_body_is_400(tmp_path):
    with _RunningServer(tmp_path) as srv:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request(
                "POST", "/v1/audio/transcriptions",
                body=json.dumps({"model": "whisper-1"}).encode(),
                headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 400
            assert "error" in json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()


def test_bearer_token_is_accepted(tmp_path):
    with _RunningServer(tmp_path, token="s3cret") as srv:
        # No credentials -> 401 in the OpenAI error envelope.
        status, _ctype, body = _post_transcription(
            srv, {"model": "whisper-1"})
        assert status == 401
        err = json.loads(body.decode("utf-8"))["error"]
        assert err["code"] == "invalid_api_key"
        # Authorization: Bearer <token> -> accepted.
        status, _ctype, body = _post_transcription(
            srv, {"model": "whisper-1"},
            headers={"Authorization": "Bearer s3cret"})
        assert status == 200
        assert json.loads(body.decode("utf-8"))["text"] == "Hello world"
        # A wrong bearer token is rejected.
        status, _ctype, _body = _post_transcription(
            srv, {"model": "whisper-1"},
            headers={"Authorization": "Bearer nope"})
        assert status == 401


def test_transcribe_failure_is_500(tmp_path):
    def boom(task, progress_cb=None, log_cb=None, language_cb=None):
        raise RuntimeError("engine exploded")

    with _RunningServer(tmp_path, transcribe_fn=boom) as srv:
        status, _ctype, body = _post_transcription(
            srv, {"model": "whisper-1"})
        assert status == 500
        err = json.loads(body.decode("utf-8"))["error"]
        assert err["type"] == "server_error"
        assert "engine exploded" in err["message"]


def test_models_endpoint(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, body = _get_json(srv, "/v1/models")
        assert status == 200
        assert body["object"] == "list"
        assert body["data"][0]["id"] == "whisper-1"


def test_openai_job_appears_in_job_list(tmp_path):
    """The synchronous route still goes through the normal job queue."""
    with _RunningServer(tmp_path) as srv:
        _post_transcription(srv, {"model": "whisper-1"})
        deadline = time.time() + 3
        jobs = []
        while time.time() < deadline:
            _status, body = _get_json(srv, "/api/jobs")
            jobs = body["jobs"]
            if jobs and jobs[0]["status"] == "finished":
                break
            time.sleep(0.05)
        assert jobs and jobs[0]["status"] == "finished"
