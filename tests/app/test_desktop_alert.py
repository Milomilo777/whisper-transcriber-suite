"""Desktop notification when a transcription job finishes on macOS (card C2.73).

``app.desktop_alert`` posts through ``osascript`` with the text as an argument-list item, never
spliced into the script. Aqua, the focus check and the subprocess are faked at the module
boundary, so the file runs on every OS; the real ``osascript`` was exercised in the macOS 13 VM
(see docs/MACOS_BUILD_NOTES.md).
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from typing import Any

import pytest

from app import desktop_alert as da
from app import mac_native

_REAL_NS_APP_ACTIVE = da._ns_app_active   # before the autouse stub replaces it

# ----------------------------------------------------------------------------- fakes


def _task(path: str = "/media/talk.mp4", *, start: float | None = 100.0, end: float | None = 160.0,
          status: str = "finished") -> Any:
    return SimpleNamespace(file_path=path, start_time=start, end_time=end, status=status)


def _app(*, aqua: bool = True, focused: bool = False, queue: list[Any] | None = None,
         chime: bool | None = True, config_chime: bool = True, closing: bool = False,
         state: str = "normal") -> Any:
    def focus_displayof() -> Any:
        return object() if focused else None

    var = None if chime is None else SimpleNamespace(get=lambda: chime)
    return SimpleNamespace(
        tk=SimpleNamespace(call=lambda *a: "aqua" if aqua else "win32"),
        queue=[] if queue is None else queue, chime_on_complete_var=var,
        app_config={"chime_on_complete": config_chime}, _closing=closing,
        focus_displayof=focus_displayof, state=lambda: state)


@pytest.fixture(autouse=True)
def _nsapp_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a Mac there is no NSApp: the default answer is "the app is the active one"."""
    monkeypatch.setattr(da, "_ns_app_active", lambda: True)


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every (text, title) handed to ``post_notification`` during the test."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(da, "post_notification", lambda text, title: calls.append((text, title)))
    return calls


# ------------------------------------------------------------------ the osascript argv

def test_argv_shape_is_fixed_and_text_goes_after_the_double_dash() -> None:
    argv = da.build_osascript_argv("done", "Title")
    assert argv[0] == da.OSASCRIPT
    assert argv[-3:] == ["--", "done", "Title"]
    scripts = [argv[i + 1] for i, a in enumerate(argv[:-3]) if a == "-e"]
    assert scripts == ["on run argv",
                       "display notification (item 1 of argv) with title (item 2 of argv)",
                       "end run"]
    assert len(argv) == 1 + 2 * 3 + 3


def test_argv_is_a_list_of_strings_never_one_command_line() -> None:
    argv = da.build_osascript_argv('say "hi" & rm -rf /', "'; do shell script \"x\"")
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    assert argv[-2:] == ['say "hi" & rm -rf /', "'; do shell script \"x\""]


NASTY = ["-x", "--", "-e", "\\", "\\\\n", "a\nb", "a\r\nb", '"', "'", "`", "$(x)", " ", "",
         "فارسی " + chr(0x200C) + " متن", "日本語", "😀", "tab\there"]


@pytest.mark.parametrize("text", NASTY)
def test_nasty_text_round_trips_exactly(text: str) -> None:
    assert da.build_osascript_argv(text, text)[-2:] == [text, text]


def test_a_nul_character_cannot_reach_exec() -> None:
    argv = da.build_osascript_argv("a\x00b", "t\x00")
    assert argv[-2:] == ["ab", "t"]
    subprocess.list2cmdline(argv)           # no exception; a NUL would make Popen raise ValueError


def test_a_lone_surrogate_is_replaced_not_fatal() -> None:
    argv = da.build_osascript_argv("bad\ud800name", "t")
    assert argv[-2] == "bad�name"
    argv[-2].encode("utf-8")


def test_property_argv_round_trips_for_any_unicode() -> None:
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")
    pieces = st.one_of(
        st.characters(),
        st.sampled_from(list("-" + chr(34) + "'" + chr(92) + chr(10) + chr(13) + chr(9) + " $`;&|*?<>(){}#~")),
        st.sampled_from(["فارسی", "ی", chr(0x200C), "日本", chr(0x202E), "--", "-e"]))
    body = st.lists(pieces, max_size=40).map("".join)
    texts = st.one_of(
        body,
        body.map(lambda tail: "-" + tail),                  # leading dash
        body.map(lambda tail: "--" + tail),
    )
    reference = da.build_osascript_argv("x", "y")[:-2]

    @hypothesis.settings(max_examples=300, deadline=None)
    @hypothesis.given(texts, texts)
    def check(text: str, title: str) -> None:
        argv = da.build_osascript_argv(text, title)
        expected_text, expected_title = (t.replace("\x00", "") for t in (text, title))
        assert argv[-2:] == [expected_text, expected_title]      # exact: nothing escaped or trimmed
        assert argv[:-2] == reference                            # the script never contains the text
        assert argv[-3] == "--" and isinstance(argv, list)
        assert all(isinstance(a, str) and "\x00" not in a for a in argv)

    check()


def test_property_surrogates_and_nul_are_cleaned_for_any_input() -> None:
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")
    anything = st.text(alphabet=st.characters(exclude_categories=()))

    @hypothesis.settings(max_examples=200, deadline=None)
    @hypothesis.given(anything, anything)
    def check(text: str, title: str) -> None:
        for arg in da.build_osascript_argv(text, title):
            assert "\x00" not in arg
            arg.encode("utf-8")                                 # must be sendable to exec

    check()


# ------------------------------------------------------------- posting without blocking

def test_posting_returns_at_once_even_if_osascript_hangs(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Any) -> None:
    fake = tmp_path / "osascript"
    fake.write_text("x")
    monkeypatch.setattr(da, "OSASCRIPT", str(fake))
    gate, started = threading.Event(), threading.Event()
    seen: list[list[str]] = []

    def slow_run(argv: list[str], **kwargs: Any) -> Any:
        seen.append(argv)
        started.set()
        gate.wait(10)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(da.subprocess, "run", slow_run)
    t0 = time.monotonic()
    da.post_notification("body", "title")
    assert time.monotonic() - t0 < 1.0
    assert started.wait(5)
    assert seen[0][-2:] == ["body", "title"]
    gate.set()
    da.join_pending_for_tests()


def test_subprocess_is_started_without_a_shell_and_with_a_timeout(monkeypatch: pytest.MonkeyPatch,
                                                                  tmp_path: Any) -> None:
    fake = tmp_path / "osascript"
    fake.write_text("x")
    monkeypatch.setattr(da, "OSASCRIPT", str(fake))
    captured: dict[str, Any] = {}

    def run(argv: Any, **kwargs: Any) -> Any:
        captured.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(da.subprocess, "run", run)
    da.post_notification("b", "t")
    da.join_pending_for_tests()
    assert isinstance(captured["argv"], list)
    assert not captured.get("shell")
    assert captured["timeout"] == da.OSASCRIPT_TIMEOUT_S
    assert captured["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("failure", [
    FileNotFoundError("no osascript"), subprocess.TimeoutExpired("osascript", 15), OSError("denied"),
    PermissionError("nope"), ValueError("embedded null byte"),
])
def test_a_failing_osascript_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
                                                  caplog: pytest.LogCaptureFixture, failure: Exception) -> None:
    fake = tmp_path / "osascript"
    fake.write_text("x")
    monkeypatch.setattr(da, "OSASCRIPT", str(fake))

    def run(*a: Any, **k: Any) -> Any:
        raise failure

    monkeypatch.setattr(da.subprocess, "run", run)
    with caplog.at_level(logging.DEBUG, logger=da.logger.name):
        da.post_notification("b", "t")
        da.join_pending_for_tests()
    assert any("notification" in r.getMessage().lower() for r in caplog.records)


def test_a_nonzero_exit_is_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
                                  caplog: pytest.LogCaptureFixture) -> None:
    fake = tmp_path / "osascript"
    fake.write_text("x")
    monkeypatch.setattr(da, "OSASCRIPT", str(fake))
    monkeypatch.setattr(da.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr=b"execution error"))
    with caplog.at_level(logging.DEBUG, logger=da.logger.name):
        da.post_notification("b", "t")
        da.join_pending_for_tests()
    assert "execution error" in caplog.text


def test_a_missing_osascript_starts_nothing_and_says_so_once(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Any,
                                                             caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(da, "OSASCRIPT", str(tmp_path / "absent"))
    started: list[Any] = []
    monkeypatch.setattr(da.subprocess, "run", lambda *a, **k: started.append(a))
    with caplog.at_level(logging.INFO, logger=da.logger.name):
        da.post_notification("b", "t")
        da.post_notification("b", "t")
    da.join_pending_for_tests()
    assert started == []
    assert sum("osascript" in r.getMessage() for r in caplog.records) == 1


# ------------------------------------------------------------ when a job finishes

def test_an_unfocused_mac_window_gets_one_notification(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/media/talk.mp4"), 3)
    assert posted == [("Done: talk.mp4 (3 output files)", da.APP_TITLE)]


def test_one_output_file_is_singular(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/m/a.mp3"), 1)
    assert posted[0][0] == "Done: a.mp3 (1 output file)"


def test_a_persian_file_name_is_passed_on_unchanged(posted: list[tuple[str, str]]) -> None:
    name = "مصاحبه " + chr(0x200C) + " فارسی.mp4"
    da.job_done(_app(), _task("/m/" + name), 2)
    assert posted[0][0] == f"Done: {name} (2 output files)"


def test_a_focused_window_gets_nothing(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(focused=True), _task(), 2)
    assert posted == []


def test_the_chime_setting_off_means_no_notification(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(chime=False), _task(), 2)
    assert posted == []


def test_without_the_menu_variable_the_saved_setting_decides(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(chime=None, config_chime=False), _task(), 1)
    assert posted == []
    da.job_done(_app(chime=None, config_chime=True), _task(), 1)
    assert len(posted) == 1


def test_other_systems_are_left_completely_alone(posted: list[tuple[str, str]]) -> None:
    app = _app(aqua=False)
    app.focus_displayof = lambda: pytest.fail("the focus must not even be asked off macOS")
    da.job_done(app, _task(), 2)
    assert posted == []


def test_nothing_is_posted_while_the_app_is_closing(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(closing=True), _task(), 2)
    assert posted == []


def test_a_broken_app_double_never_raises(posted: list[tuple[str, str]]) -> None:
    da.job_done(object(), _task(), 2)
    da.job_done(SimpleNamespace(), None, 0)
    assert posted == []


def test_an_unreadable_focus_counts_as_unfocused(posted: list[tuple[str, str]]) -> None:
    app = _app()

    def boom() -> Any:
        raise tk.TclError("application has been destroyed")

    app.focus_displayof = boom
    da.job_done(app, _task(), 1)
    assert len(posted) == 1


# ------------------------------------------------------------------ one per queue

def test_a_queue_gets_one_summary_instead_of_the_last_job_notification(
        posted: list[tuple[str, str]]) -> None:
    t1, t2, t3 = (_task(f"/m/{n}.mp4", start=10.0 * i, end=10.0 * i + 9) for i, n in enumerate("abc", 1))
    queue = [t1, t2, t3]
    t2.status = t3.status = "waiting"
    app = _app(queue=queue)
    da.job_done(app, t1, 1)                      # b and c still waiting: its own notification
    t2.status, t3.status = "finished", "running"
    da.job_done(app, t2, 1)
    t3.status = "finished"
    da.job_done(app, t3, 1)                      # the queue is empty: one summary
    assert [text for text, _title in posted] == [
        "Done: a.mp4 (1 output file)", "Done: b.mp4 (1 output file)", "Queue done: 3 files transcribed"]
    assert posted[2][1] == da.APP_TITLE


def test_the_next_single_job_after_a_queue_is_a_plain_notification(posted: list[tuple[str, str]]) -> None:
    a, b = _task("/m/a.mp4", start=10, end=20), _task("/m/b.mp4", start=21, end=30)
    app = _app(queue=[a, b])
    b.status = "waiting"
    da.job_done(app, a, 1)
    b.status = "finished"
    da.job_done(app, b, 1)
    c = _task("/m/c.mp4", start=40, end=50)
    app.queue.append(c)
    da.job_done(app, c, 2)
    assert posted[-1][0] == "Done: c.mp4 (2 output files)"
    assert len(posted) == 3


def test_a_stale_count_from_a_queue_that_ended_in_an_error_is_forgotten(
        posted: list[tuple[str, str]]) -> None:
    a = _task("/m/a.mp4", start=10, end=20)
    err = _task("/m/err.mp4", start=21, end=22, status="error")
    app = _app(queue=[a, err])
    err_pending = SimpleNamespace(status="waiting")
    app.queue.append(err_pending)
    da.job_done(app, a, 1)                        # b waiting: counted, own notification
    app.queue.remove(err_pending)                 # the next job failed: no hook ever ran for it
    later = _task("/m/later.mp4", start=20 + da.BATCH_GAP_S + 5, end=20 + da.BATCH_GAP_S + 15)
    app.queue.append(later)
    da.job_done(app, later, 1)
    assert posted[-1][0] == "Done: later.mp4 (1 output file)"      # not "Queue done: 2 files"


def test_a_summary_is_skipped_when_a_window_is_focused_but_the_count_resets(
        posted: list[tuple[str, str]]) -> None:
    a, b = _task("/m/a.mp4", start=1, end=2), _task("/m/b.mp4", start=3, end=4)
    app = _app(queue=[a, b], focused=True)
    b.status = "waiting"
    da.job_done(app, a, 1)
    b.status = "finished"
    da.job_done(app, b, 1)
    assert posted == []
    app.focus_displayof = lambda: None
    c = _task("/m/c.mp4", start=5, end=6)
    app.queue.append(c)
    da.job_done(app, c, 1)
    assert [t for t, _ in posted] == ["Done: c.mp4 (1 output file)"]


def test_paused_jobs_do_not_hold_the_summary_back(posted: list[tuple[str, str]]) -> None:
    a, b = _task("/m/a.mp4", start=1, end=2), _task("/m/b.mp4", start=3, end=4)
    paused = SimpleNamespace(status="paused")
    app = _app(queue=[a, b, paused])
    b.status = "waiting"
    da.job_done(app, a, 1)
    b.status = "finished"
    da.job_done(app, b, 1)
    assert posted[-1][0] == "Queue done: 2 files transcribed"


# ---------------------------------------------------------------- what "focused" means

def test_a_minimised_main_window_counts_as_not_focused(posted: list[tuple[str, str]]) -> None:
    # macOS 13: iconic leaves the app active AND a focus widget; nobody can see the result card.
    da.job_done(_app(focused=True, state="iconic"), _task(), 1)
    assert len(posted) == 1


def test_a_withdrawn_main_window_counts_as_not_focused(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(focused=True, state="withdrawn"), _task(), 1)
    assert len(posted) == 1


def test_an_inactive_app_with_a_leftover_tk_focus_counts_as_not_focused(
        monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]]) -> None:
    # macOS 13: another app in front, or Cmd+H, leaves focus_displayof naming a widget.
    monkeypatch.setattr(da, "_ns_app_active", lambda: False)
    da.job_done(_app(focused=True), _task(), 1)
    assert len(posted) == 1


def test_when_nsapp_cannot_be_asked_the_tk_focus_decides(
        monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]]) -> None:
    monkeypatch.setattr(da, "_ns_app_active", lambda: None)
    da.job_done(_app(focused=True), _task(), 1)
    assert posted == []
    da.job_done(_app(focused=False), _task(), 1)
    assert len(posted) == 1


def test_an_app_double_without_a_window_state_is_judged_by_focus_alone(
        posted: list[tuple[str, str]]) -> None:
    app = _app(focused=True)
    del app.state
    da.job_done(app, _task(), 1)
    assert posted == []


def test_an_unreadable_window_state_counts_as_not_focused(posted: list[tuple[str, str]]) -> None:
    app = _app(focused=True)

    def boom() -> str:
        raise tk.TclError("application has been destroyed")

    app.state = boom
    da.job_done(app, _task(), 1)
    assert len(posted) == 1


def test_nsapp_is_not_asked_off_macOS(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "_ns_app_active", _REAL_NS_APP_ACTIVE)   # the autouse stub off
    monkeypatch.setattr(da, "_on_mac", lambda: False)
    assert da._ns_app_active() is None


def test_nsapp_answer_failures_are_none_not_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "_ns_app_active", _REAL_NS_APP_ACTIVE)
    monkeypatch.setattr(da, "_on_mac", lambda: True)
    monkeypatch.setattr(da.ctypes.util, "find_library", lambda name: None)
    assert da._ns_app_active() is None
    monkeypatch.setattr(da.ctypes.util, "find_library", lambda name: "/nonexistent/libobjc.dylib")
    assert da._ns_app_active() is None          # the library cannot be loaded: None, not OSError


# ------------------------------------------------------------------- menu wording

def test_the_menu_wording_is_neutral_on_macOS_only() -> None:
    assert da.chime_menu_label(_app(aqua=True)) == da.MAC_CHIME_LABEL
    assert da.chime_menu_label(_app(aqua=False)) == "Chime on completion"
    assert da.chime_menu_label(object()) == "Chime on completion"


# ----------------------------------------------------------- the real hook in the app

def test_the_last_result_card_calls_the_hook_and_keeps_the_tray_toast(monkeypatch: pytest.MonkeyPatch,
                                                                       tmp_path: Any) -> None:
    from unittest.mock import MagicMock
    from tkinter import ttk

    from app import app as appmod
    from core.task import TranscriptionTask

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    try:
        out = tmp_path / "talk.srt"
        out.write_text("1\n", encoding="utf-8")
        task = TranscriptionTask(str(tmp_path / "talk.mp4"))
        task.output_paths = [str(out)]
        hook = MagicMock()
        monkeypatch.setattr(appmod.desktop_alert, "job_done", hook)
        fake = SimpleNamespace(
            last_result_frame=ttk.Frame(root), last_result_empty_label=MagicMock(),
            last_result_body=ttk.Frame(root), tray=MagicMock(), log=MagicMock(), nb=MagicMock(),
            t1=object(), app_config={}, chime_on_complete_var=None, _open_file=MagicMock(),
            _open_folder=MagicMock(), open_transcript_viewer_for=MagicMock(),
            _save_shareable_page_for=MagicMock())
        appmod.App.show_last_result(fake, task)  # type: ignore[arg-type]
        hook.assert_called_once_with(fake, task, 1)
        fake.tray.notify.assert_called_once_with(
            "Whisper Transcriber Suite — transcription done", "Wrote 1 output file for talk.mp4")
    finally:
        root.destroy()


def test_aqua_probe_is_the_one_the_module_uses(monkeypatch: pytest.MonkeyPatch) -> None:
    assert da.mac_native is mac_native


# ------------------------------------------------- packaging: the new modules join every spec

@pytest.mark.parametrize("spec", [
    "whisper_project_onefile.spec", "whisper_project_onedir.spec",
    "platform/macos/pyinstaller/whisper_project_mac.spec"])
def test_the_new_modules_are_hidden_imports_of_every_pyinstaller_spec(spec: str) -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / spec).read_text(encoding="utf-8")
    for module in ("app.desktop_alert", "app.theme.system_fonts"):
        assert f"'{module}'," in text, f"{module} missing from {spec}"
