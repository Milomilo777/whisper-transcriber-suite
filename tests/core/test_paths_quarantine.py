"""core.paths.clear_bundled_quarantine: the macOS app un-quarantines its own
bundled tools at startup, so Gatekeeper does not hold and kill yt-dlp after a
browser download of the .dmg ("the bundled yt-dlp failed to run" on v1.9.3).
"""
from __future__ import annotations

import os
import sys

import pytest

from core import paths


def _setup(monkeypatch, tmp_path, *, platform: str, frozen: bool) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("yt-dlp", "deno", "ffmpeg"):
        (bin_dir / name).write_bytes(b"\xca\xfe\xba\xbe")
    monkeypatch.setattr(paths, "bin_dir", lambda: str(bin_dir))
    monkeypatch.setattr(sys, "platform", platform)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    cleared: list[str] = []
    monkeypatch.setattr(paths, "_remove_quarantine_xattr", cleared.append)
    return cleared


def test_frozen_mac_app_clears_every_bundled_tool(monkeypatch, tmp_path):
    cleared = _setup(monkeypatch, tmp_path, platform="darwin", frozen=True)
    paths.clear_bundled_quarantine()
    assert sorted(p.replace("\\", "/").rsplit("/", 1)[1] for p in cleared) == [
        "deno", "ffmpeg", "yt-dlp",
    ]


def test_folder_tool_is_cleared_recursively(monkeypatch, tmp_path):
    # yt-dlp's onedir build: an executable next to a folder of libraries;
    # Gatekeeper checks each file, so each one must lose the flag.
    cleared = _setup(monkeypatch, tmp_path, platform="darwin", frozen=True)
    dist = tmp_path / "bin" / "yt-dlp_dist"
    (dist / "_internal" / "lib").mkdir(parents=True)
    (dist / "yt-dlp_macos").write_bytes(b"\xca\xfe\xba\xbe")
    (dist / "_internal" / "Python").write_bytes(b"\xca\xfe\xba\xbe")
    (dist / "_internal" / "lib" / "_ssl.so").write_bytes(b"\xca\xfe\xba\xbe")
    paths.clear_bundled_quarantine()
    rel = sorted(
        p.replace("\\", "/").split("/bin/", 1)[1] for p in cleared
    )
    assert rel == [
        "deno", "ffmpeg", "yt-dlp", "yt-dlp_dist",
        "yt-dlp_dist/_internal", "yt-dlp_dist/_internal/Python",
        "yt-dlp_dist/_internal/lib", "yt-dlp_dist/_internal/lib/_ssl.so",
        "yt-dlp_dist/yt-dlp_macos",
    ]


def test_symlinked_folder_tool_is_walked_like_in_the_app(monkeypatch, tmp_path):
    # The real .app: Contents/MacOS/bin holds only symlinks into
    # Contents/Frameworks/bin, the onedir yt-dlp folder included.
    cleared = _setup(monkeypatch, tmp_path, platform="darwin", frozen=True)
    internal = tmp_path / "Frameworks" / "bin" / "yt-dlp_dist" / "_internal"
    internal.mkdir(parents=True)
    (internal / "Python").write_bytes(b"\xca\xfe\xba\xbe")
    try:
        os.symlink(internal.parent, tmp_path / "bin" / "yt-dlp_dist",
                   target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this OS/user cannot create symlinks")
    paths.clear_bundled_quarantine()
    inside = sorted(
        p.replace("\\", "/").split("/Frameworks/bin/", 1)[1]
        for p in cleared if "/Frameworks/bin/" in p.replace("\\", "/")
    )
    assert inside == ["yt-dlp_dist/_internal", "yt-dlp_dist/_internal/Python"]


def test_source_run_and_other_platforms_are_untouched(monkeypatch, tmp_path):
    cleared = _setup(monkeypatch, tmp_path, platform="darwin", frozen=False)
    paths.clear_bundled_quarantine()
    assert cleared == []


def test_frozen_windows_build_is_untouched(monkeypatch, tmp_path):
    cleared = _setup(monkeypatch, tmp_path, platform="win32", frozen=True)
    paths.clear_bundled_quarantine()
    assert cleared == []


def test_missing_bin_dir_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "bin_dir", lambda: str(tmp_path / "nope"))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    paths.clear_bundled_quarantine()


def test_remove_xattr_never_raises_on_a_missing_file(tmp_path):
    paths._remove_quarantine_xattr(str(tmp_path / "missing"))
