"""The user-writable yt-dlp copy that updates itself (core.yt_dlp_update).

Hermetic: no network and no real yt-dlp. A "binary" here is a small file whose
content is its version ("yt-dlp 2026.08.19"); ``version_of`` reads that back,
and the fake updater rewrites the copy the way yt-dlp's ``--update-to`` does
(new file next to it, then a rename). The real update on a real yt-dlp.exe is
the card's manual check, recorded outside the test suite.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config as cfg
from core import yt_dlp_update as ytu

_OLD = "2026.08.19"
_NEW = "2026.09.27"


def _write_binary(path: Path, version: str | None) -> Path:
    """A fake yt-dlp: its content names its version (None = does not run)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"broken" if version is None else f"yt-dlp {version}".encode())
    return path


def _version_of(path: str) -> tuple[int, ...]:
    try:
        text = Path(path).read_bytes().decode("utf-8", "replace")
    except OSError:
        return ()
    if not text.startswith("yt-dlp "):
        return ()
    return tuple(int(p) for p in text.split()[1].split("."))


def _bump_mtime(path: Path) -> None:
    """Make sure a rewritten file gets another modification time."""
    st = path.stat()
    later = st.st_mtime_ns + 2_000_000_000
    os.utime(path, ns=(later, later))


class _FakeUpdater:
    """Stands in for ``subprocess.run([copy, "--update-to", "stable"])``."""

    def __init__(self, *, to: str | None = _NEW, returncode: int = 0, output: str | None = None,
                 raises: BaseException | None = None) -> None:
        self.to = to
        self.returncode = returncode
        self.output = output
        self.raises = raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if self.raises is not None:
            raise self.raises
        target = Path(cmd[0])
        current = _version_of(str(target))
        wanted = None if self.to is None else tuple(int(p) for p in self.to.split("."))
        out = self.output
        if self.returncode == 0 and (wanted is None or wanted > current):
            new = target.with_name(target.name + ".new")
            _write_binary(new, self.to)
            os.replace(new, target)
            _bump_mtime(target)
            if out is None:
                out = f"Updated yt-dlp to stable@{self.to}"
        elif out is None:
            out = f"yt-dlp is up to date (stable@{ytu.version_label(current)})"
        return SimpleNamespace(returncode=self.returncode, stdout=out, stderr="")


@pytest.fixture(autouse=True)
def _clean_gate():
    ytu._running.clear()
    ytu._updating = False
    yield
    ytu._running.clear()
    ytu._updating = False


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Bundled yt-dlp in an install folder, the cache in another one."""
    install = tmp_path / "install" / "bin"
    bundled = _write_binary(install / "yt-dlp.exe", _OLD)
    monkeypatch.setattr(ytu, "bundled_binary", lambda _name: str(bundled))
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    return SimpleNamespace(bundled=bundled, cache=tmp_path / "cache", tmp=tmp_path)


def _update(**kwargs):
    kwargs.setdefault("version_of", _version_of)
    kwargs.setdefault("run", _FakeUpdater())
    return ytu.update_cached_copy(**kwargs)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------- newer one wins

def test_the_copy_lives_in_the_user_cache_tools_folder(env):
    assert ytu.cached_path().parent == env.cache / "tools" / "yt-dlp"
    assert ytu.cached_path().name in ("yt-dlp.exe", "yt-dlp")


def test_without_a_copy_the_bundled_one_is_used(env):
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_a_newer_updated_copy_wins(env):
    result = _update()
    assert result.status == "updated"
    assert ytu.resolve_yt_dlp_path() == str(ytu.cached_path())


def test_the_bundled_one_wins_when_it_is_as_new_or_newer(env):
    _update()  # copy at _NEW
    for version in (_NEW, "2026.10.30"):
        _write_binary(env.bundled, version)
        _bump_mtime(env.bundled)
        ytu.refresh_state(version_of=_version_of)
        assert ytu.resolve_yt_dlp_path() == str(env.bundled), version


def test_a_copy_changed_since_its_record_is_not_used(env):
    _update()
    cached = ytu.cached_path()
    cached.write_bytes(b"something else entirely")
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_after_an_app_update_the_bundled_one_is_used_until_versions_are_reread(env):
    _update()  # copy at _NEW, bundled _OLD
    # The app was updated: another bundled binary, still older than the copy.
    _write_binary(env.bundled, "2026.09.01")
    _bump_mtime(env.bundled)
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)
    assert ytu.refresh_state_if_stale(version_of=_version_of) is True
    assert ytu.resolve_yt_dlp_path() == str(ytu.cached_path())
    assert ytu.refresh_state_if_stale(version_of=_version_of) is False


def test_refresh_without_a_copy_does_nothing(env):
    calls: list[str] = []
    assert ytu.refresh_state_if_stale(version_of=lambda p: calls.append(p) or ()) is False
    assert calls == []
    assert not (env.cache / "tools" / "yt-dlp" / "state.json").exists()


def test_a_broken_copy_falls_back_to_the_bundled_one(env):
    _update()
    cached = ytu.cached_path()
    _write_binary(cached, None)  # e.g. damaged on disk: --version fails
    _bump_mtime(cached)
    ytu.refresh_state(version_of=_version_of)
    state = ytu.load_state()
    assert state["cached"]["version"] == []
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


@pytest.mark.parametrize("state_text", ["not json", "[1, 2]", '{"cached": {"version": "x"}}'])
def test_an_unreadable_record_means_the_bundled_one(env, state_text):
    _update()
    (env.cache / "tools" / "yt-dlp" / "state.json").write_text(state_text, encoding="utf-8")
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_resolve_never_raises(env, monkeypatch):
    def _boom():
        raise OSError("no cache folder")

    monkeypatch.setattr(ytu, "user_cache_dir", _boom)
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_a_broken_copy_is_not_used_even_without_a_bundled_one(monkeypatch, tmp_path):
    monkeypatch.setattr(ytu, "bundled_binary", lambda name: name)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    _write_binary(ytu.cached_path(), None)
    ytu.refresh_state(version_of=_version_of)
    assert ytu.resolve_yt_dlp_path() == "yt-dlp"
    _write_binary(ytu.cached_path(), _NEW)
    _bump_mtime(ytu.cached_path())
    ytu.refresh_state(version_of=_version_of)
    assert ytu.resolve_yt_dlp_path() == str(ytu.cached_path())


def test_no_bundled_binary_and_no_copy_keeps_the_bare_name(monkeypatch, tmp_path):
    monkeypatch.setattr(ytu, "bundled_binary", lambda name: name)
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    assert ytu.resolve_yt_dlp_path() == "yt-dlp"


# ------------------------------------------------------------------ updating

def test_first_update_copies_the_bundled_one_and_updates_the_copy(env):
    before_hash, before_stat = _sha(env.bundled), env.bundled.stat()
    runner = _FakeUpdater()
    lines: list[str] = []
    result = _update(run=runner, log=lines.append)
    assert result.status == "updated"
    assert result.completed is True
    assert ytu.version_label(result.before) == _OLD
    assert ytu.version_label(result.after) == _NEW
    # yt-dlp's own updater ran on the copy, stable channel, never on the bundled file.
    (cmd, kwargs), = runner.calls
    assert cmd == [str(ytu.cached_path()), "--update-to", "stable"]
    assert kwargs["timeout"] == ytu.UPDATE_TIMEOUT_S
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert f"Updated yt-dlp to stable@{_NEW}" in lines
    # The bundled copy is never touched.
    assert _sha(env.bundled) == before_hash
    assert env.bundled.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert _version_of(str(ytu.cached_path())) == (2026, 9, 27)


def test_an_up_to_date_copy_reports_current(env):
    _update()
    runner = _FakeUpdater()
    result = _update(run=runner)
    assert result.status == "current"
    assert result.completed is True
    assert len(runner.calls) == 1


def test_a_broken_copy_is_replaced_from_the_bundled_one_before_updating(env):
    _update()
    _write_binary(ytu.cached_path(), None)
    _bump_mtime(ytu.cached_path())
    result = _update()
    assert result.status == "updated"
    assert ytu.version_label(result.before) == _OLD  # restarted from the bundled copy
    assert ytu.resolve_yt_dlp_path() == str(ytu.cached_path())


def test_a_copy_older_than_a_new_bundled_one_restarts_from_the_bundled_one(env):
    _update(run=_FakeUpdater(to="2026.09.01"))
    _write_binary(env.bundled, "2026.09.10")
    _bump_mtime(env.bundled)
    result = _update(run=_FakeUpdater(to=_NEW))
    assert ytu.version_label(result.before) == "2026.09.10"
    assert result.status == "updated"


def test_an_unverified_build_is_not_used(env):
    runner = _FakeUpdater(output=(
        "WARNING: The hash could not be found in the checksum file, skipping verification\n"
        f"Updated yt-dlp to stable@{_NEW}"
    ))
    result = _update(run=runner)
    assert result.status == "failed"
    assert not ytu.cached_path().exists()
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_a_copy_that_no_longer_starts_after_the_update_is_dropped(env):
    result = _update(run=_FakeUpdater(to=None))  # the "new" build does not run
    assert result.status == "failed"
    assert result.completed is True
    assert not ytu.cached_path().exists()
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_a_copy_that_does_not_start_is_never_updated(env):
    def _version_never(path: str) -> tuple[int, ...]:
        return () if path == str(ytu.cached_path()) else _version_of(path)

    runner = _FakeUpdater()
    result = ytu.update_cached_copy(run=runner, version_of=_version_never)
    assert result.status == "failed"
    assert runner.calls == []
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_nothing_runs_when_neither_copy_starts(env):
    _update()
    for path in (ytu.cached_path(), env.bundled):
        _write_binary(path, None)
        _bump_mtime(path)
    runner = _FakeUpdater()
    result = _update(run=runner)
    assert result.status == "failed"
    assert runner.calls == []  # never runs yt-dlp's updater on a copy that does not start
    assert not ytu.cached_path().exists()
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_a_timeout_is_a_failure_but_not_a_completed_check(env):
    result = _update(run=_FakeUpdater(raises=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)))
    assert result.status == "failed"
    assert result.completed is False
    # The copy made before the timeout is still a working one at the old version.
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)


def test_an_updater_error_reports_yt_dlps_message(env):
    """yt-dlp's updater gave up (here: GitHub unreachable). Nothing was
    checked, so it is not a completed check: the automatic mode must not wait
    24 h before trying again (an offline first download would otherwise
    suppress every retry for a day)."""
    runner = _FakeUpdater(returncode=100, output=(
        "Current version: stable@2026.08.19\n"
        "ERROR: Unable to obtain version info; Please try again later"
    ))
    result = _update(run=runner)
    assert result.status == "failed"
    assert result.completed is False
    assert result.message.startswith("ERROR: Unable to obtain version info")
    assert "Could not update the video downloader" in ytu.result_text(result)


def test_an_unwritable_cache_is_a_failure_not_an_exception(env, monkeypatch):
    def _no_copy(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(ytu.shutil, "copyfile", _no_copy)
    result = _update()
    assert result.status == "failed"
    assert "denied" in result.message
    assert ytu._updating is False


def test_unsupported_without_a_single_file_bundled_build(monkeypatch, tmp_path):
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    # On a Mac the folder build may be installed instead (bootstrap_possible); not this rule.
    monkeypatch.setattr(ytu, "bootstrap_possible", lambda: False)
    # A bare name: no bundled yt-dlp to copy (PATH lookup).
    monkeypatch.setattr(ytu, "bundled_binary", lambda name: name)
    assert ytu.can_self_update() is False
    assert _update().status == "unsupported"
    # yt-dlp's folder build (the macOS app bundles one): yt-dlp refuses --update.
    dist = tmp_path / "bin" / "yt-dlp_dist"
    exe = _write_binary(dist / "yt-dlp_macos", _OLD)
    (dist / "_internal").mkdir()
    monkeypatch.setattr(ytu, "bundled_binary", lambda _name: str(exe))
    assert ytu.can_self_update() is False
    runner = _FakeUpdater()
    assert _update(run=runner).status == "unsupported"
    assert runner.calls == []


def test_result_texts_name_the_versions():
    up = ytu.UpdateResult("updated", before=(2026, 8, 19), after=(2026, 9, 27), completed=True)
    assert "2026.09.27" in ytu.result_text(up)
    same = ytu.UpdateResult("current", before=(2026, 9, 27), after=(2026, 9, 27), completed=True)
    assert "already the newest version (2026.09.27)" in ytu.result_text(same)


def test_a_build_that_cannot_be_removed_is_marked_rejected(env, monkeypatch):
    """An unverified build held open by another program (a virus scanner, a
    running format lookup) can neither be deleted nor renamed. It must still
    never be used, and the next update must copy the bundled one over it."""
    target = ytu.cached_path()
    real_unlink, real_replace = Path.unlink, os.replace
    locked = {"on": True}

    def _unlink(self, *a, **k):
        if locked["on"] and Path(self) == target:
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)

    def _replace(src, dst):
        if locked["on"] and Path(src) == target:
            raise PermissionError("in use")
        return real_replace(src, dst)

    monkeypatch.setattr(Path, "unlink", _unlink)
    monkeypatch.setattr(ytu.os, "replace", _replace)
    runner = _FakeUpdater(output=(
        "WARNING: The hash could not be found in the checksum file, skipping verification"
    ))
    result = _update(run=runner)
    assert result.status == "failed"
    assert target.exists()  # still there: it could not be removed
    assert ytu.load_state()["cached"]["rejected"] is True
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)
    # A refresh keeps the rejection for exactly this file.
    ytu.refresh_state(version_of=_version_of)
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)
    assert ytu.refresh_state_if_stale(version_of=_version_of) is False
    # The lock is gone: the next update starts again from the bundled copy.
    locked["on"] = False
    result = _update(run=_FakeUpdater())
    assert ytu.version_label(result.before) == _OLD
    assert result.status == "updated"
    assert ytu.resolve_yt_dlp_path() == str(target)


def test_a_rejected_record_does_not_outlive_the_file_it_was_made_for(env, monkeypatch):
    """The rejection belongs to the file that was rejected. When the next update
    replaces that file, a new build with the same size and modification time
    (two files written within one timer tick) must not inherit the rejection."""
    target = ytu.cached_path()
    real_unlink, real_replace = Path.unlink, os.replace
    locked = {"on": True}

    def _unlink(self, *a, **k):
        if locked["on"] and Path(self) == target:
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)

    def _replace(src, dst):
        if locked["on"] and Path(src) == target:
            raise PermissionError("in use")
        return real_replace(src, dst)

    monkeypatch.setattr(Path, "unlink", _unlink)
    monkeypatch.setattr(ytu.os, "replace", _replace)
    unverified = _FakeUpdater(output="WARNING: ... skipping verification")
    assert _update(run=unverified).status == "failed"
    rejected_fingerprint = ytu.load_state()["cached"]["fingerprint"]
    locked["on"] = False

    class _SameTick(_FakeUpdater):
        def __call__(self, cmd, **kwargs):
            result = super().__call__(cmd, **kwargs)
            # The new build lands with the rejected file's size and mtime.
            os.utime(cmd[0], ns=(rejected_fingerprint[1], rejected_fingerprint[1]))
            assert ytu._fingerprint(cmd[0]) == rejected_fingerprint  # the aliasing is real here
            return result

    result = _update(run=_SameTick())
    assert result.status == "updated"
    assert ytu.resolve_yt_dlp_path() == str(target)


def test_an_unremovable_build_is_renamed_away_when_possible(env, monkeypatch):
    target = ytu.cached_path()
    real_unlink = Path.unlink

    def _unlink(self, *a, **k):
        if Path(self) == target:
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", _unlink)
    runner = _FakeUpdater(output="WARNING: ... skipping verification")
    assert _update(run=runner).status == "failed"
    assert not target.exists()
    assert target.with_name(target.name + ".rejected").exists()
    assert ytu.resolve_yt_dlp_path() == str(env.bundled)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert _update().status == "updated"
    assert not target.with_name(target.name + ".rejected").exists()  # cleaned by the next copy


def test_a_slow_refresh_never_overwrites_a_newer_record(env):
    """Two refreshes overlap: the startup one (slow, saw the old copy) and the
    one an update makes after replacing the copy. The newer record must win,
    or the app would run the bundled copy until the next launch."""
    _update(run=_FakeUpdater(to="2026.09.01"))
    cached = ytu.cached_path()
    asked = threading.Event()
    release = threading.Event()

    def _slow_version(path: str) -> tuple[int, ...]:
        if path == str(cached) and not release.is_set():
            asked.set()
            release.wait(5)
            return (2026, 9, 1)  # what the old copy said
        return _version_of(path)

    slow = threading.Thread(target=lambda: ytu.refresh_state(version_of=_slow_version))
    slow.start()
    assert asked.wait(5)
    # The update replaces the copy and records it, while the slow refresh still runs.
    _write_binary(cached, _NEW)
    _bump_mtime(cached)
    fast = threading.Thread(target=lambda: ytu.refresh_state(version_of=_version_of))
    fast.start()
    time.sleep(0.2)
    release.set()
    slow.join(5)
    fast.join(5)
    state = ytu.load_state()
    assert state["cached"]["fingerprint"] == ytu._fingerprint(cached)
    assert state["cached"]["version"] == [2026, 9, 27]
    assert ytu.resolve_yt_dlp_path() == str(cached)


def test_the_startup_refresh_is_skipped_while_an_update_runs(env):
    _update()
    _write_binary(env.bundled, "2026.09.01")
    _bump_mtime(env.bundled)
    asked: list[str] = []
    ytu._updating = True
    assert ytu.refresh_state_if_stale(version_of=lambda p: asked.append(p) or ()) is False
    assert asked == []


def test_state_writes_leave_no_temporary_files(env):
    _update()
    for _ in range(3):
        ytu.refresh_state(version_of=_version_of)
    leftovers = [p.name for p in (env.cache / "tools" / "yt-dlp").iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ------------------------------------------------ never during a running download

def test_no_update_while_a_download_runs(env):
    runner = _FakeUpdater()
    ytu.begin_download("download-1")
    result = _update(run=runner)
    assert result.status == "busy"
    assert result.completed is False
    assert runner.calls == []
    ytu.end_download("download-1")
    assert _update(run=runner).status == "updated"


def test_a_download_waits_for_a_running_update(env):
    release = threading.Event()
    started = threading.Event()
    real = _FakeUpdater()

    def _slow(cmd, **kwargs):
        started.set()
        release.wait(5)
        return real(cmd, **kwargs)

    results: list[ytu.UpdateResult] = []
    worker = threading.Thread(target=lambda: results.append(_update(run=_slow)))
    worker.start()
    assert started.wait(5)
    entered = threading.Event()
    downloader = threading.Thread(
        target=lambda: (ytu.begin_download("d"), entered.set()),
    )
    downloader.start()
    assert not entered.wait(0.3)  # still waiting for the update
    assert ytu.downloads_running() == 0
    release.set()
    worker.join(5)
    assert entered.wait(5)
    downloader.join(5)
    assert results and results[0].status == "updated"
    assert ytu.downloads_running() == 1
    # The download that waited now gets the updated copy.
    assert ytu.resolve_yt_dlp_path() == str(ytu.cached_path())
    ytu.end_download("d")


def test_a_second_update_while_one_runs_is_busy(env):
    release = threading.Event()
    started = threading.Event()
    real = _FakeUpdater()

    def _slow(cmd, **kwargs):
        started.set()
        release.wait(5)
        return real(cmd, **kwargs)

    worker = threading.Thread(target=lambda: _update(run=_slow))
    worker.start()
    assert started.wait(5)
    second = _FakeUpdater()
    assert _update(run=second).status == "busy"
    assert second.calls == []
    assert ytu.wait_while_updating(timeout=0.05) is False
    release.set()
    worker.join(5)
    assert ytu.wait_while_updating(timeout=1) is True


def test_download_running_unregisters_even_on_error(env):
    with pytest.raises(RuntimeError):
        with ytu.download_running():
            assert ytu.downloads_running() == 1
            raise RuntimeError("yt-dlp failed")
    assert ytu.downloads_running() == 0
    ytu.end_download("never-began")  # harmless
    assert ytu.downloads_running() == 0


def test_a_download_does_not_wait_forever_for_a_stuck_update(env):
    ytu._updating = True
    t0 = time.monotonic()
    ytu.begin_download("d", timeout=0.1)
    assert time.monotonic() - t0 < 2
    assert ytu.downloads_running() == 1


# ------------------------------------------------------------ when to offer it

@pytest.mark.parametrize("text", [
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "WARNING: [youtube] abc: Signature extraction failed: Some formats may be missing",
    "WARNING: [youtube] abc: nsig extraction failed: You may experience throttling",
    "ERROR: [youtube] abc: Unable to extract uploader id",
    "ERROR: [generic] please report this issue on https://github.com/yt-dlp/yt-dlp/issues , "
    "filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U",
])
def test_outdated_signs_are_recognised(text):
    assert ytu.looks_outdated(text)
    assert ytu.should_offer_update(text)


@pytest.mark.parametrize("text", [
    "",
    "ERROR: [youtube] abc: Private video. Sign in if you've been granted access to this video",
    "ERROR: [youtube] abc: Sign in to confirm your age",
    "ERROR: [instagram] abc: Requested content is not available, rate-limit reached or login required",
    "ERROR: unable to download video data: HTTP Error 404: Not Found",
    "ERROR: Unable to write to the output folder",
])
def test_other_failures_do_not_offer_an_update(text, monkeypatch):
    monkeypatch.setattr(ytu, "find_deno", lambda: "C:/deno.exe")
    assert not ytu.should_offer_update(text)


def test_missing_js_runtime_offers_an_update_only_when_deno_is_there(monkeypatch):
    text = "WARNING: [youtube] No supported JavaScript runtime could be found"
    monkeypatch.setattr(ytu, "find_deno", lambda: None)
    assert not ytu.should_offer_update(text)  # the "Install YouTube helper" button is the fix
    monkeypatch.setattr(ytu, "find_deno", lambda: "C:/deno.exe")
    assert ytu.should_offer_update(text)


_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("last,due", [
    ("", True),
    (None, True),
    ((_NOW - timedelta(hours=23, minutes=59)).isoformat(), False),
    ((_NOW - timedelta(hours=24)).isoformat(), True),
    ("2026-09-01T10:00:00", True),  # no UTC offset: treated as never checked
    ("garbage", True),
    (12345, True),
])
def test_auto_update_due(last, due):
    assert ytu.auto_update_due(last, _NOW) is due


@pytest.mark.parametrize("value,mode", [
    ("ask", "ask"), ("auto", "auto"), ("never", "never"), (" AUTO ", "auto"),
    ("", "ask"), (None, "ask"), ("sometimes", "ask"), (True, "ask"),
])
def test_update_mode_normalises(value, mode):
    assert ytu.update_mode({"yt_dlp_update_mode": value}) == mode


# ---------------------------------------------------------------- the config

_KEYS = ("yt_dlp_update_mode", "last_yt_dlp_update_check")


def test_the_keys_have_defaults_and_are_local_only():
    assert cfg.DEFAULT_CONFIG["yt_dlp_update_mode"] == "ask"
    assert cfg.DEFAULT_CONFIG["last_yt_dlp_update_check"] == ""
    assert "auto_update_yt_dlp" not in cfg.DEFAULT_CONFIG
    for key in (*_KEYS, "auto_update_yt_dlp"):
        assert key in cfg.LOCAL_ONLY_KEYS
        assert key not in cfg.ONLINE_ALLOWED_KEYS


def test_online_config_cannot_set_the_keys(monkeypatch):
    hostile = {"yt_dlp_update_mode": "auto", "last_yt_dlp_update_check": "2099-01-01T00:00:00+00:00",
               "auto_update_yt_dlp": True}
    monkeypatch.setattr(cfg, "ONLINE_ALLOWED_KEYS", cfg.ONLINE_ALLOWED_KEYS | set(hostile))
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, dict(hostile), None)
    assert merged["yt_dlp_update_mode"] == "ask"
    assert merged["last_yt_dlp_update_check"] == ""
    assert "auto_update_yt_dlp" not in merged
    local = {"yt_dlp_update_mode": "never"}
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, dict(hostile), local)
    assert merged["yt_dlp_update_mode"] == "never"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(cfg, "user_log_dir", lambda: tmp_path / "log")
    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(cfg, "config_path", lambda: str(config_dir / "config.json"))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.mark.parametrize("local,mode", [
    ({"auto_update_yt_dlp": True}, "auto"),
    ({"auto_update_yt_dlp": False}, "ask"),
    ({"auto_update_yt_dlp": True, "yt_dlp_update_mode": "never"}, "never"),
    ({}, "ask"),
])
def test_the_old_switch_is_read_once_as_the_mode(config_dir, local, mode):
    (config_dir / "config.json").write_text(json.dumps({"theme": "light", **local}), encoding="utf-8")
    loaded = cfg.load_config(fetch_online=False)
    assert loaded["yt_dlp_update_mode"] == mode
    assert "auto_update_yt_dlp" not in loaded
    cfg.save_config(loaded)
    on_disk = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert "auto_update_yt_dlp" not in on_disk
    if local:
        # Read from the old switch: written explicitly.
        assert on_disk["yt_dlp_update_mode"] == mode
    else:
        # Untouched default: a merged save no longer pins it.
        assert "yt_dlp_update_mode" not in on_disk
    assert cfg.load_config(fetch_online=False)["yt_dlp_update_mode"] == mode


def test_an_online_old_switch_does_not_turn_on_automatic_updates(config_dir, monkeypatch):
    (config_dir / "config.json").write_text(
        json.dumps({"theme": "light", "config_url": "https://example.invalid/app_config.json"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "_ONLINE_MEMO", {})
    monkeypatch.setattr(
        cfg, "fetch_online_config",
        lambda _url: {"auto_update_yt_dlp": True, "yt_dlp_update_mode": "auto"},
    )
    assert cfg.load_config()["yt_dlp_update_mode"] == "ask"
