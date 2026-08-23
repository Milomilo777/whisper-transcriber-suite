"""Hermetic, pure-logic tests for core.updates.

NO Tk root, NO live network. The one place that would hit the network
(``check_for_update``) is exercised by monkeypatching ``urlopen`` so the
test proves the SILENT-failure contract without any socket.
"""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from core import updates
from core.updates import (
    GITHUB_OWNER,
    GITHUB_REPO,
    RELEASES_PAGE_URL,
    UpdateInfo,
    check_for_update,
    is_newer,
    latest_release_api_url,
    parse_release_json,
)


# --- is_newer --------------------------------------------------------------

@pytest.mark.parametrize(
    "remote,local,expected",
    [
        ("1.3.10", "1.3.7", True),     # 10 > 7 numerically (not string)
        ("v1.3.10", "1.3.7", True),    # leading-v tolerance on remote
        ("1.3.10", "v1.3.7", True),    # leading-v tolerance on local
        ("1.3.7", "1.3.7", False),     # equal → not newer
        ("v1.3.7", "v1.3.7", False),   # equal with both v-prefixed
        ("1.3.6", "1.3.7", False),     # older → not newer
        ("1.4", "1.3.10", True),       # short remote, zero-padded compare
        ("1.4", "1.4.0", False),       # 1.4 == 1.4.0
        ("2.0.0", "1.9.9", True),      # major bump
    ],
)
def test_is_newer(remote: str, local: str, expected: bool) -> None:
    assert is_newer(remote, local) is expected


def test_is_newer_does_not_crash_on_odd_tags() -> None:
    # Pre-release / nightly / garbage tags must never raise.
    for remote in ("v1.4.0-rc1", "nightly", "", "v", "...", "v1.x.y", "release-2"):
        result = is_newer(remote, "1.3.7")
        assert isinstance(result, bool)
    # A pre-release of a newer numeric prefix still reads as newer.
    assert is_newer("v1.4.0-rc1", "1.3.7") is True
    # A pre-release of the SAME numeric prefix is not "newer".
    assert is_newer("v1.3.7-rc1", "1.3.7") is False
    # Unparseable remote is conservatively "not newer".
    assert is_newer("garbage", "1.3.7") is False


# --- latest_release_api_url ------------------------------------------------

def test_latest_release_api_url() -> None:
    url = latest_release_api_url("Milomilo777", "whisper-transcriber-suite")
    assert url == (
        "https://api.github.com/repos/Milomilo777/"
        "whisper-transcriber-suite/releases/latest"
    )


def test_default_repo_constants_feed_the_url() -> None:
    # The module constants are the single source of truth and must
    # produce the api.github.com endpoint the check actually uses.
    assert GITHUB_OWNER == "Milomilo777"
    assert GITHUB_REPO == "whisper-transcriber-suite"
    assert latest_release_api_url(GITHUB_OWNER, GITHUB_REPO).startswith(
        "https://api.github.com/repos/Milomilo777/"
    )
    assert RELEASES_PAGE_URL.endswith("/releases/latest")


# --- parse_release_json ----------------------------------------------------

_CANNED_JSON = """
{
  "url": "https://api.github.com/repos/o/r/releases/123",
  "html_url": "https://github.com/o/r/releases/tag/v1.4.0",
  "tag_name": "v1.4.0",
  "name": "v1.4.0",
  "draft": false,
  "prerelease": false
}
"""


def test_parse_release_json_happy_path() -> None:
    tag, html_url = parse_release_json(_CANNED_JSON)
    assert tag == "v1.4.0"
    assert html_url == "https://github.com/o/r/releases/tag/v1.4.0"


def test_parse_release_json_missing_html_url_falls_back() -> None:
    tag, html_url = parse_release_json('{"tag_name": "v1.4.0"}')
    assert tag == "v1.4.0"
    assert html_url == RELEASES_PAGE_URL


def test_parse_release_json_malformed_raises_valueerror() -> None:
    for bad in ("not json at all", "{", "", "[1, 2, 3]", '{"name": "no tag"}'):
        with pytest.raises(ValueError):
            parse_release_json(bad)


# --- check_for_update (silent failure) -------------------------------------

def test_check_for_update_silent_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> object:
        raise urllib.error.URLError("simulated offline")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert check_for_update(timeout=1) is None


def test_check_for_update_silent_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # A private repo (or no published release) returns HTTP 404; this
    # must be swallowed to None, never raised or surfaced.
    def _http_404(*_a: object, **_k: object) -> object:
        raise urllib.error.HTTPError(
            url="https://api.github.com/x", code=404, msg="Not Found",
            hdrs=None, fp=None,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(urllib.request, "urlopen", _http_404)
    assert check_for_update(timeout=1) is None


def test_check_for_update_silent_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"this is not json"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert check_for_update(timeout=1) is None


def test_check_for_update_parses_and_compares(monkeypatch: pytest.MonkeyPatch) -> None:
    # Feed a canned newer-than-current release and prove the dataclass
    # is populated + is_newer reflects the comparison against __version__.
    body = (
        b'{"tag_name": "v999.0.0", '
        b'"html_url": "https://github.com/o/r/releases/tag/v999.0.0"}'
    )

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    info = check_for_update(timeout=1)
    assert isinstance(info, UpdateInfo)
    assert info.latest_tag == "v999.0.0"
    assert info.html_url == "https://github.com/o/r/releases/tag/v999.0.0"
    assert info.is_newer is True
