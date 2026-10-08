"""File input: pasted paths, files passed at launch, the watched folder, the window position.

* "Copy as path" in Explorer quotes the path; a paste can bring spaces along.
* A file dropped on the shortcut and macOS's ``-psn_...`` argument used to stop the app
  with exit code 2 before any window appeared; the Explorer "Transcribe with" entry ran
  under pythonw with its output going nowhere.
* The watched folder queued half-copied files, macOS ``._`` sidecars and yt-dlp part
  files, and queued a file twice when a second event came during the model load.
* A window position saved on a monitor that is gone opened the window off-screen.
"""
from __future__ import annotations

import io
import sys
import types
from typing import Any, Callable

import pytest

import gui
from app import app as app_mod
from app.app import App
from core import watcher as w
from tests.core.test_watcher import _Event, _install_fake_watchdog


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _fake_app(**extra: Any) -> types.SimpleNamespace:
    logs: list[str] = []
    fake = types.SimpleNamespace(
        fv=_Var(), log=logs.append, logs=logs, queue=[], pb={},
        nb=types.SimpleNamespace(select=lambda *_: None), t1="t1", t2="t2",
        _ensure_transcribe_ready=lambda: True, _apply_task_options=lambda t: None,
        refresh=lambda: None,
    )
    for key, value in extra.items():
        setattr(fake, key, value)
    return fake


# --- pasted paths -------------------------------------------------------------------


@pytest.fixture
def media(tmp_path) -> str:
    path = tmp_path / "my talk.mp4"
    path.write_bytes(b"x")
    return str(path)


@pytest.mark.parametrize("shape", [
    "{p}", '"{p}"', " {p}", "{p}  ", ' "{p}" ', "'{p}'", "{p}\n",
])
def test_add_queues_the_clean_path(media: str, shape: str) -> None:
    fake = _fake_app()
    fake.fv.set(shape.format(p=media))
    App.add(fake)  # type: ignore[arg-type]
    assert [t.file_path for t in fake.queue] == [media]


def test_add_accepts_a_file_uri(media: str) -> None:
    from pathlib import Path

    fake = _fake_app()
    fake.fv.set(Path(media).as_uri())
    App.add(fake)  # type: ignore[arg-type]
    assert [t.file_path for t in fake.queue] == [media]


def test_add_still_reports_a_missing_file(tmp_path) -> None:
    fake = _fake_app()
    fake.fv.set(f'"{tmp_path / "gone.mp4"}"')
    App.add(fake)  # type: ignore[arg-type]
    assert fake.queue == [] and fake.logs[-1].startswith("File not found")


def test_clean_pasted_path_leaves_inner_quotes_alone() -> None:
    assert app_mod._clean_pasted_path('a "b" c') == 'a "b" c'
    assert app_mod._clean_pasted_path('"') == '"'
    assert app_mod._clean_pasted_path("https://x.test/v") == "https://x.test/v"


# --- launch arguments -----------------------------------------------------------------


@pytest.mark.parametrize(("argv", "cli", "files"), [
    ([], [], []),
    (["-psn_0_12345"], [], []),
    (["{a}"], [], ["{a}"]),
    (["{a}", "{b}"], [], ["{a}", "{b}"]),
    (["-psn_0_1", "{a}"], [], ["{a}"]),
    (["transcribe", "{a}"], ["transcribe", "{a}"], []),
    (["serve", "--port", "0"], ["serve", "--port", "0"], []),
    (["--help"], ["--help"], []),
    # A mistyped subcommand still reaches the parser (usage error, exit 2).
    (["transcibe", "{a}"], ["transcibe", "{a}"], []),
    (["Serve"], ["Serve"], []),
    (["{a}", "--model", "tiny"], ["{a}", "--model", "tiny"], []),
])
def test_split_launch_args(tmp_path, argv: list[str], cli: list[str], files: list[str]) -> None:
    names = {"a": str(tmp_path / "My Video.mp4"), "b": str(tmp_path / "b.mp3")}
    for path in names.values():
        open(path, "wb").close()

    def fill(items: list[str]) -> list[str]:
        return [item.format(**names) for item in items]

    assert gui._split_launch_args(fill(argv)) == (fill(cli), fill(files))


def test_subcommand_list_matches_the_parser() -> None:
    parser = gui._build_argparser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert set(gui._SUBCOMMANDS) == set(sub.choices or ())  # type: ignore[arg-type]


@pytest.mark.parametrize("argv", [["-psn_0_12345"], ["{media}"]])
def test_main_launches_the_window_instead_of_exiting(
    monkeypatch: pytest.MonkeyPatch, media: str, argv: list[str],
) -> None:
    import app as app_pkg

    argv = [a.format(media=media) for a in argv]
    launched: list[Any] = []
    monkeypatch.setattr(app_pkg, "run", lambda open_paths=None: launched.append(open_paths))
    monkeypatch.setattr(sys, "argv", ["gui.py", *argv])
    assert gui.main() == 0
    files = [a for a in argv if not a.startswith("-psn_")]
    assert launched == [files or None]


def test_cli_output_goes_to_a_log_without_a_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    import core.config as config_mod

    monkeypatch.setattr(config_mod, "user_log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = gui._log_missing_stdio("transcribe")
    try:
        assert path is not None
        print("progress line")
        print("error line", file=sys.stderr)
    finally:
        assert sys.stdout is not None
        sys.stdout.close()
    with open(path, encoding="utf-8") as f:
        body = f.read()
    assert "transcribe" in body and "progress line" in body and "error line" in body


def test_cli_without_a_log_folder_still_runs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import core.config as config_mod

    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    monkeypatch.setattr(config_mod, "user_log_dir", lambda: blocker / "logs")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert gui._log_missing_stdio("transcribe") is None


def test_cli_with_a_console_writes_no_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert gui._log_missing_stdio("transcribe") is None


def test_open_paths_picks_a_single_file(media: str) -> None:
    fake = _fake_app(_bulk_enqueue=lambda paths: len(paths))
    App.open_paths(fake, [media])  # type: ignore[arg-type]
    assert fake.fv.get() == media


def test_open_paths_reports_a_missing_file(tmp_path) -> None:
    fake = _fake_app(_bulk_enqueue=lambda paths: len(paths))
    App.open_paths(fake, [str(tmp_path / "gone.mp4")])  # type: ignore[arg-type]
    assert fake.fv.get() == "" and "Ignored 1" in fake.logs[-1]


# --- watched folder -----------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "clip.f137.mp4", "clip.f251.webm", "clip.f251-drc.webm", "clip.f18.mp4", "clip.fhls-1080p.mp4",
    "clip.fdash-720p.mp4", "clip.temp.mp4", "Clip.F137.MP4",
])
def test_ytdlp_part_files_are_intermediates(name: str) -> None:
    assert w.is_download_intermediate(name)


@pytest.mark.parametrize("name", [
    "clip.mp4", "my.final.mp4", "song.feat.mp3", "talk.f.mp4", "f137.mp4", "a.fun-day.mp4",
    "Lecture.f1.mp3", "My.Talk.f2.mkv",
])
def test_ordinary_names_are_not_intermediates(name: str) -> None:
    assert not w.is_download_intermediate(name)


def test_appledouble_files_are_not_media() -> None:
    assert not w.is_media_file("._clip.mp4")
    assert w.is_media_file("clip.mp4")


def test_watcher_skips_sidecars_and_part_files(monkeypatch, tmp_path) -> None:
    instances = _install_fake_watchdog(monkeypatch, w)
    got: list[str] = []
    fw = w.FolderWatcher(str(tmp_path), got.append)
    fw.start()
    handler = instances[-1].handler
    for name in ("._clip.mp4", "clip.f137.mp4", "clip.temp.mp4", "clip.mp4"):
        handler.on_created(_Event(src_path=str(tmp_path / name)))
    fw.stop()
    assert got == [str(tmp_path / "clip.mp4")]


def test_stability_needs_two_unchanged_checks() -> None:
    step = app_mod._watch_stability_step
    assert step((10, 1), (20, 2), 0) == ("wait", 0)
    assert step((20, 2), (20, 2), 0) == ("wait", 1)
    assert step((20, 2), (20, 2), 1) == ("ready", 2)
    # Same size but a newer modification time: still being written.
    assert step((20, 2), (20, 3), 1) == ("wait", 0)


def test_an_empty_file_is_dropped_after_a_long_wait() -> None:
    step = app_mod._watch_stability_step
    assert step((0, 1), (0, 1), 1)[0] == "wait"
    last = app_mod._WATCH_EMPTY_CHECKS - 1
    assert step((0, 1), (0, 1), last) == ("empty", app_mod._WATCH_EMPTY_CHECKS)


class _After:
    """Collects after() callbacks so a test runs them by hand."""

    def __init__(self) -> None:
        self.pending: dict[str, Callable[[], None]] = {}
        self._n = 0

    def after(self, _ms: int, fn: Callable[[], None]) -> str:
        self._n += 1
        aid = f"after#{self._n}"
        self.pending[aid] = fn
        return aid

    def after_cancel(self, aid: str) -> None:
        self.pending.pop(aid, None)

    def run_all(self) -> None:
        while self.pending:
            aid = next(iter(self.pending))
            self.pending.pop(aid)()


def _watch_app(ready_callbacks: list[Callable[[], None]]) -> tuple[types.SimpleNamespace, _After]:
    timer = _After()
    fake = _fake_app(
        _closing=False, _watched_after_ids={}, _watched_pending=set(),
        after=timer.after, after_cancel=timer.after_cancel,
        _when_worker_ready=lambda on_ready, **_k: ready_callbacks.append(on_ready),
    )
    fake._active_dup_in_queue = lambda p: App._active_dup_in_queue(fake, p)  # type: ignore[arg-type]
    return fake, timer


def test_second_event_during_model_load_queues_once(media: str) -> None:
    ready: list[Callable[[], None]] = []
    fake, timer = _watch_app(ready)
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    timer.run_all()
    assert len(ready) == 1
    # Windows fires another event for the same file while the model loads.
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    timer.run_all()
    for on_ready in ready:
        on_ready()
    assert [t.file_path for t in fake.queue] == [media]
    assert fake._watched_pending == set()


def test_a_file_removed_during_the_model_load_is_not_queued(media: str) -> None:
    import os

    ready: list[Callable[[], None]] = []
    fake, timer = _watch_app(ready)
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    timer.run_all()
    os.remove(media)
    ready[0]()
    assert fake.queue == [] and "moved or deleted" in fake.logs[-1]


def test_a_file_written_again_during_the_model_load_waits_again(media: str) -> None:
    ready: list[Callable[[], None]] = []
    fake, timer = _watch_app(ready)
    fake._enqueue_watched_file = lambda p: App._enqueue_watched_file(fake, p)  # type: ignore[arg-type]
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    timer.run_all()
    with open(media, "ab") as f:
        f.write(b"resumed copy")
    ready.pop()()
    assert fake.queue == [] and timer.pending, "queued a file still being written"
    timer.run_all()
    ready.pop()()
    assert [t.file_path for t in fake.queue] == [media]


def test_a_worker_start_failure_does_not_block_the_file(media: str) -> None:
    ready: list[Callable[[], None]] = []
    fake, timer = _watch_app(ready)

    def fail(*_a: Any, **_k: Any) -> None:
        raise OSError("spawn failed")

    fake._when_worker_ready = fail
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    with pytest.raises(OSError):
        timer.run_all()
    assert fake._watched_pending == set()
    fake._when_worker_ready = lambda on_ready, **_k: ready.append(on_ready)
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    timer.run_all()
    ready[0]()
    assert [t.file_path for t in fake.queue] == [media]


def test_a_growing_file_waits_until_it_stops(media: str) -> None:
    ready: list[Callable[[], None]] = []
    fake, timer = _watch_app(ready)
    App._enqueue_watched_file(fake, media)  # type: ignore[arg-type]
    for _ in range(3):
        with open(media, "ab") as f:
            f.write(b"more")
        aid, fn = timer.pending.popitem()
        fn()
        assert ready == [], "queued while the file was still growing"
    timer.run_all()
    assert len(ready) == 1


# --- window position -------------------------------------------------------------------------


def _one_monitor(x: int, y: int) -> bool:
    return 0 <= x < 1920 and 0 <= y < 1080


@pytest.mark.parametrize(("geom", "visible"), [
    ("1200x800+100+50", True),
    ("1200x800+-2500+100", False),
    ("1200x800+2000+100", False),
    ("1200x800+100+-900", False),
    ("1200x800+-500+100", True),
    ("1200x800", True),
    ("garbage", True),
])
def test_saved_geometry_visibility(geom: str, visible: bool) -> None:
    assert app_mod._saved_geometry_visible(geom, _one_monitor) is visible


@pytest.mark.skipif(sys.platform != "win32", reason="asks Windows for its monitors")
def test_point_check_asks_windows() -> None:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    assert app_mod._point_on_a_monitor(left + 5, top + 5) or app_mod._point_on_a_monitor(10, 10)
    assert not app_mod._point_on_a_monitor(left + width + 5000, top + height + 5000)
