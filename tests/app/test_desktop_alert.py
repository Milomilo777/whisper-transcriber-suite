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
          status: str = "finished", **extra: Any) -> Any:
    return SimpleNamespace(file_path=path, start_time=start, end_time=end, status=status, **extra)


#: What ``[NSApp isActive]`` answers in the current test; ``_app(focused=...)`` sets it.
_NSAPP: dict[str, bool | None] = {"active": False}


def _app(*, aqua: bool = True, focused: bool = False, queue: list[Any] | None = None,
         chime: bool | None = True, config_chime: bool = True, closing: bool = False,
         state: str = "normal", mapped: bool = True, tk_focus: bool = False) -> Any:
    """An App double. ``focused`` = the app is the frontmost one (NSApp active); ``tk_focus`` = Tk
    still names a focus widget. The measured defect case is ``focused=True`` with no Tk focus (the
    person just clicked a tab: no widget has the keyboard focus)."""
    _NSAPP["active"] = focused

    def focus_displayof() -> Any:
        return object() if tk_focus else None

    var = None if chime is None else SimpleNamespace(get=lambda: chime)
    return SimpleNamespace(
        tk=SimpleNamespace(call=lambda *a: "aqua" if aqua else "win32"),
        queue=[] if queue is None else queue, chime_on_complete_var=var,
        app_config={"chime_on_complete": config_chime}, _closing=closing,
        focus_displayof=focus_displayof, state=lambda: state, winfo_ismapped=lambda: mapped)


@pytest.fixture(autouse=True)
def _nsapp_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a Mac there is no NSApp: the answer comes from ``_NSAPP`` (default: not active)."""
    _NSAPP["active"] = False
    monkeypatch.setattr(da, "_ns_app_active", lambda: _NSAPP["active"])


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


def _expected_arg(value: str) -> str:
    """The contract, written independently of the code: text and title are cleaned the same way.

    A process argument cannot hold NUL (exec refuses it) or a lone surrogate (not UTF-8), so NUL is
    dropped and each lone surrogate becomes U+FFFD; everything else, an astral character included,
    arrives unchanged.
    """
    return "".join(chr(0xFFFD) if 0xD800 <= ord(c) <= 0xDFFF else c for c in value if c != chr(0))


@pytest.mark.parametrize("value", [chr(0xD800), chr(0xDC00), "a" + chr(0xD83D) + "b" + chr(0xDE00)])
def test_title_and_text_are_cleaned_the_same_way(value: str) -> None:
    argv = da.build_osascript_argv(value, value)
    assert argv[-2] == argv[-1] == _expected_arg(value)
    assert chr(0xFFFD) in argv[-1]
    for arg in argv:
        arg.encode("utf-8")                  # what exec needs


def test_a_valid_surrogate_pair_character_is_left_alone() -> None:
    emoji = chr(0x1F600)                     # one character: a pair only in UTF-16
    assert da.build_osascript_argv(emoji, "t" + emoji)[-2:] == [emoji, "t" + emoji]


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
    @hypothesis.example(chr(0xD800), chr(0xD800))            # a lone high surrogate, as text and title
    @hypothesis.example(chr(0xDC00), chr(0xDC00))            # a lone low surrogate
    @hypothesis.example("ok", chr(0xD800) + "x" + chr(0xDC00))
    @hypothesis.example(chr(0x1F600), chr(0x1F600) + chr(0x645))  # a valid pair (one emoji) stays
    @hypothesis.given(texts, texts)
    def check(text: str, title: str) -> None:
        argv = da.build_osascript_argv(text, title)
        expected_text, expected_title = (_expected_arg(t) for t in (text, title))
        assert argv[-2:] == [expected_text, expected_title]      # exact: only NUL and lone surrogates change
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
    app.winfo_ismapped = lambda: pytest.fail("the window must not even be asked off macOS")
    da.job_done(app, _task(), 2)
    assert posted == []


def test_nothing_is_posted_while_the_app_is_closing(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(closing=True), _task(), 2)
    assert posted == []


def test_a_broken_app_double_never_raises(posted: list[tuple[str, str]]) -> None:
    da.job_done(object(), _task(), 2)
    da.job_done(SimpleNamespace(), None, 0)
    assert posted == []


def test_an_unreadable_tk_focus_does_not_matter(posted: list[tuple[str, str]]) -> None:
    # The Tk focus is not asked at all: it is wrong both ways on macOS 13 (see window_has_focus).
    app = _app(focused=False)

    def boom() -> Any:
        raise tk.TclError("application has been destroyed")

    app.focus_displayof = boom
    da.job_done(app, _task(), 1)
    assert len(posted) == 1
    app = _app(focused=True)
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
    _NSAPP["active"] = False                  # the person switched to another app
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

def test_the_front_app_with_no_tk_focus_widget_gets_no_banner(
        posted: list[tuple[str, str]]) -> None:
    # The macOS 13 re-test: the person had just clicked the Queue tab, so no Tk widget had the
    # keyboard focus (focus_displayof() is None) while the app was frontmost and the window
    # on screen. A banner there is noise: the result card is in front of them.
    app = _app(focused=True, tk_focus=False)
    assert app.focus_displayof() is None
    da.job_done(app, _task(), 1)
    assert posted == []


def test_the_front_app_with_a_tk_focus_widget_gets_no_banner(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(focused=True, tk_focus=True), _task(), 1)
    assert posted == []


def test_an_inactive_app_gets_a_banner_with_or_without_a_tk_focus_widget(
        posted: list[tuple[str, str]]) -> None:
    # macOS 13: another app in front, or Cmd+H, leaves focus_displayof naming a widget.
    da.job_done(_app(focused=False, tk_focus=True), _task(), 1)
    da.job_done(_app(focused=False, tk_focus=False), _task(), 1)
    assert len(posted) == 2


@pytest.mark.parametrize("state", ["iconic", "withdrawn"])
def test_a_minimised_or_hidden_main_window_gets_a_banner_even_when_the_app_is_active(
        state: str, posted: list[tuple[str, str]]) -> None:
    # macOS 13: iconic leaves the app active; nobody can see the result card.
    da.job_done(_app(focused=True, tk_focus=True, state=state), _task(), 1)
    assert len(posted) == 1


def test_an_unmapped_main_window_gets_a_banner_even_when_the_app_is_active(
        posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(focused=True, mapped=False), _task(), 1)
    assert len(posted) == 1


def test_an_unreadable_window_state_counts_as_in_the_background(
        posted: list[tuple[str, str]]) -> None:
    app = _app(focused=True)

    def boom() -> str:
        raise tk.TclError("application has been destroyed")

    app.state = boom
    da.job_done(app, _task(), 1)
    assert len(posted) == 1
    app = _app(focused=True)
    app.winfo_ismapped = boom                # type: ignore[assignment]
    da.job_done(app, _task(), 1)
    assert len(posted) == 2


def test_an_app_double_without_window_queries_is_judged_by_nsapp_alone(
        posted: list[tuple[str, str]]) -> None:
    app = _app(focused=True)
    del app.state, app.winfo_ismapped
    da.job_done(app, _task(), 1)
    assert posted == []


def test_when_nsapp_cannot_be_asked_the_app_counts_as_in_the_background_and_says_so_once(
        monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]],
        caplog: pytest.LogCaptureFixture) -> None:
    # Unknown stays "background": a banner too many is harmless, a lost one is not. The Tk
    # focus is no replacement (the measured Finder / Cmd+H case leaves a focus widget).
    monkeypatch.setattr(da, "_ns_app_active", lambda: None)
    with caplog.at_level(logging.INFO, logger=da.logger.name):
        da.job_done(_app(tk_focus=True), _task(), 1)
        da.job_done(_app(tk_focus=True), _task(), 1)
        da.job_done(_app(tk_focus=False), _task(), 1)
    assert len(posted) == 3
    assert sum("NSApp" in r.getMessage() for r in caplog.records) == 1


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


# -------------------------------------------------- wording when nothing was written

def test_a_job_with_no_output_files_is_not_called_done(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/m/a.mp4"), 0)
    assert posted == [("Finished, but no output files were found: a.mp4", da.APP_TITLE)]


def test_a_job_that_recognised_no_speech_says_so(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/m/a.mp4", no_speech=True), 3)
    assert posted == [("Finished, but no speech was recognised: a.mp4", da.APP_TITLE)]
    da.job_done(_app(), _task("/m/b.mp4", no_speech=True), 0)
    assert posted[-1][0] == "Finished, but no speech was recognised: b.mp4"


# ---------------------------- the same completion events as the chime, one banner per user job

def _chain(subbed: bool) -> Any:
    return SimpleNamespace(make_subbed_video=subbed)


def test_the_transcription_inside_a_subtitled_video_chain_posts_nothing(
        posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/m/talk.mp4", source_download=_chain(True)), 2)
    assert posted == []                    # the burn's end is that job's last stage


def test_a_chained_transcription_is_not_counted_in_the_queue_summary(
        posted: list[tuple[str, str]]) -> None:
    chained = _task("/m/c.mp4", start=1, end=2, source_download=_chain(True))
    a, b = _task("/m/a.mp4", start=3, end=4), _task("/m/b.mp4", start=5, end=6)
    app = _app(queue=[chained, a, b])
    b.status = "waiting"
    da.job_done(app, chained, 1)
    da.job_done(app, a, 1)
    b.status = "finished"
    da.job_done(app, b, 1)
    assert posted[-1][0] == "Queue done: 2 files transcribed"


def test_a_plain_auto_transcription_after_a_download_still_posts(posted: list[tuple[str, str]]) -> None:
    da.job_done(_app(), _task("/m/talk.mp4", source_download=_chain(False)), 1)
    assert len(posted) == 1


def test_a_finished_download_posts_one_banner(posted: list[tuple[str, str]]) -> None:
    da.download_done(_app(), "/media/clip.mp4")
    assert posted == [("Downloaded: clip.mp4", da.APP_TITLE)]


def test_a_finished_burn_posts_one_banner(posted: list[tuple[str, str]]) -> None:
    da.burn_done(_app(), "/media/clip-subbed.mp4")
    assert posted == [("Subtitled video ready: clip-subbed.mp4", da.APP_TITLE)]


@pytest.mark.parametrize("hook_name", ["download_done", "burn_done"])
def test_download_and_burn_banners_follow_the_same_rules_as_the_job_banner(
        hook_name: str, monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]]) -> None:
    hook = getattr(da, hook_name)
    hook(_app(focused=True), "/m/x.mp4")
    hook(_app(chime=False), "/m/x.mp4")
    hook(_app(aqua=False), "/m/x.mp4")
    hook(_app(closing=True), "/m/x.mp4")
    hook(object(), "/m/x.mp4")
    assert posted == []
    monkeypatch.setattr(da, "_ns_app_active", lambda: False)
    hook(_app(focused=True), "/m/x.mp4")        # another app in front
    assert len(posted) == 1


def test_a_download_or_burn_does_not_touch_the_queue_count(posted: list[tuple[str, str]]) -> None:
    a, b = _task("/m/a.mp4", start=1, end=2), _task("/m/b.mp4", start=3, end=4)
    app = _app(queue=[a, b])
    b.status = "waiting"
    da.job_done(app, a, 1)
    da.download_done(app, "/m/d.mp4")
    da.burn_done(app, "/m/d-subbed.mp4")
    b.status = "finished"
    da.job_done(app, b, 1)
    assert posted[-1][0] == "Queue done: 2 files transcribed"


def _download_task() -> Any:
    return SimpleNamespace(
        url="https://x", folder="/tmp", format_label="mp4", format_info={}, title="T",
        subtitles_enabled=False, subtitle_lang="", detected_language="en", process=None,
        status="running", progress=0, start_time=0.0, end_time=None, cancelled=False,
        paused=False, history_id=0, caption_only=False, make_subbed_video=False)


class _DownloadApp:
    def __init__(self, auto: bool) -> None:
        self.app_config = {"auto_transcribe_after_download": auto}
        self.download_queue: list[Any] = []
        self.download_current = None
        self.history = None
        self.enqueued: list[Any] = []
        self.logs: list[str] = []
        self.download_service = SimpleNamespace(_finish_history=lambda *a, **k: None)

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def refresh_download_queue(self) -> None:
        pass

    def enqueue_transcription_from_download(self, path: str, language: str, source_download: Any = None) -> None:
        self.enqueued.append(path)


def _finish_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, *, auto: bool,
                     status: str = "finished", saved: bool = True) -> tuple[list[str], Any]:
    from app.services.download_service import DownloadService

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"v")
    seen: list[str] = []
    monkeypatch.setattr(da, "download_done", lambda app, path: seen.append(path))
    app = _DownloadApp(auto)
    svc = DownloadService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "process_queue", lambda: None)
    task = _download_task()
    svc._finish(task, status, saved_path=str(media) if saved else None)  # type: ignore[arg-type]
    return seen, task


def test_a_download_that_ends_there_posts_its_banner(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    seen, _task_ = _finish_download(monkeypatch, tmp_path, auto=False)
    assert seen == [str(tmp_path / "clip.mp4")]


def test_a_download_that_hands_off_to_transcription_posts_no_banner_yet(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    seen, task = _finish_download(monkeypatch, tmp_path, auto=True)
    assert task.status == "transcribing"
    assert seen == []                       # the transcription's end is the last stage


def test_a_failed_download_posts_no_banner(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    seen, _t = _finish_download(monkeypatch, tmp_path, auto=False, status="error", saved=False)
    assert seen == []


def test_a_chain_that_ends_finished_posts_the_burn_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import subbed_video

    seen: list[str] = []
    monkeypatch.setattr(da, "burn_done", lambda app, path: seen.append(path))
    dl = SimpleNamespace(status="burning", saved_path="/m/clip.mp4", burned_path=None, progress=0)
    app = SimpleNamespace(download_service=None, log=lambda m: None, refresh_download_queue=lambda: None)
    subbed_video.end_chain(app, dl, "finished", burned="/m/clip-subbed.mp4")
    assert seen == ["/m/clip-subbed.mp4"]
    seen.clear()
    subbed_video.end_chain(app, SimpleNamespace(status="burning", saved_path="/m/c.mp4", burned_path=None,
                                                progress=0), "error", error="x")
    assert seen == []


def test_the_manual_burn_posts_its_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import app as appmod

    seen: list[str] = []
    monkeypatch.setattr(da, "burn_done", lambda app, path: seen.append(path))
    fake = SimpleNamespace(log=lambda m: None, chime_on_complete_var=None, _open_folder=lambda *a, **k: None)
    appmod.App._burn_subs_done(fake, "/m/clip-subbed.mp4")  # type: ignore[arg-type]
    assert seen == ["/m/clip-subbed.mp4"]


# ---------------------------------------------- the queue count resets when the queue goes idle

def test_a_failed_last_job_does_not_carry_the_count_into_the_next_batch(
        posted: list[tuple[str, str]]) -> None:
    a, b = _task("/m/a.mp4", start=1, end=2), _task("/m/b.mp4", start=3, end=4, status="running")
    app = _app(queue=[a, b])
    da.job_done(app, a, 1)                       # b is running: counted, own banner
    b.status = "error"                           # b fails: nothing is waiting or running now
    da.job_ended(app, b)
    c = _task("/m/c.mp4", start=5, end=6)        # a later batch, started within the gap
    app.queue.append(c)
    da.job_done(app, c, 1)
    assert posted[-1][0] == "Done: c.mp4 (1 output file)"


def test_job_ended_keeps_the_count_while_other_jobs_wait_or_run(posted: list[tuple[str, str]]) -> None:
    a, b, c = (_task(f"/m/{n}.mp4", start=i, end=i + 0.5) for i, n in enumerate("abc", 1))
    app = _app(queue=[a, b, c])
    b.status, c.status = "running", "waiting"
    da.job_done(app, a, 1)
    da.job_ended(app, b)                         # b ended in an error, c still waits
    b.status, c.status = "error", "finished"
    da.job_done(app, c, 1)
    assert posted[-1][0] == "Queue done: 2 files transcribed"     # a and c finished, b failed


def test_job_ended_never_raises() -> None:
    da.job_ended(object(), None)
    da.job_ended(SimpleNamespace(queue=None), _task())


def test_finish_task_tells_the_alert_module_for_every_ending(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.transcription_service import TranscriptionService

    ended: list[Any] = []
    monkeypatch.setattr(da, "job_ended", lambda app, task: ended.append(task))
    app = SimpleNamespace(history=None, app_config={}, queue=[], update_overall_progress=lambda: None,
                          log=lambda m: None, show_last_result=lambda t: None,
                          note_job_success=lambda: None)
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)
    for status, keep in (("running", False), ("error", True), ("cancelled", True)):
        task = SimpleNamespace(status=status, cancelled=status == "cancelled", end_time=None,
                               start_time=1.0, output_paths=[], file_path="a.mp4", history_id=0,
                               source_download=None, no_speech=False)
        svc.finish_task({"task": task, "temporary": False}, keep_status=keep)
        assert ended[-1] is task
    assert len(ended) == 3


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


# ------------------------------------------- a chain that fails after its transcript says so

def _failed_chain(error: str, **kw: Any) -> tuple[Any, Any]:
    from app.services import subbed_video

    dl = SimpleNamespace(status="burning", saved_path="/m/clip.mp4", burned_path=None, progress=0, **kw)
    app = SimpleNamespace(download_service=None, log=lambda m: None, refresh_download_queue=lambda: None)
    subbed_video.end_chain(app, dl, "error", error=error)
    return app, dl


def test_a_chain_that_ends_in_an_error_posts_one_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, Any, str]] = []
    monkeypatch.setattr(da, "chain_failed", lambda app, dl, error: seen.append((app, dl, error)))
    app, dl = _failed_chain("Burning the subtitles failed: disk full")
    assert seen == [(app, dl, "Burning the subtitles failed: disk full")]


def test_a_cancelled_chain_posts_no_failure_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import subbed_video

    monkeypatch.setattr(da, "chain_failed", lambda *a: pytest.fail("a cancel is not a failure"))
    dl = SimpleNamespace(status="burning", saved_path="/m/c.mp4", burned_path=None, progress=0)
    app = SimpleNamespace(download_service=None, log=lambda m: None, refresh_download_queue=lambda: None)
    subbed_video.end_chain(app, dl, "cancelled")


def test_the_failure_banner_names_the_file(posted: list[tuple[str, str]]) -> None:
    dl = SimpleNamespace(saved_path="/m/clip.mp4", title="T")
    da.chain_failed(_app(), dl, "The transcription wrote no .srt file; no subtitled video was made.")
    assert posted == [("Subtitled video not made: clip.mp4", da.APP_TITLE)]


def test_the_failure_banner_says_when_no_speech_was_the_cause(posted: list[tuple[str, str]]) -> None:
    dl = SimpleNamespace(saved_path="/m/clip.mp4", title="T")
    da.chain_failed(_app(), dl, "No speech was found; no subtitled video was made.")
    assert posted == [("Subtitled video not made, no speech was found: clip.mp4", da.APP_TITLE)]


def test_the_failure_banner_falls_back_to_the_title_when_the_file_is_unknown(
        posted: list[tuple[str, str]]) -> None:
    da.chain_failed(_app(), SimpleNamespace(saved_path=None, title="Good news"), "x")
    assert posted == [("Subtitled video not made: Good news", da.APP_TITLE)]


def test_the_failure_banner_follows_the_same_rules_as_the_others(
        monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]]) -> None:
    dl = SimpleNamespace(saved_path="/m/x.mp4", title="T")
    da.chain_failed(_app(focused=True), dl, "x")
    da.chain_failed(_app(chime=False), dl, "x")
    da.chain_failed(_app(aqua=False), dl, "x")
    da.chain_failed(object(), object(), "x")
    assert posted == []


def test_the_failed_chain_end_never_raises_into_end_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "post_notification", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    _failed_chain("x")        # end_chain returns normally


def test_cancelling_a_waiting_task_resets_the_queue_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import app as appmod
    from core.task import TranscriptionTask

    ended: list[Any] = []
    monkeypatch.setattr(da, "job_ended", lambda app, task: ended.append(task))
    task = TranscriptionTask("/m/a.mp4")
    fake = SimpleNamespace(
        transcription_service=SimpleNamespace(send_control=lambda t, a: False), log=lambda m: None,
        _release_waiting_download=lambda t: None, refresh=lambda: None)
    appmod.App.cancel(fake, task)  # type: ignore[arg-type]
    assert ended == [task]


# ------------------------------------------------------- off aqua nothing is started at all

def test_the_end_of_job_download_burn_and_chain_hooks_are_no_ops_off_aqua(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*a: Any, **k: Any) -> Any:
        pytest.fail("a thread or process was started off macOS")

    monkeypatch.setattr(da.threading, "Thread", forbidden)
    monkeypatch.setattr(da.subprocess, "run", forbidden)
    monkeypatch.setattr(da.subprocess, "Popen", forbidden)
    for app in (_app(aqua=False), object()):
        da.job_ended(app, _task())
        da.download_done(app, "/m/a.mp4")
        da.burn_done(app, "/m/a-subbed.mp4")
        da.chain_failed(app, SimpleNamespace(saved_path="/m/a.mp4", title="T"), "x")
        da.job_done(app, _task(), 1)
    assert da._batch == {"count": 0, "last_end": None}
    assert da._threads == []
