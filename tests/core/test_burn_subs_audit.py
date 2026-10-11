import pytest
import os
import json
import time

import core.burn_subs as burn_subs
from core.burn_subs import (
    is_burn_temp, burn_timeout, escape_srt_markup, probe_duration, probe_media,
    release_reserved_path, reserve_output_path, _ActiveBurn
)

def test_is_burn_temp():
    assert is_burn_temp(".burn-abc.mp4") is True
    assert is_burn_temp("/path/to/.burn-xyz.mkv") is True
    assert is_burn_temp("burn-not-hidden.mp4") is False
    assert is_burn_temp(".notburn-xyz.mp4") is False
    assert is_burn_temp("") is False

def test_burn_timeout():
    assert burn_timeout(0.0) == 3600.0
    assert burn_timeout(100.0) == 3600.0
    assert burn_timeout(2000.0) == 6000.0
    assert burn_timeout(-10.0) == 3600.0

def test_escape_srt_markup():
    assert escape_srt_markup("hello <b>world</b>") == "hello <\u2060b>world<\u2060/b>"
    assert escape_srt_markup("no markup") == "no markup"

def test_probe_media(tmp_path, monkeypatch):
    def mock_run(*args, **kwargs):
        class MockResult:
            returncode = 0
            stdout = json.dumps({"format": {"duration": "10.5"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio", "codec_name": "aac"}]}).encode()
        return MockResult()
    monkeypatch.setattr(burn_subs.subprocess, "run", mock_run)
    info = probe_media("fake.mp4")
    assert info.duration == 10.5
    assert info.has_video is True
    assert info.audio_codec == "aac"

def test_probe_duration(tmp_path, monkeypatch):
    def mock_run(*args, **kwargs):
        class MockResult:
            returncode = 0
            stdout = json.dumps({"format": {"duration": "12.5"}}).encode()
        return MockResult()
    monkeypatch.setattr(burn_subs.subprocess, "run", mock_run)
    assert probe_duration("fake.mp4") == 12.5

def test_is_own_output(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")

    assert burn_subs.is_own_output(out) is False

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda *a, **kw: open(a[0][-1], "w").close())

    burn_subs.burn(str(video), str(srt), out)
    assert burn_subs.is_own_output(out) is True
    assert burn_subs.is_own_output(str(tmp_path / "other.mp4")) is False

def test_reserve_and_release_output_path(tmp_path):
    path = str(tmp_path / "test.mp4")
    assert not os.path.exists(path)
    reserved = reserve_output_path(path)
    assert reserved == path
    assert os.path.exists(path)
    assert burn_subs.is_reserved(path) is True

    release_reserved_path(path)
    assert not os.path.exists(path)
    assert burn_subs.is_reserved(path) is False

def test_abandon_active_burns(tmp_path, monkeypatch):
    tmp_dir = str(tmp_path / "burnsubs_x")
    os.makedirs(tmp_dir)
    open(os.path.join(tmp_dir, "subs.srt"), "w").close()
    entry = _ActiveBurn(tmp_dir, "")

    class FakeProc:
        killed = False
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): pass
        def poll(self): return 0
    proc = FakeProc()
    entry.proc = proc

    burn_subs._active.append(entry)

    monkeypatch.setattr("core.burn_subs.kill_process_tree", lambda p, force: setattr(p, "killed", True))
    monkeypatch.setattr(burn_subs.tempfile, "gettempdir", lambda: str(tmp_path))

    try:
        burn_subs.abandon_active_burns()
        assert burn_subs._closing.is_set()
        assert proc.killed is True
        assert not os.path.exists(tmp_dir)
    finally:
        burn_subs._closing.clear()
        if entry in burn_subs._active:
            burn_subs._active.remove(entry)

def test_sweep_stale_burns(tmp_path, monkeypatch):
    journal_dir = str(tmp_path / "burnsubs_journal")
    monkeypatch.setattr(burn_subs, "_journal_dir", lambda: journal_dir)
    os.makedirs(journal_dir)

    work_dir = str(tmp_path / "burnsubs_stale")
    os.makedirs(work_dir)
    open(os.path.join(work_dir, "subs.srt"), "w").close()

    partial = str(tmp_path / ".burn-abcdefgh.mp4")
    open(partial, "w").close()

    journal_file = os.path.join(journal_dir, "999999-123.json")
    with open(journal_file, "w") as f:
        json.dump({
            "pid": 999999,
            "pid_started": 123.0,
            "tmp_dir": work_dir,
            "tmp_out": partial,
            "placeholder": ""
        }, f)

    monkeypatch.setattr(burn_subs, "_record_owner_running", lambda r: False)
    monkeypatch.setattr(burn_subs.tempfile, "gettempdir", lambda: str(tmp_path))

    removed = burn_subs.sweep_stale_burns()
    assert partial in removed
    assert work_dir in removed
    assert not os.path.exists(partial)
    assert not os.path.exists(work_dir)
    assert not os.path.exists(journal_file)

def test_placeholder_leak_after_salvage(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")

    out = burn_subs.reserve_output_path(str(tmp_path / "v-subbed.mp4"))

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def mock_run_ffmpeg(*args, **kwargs):
        with open(args[0][-1], "w") as f:
            f.write("finished_work")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", mock_run_ffmpeg)

    real_replace = os.replace
    def mock_replace(src, dst):
        if str(dst) == out:
            raise PermissionError("Locked")
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)

    t = [0.0]
    def mock_monotonic():
        t[0] += 0.2
        return t[0]
    monkeypatch.setattr(time, "monotonic", mock_monotonic)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    returned_path = burn_subs.burn(str(video), str(srt), out, placeholder=out)

    assert returned_path != out
    assert (tmp_path / "v-subbed (2).mp4").read_text() == "finished_work"
    assert burn_subs.is_own_output(returned_path) is True
    assert not burn_subs.is_reserved(returned_path)
    assert not burn_subs.is_reserved(out)
    assert not os.path.exists(out)

def test_salvage_atomicity(tmp_path, monkeypatch):
    import core.burn_subs as burn_subs
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")
    (tmp_path / "out.mp4").write_bytes(b"locked")

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def mock_run_ffmpeg(*args, **kwargs):
        with open(args[0][-1], "w") as f:
            f.write("finished_work")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", mock_run_ffmpeg)

    real_replace = os.replace
    def mock_replace(src, dst):
        if str(dst) == out:
            raise PermissionError("Locked")
        assert os.path.exists(dst)
        assert os.path.getsize(dst) == 0
        assert burn_subs.is_reserved(dst) is True
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)

    import time
    t = [0.0]
    def mock_monotonic():
        t[0] += 0.2
        return t[0]
    monkeypatch.setattr(time, "monotonic", mock_monotonic)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    returned_path = burn_subs.burn(str(video), str(srt), out)
    assert returned_path != out
    assert open(returned_path, "r").read() == "finished_work"
    assert burn_subs.is_own_output(returned_path) is True
    assert burn_subs.is_reserved(returned_path) is False

def test_salvage_retry_succeeds(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def mock_run_ffmpeg(*args, **kwargs):
        with open(args[0][-1], "w") as f:
            f.write("finished_work")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", mock_run_ffmpeg)

    attempts = 0
    real_replace = os.replace
    def mock_replace(src, dst):
        nonlocal attempts
        if dst == out:
            attempts += 1
            if attempts < 3:
                raise PermissionError("Locked initially")
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)

    t = [0.0]
    def mock_monotonic():
        t[0] += 0.2
        return t[0]
    monkeypatch.setattr(time, "monotonic", mock_monotonic)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    returned_path = burn_subs.burn(str(video), str(srt), out)
    assert returned_path == out
    assert attempts == 3
    assert not os.path.exists(tmp_path / "out (2).mp4")

def test_salvage_filenotfound_propagates(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def mock_run_ffmpeg(*args, **kwargs):
        os.unlink(args[0][-1]) # don't leave tmp_out
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", mock_run_ffmpeg)

    with pytest.raises(FileNotFoundError):
        burn_subs.burn(str(video), str(srt), out)
    assert not burn_subs.is_own_output(out)
    assert not burn_subs.is_reserved(out)

def test_salvage_both_permissionerror(tmp_path, monkeypatch):
    import core.burn_subs as burn_subs
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")

    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type("MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def mock_run_ffmpeg(*args, **kwargs):
        with open(args[0][-1], "w") as f:
            f.write("finished_work")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", mock_run_ffmpeg)

    def mock_replace(src, dst):
        raise PermissionError("Always locked")
    monkeypatch.setattr(os, "replace", mock_replace)

    import time
    t = [0.0]
    def mock_monotonic():
        t[0] += 0.2
        return t[0]
    monkeypatch.setattr(time, "monotonic", mock_monotonic)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    with pytest.raises(PermissionError):
        burn_subs.burn(str(video), str(srt), out)
    assert not os.path.exists(tmp_path / "out (2).mp4")
    assert burn_subs.is_own_output(out) is False
    assert burn_subs.is_reserved(out) is False
    partials = [f for f in os.listdir(tmp_path) if f.startswith(".burn-")]
    assert len(partials) == 0


def test_salvage_reserve_failure_clears_produced(tmp_path, monkeypatch):
    """Destination locked AND no salvage name can be reserved: the error propagates and no bookkeeping leaks."""
    video = tmp_path / "v.mp4"
    srt = tmp_path / "v.srt"
    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")
    out = str(tmp_path / "out.mp4")
    monkeypatch.setattr("core.burn_subs.probe_media", lambda p, timeout=60: type(
        "MediaInfo", (), {"duration": 1.0, "has_video": True, "audio_codec": "aac"})())
    monkeypatch.setattr("core.burn_subs.bundled_binary", lambda n: "echo")

    def fake_ffmpeg(*args, **kwargs):
        with open(args[0][-1], "w") as f:
            f.write("finished_work")
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", fake_ffmpeg)
    real_replace = os.replace

    def locked_replace(src, dst):
        if os.path.abspath(dst) == os.path.abspath(out):
            raise PermissionError("locked")
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", locked_replace)

    def no_reserve(*a, **k):
        raise PermissionError("cannot reserve")
    monkeypatch.setattr(burn_subs, "reserve_output_path", no_reserve)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        burn_subs.burn(str(video), str(srt), out)
    assert not burn_subs.is_own_output(out)
    assert not burn_subs.is_reserved(out)
