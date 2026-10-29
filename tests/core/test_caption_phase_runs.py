"""Caption phase vs a stop or a newer run of the same task (pause + resume bumps ``_run_generation``).

A cancelled, paused or replaced run must start no yt-dlp process, never take the newer run's process
slot and never delete a caption file the newer run wrote. Acceptance tests written by an outside QA
pass, kept as regression tests. No network, no Tk.
"""
import os
import subprocess
import types
from queue import Queue

import pytest

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService
from app.services.format_service import FormatService

def build_app(tmp_path):
    import builtins
    if not hasattr(builtins, "_"):
        builtins._ = lambda x: x
    if not hasattr(builtins, "pgettext"):
        builtins.pgettext = lambda ctx, x: x
    if not hasattr(builtins, "ngettext"):
        builtins.ngettext = lambda s, p, n: p if n != 1 else s

    app = types.SimpleNamespace(
        app_config={"cookies_from_browser": "chrome"},
        entry_file=__file__,
        download_events=Queue(),
        format_events=Queue(),
        history=None,
        download_current=None,
        log=lambda *a, **k: None,
        yt_dlp_path=lambda: "fake-yt-dlp",
        bin_path=lambda: "",
        after_cancel=lambda *a: None,
        after=lambda *a: None,
        format_lookup_after=None,
        download_url_var=types.SimpleNamespace(get=lambda: "http://example.com/video"),
        audio_format_combo={"values": []},
        video_format_combo={"values": []},
        audio_format_var=types.SimpleNamespace(set=lambda x: None),
        video_format_var=types.SimpleNamespace(set=lambda x: None),
        format_status_var=types.SimpleNamespace(set=lambda x: None),
        update_caption_shortcut_state=lambda: None,
        current_video_title="",
        current_video_language="",
        current_video_caption_langs={},
        format_lookup_error="",
    )
    return app


def test_r1_stale_run_never_starts_download(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    started = []
    class FakeProc:
        def __init__(self, cmd, **kwargs):
            started.append(cmd)
            self.stdout = iter([])
            self.returncode = 0
        def wait(self): return 0

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")
    task._run_generation = 2

    svc._subtitle_phase(task, run_generation=1)
    assert not started, "Stale run started a caption download"


def test_r1_cancelled_run_never_starts_download(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    started = []
    class FakeProc:
        def __init__(self, cmd, **kwargs):
            started.append(cmd)
            self.stdout = iter([])
            self.returncode = 0
        def wait(self): return 0

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")
    task._run_generation = 2
    task.cancelled = True

    svc._subtitle_phase(task, run_generation=2)
    assert not started, "Cancelled run started a caption download"


def test_r1_never_deletes_newer_file(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    fpath = str(tmp_path / "newer_run_sub.vtt")
    with open(fpath, "w") as f:
        f.write("newer content")

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.stdout = iter([f"Writing video subtitles to: {fpath}\n"])
            self.returncode = 0
        def wait(self): return 0

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")
    task._run_generation = 2

    task.cancelled = True
    svc._subtitle_phase(task, run_generation=1)

    assert os.path.exists(fpath), "Stale/cancelled run deleted a caption file"


def test_r2_stale_run_never_overwrites_process(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.stdout = iter([])
            self.returncode = 0
        def wait(self): return 0

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")
    task._run_generation = 2

    new_proc = FakeProc(["new"])
    task.process = new_proc

    svc._subtitle_phase(task, run_generation=1)

    assert task.process is new_proc, "Stale run overwrote task.process"


def test_r3_real_error_not_reported_as_no_captions(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.stdout = iter([
                "ERROR: Unable to download webpage: HTTP Error 403: Forbidden\n"
            ])
            self.returncode = 1
        def wait(self): return 1

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")

    svc._subtitle_phase(task, run_generation=1)

    statuses = []
    while not app.download_events.empty():
        evt = app.download_events.get()
        if evt[0] == "subtitle_status":
            statuses.append(evt[2])

    assert "no captions available for this language" not in statuses, "Real error reported as no captions available"


def test_r4_missing_or_empty_file_not_counted(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    announced_file = str(tmp_path / "fake.vtt")

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.stdout = iter([
                f"Writing video subtitles to: {announced_file}\n"
            ])
            self.returncode = 0
        def wait(self): return 0

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")

    svc._subtitle_phase(task, run_generation=1)

    statuses = []
    while not app.download_events.empty():
        evt = app.download_events.get()
        if evt[0] == "subtitle_status":
            statuses.append(evt[2])

    assert not any("saved" in s for s in statuses), "Missing/empty file was counted as downloaded"


def test_r5_format_lookup_retries_without_cookies(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = FormatService(app)

    probe_calls = []
    def mock_run(cmd, **kwargs):
        probe_calls.append(cmd)
        has_cookies = any("--cookies-from-browser" in arg for arg in cmd)
        if has_cookies:
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="ERROR: Could not extract Chrome cookies: DPAPI failed"
            )
        else:
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout='{"title": "test", "formats": []}', stderr=""
            )

    monkeypatch.setattr("app.services.format_service.subprocess.run", mock_run)
    try:
        monkeypatch.setattr("app.services.format_service.yt_dlp_update.wait_while_updating", lambda: None)
    except AttributeError:
        pass

    def mock_safe_thread(target, **kwargs):
        target()
    monkeypatch.setattr("core._threads.safe_thread", mock_safe_thread)

    svc.lookup_formats()

    assert len(probe_calls) == 2, "Format lookup did not retry"
    assert any("--cookies-from-browser" in arg for arg in probe_calls[0])
    assert not any("--cookies-from-browser" in arg for arg in probe_calls[1]), "Did not retry without cookies"


def test_r5_plan_pass_retries_without_cookies(monkeypatch, tmp_path):
    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app

    probe_calls = []
    class FakeProc:
        def __init__(self, cmd, **kwargs):
            probe_calls.append(cmd)
            self.returncode = 1

        def communicate(self, timeout=None):
            has_cookies = any("--cookies-from-browser" in arg for arg in probe_calls[-1])
            if has_cookies:
                return ("", "ERROR: Could not extract Chrome cookies: DPAPI failed\n")
            else:
                self.returncode = 0
                return ('{"title": "test"}', "")

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", FakeProc)

    task = VideoDownloadTask("url", str(tmp_path), "format", {})
    cmd = ["yt-dlp", "--cookies-from-browser", "chrome"]

    svc._plan_pass(task, cmd)

    assert len(probe_calls) >= 2, "plan pass did not retry without cookies"
    assert not any("--cookies-from-browser" in arg for arg in probe_calls[-1]), "plan pass did not drop cookies on retry"


def test_a_newer_run_arriving_while_the_process_starts_keeps_its_slot(monkeypatch, tmp_path):
    import app.services.download_service as ds

    app = build_app(tmp_path)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app
    task = VideoDownloadTask("url", str(tmp_path), "format", {}, subtitle_lang="en")
    task._run_generation = 1
    newer = object()
    killed = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            task._run_generation = 2  # the resume lands during Popen
            task.process = newer
            self.stdout = iter([])
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(ds.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(ds, "kill_download_tree", lambda proc, **k: killed.append(proc))
    assert svc._run_subtitle_process(task, "en", run_generation=1) == ([], False, 0, "")
    assert task.process is newer
    assert len(killed) == 1 and isinstance(killed[0], FakeProc)
