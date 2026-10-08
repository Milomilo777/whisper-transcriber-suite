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


@pytest.fixture(autouse=True)
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
    assert burn_subs.is_reserved(reserved)
    thread, result = _start_burn(video, srt, reserved, placeholder=reserved)
    _wait_until(lambda: procs and _running_burn_files(folder), "ffmpeg to start")
    assert os.path.getsize(reserved) == 0

    burn_subs.abandon_active_burns()

    thread.join(20)
    assert sorted(os.listdir(folder)) == ["clip.mp4", "clip.srt"]
    assert isinstance(result.get("error"), burn_subs.BurnCancelled)
    assert not burn_subs.is_reserved(reserved)  # no longer listed as reserved


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


def test_sweep_removes_what_a_dead_run_recorded(tmp_path, _journal_in_tmp, systmp):
    folder = tmp_path / "media"
    folder.mkdir()
    partial = folder / ".burn-abc12345.mp4"
    partial.write_bytes(b"half an encode")
    placeholder = folder / "Talk-subbed.mp4"
    placeholder.write_bytes(b"")
    work = tmp_path / "systmp" / "burnsubs_xyz"
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

    partial = tmp_path / ".burn-live1234.mp4"
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
    placeholder = burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    numbered = burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    assert os.path.basename(numbered) == "Talk-subbed (2).mp4"
    plain = tmp_path / "Talk.mp4"
    plain.write_bytes(b"video")
    result = tmp_path / "Other-subbed.mp4"
    result.write_bytes(b"burned")
    user_file = tmp_path / "Mine-subbed.mp4"        # not produced by this run of the app
    user_file.write_bytes(b"user made it")
    monkeypatch.setattr(burn_subs, "_produced", {burn_subs._output_key(str(result))})

    assert watcher.watch_skip_reason(str(temp))
    assert watcher.watch_skip_reason(placeholder)
    assert watcher.watch_skip_reason(numbered)
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


# -- review round 2 ------------------------------------------------------------------------

def test_a_user_file_named_subbed_is_never_skipped_by_the_watcher(tmp_path):
    # A copy still at 0 bytes when its create event fires, then filled: both
    # moments are a new file, because the app never reserved this path.
    copied = tmp_path / "lecture-subbed.mp4"
    copied.write_bytes(b"")
    assert watcher.watch_skip_reason(str(copied)) == ""
    copied.write_bytes(b"x" * 10)
    assert watcher.watch_skip_reason(str(copied)) == ""


def test_a_placeholder_is_listed_as_reserved_until_released(tmp_path):
    path = burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    assert burn_subs.is_reserved(path) and watcher.watch_skip_reason(path)
    burn_subs.release_reserved_path(path)
    assert not burn_subs.is_reserved(path) and not os.path.exists(path)
    assert watcher.watch_skip_reason(path) == ""


def test_the_name_is_reserved_before_the_file_exists(tmp_path, monkeypatch):
    # The watcher's create event can fire the instant the file appears.
    seen = []
    real_open = os.open

    def spy(path, flags, *a, **k):
        seen.append(burn_subs.is_reserved(path))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(burn_subs.os, "open", spy)
    burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    assert seen == [True]


def test_a_second_job_with_the_same_name_does_not_unreserve_the_first(tmp_path):
    first = burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    second = burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    assert first != second
    assert burn_subs.is_reserved(first) and burn_subs.is_reserved(second)
    # A name taken by a file the app did not reserve is never listed.
    taken = tmp_path / "Other-subbed.mp4"
    taken.write_bytes(b"user's own")
    got = burn_subs.reserve_output_path(str(taken))
    assert got != str(taken) and not burn_subs.is_reserved(str(taken))


def test_a_finished_burn_is_no_longer_a_placeholder_but_stays_the_apps_output(tmp_path, monkeypatch):
    video, srt, out = _files(tmp_path)
    reserved = burn_subs.reserve_output_path(out)

    def ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"encoded")

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", ok)
    burn_subs.burn(video, srt, reserved, placeholder=reserved)
    assert not burn_subs.is_reserved(reserved)
    assert burn_subs.is_own_output(reserved) and watcher.watch_skip_reason(reserved)


# exit ----------------------------------------------------------------------------------

class _FakeProc:
    """Stands in for an ffmpeg Popen whose wait() uses up its whole timeout."""

    def __init__(self):
        self.pid = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        time.sleep(timeout or 0)
        raise subprocess.TimeoutExpired("ffmpeg", timeout)


def _register(tmp_path, systmp, *, proc=None, n=0):
    """A running burn as the registry sees it, with real leftover files."""
    folder = tmp_path / f"media{n}"
    folder.mkdir(exist_ok=True)
    work = os.path.join(systmp, f"burnsubs_run{n}")
    os.makedirs(work)
    open(os.path.join(work, "subs.srt"), "w").write("1")
    entry = burn_subs._ActiveBurn(work, "")
    entry.tmp_out = str(folder / f".burn-abcd123{n}.mp4")
    open(entry.tmp_out, "wb").write(b"partial")
    entry.proc = proc
    burn_subs._journal_write(entry)
    burn_subs._active.append(entry)
    return entry


@pytest.fixture
def no_active(monkeypatch):
    monkeypatch.setattr(burn_subs, "_active", [])


def test_exit_kills_every_burn_first_then_waits_once(tmp_path, systmp, monkeypatch, no_active):
    events = []
    monkeypatch.setattr(burn_subs, "kill_process_tree", lambda p, **k: events.append("kill"))
    procs = [_FakeProc() for _ in range(3)]
    for i, p in enumerate(procs):
        _register(tmp_path, systmp, proc=p, n=i)
    real_wait = _FakeProc.wait

    def spy_wait(self, timeout=None):
        events.append("wait")
        return real_wait(self, timeout)

    monkeypatch.setattr(_FakeProc, "wait", spy_wait)

    start = time.monotonic()
    assert burn_subs.abandon_active_burns(patience=1.0) == 3
    elapsed = time.monotonic() - start

    assert events[:3] == ["kill"] * 3          # all killed before the first wait
    assert elapsed < 2.5                       # one shared deadline, not 3 x 1 s
    assert os.listdir(systmp) == []


def test_exit_keeps_the_journal_while_a_partial_cannot_be_removed(tmp_path, systmp, monkeypatch, no_active, _journal_in_tmp):
    entry = _register(tmp_path, systmp, proc=_FakeProc())
    monkeypatch.setattr(burn_subs, "kill_process_tree", lambda p, **k: None)
    real_unlink = os.unlink

    def locked(path, *a, **k):
        if os.path.basename(str(path)).startswith(".burn-"):
            raise PermissionError(13, "held open", str(path))
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(burn_subs.os, "unlink", locked)

    burn_subs.abandon_active_burns(patience=0.3)

    assert os.path.exists(entry.tmp_out)
    assert len(os.listdir(_journal_in_tmp)) == 1       # the next start still finds it


def test_exit_keeps_the_journal_of_a_burn_whose_ffmpeg_has_not_started(tmp_path, systmp, no_active, _journal_in_tmp):
    entry = _register(tmp_path, systmp, proc=None)

    burn_subs.abandon_active_burns(patience=0.3)

    assert entry.abandoned.is_set()
    assert not os.path.exists(entry.tmp_out)            # what exists is removed
    assert len(os.listdir(_journal_in_tmp)) == 1        # but its thread is not accounted for


def test_an_ffmpeg_that_starts_while_the_app_closes_is_killed(tmp_path, monkeypatch, _journal_in_tmp):
    video, srt, out = _files(tmp_path)
    folder = os.path.dirname(out)
    reached, go = threading.Event(), threading.Event()
    spawned: list = []

    def late(cmd, **kw):
        # ffmpeg starts only after abandon_active_burns already ran.
        reached.set()
        assert go.wait(20)
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        spawned.append(proc)
        kw["on_process"](proc)
        try:
            proc.wait(15)
        finally:
            if proc.poll() is None:
                proc.kill()
        if kw["cancel_check"]():
            raise burn_subs.BurnCancelled("closing")

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", late)
    thread, result = _start_burn(video, srt, out)
    assert reached.wait(20)
    assert burn_subs.abandon_active_burns() == 1        # ffmpeg does not exist yet
    go.set()
    thread.join(30)

    assert not thread.is_alive()
    assert isinstance(result.get("error"), burn_subs.BurnCancelled)
    assert spawned[0].poll() is not None and spawned[0].returncode != 0   # killed, not finished
    assert sorted(os.listdir(folder)) == ["clip.mp4", "clip.srt"]
    assert os.listdir(_journal_in_tmp) == []            # its own cleanup finished the job


def test_closing_before_ffmpeg_starts_ends_as_a_cancel_not_an_error(tmp_path, monkeypatch, _journal_in_tmp):
    procs = _hanging_ffmpeg(monkeypatch)
    video, srt, out = _files(tmp_path)
    folder = os.path.dirname(out)
    inner = burn_subs._run_ffmpeg
    reached, go = threading.Event(), threading.Event()

    def late(cmd, **kw):
        reached.set()
        assert go.wait(20)
        return inner(cmd, **kw)       # its work folder is gone by now

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", late)
    thread, result = _start_burn(video, srt, out)
    assert reached.wait(20)
    burn_subs.abandon_active_burns()
    go.set()
    thread.join(30)

    assert isinstance(result.get("error"), burn_subs.BurnCancelled)
    assert all(p.poll() is not None for p in procs)
    assert sorted(os.listdir(folder)) == ["clip.mp4", "clip.srt"]
    assert os.listdir(_journal_in_tmp) == []            # its own cleanup finished the job


def test_no_burn_starts_after_the_app_began_closing(tmp_path, monkeypatch):
    video, srt, out = _files(tmp_path)
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda *a, **k: pytest.fail("ffmpeg started"))
    burn_subs.abandon_active_burns()
    with pytest.raises(burn_subs.BurnCancelled):
        burn_subs.burn(video, srt, out)
    assert sorted(os.listdir(os.path.dirname(out))) == ["clip.mp4", "clip.srt"]


# a hostile or damaged journal ---------------------------------------------------------------

def _sweep_with(journal, **fields):
    _record(journal, pid=_dead_pid(), pid_started=1.0, **fields)
    return burn_subs.sweep_stale_burns()


def test_sweep_ignores_a_work_folder_outside_the_temp_folder(tmp_path, _journal_in_tmp):
    victim = tmp_path / "Documents" / "burnsubs_projects"
    victim.mkdir(parents=True)
    (victim / "thesis.docx").write_bytes(b"precious")
    assert _sweep_with(_journal_in_tmp, tmp_dir=str(victim), tmp_out="", placeholder="") == []
    assert (victim / "thesis.docx").read_bytes() == b"precious"


def test_sweep_never_removes_a_temp_folder_holding_anything_else(tmp_path, systmp, _journal_in_tmp):
    work = tmp_path / "systmp" / "burnsubs_mine"
    work.mkdir()
    (work / "subs.srt").write_text("1", encoding="utf-8")
    (work / "important.txt").write_text("keep", encoding="utf-8")
    assert _sweep_with(_journal_in_tmp, tmp_dir=str(work), tmp_out="", placeholder="") == []
    assert (work / "important.txt").exists()


def test_sweep_ignores_a_partial_that_only_looks_like_one(tmp_path, _journal_in_tmp):
    docs = tmp_path / "Documents"
    docs.mkdir()
    for name in (".burn-notes.mp4", ".burn-abc12345.mp4.bak", ".burn-ABCDEFGH.mp4"):
        (docs / name).write_bytes(b"precious")
    for name in (".burn-notes.mp4", ".burn-abc12345.mp4.bak", ".burn-ABCDEFGH.mp4"):
        assert _sweep_with(_journal_in_tmp, tmp_dir="", tmp_out=str(docs / name), placeholder="") == []
        assert (docs / name).read_bytes() == b"precious"


def test_sweep_ignores_relative_paths(tmp_path, systmp, _journal_in_tmp, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".burn-abcd1234.mp4").write_bytes(b"x")
    (tmp_path / "Talk-subbed.mp4").write_bytes(b"")
    assert _sweep_with(_journal_in_tmp, tmp_dir="", tmp_out=".burn-abcd1234.mp4",
                       placeholder="Talk-subbed.mp4") == []
    assert (tmp_path / ".burn-abcd1234.mp4").exists() and (tmp_path / "Talk-subbed.mp4").exists()


def test_sweep_removes_only_an_empty_subbed_video_placeholder(tmp_path, _journal_in_tmp):
    docs = tmp_path / "Documents"
    docs.mkdir()
    note = docs / "my_empty_note.txt"
    note.write_bytes(b"")
    renamed = docs / "empty.mp4"          # empty, but not named like a reservation
    renamed.write_bytes(b"")
    for victim in (note, renamed):
        assert _sweep_with(_journal_in_tmp, tmp_dir="", tmp_out="", placeholder=str(victim)) == []
        assert victim.exists()


def test_sweep_does_not_follow_links(tmp_path, systmp, _journal_in_tmp):
    target_dir = tmp_path / "Documents"
    target_dir.mkdir()
    (target_dir / "thesis.docx").write_bytes(b"precious")
    link_dir = tmp_path / "systmp" / "burnsubs_link"
    target_file = target_dir / "real.mp4"
    target_file.write_bytes(b"precious")
    link_file = tmp_path / ".burn-abcd1234.mp4"
    try:
        os.symlink(target_dir, link_dir, target_is_directory=True)
        os.symlink(target_file, link_file)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    assert _sweep_with(_journal_in_tmp, tmp_dir=str(link_dir), tmp_out=str(link_file), placeholder="") == []
    assert (target_dir / "thesis.docx").exists() and target_file.exists()


def test_sweep_survives_a_record_with_wrong_types(tmp_path, _journal_in_tmp):
    assert _sweep_with(_journal_in_tmp, tmp_dir=5, tmp_out=["x"], placeholder={"a": 1}) == []


# new-file permissions ----------------------------------------------------------------------------

def test_the_burn_temp_is_created_with_the_normal_new_file_mode(tmp_path, monkeypatch):
    modes = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **k):
        modes.append(mode)
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(burn_subs.os, "open", spy)
    path = burn_subs._create_burn_temp(str(tmp_path), ".mp4")
    assert modes == [0o666]                    # the umask then gives the usual 0644
    assert burn_subs._BURN_TEMP_NAME_RE.match(os.path.basename(path))
    if os.name != "nt":
        mask = os.umask(0)
        os.umask(mask)
        assert os.stat(path).st_mode & 0o777 == 0o666 & ~mask


def test_the_burn_temp_keeps_the_output_extension_in_any_case(tmp_path):
    for ext in (".mp4", ".MP4", ""):
        path = burn_subs._create_burn_temp(str(tmp_path), ext)
        assert os.path.splitext(path)[1] == ext
        assert burn_subs._is_burn_partial(path)


def test_a_reserved_placeholder_is_not_created_executable(tmp_path, monkeypatch):
    modes = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **k):
        modes.append(mode)
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(burn_subs.os, "open", spy)
    burn_subs.reserve_output_path(str(tmp_path / "Talk-subbed.mp4"))
    assert modes == [0o666]


# -- review round 3 ------------------------------------------------------------------------

def test_closing_the_app_does_not_leak_into_the_next_test_part_one():
    # Pair of tests: the closing flag is process-wide and one-way, and the
    # autouse fixture in tests/conftest.py must reset it between tests.
    burn_subs.abandon_active_burns()
    assert burn_subs._closing.is_set()


def test_closing_the_app_does_not_leak_into_the_next_test_part_two(tmp_path, monkeypatch):
    assert not burn_subs._closing.is_set()
    video, srt, out = _files(tmp_path)
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda cmd, **kw: open(cmd[-1], "wb").write(b"x"))
    burn_subs.burn(video, srt, out)
    assert os.path.getsize(out) == 1


def test_sweep_keeps_the_record_while_a_vetted_partial_cannot_be_removed(tmp_path, monkeypatch, _journal_in_tmp):
    partial = tmp_path / ".burn-abcd1234.mp4"
    partial.write_bytes(b"held open")
    record = _record(_journal_in_tmp, pid=_dead_pid(), pid_started=1.0, tmp_dir="",
                     tmp_out=str(partial), placeholder="")
    real_unlink = os.unlink

    def locked(path, *a, **k):
        if os.path.basename(str(path)).startswith(".burn-"):
            raise PermissionError(13, "held open", str(path))
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(burn_subs.os, "unlink", locked)
    assert burn_subs.sweep_stale_burns() == []
    assert partial.exists() and record.exists()          # kept for the next start

    monkeypatch.setattr(burn_subs.os, "unlink", real_unlink)
    assert burn_subs.sweep_stale_burns() == [str(partial)]  # released: now it goes
    assert not partial.exists() and not record.exists()


@pytest.mark.parametrize("ext", [".mp4", ".MP4", "", ".mp4_old", ".verylongext", ".视频", ".a b", "mp4", "."])
def test_every_burn_temp_the_module_writes_is_one_it_cleans_up(tmp_path, ext):
    path = burn_subs._create_burn_temp(str(tmp_path), ext)
    assert burn_subs._BURN_TEMP_NAME_RE.match(os.path.basename(path))
    assert burn_subs._is_burn_partial(path)
    assert burn_subs._remove_leftovers("", path, "") == [path]


def test_the_output_key_is_the_same_for_composed_and_decomposed_names(tmp_path):
    composed = str(tmp_path / "\u0622\u0645\u0627\u062f\u0647-subbed.mp4")
    decomposed = str(tmp_path / "\u0627\u0653\u0645\u0627\u062f\u0647-subbed.mp4")
    assert composed != decomposed
    assert burn_subs._output_key(composed) == burn_subs._output_key(decomposed)
    reserved = burn_subs.reserve_output_path(composed)
    assert burn_subs.is_reserved(decomposed)
    assert watcher.watch_skip_reason(decomposed)
    assert burn_subs.is_reserved(reserved)


def test_a_burn_that_notices_the_close_before_its_temp_exists_creates_nothing(tmp_path, monkeypatch, _journal_in_tmp):
    video, srt, out = _files(tmp_path)
    real_prepare = burn_subs._prepare_srt

    def prepare_then_close(srt_path, safe):
        font = real_prepare(srt_path, safe)
        burn_subs.abandon_active_burns()      # the app closes right here
        return font

    monkeypatch.setattr(burn_subs, "_prepare_srt", prepare_then_close)
    monkeypatch.setattr(burn_subs, "_create_burn_temp", lambda *a, **k: pytest.fail("temp created"))
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda *a, **k: pytest.fail("ffmpeg started"))
    with pytest.raises(burn_subs.BurnCancelled):
        burn_subs.burn(video, srt, out)
    assert sorted(os.listdir(os.path.dirname(out))) == ["clip.mp4", "clip.srt"]
    assert not os.path.exists(_journal_in_tmp) or os.listdir(_journal_in_tmp) == []
