"""Download fixes from the 2026-10 review: non-Latin titles, history rows,
stale yt-dlp advice, the updater on unofficial builds, rolling auto captions
in the subtitle extras, cancel leftovers, regional caption tracks, invisible
URL marks, time-range file names and the SMTV "all parts" lookup.

Hermetic: yt-dlp, the network and Tk are faked.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest

from app.domain import languages
from app.domain.tasks import VideoDownloadTask
from app.services import download_service as ds
from app.services.download_service import DownloadService
from core import js_runtime as js
from core import yt_dlp_update as ytu
from core.history import HistoryDB
from core.integrations import smtv

if "faster_whisper" not in sys.modules:
    _fw = types.ModuleType("faster_whisper")
    _fw.WhisperModel = object  # type: ignore[attr-defined]
    sys.modules["faster_whisper"] = _fw

from app.app import App  # noqa: E402


def _task(folder: str = "C:/out", **kwargs) -> VideoDownloadTask:
    return VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc",
        folder=folder,
        format_label="x",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"},
        },
        **kwargs,
    )


def _app(**extra) -> App:
    app = App.__new__(App)
    app.app_config = {}
    app.entry_file = __file__
    app.download_events = Queue()
    for k, v in extra.items():
        setattr(app, k, v)
    return app


def _events(app: App) -> list[tuple]:
    out = []
    while not app.download_events.empty():
        out.append(app.download_events.get_nowait())
    return out


# ------------------------------------------------- S04-1 UTF-8 yt-dlp output

def _encoding_value(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--encoding") + 1] if "--encoding" in cmd else None


def test_media_and_subtitle_commands_ask_yt_dlp_for_utf8():
    task = _task()
    media = ds.build_download_command(task, yt_dlp_path="y", bin_path="")
    subs = ds.build_subtitle_command(task, "fa", yt_dlp_path="y", bin_path="")
    assert _encoding_value(media) == "utf-8"
    assert _encoding_value(subs) == "utf-8"
    # Options, so before the end-of-options separator.
    assert media.index("--encoding") < media.index("--")
    assert subs.index("--encoding") < subs.index("--")


def test_server_download_asks_yt_dlp_for_utf8(monkeypatch, tmp_path):
    from core import server

    seen: dict = {}

    class _Popen:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            self._write()

        def communicate(self, timeout=None):
            return "", ""

        def _write(self):
            (tmp_path / "\u0633\u0644\u0627\u0645.mp4").write_bytes(b"x")  # Persian title

    monkeypatch.setattr(server.subprocess, "Popen", _Popen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    out = server._download_url("https://example.com/v", str(tmp_path))
    assert _encoding_value(seen["cmd"]) == "utf-8"
    assert seen["kwargs"]["encoding"] == "utf-8"
    assert os.path.basename(out) == "\u0633\u0644\u0627\u0645.mp4"


# ---------------------------------------------------------- S04-2 history

def test_errored_download_closes_its_history_row_with_the_error(tmp_path):
    h = HistoryDB(str(tmp_path / "h.db"))
    rid = h.insert_download(url="http://x", title="t", folder=str(tmp_path), format_label="f")
    task = SimpleNamespace(history_id=rid, status="running", cancelled=False, paused=False,
                           end_time=None, detected_language="")
    app = SimpleNamespace(history=h, log=lambda m: None, download_current=task, _closing=True)
    svc = DownloadService(app)  # type: ignore[arg-type]
    svc._dispatch_event(app, "error", task, "Download failed (yt-dlp exit code 1): ERROR boom")  # type: ignore[arg-type]
    row = next(r for r in h.list_downloads() if r["id"] == rid)
    assert row["status"] == "error"
    assert "ERROR boom" in row["error"]
    h.mark_interrupted()
    row = next(r for r in h.list_downloads() if r["id"] == rid)
    assert row["status"] == "error"


def test_resumed_download_continues_in_the_same_history_row(tmp_path):
    h = HistoryDB(str(tmp_path / "h.db"))
    app = SimpleNamespace(history=h, log=lambda m: None)
    svc = DownloadService(app)  # type: ignore[arg-type]
    task = _task(str(tmp_path))
    svc._start_history(task)
    first = task.history_id
    svc._finish_history(task, "paused", [])
    svc._start_history(task)  # resume
    assert task.history_id == first
    rows = h.list_downloads()
    assert len(rows) == 1
    assert rows[0]["status"] == "running"
    assert not rows[0]["finished_at"]
    # A re-run copy (new task object) is a new row.
    svc._start_history(_task(str(tmp_path)))
    assert len(h.list_downloads()) == 2


def test_history_finish_failure_is_retried_once_then_logged():
    calls: list[str] = []
    logged: list[str] = []

    class _H:
        def finish_download(self, *_a, **_k):
            calls.append("x")
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return True

    app = SimpleNamespace(history=_H(), log=logged.append)
    task = _task()
    task.history_id = 7
    DownloadService(app)._finish_history(task, "finished", [])  # type: ignore[arg-type]
    assert calls == ["x", "x"]
    assert logged == []


def test_history_finish_that_fails_twice_is_logged():
    logged: list[str] = []

    class _H:
        def finish_download(self, *_a, **_k):
            raise RuntimeError("database is locked")

    task = _task()
    task.history_id = 7
    DownloadService(SimpleNamespace(history=_H(), log=logged.append))._finish_history(  # type: ignore[arg-type]
        task, "finished", [])
    assert logged == ["history record update failed: database is locked"]


# --------------------------------------------- S04-3 stale yt-dlp, no updater

def _failing_media_phase(monkeypatch, reason: str, can_update: bool) -> str:
    app = _app()
    svc = DownloadService(app)
    monkeypatch.setattr(svc, "build_download_command", lambda *_a, **_k: [])
    monkeypatch.setattr(svc, "_run_media_process", lambda *_a: (1, reason, reason, None, False))
    monkeypatch.setattr(ytu, "can_self_update", lambda *_a: can_update)
    monkeypatch.setattr(ytu, "should_offer_update", lambda _r: False)
    svc._media_phase(_task())
    errors = [e for e in _events(app) if e[0] == "error"]
    assert len(errors) == 1
    return errors[0][2]


def test_stale_yt_dlp_without_self_update_says_to_install_the_newest_app(monkeypatch):
    msg = _failing_media_phase(monkeypatch, "ERROR: unable to download video data: HTTP Error 403: Forbidden", False)
    assert "install the newest version of this app" in msg


def test_stale_yt_dlp_with_self_update_keeps_the_bar_instead(monkeypatch):
    msg = _failing_media_phase(monkeypatch, "ERROR: unable to download video data: HTTP Error 403: Forbidden", True)
    assert "install the newest version of this app" not in msg


def test_other_failures_get_no_update_advice(monkeypatch):
    msg = _failing_media_phase(monkeypatch, "ERROR: Video unavailable", False)
    assert "newest version" not in msg


# ------------------------------------ S04-4 updater refuses unofficial builds

@pytest.fixture
def ytu_env(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    bundled = install / "yt-dlp.exe"
    bundled.write_bytes(b"yt-dlp 2026.08.19")
    monkeypatch.setattr(ytu, "bundled_binary", lambda _n: str(bundled))
    monkeypatch.setattr(ytu, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ytu.offline, "is_offline", lambda: False)
    ytu._running.clear()
    ytu._updating = False
    return bundled


def _version_of(path: str) -> tuple[int, ...]:
    text = Path(path).read_bytes().decode("utf-8", "replace")
    return tuple(int(p) for p in text.split()[1].split(".")) if text.startswith("yt-dlp ") else ()


@pytest.mark.parametrize("answer", [
    "ERROR: You installed yt-dlp from a manual build or with a package manager; Use that to update",
    "ERROR: You are using an unofficial build of yt-dlp; Build the executable again",
    "ERROR: You installed yt-dlp with pip or using the wheel from PyPi; Use that to update",
])
def test_an_updater_that_refuses_the_build_is_not_started_again(ytu_env, answer):
    runs: list[list[str]] = []

    def _run(cmd, **_k):
        runs.append(cmd)
        return SimpleNamespace(returncode=100, stdout="", stderr=answer)

    first = ytu.update_cached_copy(run=_run, version_of=_version_of)
    assert first.status == "unsupported"
    assert first.completed is True
    assert ytu.can_self_update() is False
    # A refresh (e.g. on the next start) keeps the record.
    ytu.refresh_state(version_of=_version_of)
    second = ytu.update_cached_copy(run=_run, version_of=_version_of)
    assert second.status == "unsupported"
    assert len(runs) == 1


def test_a_new_bundled_binary_is_tried_again(ytu_env):
    def _refuse(cmd, **_k):
        return SimpleNamespace(returncode=100, stdout="", stderr="ERROR: You installed yt-dlp "
                               "from a manual build or with a package manager; Use that to update")

    ytu.update_cached_copy(run=_refuse, version_of=_version_of)
    assert ytu.can_self_update() is False
    ytu_env.write_bytes(b"yt-dlp 2026.09.30")  # the app was updated
    st = ytu_env.stat()
    os.utime(ytu_env, ns=(st.st_mtime_ns + 2_000_000_000,) * 2)
    assert ytu.can_self_update() is True


def test_a_network_failure_is_not_taken_for_an_unofficial_build(ytu_env):
    def _offline(cmd, **_k):
        return SimpleNamespace(returncode=100, stdout="", stderr="ERROR: Unable to obtain "
                               "version info (<urlopen error timed out>); Please try again later")

    result = ytu.update_cached_copy(run=_offline, version_of=_version_of)
    assert result.status == "failed"
    assert ytu.can_self_update() is True


# ---------------------------------------- S04-9 failed --version not cached

def test_a_failed_version_answer_is_asked_again(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_bytes(b"")
    answers = [subprocess.TimeoutExpired("yt-dlp", 120), "2026.08.19\n"]

    def _run(*_a, **_k):
        a = answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return SimpleNamespace(returncode=0, stdout=a)

    monkeypatch.setattr(subprocess, "run", _run)
    js._yt_dlp_version_cache.clear()
    assert js.yt_dlp_version(str(exe)) == ()
    assert js.yt_dlp_version(str(exe)) == (2026, 8, 19)


def test_a_failed_version_answer_keeps_the_recorded_version(ytu_env):
    ytu.refresh_state(version_of=_version_of)
    assert ytu.load_state()["bundled"]["version"] == [2026, 8, 19]
    ytu.refresh_state(version_of=lambda _p: ())  # one failed --version
    assert ytu.load_state()["bundled"]["version"] == [2026, 8, 19]
    # A changed file never inherits the old version.
    ytu_env.write_bytes(b"something else")
    st = ytu_env.stat()
    os.utime(ytu_env, ns=(st.st_mtime_ns + 2_000_000_000,) * 2)
    ytu.refresh_state(version_of=lambda _p: ())
    assert ytu.load_state()["bundled"]["version"] == []


# ------------------------------------------------ S04-5 rolling auto captions

_ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.160 --> 00:00:02.230 align:start position:0%

hello<00:00:00.640><c> everyone</c><00:00:01.120><c> welcome</c>

00:00:02.230 --> 00:00:02.240 align:start position:0%
hello everyone welcome


00:00:02.240 --> 00:00:04.150 align:start position:0%
hello everyone welcome
to<00:00:02.560><c> the</c><00:00:02.800><c> show</c>

00:00:04.150 --> 00:00:04.160 align:start position:0%
to the show

"""


def _txt_words(path: str) -> str:
    return " ".join(Path(path).read_text(encoding="utf-8").split())


def test_subtitle_extras_of_auto_captions_drop_the_rolling_repeats(tmp_path):
    vtt = tmp_path / "a.en.vtt"
    vtt.write_text(_ROLLING_VTT, encoding="utf-8")
    written = ds.write_subtitle_extra_formats(str(vtt), language="en", dedupe=True)
    txt = next(p for p in written if p.endswith(".txt"))
    words = _txt_words(txt)
    assert words.count("welcome") == 1
    assert words.count("show") == 1


def test_subtitle_phase_dedupes_only_auto_tracks(tmp_path, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(ds, "write_subtitle_extra_formats",
                        lambda _p, **k: seen.append(k.get("dedupe", False)) or [])
    for kind in ("auto", "manual", ""):
        app = _app(subtitle_status_var=None)
        svc = DownloadService(app)
        monkeypatch.setattr(svc, "_fetch_subtitles", lambda *_a: ([str(tmp_path / "a.vtt")], False, 0))
        task = _task(str(tmp_path), subtitle_lang="en", caption_kind=kind)
        svc._subtitle_phase(task)
    assert seen == [True, False, False]


def test_subtitle_phase_passes_the_run_generation_on(tmp_path, monkeypatch):
    got: list = []
    app = _app()
    svc = DownloadService(app)
    monkeypatch.setattr(svc, "_fetch_subtitles", lambda *a: got.append(a[2:]) or ([], False, 0))
    svc._subtitle_phase(_task(str(tmp_path), subtitle_lang="en"), run_generation=5)
    assert got == [(5,)]


def test_cancel_stops_the_subtitle_extras(tmp_path, monkeypatch):
    calls: list[str] = []
    app = _app()
    svc = DownloadService(app)
    task = _task(str(tmp_path), subtitle_lang="en")
    files = [str(tmp_path / "a.en.vtt"), str(tmp_path / "a.de.vtt")]

    def _extras(path, **_k):
        calls.append(path)
        task.cancelled = True  # cancel lands while the first file converts
        return []

    monkeypatch.setattr(ds, "write_subtitle_extra_formats", _extras)
    monkeypatch.setattr(svc, "_fetch_subtitles", lambda *_a: (files, False, 0))
    svc._subtitle_phase(task)
    assert calls == files[:1]


# ---------------------------------------------------- S04-8 cancel leftovers

def _touch(path: Path) -> Path:
    path.write_bytes(b"x")
    return path


def test_cancel_removes_the_partial_files_and_keeps_the_rest(tmp_path, monkeypatch):
    title = "\u0633\u0644\u0627\u0645 \u041f\u0440\u0438\u0432\u0435\u0442"  # Persian + Russian
    video = tmp_path / f"{title}.f137.mp4"
    audio = tmp_path / f"{title}.f140.m4a"
    leftovers = [
        _touch(video),  # finished video stream, never merged
        _touch(Path(str(audio) + ".part")),
        _touch(Path(str(audio) + ".ytdl")),
        _touch(Path(str(audio) + ".part-Frag3")),
    ]
    keep = [_touch(tmp_path / "other.mp4"), _touch(tmp_path / f"{title}.mp4.bak")]
    lines = [
        f"[download] Destination: {video}",
        "[download] 100% of 1.00MiB",
        f"[download] Destination: {audio}",
    ]
    app = _app()
    svc = DownloadService(app)
    task = _task(str(tmp_path))

    class _Proc:
        stdout = iter(lines)

        def wait(self):
            task.cancelled = True
            return 1

    monkeypatch.setattr(ds.subprocess, "Popen", lambda *_a, **_k: _Proc())
    monkeypatch.setattr(svc, "build_download_command", lambda *_a, **_k: [])
    svc._media_phase(task)
    assert [p for p in leftovers if p.exists()] == []
    assert all(p.exists() for p in keep)
    assert ("done", task, "cancelled") in _events(app)


def test_pause_keeps_the_partial_files(tmp_path, monkeypatch):
    part = _touch(tmp_path / "v.mp4.part")
    app = _app()
    svc = DownloadService(app)
    task = _task(str(tmp_path))

    class _Proc:
        stdout = iter([f"[download] Destination: {tmp_path / 'v.mp4'}"])

        def wait(self):
            task.paused = True
            return 1

    monkeypatch.setattr(ds.subprocess, "Popen", lambda *_a, **_k: _Proc())
    monkeypatch.setattr(svc, "build_download_command", lambda *_a, **_k: [])
    svc._media_phase(task)
    assert part.exists()


def test_cancel_of_a_paused_download_cleans_up_and_closes_history(tmp_path):
    h = HistoryDB(str(tmp_path / "h.db"))
    part = _touch(tmp_path / "v.mp4.part")
    app = _app(history=h, download_current=None, download_queue=[])
    app.refresh_download_queue = lambda: None  # type: ignore[method-assign]
    svc = DownloadService(app)
    app.download_service = svc
    task = _task(str(tmp_path))
    svc._start_history(task)
    svc._finish_history(task, "paused", [])
    task.status = "paused"
    task.paused = True
    task.partial_paths = [str(tmp_path / "v.mp4")]
    App.cancel_download(app, task)
    assert not part.exists()
    assert h.list_downloads()[0]["status"] == "cancelled"


def test_a_finished_final_file_is_never_listed_as_partial(tmp_path):
    final = _touch(tmp_path / "Title.final.mp4")
    assert ds.partial_download_files(str(final)) == []
    # A single-piece download whose title merely looks like a stream.
    single = _touch(tmp_path / "Weekly sync.f1.mp4")
    assert ds.partial_download_files(str(single), [str(single)]) == []
    # Two streams of one merge, numeric or named format ids.
    video = _touch(tmp_path / "Title.fhls-720.mp4")
    audio = tmp_path / "Title.f251.webm"
    assert ds.partial_download_files(str(video), [str(video), str(audio)]) == [str(video)]


def test_the_merge_target_is_never_removed_only_its_temp_file(tmp_path, monkeypatch):
    title = tmp_path / "Weekly sync.f1.mp4"  # finished merge whose title looks like a stream
    _touch(title)
    temp = _touch(tmp_path / "Weekly sync.f1.temp.mp4")
    task = _task(str(tmp_path))
    ds._remember_partial(task, f'[Merger] Merging formats into "{title}"', str(title))
    DownloadService(_app()).remove_partial_files(task)
    assert title.exists()
    assert not temp.exists()


def test_cancel_before_a_resumed_run_starts_still_cleans_up(tmp_path, monkeypatch):
    part = _touch(tmp_path / "v.mp4.part")
    app = SimpleNamespace(download_events=Queue(), app_config={}, log=lambda _m: None)
    svc = DownloadService(app)  # type: ignore[arg-type]
    task = _task(str(tmp_path))
    task.partial_paths = [str(tmp_path / "v.mp4")]

    def _update(t):
        t.cancelled = True  # cancel lands during the yt-dlp update wait

    monkeypatch.setattr(svc, "maybe_update_yt_dlp", _update)
    monkeypatch.setattr(svc, "_refused_offline", lambda _t: False)
    svc._run_task(task)
    assert not part.exists()
    assert ("done", task, "cancelled") in _events(app)  # type: ignore[arg-type]


def test_cancel_after_the_subtitle_phase_cleans_up(tmp_path, monkeypatch):
    part = _touch(tmp_path / "v.mp4.part")
    app = SimpleNamespace(download_events=Queue(), app_config={}, log=lambda _m: None)
    svc = DownloadService(app)  # type: ignore[arg-type]
    task = _task(str(tmp_path), subtitles_enabled=True, subtitle_lang="en")
    task.partial_paths = [str(tmp_path / "v.mp4")]
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", lambda _t: None)
    monkeypatch.setattr(svc, "_refused_offline", lambda _t: False)

    def _subs(t, run_generation=None):
        t.cancelled = True
        return False

    monkeypatch.setattr(svc, "_subtitle_phase", _subs)
    svc._run_task(task)
    assert not part.exists()


# ------------------------------------------- S03-11 regional caption tracks

@pytest.mark.parametrize("wanted, track, hit", [
    ("pt", "pt-BR", True), ("pt", "pt-PT", True), ("en", "en-GB", True),
    ("es", "es-419", True), ("pt", "pt", True), ("en", "en-orig", False),
    ("zh-Hans", "zh-Hans", True), ("zh", "zh-Hans", False), ("pt", "ptx", False),
    # yt-dlp's keys for YouTube's machine translations of an uploader track
    # are "<target>-<source>" in lower case: never a regional track.
    ("en", "en-ja", False), ("pt", "pt-en", False), ("es", "es-de", False),
    ("pt", "pt-br", False),
])
def test_bare_language_codes_match_their_regional_tracks(wanted, track, hit):
    assert languages.lang_code_matches(wanted, track) is hit


def test_sub_langs_value_matches_regional_tracks_and_stays_literal_otherwise():
    import re

    value = languages.subtitle_lang_patterns("pt")
    assert re.fullmatch(value, "pt-BR", re.I) and re.fullmatch(value, "pt", re.I)
    assert not re.fullmatch(value, "pt-orig", re.I)
    assert languages.subtitle_lang_patterns("zh-Hans,zh-CN") == "zh-Hans,zh-CN"
    assert languages.subtitle_lang_patterns(".*") == r"\.\*"


def test_sub_langs_value_with_yt_dlps_own_matcher():
    # The python package (not a dependency): its own --sub-langs matcher.
    utils = pytest.importorskip("yt_dlp.utils")

    keys = ("en", "en-GB", "en-ja", "en-fr", "pt-BR", "pt-en", "es-419", "es-de", "en-orig")
    for lang, want in (("en", ["en", "en-GB"]), ("pt", ["pt-BR"]), ("es", ["es-419"])):
        got = utils.orderedSet_from_options(
            [languages.subtitle_lang_patterns(lang)], {"all": keys}, use_regex=True,
        )
        assert list(got) == want, lang


def test_caption_kind_found_through_a_regional_track():
    assert languages.resolve_caption_kind({"pt-BR": "manual"}, "pt") == "manual"
    assert languages.resolve_caption_kind({"en-GB": "auto", "en-US": "manual"}, "en") == "manual"
    assert languages.resolve_caption_kind({"de": "manual"}, "pt") == ""


# ---------------------------------------------------- P6-06 invisible marks

@pytest.mark.parametrize("mark", ["\u200f", "\u200e", "\u200c", "\u200b", "\ufeff", "\u202a", "\u2066", "\u061c"])
def test_invisible_marks_around_a_link_are_dropped(mark):
    url = "https://suprememastertv.com/en1/v/123456.html"
    assert smtv.clean_url(mark + url + mark + " ") == url
    assert smtv.is_smtv_url(mark + url)
    assert smtv.parse_episode_id(mark + url + mark) == ("en", "123456")


def test_invisible_marks_inside_text_are_kept():
    assert smtv.clean_url("a\u200cb") == "a\u200cb"


def test_clean_url_is_fast_on_a_long_run_of_spaces():
    import time

    text = "a" + " " * 50000 + "b"
    start = time.perf_counter()
    assert smtv.clean_url(text) == text
    assert time.perf_counter() - start < 0.5


# ------------------------------------------------ P6-02 time-range file name

def test_a_time_range_download_gets_its_own_file_name():
    full = ds.build_download_command(_task(), yt_dlp_path="y", bin_path="")
    clip = ds.build_download_command(_task(section_start=51.0, section_end=85.0),
                                     yt_dlp_path="y", bin_path="")
    out_full = full[full.index("-o") + 1]
    out_clip = clip[clip.index("-o") + 1]
    assert out_full != out_clip
    name = os.path.basename(out_clip)
    assert name == "%(title)s (clip 0.00.51-0.01.25).%(ext)s"
    assert ":" not in name
    open_end = ds.build_download_command(_task(section_start=51.0), yt_dlp_path="y", bin_path="")
    assert os.path.basename(open_end[open_end.index("-o") + 1]).endswith("-end).%(ext)s")


# ------------------------------------------- P6-01 SMTV parts off Tk thread

def test_smtv_parts_are_looked_up_off_the_calling_thread(monkeypatch):
    import threading

    fetch_threads: list[str] = []
    posted: list = []
    app = _app(download_queue=[], _closing=False)
    app.post_to_main = posted.append  # type: ignore[method-assign]
    app.refresh_download_queue = lambda: None  # type: ignore[method-assign]
    svc = DownloadService(app)
    monkeypatch.setattr(svc, "process_queue", lambda: None)
    done = threading.Event()

    def _build(_ep, **_k):
        fetch_threads.append(threading.current_thread().name)
        done.set()
        return [_task()]

    monkeypatch.setattr(svc, "_build_smtv_sibling_tasks", _build)
    episode = SimpleNamespace(siblings=[object(), object()])
    svc._enqueue_smtv_siblings_async(episode, mode="Audio", video_label="", folder="f",  # type: ignore[arg-type]
                                     format_label="x", output="mp3")
    assert done.wait(5)
    for _ in range(100):
        if posted:
            break
        threading.Event().wait(0.02)
    assert fetch_threads and fetch_threads[0] != threading.current_thread().name
    assert len(posted) == 1
    posted[0]()
    assert len(app.download_queue) == 1
    # Parts that arrive while the app closes are dropped.
    app._closing = True
    done.clear()
    posted.clear()
    svc._enqueue_smtv_siblings_async(episode, mode="Audio", video_label="", folder="f",  # type: ignore[arg-type]
                                     format_label="x", output="mp3")
    assert done.wait(5)
    for _ in range(100):
        if posted:
            break
        threading.Event().wait(0.02)
    posted[0]()
    assert len(app.download_queue) == 1


# ------------------------------------------ optional: SMTV error contract

class _Resp:
    def __init__(self, charset: str | None = None, body: bytes = b"ok", exc: Exception | None = None):
        self.headers = SimpleNamespace(get_content_charset=lambda: charset)
        self._body = body
        self._exc = exc

    def read(self):
        if self._exc is not None:
            raise self._exc
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_smtv_page_with_an_unknown_charset_is_read_as_utf8(monkeypatch):
    monkeypatch.setattr(smtv.offline, "is_offline", lambda: False)
    monkeypatch.setattr(smtv.urllib.request, "urlopen",
                        lambda *_a, **_k: _Resp("x-no-such-charset", "caf\u00e9".encode()))
    assert smtv._http_get("https://suprememastertv.com/x", timeout=1) == "caf\u00e9"


def test_smtv_cut_off_page_raises_the_smtv_error(monkeypatch):
    import http.client

    monkeypatch.setattr(smtv.offline, "is_offline", lambda: False)
    monkeypatch.setattr(smtv.urllib.request, "urlopen",
                        lambda *_a, **_k: _Resp(exc=http.client.IncompleteRead(b"par", 10)))
    with pytest.raises(smtv.SmtvError):
        smtv._http_get("https://suprememastertv.com/x", timeout=1)
