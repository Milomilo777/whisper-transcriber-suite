"""A burn that is stopped by closing the app (or by a crash) leaves nothing
behind in the user's folder, and the watched folder never re-transcribes
the app's own burn files.

Covers core/burn_subs.py (registry of running burns, ``abandon_active_burns``,
the crash journal and ``sweep_stale_burns``, the record of produced outputs)
and the watched-folder filter in core/watcher.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from core import burn_subs, watcher

# Stand-in for ffmpeg: writes part of the output and then hangs.
_HANG = r"""
import sys, time
open(sys.argv[1], "wb").write(b"partial")
print("out_time_us=1000000", flush=True)
time.sleep(120)
"""


@pytest.fixture
def systmp(tmp_path, monkeypatch):
    """The folder tempfile.mkdtemp() uses, so work folders can be listed."""
    d = tmp_path / "systmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return str(d)


@pytest.fixture(autouse=True)
def _journal_in_tmp(tmp_path, monkeypatch):
    journal = tmp_path / "_journal"
    monkeypatch.setattr(burn_subs, "_journal_dir", lambda: str(journal))
    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(
        burn_subs, "probe_media", lambda path: burn_subs.MediaInfo(10.0, True, "aac")
    )
    return journal


def _files(tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    video = folder / "clip.mp4"
    video.write_bytes(b"video")
    srt = folder / "clip.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    return str(video), str(srt), str(folder / "clip-subbed.mp4")


def _hanging_ffmpeg(monkeypatch):
    real = burn_subs._run_ffmpeg
    procs: list = []

    def run(cmd, **kw):
        fake = [sys.executable, "-c", _HANG, cmd[-1]]
        user_on_process = kw.get("on_process")

        def on_process(p):
            procs.append(p)
            if user_on_process:
                user_on_process(p)

        kw["on_process"] = on_process
        return real(fake, **kw)

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", run)
    return procs


def _start_burn(video, srt, out, **kw):
    result: dict = {}

    def target():
        try:
            burn_subs.burn(video, srt, out, **kw)
            result["ok"] = True
        except BaseException as e:  # noqa: BLE001 - handed to the test
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result


def _wait_until(cond, what, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _running_burn_files(folder):
    return [n for n in os.listdir(folder) if n.startswith(".burn-")]


# -- exit while a burn runs --------------------------------------------------------

def test_exit_stops_a_manual_burn_and_removes_its_partial(tmp_path, monkeypatch, _journal_in_tmp, systmp):
    procs = _hanging_ffmpeg(monkeypatch)
    video, srt, out = _files(tmp_path)
    folder = os.path.dirname(out)
    thread, result = _start_burn(video, srt, out)
    _wait_until(lambda: procs and _running_burn_files(folder), "ffmpeg to start")
    assert os.listdir(_journal_in_tmp)  # the crash journal exists while it runs

    assert burn_subs.abandon_active_burns() == 1

    thread.join(20)
    assert not thread.is_alive()
    assert isinstance(result.get("error"), burn_subs.BurnCancelled)
    assert procs[0].poll() is not None
    assert sorted(os.listdir(folder)) == ["clip.mp4", "clip.srt"]
    assert os.listdir(systmp) == []  # the burnsubs_ work folder is gone too
    assert os.listdir(_journal_in_tmp) == []
    assert burn_subs.abandon_active_burns() == 0  # nothing left registered


def test_exit_removes_the_chains_empty_placeholder(tmp_path, monkeypatch):
    procs = _hanging_ffmpeg(monkeypatch)
    video, srt, out = _files(tmp_path)
    folder = os.path.dirname(out)
    reserved = burn_subs.reserve_output_path(out)
    thread, result = _start_burn(video, srt, reserved, placeholder=reserved)
    _wait_until(lambda: procs and _running_burn_files(folder), "ffmpeg to start")
    assert os.path.getsize(reserved) == 0

    burn_subs.abandon_active_burns()

    thread.join(20)
    assert sorted(os.listdir(folder)) == ["clip.mp4", "clip.srt"]
    assert isinstance(result.get("error"), burn_subs.BurnCancelled)


def test_exit_never_removes_a_placeholder_that_holds_data(tmp_path, monkeypatch):
    procs = _hanging_ffmpeg(monkeypatch)
    video, srt, out = _files(tmp_path)
    folder = os.path.dirname(out)
    with open(out, "wb") as f:
        f.write(b"an earlier result")
    thread, _ = _start_burn(video, srt, out + "2.mp4", placeholder=out)
    _wait_until(lambda: procs and _running_burn_files(folder), "ffmpeg to start")

    burn_subs.abandon_active_burns()

    thread.join(20)
    assert open(out, "rb").read() == b"an earlier result"


def test_a_burn_that_ended_leaves_no_registration(tmp_path, monkeypatch, _journal_in_tmp):
    video, srt, out = _files(tmp_path)

    def ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"encoded")

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", ok)
    burn_subs.burn(video, srt, out)

    assert os.listdir(_journal_in_tmp) == []
    assert burn_subs.abandon_active_burns() == 0
    assert open(out, "rb").read() == b"encoded"


# -- crash: the next start sweeps what the journal recorded -----------------------------

def _record(journal, **fields):
    journal.mkdir(exist_ok=True)
    path = journal / "dead.json"
    path.write_text(json.dumps(fields), encoding="utf-8")
    return path


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_sweep_removes_what_a_dead_run_recorded(tmp_path, _journal_in_tmp):
    folder = tmp_path / "media"
    folder.mkdir()
    partial = folder / ".burn-abc123.mp4"
    partial.write_bytes(b"half an encode")
    placeholder = folder / "Talk-subbed.mp4"
    placeholder.write_bytes(b"")
    work = tmp_path / "burnsubs_xyz"
    work.mkdir()
    (work / "subs.srt").write_text("1", encoding="utf-8")
    unrelated = folder / "Talk.mp4"
    unrelated.write_bytes(b"the download")
    rec = _record(_journal_in_tmp, pid=_dead_pid(), pid_started=1.0, tmp_dir=str(work),
                  tmp_out=str(partial), placeholder=str(placeholder))

    removed = burn_subs.sweep_stale_burns()

    assert sorted(os.listdir(folder)) == ["Talk.mp4"]
    assert not work.exists() and not rec.exists()
    assert len(removed) == 3


def test_sweep_keeps_a_file_it_cannot_prove_is_its_own(tmp_path, _journal_in_tmp):
    folder = tmp_path / "media"
    folder.mkdir()
    finished = folder / "Talk-subbed.mp4"
    finished.write_bytes(b"a finished burn")        # placeholder that got data
    precious = folder / "notes-from-user.mp4"
    precious.write_bytes(b"user file")              # journal names it as the temp: wrong prefix
    rec = _record(_journal_in_tmp, pid=_dead_pid(), pid_started=1.0, tmp_dir=str(folder),
                  tmp_out=str(precious), placeholder=str(finished))

    burn_subs.sweep_stale_burns()

    assert finished.read_bytes() == b"a finished burn"
    assert precious.read_bytes() == b"user file"
    assert folder.is_dir()                          # not named burnsubs_*: not removed
    assert not rec.exists()


def test_sweep_leaves_a_run_that_is_still_alive(tmp_path, _journal_in_tmp):
    import psutil

    partial = tmp_path / ".burn-live.mp4"
    partial.write_bytes(b"encoding right now")
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        started = psutil.Process(live.pid).create_time()
        rec = _record(_journal_in_tmp, pid=live.pid, pid_started=started, tmp_dir="",
                      tmp_out=str(partial), placeholder="")
        assert burn_subs.sweep_stale_burns() == []
        assert partial.exists() and rec.exists()
    finally:
        live.kill()
        live.wait()


def test_sweep_with_no_journal_is_a_noop(tmp_path):
    assert burn_subs.sweep_stale_burns() == []


def test_sweep_drops_an_unreadable_record(tmp_path, _journal_in_tmp):
    _journal_in_tmp.mkdir()
    bad = _journal_in_tmp / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert burn_subs.sweep_stale_burns() == []
    assert not bad.exists()


# -- the watched folder ----------------------------------------------------------------

def test_a_finished_burn_is_remembered_as_the_apps_own_output(tmp_path, monkeypatch):
    video, srt, out = _files(tmp_path)
    def ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"encoded")

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", ok)
    assert not burn_subs.is_own_output(out)
    burn_subs.burn(video, srt, out)
    assert burn_subs.is_own_output(out)
    assert not burn_subs.is_own_output(video)


def test_the_output_is_known_before_the_file_appears(tmp_path, monkeypatch):
    # The watcher event for the final rename must not beat the record.
    video, srt, out = _files(tmp_path)

    def ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"encoded")

    real_replace = os.replace
    checked = []

    def replace(src, dst):
        if dst == out:  # not the journal's own rename
            checked.append(burn_subs.is_own_output(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", ok)
    monkeypatch.setattr(burn_subs.os, "replace", replace)
    burn_subs.burn(video, srt, out)
    assert checked == [True]


def test_a_failed_burn_is_not_remembered_as_an_output(tmp_path, monkeypatch):
    video, srt, out = _files(tmp_path)

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, b"", b"nope")

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", boom)
    with pytest.raises(RuntimeError):
        burn_subs.burn(video, srt, out)
    assert not burn_subs.is_own_output(out)


def test_watcher_skips_burn_temps_placeholders_and_own_outputs(tmp_path, monkeypatch):
    temp = tmp_path / ".burn-abc123.mp4"
    temp.write_bytes(b"x")
    placeholder = tmp_path / "Talk-subbed.mp4"
    placeholder.write_bytes(b"")
    numbered = tmp_path / "Talk-subbed (2).mp4"
    numbered.write_bytes(b"")
    plain = tmp_path / "Talk.mp4"
    plain.write_bytes(b"video")
    result = tmp_path / "Other-subbed.mp4"
    result.write_bytes(b"burned")
    user_file = tmp_path / "Mine-subbed.mp4"        # not produced by this run of the app
    user_file.write_bytes(b"user made it")
    monkeypatch.setattr(burn_subs, "_produced", {burn_subs._output_key(str(result))})

    assert watcher.watch_skip_reason(str(temp))
    assert watcher.watch_skip_reason(str(placeholder))
    assert watcher.watch_skip_reason(str(numbered))
    assert watcher.watch_skip_reason(str(result))
    assert watcher.watch_skip_reason(str(plain)) == ""
    assert watcher.watch_skip_reason(str(user_file)) == ""


def test_is_media_file_rejects_the_burn_temp_only():
    assert not watcher.is_media_file(".burn-abc123.mp4")
    assert watcher.is_media_file("burn-notes.mp4")
    assert watcher.is_media_file("Talk-subbed.mp4")   # drops/drag stay allowed


# -- App.on_exit stops the burns ----------------------------------------------------------

def _closing_app(order):
    import types

    return types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None, queue=[], download_queue=[],
        _closing=False, _folder_watcher=None, history=None,
        _save_window_geometry=lambda: order.append("geometry"),
        withdraw=lambda: None,
        _shutdown_server_on_exit=lambda: order.append("server"),
        transcription_service=types.SimpleNamespace(stop_all=lambda: order.append("workers")),
        destroy=lambda: order.append("destroy"),
    )


@pytest.mark.parametrize("fails", [False, True])
def test_app_exit_stops_running_burns_before_the_window_is_destroyed(monkeypatch, fails):
    from app import app as app_module

    order: list[str] = []

    def abandon():
        order.append("burns")
        if fails:
            raise RuntimeError("boom")
        return 1

    monkeypatch.setattr(burn_subs, "abandon_active_burns", abandon)
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda app: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda app: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker", lambda app: None)

    app_module.App.on_exit(_closing_app(order))  # type: ignore[arg-type]

    assert "burns" in order and order[-1] == "destroy"
    assert order.index("burns") < order.index("workers")


def test_a_cancel_after_the_encode_finished_keeps_the_finished_video(tmp_path, monkeypatch):
    # The chain row relies on this: only the app closing discards a finished encode.
    video, srt, out = _files(tmp_path)
    cancelled = {"now": False}

    def ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"encoded")
        cancelled["now"] = True            # the user's Cancel lands as ffmpeg ends

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", ok)
    burn_subs.burn(video, srt, out, cancel_check=lambda: cancelled["now"])
    assert open(out, "rb").read() == b"encoded"


def test_manual_burn_stopped_by_exit_is_not_reported_as_a_failure(tmp_path, monkeypatch):
    # App._burn_subs_for: BurnCancelled from abandon_active_burns is logged, no error dialog.
    import types
    from app import app as app_module

    posted, shown = [], []
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "o.mp4"))
    monkeypatch.setattr(app_module, "task_srt_output", lambda t: str(tmp_path / "a.srt"))
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *a, **k: shown.append(a))

    def stopped(*a, **k):
        raise burn_subs.BurnCancelled("closing")

    monkeypatch.setattr(burn_subs, "burn", stopped)
    import core._threads as threads
    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())
    fake = types.SimpleNamespace(
        log=lambda m: None, post_to_main=posted.append,
    )
    task = types.SimpleNamespace(file_path=str(tmp_path / "a.mp4"))

    app_module.App._burn_subs_for(fake, task)  # type: ignore[arg-type]

    assert posted == [] and shown == []
