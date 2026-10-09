"""macOS: the first "Update it" downloads yt-dlp's single-file build (core.yt_dlp_update).

The macOS app bundles a folder ("onedir") yt-dlp, which yt-dlp's own updater
refuses, so the first update fetches the official ``yt-dlp_macos`` from the
latest stable GitHub release, checks it against that release's SHA2-256SUMS and
only then makes it executable. Hermetic: the GitHub release is a fake that
answers inside ``HTTPSHandler.https_open``, so the real redirect handling, size
checks and hashing run; nothing touches the network. A "binary" is a small file
whose content is its version ("yt-dlp 2026.09.27"), as in test_yt_dlp_update.py.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import socket
import urllib.error
import urllib.request
import urllib.response
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import yt_dlp_update as ytu

_OLD = "2026.08.19"
_NEW = "2026.09.27"
_NEWER = "2026.10.30"

_LATEST = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
_TAGGED = "https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/"
_CDN = "https://release-assets.githubusercontent.com/github-production-release-asset/1/{name}"


def _binary(version: str) -> bytes:
    return f"yt-dlp {version}".encode()


def _write_binary(path: Path, version: str | None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"broken" if version is None else _binary(version))
    return path


def _version_of(path: str) -> tuple[int, ...]:
    try:
        text = Path(path).read_bytes().decode("utf-8", "replace")
    except OSError:
        return ()
    if not text.startswith("yt-dlp "):
        return ()
    return tuple(int(p) for p in text.split()[1].split("."))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeGithub:
    """Answers the release URLs the way GitHub does: 302 hops, then the file."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.routes: dict[str, dict] = {}
        self.requested: list[str] = []
        monkeypatch.setattr(
            urllib.request.HTTPSHandler, "https_open", lambda _handler, req: self._open(req),
        )

    # --- building a release ---------------------------------------------------
    def publish(
        self,
        version: str = _NEW,
        *,
        asset: bytes | None = None,
        sums: str | None = None,
        sums_hash: str | None = None,
        binary_hop: str | None = None,
        content_length: int | None = None,
        sums_status: int = 200,
    ) -> bytes:
        """A release ``version``. ``asset`` is what the download serves; the
        checksum file lists ``sums_hash`` (default: the hash of ``asset``)."""
        data = _binary(version) if asset is None else asset
        listed = sums_hash if sums_hash is not None else _sha(data)
        text = sums if sums is not None else (
            f"{listed}  yt-dlp_macos\n{'0' * 64}  yt-dlp_macos.zip\n{'1' * 64}  yt-dlp.exe\n"
        )
        tagged = _TAGGED.format(tag=version)
        self.routes[_LATEST + "SHA2-256SUMS"] = {"redirect": tagged + "SHA2-256SUMS"}
        self.routes[tagged + "SHA2-256SUMS"] = {"redirect": _CDN.format(name="sums")}
        self.routes[_CDN.format(name="sums")] = {"body": text.encode(), "status": sums_status}
        # The latest-URL for the binary: only the tag-pinned one is expected.
        self.routes[tagged + "yt-dlp_macos"] = {
            "redirect": binary_hop or _CDN.format(name="binary"),
        }
        self.routes[_CDN.format(name="binary")] = {"body": data, "content_length": content_length}
        return data

    # --- the transport -----------------------------------------------------------
    def _open(self, req: urllib.request.Request):
        url = req.full_url
        self.requested.append(url)
        route = self.routes.get(url)
        headers = http.client.HTTPMessage()
        if route is None:
            status, body, reason = 404, b"", "Not Found"
        elif "raises" in route:
            raise route["raises"]
        elif "redirect" in route:
            headers["Location"] = route["redirect"]
            status, body, reason = 302, b"", "Found"
        else:
            body = route["body"]
            status = route.get("status", 200)
            reason = "OK" if status == 200 else "Error"
            length = route.get("content_length")
            headers["Content-Length"] = str(len(body) if length is None else length)
        resp = urllib.response.addinfourl(io.BytesIO(body), headers, url, status)
        resp.msg = reason  # type: ignore[attr-defined]
        return resp


@pytest.fixture(autouse=True)
def _clean_gate():
    ytu._running.clear()
    ytu._updating = False
    yield
    ytu._running.clear()
    ytu._updating = False


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """The macOS app: a folder yt-dlp bundled, the cache elsewhere, macOS 13.7."""
    dist = tmp_path / "app" / "bin" / "yt-dlp_dist"
    exe = _write_binary(dist / "yt-dlp_macos", _OLD)
    (dist / "_internal").mkdir()
    monkeypatch.setattr(ytu, "bundled_binary", lambda _n: str(exe))
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu, "_is_macos", lambda: True)
    monkeypatch.setattr(ytu, "macos_version", lambda: (13, 7))
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    return SimpleNamespace(bundled=exe, cache=tmp_path / "cache", tmp=tmp_path)


@pytest.fixture
def github(monkeypatch):
    return FakeGithub(monkeypatch)


def _no_updater(*_a, **_k):  # a bootstrap must not start yt-dlp's own updater
    raise AssertionError("--update-to must not run for a fresh download")


def _update(**kwargs):
    kwargs.setdefault("version_of", _version_of)
    kwargs.setdefault("run", _no_updater)
    return ytu.update_cached_copy(**kwargs)


def _cache_files(mac) -> list[str]:
    folder = mac.cache / "tools" / "yt-dlp"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --------------------------------------------------------------- the good path

def test_a_good_download_is_installed_and_used(mac, github, monkeypatch):
    chmods: list[tuple[str, int]] = []
    original = Path.chmod
    monkeypatch.setattr(
        Path, "chmod", lambda self, mode, **k: (chmods.append((self.name, mode)), original(self, mode, **k))[1],
    )
    bundled_before = mac.bundled.read_bytes()
    github.publish(_NEW)

    result = _update()

    assert result.status == "updated" and result.completed is True
    assert result.after == (2026, 9, 27) and result.before == (2026, 8, 19)
    target = ytu.cached_path()
    assert target.read_bytes() == _binary(_NEW)
    assert ytu.resolve_yt_dlp_path() == str(target)  # newer than the bundled one
    assert mac.bundled.read_bytes() == bundled_before  # the bundled copy is never touched
    assert _cache_files(mac) == sorted(["state.json", target.name])  # no partial file left behind
    assert [mode for name, mode in chmods if name.endswith(".download")] == [0o755]
    if os.name != "nt":
        assert os.access(target, os.X_OK)
    state = ytu.load_state()
    assert state["cached"]["version"] == [2026, 9, 27]
    assert state["bootstrap"]["tag"] == _NEW
    assert state["bootstrap"]["sha256"] == _sha(_binary(_NEW))
    # The binary came from the release the checksum file named, not "latest".
    assert _TAGGED.format(tag=_NEW) + "yt-dlp_macos" in github.requested
    assert _LATEST + "yt-dlp_macos" not in github.requested


def test_a_release_no_newer_than_the_bundled_copy_reports_already_newest(mac, github):
    github.publish(_OLD)
    result = _update()
    assert result.status == "current" and result.completed is True
    assert "already the newest version (2026.08.19)" in ytu.result_text(result)
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)  # the app's own copy stays in use


def test_work_offline_raised_inside_the_download_is_reported_as_is(mac, github):
    from core import offline

    github.publish(_NEW)
    github.routes[_LATEST + "SHA2-256SUMS"] = {"raises": offline.OfflineModeError(offline.message("x"))}
    result = _update()
    assert result.status == "failed"
    assert result.message == offline.message("x")
    assert _cache_files(mac) == []


def test_the_bootstrap_record_survives_a_refresh(mac, github):
    github.publish(_NEW)
    _update()
    ytu.refresh_state(version_of=_version_of)
    assert ytu.load_state()["bootstrap"]["tag"] == _NEW


def test_after_the_download_the_normal_updater_updates_the_copy(mac, github):
    github.publish(_NEW)
    _update()
    calls: list[list[str]] = []

    def _updater(cmd, **_kwargs):
        calls.append(list(cmd))
        target = Path(cmd[0])
        target.write_bytes(_binary(_NEWER))
        os.utime(target, ns=(target.stat().st_mtime_ns + 2_000_000_000,) * 2)
        return SimpleNamespace(returncode=0, stdout="Updated yt-dlp", stderr="")

    result = _update(run=_updater)
    assert result.status == "updated" and result.after == (2026, 10, 30)
    assert calls == [[str(ytu.cached_path()), "--update-to", "stable"]]
    assert github.requested.count(_TAGGED.format(tag=_NEW) + "yt-dlp_macos") == 1  # no second download


def test_a_broken_copy_is_downloaded_again(mac, github):
    _write_binary(ytu.cached_path(), None)
    github.publish(_NEW)
    result = _update()
    assert result.status == "updated"
    assert ytu.cached_path().read_bytes() == _binary(_NEW)


def test_the_bar_can_offer_it_and_the_bundled_one_is_still_the_fallback(mac, github):
    assert ytu.can_self_update() is True
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)  # nothing downloaded yet


# ----------------------------------------------------------- fail closed: bytes

def test_a_checksum_mismatch_installs_nothing(mac, github, monkeypatch):
    chmods: list[str] = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode, **k: chmods.append(self.name))
    asked: list[str] = []
    github.publish(_NEW, sums_hash="f" * 64)

    result = _update(version_of=lambda p: asked.append(p) or _version_of(p))

    assert result.status == "failed"
    assert "checksum" in result.message
    assert "not installed" in result.message
    assert not ytu.cached_path().exists()
    assert _cache_files(mac) == []  # the partial file is removed too
    assert chmods == []  # never made executable
    assert [p for p in asked if not p.endswith("yt-dlp_macos")] == []  # never started
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)
    assert ytu.result_text(result).startswith("Could not update the video downloader:")


def test_a_truncated_download_installs_nothing(mac, github):
    data = _binary(_NEW)
    github.publish(_NEW, asset=data[:-5], sums_hash=_sha(data), content_length=len(data))
    result = _update()
    assert result.status == "failed"
    assert "cut short" in result.message
    assert result.completed is False  # a network problem: try again
    assert _cache_files(mac) == []


def test_a_truncated_download_without_a_length_fails_the_checksum(mac, github):
    data = _binary(_NEW)
    github.publish(_NEW, asset=data[:-5], sums_hash=_sha(data))
    result = _update()
    assert result.status == "failed"
    assert _cache_files(mac) == []


def test_an_empty_download_installs_nothing(mac, github):
    github.publish(_NEW, asset=b"", sums_hash=_sha(_binary(_NEW)))
    result = _update()
    assert result.status == "failed"
    assert _cache_files(mac) == []


def test_a_release_without_a_checksum_line_installs_nothing(mac, github):
    github.publish(_NEW, sums=f"{'a' * 64}  yt-dlp_macos.zip\n{'b' * 64}  yt-dlp_macos_legacy\n")
    result = _update()
    assert result.status == "failed"
    assert "no checksum" in result.message
    assert not any(u.endswith("/yt-dlp_macos") for u in github.requested)  # nothing fetched unchecked
    assert _cache_files(mac) == []


def test_an_oversized_download_is_stopped(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "BOOTSTRAP_MAX_BYTES", 8)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed"
    assert "larger than expected" in result.message
    assert _cache_files(mac) == []


def test_a_slow_download_times_out(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "BOOTSTRAP_TIMEOUT_S", -1)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed"
    assert "timed out" in result.message
    assert result.completed is False
    assert _cache_files(mac) == []


def test_a_verified_file_that_does_not_start_is_removed_and_remembered(mac, github, monkeypatch):
    broken = b"verified but not a program"
    github.publish(_NEW, asset=broken)
    result = _update()
    assert result.status == "failed" and result.completed is True
    assert "does not start on this Mac" in result.message
    assert _cache_files(mac) == ["state.json"]
    # The same macOS is not asked to download it again; another version is.
    assert ytu.can_self_update() is False
    assert _update().status == "unsupported"
    assert github.requested.count(_TAGGED.format(tag=_NEW) + "yt-dlp_macos") == 1
    monkeypatch.setattr(ytu, "macos_version", lambda: (14, 0))
    assert ytu.can_self_update() is True


# ---------------------------------------------------- fail closed: where from

@pytest.mark.parametrize("hop", [
    "https://evil.example/yt-dlp_macos",
    "https://github.com.evil.example/yt-dlp/yt-dlp/releases/download/x/yt-dlp_macos",
    "https://evilgithub.com/yt-dlp_macos",
    "http://github.com/yt-dlp/yt-dlp/releases/download/x/yt-dlp_macos",
    "https://user@release-assets.githubusercontent.com/x",
    "https://github.com:8443/yt-dlp_macos",
    "ftp://github.com/yt-dlp_macos",
])
def test_a_redirect_to_a_foreign_place_is_refused(mac, github, hop):
    github.publish(_NEW, binary_hop=hop)
    result = _update()
    assert result.status == "failed"
    assert "address" in result.message
    assert hop not in github.requested  # never even requested
    assert _cache_files(mac) == []


def test_a_redirect_of_the_checksum_file_to_a_foreign_host_is_refused(mac, github):
    github.publish(_NEW)
    github.routes[_TAGGED.format(tag=_NEW) + "SHA2-256SUMS"] = {"redirect": "https://evil.example/sums"}
    result = _update()
    assert result.status == "failed"
    assert "https://evil.example/sums" not in github.requested
    assert not any("yt-dlp_macos" in u for u in github.requested)


@pytest.mark.parametrize("host", [
    "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
])
def test_the_known_github_hosts_are_followed(host):
    ytu._check_release_url(f"https://{host}/x")


@pytest.mark.parametrize("url", [
    "https://evil.example/x", "http://github.com/x", "https://api.github.com/x",
    "https://github.com.evil.example/x", "https://GITHUB.COM.evil.example/x",
    "https://github.com:444/x", "https://a@github.com/x", "file:///etc/passwd", "",
])
def test_other_addresses_are_not(url):
    with pytest.raises(ytu._BootstrapFailed):
        ytu._check_release_url(url)


def test_the_uppercase_host_name_is_the_same_host():
    ytu._check_release_url("https://GitHub.com/x")


# ------------------------------------------------------------ fail closed: net

def test_work_offline_downloads_nothing(mac, github, monkeypatch):
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: True)
    github.publish(_NEW)
    result = _update()
    assert result.status == "offline" and result.completed is False
    assert github.requested == []
    assert "Offline mode is on" in ytu.result_text(result)
    assert _cache_files(mac) == []


def test_no_internet_says_so_in_plain_words(mac, github):
    github.publish(_NEW)
    github.routes[_LATEST + "SHA2-256SUMS"] = {
        "raises": urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")),
    }
    result = _update()
    assert result.status == "failed" and result.completed is False
    assert "internet connection" in result.message
    assert "The app keeps using the version it has." in ytu.result_text(result)


def test_a_github_error_names_the_code(mac, github):
    github.publish(_NEW, sums_status=503)
    result = _update()
    assert result.status == "failed"
    assert "503" in result.message
    assert result.completed is False


def test_a_timeout_while_connecting_is_reported(mac, github):
    github.publish(_NEW)
    github.routes[_LATEST + "SHA2-256SUMS"] = {"raises": socket.timeout("timed out")}
    result = _update()
    assert result.status == "failed" and "timed out" in result.message


def test_a_certificate_problem_is_reported(mac, github):
    import ssl

    github.publish(_NEW)
    github.routes[_LATEST + "SHA2-256SUMS"] = {
        "raises": urllib.error.URLError(ssl.SSLCertVerificationError("bad certificate")),
    }
    result = _update()
    assert result.status == "failed" and "secure connection" in result.message


def test_an_update_refuses_during_a_running_download(mac, github):
    github.publish(_NEW)
    ytu.begin_download("running")
    try:
        result = _update()
    finally:
        ytu.end_download("running")
    assert result.status == "busy"
    assert github.requested == []


def test_the_gate_is_released_after_a_failed_download(mac, github):
    github.publish(_NEW, sums_hash="0" * 64)
    assert _update().status == "failed"
    assert ytu._updating is False


# ------------------------------------------------------------------- the floor

@pytest.mark.parametrize("version,expected", [
    ((10, 14), False), ((10, 15), True), ((11, 0), True), ((10, 16), True), ((13, 7), True), ((), True),
])
def test_the_macos_floor_decides_whether_it_is_offered(mac, monkeypatch, version, expected):
    monkeypatch.setattr(ytu, "macos_version", lambda: version)
    assert ytu.can_self_update() is expected


def test_a_mac_below_the_floor_keeps_the_old_behaviour(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "macos_version", lambda: (10, 14))
    github.publish(_NEW)
    result = _update()
    assert result.status == "unsupported"
    assert github.requested == []
    assert result.message == ytu._UNSUPPORTED_TEXT


def test_the_version_comes_from_the_operating_system(monkeypatch):
    for text, expected in (("13.7.8", (13, 7)), ("10.15.7", (10, 15)), ("", ()), ("garbage", ())):
        monkeypatch.setattr(ytu.platform, "mac_ver", lambda t=text: (t, ("", "", ""), ""))
        assert ytu.macos_version() == expected, text


# ------------------------------------------------- Windows and Linux unchanged

@pytest.mark.parametrize("system", ["windows", "linux"])
def test_other_systems_never_download_an_executable(tmp_path, monkeypatch, github, system):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    github.publish(_NEW)
    # A folder build or a bare name: no copy to make and no download to do.
    dist = tmp_path / "bin" / "yt-dlp_dist"
    exe = _write_binary(dist / "yt-dlp", _OLD)
    (dist / "_internal").mkdir()
    for bundled in (str(exe), "yt-dlp"):
        monkeypatch.setattr(ytu, "bundled_binary", lambda _n, b=bundled: b)
        assert ytu.can_self_update() is False
        assert _update().status == "unsupported"
    assert github.requested == []


def test_a_single_file_build_still_updates_by_copying_not_downloading(tmp_path, monkeypatch, github):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    exe = _write_binary(tmp_path / "install" / "yt-dlp.exe", _OLD)
    monkeypatch.setattr(ytu, "bundled_binary", lambda _n: str(exe))

    def _updater(cmd, **_k):
        target = Path(cmd[0])
        target.write_bytes(_binary(_NEW))
        os.utime(target, ns=(target.stat().st_mtime_ns + 2_000_000_000,) * 2)
        return SimpleNamespace(returncode=0, stdout="Updated", stderr="")

    assert ytu.can_self_update() is True
    result = _update(run=_updater)
    assert result.status == "updated"
    assert github.requested == []


def test_the_mac_download_size_is_the_universal_build(monkeypatch):
    monkeypatch.setattr(ytu, "_is_macos", lambda: True)
    assert ytu.download_mb() == ytu.DOWNLOAD_MB_MACOS == 37
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    assert ytu.download_mb() == ytu.DOWNLOAD_MB == 18


# ------------------------------------------------------------ checksum parsing

def test_the_checksum_line_is_matched_by_exact_file_name():
    good = "a" * 64
    text = (
        f"{'b' * 64}  yt-dlp_macos.zip\n"
        f"{'c' * 64}  yt-dlp_macos_legacy\n"
        f"{good} *yt-dlp_macos\n"
        f"{'d' * 64}  yt-dlp\n"
    )
    assert ytu._expected_hash(text, "yt-dlp_macos") == good
    assert ytu._expected_hash(text.upper().replace("YT-DLP_MACOS", "yt-dlp_macos"), "yt-dlp_macos") == good


@pytest.mark.parametrize("text", [
    "", "not a checksum file", f"{'a' * 63}  yt-dlp_macos\n", f"{'g' * 64}  yt-dlp_macos\n",
    f"{'a' * 64}  other/yt-dlp_macos\n",
])
def test_a_missing_or_malformed_line_is_an_error(text):
    with pytest.raises(ytu._BootstrapFailed):
        ytu._expected_hash(text, "yt-dlp_macos")


def test_the_state_file_stays_valid_json(mac, github):
    github.publish(_NEW)
    _update()
    json.loads((mac.cache / "tools" / "yt-dlp" / "state.json").read_text(encoding="utf-8"))


def test_the_fallback_hint_names_the_app_download_page():
    from core.updates import RELEASES_PAGE_URL

    assert "install the newest version of this app" in ytu.OUTDATED_HINT
    assert RELEASES_PAGE_URL in ytu.OUTDATED_HINT
