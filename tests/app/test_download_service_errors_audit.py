"""The message a failed yt-dlp run leaves in the queue, from a fake yt-dlp script's output."""
from __future__ import annotations

import sys
from queue import Queue
from unittest.mock import Mock

import pytest

from app.services.download_service import DownloadService


class FakeApp:
    def __init__(self):
        self.entry_file = "gui.py"
        self.download_events = Queue()
        self.app_config = {}
        self.ensure_online = lambda what: True
        self.app_state = Mock()
        self.log = Mock()

    def enqueue_transcription_from_download(self, *args, **kwargs):
        pass

    def bell(self):
        pass

    def post_to_main(self, *args, **kwargs):
        pass


class FakeTask:
    def __init__(self, **kwargs):
        self.url = "http://example.com/video"
        self.format_info = {}
        self.detected_language = "en"
        self.cancelled = False
        self.paused = False
        self.id = 1
        self.partial_paths = []
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def fake_app():
    return FakeApp()


@pytest.fixture
def service(fake_app):
    return DownloadService(fake_app)


def run_test_case(monkeypatch, tmp_path, service, fake_app, case_script_content):
    fake_dlp = tmp_path / "fake_yt_dlp.py"
    fake_dlp.write_text(case_script_content, encoding="utf-8")

    def fake_build_command(task, **kwargs):
        return [sys.executable, str(fake_dlp)]

    monkeypatch.setattr(service, "build_download_command", fake_build_command)

    task = FakeTask()
    service._media_phase(task)

    events = []
    while not fake_app.download_events.empty():
        events.append(fake_app.download_events.get())
    return events, task


@pytest.mark.parametrize("self_update", [False, True])
def test_http_403(monkeypatch, tmp_path, service, fake_app, self_update):
    # Whether yt-dlp can update itself depends on the machine (a bin/yt-dlp.exe
    # in a source checkout can); pin it, or the result follows the developer's PC.
    from core import yt_dlp_update

    monkeypatch.setattr(yt_dlp_update, "can_self_update", lambda *a, **k: self_update)
    monkeypatch.setattr(service, "_offer_yt_dlp_update", lambda reason: None)
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("ERROR: unable to download video data: HTTP Error 403: Forbidden")
sys.exit(1)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    assert "HTTP Error 403: Forbidden" in errors[0]
    # A copy that can update itself shows the "Update it" bar instead of this advice.
    assert ("video downloader in this app may be out of date" in errors[0]) is (not self_update)


def test_sign_in_bot(monkeypatch, tmp_path, service, fake_app):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("ERROR: Sign in to confirm you're not a bot")
sys.exit(1)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    assert "Sign in to confirm you're not a bot" in errors[0]
    assert "needs a logged-in session" in errors[0]


def test_geo_blocked(monkeypatch, tmp_path, service, fake_app):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("ERROR: This video is not available in your country")
sys.exit(1)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    assert "This video is not available in your country" in errors[0]


def test_private_video(monkeypatch, tmp_path, service, fake_app):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("ERROR: Private video")
sys.exit(1)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    assert "Private video" in errors[0]
    assert "needs a logged-in session" in errors[0]


def test_playlist_failed_entry(monkeypatch, tmp_path, service, fake_app):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("[download] Downloading video 1 of 3")
print("ERROR: Video 1 failed")
print("[download] Downloading video 2 of 3")
print("ERROR: Video 2 failed")
print("[download] Downloading video 3 of 3")
print("[download] 100% of 10MiB")
sys.exit(2)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    # Check that it surfaces an error line
    assert "Video" in errors[0]


def test_live_stream(monkeypatch, tmp_path, service, fake_app):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, """
import sys
print("[download] Destination: live_stream.mp4")
print("[download] 100% of ~10MiB")
sys.exit(0)
""")
    done = [e for e in events if e[0] == "done_full"]
    assert len(done) == 1


@pytest.mark.parametrize("line", [
    "ERROR: unable to write data: [Errno 28] No space left on device",
    "ERROR: [WinError 112] There is not enough space on the disk",
    "ERROR: [WinError 39] The disk is full",
])
def test_disk_full(monkeypatch, tmp_path, service, fake_app, line):
    events, _ = run_test_case(monkeypatch, tmp_path, service, fake_app, f"""
import sys
print({line!r})
sys.exit(1)
""")
    errors = [e[2] for e in events if e[0] == "error"]
    assert len(errors) == 1
    # The hint, not the echoed reason ("The disk is full" is part of one reason).
    assert "your disk is full: clear some space" in errors[0]
