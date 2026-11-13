"""Credential-channel routing survives IPv6 table pressure and trust refunds.

HTTP uses a real loopback socket; only the handler's accounting address is mapped
to a documentation IPv6 address. This is not a native routed-IPv6 network test.
"""
from copy import deepcopy

import pytest

from core.server.auth_throttle import AuthThrottle
from core.server.httpd import JobRequestHandler
from tests.core.test_server_security import _RunningServer, _request, _SHARED


@pytest.fixture
def ipv6_accounting(monkeypatch):
    original = JobRequestHandler._authed

    def mapped(handler, route):
        address = handler.client_address
        handler.client_address = ('2001:db8:1:2::5', address[1])
        try:
            return original(handler, route)
        finally:
            handler.client_address = address

    monkeypatch.setattr(JobRequestHandler, '_authed', mapped)


@pytest.mark.parametrize('pressured', ['query', 'header'])
@pytest.mark.parametrize('header', ['X-Auth-Token', 'Authorization'])
def test_full_subnet_and_overflow_tables_remain_channel_local(tmp_path, ipv6_accounting,
                                                            pressured, header):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        srv.server.auth_throttle = AuthThrottle(clock=lambda: 1000, max_subnets=1,
                                               overflow_budget=1)
        srv.server.navigation_auth_throttle = AuthThrottle(clock=lambda: 1000, max_subnets=1,
                                                          overflow_budget=1)
        query = srv.server.navigation_auth_throttle
        main = srv.server.auth_throttle
        busy = query if pressured == 'query' else main
        idle = main if pressured == 'query' else query
        assert busy.admit('2001:db8:1:1::1') == 0
        assert busy.admit('2001:db8:1:2::1') == 0
        assert busy.admit('2001:db8:1:2::2') > 0
        snapshot = deepcopy((dict(busy._subnets), list(busy._overflow), dict(busy._prefixes)))
        url = f'/api/health?token={_SHARED}' if pressured == 'header' else '/api/health'
        headers = {} if pressured == 'header' else {
            header: _SHARED if header == 'X-Auth-Token' else f'Bearer {_SHARED}'}
        assert _request(srv, 'GET', url, headers=headers)[0] == 200
        assert snapshot == (dict(busy._subnets), list(busy._overflow), dict(busy._prefixes))
        assert '2001:db8:1:2::5' in idle._trusted
        assert '2001:db8:1:2::5' not in busy._trusted
        blocked = '/api/health?token='+_SHARED if pressured == 'query' else '/api/health'
        blocked_headers = {} if pressured == 'query' else {'X-Auth-Token': _SHARED}
        assert _request(srv, 'GET', blocked, headers=blocked_headers)[0] == 429
