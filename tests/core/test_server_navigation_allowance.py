"""Foreign top-level navigation must not lock out authenticated API clients."""
import http.client
import socket

import pytest

from tests.core.test_server_security import _RunningServer, _request, _SHARED


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
@pytest.mark.parametrize("purpose", [None, "prefetch;prerender"])
@pytest.mark.parametrize("destination", ["document", None])
@pytest.mark.parametrize("auth_header", ["X-Auth-Token", "Authorization"])
def test_foreign_document_guesses_cannot_lock_out_header_clients(tmp_path, site, purpose, destination, auth_header):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        headers = {"Sec-Fetch-Site": site, "Sec-Fetch-Mode": "navigate"}
        if destination is not None:
            headers["Sec-Fetch-Dest"] = destination
        if purpose:
            headers["Sec-Purpose"] = purpose
        statuses = [_request(srv, "GET", "/api/health?token=wrong-fixture-guess", headers=headers)[0]
                    for _ in range(8)]
        # Foreign navigation remains rate-limited in its own allowance.
        assert 401 in statuses and 429 in statuses
        client_headers = {**headers, auth_header: (_SHARED if auth_header == "X-Auth-Token"
                                                 else f"Bearer {_SHARED}")}
        assert _request(srv, "GET", "/api/health", headers=client_headers)[0] == 200
        assert srv.server.auth_throttle.peek("127.0.0.1") == 0
        assert srv.server.navigation_auth_throttle.peek("127.0.0.1") > 0


@pytest.mark.parametrize("destination", ["frame", "fencedframe", "webview", " IFRAME "])
def test_foreign_unknown_destinations_fail_closed_before_booking(tmp_path, destination):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        for _ in range(8):
            assert _request(srv, "GET", "/api/health?token=wrong-fixture-guess", headers={
                "Sec-Fetch-Site": " CROSS-SITE ", "Sec-Fetch-Mode": " NAVIGATE ",
                "Sec-Fetch-Dest": destination,
            })[0] == 403
        assert srv.server.auth_throttle.peek("127.0.0.1") == 0


@pytest.mark.parametrize("path", ["/api/jobs", "/v1/audio/transcriptions"])
@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_foreign_frame_post_refuses_closes_body_and_books_nothing(tmp_path, path, site):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            connection.request("POST", path+"?token=wrong-fixture-guess", body=b"untrusted body", headers={
                "Sec-Fetch-Site": site, "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe",
                "Content-Type": "text/plain",
            })
            response = connection.getresponse()
            assert response.status == 403
            assert response.will_close
            varied = {v.strip().lower() for v in response.getheader("Vary", "").split(",")}
            assert {"sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest"} <= varied
            response.read()
        finally:
            connection.close()
        assert srv.server.auth_throttle.peek("127.0.0.1") == 0
        assert srv.manager.list() == []


def test_document_normalization_and_shared_token_link_still_work(tmp_path):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        assert _request(srv, "GET", f"/api/health?token={_SHARED}", headers={
            "Sec-Fetch-Site": " SAME-SITE ", "Sec-Fetch-Mode": " NAVIGATE ",
            "Sec-Fetch-Dest": " document ",
        })[0] == 200


def test_auth_errors_vary_but_interim_continue_does_not(tmp_path):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        statuses = []
        try:
            for _ in range(8):
                connection.request("GET", "/api/health", headers={"X-Auth-Token": "wrong-fixture-guess"})
                response = connection.getresponse()
                statuses.append(response.status)
                varied = {v.strip().lower() for v in response.getheader("Vary", "").split(",")}
                assert {"sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest"} <= varied
                response.read()
        finally:
            connection.close()
        assert 401 in statuses and 429 in statuses
        with socket.create_connection(("127.0.0.1", srv.port), timeout=5) as sock:
            sock.sendall((f"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
                          "Content-Length: 0\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n").encode("ascii"))
            with sock.makefile("rb") as incoming:
                assert incoming.readline().startswith(b"HTTP/1.1 100 ")
                headers = []
                while line := incoming.readline():
                    if line == b"\r\n":
                        break
                    headers.append(line)
                assert not any(line.lower().startswith(b"vary:") for line in headers)


def test_navigation_allowance_retains_ipv6_subnet_cap_and_bounded_tables(tmp_path):
    from core.server.auth_throttle import AuthThrottle
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        navigation = srv.server.navigation_auth_throttle
        assert isinstance(navigation, AuthThrottle)
        # Distinct addresses in the same real /64 share a finite budget.
        for n in range(50):
            assert navigation.admit(f"2001:db8::{n+1:x}") == 0
        assert navigation.admit("2001:db8::ff") > 0
        assert srv.server.auth_throttle.admit("2001:db8::ff") == 0
        # Saturated navigation hosts use the existing bounded overflow limiter.
        srv.server.navigation_auth_throttle = AuthThrottle(free_attempts=0, max_hosts=1,
                                                         overflow_budget=1)
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        limiter = srv.server.navigation_auth_throttle
        assert limiter.admit("192.0.2.1") == 0
        assert _request(srv, "GET", "/api/health?token=wrong-fixture-guess", headers=headers)[0] == 401
        assert _request(srv, "GET", "/api/health?token=wrong-fixture-guess", headers=headers)[0] == 429
        assert len(limiter) == 1
        assert _request(srv, "GET", "/api/health", headers={"X-Auth-Token": _SHARED})[0] == 200
