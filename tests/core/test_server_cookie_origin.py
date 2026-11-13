"""Foreign Origins must authenticate the header they use to bypass the guard."""
import http.client
import threading

import pytest

from tests.core.test_server_security import _RunningServer, _request, _SHARED


def _session(srv):
    connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        connection.request("GET", "/api/health", headers={"X-Auth-Token": _SHARED})
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        cookie = response.getheader("Set-Cookie")
        assert cookie
        return cookie.split(";", 1)[0]
    finally:
        connection.close()


def _header(kind, value):
    return {kind: value if kind == "X-Auth-Token" else f"Bearer {value}"}


@pytest.mark.parametrize("kind", ["X-Auth-Token", "Authorization"])
@pytest.mark.parametrize("origin", ["http://foreign.example", "null"])
@pytest.mark.parametrize("credential", ["cookie", "query"])
def test_foreign_origin_cannot_substitute_cookie_or_query_for_header(
        tmp_path, monkeypatch, kind, origin, credential):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        called = []
        monkeypatch.setattr(srv.manager, "cancel", lambda job: called.append(job) or True)
        headers = {"Origin": origin, **_header(kind, "wrong-example-password")}
        path = "/api/jobs/fixture-job/cancel"
        if credential == "cookie":
            headers["Cookie"] = _session(srv)
        else:
            path += f"?token={_SHARED}"
        status, _ = _request(srv, "POST", path, body=b"", headers=headers)
        assert status == 401
        assert called == []


@pytest.mark.parametrize("kind", ["X-Auth-Token", "Authorization"])
@pytest.mark.parametrize("origin", ["http://foreign.example", "null"])
def test_foreign_origin_with_the_correct_header_still_reaches_action(
        tmp_path, monkeypatch, kind, origin):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        called = []
        monkeypatch.setattr(srv.manager, "cancel", lambda job: called.append(job) or True)
        status, _ = _request(srv, "POST", "/api/jobs/fixture-job/cancel", body=b"", headers={
            "Origin": origin, "Cookie": _session(srv), **_header(kind, _SHARED),
        })
        assert status == 200
        assert called == ["fixture-job"]


def test_foreign_cookie_request_cannot_cancel_a_running_upload(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        entered.set()
        assert release.wait(5), "test did not release the running upload"

    with _RunningServer(tmp_path, token=_SHARED, transcribe_fn=transcribe) as srv:
        try:
            session = _session(srv)
            job_id = srv.manager.submit_upload("fixture.wav", b"fixture", ["txt"])
            assert entered.wait(5)
            job = srv.manager.get(job_id)
            assert job is not None and not job.cancelled
            headers = {"Origin": "http://foreign.example", "Cookie": session,
                       "X-Auth-Token": "wrong-example-password"}
            status, _ = _request(srv, "POST", f"/api/jobs/{job_id}/cancel", b"", headers)
            assert status == 401
            assert not job.cancelled
            headers["X-Auth-Token"] = _SHARED
            status, _ = _request(srv, "POST", f"/api/jobs/{job_id}/cancel", b"", headers)
            assert status == 200
            assert job.cancelled
        finally:
            release.set()


@pytest.mark.parametrize("origin", ["same", "absent"])
@pytest.mark.parametrize("credential", ["cookie", "query"])
def test_own_origin_and_non_browser_credentials_keep_working(
        tmp_path, monkeypatch, origin, credential):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        called = []
        monkeypatch.setattr(srv.manager, "cancel", lambda job: called.append(job) or True)
        headers = {"X-Auth-Token": "wrong-example-password"}
        if origin == "same":
            headers["Origin"] = f"http://127.0.0.1:{srv.port}"
        path = "/api/jobs/fixture-job/cancel"
        if credential == "cookie":
            headers["Cookie"] = _session(srv)
        else:
            path += f"?token={_SHARED}"
        status, _ = _request(srv, "POST", path, body=b"", headers=headers)
        assert status == 200
        assert called == ["fixture-job"]
