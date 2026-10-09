"""Opening a result file must report a failure, on every platform.

``open file.srt`` returns 1 on a Mac with no app for .srt, and the Last result "Open" button
used to ignore that (nothing happened, nothing was said). The platform and the opener process
are faked at the module boundary; no Tk window is needed.
"""
from __future__ import annotations

import os
import subprocess
import types
from typing import Any, Callable

import pytest

from app.widgets import platform as plat


class _Proc:
    def __init__(self, code: int = 0, hang: bool = False) -> None:
        self.code = code
        self.hang = hang

    def wait(self, timeout: float | None = None) -> int:
        if self.hang:
            raise subprocess.TimeoutExpired("opener", timeout or 0)
        return self.code


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fake ``subprocess.Popen``: ``opener.codes`` maps argv[1] ("-t" or the path) to an exit code."""
    state = types.SimpleNamespace(calls=[], default=0, by_flag={}, hang=False, raises=None)

    def popen(cmd: list[str], **_kw: Any) -> _Proc:
        state.calls.append(list(cmd))
        if state.raises is not None:
            raise state.raises
        flag = cmd[1] if cmd[1].startswith("-") else ""
        return _Proc(state.by_flag.get(flag, state.default), state.hang)

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

    rec = types.SimpleNamespace(folders=[], notices=[], errors=[], boxes=[])
    monkeypatch.setattr(plat, "open_folder", lambda folder, parent=None, select=None: rec.folders.append((folder, select)))
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
    """Stands in for a Tk window: only its type matters to the helper."""


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
    for code in (1, 3, 4):
        opener.default = code
        with pytest.raises(plat.NoDefaultAppError):
            plat.open_with_default_app(srt)
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

def test_success_shows_nothing(platform_name, opener, shown, srt) -> None:
    platform_name("darwin")
    assert plat.open_file(srt, parent=_Window()) is True  # type: ignore[arg-type]
    assert not (shown.folders or shown.notices or shown.errors or shown.boxes)


def test_macos_with_no_app_for_srt_opens_it_as_text(platform_name, opener, shown, srt) -> None:
    platform_name("darwin")
    opener.by_flag = {}
    opener.default = 1
    opener.by_flag["-t"] = 0
    assert plat.open_file(srt, parent=_Window()) is True  # type: ignore[arg-type]
    assert opener.calls == [["open", srt], ["open", "-t", srt]]
    assert not (shown.folders or shown.notices or shown.errors)


def test_macos_with_no_app_and_no_text_editor_reveals_the_file_and_says_so(
    platform_name, opener, shown, srt, tmp_path,
) -> None:
    platform_name("darwin")
    opener.default = 1
    assert plat.open_file(srt, parent=_Window()) is False  # type: ignore[arg-type]
    assert shown.folders == [(str(tmp_path), srt)]
    assert shown.notices == [
        ("No app is set to open .srt files; the file is shown in its folder.", "warning")
    ]


def test_macos_with_no_app_for_a_video_reveals_it_without_the_text_editor(
    platform_name, opener, shown, tmp_path,
) -> None:
    platform_name("darwin")
    video = tmp_path / "clip.xyz"
    video.write_bytes(b"\0")
    opener.default = 1
    assert plat.open_file(str(video), parent=_Window()) is False  # type: ignore[arg-type]
    assert opener.calls == [["open", str(video)]]
    assert shown.folders == [(str(tmp_path), str(video))]
    assert "No app is set to open .xyz files" in shown.notices[0][0]


def test_linux_and_windows_with_no_app_reveal_the_file_and_say_so(
    platform_name, opener, shown, srt, tmp_path,
) -> None:
    platform_name("linux")
    opener.default = 3
    assert plat.open_file(srt, parent=_Window()) is False  # type: ignore[arg-type]
    assert opener.calls == [["xdg-open", srt]]  # no text-editor fallback outside macOS
    assert shown.folders == [(str(tmp_path), srt)] and len(shown.notices) == 1

    shown.folders.clear()
    shown.notices.clear()

    def startfile(_p: str) -> None:
        err = OSError(1155, "No application is associated")
        err.winerror = 1155  # type: ignore[attr-defined]
        raise err

    platform_name("win32", startfile)
    assert plat.open_file(srt, parent=_Window()) is False  # type: ignore[arg-type]
    assert shown.folders == [(str(tmp_path), srt)] and len(shown.notices) == 1


def test_a_file_without_an_extension_gets_a_generic_message(platform_name, opener, shown, tmp_path) -> None:
    platform_name("linux")
    bare = tmp_path / "README"
    bare.write_text("x", encoding="utf-8")
    opener.default = 3
    plat.open_file(str(bare), parent=_Window())  # type: ignore[arg-type]
    assert shown.notices[0][0] == (
        "No app is set to open this kind of file; the file is shown in its folder."
    )


def test_no_app_without_a_window_uses_a_message_box(platform_name, opener, shown, srt) -> None:
    platform_name("linux")
    opener.default = 3
    assert plat.open_file(srt) is False
    assert shown.boxes and ".srt" in shown.boxes[0] and not shown.notices


def test_other_failures_show_an_error_with_the_detail(platform_name, opener, shown, srt, monkeypatch) -> None:
    platform_name("linux")
    opener.raises = FileNotFoundError("xdg-open is not installed")
    # the helper shows the error dialog only for a real Tk / Toplevel parent
    monkeypatch.setattr(plat, "tk", types.SimpleNamespace(Tk=_Window, Toplevel=_Window))
    window = _Window()
    assert plat.open_file(srt, parent=window, error_text="Could not play it.") is False  # type: ignore[arg-type]
    assert shown.errors == [("Could not play it.", "xdg-open is not installed")]
    assert not shown.folders


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
    app_mod.App._open_file(_Window(), srt)  # type: ignore[arg-type]
    assert shown.folders == [(str(tmp_path), srt)]
    assert "No app is set to open .srt files" in shown.notices[0][0]


def test_share_page_browser_open_raises_when_no_app(platform_name, opener, tmp_path) -> None:
    from app.dialogs import share_page

    platform_name("darwin")
    page = tmp_path / "page.html"
    page.write_text("<html></html>", encoding="utf-8")
    opener.default = 1
    with pytest.raises(OSError):
        share_page.open_in_browser(str(page))
