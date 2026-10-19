"""core.llama_runtime: pinned llama.cpp assets, safe extraction, atomic install, VC++ preflight."""
from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from core import llama_runtime as lr
from core import offline
from tests.core._fake_file_server import FakeFileServer

EXE = lr.server_exe_name()


# ---------------------------------------------------------------- pins


def test_every_pin_is_an_explicit_tag_with_size_and_sha256():
    assert re.fullmatch(r"b\d{4,6}", lr.LLAMA_CPP_TAG)
    assert lr.ASSETS, "no assets pinned"
    for asset in lr.ASSETS.values():
        assert asset.name.startswith(f"llama-{lr.LLAMA_CPP_TAG}-bin-")
        assert asset.name.endswith((".zip", ".tar.gz"))
        assert re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
        assert 1_000_000 < asset.size < 200_000_000
        url = lr.release_url(asset)
        assert f"/releases/download/{lr.LLAMA_CPP_TAG}/{asset.name}" in url
        assert "latest" not in url


@pytest.mark.parametrize(
    ("system", "machine", "mac", "expected"),
    [
        ("Windows", "AMD64", None, "win-cpu-x64.zip"),
        ("Windows", "ARM64", None, "win-cpu-arm64.zip"),
        ("Darwin", "arm64", (14, 6), "macos-arm64.tar.gz"),
        ("Darwin", "x86_64", (13, 3), "macos-x64.tar.gz"),
        ("Linux", "x86_64", None, "ubuntu-x64.tar.gz"),
    ],
)
def test_asset_per_platform(system, machine, mac, expected):
    asset = lr.asset_for(system, machine, mac)
    assert asset is not None and asset.name.endswith(expected)
    assert lr.unsupported_reason(system, machine, mac) == ""


@pytest.mark.parametrize(
    ("system", "machine", "mac", "needle"),
    [
        ("Darwin", "x86_64", (10, 15), "13.3"),
        ("Darwin", "arm64", (13, 2), "13.3"),
        ("Linux", "aarch64", None, "Linux aarch64"),
        ("Windows", "x86", None, "Windows x86"),
        ("FreeBSD", "amd64", None, "FreeBSD"),
    ],
)
def test_unsupported_platforms_get_a_reason_and_no_asset(system, machine, mac, needle):
    assert lr.asset_for(system, machine, mac) is None
    assert needle in lr.unsupported_reason(system, machine, mac)


# ---------------------------------------------------------------- archives


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _tar(members: list[tuple[str, str, bytes | str]]) -> bytes:
    """(name, kind, data-or-linkname); kind in file / dir / sym / hard."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, kind, data in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                assert isinstance(data, bytes)
                info.size = len(data)
                info.mode = 0o755
                tf.addfile(info, io.BytesIO(data))
                continue
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
            elif kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = str(data)
            elif kind == "hard":
                info.type = tarfile.LNKTYPE
                info.linkname = str(data)
            tf.addfile(info)
    return buf.getvalue()


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize(
    "bad_name",
    ["../evil.dll", "sub/../../evil.dll", "/abs/evil.dll", "C:/evil.dll", "..\\evil.dll", "C:evil.dll"],
)
def test_zip_slip_and_absolute_names_are_rejected(tmp_path, bad_name):
    archive = _write(tmp_path, "a.zip", _zip({EXE: b"exe", bad_name: b"x"}))
    out = tmp_path / "out"
    with pytest.raises(lr.UnsafeArchiveError):
        lr.extract_archive(archive, out)
    assert not (tmp_path / "evil.dll").exists()
    assert not out.exists() or not any(out.rglob("evil.dll"))


@pytest.mark.parametrize(
    "name",
    ["../x", "a/../../x", "a/b/../../../x", "/x", "C:x", "a:b", "nul", "x/aux.txt", "COM1", "x/evil.dll.", "x/evil "],
)
def test_member_path_check_alone_refuses_unsafe_names(name):
    # Tested on its own: the later inside-the-folder check must not be the only guard.
    with pytest.raises(lr.UnsafeArchiveError):
        lr._checked_member_path(name)


def test_member_path_check_keeps_normal_names():
    assert str(lr._checked_member_path("llama-b1/./lib/x.dll")) == "llama-b1/lib/x.dll"
    assert str(lr._checked_member_path("a\\b.dll")) == "a/b.dll"


def test_inside_check_alone_refuses_a_path_that_leaves_the_folder(tmp_path):
    from pathlib import PurePosixPath

    with pytest.raises(lr.UnsafeArchiveError):
        lr._inside(tmp_path / "out", PurePosixPath("..", "x"))
    assert lr._inside(tmp_path / "out", PurePosixPath("a", "b")) == (tmp_path / "out" / "a" / "b").resolve()


def test_zip_symlink_entries_are_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(EXE, b"exe")
        info = zipfile.ZipInfo("lib.so")
        info.external_attr = (0o120777 << 16)  # a symlink entry
        zf.writestr(info, "libreal.so")
    archive = _write(tmp_path, "a.zip", buf.getvalue())
    with pytest.raises(lr.UnsafeArchiveError, match="link"):
        lr.extract_archive(archive, tmp_path / "out")


def test_child_env_drops_options_and_injection_variables(monkeypatch):
    monkeypatch.setenv("LLAMA_ARG_HOST", "0.0.0.0")
    monkeypatch.setenv("GGML_BACKEND_PATH", "x")
    monkeypatch.setenv("LD_PRELOAD", "evil.so")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "evil.dylib")
    monkeypatch.setenv("WTS_KEEP_ME", "1")
    env = lr.child_env()
    assert env.get("WTS_KEEP_ME") == "1"
    for k in ("LLAMA_ARG_HOST", "GGML_BACKEND_PATH", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"):
        assert k not in env


def test_a_frozen_app_gives_the_child_the_users_library_path(monkeypatch):
    monkeypatch.setattr(lr.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/app/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    assert lr.child_env()["LD_LIBRARY_PATH"] == "/usr/local/lib"
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in lr.child_env()


@pytest.mark.parametrize(
    "member",
    [
        ("top/link", "sym", "../../outside"),
        ("top/link", "sym", "/etc/passwd"),
        ("top/sub/link", "sym", "../../../x"),
        ("top/hard", "hard", "../outside"),
        ("top/hard", "hard", "/etc/passwd"),
        ("../evil", "file", b"x"),
        ("/abs", "file", b"x"),
    ],
)
def test_tar_entries_that_escape_are_rejected(tmp_path, member):
    archive = _write(tmp_path, "a.tar.gz", _tar([("top", "dir", b""), (f"top/{EXE}", "file", b"e"), member]))
    out = tmp_path / "out"
    with pytest.raises(lr.UnsafeArchiveError):
        lr.extract_archive(archive, out)
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "members",
    [
        # a/b/up -> .. is a; a/b/up/out -> ../../.. would then leave dest by two levels
        [("a", "dir", b""), ("a/b", "dir", b""), ("a/b/up", "sym", ".."), ("a/b/up/out", "sym", "x")],
        # a link to a folder, then a file written through it
        [("top", "dir", b""), ("top/d", "sym", "sub"), ("top/sub", "dir", b""), ("top/d/x.dll", "file", b"x")],
        [("top", "dir", b""), ("top/l", "sym", "sub/lib.so")],  # a folder part in the target
        [("top", "dir", b""), ("top/lib.so", "file", b"x"), ("top/h", "hard", "top/lib.so")],
    ],
)
def test_tar_link_chains_and_writes_through_links_are_rejected(tmp_path, members):
    archive = _write(tmp_path, "a.tar.gz", _tar(members))
    out = tmp_path / "out"
    with pytest.raises(lr.UnsafeArchiveError):
        lr.extract_archive(archive, out)
    assert not out.exists() or not any(out.iterdir())


def test_tar_devices_and_fifos_are_rejected(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("top/fifo")
        info.type = tarfile.FIFOTYPE
        tf.addfile(info)
    archive = _write(tmp_path, "a.tar.gz", buf.getvalue())
    with pytest.raises(lr.UnsafeArchiveError):
        lr.extract_archive(archive, tmp_path / "out")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_tar_symlinks_inside_the_folder_are_kept(tmp_path):
    # The macOS and Linux tarballs carry libfoo.0.dylib -> libfoo.0.6.0.dylib links.
    archive = _write(tmp_path, "a.tar.gz", _tar([
        ("top", "dir", b""),
        (f"top/{EXE}", "file", b"e"),
        ("top/libx.0.6.0.dylib", "file", b"lib"),
        ("top/libx.0.dylib", "sym", "libx.0.6.0.dylib"),
    ]))
    out = tmp_path / "out"
    lr.extract_archive(archive, out)
    link = out / "top" / "libx.0.dylib"
    assert link.is_symlink() and link.read_bytes() == b"lib"
    assert os.access(out / "top" / EXE, os.X_OK)


def test_zip_with_a_folder_extracts_its_files(tmp_path):
    archive = _write(tmp_path, "a.zip", _zip({EXE: b"exe", "sub/lib.dll": b"lib"}))
    out = tmp_path / "out"
    lr.extract_archive(archive, out)
    assert (out / EXE).read_bytes() == b"exe"
    assert (out / "sub" / "lib.dll").read_bytes() == b"lib"


# ---------------------------------------------------------------- install


@pytest.fixture
def server():
    srv = FakeFileServer()
    yield srv
    srv.close()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    monkeypatch.setattr(lr, "user_cache_dir", lambda: root)
    monkeypatch.setattr(lr, "ensure_vc_runtime", lambda folder: [])
    return root


def _serve(server, data: bytes, name: str) -> lr.RuntimeAsset:
    server.state.payload = data
    return lr.RuntimeAsset(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def _leftovers(cache: Path) -> list[str]:
    root = cache / "tools" / "llama.cpp"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.name not in ("downloads", ".install.lock"))


def test_install_from_a_zip_puts_the_whole_folder_in_place(server, cache):
    asset = _serve(server, _zip({EXE: b"exe", "llama-server-impl.dll": b"impl"}), "llama-bX-bin-test.zip")
    exe = lr.install_runtime(base_url=server.base_url, asset=asset)
    assert exe == lr.runtime_dir() / EXE
    assert exe.read_bytes() == b"exe"
    assert (exe.parent / "llama-server-impl.dll").read_bytes() == b"impl"
    assert lr.installed_server() == exe
    assert _leftovers(cache) == [lr.LLAMA_CPP_TAG]
    # Only the (empty) lock file stays: deleting it would race another window.
    left = [p.name for p in (cache / "tools" / "llama.cpp" / "downloads").iterdir()]
    assert left == [asset.name + ".lock"], "archive or .part not removed"
    if os.name != "nt":
        assert os.access(exe, os.X_OK)


def test_install_from_a_tarball_drops_the_single_top_folder(server, cache):
    data = _tar([("llama-bX", "dir", b""), (f"llama-bX/{EXE}", "file", b"e"), ("llama-bX/LICENSE", "file", b"MIT")])
    asset = _serve(server, data, "llama-bX-bin-test.tar.gz")
    exe = lr.install_runtime(base_url=server.base_url, asset=asset)
    assert exe == lr.runtime_dir() / EXE
    assert (lr.runtime_dir() / "LICENSE").read_bytes() == b"MIT"


def test_an_installed_runtime_is_not_downloaded_again(server, cache):
    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    lr.install_runtime(base_url=server.base_url, asset=asset)
    lr.install_runtime(base_url=server.base_url, asset=asset)
    assert server.state.requests == 1


def test_a_second_window_is_refused_while_one_installs(server, cache):
    from core import verified_download as vd

    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    root = cache / "tools" / "llama.cpp"
    root.mkdir(parents=True)
    with vd.exclusive_lock(root / ".install.lock", "held by the other window"):
        with pytest.raises(vd.DownloadError, match="installing the offline AI engine"):
            lr.install_runtime(base_url=server.base_url, asset=asset)
    assert server.state.requests == 0
    assert lr.install_runtime(base_url=server.base_url, asset=asset).is_file()


def test_an_unsafe_archive_installs_nothing(server, cache):
    asset = _serve(server, _zip({EXE: b"exe", "../escape.dll": b"x"}), "llama-bX-bin-test.zip")
    with pytest.raises(lr.UnsafeArchiveError):
        lr.install_runtime(base_url=server.base_url, asset=asset)
    assert lr.installed_server() is None
    assert _leftovers(cache) == []
    assert not (cache / "tools" / "llama.cpp" / "escape.dll").exists()


def test_an_archive_without_the_server_installs_nothing(server, cache):
    asset = _serve(server, _zip({"llama-cli.exe": b"x"}), "llama-bX-bin-test.zip")
    with pytest.raises(RuntimeError, match="llama-server"):
        lr.install_runtime(base_url=server.base_url, asset=asset)
    assert lr.installed_server() is None
    assert _leftovers(cache) == []


def test_an_interrupted_install_leaves_no_half_folder(server, cache, monkeypatch):
    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    real = lr.extract_archive

    def boom(archive, dest):
        real(archive, dest)
        raise OSError("disk unplugged")

    monkeypatch.setattr(lr, "extract_archive", boom)
    with pytest.raises(OSError, match="disk unplugged"):
        lr.install_runtime(base_url=server.base_url, asset=asset)
    assert lr.installed_server() is None
    assert _leftovers(cache) == []


def test_a_stale_staging_folder_from_a_crash_is_swept(server, cache):
    stale = cache / "tools" / "llama.cpp" / ".staging-dead"
    stale.mkdir(parents=True)
    (stale / "x.dll").write_bytes(b"x")
    old = 1_000_000_000
    os.utime(stale, (old, old))
    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    lr.install_runtime(base_url=server.base_url, asset=asset)
    assert _leftovers(cache) == [lr.LLAMA_CPP_TAG]


def test_a_wrong_checksum_installs_nothing(server, cache):
    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    asset = lr.RuntimeAsset(name=asset.name, size=asset.size, sha256="f" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        lr.install_runtime(base_url=server.base_url, asset=asset)
    assert lr.installed_server() is None
    assert _leftovers(cache) == []


def test_work_offline_refuses_the_install(server, cache, monkeypatch):
    asset = _serve(server, _zip({EXE: b"exe"}), "llama-bX-bin-test.zip")
    monkeypatch.setattr(offline, "_override", True)
    with pytest.raises(offline.OfflineModeError):
        lr.install_runtime(base_url=server.base_url, asset=asset)
    assert server.state.requests == 0


def test_an_unsupported_computer_gets_the_reason(cache, monkeypatch):
    monkeypatch.setattr(lr, "unsupported_reason", lambda *a, **k: "no build for Plan 9")
    with pytest.raises(RuntimeError, match="Plan 9"):
        lr.install_runtime()


# ---------------------------------------------------------------- VC++ runtime


def test_vc_plan_copies_the_apps_newer_dll_and_keeps_a_newer_system_one(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for n in lr.VC_RUNTIME_DLLS:
        (app / n).write_bytes(b"dll")
    system = {"msvcp140.dll": (14, 50, 1, 0), "vcruntime140.dll": (14, 29, 0, 0), "vcruntime140_1.dll": None}
    app_versions = {str(app / n): (14, 44, 0, 0) for n in lr.VC_RUNTIME_DLLS}
    copies, missing = lr.plan_vc_runtime(system.get, lambda p: app_versions.get(str(p)), [app])
    assert missing == []
    assert copies == {
        "vcruntime140.dll": app / "vcruntime140.dll",  # app 14.44 beats system 14.29
        "vcruntime140_1.dll": app / "vcruntime140_1.dll",  # system has none
    }  # msvcp140: system 14.50 is newer, used as-is


def test_vc_plan_reports_what_neither_side_has(tmp_path):
    copies, missing = lr.plan_vc_runtime(lambda n: None, lambda p: None, [tmp_path])
    assert copies == {}
    assert missing == list(lr.VC_RUNTIME_DLLS)
    msg = lr.vc_runtime_message(missing)
    assert lr.VC_REDIST_URL in msg and "msvcp140.dll" in msg


def test_ensure_vc_runtime_copies_and_removes_its_own_stale_copies(tmp_path, monkeypatch):
    folder = tmp_path / "rt"
    folder.mkdir()
    src = tmp_path / "app"
    src.mkdir()
    (src / "vcruntime140.dll").write_bytes(b"app-copy")
    (folder / "msvcp140.dll").write_bytes(b"old local copy")  # system is newer now
    (folder / "vcruntime140_1.dll").write_bytes(b"not ours")  # never listed as copied
    (folder / lr._VC_MARKER).write_text("msvcp140.dll\n", encoding="utf-8")
    monkeypatch.setattr(lr.sys, "platform", "win32")
    monkeypatch.setattr(lr, "plan_vc_runtime", lambda *a, **k: ({"vcruntime140.dll": src / "vcruntime140.dll"}, []))
    assert lr.ensure_vc_runtime(folder) == []
    assert (folder / "vcruntime140.dll").read_bytes() == b"app-copy"
    assert not (folder / "msvcp140.dll").exists()
    assert (folder / "vcruntime140_1.dll").read_bytes() == b"not ours"
    assert (folder / lr._VC_MARKER).read_text(encoding="utf-8").split() == ["vcruntime140.dll"]


@pytest.mark.skipif(sys.platform != "win32", reason="reads a real Windows file version")
def test_file_version_reads_a_real_windows_dll():
    version = lr._file_version(Path(os.environ["WINDIR"]) / "System32" / "kernel32.dll")
    assert version is not None and len(version) == 4 and version[0] >= 6
    assert lr._file_version(Path(os.environ["WINDIR"]) / "no-such.dll") is None


@pytest.mark.parametrize("code", [0xC0000135, 0xC0000139, -1073741515])
def test_a_missing_dll_exit_code_becomes_the_vc_message(tmp_path, monkeypatch, code):
    monkeypatch.setattr(lr.sys, "platform", "win32")
    monkeypatch.setattr(
        lr.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], code, "", ""),
    )
    with pytest.raises(RuntimeError, match=re.escape(lr.VC_REDIST_URL)):
        lr.server_version(tmp_path / EXE)


def test_server_version_reads_the_build_line(tmp_path, monkeypatch):
    out = "version: 0.6.0-dev (build 11514, commit de7fa0a3c)\nbuilt with Clang 20.1.8 for Windows x86_64\n"
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(lr.subprocess, "run", run)
    assert lr.server_version(tmp_path / EXE) == "version: 0.6.0-dev (build 11514, commit de7fa0a3c)"
    assert seen["cwd"] == str(tmp_path)
