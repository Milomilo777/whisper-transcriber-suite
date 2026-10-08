"""Server job handling review findings (card C266-A1).

1. a cloud job that fails part-way keeps its ``.partial.srt`` (paid text),
2. a download that wrote no file never "transcribes" the folder marker,
3. a second server never purges another live server's job folders,
4. outputs are archived and the history row written BEFORE a job reads
   "finished", and a finishing job cannot be evicted,
5. a finished job's server-owned input media is deleted, a user's own file
   never.

Fakes only: no network, no real yt-dlp, no real engine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from core import server
from core.backends.base import PartialResultError
from core.server import jobs as J
from core.server.jobs import (
    STATUS_ERROR,
    STATUS_FINISHED,
    DownloadLimits,
    JobManager,
)


def _manager(tmp_path, transcribe=None, **kw):
    kw.setdefault("record_history", False)
    return JobManager(transcribe or (lambda *a, **k: None),
                      jobs_root=str(tmp_path / "server_jobs"), **kw)


def _wait(mgr, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        job = mgr.get(job_id)
        if job is not None and job.status in (
                STATUS_FINISHED, STATUS_ERROR, "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _wait_idle(mgr, job_id, timeout=10.0):
    """Terminal AND the worker has finished its clean-up for the job."""
    job = _wait(mgr, job_id, timeout)
    time.sleep(0.3)
    return job


def _partial_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    """What core.transcriber does when a paid cloud run dies part-way."""
    path = os.path.splitext(task.file_path)[0] + ".partial.srt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:01,000\npaid text\n")
    raise PartialResultError("cloud engine failed (chunks 1-3 were kept)",
                             [{"start": 0.0, "end": 1.0, "text": "paid text"}])


def _srt_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    out = os.path.splitext(task.file_path)[0] + ".srt"
    with open(out, "w", encoding="utf-8") as f:
        f.write("1")
    task.output_paths = [out]


# --- 1: a failed cloud job keeps its partial --------------------------------

def test_failed_job_keeps_and_exposes_its_partial(tmp_path):
    mgr = _manager(tmp_path, _partial_transcribe)
    mgr.start()
    try:
        job_id = mgr.submit_upload("talk.wav", b"RIFF0000", ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert job.status == STATUS_ERROR
    assert [k for k, _ in job.outputs] == [J.PARTIAL_OUTPUT_KEY]
    path = mgr.output_path(job_id, J.PARTIAL_OUTPUT_KEY)
    assert path and os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        assert "paid text" in f.read()
    assert job.public_dict()["outputs"] == [
        {"fmt": J.PARTIAL_OUTPUT_KEY, "name": "talk.partial.srt"}]
    # A durable copy outside the temporary job folder.
    kept = tmp_path / "server_outputs" / job_id[:12] / "talk.partial.srt"
    assert kept.is_file()


def test_partial_is_not_served_as_a_complete_srt(tmp_path):
    mgr = _manager(tmp_path, _partial_transcribe)
    mgr.start()
    try:
        job_id = mgr.submit_upload("talk.wav", b"RIFF0000", ["srt"])
        _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert mgr.output_path(job_id, "srt") is None


def test_failed_job_without_partial_still_reclaims_its_folder(tmp_path):
    def boom(task, *a, **k):
        raise RuntimeError("engine down")

    mgr = _manager(tmp_path, boom)
    mgr.start()
    try:
        job_id = mgr.submit_upload("talk.wav", b"RIFF0000", ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert job.status == STATUS_ERROR and not job.outputs
    assert not os.path.isdir(job.work_dir)


def test_purge_rescues_a_partial_before_deleting_the_folder(tmp_path):
    root = tmp_path / "server_jobs"
    old = root / ("a" * 32)
    old.mkdir(parents=True)
    (old / "x.partial.srt").write_text("paid", encoding="utf-8")
    (old / "x.wav").write_bytes(b"x")
    (old / J._JOB_DIR_MARKER).write_text(
        json.dumps({"v": 1, "pid": _dead_pid(), "started": 1.0,
                    "instance": "gone"}))
    long_ago = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
    os.utime(old, (long_ago, long_ago))
    mgr = _manager(tmp_path)
    mgr.start()
    try:
        assert not old.exists()
        assert (tmp_path / "server_outputs" / ("a" * 12)
                / "x.partial.srt").read_text(encoding="utf-8") == "paid"
    finally:
        mgr.stop()


def test_purge_keeps_a_folder_whose_partial_cannot_be_copied(
        tmp_path, monkeypatch):
    root = tmp_path / "server_jobs"
    old = root / ("a" * 32)
    old.mkdir(parents=True)
    (old / "x.partial.srt").write_text("paid", encoding="utf-8")
    (old / "x.wav").write_bytes(b"x")  # the media the partial belongs to
    (old / J._JOB_DIR_MARKER).write_text(
        json.dumps({"v": 1, "pid": _dead_pid(), "started": 1.0,
                    "instance": "gone"}))
    long_ago = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
    os.utime(old, (long_ago, long_ago))

    def no_copy(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(J.shutil, "copy2", no_copy)
    mgr = _manager(tmp_path)
    mgr.start()
    try:
        assert (old / "x.partial.srt").read_text(encoding="utf-8") == "paid"
    finally:
        mgr.stop()


def test_eviction_never_deletes_an_unsaved_partial(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, max_jobs=1)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "", "x.wav")
    part = os.path.join(job.work_dir, "x.partial.srt")
    with open(part, "w", encoding="utf-8") as f:
        f.write("paid")
    job.media_path = os.path.join(job.work_dir, "x.wav")
    job.outputs = [(J.PARTIAL_OUTPUT_KEY, part)]
    job.status = STATUS_ERROR

    def no_copy(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(J.shutil, "copy2", no_copy)
    with mgr._lock:
        mgr._evict_locked()
    assert mgr.get(job.job_id) is None
    assert os.path.isfile(part)


# --- 2: the marker is not media ---------------------------------------------

class _FakePopen:
    stdout_text = ""

    def __init__(self, cmd, **kwargs):
        self.pid = 4242
        self.returncode = 0

    def communicate(self, timeout=None):
        return type(self).stdout_text, ""

    def poll(self):
        return None


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    monkeypatch.setattr(_FakePopen, "stdout_text", "")
    monkeypatch.setattr(server.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])


def test_download_with_no_file_never_picks_the_marker(tmp_path, fake_yt_dlp):
    (tmp_path / J._JOB_DIR_MARKER).write_bytes(b"")
    _FakePopen.stdout_text = (
        "[download] File is larger than max-filesize. Aborting.\n")
    limits = DownloadLimits(cancelled=lambda: False, max_bytes=10)
    with pytest.raises(RuntimeError, match="download limit"):
        server._download_url("https://example.com/v", str(tmp_path), limits)


def test_download_with_no_file_and_no_limit_message(tmp_path, fake_yt_dlp):
    (tmp_path / J._JOB_DIR_MARKER).write_bytes(b"")
    with pytest.raises(RuntimeError, match="no file"):
        server._download_url("https://example.com/v", str(tmp_path))


def test_download_ignores_partial_empty_and_hidden_files(tmp_path, fake_yt_dlp):
    (tmp_path / J._JOB_DIR_MARKER).write_bytes(b"")
    (tmp_path / "clip.mp4.part").write_bytes(b"half")
    (tmp_path / "clip.f137.mp4.part-Frag3").write_bytes(b"half")
    (tmp_path / "clip.mp4.ytdl").write_bytes(b"{}")
    (tmp_path / "empty.mp4").write_bytes(b"")
    with pytest.raises(RuntimeError):
        server._download_url("https://example.com/v", str(tmp_path))
    real = tmp_path / "real.mp4"
    real.write_bytes(b"media")
    got = server._download_url("https://example.com/v", str(tmp_path))
    assert os.path.basename(got) == "real.mp4"


# --- 3: a second server never purges a live server's folders -----------------

def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _age(path, factor=2):
    long_ago = time.time() - factor * J._STALE_JOB_DIR_AGE_S
    os.utime(path, (long_ago, long_ago))


def test_second_server_leaves_the_first_servers_jobs(tmp_path):
    a = _manager(tmp_path)  # never started: a job just sits queued
    job_id = a.submit_upload("lecture.wav", b"RIFF", ["srt"])
    job = a.get(job_id)
    _age(job.work_dir)
    b = _manager(tmp_path)
    b.start()
    try:
        assert os.path.isdir(job.work_dir)
        assert os.path.isfile(job.media_path)
    finally:
        b.stop()


def test_purge_leaves_a_folder_owned_by_a_live_other_process(tmp_path):
    import psutil

    root = tmp_path / "server_jobs"
    d = root / ("a" * 32)
    d.mkdir(parents=True)
    parent = psutil.Process(os.getppid())
    (d / J._JOB_DIR_MARKER).write_text(json.dumps(
        {"v": 1, "pid": parent.pid, "started": parent.create_time(),
         "instance": "other"}))
    _age(d)
    m = _manager(tmp_path)
    m.start()
    try:
        assert d.exists()
    finally:
        m.stop()


def test_purge_removes_a_folder_whose_pid_was_reused(tmp_path):
    import psutil

    root = tmp_path / "server_jobs"
    d = root / ("a" * 32)
    d.mkdir(parents=True)
    parent = psutil.Process(os.getppid())
    (d / J._JOB_DIR_MARKER).write_text(json.dumps(
        {"v": 1, "pid": parent.pid, "started": parent.create_time() - 1000,
         "instance": "other"}))
    _age(d)
    m = _manager(tmp_path)
    m.start()
    try:
        assert not d.exists()
    finally:
        m.stop()


def test_purge_removes_a_stopped_servers_old_folder_in_this_process(tmp_path):
    a = _manager(tmp_path)
    job_id = a.submit_upload("lecture.wav", b"RIFF", ["srt"])
    job = a.get(job_id)
    job.status = STATUS_FINISHED  # a finished job's folder outlives stop()
    work_dir = job.work_dir
    a.stop()
    assert os.path.isdir(work_dir)
    _age(work_dir)
    b = _manager(tmp_path)
    b.start()
    try:
        assert not os.path.isdir(work_dir)
    finally:
        b.stop()


def test_purge_gives_an_ownerless_legacy_marker_a_long_grace(tmp_path):
    root = tmp_path / "server_jobs"
    young = root / ("a" * 32)
    ancient = root / ("b" * 32)
    for d in (young, ancient):
        d.mkdir(parents=True)
        (d / J._JOB_DIR_MARKER).write_bytes(b"")  # an older build's marker
    _age(young)  # 12 h: past the plain limit, short of the legacy grace
    _age(ancient, factor=J._LEGACY_JOB_DIR_AGE_S / J._STALE_JOB_DIR_AGE_S + 1)
    m = _manager(tmp_path)
    m.start()
    try:
        assert young.exists()
        assert not ancient.exists()
    finally:
        m.stop()


def test_new_job_marker_names_its_owner(tmp_path):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "", "x.wav")
    with open(os.path.join(job.work_dir, J._JOB_DIR_MARKER),
              encoding="utf-8") as f:
        data = json.load(f)
    assert data["pid"] == os.getpid()
    assert data["instance"] == mgr._instance_id


# --- 4: persist first, then "finished"; a finishing job is not evictable -----

def test_outputs_are_archived_and_history_written_before_finished(tmp_path):
    events: list[str] = []

    class _Watch(JobManager):
        def _set_status(self, job, status):
            if status == STATUS_FINISHED:
                events.append("finished")
            super()._set_status(job, status)

        def _archive_outputs(self, job):
            events.append("archive")
            return super()._archive_outputs(job)

        def _finish_history(self, *a, **k):
            events.append("history")
            return super()._finish_history(*a, **k)

    mgr = _Watch(_srt_transcribe, jobs_root=str(tmp_path / "server_jobs"),
                 record_history=False)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert "finished" in events
    assert events.index("archive") < events.index("finished")
    assert events.index("history") < events.index("finished")
    assert (tmp_path / "server_outputs" / job_id[:12] / "a.srt").is_file()


def test_a_finishing_job_cannot_be_evicted(tmp_path):
    seen: dict = {}

    class _Evicting(JobManager):
        def _archive_outputs(self, job):
            with self._lock:
                self._evict_locked()
            seen["still_there"] = self.get(job.job_id) is job
            seen["dir"] = os.path.isdir(job.work_dir)
            return super()._archive_outputs(job)

    mgr = _Evicting(_srt_transcribe, jobs_root=str(tmp_path / "server_jobs"),
                    record_history=False, max_jobs=1)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert seen == {"still_there": True, "dir": True}
    assert job.status == STATUS_FINISHED
    assert os.path.isfile(job.outputs[0][1])


# --- 5: input media of a finished job -----------------------------------------

def test_finished_upload_media_is_deleted_outputs_kept(tmp_path):
    mgr = _manager(tmp_path, _srt_transcribe)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x" * 100, ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert job.status == STATUS_FINISHED
    assert not os.path.exists(job.media_path)
    assert os.path.isfile(job.outputs[0][1])
    assert mgr.output_path(job_id, "srt") == job.outputs[0][1]


def test_downloaded_media_is_deleted_but_a_users_own_file_is_not(tmp_path):
    own = tmp_path / "my own recording.wav"
    own.write_bytes(b"precious")

    def download_own(url, dest, limits):
        return str(own)

    def download_inside(url, dest, limits):
        p = os.path.join(dest, "dl.wav")
        with open(p, "wb") as f:
            f.write(b"x")
        return p

    mgr = _manager(tmp_path, _srt_transcribe, download_fn=download_own)
    mgr.start()
    try:
        j1 = _wait_idle(mgr, mgr.submit_url("http://192.0.2.10/a.wav", ["srt"]))
        assert own.read_bytes() == b"precious"
        mgr._download = download_inside
        j2 = _wait_idle(mgr, mgr.submit_url("http://192.0.2.10/b.wav", ["srt"]))
    finally:
        mgr.stop()
    assert j1.status == STATUS_FINISHED and j2.status == STATUS_FINISHED
    assert own.exists()
    assert not os.path.exists(j2.media_path)


def test_media_delete_failure_does_not_fail_the_job(tmp_path, monkeypatch):
    real_remove = os.remove

    def locked(path, *a, **k):
        if path.endswith("a.wav"):
            raise PermissionError("in use")
        return real_remove(path, *a, **k)

    monkeypatch.setattr(J.os, "remove", locked)
    mgr = _manager(tmp_path, _srt_transcribe)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert job.status == STATUS_FINISHED
    assert os.path.isfile(job.outputs[0][1])


# =============================================================================
# Review round 2
# =============================================================================

# --- F1: only a trailing yt-dlp suffix marks an unfinished file --------------

@pytest.mark.parametrize("name", [
    "Vlog.Part-1.mp4", "talk.part-2.mp3", "my.tmp.talk.mp4",
    "Season.Temp-Edition.mkv", "x.temp.mp4",  # alone: may be a real title
])
def test_titles_that_contain_part_words_are_media(tmp_path, name):
    (tmp_path / name).write_bytes(b"media")
    assert server._is_downloaded_media(str(tmp_path), name)


@pytest.mark.parametrize("name", [
    "name.f137.mp4.part", "name.mp4.part-Frag12", "name.mp4.ytdl",
    "NAME.MP4.PART", "a.tmp", "a.mp4.temp", ".wts-job", "empty.mp4",
])
def test_unfinished_yt_dlp_files_are_not_media(tmp_path, name):
    (tmp_path / name).write_bytes(b"" if name == "empty.mp4" else b"half")
    assert not server._is_downloaded_media(str(tmp_path), name)


def test_post_processing_temp_file_is_not_media_beside_the_final_one(tmp_path):
    (tmp_path / "x.temp.mp4").write_bytes(b"half")
    (tmp_path / "x.mp4").write_bytes(b"done")
    assert not server._is_downloaded_media(str(tmp_path), "x.temp.mp4")
    assert server._is_downloaded_media(str(tmp_path), "x.mp4")


# --- F2: only the engine's own partial is rescued -----------------------------

def _outputs_files(tmp_path):
    out = tmp_path / "server_outputs"
    return [p for p in out.rglob("*") if p.is_file()] if out.exists() else []


def test_uploaded_file_named_partial_is_never_copied_to_outputs(tmp_path):
    def boom(task, *a, **k):
        raise RuntimeError("bad media")

    mgr = _manager(tmp_path, boom)
    mgr.start()
    try:
        job_id = mgr.submit_upload("big.partial.srt", b"X" * 1000, ["srt"])
        _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert _outputs_files(tmp_path) == []


def test_stop_and_discard_never_copy_an_uploaded_partial_named_file(tmp_path):
    mgr = _manager(tmp_path)  # worker not started: jobs stay queued
    queued = mgr.submit_upload("big.partial.srt", b"X" * 1000, ["srt"])
    streamed, path = mgr.submit_upload_stream("other.partial.srt", ["srt"])
    with open(path, "wb") as f:
        f.write(b"Y" * 1000)
    mgr.discard(streamed)  # an aborted streamed upload
    mgr.cancel(queued)
    mgr.stop()
    assert _outputs_files(tmp_path) == []


def test_purge_copies_only_a_partial_that_has_its_media(tmp_path):
    root = tmp_path / "server_jobs"
    owner = json.dumps({"v": 1, "pid": _dead_pid(), "started": 1.0,
                        "instance": "gone"})
    real = root / ("a" * 32)  # a run that died before the job could settle
    upload = root / ("b" * 32)  # a client file that happens to end so
    for d in (real, upload):
        d.mkdir(parents=True)
        (d / J._JOB_DIR_MARKER).write_text(owner)
    (real / "talk.wav").write_bytes(b"x")
    (real / "talk.partial.srt").write_text("paid", encoding="utf-8")
    (upload / "big.partial.srt").write_bytes(b"X" * 1000)
    for d in (real, upload):
        _age(d)  # after the files are written: they touch the folder
    mgr = _manager(tmp_path)
    mgr.start()
    try:
        assert not real.exists() and not upload.exists()
    finally:
        mgr.stop()
    assert [p.name for p in _outputs_files(tmp_path)] == ["talk.partial.srt"]


# --- F3: a damaged marker never stops the server ------------------------------

@pytest.mark.parametrize("text", [
    '{"pid": 1e999, "instance": "x"}',
    '{"pid": -5, "instance": "x"}',
    '{"pid": 99999999999999999999, "instance": "x"}',
    '{"pid": 0, "instance": "x"}',
    '{"pid": "abc", "instance": "x"}',
    '{"pid": 1, "instance": ["x"], "started": "soon"}',
    '[]', '123', 'null', '{', '', '\x00\x01',
])
def test_damaged_marker_means_unknown_owner(text):
    assert J._marker_owner_state(text) == "unknown"


def test_start_survives_a_damaged_marker(tmp_path):
    root = tmp_path / "server_jobs"
    d = root / ("a" * 32)
    d.mkdir(parents=True)
    (d / J._JOB_DIR_MARKER).write_text('{"pid": 1e999, "instance": "x"}')
    _age(d)
    mgr = _manager(tmp_path)
    mgr.start()  # must not raise
    try:
        assert d.exists()  # unknown owner: the long legacy grace applies
    finally:
        mgr.stop()


# --- F4: a failed archive copy never loses the finished transcript -----------

def _failing_copy(monkeypatch):
    def no_copy(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(J.shutil, "copy2", no_copy)


def test_failed_archive_warns_and_protects_the_outputs_folder(
        tmp_path, monkeypatch):
    _failing_copy(monkeypatch)
    mgr = _manager(tmp_path, _srt_transcribe, max_jobs=1)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"RIFF", ["srt"])
        job = _wait_idle(mgr, job_id)
        assert job.status == STATUS_FINISHED
        assert job.warning
        assert job.public_dict()["warning"] == job.warning
        # The results are protected; the (large) input is expendable.
        assert not os.path.exists(job.media_path)
        # The cap now evicts the finished job: its folder must survive.
        with mgr._lock:
            mgr._evict_locked()
        assert mgr.get(job_id) is None
        assert os.path.isfile(job.outputs[0][1])
        assert not os.path.exists(job.media_path)  # the input is let go now
        monkeypatch.undo()  # disk space is back: the next clean-up copies
        assert mgr._discard_dir(job.work_dir, job)
    finally:
        mgr.stop()
    assert not os.path.isdir(job.work_dir)
    kept = tmp_path / "server_outputs" / job_id[:12] / "a.srt"
    assert kept.is_file()


def test_purge_retries_a_failed_archive_from_the_keep_list(
        tmp_path, monkeypatch):
    root = tmp_path / "server_jobs"
    d = root / ("a" * 32)
    d.mkdir(parents=True)
    (d / J._JOB_DIR_MARKER).write_text(json.dumps(
        {"v": 1, "pid": _dead_pid(), "started": 1.0, "instance": "gone"}))
    (d / "a.srt").write_text("transcript", encoding="utf-8")
    (d / J._KEEP_FILE).write_text(json.dumps(["a.srt", "../evil.txt"]))
    _age(d)
    _failing_copy(monkeypatch)
    mgr = _manager(tmp_path)
    mgr.start()
    mgr.stop()
    assert (d / "a.srt").is_file()  # copy failed: folder kept
    monkeypatch.undo()
    mgr2 = _manager(tmp_path)
    mgr2.start()
    try:
        assert not d.exists()
    finally:
        mgr2.stop()
    assert (tmp_path / "server_outputs" / ("a" * 12) / "a.srt").read_text(
        encoding="utf-8") == "transcript"
    assert not (tmp_path / "server_outputs" / "evil.txt").exists()


def test_cancel_is_refused_once_the_job_is_settling(tmp_path):
    gate = threading.Event()
    entered = threading.Event()

    class _Slow(JobManager):
        def _archive_outputs(self, job):
            entered.set()
            gate.wait(10)
            return super()._archive_outputs(job)

    mgr = _Slow(_srt_transcribe, jobs_root=str(tmp_path / "server_jobs"),
                record_history=False)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        assert entered.wait(10)
        assert mgr.cancel(job_id) is False
        gate.set()
        job = _wait_idle(mgr, job_id)
    finally:
        gate.set()
        mgr.stop()
    assert job.status == STATUS_FINISHED and not job.cancelled


def test_media_removal_is_retried_while_the_file_is_open(tmp_path, monkeypatch):
    real_remove = os.remove
    calls = {"n": 0}

    def flaky(path, *a, **k):
        if str(path).endswith("a.wav"):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("in use")
        return real_remove(path, *a, **k)

    monkeypatch.setattr(J.os, "remove", flaky)
    mgr = _manager(tmp_path, _srt_transcribe)
    mgr.start()
    try:
        job_id = mgr.submit_upload("a.wav", b"x", ["srt"])
        job = _wait_idle(mgr, job_id)
    finally:
        mgr.stop()
    assert calls["n"] == 3
    assert not os.path.exists(job.media_path)


# =============================================================================
# Review round 3: the keep list
# =============================================================================

_PERSIAN_TITLE = "گزارش خبری بسیار طولانی امروز " * 3  # 90 characters


def _persian_outputs(work_dir, count=9):
    paths = []
    for i in range(count):
        p = os.path.join(work_dir, f"{_PERSIAN_TITLE}{i}.srt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("transcript")
        paths.append(p)
    return paths


def test_keep_list_keeps_every_long_persian_name(tmp_path):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "", "x.wav")
    paths = _persian_outputs(job.work_dir)
    mgr._write_keep_file(job, paths)
    keep = os.path.join(job.work_dir, J._KEEP_FILE)
    raw = open(keep, "rb").read()
    names = sorted(os.path.basename(p) for p in paths)
    # With ASCII escapes this list would be longer than the old read limit.
    assert len(json.dumps(names)) > 4096
    assert b"\\u" not in raw  # real UTF-8, not escapes
    assert J._read_keep_list(keep) == names


def test_purge_keeps_then_copies_long_persian_outputs(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    with mgr._lock:
        job = mgr._new_job("upload", ["srt"], "", "x.wav")
    paths = _persian_outputs(job.work_dir)
    mgr._write_keep_file(job, paths)
    d = job.work_dir
    job.status = STATUS_FINISHED  # a finished job's folder outlives stop()
    mgr.stop()  # its folder now belongs to a stopped server
    (tmp_path / "server_jobs" / job.job_id / J._JOB_DIR_MARKER).write_text(
        json.dumps({"v": 1, "pid": _dead_pid(), "started": 1.0,
                    "instance": "gone"}))
    _age(d)
    _failing_copy(monkeypatch)
    m2 = _manager(tmp_path)
    m2.start()
    m2.stop()
    assert all(os.path.isfile(p) for p in paths)  # copies failed: all kept
    monkeypatch.undo()
    m3 = _manager(tmp_path)
    m3.start()
    try:
        assert not os.path.isdir(d)
    finally:
        m3.stop()
    out = tmp_path / "server_outputs" / job.job_id[:12]
    assert sorted(p.name for p in out.iterdir()) == sorted(
        os.path.basename(p) for p in paths)


@pytest.mark.parametrize("content", [
    pytest.param(b'["a.srt", "b', id="cut-short"),
    pytest.param(b'{"a": 1}', id="not-a-list"),
    pytest.param(b"\xff\xfe\x00bad", id="not-utf8"),
    pytest.param(b'["a.srt", "' + b"x" * (2 * 1024 * 1024) + b'"]',
                 id="over-the-size-limit"),
    pytest.param(b"", id="empty"),
])
def test_unreadable_keep_list_protects_the_whole_folder(tmp_path, content):
    d = tmp_path / "server_jobs" / ("a" * 32)
    d.mkdir(parents=True)
    (d / J._JOB_DIR_MARKER).write_text(json.dumps(
        {"v": 1, "pid": _dead_pid(), "started": 1.0, "instance": "gone"}))
    (d / "a.srt").write_text("transcript", encoding="utf-8")
    (d / J._KEEP_FILE).write_bytes(content)
    _age(d)
    mgr = _manager(tmp_path)
    mgr.start()
    try:
        assert (d / "a.srt").read_text(encoding="utf-8") == "transcript"
    finally:
        mgr.stop()


def test_keep_list_is_written_before_the_history_row(tmp_path, monkeypatch):
    _failing_copy(monkeypatch)
    seen = {}

    class _Watch(JobManager):
        def _finish_history(self, db, rid, job, *a, **k):
            seen["keep"] = os.path.isfile(
                os.path.join(job.work_dir, J._KEEP_FILE))
            return super()._finish_history(db, rid, job, *a, **k)

    mgr = _Watch(_srt_transcribe, jobs_root=str(tmp_path / "server_jobs"),
                 record_history=False)
    mgr.start()
    try:
        _wait_idle(mgr, mgr.submit_upload("a.wav", b"x", ["srt"]))
    finally:
        mgr.stop()
    assert seen == {"keep": True}


def test_failed_keep_list_write_logs_the_unsaved_names(
        tmp_path, monkeypatch, caplog):
    _failing_copy(monkeypatch)

    class _BlockKeep(JobManager):
        def _archive_outputs(self, job):
            # A directory in the keep list's place makes its write fail.
            os.makedirs(os.path.join(job.work_dir, J._KEEP_FILE),
                        exist_ok=True)
            return super()._archive_outputs(job)

    mgr = _BlockKeep(_srt_transcribe, jobs_root=str(tmp_path / "server_jobs"),
                     record_history=False)
    mgr.start()
    try:
        with caplog.at_level("ERROR", logger="core.server.jobs"):
            job = _wait_idle(mgr, mgr.submit_upload("a.wav", b"x", ["srt"]))
    finally:
        mgr.stop()
    assert job.status == STATUS_FINISHED and job.warning
    assert any("a.srt" in r.getMessage() and r.levelname == "ERROR"
               for r in caplog.records)
