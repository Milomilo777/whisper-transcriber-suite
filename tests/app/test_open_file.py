"""Opening a result file must report a failure, on every platform.

``open file.srt`` returns 1 on a Mac with no app for .srt, and the Last result "Open" button
used to ignore that (nothing happened, nothing was said). The platform and the opener process
are faked at the module boundary; no Tk window is needed. The opener runs on a worker thread and
the outcome comes back through ``parent.after`` (``_Window.pump`` plays the Tk event loop).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import types
from typing import Any, Callable

import pytest

from app.widgets import platform as plat


class _Proc:
    def __init__(self, code: int = 0, hang: bool = False, gate: threading.Event | None = None) -> None:
        self.code = code
        self.hang = hang
        self.gate = gate

    def wait(self, timeout: float | None = None) -> int:
        if self.gate is not None:
            self.gate.wait(10)  # the opener "runs" until the test lets it finish
        if self.hang:
            raise subprocess.TimeoutExpired("opener", timeout or 0)
        return self.code


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fake ``subprocess.Popen``: ``opener.codes`` maps argv[1] ("-t" or the path) to an exit code."""
    state = types.SimpleNamespace(calls=[], default=0, by_flag={}, hang=False, raises=None, gate=None)

    def popen(cmd: list[str], **_kw: Any) -> _Proc:
        state.calls.append(list(cmd))
        if state.raises is not None:
            raise state.raises
        flag = cmd[1] if cmd[1].startswith("-") else ""
        return _Proc(state.by_flag.get(flag, state.default), state.hang, state.gate)

    monkeypatch.setattr(plat.subprocess, "Popen", popen)
    return state


@pytest.fixture
def platform_name(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    started: list[str] = []

    def set_platform(name: str, startfile: Callable[[str], None] | None = None) -> list[str]:
        monkeypatch.setattr(plat, "sys", types.SimpleNamespace(platform=name))
        monkeypatch.setattr(plat, "os", types.SimpleNamespace(
            name="nt" if name == "win32" else "posix", path=os.path,
            startfile=startfile or started.append))
        return started

    return set_platform


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Records what the person is shown: folder reveals, notices, error dialogs, message boxes."""
    from app.widgets import notice

    rec = types.SimpleNamespace(folders=[], notices=[], errors=[], boxes=[], reveal_ok=True)

    def open_folder(folder: str, parent: Any = None, select: Any = None) -> bool:
        rec.folders.append((folder, select))
        return rec.reveal_ok

    monkeypatch.setattr(plat, "open_folder", open_folder)
    monkeypatch.setattr(notice, "notify", lambda w, text, kind="info": rec.notices.append((text, kind)))
    monkeypatch.setattr(plat, "show_error", lambda parent, title, msg, detail=None: rec.errors.append((msg, detail)))
    monkeypatch.setattr(plat.messagebox, "showinfo", lambda title, msg, **k: rec.boxes.append(msg))
    monkeypatch.setattr(plat.messagebox, "showerror", lambda title, msg, **k: rec.boxes.append(msg))
    return rec


@pytest.fixture
def srt(tmp_path: Any) -> str:
    path = tmp_path / "talk.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    return str(path)


class _Window:
    """Stands in for a Tk window: ``after`` queues, ``pump`` runs the queue like the event loop."""

    def __init__(self) -> None:
        self.calls: list[Callable[[], None]] = []

    def after(self, _ms: int, func: Callable[[], None]) -> str:
        self.calls.append(func)
        return "after#1"

    def pump(self, seconds: float = 5.0) -> None:
        end = time.monotonic() + seconds
        while self.calls and time.monotonic() < end:
            batch, self.calls = self.calls, []
            for func in batch:
                func()
            time.sleep(0.002)
        assert not self.calls, "the outcome never came back"


# ------------------------------------------------------------ open_with_default_app

def test_macos_open_failure_on_an_existing_file_means_no_app(platform_name, opener, srt) -> None:
    platform_name("darwin")
    opener.default = 1
    with pytest.raises(plat.NoDefaultAppError):
        plat.open_with_default_app(srt)
    assert opener.calls == [["open", srt]]


def test_macos_open_success_returns_quietly(platform_name, opener, srt) -> None:
    platform_name("darwin")
    plat.open_with_default_app(srt)
    assert opener.calls == [["open", srt]]


def test_a_missing_file_is_not_reported_as_no_app(platform_name, opener, tmp_path) -> None:
    platform_name("darwin")
    opener.default = 1
    with pytest.raises(FileNotFoundError):
        plat.open_with_default_app(str(tmp_path / "gone.srt"))


def test_linux_xdg_open_codes(platform_name, opener, srt) -> None:
    platform_name("linux")
    for code, words in ((1, "could not open"), (3, "not installed"), (4, "could not open")):
        opener.default = code
        with pytest.raises(OSError) as info:
            plat.open_with_default_app(srt)
        # exit codes 3 and 4 of xdg-open are not "no app is set"
        assert not isinstance(info.value, plat.NoDefaultAppError)
        assert words in str(info.value) and f"exit code {code}" in str(info.value)
    opener.default = 5
    with pytest.raises(PermissionError):
        plat.open_with_default_app(srt)
    opener.default = 0
    plat.open_with_default_app(srt)
    assert all(c == ["xdg-open", srt] for c in opener.calls)


def test_an_opener_still_running_counts_as_handed_over(platform_name, opener, srt) -> None:
    platform_name("linux")
    opener.hang = True
    opener.default = 1
    plat.open_with_default_app(srt)  # no error: the app is up and the opener waits for it


def test_a_missing_opener_program_raises(platform_name, opener, srt) -> None:
    platform_name("linux")
    opener.raises = FileNotFoundError("xdg-open")
    with pytest.raises(FileNotFoundError):
        plat.open_with_default_app(srt)


def test_windows_no_association_means_no_app(platform_name, srt) -> None:
    def startfile(_p: str) -> None:
        err = OSError(1155, "No application is associated")
        err.winerror = 1155  # type: ignore[attr-defined]
        raise err

    platform_name("win32", startfile)
    with pytest.raises(plat.NoDefaultAppError):
        plat.open_with_default_app(srt)


def test_windows_other_failures_stay_plain_oserrors(platform_name, srt) -> None:
    def startfile(_p: str) -> None:
        err = OSError(2, "not found")
        err.winerror = 2  # type: ignore[attr-defined]
        raise err

    platform_name("win32", startfile)
    with pytest.raises(OSError) as info:
        plat.open_with_default_app(srt)
    assert not isinstance(info.value, plat.NoDefaultAppError)


# ------------------------------------------------------------ open_file (what the person sees)

def _windows_no_app(_p: str) -> None:
    err = OSError(1155, "No application is associated")
    err.winerror = 1155  # type: ignore[attr-defined]
    raise err


def test_success_shows_nothing(platform_name, opener, shown, srt) -> None:
    platform_name("darwin")
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    window.pump()
    assert opener.calls == [["open", srt]]
    assert not (shown.folders or shown.notices or shown.errors or shown.boxes)


def test_the_tk_thread_never_waits_for_the_opener(platform_name, opener, shown, srt) -> None:
    """open_file returns at once while the opener is still running; the answer comes later."""
    platform_name("darwin")
    opener.gate = threading.Event()
    opener.default = 1
    window = _Window()
    started = time.monotonic()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    assert time.monotonic() - started < 0.5          # the opener has not finished (gate is shut)
    window.calls.pop(0)()                              # one Tk poll: still waiting, nothing shown
    assert not (shown.folders or shown.notices or shown.errors)
    opener.gate.set()
    window.pump()
    assert shown.folders and shown.notices           # the no-app fallback arrived afterwards


def test_a_slow_opener_does_not_block_other_callers_either(platform_name, opener, srt, tmp_path) -> None:
    platform_name("linux")
    opener.gate = threading.Event()
    window = _Window()
    seen: list[BaseException | None] = []
    started = time.monotonic()
    plat.open_async(srt, window, seen.append)  # type: ignore[arg-type]
    assert time.monotonic() - started < 0.5 and seen == []
    opener.gate.set()
    window.pump()
    assert seen == [None]


def test_without_a_window_the_opener_runs_inline(platform_name, opener, srt) -> None:
    platform_name("linux")
    seen: list[BaseException | None] = []
    plat.open_async(srt, None, seen.append)
    assert seen == [None] and opener.calls == [["xdg-open", srt]]


def test_macos_with_no_app_for_srt_opens_it_as_text(platform_name, opener, shown, srt) -> None:
    platform_name("darwin")
    opener.default = 1
    opener.by_flag["-t"] = 0
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    window.pump()
    assert opener.calls == [["open", srt], ["open", "-t", srt]]
    assert not (shown.folders or shown.notices or shown.errors)


def test_macos_with_no_app_and_no_text_editor_reveals_the_file_and_says_so(
    platform_name, opener, shown, srt, tmp_path,
) -> None:
    platform_name("darwin")
    opener.default = 1
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    window.pump()
    assert shown.folders == [(str(tmp_path), srt)]
    assert shown.notices == [
        ("No app is set to open .srt files; the file is shown in its folder.", "warning")
    ]


def test_the_notice_does_not_claim_the_folder_was_shown_when_it_could_not_be_opened(
    platform_name, opener, shown, srt,
) -> None:
    platform_name("darwin")
    opener.default = 1
    shown.reveal_ok = False
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    window.pump()
    (text, kind), = shown.notices
    assert "shown in its folder" not in text and "could not be opened" in text and kind == "warning"


def test_macos_with_no_app_for_a_video_reveals_it_without_the_text_editor(
    platform_name, opener, shown, tmp_path,
) -> None:
    platform_name("darwin")
    video = tmp_path / "clip.xyz"
    video.write_bytes(b"\0")
    opener.default = 1
    window = _Window()
    plat.open_file(str(video), parent=window)  # type: ignore[arg-type]
    window.pump()
    assert opener.calls == [["open", str(video)]]
    assert shown.folders == [(str(tmp_path), str(video))]
    assert "No app is set to open .xyz files" in shown.notices[0][0]


def test_windows_with_no_app_reveals_the_file_and_says_so(
    platform_name, opener, shown, srt, tmp_path,
) -> None:
    platform_name("win32", _windows_no_app)
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    assert shown.folders == [(str(tmp_path), srt)] and len(shown.notices) == 1


def test_linux_failures_show_the_exit_code_not_a_no_app_message(
    platform_name, opener, shown, srt, monkeypatch,
) -> None:
    platform_name("linux")
    monkeypatch.setattr(plat, "tk", types.SimpleNamespace(Tk=_Window, Toplevel=_Window))
    for code in (3, 4):
        shown.errors.clear()
        opener.default = code
        window = _Window()
        plat.open_file(srt, parent=window)  # type: ignore[arg-type]
        window.pump()
        (msg, detail), = shown.errors
        assert f"exit code {code}" in str(detail) and "No app is set" not in str(detail)
    assert not shown.folders and not shown.notices


def test_a_file_without_an_extension_gets_a_generic_message(platform_name, opener, shown, tmp_path) -> None:
    platform_name("win32", _windows_no_app)
    bare = tmp_path / "README"
    bare.write_text("x", encoding="utf-8")
    plat.open_file(str(bare), parent=_Window())  # type: ignore[arg-type]
    assert shown.notices[0][0] == (
        "No app is set to open this kind of file; the file is shown in its folder."
    )


def test_no_app_without_a_window_uses_a_message_box(platform_name, opener, shown, srt) -> None:
    platform_name("win32", _windows_no_app)
    plat.open_file(srt)
    assert shown.boxes and ".srt" in shown.boxes[0] and not shown.notices


def test_other_failures_show_an_error_with_the_detail(platform_name, opener, shown, srt, monkeypatch) -> None:
    platform_name("linux")
    opener.raises = FileNotFoundError("xdg-open is not installed")
    # the helper shows the error dialog only for a real Tk / Toplevel parent
    monkeypatch.setattr(plat, "tk", types.SimpleNamespace(Tk=_Window, Toplevel=_Window))
    window = _Window()
    plat.open_file(srt, parent=window, error_text="Could not play it.")  # type: ignore[arg-type]
    window.pump()
    assert shown.errors == [("Could not play it.", "xdg-open is not installed")]
    assert not shown.folders


def test_a_path_the_opener_rejects_with_a_value_error_shows_the_error_dialog(
    platform_name, opener, shown, srt, monkeypatch,
) -> None:
    """The old code caught every Exception: a null byte in the path must not escape to Tk."""
    platform_name("linux")
    opener.raises = ValueError("embedded null byte")
    monkeypatch.setattr(plat, "tk", types.SimpleNamespace(Tk=_Window, Toplevel=_Window))
    window = _Window()
    plat.open_file(srt, parent=window)  # type: ignore[arg-type]
    window.pump()
    assert shown.errors == [("Could not open that file with your system's default app.", "embedded null byte")]


def test_a_window_destroyed_before_the_answer_is_not_called_back(platform_name, opener, srt) -> None:
    import tkinter as tk

    class Gone(_Window):
        def after(self, _ms: int, func: Callable[[], None]) -> str:
            raise tk.TclError("application has been destroyed")

    platform_name("linux")
    seen: list[BaseException | None] = []
    plat.open_async(srt, Gone(), seen.append)  # type: ignore[arg-type]
    assert seen == []


# ------------------------------------------------------------ the callers

def test_last_result_open_reports_a_mac_with_no_app_for_srt(
    platform_name, opener, shown, srt, tmp_path, monkeypatch,
) -> None:
    """The reported defect: Open on a .srt did nothing and said nothing."""
    import app.app as app_mod

    platform_name("darwin")
    opener.default = 1
    # the old code ran the opener through subprocess.run and dropped the result
    monkeypatch.setattr(
        plat.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(returncode=1))
    monkeypatch.setattr(app_mod, "show_error", lambda *a, **k: pytest.fail("not an error"))
    window = _Window()
    app_mod.App._open_file(window, srt)  # type: ignore[arg-type]
    window.pump()
    assert shown.folders == [(str(tmp_path), srt)]
    assert "No app is set to open .srt files" in shown.notices[0][0]


def test_share_page_browser_open_reports_when_no_app(platform_name, opener, tmp_path, monkeypatch) -> None:
    from app.dialogs import share_page

    platform_name("darwin")
    page = tmp_path / "page.html"
    page.write_text("<html></html>", encoding="utf-8")
    opener.default = 1
    errors: list[str] = []
    monkeypatch.setattr(share_page.messagebox, "showerror", lambda title, msg, **k: errors.append(msg))
    window = _Window()
    share_page.open_in_browser(str(page), window)  # type: ignore[arg-type]
    window.pump()
    assert len(errors) == 1 and "could not be opened" in errors[0] and str(page) in errors[0]
