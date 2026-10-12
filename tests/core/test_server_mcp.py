"""MCP endpoint: the pure dispatcher (core.server.mcp) and POST /mcp.

The dispatcher tests drive ``mcp.handle`` with a stub manager. The socket
tests run a real JobHTTPServer on 127.0.0.1:0 with a fake download and a fake
transcribe function (no model, no network egress) and check the HTTP framing
of the MCP Streamable HTTP transport (revision 2025-06-18).
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time
from typing import Any

import pytest

from core import __version__
from core.server import httpd, mcp
from core.server.httpd import JobHTTPServer
from core.server.jobs import STATUS_FINISHED, Job, JobManager, QueueFull
from core.writers import BINARY_WRITERS, supported_formats


# --- dispatcher (no socket) ---------------------------------------------------

class _StubManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.cancelled: set[str] = set()
        self.submitted: list[dict[str, Any]] = []
        self.paths: dict[tuple[str, str], str] = {}
        self.raise_on_submit: Exception | None = None

    def submit_url(self, url, formats, language="", *, options=None,
                   clip_start=None, clip_end=None):
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        job_id = f"stub{len(self.jobs) + 1}"
        self.submitted.append({"url": url, "formats": formats,
                               "language": language, "options": options,
                               "clip_start": clip_start, "clip_end": clip_end})
        self.jobs[job_id] = Job(job_id=job_id, kind="url", source=url,
                                formats=list(formats), language=language)
        return job_id

    def get(self, job_id):
        return self.jobs.get(job_id)

    def list(self):
        return [j.list_dict() for j in self.jobs.values()]

    def cancel(self, job_id):
        if job_id in self.jobs and job_id not in self.cancelled:
            self.cancelled.add(job_id)
            return True
        return False

    def output_path(self, job_id, fmt):
        return self.paths.get((job_id, fmt.lower()))


def _rpc(method: str, params: Any = None, msg_id: Any = 1) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _call(mgr: Any, name: str, arguments: Any = None,
          msg_id: Any = 7) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    res = mcp.handle(_rpc("tools/call", params, msg_id), mgr,
                     app_version="9.9.9")
    assert res is not None
    assert res["id"] == msg_id
    return res


def _tool_ok(res: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in res, res
    result = res["result"]
    assert result["isError"] is False, result
    return result


def _tool_err(res: dict[str, Any]) -> str:
    assert "error" not in res, res
    result = res["result"]
    assert result["isError"] is True, result
    return result["content"][0]["text"]


@pytest.mark.parametrize("asked,answered", [
    ("2025-06-18", "2025-06-18"),
    ("2025-03-26", "2025-03-26"),
    ("2024-11-05", "2025-06-18"),   # HTTP+SSE era: not this transport
    ("2099-01-01", "2025-06-18"),   # unknown: offer our latest
])
def test_initialize_negotiates_the_protocol_version(asked, answered):
    res = mcp.handle(_rpc("initialize", {
        "protocolVersion": asked, "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"}}), _StubManager(),
        app_version="9.9.9")
    assert res is not None and res["id"] == 1
    result = res["result"]
    assert result["protocolVersion"] == answered
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"] == {"name": "whisper-transcriber-suite",
                                    "version": "9.9.9"}


@pytest.mark.parametrize("params", [None, {}, {"protocolVersion": 5}, [1]])
def test_initialize_without_a_version_string_is_invalid_params(params):
    res = mcp.handle(_rpc("initialize", params), _StubManager(),
                     app_version="1")
    assert res is not None and res["error"]["code"] == -32602


def test_tools_list_schemas():
    res = mcp.handle(_rpc("tools/list"), _StubManager(), app_version="1")
    assert res is not None
    tools = {t["name"]: t for t in res["result"]["tools"]}
    assert set(tools) == {"transcribe_url", "job_status", "get_result",
                          "list_jobs", "cancel_job"}
    for tool in tools.values():
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False
    tr = tools["transcribe_url"]["inputSchema"]
    assert tr["required"] == ["url"]
    assert tr["properties"]["formats"]["items"]["enum"] == supported_formats()
    gr = tools["get_result"]["inputSchema"]["properties"]
    assert "fmt" not in gr
    assert gr["format"]["default"] == "txt"
    assert gr["format"]["enum"] == supported_formats()


def test_tools_list_formats_follow_the_writer_registry(monkeypatch):
    monkeypatch.setattr(mcp, "supported_formats", lambda: ["txt", "zzz"])
    res = mcp.handle(_rpc("tools/list"), _StubManager(), app_version="1")
    assert res is not None
    tools = {t["name"]: t for t in res["result"]["tools"]}
    props = tools["transcribe_url"]["inputSchema"]["properties"]
    assert props["formats"]["items"]["enum"] == ["txt", "zzz"]


def test_unknown_tool_is_invalid_params():
    res = _call(_StubManager(), "rm_rf", {})
    assert res["error"]["code"] == -32602


def test_unknown_method_is_method_not_found():
    res = mcp.handle(_rpc("resources/list"), _StubManager(), app_version="1")
    assert res is not None and res["error"]["code"] == -32601


def test_ping_answers_an_empty_result():
    res = mcp.handle(_rpc("ping", msg_id="p"), _StubManager(), app_version="1")
    assert res == {"jsonrpc": "2.0", "id": "p", "result": {}}


@pytest.mark.parametrize("params", [
    {"name": "list_jobs", "arguments": "not-an-object"},
    {"arguments": {}},
    {"name": 5},
    "not-an-object",
])
def test_malformed_tools_call_is_invalid_params(params):
    res = mcp.handle(_rpc("tools/call", params), _StubManager(),
                     app_version="1")
    assert res is not None and res["error"]["code"] == -32602


def test_notifications_and_client_responses_get_no_reply():
    mgr = _StubManager()
    assert mcp.handle({"jsonrpc": "2.0",
                       "method": "notifications/initialized"},
                      mgr, app_version="1") is None
    # A notification never runs a tool (it has nobody to report to).
    assert mcp.handle({"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "transcribe_url",
                                  "arguments": {"url": "http://x/a"}}},
                      mgr, app_version="1") is None
    assert mgr.submitted == []
    # A JSON-RPC response sent by the client (e.g. to a ping).
    assert mcp.handle({"jsonrpc": "2.0", "id": 3, "result": {}},
                      mgr, app_version="1") is None


@pytest.mark.parametrize("message", [
    None, 5, "x", [], [_rpc("ping")],
    {"jsonrpc": "1.0", "id": 1, "method": "ping"},
    {"jsonrpc": "2.0", "id": 1, "method": 5},
    {"jsonrpc": "2.0", "id": None, "method": "ping"},
    {"jsonrpc": "2.0", "id": 1.5, "method": "ping"},
    {"jsonrpc": "2.0", "id": True, "method": "ping"},
])
def test_invalid_requests(message):
    res = mcp.handle(message, _StubManager(), app_version="1")
    assert res is not None
    assert res["error"]["code"] == -32600


# transcribe_url: the validation of POST /api/jobs, but strict.

def test_transcribe_url_submits_normalized_values():
    mgr = _StubManager()
    res = _call(mgr, "transcribe_url", {
        "url": " http://192.0.2.10/a.mp4 ", "language": "EN-us",
        "formats": ["SRT", "txt", "srt"], "clip_start": 10, "clip_end": 20.5})
    result = _tool_ok(res)
    assert result["structuredContent"] == {"job_id": "stub1"}
    assert json.loads(result["content"][0]["text"]) == {"job_id": "stub1"}
    assert mgr.submitted == [{
        "url": "http://192.0.2.10/a.mp4", "formats": ["srt", "txt"],
        "language": "en", "options": {}, "clip_start": 10.0,
        "clip_end": 20.5}]


def test_transcribe_url_defaults():
    mgr = _StubManager()
    _tool_ok(_call(mgr, "transcribe_url", {"url": "http://192.0.2.10/a",
                                           "language": None}))
    (sub,) = mgr.submitted
    assert sub["language"] == ""          # auto-detect, never "None"
    assert sub["formats"] == ["txt"]
    assert sub["clip_start"] is None and sub["clip_end"] is None


@pytest.mark.parametrize("arguments,needle", [
    ({}, "url"),
    ({"url": ""}, "url"),
    ({"url": 5}, "url"),
    ({"url": "http://x/a", "language": "xx"}, "language"),
    ({"url": "http://x/a", "language": 7}, "language"),
    ({"url": "http://x/a", "formats": ["../../evil"]}, "../../evil"),
    ({"url": "http://x/a", "formats": ["srt", "exe"]}, "exe"),
    ({"url": "http://x/a", "formats": []}, "formats"),
    ({"url": "http://x/a", "formats": "srt"}, "formats"),
    ({"url": "http://x/a", "formats": [3]}, "formats"),
    ({"url": "http://x/a", "clip_start": "abc"}, "clip_start"),
    ({"url": "http://x/a", "clip_start": True}, "clip_start"),
    ({"url": "http://x/a", "clip_start": -1}, "clip_start"),
    ({"url": "http://x/a", "clip_end": float("inf")}, "clip_end"),
    ({"url": "http://x/a", "clip_end": float("nan")}, "clip_end"),
    ({"url": "http://x/a", "clip_end": 0}, "clip_end"),
    ({"url": "http://x/a", "clip_start": 30, "clip_end": 10}, "clip_end"),
    ({"url": "http://x/a", "clip_start": 30, "clip_end": 30}, "clip_end"),
    ({"url": "http://x/a", "path": "C:/Windows/win.ini"}, "path"),
])
def test_transcribe_url_rejects_bad_input(arguments, needle):
    mgr = _StubManager()
    text = _tool_err(_call(mgr, "transcribe_url", arguments))
    assert needle in text
    assert mgr.submitted == []


def test_transcribe_url_applies_the_english_only_guard(monkeypatch):
    monkeypatch.setattr(httpd, "english_only_problem",
                        lambda lang: None if lang == "en" else "english only")
    mgr = _StubManager()
    assert _tool_err(_call(mgr, "transcribe_url", {
        "url": "http://x/a", "language": "fa"})) == "english only"
    assert mgr.submitted == []
    _tool_ok(_call(mgr, "transcribe_url", {"url": "http://x/a",
                                           "language": "en"}))


@pytest.mark.parametrize("exc", [ValueError("only http(s) URLs"),
                                 QueueFull("too many queued jobs")])
def test_transcribe_url_reports_manager_refusals(exc):
    mgr = _StubManager()
    mgr.raise_on_submit = exc
    assert str(exc) in _tool_err(_call(mgr, "transcribe_url",
                                       {"url": "file:///etc/passwd"}))


# job_status / list_jobs / get_result / cancel_job

def test_job_status_returns_json():
    mgr = _StubManager()
    mgr.submit_url("http://x/a", ["srt"])
    result = _tool_ok(_call(mgr, "job_status", {"job_id": "stub1"}))
    expected = mgr.jobs["stub1"].public_dict()
    assert result["structuredContent"] == expected
    assert json.loads(result["content"][0]["text"]) == expected
    for key in ("status", "progress", "error", "outputs"):
        assert key in expected


def test_job_status_unknown_and_bad_id():
    mgr = _StubManager()
    assert "nope" in _tool_err(_call(mgr, "job_status", {"job_id": "nope"}))
    assert "job_id" in _tool_err(_call(mgr, "job_status", {"job_id": 5}))
    assert "job_id" in _tool_err(_call(mgr, "job_status", {}))


def test_list_jobs_returns_json():
    mgr = _StubManager()
    mgr.submit_url("http://x/a", ["srt"])
    mgr.submit_url("http://x/b", ["txt"])
    result = _tool_ok(_call(mgr, "list_jobs", {}))
    expected = {"jobs": mgr.list()}
    assert result["structuredContent"] == expected
    assert json.loads(result["content"][0]["text"]) == expected
    # "arguments" may be omitted entirely.
    _tool_ok(_call(mgr, "list_jobs"))


def _finished(mgr: _StubManager, tmp_path, fmt: str, data: bytes) -> str:
    job_id = mgr.submit_url("http://x/a", [fmt])
    mgr.jobs[job_id].status = STATUS_FINISHED
    path = tmp_path / f"out.{fmt}"
    path.write_bytes(data)
    mgr.paths[(job_id, fmt)] = str(path)
    return job_id


def test_get_result_reads_text(tmp_path):
    mgr = _StubManager()
    job_id = _finished(mgr, tmp_path, "txt", "سلام mcp\n".encode("utf-8"))
    result = _tool_ok(_call(mgr, "get_result", {"job_id": job_id}))
    assert result["content"][0]["text"] == "سلام mcp\n"
    job_id = _finished(mgr, tmp_path, "srt", b"1\n")
    result = _tool_ok(_call(mgr, "get_result",
                            {"job_id": job_id, "format": "SRT"}))
    assert result["content"][0]["text"] == "1\n"


def test_get_result_refuses_the_old_fmt_argument(tmp_path):
    mgr = _StubManager()
    job_id = _finished(mgr, tmp_path, "srt", b"1\n")
    assert "fmt" in _tool_err(_call(mgr, "get_result",
                                    {"job_id": job_id, "fmt": "srt"}))


@pytest.mark.parametrize("fmt", sorted(BINARY_WRITERS))
def test_get_result_binary_names_the_http_route(tmp_path, fmt):
    mgr = _StubManager()
    job_id = _finished(mgr, tmp_path, fmt, b"PK\x03\x04")
    text = _tool_err(_call(mgr, "get_result",
                           {"job_id": job_id, "format": fmt}))
    assert f"/api/jobs/{job_id}/result?fmt={fmt}" in text


def test_get_result_errors(tmp_path):
    mgr = _StubManager()
    job_id = mgr.submit_url("http://x/a", ["txt"])
    assert "queued" in _tool_err(_call(mgr, "get_result", {"job_id": job_id}))
    mgr.jobs[job_id].status = STATUS_FINISHED
    assert "no 'txt' output" in _tool_err(
        _call(mgr, "get_result", {"job_id": job_id}))
    assert "format" in _tool_err(_call(mgr, "get_result",
                                       {"job_id": job_id, "format": "exe"}))
    assert "nope" in _tool_err(_call(mgr, "get_result", {"job_id": "nope"}))
    bad = _finished(mgr, tmp_path, "json", b"\xff\xfe\xff")
    assert "UTF-8" in _tool_err(_call(mgr, "get_result",
                                      {"job_id": bad, "format": "json"}))


def test_cancel_job():
    mgr = _StubManager()
    job_id = mgr.submit_url("http://x/a", ["srt"])
    result = _tool_ok(_call(mgr, "cancel_job", {"job_id": job_id}))
    assert result["structuredContent"] == {"cancelled": job_id}
    assert job_id in mgr.cancelled
    assert "no such active job" in _tool_err(
        _call(mgr, "cancel_job", {"job_id": job_id}))


def test_a_failing_manager_becomes_a_tool_error():
    class _Broken(_StubManager):
        def list(self):
            raise RuntimeError("disk on fire")
    assert "disk on fire" in _tool_err(_call(_Broken(), "list_jobs", {}))


# Invariants (hypothesis).

try:
    from hypothesis import given, settings
    import hypothesis.strategies as st
except ImportError:  # the property tests below need it; the rest do not
    given = None

if given is not None:
    _json = st.recursive(
        st.none() | st.booleans() | st.integers() | st.floats() | st.text(),
        lambda kids: st.lists(kids, max_size=4)
        | st.dictionaries(st.text(max_size=8), kids, max_size=4),
        max_leaves=12)
    _ids = st.integers() | st.text(max_size=8)
    _methods = (st.sampled_from(["initialize", "ping", "tools/list",
                                 "tools/call", "notifications/initialized"])
                | st.text(max_size=12))

    @settings(max_examples=200, derandomize=True, deadline=None,
              database=None)
    @given(_json)
    def test_handle_never_raises_for_any_json_value(message):
        res = mcp.handle(message, _StubManager(), app_version="1")
        if res is not None:
            assert res["jsonrpc"] == "2.0"
            assert ("result" in res) != ("error" in res)
            json.dumps(res)

    @settings(max_examples=200, derandomize=True, deadline=None,
              database=None)
    @given(_ids, _methods, _json, _json)
    def test_response_id_equals_request_id(msg_id, method, params, arguments):
        if isinstance(params, dict):
            params = dict(params, arguments=arguments)
        res = mcp.handle({"jsonrpc": "2.0", "id": msg_id, "method": method,
                          "params": params}, _StubManager(), app_version="1")
        assert res is not None
        assert res["id"] == msg_id

    @settings(max_examples=200, derandomize=True, deadline=None,
              database=None)
    @given(_ids, st.text(max_size=20))
    def test_unknown_methods_give_method_not_found(msg_id, method):
        if method in mcp.METHODS:
            return
        res = mcp.handle({"jsonrpc": "2.0", "id": msg_id, "method": method},
                         _StubManager(), app_version="1")
        assert res is not None and res["error"]["code"] == -32601
else:
    @pytest.mark.skip(reason="hypothesis is not installed")
    def test_mcp_property_tests_need_hypothesis():
        pass


# --- POST /mcp over a real socket ---------------------------------------------

def _download(url, dest):
    path = os.path.join(dest, "m.wav")
    with open(path, "wb") as f:
        f.write(b"x")
    return path


def _transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base = os.path.splitext(task.file_path)[0]
    written = []
    for fmt in task.output_formats or ["srt"]:
        out = f"{base}.{fmt}"
        with open(out, "wb") as f:
            f.write(f"dummy {fmt} ✓".encode("utf-8"))
        written.append(out)
    task.output_paths = written


class _Server:
    def __init__(self, tmp_path, token: str = "") -> None:
        self.tmp_path = tmp_path
        self.token = token

    def __enter__(self) -> "_Server":
        self.manager = JobManager(
            _transcribe, download_fn=_download,
            jobs_root=str(self.tmp_path / "server_jobs"),
            record_history=False)
        self.manager.start()
        self.server = JobHTTPServer(("127.0.0.1", 0), self.manager,
                                    token=self.token)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()

    def conn(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)


_JSON_HEADERS = {"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"}


def _post(conn: http.client.HTTPConnection, payload: Any,
          headers: dict[str, str] | None = None,
          raw: bytes | None = None) -> tuple[http.client.HTTPResponse, bytes]:
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    conn.request("POST", "/mcp", body=body,
                 headers=dict(_JSON_HEADERS, **(headers or {})))
    resp = conn.getresponse()
    return resp, resp.read()


def _post_rpc(conn, payload, headers=None) -> dict[str, Any]:
    resp, body = _post(conn, payload, headers)
    assert resp.status == 200, (resp.status, body)
    assert resp.getheader("Content-Type", "").startswith("application/json")
    assert resp.getheader("Mcp-Session-Id") is None
    return json.loads(body.decode("utf-8"))


def test_http_full_session_on_one_keep_alive_connection(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        init = _post_rpc(conn, _rpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"}}))
        assert init["result"]["protocolVersion"] == "2025-06-18"
        assert init["result"]["serverInfo"]["version"] == __version__

        # Notification: 202, an explicit empty body, connection still usable.
        resp, body = _post(conn, {"jsonrpc": "2.0",
                                  "method": "notifications/initialized"},
                           {"MCP-Protocol-Version": "2025-06-18"})
        assert resp.status == 202
        assert resp.getheader("Content-Length") == "0"
        assert body == b""
        assert not resp.will_close

        hdr = {"MCP-Protocol-Version": "2025-06-18"}
        tools = _post_rpc(conn, _rpc("tools/list", msg_id=2), hdr)
        assert len(tools["result"]["tools"]) == 5

        sub = _post_rpc(conn, _rpc("tools/call", {
            "name": "transcribe_url",
            "arguments": {"url": "http://192.0.2.10/a.mp4",
                          "formats": ["txt", "docx"]}}, 3), hdr)
        job_id = sub["result"]["structuredContent"]["job_id"]

        deadline = time.time() + 10
        status: dict[str, Any] = {}
        while time.time() < deadline:
            res = _post_rpc(conn, _rpc("tools/call", {
                "name": "job_status", "arguments": {"job_id": job_id}}, 4),
                hdr)
            status = res["result"]["structuredContent"]
            if status["status"] == STATUS_FINISHED:
                break
            time.sleep(0.05)
        assert status["status"] == STATUS_FINISHED, status

        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "get_result", "arguments": {"job_id": job_id}}, 5), hdr)
        assert res["result"]["content"][0]["text"] == "dummy txt ✓"
        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "get_result",
            "arguments": {"job_id": job_id, "format": "docx"}}, 6), hdr)
        assert res["result"]["isError"] is True
        assert (f"/api/jobs/{job_id}/result?fmt=docx"
                in res["result"]["content"][0]["text"])

        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "list_jobs", "arguments": {}}, 7), hdr)
        assert [j["job_id"] for j in
                res["result"]["structuredContent"]["jobs"]] == [job_id]
        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "cancel_job", "arguments": {"job_id": job_id}}, 8), hdr)
        assert res["result"]["isError"] is True     # already finished
        conn.close()


def test_http_cancel_job_of_a_queued_job(tmp_path):
    with _Server(tmp_path) as srv:
        srv.manager.stop()          # nothing runs: the job stays queued
        conn = srv.conn()
        sub = _post_rpc(conn, _rpc("tools/call", {
            "name": "transcribe_url",
            "arguments": {"url": "http://192.0.2.10/a.mp4"}}))
        job_id = sub["result"]["structuredContent"]["job_id"]
        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "cancel_job", "arguments": {"job_id": job_id}}, 2))
        assert res["result"]["structuredContent"] == {"cancelled": job_id}
        conn.close()


def test_http_bad_input_is_a_tool_error_not_a_job(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "transcribe_url",
            "arguments": {"url": "http://192.0.2.10/a",
                          "formats": ["../../evil"]}}))
        assert res["result"]["isError"] is True
        res = _post_rpc(conn, _rpc("tools/call", {
            "name": "transcribe_url",
            "arguments": {"url": "http://127.0.0.1:9/x"}}, 2))
        assert res["result"]["isError"] is True     # SSRF guard
        assert srv.manager.list() == []
        conn.close()


def test_http_text_plain_is_415(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"), {"Content-Type": "text/plain"})
        assert resp.status == 415
        conn.close()


def test_http_foreign_origin_is_403_without_and_with_a_token(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"), {"Origin": "http://evil.example"})
        assert resp.status == 403
    with _Server(tmp_path, token="dummy-credential-A") as srv:
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"),
                        {"Origin": "http://evil.example",
                         "X-Auth-Token": "dummy-credential-A"})
        assert resp.status == 403
        conn = srv.conn()
        own = f"http://127.0.0.1:{srv.port}"
        res = _post_rpc(conn, _rpc("ping"),
                        {"Origin": own, "X-Auth-Token": "dummy-credential-A"})
        assert res["result"] == {}
        conn.close()


def test_http_token_required_header_or_bearer(tmp_path):
    with _Server(tmp_path, token="dummy-credential-A") as srv:
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"))
        assert resp.status == 401
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"),
                        {"X-Auth-Token": "dummy-credential-B"})
        assert resp.status == 401
        conn = srv.conn()
        assert _post_rpc(conn, _rpc("ping"),
                         {"X-Auth-Token": "dummy-credential-A"})["id"] == 1
        assert _post_rpc(conn, _rpc("ping", msg_id=2), {
            "Authorization": "Bearer dummy-credential-A"})["id"] == 2
        conn.close()


def test_http_get_is_405(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        conn.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 405
        assert resp.getheader("Allow") == "POST"
        conn.close()


def test_http_unsupported_protocol_version_header_is_400(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        resp, _ = _post(conn, _rpc("ping"),
                        {"MCP-Protocol-Version": "1999-01-01"})
        assert resp.status == 400
        conn = srv.conn()
        assert _post_rpc(conn, _rpc("ping"),
                         {"MCP-Protocol-Version": "2025-03-26"})["id"] == 1
        conn.close()


def test_http_parse_error_and_invalid_request_are_400(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        resp, body = _post(conn, None, raw=b"{not json")
        assert resp.status == 400
        assert json.loads(body)["error"]["code"] == -32700
        resp, body = _post(conn, [_rpc("ping")])     # batches: not in 2025-06-18
        assert resp.status == 400
        assert json.loads(body)["error"]["code"] == -32600
        resp, body = _post(conn, None, raw=b"")
        assert resp.status == 400
        assert json.loads(body)["error"]["code"] == -32700
        conn.close()


def test_http_body_cap(tmp_path):
    with _Server(tmp_path) as srv:
        conn = srv.conn()
        resp, _ = _post(conn, None, raw=b" " * (1024 * 1024 + 1))
        assert resp.status == 413
        conn.close()
