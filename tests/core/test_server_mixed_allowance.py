"""Actual comparisons, rather than requests, must fit the two credential budgets."""
import json
import http.client
from urllib.parse import quote

import pytest

from core.server import httpd
from core.server.auth_throttle import AuthThrottle
from tests.core.test_server_security import _RunningServer, _request, _SHARED


@pytest.mark.parametrize('header', ['X-Auth-Token', 'Authorization'])
def test_mixed_and_encoded_candidates_cannot_multiply_comparison_budget(tmp_path, monkeypatch, header):
    compared = []
    original = httpd.hmac.compare_digest
    def observe(candidate, expected):
        if expected == _SHARED.encode():
            compared.append(candidate)
        return original(candidate, expected)
    monkeypatch.setattr(httpd.hmac, 'compare_digest', observe)
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        for number in range(6):
            value = f'header-{number}%41'
            if header == 'Authorization':
                value = 'Bearer ' + value
            _request(srv, 'GET', f'/api/health?token=query-{number}', headers={header: value})
        for number in range(6):
            _request(srv, 'GET', f'/api/health?token=remaining-{number}')
        assert len(compared) == len(set(compared)) == 12
        assert srv.server.auth_throttle.peek('127.0.0.1') > 0
        assert srv.server.navigation_auth_throttle.peek('127.0.0.1') > 0


@pytest.mark.parametrize('header', ['X-Auth-Token', 'Authorization'])
def test_correct_query_with_dummy_header_refunds_only_query_channel(tmp_path, header):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        value = 'dummy' if header == 'X-Auth-Token' else 'Bearer dummy'
        assert _request(srv, 'GET', '/api/health?token='+_SHARED, headers={header:value})[0] == 200
        assert len(srv.server.auth_throttle) == 1
        assert len(srv.server.navigation_auth_throttle) == 0


@pytest.mark.parametrize('header', ['X-Auth-Token', 'Authorization'])
def test_locked_dummy_header_cannot_hide_a_valid_query_candidate(tmp_path, header):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        dummy = 'dummy' if header == 'X-Auth-Token' else 'Bearer dummy'
        for _ in range(7):
            _request(srv, 'GET', '/api/health', headers={header:dummy})
        assert srv.server.auth_throttle.peek('127.0.0.1') > 0
        assert _request(srv, 'GET', '/api/health?token='+_SHARED, headers={header:dummy})[0] == 200
        assert srv.server.auth_throttle.peek('127.0.0.1') > 0


def test_empty_header_uses_query_and_correct_header_does_not_compare_query(tmp_path, monkeypatch):
    compared = []
    original = httpd.hmac.compare_digest
    def observe(candidate, expected):
        if expected == _SHARED.encode(): compared.append(candidate)
        return original(candidate, expected)
    monkeypatch.setattr(httpd.hmac, 'compare_digest', observe)
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        assert _request(srv, 'GET', '/api/health?token=wrong', headers={'X-Auth-Token':''})[0] == 401
        assert len(srv.server.auth_throttle) == 0
        assert len(srv.server.navigation_auth_throttle) == 1
        compared.clear()
        assert _request(srv, 'GET', '/api/health?token=unused', headers={'X-Auth-Token':_SHARED})[0] == 200
        assert compared == [_SHARED.encode()]
        assert len(srv.server.navigation_auth_throttle) == 1


def test_post_query_pressure_preserves_openai_header_authentication(tmp_path):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        for _ in range(7):
            _request(srv, 'POST', '/api/jobs?token=wrong', b'{}', {'Content-Type':'application/json'})
        status, body = _request(srv, 'POST', '/v1/audio/transcriptions', b'{}',
            {'Content-Type':'application/json', 'Authorization':'Bearer '+_SHARED})
        assert status == 400  # Auth passed; OpenAI's multipart validation rejects the JSON body.
        assert isinstance(json.loads(body)['error'], dict)


@pytest.mark.parametrize('secret,encode', [('50%41',False),('50%41',True),('رمز',True)])
def test_percent_literal_and_encoded_password_compatibility(tmp_path, secret, encode):
    with _RunningServer(tmp_path, token=secret) as srv:
        value = quote(secret, safe='') if encode else secret
        for _ in range(8):
            assert _request(srv, 'GET', '/api/health', headers={'X-Auth-Token':value})[0] == 200
        assert len(srv.server.auth_throttle) == 0


def test_invalid_percent_escape_is_compared_only_once(tmp_path, monkeypatch):
    compared = []
    original = httpd.hmac.compare_digest
    def observe(candidate, expected):
        if expected == _SHARED.encode(): compared.append(candidate)
        return original(candidate, expected)
    monkeypatch.setattr(httpd.hmac, 'compare_digest', observe)
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        assert _request(srv, 'GET', '/api/health', headers={'X-Auth-Token':'wrong%QZ'})[0] == 401
        assert compared == [b'wrong%QZ']


@pytest.mark.parametrize('pressured', ['header', 'query'])
def test_ipv6_subnet_pressure_leaves_other_credential_channel_usable(tmp_path, monkeypatch, pressured):
    # Real loopback HTTP with explicitly mapped documentation IPv6 identities.
    # This tests accounting and routing together, not native IPv6 transport.
    original = httpd.JobRequestHandler._authed
    def mapped(handler, route):
        handler.client_address = (handler.headers['X-Test-IP'], handler.client_address[1])
        return original(handler, route)
    monkeypatch.setattr(httpd.JobRequestHandler, '_authed', mapped)
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        for number in range(1, 51):
            headers = {'X-Test-IP':f'2001:db8:44:1::{number:x}'}
            path = '/api/health'
            if pressured == 'header': headers['X-Auth-Token'] = 'wrong'
            else: path += '?token=wrong'
            assert _request(srv, 'GET', path, headers=headers)[0] == 401
        headers = {'X-Test-IP':'2001:db8:44:1::ff'}
        path = '/api/health'
        if pressured == 'header': headers['X-Auth-Token'] = 'wrong'
        else: path += '?token=wrong'
        assert _request(srv, 'GET', path, headers=headers)[0] == 429
        if pressured == 'header': path += '?token='+_SHARED
        else: headers['X-Auth-Token'] = _SHARED
        assert _request(srv, 'GET', path, headers=headers)[0] == 200
        limiter = srv.server.auth_throttle if pressured == 'header' else srv.server.navigation_auth_throttle
        assert next(iter(limiter._subnets.values()))[0] == 50


def test_valid_session_cookie_survives_both_locked_channels_without_comparison(tmp_path, monkeypatch):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        connection = http.client.HTTPConnection('127.0.0.1', srv.port, timeout=5)
        try:
            connection.request('GET', '/api/health', headers={'X-Auth-Token':_SHARED})
            response = connection.getresponse()
            assert response.status == 200
            cookie = response.getheader('Set-Cookie').split(';', 1)[0]
            response.read()
        finally:
            connection.close()
        for _ in range(7):
            _request(srv, 'GET', '/api/health?token=wrong', headers={'X-Auth-Token':'wrong'})
        assert srv.server.auth_throttle.peek('127.0.0.1') > 0
        assert srv.server.navigation_auth_throttle.peek('127.0.0.1') > 0
        original = httpd.token_ok
        compared = []
        def observe(*args):
            compared.append(args)
            return original(*args)
        monkeypatch.setattr(httpd, 'token_ok', observe)
        counts = (len(srv.server.auth_throttle), len(srv.server.navigation_auth_throttle))
        assert _request(srv, 'GET', '/api/health', headers={'Cookie':cookie})[0] == 200
        assert compared == []
        assert (len(srv.server.auth_throttle), len(srv.server.navigation_auth_throttle)) == counts


def test_mixed_blocked_credentials_retry_at_first_channel_without_password_uses_longer_wait(tmp_path):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        srv.server.auth_throttle = AuthThrottle(base_delay=30, clock=lambda:100.0)
        srv.server.navigation_auth_throttle = AuthThrottle(base_delay=90, clock=lambda:100.0)
        for _ in range(6):
            _request(srv, 'GET', '/api/health?token=wrong', headers={'X-Auth-Token':'wrong'})
        for path, headers, expected in [('/api/health?token=wrong', {'X-Auth-Token':'wrong'},31),
                                         ('/api/health', {},91)]:
            connection = http.client.HTTPConnection('127.0.0.1', srv.port, timeout=5)
            try:
                connection.request('GET', path, headers=headers)
                response = connection.getresponse()
                assert response.status == 429
                assert int(response.getheader('Retry-After')) == expected
                response.read()
            finally:
                connection.close()
