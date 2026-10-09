"""macOS: "Update it" installs yt-dlp's official folder (onedir) build (core.yt_dlp_update).

The macOS app bundles a folder yt-dlp, which yt-dlp's own updater refuses. The
single-file build unpacks itself on every run (about 25 s per call), so instead
the app installs the release's ``yt-dlp_macos.zip`` into a versioned folder in
the user cache: checksum list first (its redirect names the tag), the zip of
that tag, SHA-256 and length checked, a safe extraction, ``--version`` on the
result, and only then the switch in ``state.json``. Hermetic: the GitHub release
is a fake that answers inside ``HTTPSHandler.https_open``, so the real redirect
handling, size checks, hashing and extraction run; nothing touches the network.
A "binary" is a small file whose content is its version ("yt-dlp 2026.09.27"),
as in test_yt_dlp_update.py.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import socket
import stat
import urllib.error
import urllib.request
import urllib.response
import zipfile
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
_ZIP = "yt-dlp_macos.zip"

_FILE = 0o100000
_DIR = 0o040000
_LINK = 0o120000
_posix_only = pytest.mark.skipif(os.name == "nt", reason="needs POSIX permission bits")


def _binary(version: str) -> bytes:
    return f"yt-dlp {version}".encode()


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


def _entries(version: str | None = _NEW) -> list[tuple[str, bytes, int]]:
    """What the release zip holds: the program beside an ``_internal`` folder."""
    exe = b"broken" if version is None else _binary(version)
    return [
        ("yt-dlp_macos", exe, _FILE | 0o755),
        ("_internal/", b"", _DIR | 0o755),
        ("_internal/lib.dylib", b"library", _FILE | 0o755),
        ("_internal/data.txt", b"data", _FILE | 0o644),
    ]


def _zip_bytes(entries: list[tuple[str, bytes, int]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 27, 0, 0, 0))
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


class _Trickle(io.BytesIO):
    """An answer that delivers one byte per call, as a stalled connection does.
    ``read(n)`` would wait for n bytes, so using it is a failure."""

    def read(self, *_a, **_k):  # type: ignore[override]
        raise AssertionError("read(n) keeps waiting for n bytes; the code must use read1")

    def read1(self, _size=-1):  # type: ignore[override]
        return super().read(1)


class FakeGithub:
    """Answers the release URLs the way GitHub does: 302 hops, then the file."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.routes: dict[str, dict] = {}
        self.requested: list[str] = []
        monkeypatch.setattr(
            urllib.request.HTTPSHandler, "https_open", lambda _handler, req: self._open(req),
        )

    def publish(
        self,
        version: str = _NEW,
        *,
        entries: list[tuple[str, bytes, int]] | None = None,
        asset: bytes | None = None,
        sums: str | None = None,
        sums_hash: str | None = None,
        zip_hop: str | None = None,
        content_length: int | None = None,
        sums_status: int = 200,
    ) -> bytes:
        """A release ``version``. ``asset`` (default: a zip of ``entries``) is
        what the download serves; the checksum file lists ``sums_hash``
        (default: the hash of ``asset``)."""
        data = asset if asset is not None else _zip_bytes(entries or _entries(version))
        listed = sums_hash if sums_hash is not None else _sha(data)
        text = sums if sums is not None else (
            f"{'2' * 64}  yt-dlp_macos\n{listed}  {_ZIP}\n{'1' * 64}  yt-dlp.exe\n"
        )
        tagged = _TAGGED.format(tag=version)
        self.routes[_LATEST + "SHA2-256SUMS"] = {"redirect": tagged + "SHA2-256SUMS"}
        self.routes[tagged + "SHA2-256SUMS"] = {"redirect": _CDN.format(name="sums")}
        self.routes[_CDN.format(name="sums")] = {"body": text.encode(), "status": sums_status}
        self.routes[tagged + _ZIP] = {"redirect": zip_hop or _CDN.format(name="zip")}
        self.routes[_CDN.format(name="zip")] = {"body": data, "content_length": content_length}
        return data

    def zip_requests(self) -> list[str]:
        return [u for u in self.requested if u.endswith("/" + _ZIP)]

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
        fp = _Trickle(body) if route and route.get("trickle") else io.BytesIO(body)
        resp = urllib.response.addinfourl(fp, headers, url, status)
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
    dist.mkdir(parents=True)
    exe = dist / "yt-dlp_macos"
    exe.write_bytes(_binary(_OLD))
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


def _no_updater(*_a, **_k):  # yt-dlp's own updater refuses folder builds: never used on macOS
    raise AssertionError("--update-to must not run on macOS")


def _update(**kwargs):
    kwargs.setdefault("version_of", _version_of)
    kwargs.setdefault("run", _no_updater)
    return ytu.update_cached_copy(**kwargs)


def _tools(mac) -> Path:
    return mac.cache / "tools" / "yt-dlp"


def _cache_files(mac) -> list[str]:
    folder = _tools(mac)
    names = sorted(p.name for p in folder.iterdir()) if folder.exists() else []
    return [n for n in names if n != ytu.LOCK_NAME]  # the lock file is always there


def _installed(mac) -> list[str]:
    return [n for n in _cache_files(mac) if n.startswith("onedir-")]


def _active_exe(mac) -> Path:
    rec = ytu.load_state()["onedir"]
    return _tools(mac) / rec["dir"] / "yt-dlp_macos"


# ----------------------------------------------------------------- the good path

def test_a_good_zip_is_installed_and_used(mac, github):
    bundled_before = mac.bundled.read_bytes()
    github.publish(_NEW)

    result = _update()

    assert result.status == "updated" and result.completed is True
    assert result.after == (2026, 9, 27) and result.before == (2026, 8, 19)
    folders = _installed(mac)
    assert len(folders) == 1 and folders[0].startswith(f"onedir-{_NEW}")
    assert _cache_files(mac) == sorted(["state.json", folders[0]])  # no part folder, no .download
    exe = _tools(mac) / folders[0] / "yt-dlp_macos"
    assert exe.read_bytes() == _binary(_NEW)
    assert (_tools(mac) / folders[0] / "_internal" / "lib.dylib").read_bytes() == b"library"
    assert ytu.cached_path() == exe
    assert ytu.resolve_yt_dlp_path() == str(exe)  # newer than the bundled one
    assert mac.bundled.read_bytes() == bundled_before  # the bundled copy is never touched
    state = ytu.load_state()
    assert state["cached"]["version"] == [2026, 9, 27]
    assert state["onedir"]["tag"] == _NEW and state["onedir"]["dir"] == folders[0]
    assert state["onedir"]["sha256"] == _sha(_zip_bytes(_entries(_NEW)))
    # The zip came from the release the checksum file named, not "latest".
    assert github.zip_requests() == [_TAGGED.format(tag=_NEW) + _ZIP]


@_posix_only
def test_the_program_and_libraries_keep_their_execute_bits(mac, github):
    github.publish(_NEW)
    _update()
    root = _tools(mac) / ytu.load_state()["onedir"]["dir"]
    assert stat.S_IMODE((root / "yt-dlp_macos").stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "_internal" / "lib.dylib").stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "_internal" / "data.txt").stat().st_mode) == 0o644
    assert stat.S_IMODE((root / "_internal").stat().st_mode) == 0o755


def test_without_an_install_the_bundled_one_is_used_and_the_offer_exists(mac):
    assert ytu.can_self_update() is True
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)
    assert ytu.cached_path().parent == _tools(mac)  # nothing installed: the plain default name


def test_a_newer_bundled_copy_wins_over_the_install(mac, github):
    github.publish(_NEW)
    _update()
    mac.bundled.write_bytes(_binary(_NEWER))
    os.utime(mac.bundled, ns=(mac.bundled.stat().st_mtime_ns + 2_000_000_000,) * 2)
    ytu.refresh_state(version_of=_version_of)
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)


def test_the_onedir_record_survives_a_refresh(mac, github):
    github.publish(_NEW)
    _update()
    ytu.refresh_state(version_of=_version_of)
    assert ytu.load_state()["onedir"]["tag"] == _NEW
    assert ytu.resolve_yt_dlp_path() == str(_active_exe(mac))


# ------------------------------------------------------------- update = reinstall

def test_a_newer_release_replaces_the_old_folder_after_a_grace_period(mac, github, monkeypatch):
    github.publish(_NEW)
    _update()
    old = _installed(mac)[0]
    github.publish(_NEWER)

    result = _update()

    assert result.status == "updated" and result.after == (2026, 10, 30)
    assert result.before == (2026, 9, 27)
    new = ytu.load_state()["onedir"]["dir"]
    assert new != old and new.startswith(f"onedir-{_NEWER}")
    assert _active_exe(mac).read_bytes() == _binary(_NEWER)
    assert ytu.resolve_yt_dlp_path() == str(_active_exe(mac))
    # A lookup that started from the old folder keeps its files for a while.
    assert sorted(_installed(mac)) == sorted([old, new])
    assert [r["dir"] for r in ytu.load_state()["onedir_retired"]] == [old]

    later = ytu.now_utc() + ytu.RETIRED_GRACE + ytu.timedelta(minutes=1)
    monkeypatch.setattr(ytu, "now_utc", lambda: later)
    ytu.refresh_state_if_stale(version_of=_version_of)  # what the app does a few seconds after it starts

    assert _installed(mac) == [new]
    assert "onedir_retired" not in ytu.load_state()
    assert _cache_files(mac) == sorted(["state.json", new])
    assert ytu.resolve_yt_dlp_path() == str(_active_exe(mac))


def test_the_old_folder_survives_until_its_grace_has_passed(mac, github, monkeypatch):
    github.publish(_NEW)
    _update()
    old = _installed(mac)[0]
    github.publish(_NEWER)
    _update()
    just_before = ytu.now_utc() + ytu.RETIRED_GRACE - ytu.timedelta(minutes=1)
    monkeypatch.setattr(ytu, "now_utc", lambda: just_before)
    ytu.prune_old_installs()
    assert old in _installed(mac)


def test_a_release_that_is_not_newer_downloads_nothing(mac, github):
    github.publish(_NEW)
    _update()
    folder = _installed(mac)
    github.requested.clear()

    result = _update()

    assert result.status == "current" and result.completed is True
    assert "already the newest version (2026.09.27)" in ytu.result_text(result)
    assert github.zip_requests() == []  # only the checksum list was read
    assert _installed(mac) == folder


def test_a_release_no_newer_than_the_bundled_copy_downloads_nothing(mac, github):
    github.publish(_OLD)
    result = _update()
    assert result.status == "current" and result.completed is True
    assert "already the newest version (2026.08.19)" in ytu.result_text(result)
    assert github.zip_requests() == []
    assert _installed(mac) == []
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)


def test_an_older_release_than_the_install_changes_nothing(mac, github):
    github.publish(_NEWER)
    _update()
    github.publish(_NEW)  # e.g. the newest release was withdrawn
    result = _update()
    assert result.status == "current" and result.after == (2026, 10, 30)
    assert _active_exe(mac).read_bytes() == _binary(_NEWER)


def test_a_broken_install_is_replaced(mac, github):
    github.publish(_NEW)
    _update()
    broken = _active_exe(mac)
    broken.write_bytes(b"damaged")
    os.utime(broken, ns=(broken.stat().st_mtime_ns + 2_000_000_000,) * 2)
    ytu.refresh_state(version_of=_version_of)
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)

    result = _update()

    assert result.status == "updated"
    assert _active_exe(mac) != broken  # a new folder; the damaged one is retired
    assert _active_exe(mac).read_bytes() == _binary(_NEW)
    assert ytu.resolve_yt_dlp_path() == str(_active_exe(mac))


def _stray(mac, name: str, *, age_days: float) -> Path:
    folder = _tools(mac) / name
    folder.mkdir(parents=True)
    (folder / "yt-dlp_macos").write_bytes(b"x")
    then = folder.stat().st_mtime - age_days * 86400
    os.utime(folder, (then, then))
    return folder


def test_old_leftovers_of_an_interrupted_install_are_cleaned_up(mac, github):
    _stray(mac, "onedir-2026.01.01-dead", age_days=2)
    _stray(mac, "onedir-2026.01.01-half.part", age_days=2)
    github.publish(_NEW)
    _update()
    assert _cache_files(mac) == sorted(["state.json", *_installed(mac)])
    assert len(_installed(mac)) == 1


def test_a_fresh_stray_folder_is_left_alone(mac, github):
    # E.g. a folder no record names yet, or one made a minute ago: not ours to remove.
    _stray(mac, "onedir-2026.01.01-fresh", age_days=0)
    github.publish(_NEW)
    _update()
    assert "onedir-2026.01.01-fresh" in _installed(mac)


def test_yt_dlps_own_updater_is_never_used_on_a_mac(mac, github):
    github.publish(_NEW)
    _update()
    github.publish(_NEWER)
    _update()  # _no_updater raises if --update-to is started


# ------------------------------------------------------- the switch is atomic

def test_a_new_build_that_does_not_start_leaves_the_old_one_in_use(mac, github):
    github.publish(_NEW)
    _update()
    old_folder, old_state = _installed(mac), ytu.load_state()["onedir"]
    github.publish(_NEWER, entries=_entries(None))  # verified, but not a program

    result = _update()

    assert result.status == "failed" and "does not start on this Mac" in result.message
    assert _installed(mac) == old_folder
    assert ytu.load_state()["onedir"] == old_state
    assert ytu.resolve_yt_dlp_path() == str(_active_exe(mac))
    assert _active_exe(mac).read_bytes() == _binary(_NEW)
    assert ytu.can_self_update() is True  # a working install keeps the updates available


def test_a_failed_switch_removes_the_new_folder_and_keeps_the_old_one(mac, github, monkeypatch):
    github.publish(_NEW)
    _update()
    old_folder, old_state = _installed(mac), ytu.load_state()["onedir"]
    github.publish(_NEWER)
    real_save = ytu._save_state

    def _save(state):
        if state.get("onedir", {}).get("tag") == _NEWER:
            raise OSError("disk full")
        real_save(state)

    monkeypatch.setattr(ytu, "_save_state", _save)
    result = _update()

    assert result.status == "failed" and "disk full" in result.message
    assert _installed(mac) == old_folder  # the new folder is gone, the old one is not
    assert ytu.load_state()["onedir"] == old_state
    assert _active_exe(mac).read_bytes() == _binary(_NEW)


def test_the_old_folder_stays_until_the_state_points_at_the_new_one(mac, github, monkeypatch):
    github.publish(_NEW)
    _update()
    old_folder = _installed(mac)
    github.publish(_NEWER)
    seen: dict[str, object] = {}
    real_save = ytu._save_state

    def _save(state):
        if state.get("onedir", {}).get("tag") == _NEWER:
            seen["folders_at_switch"] = _installed(mac)
        real_save(state)

    monkeypatch.setattr(ytu, "_save_state", _save)
    _update()
    assert set(old_folder) <= set(seen["folders_at_switch"])  # type: ignore[arg-type]
    assert len(seen["folders_at_switch"]) == 2  # type: ignore[arg-type]
    assert len(_installed(mac)) == 2  # still: the old one is only retired


# ----------------------------------------------------------- fail closed: bytes

def test_a_checksum_mismatch_installs_nothing(mac, github):
    asked: list[str] = []
    github.publish(_NEW, sums_hash="f" * 64)

    result = _update(version_of=lambda p: asked.append(p) or _version_of(p))

    assert result.status == "failed" and result.completed is True
    assert "checksum" in result.message and "not installed" in result.message
    assert _cache_files(mac) == []  # nothing was extracted, no partial file is left
    assert [p for p in asked if str(mac.cache) in p] == []  # nothing from the zip was started
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)
    assert ytu.result_text(result).startswith("Could not update the video downloader:")


def test_a_truncated_download_installs_nothing(mac, github):
    data = github.publish(_NEW)
    github.publish(_NEW, asset=data[:-50], sums_hash=_sha(data), content_length=len(data))
    result = _update()
    assert result.status == "failed" and "cut short" in result.message
    assert result.completed is False  # a network problem: try again
    assert _cache_files(mac) == []


def test_a_truncated_download_without_a_length_fails_the_checksum(mac, github):
    data = github.publish(_NEW)
    github.publish(_NEW, asset=data[:-50], sums_hash=_sha(data))
    assert _update().status == "failed"
    assert _cache_files(mac) == []


def test_an_empty_download_installs_nothing(mac, github):
    github.publish(_NEW, asset=b"", sums_hash=_sha(b"x"))
    assert _update().status == "failed"
    assert _cache_files(mac) == []


def test_a_release_without_a_checksum_for_the_zip_installs_nothing(mac, github):
    # The single-file build and the legacy name are not the folder build.
    github.publish(_NEW, sums=f"{'a' * 64}  yt-dlp_macos\n{'b' * 64}  yt-dlp_macos_legacy\n")
    result = _update()
    assert result.status == "failed" and "no checksum" in result.message
    assert github.zip_requests() == []
    assert _cache_files(mac) == []


def test_an_oversized_download_is_stopped(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "BOOTSTRAP_MAX_BYTES", 8)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed" and "larger than expected" in result.message
    assert _cache_files(mac) == []


def test_a_slow_download_times_out(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "BOOTSTRAP_TIMEOUT_S", -1)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed" and "timed out" in result.message
    assert result.completed is False
    assert _cache_files(mac) == []


def test_a_verified_file_that_is_not_a_zip_installs_nothing(mac, github):
    junk = b"this is not an archive at all"
    github.publish(_NEW, asset=junk)
    result = _update()
    assert result.status == "failed" and "not a valid archive" in result.message
    assert _cache_files(mac) == []


def test_a_corrupt_member_installs_nothing(mac, github):
    data = bytearray(_zip_bytes(_entries(_NEW)))
    data[len(data) // 3] ^= 0xFF  # damage the stored data; the checksum below is of the damaged file
    github.publish(_NEW, asset=bytes(data))
    result = _update()
    assert result.status == "failed"
    assert _cache_files(mac) == []


# ------------------------------------------------------ fail closed: the archive

@pytest.mark.parametrize("name", [
    "../evil.txt", "_internal/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "..\\evil.txt",
    "_internal/..\\evil.txt", "a/./../../evil.txt",
])
def test_a_path_that_leaves_the_folder_is_refused(mac, github, name):
    github.publish(_NEW, entries=[*_entries(_NEW), (name, b"pwned", _FILE | 0o644)])
    result = _update()
    assert result.status == "failed" and "unsafe" in result.message
    assert result.completed is True
    assert _cache_files(mac) == []  # nothing at all was written
    assert not (mac.cache / "evil.txt").exists() and not (mac.tmp / "evil.txt").exists()
    assert not Path("/abs/evil.txt").exists()


def test_a_link_pointing_outside_is_refused(mac, github, monkeypatch):
    made: list[tuple[str, str]] = []
    monkeypatch.setattr(os, "symlink", lambda target, path, *a, **k: made.append((target, path)))
    for target in ("../../../outside", "/etc/passwd", "../../x", "_internal/../../../x"):
        github.publish(_NEW, entries=[*_entries(_NEW), ("_internal/lnk", target.encode(), _LINK | 0o777)])
        result = _update()
        assert result.status == "failed" and "unsafe" in result.message, target
        assert _cache_files(mac) == [], target
    assert made == []


def test_a_link_inside_the_folder_is_allowed(mac, github, monkeypatch):
    made: list[tuple[str, str]] = []
    monkeypatch.setattr(os, "symlink", lambda target, path, *a, **k: made.append((target, Path(path).name)))
    github.publish(_NEW, entries=[*_entries(_NEW), ("_internal/Current", b"lib.dylib", _LINK | 0o755)])
    assert _update().status == "updated"
    assert made == [("lib.dylib", "Current")]


def test_a_file_written_through_a_link_is_refused(mac, github, monkeypatch):
    monkeypatch.setattr(os, "symlink", lambda *a, **k: None)
    github.publish(_NEW, entries=[
        *_entries(_NEW), ("_internal/lnk", b".", _LINK | 0o777), ("_internal/lnk/x.txt", b"x", _FILE | 0o644),
    ])
    result = _update()
    assert result.status == "failed" and "unsafe" in result.message
    assert _cache_files(mac) == []


@pytest.mark.parametrize("mode", [0o020644, 0o060644, 0o010644, 0o140644])  # char, block, fifo, socket
def test_device_files_and_other_special_entries_are_refused(mac, github, mode):
    github.publish(_NEW, entries=[*_entries(_NEW), ("_internal/dev", b"", mode)])
    result = _update()
    assert result.status == "failed" and "unsafe" in result.message
    assert _cache_files(mac) == []


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_a_repeated_name_is_refused(mac, github):
    github.publish(_NEW, entries=[*_entries(_NEW), ("_internal/data.txt", b"second", _FILE | 0o644)])
    result = _update()
    assert result.status == "failed" and "unsafe" in result.message
    assert _cache_files(mac) == []


def test_too_many_files_are_refused(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "ONEDIR_MAX_FILES", 3)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed" and "more files than expected" in result.message
    assert _cache_files(mac) == []


def test_an_archive_that_unpacks_too_large_is_refused(mac, github, monkeypatch):
    monkeypatch.setattr(ytu, "ONEDIR_MAX_UNPACKED_BYTES", 10)
    github.publish(_NEW)
    result = _update()
    assert result.status == "failed" and "unpacks larger than expected" in result.message
    assert _cache_files(mac) == []


@pytest.mark.parametrize("entries", [
    [("_internal/lib.dylib", b"library", _FILE | 0o755)],
    [("sub/yt-dlp_macos", _binary(_NEW), _FILE | 0o755)],
    [("yt-dlp_macos/", b"", _DIR | 0o755), ("_internal/lib.dylib", b"library", _FILE | 0o755)],
])
def test_a_zip_without_the_program_installs_nothing(mac, github, entries):
    github.publish(_NEW, entries=entries)
    result = _update()
    assert result.status == "failed" and "does not contain the program" in result.message
    assert _cache_files(mac) == []


def test_a_program_that_is_a_link_is_refused(mac, github, monkeypatch):
    monkeypatch.setattr(os, "symlink", lambda *a, **k: None)
    github.publish(_NEW, entries=[("yt-dlp_macos", b"_internal/lib.dylib", _LINK | 0o755),
                                  ("_internal/lib.dylib", b"library", _FILE | 0o755)])
    result = _update()
    assert result.status == "failed" and "does not contain the program" in result.message
    assert _cache_files(mac) == []


def test_a_failure_halfway_through_the_extraction_leaves_nothing(mac, github, monkeypatch):
    github.publish(_NEW)
    real_copy = ytu.shutil.copyfileobj
    calls: list[int] = []

    def _flaky(src, dst, *a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("No space left on device")
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(ytu.shutil, "copyfileobj", _flaky)
    result = _update()
    assert len(calls) == 2  # one file was already written when it failed
    assert result.status == "failed" and "No space left" in result.message
    assert _cache_files(mac) == []  # no part folder, no zip
    assert ytu.resolve_yt_dlp_path() == str(mac.bundled)


def test_extraction_asks_for_the_archives_modes_without_special_bits(tmp_path, monkeypatch):
    asked: dict[str, int] = {}
    real = os.chmod
    monkeypatch.setattr(ytu.os, "chmod", lambda p, m, *a, **k: (asked.__setitem__(Path(p).name, m), real(p, m, *a, **k))[1])
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(_zip_bytes([
        *_entries(_NEW), ("_internal/suid", b"x", _FILE | 0o4755), ("_internal/odd", b"x", _FILE | 0o000),
    ]))
    dest = tmp_path / "out"
    dest.mkdir()
    ytu._extract_onedir(zip_path, dest)
    assert asked["yt-dlp_macos"] == 0o755 and asked["lib.dylib"] == 0o755 and asked["data.txt"] == 0o644
    assert asked["suid"] == 0o755  # the setuid bit is not asked for
    assert asked["odd"] == 0o644  # an archive without a mode: a readable file
    assert asked["_internal"] == 0o755


@_posix_only
def test_extraction_keeps_the_modes_of_the_archive_and_drops_special_bits(tmp_path):
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(_zip_bytes([
        *_entries(_NEW), ("_internal/suid", b"x", _FILE | 0o4755), ("_internal/odd", b"x", _FILE | 0o000),
    ]))
    dest = tmp_path / "out"
    dest.mkdir()
    ytu._extract_onedir(zip_path, dest)
    assert stat.S_IMODE((dest / "yt-dlp_macos").stat().st_mode) == 0o755
    assert stat.S_IMODE((dest / "_internal" / "suid").stat().st_mode) == 0o755  # setuid dropped
    assert stat.S_IMODE((dest / "_internal" / "odd").stat().st_mode) == 0o644  # no mode: readable file


# ----------------------------------------------- fail closed: the start check

def test_a_verified_build_that_does_not_start_is_removed_and_remembered(mac, github, monkeypatch):
    github.publish(_NEW, entries=_entries(None))
    result = _update()
    assert result.status == "failed" and result.completed is True
    assert "does not start on this Mac" in result.message
    assert ytu.load_state()["bootstrap_refused"]["macos"] == [13, 7]
    assert _cache_files(mac) == ["state.json"]
    # The same macOS is not asked to download it again; another version is.
    assert ytu.can_self_update() is False
    assert _update().status == "unsupported"
    assert github.zip_requests() == [_TAGGED.format(tag=_NEW) + _ZIP]
    monkeypatch.setattr(ytu, "macos_version", lambda: (14, 0))
    assert ytu.can_self_update() is True


def test_the_refusal_expires(mac, github, monkeypatch):
    from datetime import timedelta

    github.publish(_NEW, entries=_entries(None))
    _update()
    assert ytu.can_self_update() is False
    later = ytu.datetime.now(ytu.timezone.utc) + timedelta(days=ytu.REFUSAL_DAYS + 1)
    monkeypatch.setattr(ytu, "now_utc", lambda: later)
    assert ytu.can_self_update() is True


@pytest.mark.parametrize("until", ["", "garbage", "2999-01-01T00:00:00", None])
def test_an_unreadable_or_offsetless_refusal_time_does_not_block(mac, until):
    ytu._save_state({"bootstrap_refused": {"macos": [13, 7], "until": until}})
    assert ytu.can_self_update() is True


def test_a_slow_first_start_is_asked_again_before_giving_up(mac, github):
    github.publish(_NEW)
    answers: list[str] = []

    def _slow_first_start(path: str) -> tuple[int, ...]:
        if "part" in path and not answers:
            answers.append(path)
            return ()  # the first start timed out
        return _version_of(path)

    result = _update(version_of=_slow_first_start)
    assert result.status == "updated"
    assert ytu.can_self_update() is True
    assert "bootstrap_refused" not in ytu.load_state()


# ---------------------------------------------------- fail closed: where from

@pytest.mark.parametrize("hop", [
    "https://evil.example/yt-dlp_macos.zip",
    "https://github.com.evil.example/yt-dlp/yt-dlp/releases/download/x/yt-dlp_macos.zip",
    "https://evilgithub.com/yt-dlp_macos.zip",
    "http://github.com/yt-dlp/yt-dlp/releases/download/x/yt-dlp_macos.zip",
    "https://user@release-assets.githubusercontent.com/x",
    "https://github.com:8443/yt-dlp_macos.zip",
    "ftp://github.com/yt-dlp_macos.zip",
])
def test_a_redirect_to_a_foreign_place_is_refused(mac, github, hop):
    github.publish(_NEW, zip_hop=hop)
    result = _update()
    assert result.status == "failed" and "address" in result.message
    assert hop not in github.requested  # never even requested
    assert _cache_files(mac) == []


def test_a_redirect_of_the_checksum_file_to_a_foreign_host_is_refused(mac, github):
    github.publish(_NEW)
    github.routes[_TAGGED.format(tag=_NEW) + "SHA2-256SUMS"] = {"redirect": "https://evil.example/sums"}
    result = _update()
    assert result.status == "failed"
    assert "https://evil.example/sums" not in github.requested
    assert github.zip_requests() == []


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


def test_work_offline_raised_inside_the_download_is_reported_as_is(mac, github):
    from core import offline

    github.publish(_NEW)
    github.routes[_LATEST + "SHA2-256SUMS"] = {"raises": offline.OfflineModeError(offline.message("x"))}
    result = _update()
    assert result.status == "failed" and result.message == offline.message("x")
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
    assert result.status == "failed" and "503" in result.message
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
    assert result.status == "unsupported" and result.message == ytu._UNSUPPORTED_TEXT
    assert github.requested == []


def test_the_version_comes_from_the_operating_system(monkeypatch):
    for text, expected in (("13.7.8", (13, 7)), ("10.15.7", (10, 15)), ("", ()), ("garbage", ())):
        monkeypatch.setattr(ytu.platform, "mac_ver", lambda t=text: (t, ("", "", ""), ""))
        assert ytu.macos_version() == expected, text


# ------------------------------------------------- Windows and Linux unchanged

@pytest.mark.parametrize("system", ["windows", "linux"])
def test_other_systems_never_download_an_archive(tmp_path, monkeypatch, github, system):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    github.publish(_NEW)
    # A folder build or a bare name: no copy to make and no download to do.
    dist = tmp_path / "bin" / "yt-dlp_dist"
    dist.mkdir(parents=True)
    exe = dist / "yt-dlp"
    exe.write_bytes(_binary(_OLD))
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
    exe = tmp_path / "install" / "yt-dlp.exe"
    exe.parent.mkdir()
    exe.write_bytes(_binary(_OLD))
    monkeypatch.setattr(ytu, "bundled_binary", lambda _n: str(exe))

    def _updater(cmd, **_k):
        target = Path(cmd[0])
        target.write_bytes(_binary(_NEW))
        os.utime(target, ns=(target.stat().st_mtime_ns + 2_000_000_000,) * 2)
        return SimpleNamespace(returncode=0, stdout="Updated", stderr="")

    assert ytu.can_self_update() is True
    assert ytu.cached_path() == tmp_path / "cache" / "tools" / "yt-dlp" / ytu._exe_name()
    result = _update(run=_updater)
    assert result.status == "updated"
    assert github.requested == []


def test_the_wait_for_an_update_is_longer_only_on_a_mac(monkeypatch):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    assert ytu.wait_bound() == ytu.WAIT_FOR_UPDATE_S == ytu.UPDATE_TIMEOUT_S + 2 * 120 + 60
    monkeypatch.setattr(ytu, "_is_macos", lambda: True)
    assert ytu.wait_bound() > ytu.BOOTSTRAP_TIMEOUT_S


def test_the_mac_download_size_is_the_zips(monkeypatch):
    monkeypatch.setattr(ytu, "_is_macos", lambda: True)
    assert ytu.download_mb() == ytu.DOWNLOAD_MB_MACOS == 54  # 53,923,637 bytes in 2026.08.19
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    assert ytu.download_mb() == ytu.DOWNLOAD_MB == 18


# ------------------------------------------------------------ checksum parsing

def test_the_checksum_line_is_matched_by_exact_file_name():
    good = "a" * 64
    text = (
        f"{'b' * 64}  yt-dlp_macos\n"
        f"{'c' * 64}  yt-dlp_macos_legacy\n"
        f"{good} *yt-dlp_macos.zip\n"
        f"{'d' * 64}  yt-dlp\n"
    )
    assert ytu._expected_hash(text, "yt-dlp_macos.zip") == good
    assert ytu._expected_hash(text, "yt-dlp_macos") == "b" * 64
    assert ytu._expected_hash(text.upper().replace("YT-DLP_MACOS.ZIP", "yt-dlp_macos.zip"), "yt-dlp_macos.zip") == good


@pytest.mark.parametrize("text", [
    "", "not a checksum file", f"{'a' * 63}  yt-dlp_macos.zip\n", f"{'g' * 64}  yt-dlp_macos.zip\n",
    f"{'a' * 64}  other/yt-dlp_macos.zip\n",
])
def test_a_missing_or_malformed_line_is_an_error(text):
    with pytest.raises(ytu._BootstrapFailed):
        ytu._expected_hash(text, "yt-dlp_macos.zip")


def test_the_state_file_stays_valid_json(mac, github):
    github.publish(_NEW)
    _update()
    json.loads((_tools(mac) / "state.json").read_text(encoding="utf-8"))


def test_the_fallback_hint_names_the_app_download_page():
    from core.updates import RELEASES_PAGE_URL

    assert "install the newest version of this app" in ytu.OUTDATED_HINT
    assert RELEASES_PAGE_URL in ytu.OUTDATED_HINT


# ------------------------------------------- one deadline for the whole install

@pytest.fixture
def clock(monkeypatch):
    """A clock that moves one second per look, and a 20 s limit for the install."""
    ticks = {"now": 1000.0}

    def _monotonic():
        ticks["now"] += 1.0
        return ticks["now"]

    monkeypatch.setattr(ytu, "time", SimpleNamespace(monotonic=_monotonic, time=ytu.time.time))
    monkeypatch.setattr(ytu, "BOOTSTRAP_TIMEOUT_S", 20)
    return ticks


def test_a_zip_that_trickles_in_is_cut_off_at_the_deadline(mac, github, clock):
    github.publish(_NEW)
    github.routes[_CDN.format(name="zip")]["trickle"] = True  # one byte per read, as a stalled link does

    result = _update()

    assert result.status == "failed" and "timed out" in result.message
    assert result.completed is False
    assert _cache_files(mac) == []


def test_a_checksum_list_that_trickles_in_is_cut_off_too(mac, github, clock):
    github.publish(_NEW)
    github.routes[_CDN.format(name="sums")]["trickle"] = True

    result = _update()

    assert result.status == "failed" and "timed out" in result.message
    assert github.zip_requests() == []


def test_connecting_is_given_only_the_time_that_is_left(mac, github, monkeypatch):
    seen: list[float] = []
    real_open = urllib.request.OpenerDirector.open

    def _open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        seen.append(timeout)
        return real_open(self, fullurl, data, timeout)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _open)
    monkeypatch.setattr(ytu, "BOOTSTRAP_TIMEOUT_S", 5)
    github.publish(_NEW)
    assert _update().status == "updated"
    assert seen and all(0 < t <= 5 for t in seen)  # never the full 30 s socket timeout


def test_the_whole_install_shares_one_deadline(mac, github, monkeypatch):
    seen: list[float] = []
    real = ytu._download_checked

    def _spy(url, out, expected, deadline):
        seen.append(deadline)
        return real(url, out, expected, deadline)

    monkeypatch.setattr(ytu, "_download_checked", _spy)
    real_fetch = ytu._fetch_checksum

    def _spy_fetch(asset, deadline):
        seen.append(deadline)
        return real_fetch(asset, deadline)

    monkeypatch.setattr(ytu, "_fetch_checksum", _spy_fetch)
    github.publish(_NEW)
    _update()
    assert len(seen) == 2 and seen[0] == seen[1]


# ------------------------------------------------------ one install at a time

def test_a_second_app_instance_is_told_to_wait_and_touches_nothing(mac, github, monkeypatch):
    _stray(mac, "onedir-2026.01.01-other", age_days=3)  # would be removed by an install
    monkeypatch.setattr(ytu, "_try_lock", lambda _handle: False)
    github.publish(_NEW)

    result = _update()

    assert result.status == "busy"
    assert "Another copy of the app" in result.message
    assert github.requested == []
    assert "onedir-2026.01.01-other" in _installed(mac)
    assert ytu._updating is False


def test_the_start_up_clean_up_waits_for_the_other_instance_too(mac, github, monkeypatch):
    github.publish(_NEW)
    _update()
    old = _installed(mac)[0]
    github.publish(_NEWER)
    _update()
    later = ytu.now_utc() + ytu.RETIRED_GRACE + ytu.timedelta(minutes=1)
    monkeypatch.setattr(ytu, "now_utc", lambda: later)
    monkeypatch.setattr(ytu, "_try_lock", lambda _handle: False)
    ytu.prune_old_installs()
    assert old in _installed(mac)


def test_the_lock_is_released_after_every_install(mac, github, monkeypatch):
    held: list[bool] = []
    real = ytu._install_lock

    @ytu.contextlib.contextmanager
    def _watch():
        with real() as got:
            held.append(got)
            yield got

    monkeypatch.setattr(ytu, "_install_lock", _watch)
    github.publish(_NEW, sums_hash="0" * 64)
    assert _update().status == "failed"  # a failed install
    github.publish(_NEW)
    assert _update().status == "updated"  # and the next one still gets the lock
    assert held == [True, True]


def test_the_clean_up_does_nothing_off_a_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    ytu.prune_old_installs()
    assert not (tmp_path / "cache").exists()


def test_other_systems_never_make_a_lock_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ytu, "_is_macos", lambda: False)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    exe = tmp_path / "install" / "yt-dlp.exe"
    exe.parent.mkdir()
    exe.write_bytes(_binary(_OLD))
    monkeypatch.setattr(ytu, "bundled_binary", lambda _n: str(exe))
    ytu.update_cached_copy(version_of=_version_of, run=lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="up to date", stderr=""))
    assert not (tmp_path / "cache" / "tools" / "yt-dlp" / ytu.LOCK_NAME).exists()


def test_two_handles_cannot_hold_the_real_lock_at_once(tmp_path):
    pytest.importorskip("fcntl")  # POSIX only: this is the macOS code path
    path = tmp_path / "lock"
    with open(path, "a+b") as first, open(path, "a+b") as second:
        assert ytu._try_lock(first) is True
        assert ytu._try_lock(second) is False
    with open(path, "a+b") as third:
        assert ytu._try_lock(third) is True  # closing the first released it


# --------------------------------------------- links are re-checked once all exist

def test_a_later_link_that_retargets_an_earlier_one_is_refused(mac, github, monkeypatch):
    """x/y/s -> t/.. is inside while t does not exist; x/y/t -> ../.. then makes s resolve above."""
    made: list[str] = []
    monkeypatch.setattr(os, "symlink", lambda target, path, *a, **k: made.append(Path(path).name))
    real_realpath = os.path.realpath

    def _realpath(path, *a, **k):
        if Path(path).name == "s" and len(made) == 2:  # both links exist now: s leads out
            return str(mac.tmp.parent / "outside")
        return real_realpath(path, *a, **k)

    monkeypatch.setattr(ytu.os.path, "realpath", _realpath)
    github.publish(_NEW, entries=[
        *_entries(_NEW), ("x/y/s", b"t/..", _LINK | 0o777), ("x/y/t", b"../..", _LINK | 0o777),
    ])
    result = _update()
    assert result.status == "failed" and "unsafe" in result.message
    assert made == ["s", "t"]  # each passed its own check when it was made
    assert _cache_files(mac) == []


@_posix_only  # Windows makes file links for targets that do not exist yet, so chains behave differently
def test_a_real_link_chain_that_leads_out_is_refused(tmp_path):
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(_zip_bytes([
        *_entries(_NEW), ("x/y/s", b"t/..", _LINK | 0o777), ("x/y/t", b"../..", _LINK | 0o777),
    ]))
    dest = tmp_path / "out"
    dest.mkdir()
    try:
        probe = tmp_path / "probe"
        os.symlink(".", probe)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create symbolic links")
    with pytest.raises(ytu._BootstrapFailed) as caught:
        ytu._extract_onedir(zip_path, dest)
    assert "unsafe" in caught.value.message


@_posix_only
def test_a_real_link_inside_the_folder_is_made(tmp_path):
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(_zip_bytes([*_entries(_NEW), ("_internal/Current", b"lib.dylib", _LINK | 0o755)]))
    dest = tmp_path / "out"
    dest.mkdir()
    try:
        os.symlink(".", tmp_path / "probe")
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create symbolic links")
    ytu._extract_onedir(zip_path, dest)
    assert (dest / "_internal" / "Current").is_symlink()
    assert (dest / "_internal" / "Current").read_bytes() == b"library"


# ------------------------------------------------------- what is checked is what is used

def test_the_unpacked_bytes_are_the_hashed_bytes_not_a_file_read_again(mac, github, monkeypatch):
    github.publish(_NEW)
    sources: list[object] = []
    real = ytu._extract_onedir

    def _spy(source, dest):
        sources.append(source)
        assert not any(n.endswith(".download") or n.endswith(".zip") for n in _cache_files(mac))
        return real(source, dest)

    monkeypatch.setattr(ytu, "_extract_onedir", _spy)
    assert _update().status == "updated"
    assert len(sources) == 1 and isinstance(sources[0], io.BytesIO)


# ------------------------------------------------------------ tag and modes

@pytest.mark.parametrize("path,tag", [
    ("/yt-dlp/yt-dlp/releases/download/2026.08.19/SHA2-256SUMS", "2026.08.19"),
    ("/yt-dlp/yt-dlp/releases/download/2026.8.19.123456/x", "2026.8.19.123456"),
    ("/yt-dlp/yt-dlp/releases/download/2026/x", "2026"),
    ("/yt-dlp/yt-dlp/releases/download/../x", ""),
    ("/yt-dlp/yt-dlp/releases/download/./x", ""),
    ("/yt-dlp/yt-dlp/releases/download/.../x", ""),
    ("/yt-dlp/yt-dlp/releases/download/2026..08/x", ""),
    ("/yt-dlp/yt-dlp/releases/download/2026.08./x", ""),
    ("/yt-dlp/yt-dlp/releases/download/nightly/x", ""),
    ("/yt-dlp/yt-dlp/releases/download/a-b/x", ""),
])
def test_only_a_dotted_number_is_taken_for_a_release_tag(path, tag):
    assert ytu._release_tag([f"https://github.com{path}"]) == tag


def test_group_and_other_never_get_write_permission(tmp_path, monkeypatch):
    asked: dict[str, int] = {}
    real = os.chmod
    monkeypatch.setattr(ytu.os, "chmod", lambda p, m, *a, **k: (asked.__setitem__(Path(p).name, m), real(p, m, *a, **k))[1])
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(_zip_bytes([
        *_entries(_NEW), ("_internal/wide", b"x", _FILE | 0o777), ("_internal/rw", b"x", _FILE | 0o666),
        ("_internal/sticky", b"x", _FILE | 0o1777),
    ]))
    dest = tmp_path / "out"
    dest.mkdir()
    ytu._extract_onedir(zip_path, dest)
    assert asked["wide"] == 0o755 and asked["rw"] == 0o644 and asked["sticky"] == 0o755
