"""The small best-effort fetches and posts never follow an https -> http redirect.

Fake handlers stand in for the network; nothing here opens a socket.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message

import pytest

from core import config as cfg
from core import problem_report, stats, updates, verified_download as vd


class _FakeHttps(urllib.request.HTTPSHandler):
    """Answers every https request with a redirect to ``target``."""

    def __init__(self, target: str) -> None:
        super().__init__()
        self.target = target
        self.hits: list[str] = []

    def https_open(self, req):  # noqa: ANN001
        self.hits.append(req.full_url)
        headers = Message()
        headers["Location"] = self.target
        resp = urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
        resp.msg = "Found"  # type: ignore[attr-defined]
        return resp


class _FakeHttp(urllib.request.HTTPHandler):
    def __init__(self) -> None:
        super().__init__()
        self.hits: list[str] = []

    def http_open(self, req):  # noqa: ANN001
        self.hits.append(req.full_url)
        resp = urllib.response.addinfourl(io.BytesIO(b"{}"), Message(), req.full_url, 200)
        resp.msg = "OK"  # type: ignore[attr-defined]
        return resp


@pytest.fixture
def downgrade(monkeypatch):
    """Route the shared opener through fakes: https answers 302 -> http."""
    https = _FakeHttps("http://plain.example/next")
    http = _FakeHttp()
    opener = urllib.request.build_opener(vd._HttpsOnlyRedirects, https, http)
    monkeypatch.setattr(vd, "_opener", opener)
    return https, http


def test_https_to_http_redirect_is_refused(downgrade):
    https, http = downgrade
    with pytest.raises(urllib.error.HTTPError):
        vd.urlopen_https_only(urllib.request.Request("https://secure.example/x"), timeout=1)
    assert https.hits == ["https://secure.example/x"]
    assert http.hits == []


def test_http_to_http_redirect_is_still_followed(monkeypatch):
    class _Redir(urllib.request.HTTPHandler):
        def http_open(self, req):  # noqa: ANN001
            if req.full_url.endswith("/next"):
                resp = urllib.response.addinfourl(io.BytesIO(b"ok"), Message(), req.full_url, 200)
                resp.msg = "OK"  # type: ignore[attr-defined]
                return resp
            headers = Message()
            headers["Location"] = "http://plain.example/next"
            resp = urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
            resp.msg = "Found"  # type: ignore[attr-defined]
            return resp

    monkeypatch.setattr(vd, "_opener", urllib.request.build_opener(vd._HttpsOnlyRedirects, _Redir))
    with vd.urlopen_https_only(urllib.request.Request("http://plain.example/x"), timeout=1) as r:
        assert r.read() == b"ok"


def test_a_replaced_urlopen_is_honoured(monkeypatch):
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: seen.append(req) or "fake")
    assert vd.urlopen_https_only("req", timeout=1) == "fake"
    assert seen == ["req"]


def test_online_config_does_not_follow_a_downgrade(downgrade, tmp_path):
    https, http = downgrade
    out = cfg.fetch_online_config("https://secure.example/c.json", cache_path=tmp_path / "c.json")
    assert out == {}
    assert http.hits == []
    assert https.hits


def test_usage_stats_post_does_not_follow_a_downgrade(downgrade):
    https, http = downgrade
    stats._post("https://secure.example/s", {"model": "x"}, 1.0)
    assert https.hits and http.hits == []


def test_problem_report_does_not_follow_a_downgrade(downgrade, monkeypatch):
    https, http = downgrade
    monkeypatch.setattr(problem_report.offline, "is_offline", lambda: False)
    with pytest.raises(problem_report.ProblemReportError):
        problem_report.send({"stats_url": "https://secure.example/r"}, "something broke")
    assert https.hits and http.hits == []


def test_update_check_does_not_follow_a_downgrade(downgrade, monkeypatch):
    https, http = downgrade
    monkeypatch.setattr("core.offline.is_offline", lambda: False)
    assert updates.check_for_update(timeout=1) is None
    assert https.hits and http.hits == []


def test_update_response_is_capped(monkeypatch):
    big = b"x" * (updates.MAX_RELEASE_BYTES + 10)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self, n=-1):
            reads.append(n)
            return big if n < 0 else big[:n]

    reads: list[int] = []
    monkeypatch.setattr("core.offline.is_offline", lambda: False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert updates.check_for_update(timeout=1) is None
    assert reads and all(0 <= n <= updates.MAX_RELEASE_BYTES + 1 for n in reads)
    ok = json.dumps({"tag_name": "v0.0.1", "html_url": "https://github.com/o/r/releases/tag/v0.0.1"}).encode()

    class _Ok(_Resp):
        def read(self, n=-1):
            return ok

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Ok())
    assert updates.check_for_update(timeout=1) is not None
