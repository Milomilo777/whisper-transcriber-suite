"""The download service's handling of unreadable browser cookies and of file-system errors.

* a Chromium-family browser on Windows: the message says plainly that its cookies cannot be read
  any more (browser encryption) and points at Firefox or a cookies.txt file, never "close the browser";
* the failure is remembered for the run: the next download starts without the doomed attempt;
* the final message blames cookies / a login only when the error without cookies is a login wall;
  a file-system error is reported as what it is;
* ``--cookies FILE`` reaches the download, caption and plan commands.
Stand-in processes only; no Tk, no network.
"""
from __future__ import annotations

import pytest

from app.domain import cookies as ck
from app.services.download_service import DownloadService
from tests.core.test_download_cookie_retry import (
    COOKIE_ERROR_LINE,
    _app,
    _drain,
    _fake_popen_factory,
    _task,
)

ERRNO22 = (
    '[download] Unable to open file: [Errno 22] Invalid argument: '
    '"C:\\Users\\Owner\\Desktop\\New folder\\134K views.f3520236458150143v.mp4.part"'
)
WALL = "ERROR: Private video. Sign in if you've been granted access to this video"


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(ck, "_is_windows", lambda: True)


@pytest.fixture
def not_windows(monkeypatch):
    monkeypatch.setattr(ck, "_is_windows", lambda: False)


def _errors(app):
    return [e[2] for e in _drain(app) if e[0] == "error"]


def test_chromium_on_windows_gets_the_plain_message_when_the_site_needs_a_login(monkeypatch, windows):
    app = _app("brave")
    _fake_popen_factory(monkeypatch, [([COOKIE_ERROR_LINE], 1), ([WALL], 1)])
    DownloadService(app)._media_phase(_task())
    msg = _errors(app)[0]
    assert ck.cookies_blocked_text() in msg
    assert "Fully close" not in msg and "close the browser" not in msg.lower()


def test_the_second_download_skips_the_failed_browser_and_logs_one_line(monkeypatch, windows):
    app = _app("brave")
    calls = _fake_popen_factory(monkeypatch, [
        ([COOKIE_ERROR_LINE], 1), (["[download] Destination: C:/out/a.mp4"], 0),
        (["[download] Destination: C:/out/b.mp4"], 0),
    ])
    svc = DownloadService(app)
    svc._media_phase(_task())
    first = _drain(app)
    assert len(calls) == 2
    svc._media_phase(_task("https://x.com/user/status/2/video/1"))
    assert len(calls) == 3                                   # ONE process: no cookie attempt, no retry
    assert "--cookies-from-browser" not in calls[2]
    second = _drain(app)
    logs = [str(e[2]) for e in second if e[0] == "log"]
    skip = [line for line in logs if "skipped" in line.lower() and "brave" in line]
    assert len(skip) == 1
    assert not any("retrying" in line.lower() for line in logs)
    assert any(e[0] == "done_full" for e in first) and any(e[0] == "done_full" for e in second)


def test_picking_the_setting_again_clears_the_memory(monkeypatch, windows):
    app = _app("brave")
    _fake_popen_factory(monkeypatch, [([COOKIE_ERROR_LINE], 1), (["[download] Destination: C:/out/a.mp4"], 0)])
    svc = DownloadService(app)
    svc._media_phase(_task())
    assert "--cookies-from-browser" not in svc.build_download_command(_task())
    ck.forget_cookie_failures(app)
    assert "--cookies-from-browser" in svc.build_download_command(_task())


def test_a_transient_failure_outside_windows_is_not_remembered(monkeypatch, not_windows):
    # A locked cookie database is cured by closing the browser: keep trying next time.
    app = _app("chrome")
    _fake_popen_factory(monkeypatch, [([COOKIE_ERROR_LINE], 1), (["[download] Destination: C:/out/a.mp4"], 0)])
    svc = DownloadService(app)
    svc._media_phase(_task())
    assert "--cookies-from-browser" in svc.build_download_command(_task())


def test_the_dpapi_failure_is_remembered_on_any_platform(monkeypatch, not_windows):
    app = _app("chrome")
    _fake_popen_factory(monkeypatch, [
        (["ERROR: Failed to decrypt with DPAPI. See  https://github.com/yt-dlp/yt-dlp/issues/10927"], 1),
        (["[download] Destination: C:/out/a.mp4"], 0),
    ])
    svc = DownloadService(app)
    svc._media_phase(_task())
    assert "--cookies-from-browser" not in svc.build_download_command(_task())


def test_a_file_error_after_the_cookie_retry_is_not_blamed_on_cookies(monkeypatch, windows):
    app = _app("brave")
    _fake_popen_factory(monkeypatch, [([COOKIE_ERROR_LINE], 1), ([ERRNO22], 1)])
    DownloadService(app)._media_phase(_task())
    msg = _errors(app)[0]
    low = msg.lower()
    assert "too long" in low
    assert "logged-in" not in low and "cookie" not in low
    assert ck.cookies_blocked_text() not in msg


def test_a_file_error_without_any_cookies_is_reported_as_one(monkeypatch):
    app = _app("")
    _fake_popen_factory(monkeypatch, [([ERRNO22], 1)])
    DownloadService(app)._media_phase(_task())
    assert "too long" in _errors(app)[0].lower()


def test_permission_denied_is_reported_in_plain_words(monkeypatch):
    app = _app("")
    _fake_popen_factory(monkeypatch, [(["ERROR: unable to open for writing: [Errno 13] Permission denied: 'x'"], 1)])
    DownloadService(app)._media_phase(_task())
    assert "not allowed" in _errors(app)[0].lower()


def test_the_login_text_still_appears_when_the_site_really_needs_a_login(monkeypatch, not_windows):
    app = _app("firefox")
    _fake_popen_factory(monkeypatch, [(["ERROR: Could not copy Firefox cookie database"], 1), ([WALL], 1)])
    DownloadService(app)._media_phase(_task())
    msg = _errors(app)[0].lower()
    assert "logged-in session" in msg


def test_a_cookies_file_reaches_the_download_and_caption_commands(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    svc = DownloadService(_app(str(path)))
    for cmd in (svc.build_download_command(_task()), svc.build_subtitle_command(_task(), "en")):
        used = cmd[cmd.index("--cookies") + 1]
        assert used != str(path)                       # yt-dlp rewrites the file it gets: a copy
        assert open(used, encoding="utf-8").read() == path.read_text(encoding="utf-8")
        assert "--cookies-from-browser" not in cmd
    assert "--cookies" not in svc.build_download_command(_task(), force_no_cookies=True)


def test_the_caption_retry_remembers_the_failure(monkeypatch, windows, tmp_path):
    app = _app("brave")
    vtt = tmp_path / "a.en.vtt"
    vtt.write_text("WEBVTT cues", encoding="utf-8")
    calls = _fake_popen_factory(monkeypatch, [
        ([COOKIE_ERROR_LINE], 1),
        ([f"[info] Writing video subtitles to: {vtt}"], 0),
    ])
    svc = DownloadService(app)
    wrote, _no, rc = svc._fetch_subtitles(_task(), "en")
    assert rc == 0 and wrote
    assert len(calls) == 2 and "--cookies-from-browser" not in calls[1]
    assert ck.cookies_failed_before(app, "brave")


def test_the_plan_pass_retries_without_cookies_and_remembers(monkeypatch, windows):
    import subprocess

    app = _app("brave")
    plans: list[list[str]] = []

    class _Plan:
        def __init__(self, rc, out, err):
            self.returncode, self._o, self._e = rc, out, err

        def communicate(self, timeout=None):  # noqa: ANN001
            return self._o, self._e

    def _popen(command, **_):  # noqa: ANN001, ANN003
        plans.append(command)
        if "--cookies-from-browser" in command:
            return _Plan(1, "", COOKIE_ERROR_LINE)
        return _Plan(0, "wts-plan:C:/out/a.mp4\n", "")

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    svc = DownloadService(app)
    items = svc._plan_pass(_task(), svc.build_download_command(_task()))
    assert items and items[0].source == "C:/out/a.mp4"
    assert len(plans) == 2 and "--cookies-from-browser" not in plans[1]
    assert ck.cookies_failed_before(app, "brave")


def test_the_login_hint_for_unreadable_chromium_cookies_on_windows_is_the_plain_message(windows):
    # Only once reading them failed: a readable jar plus a login wall means "log in to the site".
    hint = ck.login_required_hint(
        "rate-limit reached or login required. Use --cookies", "edge", cookies_unreadable=True
    )
    assert hint == ck.cookies_blocked_text()


def test_a_caption_file_that_was_announced_but_never_written_is_not_counted(monkeypatch, tmp_path):
    # Real log: "Writing video subtitles to: <name>" then [Errno 22]; the app then said the captions
    # "were downloaded but could not be read".
    app = _app("")
    empty = tmp_path / "empty.en.vtt"
    empty.write_text("", encoding="utf-8")
    _fake_popen_factory(monkeypatch, [(
        [f"[info] Writing video subtitles to: {tmp_path / 'never.en.vtt'}",
         f"[info] Writing video subtitles to: {empty}", ERRNO22], 1)])
    wrote, _no, rc = DownloadService(app)._fetch_subtitles(_task(), "en")
    assert rc == 1 and wrote == []


def test_the_cookies_copy_is_private_and_the_users_file_is_untouched(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    copy = ck.private_cookies_copy(str(path))
    assert copy != str(path) and open(copy, encoding="utf-8").read() == path.read_text(encoding="utf-8")
    assert ck.private_cookies_copy("brave") == "brave"
    assert ck.private_cookies_copy("") == ""


def test_a_lone_unrelated_fresh_file_is_not_taken_as_the_download(tmp_path):
    import time
    import types

    stranger = tmp_path / "Something else entirely.mp4"
    stranger.write_bytes(b"x")
    svc = DownloadService(types.SimpleNamespace())  # type: ignore[arg-type]
    task = types.SimpleNamespace(folder=str(tmp_path), start_time=time.time() - 1, title="My Real Title")
    assert svc._find_recovered_path(task, None) == (None, True)
    mine = tmp_path / "My Real Title (1).mp4"
    mine.write_bytes(b"x")
    stranger.unlink()
    assert svc._find_recovered_path(task, None) == (str(mine), False)
