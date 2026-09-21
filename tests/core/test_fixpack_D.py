"""Regression tests for fixpack cluster D (core/server hardening).

Covers five confirmed bugs in the LAN/web HTTP job server:

  1. ``token_ok`` crashed (TypeError) on a non-ASCII candidate / configured
     token because ``hmac.compare_digest`` rejects non-ASCII str operands.
  2. The multipart upload was buffered whole in RAM (twice) despite the
     "never fully buffered" design claim — now the file part's byte range is
     copied straight from the temp file, never materialised in RAM.
  3. ``JobManager.stop()`` leaked the worker thread when a job was PAUSED in
     flight (the engine's ``while task.paused`` spin never saw a stop signal).
  4. The JSON / URL control POST body was capped only at the (large) upload
     cap — a tiny intended JSON call could be inflated to the upload cap.
  5. ``is_safe_url`` only validated the scheme — an SSRF surface to loopback /
     cloud-metadata targets.

Hermetic: no real Whisper model, no network (DNS is stubbed for the SSRF
tests), no Tk root. The streaming / JSON-cap tests bind a real
ThreadingHTTPServer on 127.0.0.1:0 with a STUBBED transcribe, mirroring the
repo's existing ``tests/core/test_server_http_control.py`` pattern.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time

import pytest

from core.server import httpd as httpd_mod
from core.server import jobs as jobs_mod
from core.server.httpd import (
    JobHTTPServer,
    scan_multipart_file,
    token_ok,
)
from core.server.jobs import (
    STATUS_CANCELLED,
    STATUS_FINISHED,
    JobManager,
    is_safe_url,
)


# =============================================================================
# Fix 1: token_ok is byte-safe (no TypeError on non-ASCII).
# =============================================================================

def test_token_ok_non_ascii_candidate_does_not_raise():
    """A non-ASCII ?token= must NOT crash the comparison; it just fails auth.

    Pre-fix, hmac.compare_digest('secret', 'café') raised TypeError that
    propagated out of the handler, dropping the connection on every such
    request — a remote unauthenticated DoS.
    """
    assert token_ok("secret", None, "café") is False
    assert token_ok("secret", "café", None) is False


def test_token_ok_non_ascii_configured_token_still_authenticates():
    """An operator who chose a non-Latin token must not be locked out.

    Pre-fix, EVERY comparison against a non-ASCII configured token raised,
    so even the correct token failed and the server was unusable.
    """
    assert token_ok("päss", None, "päss") is True
    assert token_ok("päss", "päss", None) is True
    assert token_ok("päss", None, "pass") is False


def test_token_ok_plain_cases_unchanged():
    assert token_ok("", "anything", None) is True  # no token configured
    assert token_ok("secret", "secret", None) is True
    assert token_ok("secret", None, "secret") is True
    assert token_ok("secret", "nope", "nope") is False


# =============================================================================
# Fix 5: is_safe_url SSRF guard (loopback / link-local / metadata blocked,
#        ordinary RFC-1918 LAN still allowed).
# =============================================================================

def _stub_getaddrinfo(monkeypatch, mapping):
    """Resolve the named test hosts to fixed IPs; delegate everything else
    (e.g. the loopback the HTTP client connects to) to the real resolver, so
    the SSRF resolution path is deterministic without breaking real sockets."""
    real = jobs_mod.socket.getaddrinfo

    def fake(host, *a, **k):
        if host in mapping:
            return [(2, 1, 6, "", (mapping[host], 0))]
        return real(host, *a, **k)
    monkeypatch.setattr(jobs_mod.socket, "getaddrinfo", fake)


def test_is_safe_url_blocks_loopback_and_metadata_literals():
    assert is_safe_url("http://127.0.0.1/x") is False
    assert is_safe_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_url("http://[::1]/x") is False
    assert is_safe_url("http://0.0.0.0/x") is False


def test_is_safe_url_allows_ordinary_lan_literals():
    # RFC-1918 private ranges are the documented normal LAN use — keep them.
    assert is_safe_url("http://192.168.1.50:8080/m.mp4") is True
    assert is_safe_url("http://10.0.0.5/v") is True
    assert is_safe_url("http://172.16.4.4/v") is True


def test_is_safe_url_blocks_names_resolving_to_loopback(monkeypatch):
    _stub_getaddrinfo(monkeypatch, {"evil.test": "127.0.0.1"})
    assert is_safe_url("http://evil.test/x") is False


def test_is_safe_url_blocks_names_resolving_to_metadata(monkeypatch):
    _stub_getaddrinfo(monkeypatch, {"meta.test": "169.254.169.254"})
    assert is_safe_url("http://meta.test/x") is False


def test_is_safe_url_allows_names_resolving_to_public_addr(monkeypatch):
    _stub_getaddrinfo(monkeypatch, {"ok.test": "93.184.216.34"})
    assert is_safe_url("http://ok.test/v") is True


def test_is_safe_url_allows_name_that_fails_to_resolve(monkeypatch):
    # A resolution failure is allowed through (the fetch layer reports the
    # real error) so transient DNS does not block normal URLs.
    _stub_getaddrinfo(monkeypatch, {})  # nothing resolves
    assert is_safe_url("http://nonexistent.invalid/v") is True


def test_is_safe_url_scheme_and_host_gate_unchanged(monkeypatch):
    _stub_getaddrinfo(monkeypatch, {})
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("ftp://host/x") is False
    assert is_safe_url("/local/path") is False
    assert is_safe_url("") is False
    assert is_safe_url("https://") is False  # no host


def test_is_safe_url_blocks_legacy_numeric_loopback(monkeypatch):
    # inet_aton-style numeric forms of 127.0.0.1. The resolver is stubbed to
    # FAIL (like Windows getaddrinfo does for these forms) to prove the
    # refusal is static and does not depend on the fail-open DNS path.
    def boom(host, *a, **k):
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(jobs_mod.socket, "getaddrinfo", boom)
    for url in (
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0x7f.0.0.1/",
        "http://0177.0.0.1/",
        "http://127.1/",
        "http://0x7f.1/",
    ):
        assert is_safe_url(url) is False, url


def test_is_safe_url_numeric_private_matches_dotted_form(monkeypatch):
    # A numeric encoding of an RFC-1918 address follows the dotted form's
    # verdict (allowed) — the fix must not over-block the LAN normal case.
    def boom(host, *a, **k):
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(jobs_mod.socket, "getaddrinfo", boom)
    assert is_safe_url("http://3232235521/") is True  # == 192.168.0.1
    assert is_safe_url("http://0xC0A80101/") is True  # == 192.168.1.1
    assert is_safe_url("http://1.2.3.256/") is True  # not numeric at all


def test_submit_url_rejects_loopback(tmp_path):
    mgr = JobManager(
        lambda *a, **k: None,
        jobs_root=str(tmp_path / "j"), record_history=False,
    )
    with pytest.raises(ValueError):
        mgr.submit_url("http://127.0.0.1:9000/internal", ["srt"])


# =============================================================================
# Fix 2 (pure): scan_multipart_file locates the file-part byte range without
#               copying the payload.
# =============================================================================

def _multipart_body(boundary, fields, filename, file_bytes):
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode() + b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'
        f"\r\n".encode())
    parts.append(b"Content-Type: video/mp4\r\n\r\n")
    parts.append(file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def test_scan_multipart_file_finds_range_and_fields():
    boundary = "----b0undary"
    payload = b"RAWMEDIA-" + bytes(range(256)) * 4
    body = _multipart_body(
        boundary, {"formats": "srt,txt", "language": "en-US"},
        "clip.mp4", payload)
    parts = scan_multipart_file(body, boundary)
    assert parts.filename == "clip.mp4"
    assert parts.fields == {"formats": "srt,txt", "language": "en-US"}
    assert body[parts.file_start:parts.file_end] == payload


def test_scan_multipart_file_no_file_part():
    boundary = "b"
    body = (f"--{boundary}\r\n".encode()
            + b'Content-Disposition: form-data; name="formats"\r\n\r\n'
            + b"srt\r\n" + f"--{boundary}--\r\n".encode())
    parts = scan_multipart_file(body, boundary)
    assert parts.file_start == -1
    assert parts.fields == {"formats": "srt"}


def test_extract_from_file_tail_window_recovers_end(tmp_path, monkeypatch):
    """The file-part END is recovered from a bounded tail window when the
    payload exceeds the leading header window — proving the payload is never
    fully read into RAM during extraction."""
    boundary = "----bnd"
    payload = b"Z" * (300 * 1024)
    body = _multipart_body(boundary, {"formats": "srt"}, "big.mp4", payload)
    tmp = tmp_path / "u.part"
    tmp.write_bytes(body)
    # Force a tiny leading window so the file body extends past it and the
    # tail-window recovery path must run.
    monkeypatch.setattr(httpd_mod, "_MULTIPART_HEADER_WINDOW", 512)
    monkeypatch.setattr(httpd_mod, "_MULTIPART_TAIL_WINDOW", 4096)
    fn, start, end, fields = httpd_mod.JobRequestHandler._extract_upload_from_file(
        str(tmp), len(body), boundary)
    assert fn == "big.mp4"
    assert fields == {"formats": "srt"}
    assert body[start:end] == payload


# =============================================================================
# Fixes 2 & 4 over HTTP: streaming upload writes the exact payload; the JSON
# control body is capped small.
# =============================================================================

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


def _wait_finished(srv, job_id, timeout=5):
    deadline = time.time() + timeout
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        while time.time() < deadline:
            conn.request("GET", f"/api/jobs/{job_id}")
            body = json.loads(conn.getresponse().read().decode("utf-8"))
            if body["status"] in ("finished", "error", "cancelled"):
                return body
            time.sleep(0.04)
    finally:
        conn.close()
    return None


def test_streamed_upload_preserves_exact_payload(tmp_path):
    """End-to-end: the streamed file part lands on disk byte-for-byte.

    Exercises the temp-file -> range-copy path that replaced the
    whole-body read + extract_upload double-buffer.
    """
    captured = {}

    def _capture(task, progress_cb=None, log_cb=None, language_cb=None):
        with open(task.file_path, "rb") as f:
            captured["bytes"] = f.read()
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]
        if progress_cb:
            progress_cb(100)

    payload = bytes(range(256)) * 700  # ~175 KB, non-trivial + binary-safe
    with _RunningServer(tmp_path, transcribe_fn=_capture) as srv:
        boundary = "----bnd"
        body = _multipart_body(boundary, {"formats": "srt"}, "v.bin", payload)
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("POST", "/api/jobs", body=body, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            resp = conn.getresponse()
            assert resp.status == 202
            data = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()
        out = _wait_finished(srv, data["job_id"])
        assert out is not None and out["status"] == "finished"
        assert captured.get("bytes") == payload


def test_json_control_body_is_capped_small(tmp_path):
    """A non-multipart POST body over the small JSON cap is rejected 413,
    independent of the (much larger) multipart upload cap.

    Pre-fix, the JSON/URL control path read up to the full upload cap into
    RAM — a memory-amplification DoS with no media involved.
    """
    with _RunningServer(tmp_path, max_upload_mb=512) as srv:
        # Just over the 1 MiB JSON cap, well under the 512 MB upload cap.
        big = b'{"url":"' + b"a" * (2 * 1024 * 1024) + b'"}'
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("POST", "/api/jobs", body=big,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 413
            resp.read()
        finally:
            conn.close()


def test_small_json_url_body_still_accepted(tmp_path, monkeypatch):
    """A normal small JSON url body is unaffected by the new cap."""
    # Keep it offline + deterministic: a literal public-ish address avoids a
    # real DNS lookup inside is_safe_url, but stub getaddrinfo too as a guard.
    _stub_getaddrinfo(monkeypatch, {"media.lan.test": "203.0.113.10"})
    with _RunningServer(tmp_path) as srv:
        payload = json.dumps({"url": "http://media.lan.test/v",
                              "formats": "srt"}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("POST", "/api/jobs", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            # Accepted (202) — the URL job is created (it will later error with
            # no downloader configured, but that is a separate, later state).
            assert resp.status == 202
            resp.read()
        finally:
            conn.close()


# =============================================================================
# Fix 3: stop() unblocks a PAUSED in-flight job so the worker thread exits.
# =============================================================================

def test_stop_joins_worker_when_job_is_paused(tmp_path):
    """A paused in-flight job must not leak the worker thread on stop().

    The fake transcribe mirrors the engine's pause spin
    (``while task.paused and not task.cancelled``). Pre-fix, stop() set its
    own _stop flag but never cleared the job's pause / set cancel, so the
    worker stayed parked forever and join() timed out (thread leak). Post-fix,
    stop() flips cancelled=True / paused=False on every non-terminal job, so
    the spin exits and the worker thread joins.
    """
    entered = threading.Event()

    def _pausing(task, progress_cb=None, log_cb=None, language_cb=None):
        # Mirror the engine's segment loop: many iterations, each honouring
        # the pause spin (``while task.paused and not task.cancelled``) and
        # breaking out on cancel. ``entered`` fires once we are looping so the
        # test can pause us while we are demonstrably parked.
        for _ in range(100_000):
            entered.set()
            if task.cancelled:
                return
            while task.paused and not task.cancelled:
                time.sleep(0.02)
            if task.cancelled:
                return
            time.sleep(0.005)
        base, _ = os.path.splitext(task.file_path)
        with open(f"{base}.srt", "w", encoding="utf-8") as f:
            f.write("x")
        task.output_paths = [f"{base}.srt"]

    mgr = JobManager(
        _pausing, jobs_root=str(tmp_path / "j"), record_history=False)
    mgr.start()
    jid = mgr.submit_upload("clip.mp4", b"\x00\x01\x02", ["srt"])
    assert entered.wait(timeout=5), "worker never started the job"
    # Pause the in-flight job, then confirm the worker is parked in the spin.
    assert mgr.pause(jid) is True
    time.sleep(0.1)
    job = mgr.get(jid)
    assert job is not None and job.paused is True

    # stop() must un-park + join the worker within the timeout.
    mgr.stop(timeout=5.0)
    worker = mgr._worker
    assert worker is not None
    assert worker.is_alive() is False, "worker thread leaked (join timed out)"
    # The paused job was cancelled out so the spin could exit.
    job = mgr.get(jid)
    assert job is not None
    assert job.cancelled is True


def test_stop_with_no_jobs_is_clean(tmp_path):
    mgr = JobManager(
        lambda *a, **k: None,
        jobs_root=str(tmp_path / "j"), record_history=False)
    mgr.start()
    mgr.stop(timeout=5.0)
    assert mgr._worker is not None and mgr._worker.is_alive() is False


def test_cancel_still_unblocks_paused_job(tmp_path):
    """Sanity: the existing cancel() path (cancelled=True / paused=False)
    still ends a paused in-flight job (the behaviour stop() now mirrors)."""
    entered = threading.Event()

    def _pausing(task, progress_cb=None, log_cb=None, language_cb=None):
        for _ in range(100_000):
            entered.set()
            if task.cancelled:
                return
            while task.paused and not task.cancelled:
                time.sleep(0.02)
            if task.cancelled:
                return
            time.sleep(0.005)

    mgr = JobManager(
        _pausing, jobs_root=str(tmp_path / "j"), record_history=False)
    mgr.start()
    try:
        jid = mgr.submit_upload("a.mp4", b"d", ["srt"])
        assert entered.wait(timeout=5)
        assert mgr.pause(jid) is True
        time.sleep(0.05)
        assert mgr.cancel(jid) is True
        deadline = time.time() + 5
        while time.time() < deadline:
            job = mgr.get(jid)
            if job is not None and job.status in (
                    STATUS_CANCELLED, STATUS_FINISHED):
                break
            time.sleep(0.02)
        job = mgr.get(jid)
        assert job is not None and job.status == STATUS_CANCELLED
    finally:
        mgr.stop()
