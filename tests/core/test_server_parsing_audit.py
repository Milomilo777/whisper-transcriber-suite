from __future__ import annotations

import json
import socket
import http.client
from pathlib import Path
from http import HTTPStatus

import pytest
from hypothesis import settings, given, strategies as st

from tests.core.test_server_health import _RunningServer

@pytest.fixture
def running_server(tmp_path):
    with _RunningServer(tmp_path) as s:
        yield s


@pytest.fixture(autouse=True)
def _keep_uploaded_media(monkeypatch):
    # The stub job finishes at once and JobManager then deletes the uploaded media; the tests that read the
    # saved upload back would race that delete.
    from core.server.jobs import JobManager
    monkeypatch.setattr(JobManager, "_drop_input_media", lambda self, job: None)

def test_audit_json_body_cap(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{"url": "x"}'
    body = body.ljust(1 * 1024 * 1024 + 1, b" ") # > 1MB
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    conn.close()


def test_audit_multipart_options(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    # Let's write a multipart payload
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
        'test audio content\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="formats"\r\n\r\n'
        'srt,vtt\r\n'
        f"--{boundary}--\r\n"
    ).encode('utf-8')
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp.read()
    conn.close()


def test_audit_json_body_cap_content_type(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{"url": "x"}'
    headers = {"Content-Type": "text/plain"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    conn.close()

def test_audit_json_body_invalid(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{"url": "x"' # invalid json
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()


def test_audit_json_body_non_object(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'["a list"]'
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()


def test_audit_json_no_url(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{}'
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()


def test_audit_json_wrong_types(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = json.dumps({"url": "http://x", "formats": {"bad": "type"}}).encode()
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    conn.close()


def test_audit_json_wrong_type_options(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = json.dumps({"url": "http://x", "word_timestamps": "not_a_boolean"}).encode()
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp.read()
    conn.close()


def test_audit_json_body_cap_edge(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{"url": "x"}'
    # exactly 1 MB
    body = body.ljust(1 * 1024 * 1024, b" ")
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST  # fails validation but body accepted
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    # > 1MB
    body = body.ljust(1 * 1024 * 1024 + 1, b" ")
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    conn.close()


def test_audit_json_body_cap_content_length_absent(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    # The client isn't sending Content-Length header, our server reads it as 0
    # when processing JSON body? Let's see:
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.endheaders()
    conn.send(b'{"url": "x"}')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()

def test_audit_json_body_cap_content_length_negative(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "-10")
    conn.endheaders()
    conn.send(b'{"url": "x"}')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()
def test_audit_json_body_cap_content_length_wrong(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "9999999999999")
    conn.endheaders()
    conn.send(b'{"url": "x"}')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    conn.close()


def test_audit_json_chunked(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    conn.send(b'A\r\n{"url":"x"}\r\n0\r\n\r\n')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.LENGTH_REQUIRED
    conn.close()


def test_audit_multipart_huge_part_then_fields(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    # Let's write a multipart payload where file part is > 1MB, followed by form fields > 64KB
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    part1_body = b"0" * (1 * 1024 * 1024 + 10)
    part2_header = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="formats"\r\n\r\n'
    ).encode('utf-8')
    part2_body = b"srt," * (16 * 1024 + 10)
    part3_header = (
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    body = part1_header + part1_body + part2_header + part2_body + part3_header
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp.read()
    conn.close()


def test_audit_multipart_huge_part_then_fields_past_tail_window(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    part1_body = b"0" * (1 * 1024 * 1024 + 10)
    part2_header = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="formats"\r\n\r\n'
    ).encode('utf-8')
    # Make the field much larger than tail window (64 KB). The test should either succeed or fail gracefully.
    part2_body = b"srt," * (32 * 1024) # ~ 128 KB
    part3_header = (
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    body = part1_header + part1_body + part2_header + part2_body + part3_header
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp.read()
    conn.close()


def test_audit_multipart_options_missing_boundary(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
        'test audio content\r\n'
        # Missing trailing boundary!
    ).encode('utf-8')
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp.read()
    conn.close()


def test_audit_multipart_options_crlf_vs_lf(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    # Send LF instead of CRLF in headers
    body = (
        f"--{boundary}\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\n'
        'Content-Type: audio/wav\n\n'
        'test audio content\n'
        f"--{boundary}--\n"
    ).encode('utf-8')
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    resp.read()
    conn.close()


def test_audit_error_reply_no_absolute_path_or_stacktrace(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    # Cause a server error intentionally if we can. What if we send very malformed data?
    # Or what if we post something to an endpoint that crashes? Let's just check the existing handlers
    # like a bad JSON or upload that fails.
    # Bad JSON gives 400 invalid JSON body, we already verified that.
    # Let's try an upload that raises an OSError during copy. It's hard to trigger here without mocking.
    conn.request("POST", "/api/jobs", b'{"url": "x"}', {"Content-Type": "application/json", "Content-Length": "99999999999"})
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    assert resp.status == 413
    assert "Traceback" not in body
    assert "://" not in body
    assert "C:\\" not in body
    assert "/" not in body
    conn.close()

def test_audit_json_body_cap_content_length_invalid(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "invalid")
    conn.endheaders()
    conn.send(b'{"url": "x"}')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()


def test_audit_json_huge_json(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    body = b'{"url": "x"'
    body += b',"dummy":"' + b"a" * 1024 * 1024 + b'"}'
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    resp.read()
    conn.close()


def test_audit_multipart_boundary_inside_data():
    from core.server.httpd import scan_multipart_file
    boundary = "bound"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
        'hello--bound--world\r\n'
        f"--{boundary}--\r\n"
    ).encode('utf-8')
    parts = scan_multipart_file(body, boundary)
    assert body[parts.file_start:parts.file_end] == b"hello--bound--world"


def test_audit_safe_filename():
    from core.server.jobs import _MAX_UPLOAD_EXT, _MAX_UPLOAD_STEM, _safe_filename

    # Built with chr() so this file holds no invisible combining characters.
    assert _safe_filename("cafe" + chr(0x301) + ".wav") == "caf" + chr(0xE9) + ".wav"  # NFC (macOS names)
    assert _safe_filename("گفتگو.mp3") == "گفتگو.mp3"
    assert _safe_filename("C:" + chr(92) + "x.wav") == "x.wav"
    assert _safe_filename("../x") == "x"
    assert _safe_filename("CON") == "_CON"
    assert _safe_filename("NUL.txt") == "_NUL.txt"
    capped = _safe_filename("a" * 300 + ".wav")
    assert capped == "a" * _MAX_UPLOAD_STEM + ".wav" and len(capped) <= _MAX_UPLOAD_STEM + _MAX_UPLOAD_EXT

def test_audit_multipart_zero_length_file(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    resp.read()
    conn.close()


@settings(derandomize=True, deadline=None, database=None)
@given(
    st.binary(min_size=0, max_size=1000),
    st.text(min_size=0, max_size=50)
)
def test_hypothesis_scan_multipart(data, boundary):
    from core.server.httpd import scan_multipart_file
    # Check it doesn't crash on garbage inputs
    scan_multipart_file(data, boundary)


def test_audit_json_body_no_content_length_empty_body(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs/some_id/cancel")
    conn.endheaders()
    # Sending no body at all. This should be accepted as empty body.
    resp = conn.getresponse()
    assert resp.status in (HTTPStatus.OK, HTTPStatus.NOT_FOUND, HTTPStatus.NO_CONTENT) # not found is fine since some_id is fake
    conn.close()
def test_audit_json_body_malformed_content_length(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "abc")
    conn.endheaders()
    conn.send(b'{"url": "x"}')
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.BAD_REQUEST
    conn.close()

@pytest.mark.parametrize("bad_len", [
    "1_0", "+5", " 12 ", "\u0661\u0662", "abc", "-10"
])
def test_audit_json_body_cap_content_length_strict(running_server, bad_len):
    # Testing that malformed headers are rejected strictly
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", running_server.port))
    req = f"POST /api/jobs HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {bad_len}\r\n\r\n{{\"url\": \"x\"}}"
    s.sendall(req.encode('utf-8'))
    resp = s.recv(1024)
    s.close()
    # We should get a 400 Bad Request
    assert b"400 Bad Request" in resp



@pytest.mark.parametrize("offset", [0, 1, 2])
def test_audit_multipart_data_corruption_offsets(running_server, offset):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    # We want tail window to split the boundary and CRLF exactly.
    # We monkeypatch the server so the windows are small.
    import core.server.httpd
    old_head = core.server.httpd._MULTIPART_HEADER_WINDOW
    old_tail = core.server.httpd._MULTIPART_TAIL_WINDOW
    try:
        core.server.httpd._MULTIPART_HEADER_WINDOW = 256
        core.server.httpd._MULTIPART_TAIL_WINDOW = 64
        # Calculate body so the closing boundary is exactly at the tail window boundary + offset
        part1_body = b"0" * 300
        part2_header = (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="formats"\r\n\r\n'
            'srt\r\n'
        ).encode('utf-8')
        part3_header = (
            f"--{boundary}--\r\n"
        ).encode('utf-8')
        body = part1_header + part1_body + part2_header + part3_header
        # Adjust body size so that tail window (last 64 bytes) starts exactly `offset` bytes
        # into the `\r\n--boundary` delimiter.
        # delim is part2_header (which starts with \r\n--boundary...)
        # tail window is 64 bytes long.
        # body length is len(part1_header) + len(part1_body) + len(part2_header) + len(part3_header)
        # tail starts at len(body) - 64
        # We want tail_start == len(part1_header) + len(part1_body) + offset
        # len(body) - 64 == len(part1_header) + len(part1_body) + offset
        # len(part1_body) + ... - 64 == len(...) + len(part1_body) + offset
        # len(part2_header) + len(part3_header) - 64 == offset
        # So we pad part3_header to make this true!
        target_tail_len = len(part2_header) + len(part3_header) - offset
        core.server.httpd._MULTIPART_TAIL_WINDOW = target_tail_len
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body))
        }
        conn.request("POST", "/api/jobs", body, headers)
        resp = conn.getresponse()
        assert resp.status == HTTPStatus.ACCEPTED
        resp_data = resp.read()
        conn.close()
        import time
        # wait a bit for job setup in tests
        job_id = json.loads(resp_data)["job_id"]
        job_dir = Path(running_server.tmp_path) / "server_jobs" / job_id
        for _ in range(20):
            if (job_dir / "test.wav").exists():
                break
            time.sleep(0.1)
        with open(job_dir / "test.wav", "rb") as f:
            saved = f.read()
            assert saved == part1_body
            assert len(saved) == len(part1_body)
    finally:
        core.server.httpd._MULTIPART_HEADER_WINDOW = old_head
        core.server.httpd._MULTIPART_TAIL_WINDOW = old_tail


def test_audit_multipart_binary_truncation_proof():
    from core.server.httpd import scan_multipart_file
    boundary = "bound"
    # Binary payload contains `\n--bound` and `\r--bound` and `--bound`
    payload = b"test\n--bound\r--bound--boundtest"
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    part3_header = (
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    body = part1_header + payload + part3_header
    parts = scan_multipart_file(body, boundary)
    assert parts.file_start == len(part1_header)
    assert parts.file_end == len(part1_header) + len(payload)
    saved_payload = body[parts.file_start:parts.file_end]
    assert saved_payload == payload


def test_audit_multipart_binary_truncation_proof_server(running_server):
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    payload = b"test\n--" + boundary.encode('utf-8') + b"\r--" + boundary.encode('utf-8') + b"test"
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    part3_header = (
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    body = part1_header + payload + part3_header
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }
    conn.request("POST", "/api/jobs", body, headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.ACCEPTED
    resp_data = resp.read()
    conn.close()
    import time
    job_id = json.loads(resp_data)["job_id"]
    job_dir = Path(running_server.tmp_path) / "server_jobs" / job_id
    for _ in range(20):
        if (job_dir / "test.wav").exists():
            break
        time.sleep(0.1)
    with open(job_dir / "test.wav", "rb") as f:
        saved = f.read()
        assert saved == payload
        assert len(saved) == len(payload)


@settings(derandomize=True, deadline=None, database=None)
@given(
    st.binary(min_size=0, max_size=1000).filter(lambda x: b"--bound" not in x),
    st.text(min_size=0, max_size=50)
)
def test_hypothesis_scan_multipart_roundtrip(data, garbage):
    from core.server.httpd import scan_multipart_file
    boundary = "bound"
    part1_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    part3_header = (
        f"\r\n--{boundary}--\r\n"
    ).encode('utf-8')
    body = part1_header + data + part3_header
    parts = scan_multipart_file(body, boundary)
    assert parts.file_start == len(part1_header)
    assert parts.file_end == len(part1_header) + len(data)
    assert body[parts.file_start:parts.file_end] == data

@settings(derandomize=True, deadline=None, database=None)
@given(
    st.binary(min_size=0, max_size=1000),
    st.text(min_size=1, max_size=10).filter(lambda x: x.isascii())
)
def test_hypothesis_scan_multipart_invariants(data, boundary):
    from core.server.httpd import scan_multipart_file
    parts = scan_multipart_file(data, boundary)
    if parts.file_start >= 0:
        assert 0 <= parts.file_start <= parts.file_end <= len(data)


@pytest.mark.parametrize("digits", [19, 4301, 6000])
def test_audit_json_content_length_with_thousands_of_digits_gets_a_reply(running_server, digits):
    # int() refuses more than 4300 digits; that ValueError used to kill the handler with no reply.
    conn = http.client.HTTPConnection("127.0.0.1", running_server.port, timeout=10)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "9" * digits)
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    conn.close()


@pytest.mark.parametrize("padding", [b" ", b"\t", b"  \t "])
def test_audit_multipart_transport_padding_after_the_delimiter(padding):
    # RFC 2046 allows spaces/tabs between a delimiter and its CRLF.
    from core.server.httpd import scan_multipart_file
    body = (b"--XbX" + padding + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n\r\n'
            b"DATA\r\n--XbX" + padding + b"\r\n"
            b'Content-Disposition: form-data; name="formats"\r\n\r\nsrt\r\n--XbX--' + padding + b"\r\n")
    parts = scan_multipart_file(body, "XbX")
    assert body[parts.file_start:parts.file_end] == b"DATA"
    assert parts.filename == "a.wav"
    assert parts.fields == {"formats": "srt"}


@pytest.mark.parametrize("value", ["{n}  ", "{n}\t", " {n}"])
def test_audit_json_content_length_with_surrounding_whitespace_is_accepted(running_server, value):
    # RFC 9110 allows optional whitespace around a field value; 2.0.0 accepted it (int() strips it),
    # the stricter digit check after it answered 400 "bad length".
    body = b'{"url": "x"}'
    statuses = []
    for header in (str(len(body)), value.format(n=len(body))):
        conn = http.client.HTTPConnection("127.0.0.1", running_server.port, timeout=10)
        conn.putrequest("POST", "/api/jobs")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", header)
        conn.endheaders()
        conn.send(body)
        resp = conn.getresponse()
        statuses.append((resp.status, resp.read()))
        conn.close()
    assert statuses[1][0] == statuses[0][0], statuses
    assert b"bad length" not in statuses[1][1]


def test_audit_all_interfaces_ipv6_bind_also_takes_ipv4(monkeypatch):
    # "::" lists 127.0.0.1 and the LAN IPv4 address (reachable_urls), so the socket must be dual-stack;
    # Windows makes IPv6 sockets IPv6-only by default. The real bind is skipped (no firewall prompt).
    import socket
    import socketserver
    from core.server.httpd import JobHTTPServer
    from core.server.jobs import JobManager
    if not socket.has_ipv6:
        pytest.skip("no IPv6 support")
    monkeypatch.setattr(socketserver.TCPServer, "server_bind", lambda self: None)
    monkeypatch.setattr(socketserver.TCPServer, "server_activate", lambda self: None)
    server = JobHTTPServer(("::", 0), JobManager(lambda *a, **k: None))
    try:
        assert server.socket.family == socket.AF_INET6
        assert server.socket.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
    finally:
        server.server_close()
