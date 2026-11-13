"""URL-token isolation must not depend on optional browser Fetch Metadata."""
import http.client

import pytest

from tests.core.test_server_security import _RunningServer,_request,_SHARED


META={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
WRONG='wrong-test-only-token'


@pytest.mark.parametrize('header',['X-Auth-Token','Authorization'])
def test_query_guesses_without_metadata_leave_header_clients_usable(tmp_path,header):
    with _RunningServer(tmp_path,token=_SHARED) as srv:
        statuses=[_request(srv,'GET',f'/api/health?token={WRONG}')[0] for _ in range(8)]
        assert 429 in statuses
        value=_SHARED if header=='X-Auth-Token' else f'Bearer {_SHARED}'
        assert _request(srv,'GET','/api/health',headers={header:value})[0]==200
        assert srv.server.auth_throttle.peek('127.0.0.1')==0
        assert srv.server.navigation_auth_throttle.peek('127.0.0.1')>0


def test_spoofing_metadata_does_not_create_another_query_budget(tmp_path):
    with _RunningServer(tmp_path,token=_SHARED) as srv:
        statuses=[_request(srv,'GET',f'/api/health?token={WRONG}',headers=META if n%2 else {})[0]
                  for n in range(8)]
        assert statuses[:6]==[401]*6
        assert statuses[6:]==[429]*2
        assert len(srv.server.auth_throttle)==0


@pytest.mark.parametrize('metadata',[{},META])
def test_correct_url_token_refunds_only_its_query_allowance(tmp_path,metadata):
    with _RunningServer(tmp_path,token=_SHARED) as srv:
        # http.client has no cookie jar: each call must authenticate its token.
        for _ in range(3):
            assert _request(srv,'GET',f'/api/health?token={WRONG}',headers=metadata)[0]==401
        assert _request(srv,'GET',f'/api/health?token={_SHARED}',headers=metadata)[0]==200
        assert len(srv.server.navigation_auth_throttle)==0
        assert len(srv.server.auth_throttle)==0
        for _ in range(5):
            assert _request(srv,'GET',f'/api/health?token={WRONG}',headers=metadata)[0]==401
        assert len(srv.server.auth_throttle)==0


@pytest.mark.parametrize('metadata',[{},META])
def test_header_lockout_does_not_block_correct_url_token(tmp_path,metadata):
    with _RunningServer(tmp_path,token=_SHARED) as srv:
        for _ in range(8):
            _request(srv,'GET','/api/health',headers={'X-Auth-Token':WRONG})
        assert srv.server.auth_throttle.peek('127.0.0.1')>0
        assert _request(srv,'GET',f'/api/health?token={_SHARED}',headers=metadata)[0]==200
        assert srv.server.auth_throttle.peek('127.0.0.1')>0


def test_no_password_peeks_both_allowances_without_booking_and_returns_retry_after(tmp_path):
    with _RunningServer(tmp_path,token=_SHARED) as srv:
        for _ in range(8):
            _request(srv,'GET',f'/api/health?token={WRONG}',headers=META)
        before=len(srv.server.navigation_auth_throttle)
        connection=http.client.HTTPConnection('127.0.0.1',srv.port,timeout=5)
        try:
            connection.request('GET','/api/health')
            response=connection.getresponse()
            assert response.status==429
            assert int(response.getheader('Retry-After'))>0
            response.read()
        finally:
            connection.close()
        assert len(srv.server.navigation_auth_throttle)==before
        assert len(srv.server.auth_throttle)==0
        assert _request(srv,'GET','/api/health',headers={'X-Auth-Token':_SHARED})[0]==200
