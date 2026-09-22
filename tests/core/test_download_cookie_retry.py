"""Tests for the cookie-extraction-failure retry in DownloadService._media_phase.

Real-world regression (2026-08-19): a plain, fully public X/Twitter video
download failed solely because Advanced settings had "Cookies from browser"
pointed at Brave and yt-dlp could not copy Brave's (open, locked) cookie
database -- a LOCAL file-access problem, not the site rejecting the
request. Confirmed in app.log:

    Extracting cookies from brave
    ERROR: Could not copy Chrome cookie database. See
    https://github.com/yt-dlp/yt-dlp/issues/7271 for more info
    Download failed (yt-dlp exit code 1)

``_media_phase`` now retries once without cookies when this specific
failure shape is seen, so a cookie-jar read failure no longer breaks
downloads that never needed the cookies -- while a genuine "this site
needs a login" failure still surfaces an actionable message.
"""
from __future__ import annotations

import sys
import types
from queue import Queue

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService, _is_cookie_extraction_error

# app.app.App transitively imports faster_whisper; stub it so this hermetic
# test doesn't need the real (heavy) package installed, matching the
# convention in tests/core/test_fixpack_bl_downloadsvc.py.
if "faster_whisper" not in sys.modules:
    _fw = types.ModuleType("faster_whisper")
    _fw.WhisperModel = object  # type: ignore[attr-defined]
    sys.modules["faster_whisper"] = _fw

from app.app import App  # noqa: E402

COOKIE_ERROR_LINE = (
    "ERROR: Could not copy Chrome cookie database. See "
    "https://github.com/yt-dlp/yt-dlp/issues/7271 for more info"
)


# --- _is_cookie_extraction_error: local read failure vs. real auth wall ----


def test_is_cookie_extraction_error_matches_real_yt_dlp_message():
    assert _is_cookie_extraction_error(COOKIE_ERROR_LINE)


def test_is_cookie_extraction_error_matches_other_browsers():
    assert _is_cookie_extraction_error("ERROR: could not find firefox cookies database")
    assert _is_cookie_extraction_error("could not load edge cookies database")


def test_is_cookie_extraction_error_false_for_genuine_login_wall():
    assert not _is_cookie_extraction_error(
        "ERROR: Private video. Sign in if you've been granted access to this video"
    )
    assert not _is_cookie_extraction_error("ERROR: Video unavailable")


def test_is_cookie_extraction_error_false_for_blank():
    assert not _is_cookie_extraction_error("")
    assert not _is_cookie_extraction_error(None)  # type: ignore[arg-type]


# --- DownloadService.build_download_command(force_no_cookies=...) ----------


def _app(cookies_from_browser: str) -> App:
    """A real App instance (bypassing __init__ / Tk) carrying only what
    DownloadService._media_phase / build_download_command touch."""
    app = App.__new__(App)
    app.app_config = {"cookies_from_browser": cookies_from_browser}
    app.entry_file = __file__
    app.download_events = Queue()
    return app


def _task(url: str = "https://x.com/user/status/1/video/1") -> VideoDownloadTask:
    return VideoDownloadTask(
        url=url,
        folder="C:/out",
        format_label="x",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"},
        },
    )


def test_build_download_command_force_no_cookies_omits_flag_even_when_configured():
    svc = DownloadService(_app("brave"))
    with_cookies = svc.build_download_command(_task())
    without_cookies = svc.build_download_command(_task(), force_no_cookies=True)
    assert "--cookies-from-browser" in with_cookies
    assert "--cookies-from-browser" not in without_cookies


# --- _media_phase: the actual retry behaviour -------------------------------


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int):
        self.stdout = iter(lines)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


def _fake_popen_factory(monkeypatch, responses: list[tuple[list[str], int]]):
    """Patch subprocess.Popen for one _media_phase run.

    Each call consumes the next ``(lines, returncode)`` pair and records the
    argv it was invoked with, so the test can assert whether a given call
    carried ``--cookies-from-browser``.
    """
    calls: list[list[str]] = []
    remaining = list(responses)

    def _popen(command, **_):  # noqa: ANN001, ANN003
        calls.append(command)
        lines, rc = remaining.pop(0)
        return _FakeProcess(lines, rc)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    return calls


def _drain(app: App) -> list[tuple]:
    events = []
    while not app.download_events.empty():
        events.append(app.download_events.get_nowait())
    return events


def test_media_phase_retries_without_cookies_on_extraction_failure(monkeypatch):
    app = _app("brave")
    calls = _fake_popen_factory(monkeypatch, [
        ([COOKIE_ERROR_LINE], 1),
        (["[download] Destination: C:/out/clip.mp4"], 0),
    ])
    DownloadService(app)._media_phase(_task())

    assert len(calls) == 2
    assert "--cookies-from-browser" in calls[0]
    assert "--cookies-from-browser" not in calls[1]

    events = _drain(app)
    kinds = [e[0] for e in events]
    assert "done_full" in kinds
    assert "error" not in kinds
    assert any(e[0] == "log" and "retrying" in str(e[2]).lower() for e in events)


def test_media_phase_reports_actionable_error_when_retry_also_fails(monkeypatch):
    app = _app("brave")
    calls = _fake_popen_factory(monkeypatch, [
        ([COOKIE_ERROR_LINE], 1),
        (["ERROR: Private video. Sign in if you've been granted access to this video"], 1),
    ])
    DownloadService(app)._media_phase(_task())

    assert len(calls) == 2
    events = _drain(app)
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    msg = error_events[0][2].lower()
    assert "logged-in session" in msg and "cookie" in msg


def test_media_phase_stays_silent_when_superseded_during_the_retry(monkeypatch):
    """Found by an adversarial review (2026-09-22): the generation check
    only ran once, right after the FIRST _run_media_process call -- not
    after the cookie retry's own call. A pause+fast-resume landing while
    the retry was draining (exactly as long-running/blocking as the
    first attempt) used to fall through to the terminal branching anyway,
    posting a terminal event for a task a fresh run already owns and
    potentially releasing its download slot out from under it."""
    app = _app("brave")
    task = _task()
    task._run_generation = 1  # type: ignore[attr-defined]

    calls: list[list[str]] = []
    responses = iter([
        ([COOKIE_ERROR_LINE], 1),  # first attempt: cookie-jar read failure
        (["[download] Destination: C:/out/clip.mp4"], 0),  # retry succeeds
    ])

    def _popen(command, **_):  # noqa: ANN001, ANN003
        calls.append(command)
        lines, rc = next(responses)
        if len(calls) == 2:
            # Simulate a resume bumping the generation WHILE this retry
            # process is what's actually running (the real race is a
            # pause landing during the retry's blocking drain; bumping
            # here, before _media_phase reads the result, has the same
            # observable effect on the post-retry generation check).
            task._run_generation = 2  # type: ignore[attr-defined]
        return _FakeProcess(lines, rc)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)

    DownloadService(app)._media_phase(task, run_generation=1)

    assert len(calls) == 2, "the retry must still have been attempted"
    events = _drain(app)
    terminal_kinds = [e[0] for e in events if e[0] in ("done", "done_full", "error")]
    assert terminal_kinds == [], (
        f"a stale run posted terminal event(s) for a task a fresh run "
        f"already owns: {terminal_kinds}"
    )


def test_media_phase_does_not_retry_when_cookies_not_configured(monkeypatch):
    app = _app("")  # "Cookies from browser" is off
    calls = _fake_popen_factory(monkeypatch, [([COOKIE_ERROR_LINE], 1)])
    DownloadService(app)._media_phase(_task())
    assert len(calls) == 1  # nothing to retry without: no browser was ever consulted


def test_media_phase_does_not_retry_for_unrelated_error(monkeypatch):
    app = _app("brave")
    calls = _fake_popen_factory(monkeypatch, [(["ERROR: Video unavailable"], 1)])
    DownloadService(app)._media_phase(_task())
    assert len(calls) == 1  # not a cookie-jar read failure -> no retry

    events = _drain(app)
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    # The pre-existing "turn on Cookies from browser" hint must not fire for
    # this unrelated error either.
    assert "cookies from browser" not in error_events[0][2].lower()


def test_media_phase_success_on_first_try_needs_no_retry(monkeypatch):
    app = _app("brave")
    calls = _fake_popen_factory(monkeypatch, [
        (["[download] Destination: C:/out/clip.mp4"], 0),
    ])
    DownloadService(app)._media_phase(_task())
    assert len(calls) == 1
    events = _drain(app)
    # One "log" event for the Destination line, then the final done_full.
    assert [e[0] for e in events] == ["log", "done_full"]
