"""Hermetic regression tests for fix-pack Ia.

Covers ten confirmed defects across app/app.py, app/widgets/tray.py and
app/services/download_service.py. Every test drives the real method UNBOUND
against a lightweight fake ``self`` (a ``types.SimpleNamespace`` or a tiny
stub) so there is NO real tk.Tk() root, no network, and no real model or
binaries — the Python-3.14 box cannot reliably build a Tk root and none of
this logic needs one.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("tkinter")

from app.app import App, _split_dnd_paths
from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService


# ---------------------------------------------------------------------------
# Finding 1 — _exit_from_tray latch reset after a declined exit
# ---------------------------------------------------------------------------


class _FakeMessagebox:
    def __init__(self, answer: bool) -> None:
        self.answer = answer

    def askyesno(self, *_a, **_k) -> bool:
        return self.answer


def _exit_app(tray_alive: bool = True, minimise: bool = True):
    """Build a minimal fake App for on_exit's redirect/decline logic."""
    running = types.SimpleNamespace(status="running")

    def _log(_msg: str) -> None:
        pass

    app = types.SimpleNamespace(
        _exit_from_tray=False,
        app_config={"minimise_to_tray": minimise},
        tray=types.SimpleNamespace(is_supported=lambda: True) if tray_alive else None,
        queue=[running],
        download_queue=[],
        log=_log,
        withdrew=[],
    )
    app.withdraw = lambda: app.withdrew.append(True)
    return app


def test_declined_exit_resets_exit_from_tray_latch(monkeypatch):
    """File->Exit/Ctrl+Q set _exit_from_tray=True; declining the
    'queued tasks' prompt must reset it so the X button still honours
    minimise-to-tray for the rest of the session."""
    monkeypatch.setattr("app.app.messagebox", _FakeMessagebox(answer=False))
    app = _exit_app()
    # Simulate _force_exit / tray Exit having set the override.
    app._exit_from_tray = True

    App.on_exit(app)  # type: ignore[arg-type]

    # Declined => returned early WITHOUT tearing down, and the latch is reset.
    assert app._exit_from_tray is False
    assert app.withdrew == []  # the override skipped the tray redirect this call


def test_x_button_minimises_to_tray_after_a_declined_force_exit(monkeypatch):
    """After the declined exit resets the latch, a plain X-button close
    (no override) routes back through the minimise-to-tray branch."""
    monkeypatch.setattr("app.app.messagebox", _FakeMessagebox(answer=False))
    app = _exit_app()
    app._exit_from_tray = True
    App.on_exit(app)  # type: ignore[arg-type]  # decline -> resets latch

    # Now the user clicks X (no override): should minimise, not tear down.
    App.on_exit(app)  # type: ignore[arg-type]
    assert app.withdrew == [True]


# ---------------------------------------------------------------------------
# Finding 2 — SMTV video-only clip (no audio track) must still enqueue
# Finding 6 — os.makedirs / save_config guarded on a bad folder
# ---------------------------------------------------------------------------


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = str(v)


def _enqueue_app(*, audio_map, video_map, mode, smtv_episode=None,
                 makedirs_ok=True):
    warnings: list[tuple[str, str]] = []

    app = types.SimpleNamespace(
        download_url_var=_Var("https://smtv.example/clip"),
        download_folder_var=_Var(r"C:\dl"),
        download_mode_var=_Var(mode),
        audio_format_var=_Var(next(iter(audio_map), "")),
        video_format_var=_Var(next(iter(video_map), "")),
        output_format_var=_Var("mp4"),
        audio_format_map=audio_map,
        video_format_map=video_map,
        app_config={},
        current_video_title="Clip",
        current_video_language="en",
        download_subtitles_var=_Var(""),
        subtitle_lang_var=_Var(""),
        download_start_time_var=_Var(""),
        download_end_time_var=_Var(""),
        smtv_download_all_parts_var=None,
        _smtv_episode=smtv_episode,
        download_queue=[],
        refresh_download_queue=lambda: None,
    )
    app.download_subtitles_var = _Var("")  # falsy -> subtitles off
    # bool("") is False
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc, app, warnings


def test_smtv_video_only_clip_enqueues_without_audio_format(monkeypatch):
    """An SMTV news clip ships no mp3 -> audio_format_map is empty. In
    'Audio and video' mode with a valid video quality it MUST enqueue, not
    be rejected with 'Missing audio format'."""
    from core.integrations import smtv as smtv_mod

    episode = object.__new__(smtv_mod.SmtvEpisode)
    # is_smtv_url + isinstance gate it; force both true.
    monkeypatch.setattr(smtv_mod, "is_smtv_url", lambda _u: True)

    warnings: list[str] = []

    class _MB:
        @staticmethod
        def showwarning(title, *_a, **_k):
            warnings.append(title)

    monkeypatch.setattr("tkinter.messagebox", _MB)
    monkeypatch.setattr("app.services.download_service.os.makedirs",
                        lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.download_service.save_config",
                        lambda _c: None)

    svc = DownloadService.__new__(DownloadService)
    app = types.SimpleNamespace(
        download_url_var=_Var("https://smtv.example/clip"),
        download_folder_var=_Var(r"C:\dl"),
        download_mode_var=_Var("Audio and video"),
        audio_format_var=_Var(""),                 # no audio for a news clip
        video_format_var=_Var("HD 720p"),
        output_format_var=_Var("mp4"),
        audio_format_map={},                       # empty -> the old gate failed
        video_format_map={"HD 720p": {"kind": "smtv", "mode": "video-720",
                                       "url": "https://cdn/x.mp4"}},
        app_config={},
        current_video_title="Clip",
        current_video_language="en",
        download_subtitles_var=_Var(""),
        subtitle_lang_var=_Var(""),
        download_start_time_var=_Var(""),
        download_end_time_var=_Var(""),
        smtv_download_all_parts_var=None,
        _smtv_episode=episode,
        download_queue=[],
        refresh_download_queue=lambda: None,
        process_queue=lambda: None,
    )
    svc.app = app  # type: ignore[attr-defined]
    svc.process_queue = lambda: None  # type: ignore[attr-defined]

    DownloadService.enqueue_from_form(svc)

    assert warnings == []                          # NOT rejected
    assert len(app.download_queue) == 1            # the clip was enqueued
    task = app.download_queue[0]
    # No audio entry, video carries the SMTV CDN url.
    assert task.format_info["audio"] is None
    assert task.format_info["video"]["kind"] == "smtv"


def test_enqueue_guards_unwritable_download_folder(monkeypatch):
    """A stale/read-only folder makes os.makedirs raise; the Download
    button must warn + return, not crash with an OSError traceback."""
    warnings: list[str] = []

    class _MB:
        @staticmethod
        def showwarning(title, *_a, **_k):
            warnings.append(title)

    monkeypatch.setattr("tkinter.messagebox", _MB)

    def _boom(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr("app.services.download_service.os.makedirs", _boom)

    svc = DownloadService.__new__(DownloadService)
    app = types.SimpleNamespace(
        download_url_var=_Var("https://youtube.example/v"),
        download_folder_var=_Var(r"X:\gone"),
        download_mode_var=_Var("Audio and video"),
        audio_format_var=_Var("Best audio"),
        video_format_var=_Var("Best video"),
        output_format_var=_Var("mp4"),
        audio_format_map={"Best audio": {"kind": "best_audio"}},
        video_format_map={"Best video": {"kind": "best_video"}},
        app_config={},
        current_video_title="v",
        current_video_language="",
        download_subtitles_var=_Var(""),
        subtitle_lang_var=_Var(""),
        download_start_time_var=_Var(""),
        download_end_time_var=_Var(""),
        smtv_download_all_parts_var=None,
        _smtv_episode=None,
        download_queue=[],
        refresh_download_queue=lambda: None,
        process_queue=lambda: None,
    )
    svc.app = app  # type: ignore[attr-defined]
    svc.process_queue = lambda: None  # type: ignore[attr-defined]

    DownloadService.enqueue_from_form(svc)

    assert warnings == ["Folder unavailable"]
    assert app.download_queue == []  # nothing enqueued, and no exception raised


# ---------------------------------------------------------------------------
# Finding 3 — OSError from save_config must not freeze the server toggle
# ---------------------------------------------------------------------------


class _Btn:
    def __init__(self) -> None:
        self.kw: dict = {}

    def config(self, **kw) -> None:
        self.kw.update(kw)


def _server_app():
    app = types.SimpleNamespace(
        _server_busy=True,
        server_port_var=_Var("8765"),
        app_config={"server_port": 8765},
        server_toggle_btn=_Btn(),
        server_open_btn=_Btn(),
        server_status_var=_Var("Starting..."),
        server_url_var=_Var(""),
        logs=[],
    )
    app.log = app.logs.append
    return app


def test_server_started_reenables_toggle_even_if_save_config_oserrors(monkeypatch):
    """Auto-port picks a different port -> save_config runs and raises
    OSError. The toggle button must STILL re-enable, status -> Running,
    and url be set (otherwise the server is live but its only control is
    stuck disabled at 'Starting...')."""
    def _boom(_c):
        raise OSError("config.json locked by antivirus")

    monkeypatch.setattr("app.app.save_config", _boom)
    app = _server_app()

    App._on_server_started(app, ["http://127.0.0.1:9001/"], 9001, False)  # type: ignore[arg-type]

    assert app._server_busy is False
    assert app.server_toggle_btn.kw.get("state") == "normal"
    assert app.server_toggle_btn.kw.get("text") == "Stop web access"
    assert app.server_open_btn.kw.get("state") == "normal"
    assert app.server_status_var.get() == "Running on this computer."
    assert app.server_url_var.get() == "http://127.0.0.1:9001/"
    # The new bound port still got reflected into the var/config.
    assert app.server_port_var.get() == "9001"


# ---------------------------------------------------------------------------
# Finding 4 — resume race: old worker's finally must not kill the new process
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive
        self.killed = False
        self.stdout = None

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):  # noqa: ANN001
        self._alive = False
        return 0


def _run_task_svc(app):
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc


def _run_task_app():
    return types.SimpleNamespace(
        download_events=types.SimpleNamespace(put=lambda _e: None),
        history=None,
    )


def test_run_task_finally_skips_process_owned_by_a_newer_run(monkeypatch):
    """The resume race: the OLD _run_task's _media_phase finishes; a resume
    has meanwhile bumped task._run_generation and assigned a brand-new live
    process. The old run's finally must NOT reap/kill that new process."""
    killed = {"n": 0}

    def _kill(proc, force=False):  # noqa: ANN001
        killed["n"] += 1
        proc.killed = True

    monkeypatch.setattr("app.services.download_service.kill_process_tree", _kill)

    app = _run_task_app()
    svc = _run_task_svc(app)
    new_proc = _FakeProc(alive=True)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
    )

    # Stub the phases the OLD run walks. When _media_phase returns, simulate
    # the resume that has already started a NEW run: bump the generation and
    # attach the fresh live process.
    svc.maybe_update_yt_dlp = lambda _t: None  # type: ignore[attr-defined]

    def _media_phase(_t, run_generation=None):
        # The new run (resume) bumped the generation past ours and owns proc.
        task._run_generation = 999  # type: ignore[attr-defined]
        task.process = new_proc

    svc._media_phase = _media_phase  # type: ignore[attr-defined]

    DownloadService._run_task(svc, task)

    # The new run's process survived: not tree-killed, still on the task.
    assert killed["n"] == 0
    assert new_proc.killed is False
    assert task.process is new_proc


def test_run_task_finally_reaps_its_own_process(monkeypatch):
    """No newer run: the finally still reaps + nulls its own process — the
    normal path is preserved."""
    monkeypatch.setattr("app.services.download_service.kill_process_tree",
                        lambda *a, **k: None)
    app = _run_task_app()
    svc = _run_task_svc(app)
    own_proc = _FakeProc(alive=False)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
    )
    svc.maybe_update_yt_dlp = lambda _t: None  # type: ignore[attr-defined]

    def _media_phase(_t, run_generation=None):
        task.process = own_proc  # our own run owns it; no newer generation

    svc._media_phase = _media_phase  # type: ignore[attr-defined]

    DownloadService._run_task(svc, task)
    assert task.process is None  # our own process was reapped + nulled


# ---------------------------------------------------------------------------
# Finding 4b — superseded _run_task must not enter media/subtitle phases
# ---------------------------------------------------------------------------


def test_run_task_superseded_skips_media_and_subtitle(monkeypatch):
    """If a pause+resume bumps _run_generation while _run_task is blocked
    in maybe_update_yt_dlp, the old run must return without entering the
    subtitle or media phases — doing so would start a duplicate download
    concurrently with the fresh run."""
    phases_entered: list[str] = []
    events: list[tuple] = []
    monkeypatch.setattr("app.services.download_service.kill_process_tree",
                        lambda *a, **k: None)

    app = _run_task_app()
    app.download_events = types.SimpleNamespace(put=lambda e: events.append(e))
    svc = _run_task_svc(app)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
        subtitles_enabled=True,
    )

    def _bump_generation(_t):
        # Simulate a pause+resume: the fresh run bumps the generation.
        task._run_generation = 999  # type: ignore[attr-defined]

    svc.maybe_update_yt_dlp = _bump_generation  # type: ignore[attr-defined]

    def _subtitle_phase(_t):
        phases_entered.append("subtitle")

    def _media_phase(_t, run_generation=None):
        phases_entered.append("media")

    svc._subtitle_phase = _subtitle_phase  # type: ignore[attr-defined]
    svc._media_phase = _media_phase  # type: ignore[attr-defined]

    DownloadService._run_task(svc, task)

    # Neither phase was entered — the superseded run returned early.
    assert phases_entered == []
    # No error event posted (suppressed for superseded runs).
    assert not any(e[0] == "error" for e in events)


def test_run_task_superseded_after_subtitle_skips_media(monkeypatch):
    """If _run_generation is bumped during _subtitle_phase, the old run
    must not enter _media_phase afterward."""
    phases_entered: list[str] = []
    monkeypatch.setattr("app.services.download_service.kill_process_tree",
                        lambda *a, **k: None)

    app = _run_task_app()
    svc = _run_task_svc(app)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
        subtitles_enabled=True,
    )
    svc.maybe_update_yt_dlp = lambda _t: None  # type: ignore[attr-defined]

    def _subtitle_phase(_t):
        # Simulate pause+resume during subtitle fetch.
        task._run_generation = 999  # type: ignore[attr-defined]

    def _media_phase(_t, run_generation=None):
        phases_entered.append("media")

    svc._subtitle_phase = _subtitle_phase  # type: ignore[attr-defined]
    svc._media_phase = _media_phase  # type: ignore[attr-defined]

    DownloadService._run_task(svc, task)

    assert phases_entered == []


def test_superseded_caption_only_run_suppresses_error(monkeypatch):
    """A caption-only run that gets superseded during the caption fetch
    must not post an error event — doing so would flip the fresh run's
    row to error and release its download slot."""
    events: list[tuple] = []
    monkeypatch.setattr("app.services.download_service.kill_process_tree",
                        lambda *a, **k: None)

    app = _run_task_app()
    app.download_events = types.SimpleNamespace(put=lambda e: events.append(e))
    svc = _run_task_svc(app)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
        caption_only=True,
    )
    svc.maybe_update_yt_dlp = lambda _t: None  # type: ignore[attr-defined]

    def _caption_phase(_t, run_generation=None):
        # Simulate pause+resume during the caption fetch.
        task._run_generation = 999  # type: ignore[attr-defined]

    svc._run_caption_only_task = _caption_phase  # type: ignore[attr-defined]

    DownloadService._run_task(svc, task)

    # No error event — suppressed because the run is superseded.
    assert not any(e[0] == "error" for e in events)


def test_caption_only_pause_before_start_is_not_silently_ignored(monkeypatch):
    """Found by an adversarial review (2026-09-22): the media path already
    checks `_superseded() or task.paused` right after maybe_update_yt_dlp
    and before starting -- the caption-only path called
    maybe_update_yt_dlp and went straight into _run_caption_only_task
    with no such check. A pause landing during maybe_update_yt_dlp's up-
    to-60s blocking wait has no process to kill yet (caption-only hasn't
    spawned yt-dlp), so pause_download only sets the flag and frees the
    slot -- the run then launched its own yt-dlp anyway, writing caption
    files for a task the user paused."""
    monkeypatch.setattr("app.services.download_service.kill_process_tree",
                        lambda *a, **k: None)

    app = _run_task_app()
    svc = _run_task_svc(app)

    task = VideoDownloadTask(
        url="u", folder="f", format_label="x",
        format_info={"mode": "Audio and video",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
        caption_only=True,
    )

    def _mark_paused_during_update(_t):
        # Simulate the user hitting Pause while maybe_update_yt_dlp's
        # up-to-60s subprocess call is still blocking.
        task.paused = True  # type: ignore[attr-defined]

    svc.maybe_update_yt_dlp = _mark_paused_during_update  # type: ignore[attr-defined]

    ran = {"n": 0}
    svc._run_caption_only_task = lambda _t, run_generation=None: ran.__setitem__(  # type: ignore[attr-defined]
        "n", ran["n"] + 1
    )

    DownloadService._run_task(svc, task)

    assert ran["n"] == 0, "caption-only yt-dlp launched despite the pause"


# ---------------------------------------------------------------------------
# Finding 5 — TOCTOU on task.process in pause/cancel: snapshot, no AttributeError
# ---------------------------------------------------------------------------


class _LiveProc:
    def __init__(self) -> None:
        self.killed = False

    def poll(self):
        return None  # alive


class _RacingTask(VideoDownloadTask):
    """Models the worker thread nulling task.process BETWEEN the
    truthiness test and the .poll() call.

    ``process`` is a property: the FIRST read (the truthiness check)
    returns the live proc, the SECOND read (``.poll()`` on the old
    double-deref code) returns None. The pre-fix code therefore did
    ``None.poll()`` -> AttributeError on the Tk thread; the fixed code
    snapshots the first read into a local, so it never re-reads None.
    """

    def __init__(self, proc, **kw) -> None:  # noqa: ANN001
        super().__init__(**kw)
        self._proc = proc
        self._reads = 0

    @property  # type: ignore[override]
    def process(self):
        self._reads += 1
        # First read -> live proc; every later read -> None (worker nulled it).
        return self._proc if self._reads <= 1 else None

    @process.setter
    def process(self, value) -> None:  # noqa: ANN001
        self._proc = value


def test_cancel_download_snapshots_process_no_attributeerror(monkeypatch):
    """The fixed cancel_download snapshots task.process once; even if the
    worker nulls task.process between the truthiness test and .poll(),
    there is no None.poll() AttributeError on the Tk thread."""
    killed = {"n": 0}
    monkeypatch.setattr("app.app.kill_process_tree",
                        lambda proc, force=False: killed.__setitem__("n", killed["n"] + 1))

    proc = _LiveProc()
    task = _RacingTask(proc, url="u", folder="f", format_label="x",
                       format_info={"mode": "Audio"})
    task.status = "running"
    app = types.SimpleNamespace(
        download_queue=[task],
        download_current=task,
        refresh_download_queue=lambda: None,
    )

    # Must not raise AttributeError.
    App.cancel_download(app, task)  # type: ignore[arg-type]
    assert task.status == "cancelled"
    assert killed["n"] == 1  # the snapshot was killed


def test_pause_download_snapshots_process_no_attributeerror(monkeypatch):
    killed = {"n": 0}
    monkeypatch.setattr("app.app.kill_process_tree",
                        lambda proc, force=False: killed.__setitem__("n", killed["n"] + 1))

    proc = _LiveProc()
    task = _RacingTask(proc, url="u", folder="f", format_label="x",
                       format_info={"mode": "Audio and video",
                                    "audio": {"kind": "best_audio"},
                                    "video": {"kind": "best_video"}})
    task.status = "running"
    app = types.SimpleNamespace(
        download_queue=[task],
        download_current=task,
        refresh_download_queue=lambda: None,
        download_service=types.SimpleNamespace(process_queue=lambda: None),
        log=lambda _m: None,
    )

    App.pause_download(app, task)  # type: ignore[arg-type]
    assert task.status == "paused"
    assert killed["n"] == 1


# ---------------------------------------------------------------------------
# Finding 7 — Recent-files "Clear list" actually clears the list
# ---------------------------------------------------------------------------


class _FakeMenu:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    def delete(self, *_a) -> None:
        self.items.clear()

    def add_command(self, **kw) -> None:
        self.items.append((kw.get("label", ""), kw))

    def add_separator(self) -> None:
        self.items.append(("---", {}))

    def labels(self) -> list[str]:
        return [lbl for lbl, _ in self.items]


class _FakeHistory:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = rows

    def list_transcriptions(self, limit=200):  # noqa: ANN001
        return list(self._rows)[:limit]


def test_clear_recent_then_populate_shows_empty(monkeypatch):
    """Clicking 'Clear list' must hide the listed paths via the config
    dismissed-set so the next open shows '(no recent files)' — not a
    silent no-op."""
    saved = {"n": 0}
    monkeypatch.setattr("app.app.save_config",
                        lambda _c: saved.__setitem__("n", saved["n"] + 1))

    rows = [{"file_path": r"C:\a.mp4"}, {"file_path": r"C:\b.mp4"}]
    menu = _FakeMenu()
    app = types.SimpleNamespace(
        history=_FakeHistory(rows),
        app_config={},
        _recent_menu=menu,
        log=lambda _m: None,
    )
    # bind the real methods for cross-call use
    app._open_recent = lambda p: None
    app._clear_recent = lambda: App._clear_recent(app)  # type: ignore[arg-type]

    # Before clearing: both files listed + a "Clear list" command.
    App._populate_recent_menu(app)  # type: ignore[arg-type]
    assert "Clear list" in menu.labels()
    assert any("a.mp4" in lbl for lbl in menu.labels())

    # Clear.
    App._clear_recent(app)  # type: ignore[arg-type]
    assert saved["n"] == 1
    assert set(app.app_config["recent_files_dismissed"]) == {r"C:\a.mp4", r"C:\b.mp4"}

    # After clearing: dismissed paths are filtered out -> empty placeholder.
    App._populate_recent_menu(app)  # type: ignore[arg-type]
    assert menu.labels() == ["(no recent files)"]


def test_clear_recent_keeps_new_files_visible(monkeypatch):
    """A transcription added AFTER a clear (a path not in the dismissed
    set) still shows up."""
    monkeypatch.setattr("app.app.save_config", lambda _c: None)
    app = types.SimpleNamespace(
        history=_FakeHistory([{"file_path": r"C:\old.mp4"}]),
        app_config={"recent_files_dismissed": [r"C:\old.mp4"]},
        _recent_menu=_FakeMenu(),
        log=lambda _m: None,
    )
    app._open_recent = lambda p: None
    app._clear_recent = lambda: None
    # old.mp4 dismissed -> hidden
    App._populate_recent_menu(app)  # type: ignore[arg-type]
    assert app._recent_menu.labels() == ["(no recent files)"]

    # A new transcription arrives.
    app.history = _FakeHistory([{"file_path": r"C:\new.mp4"},
                                {"file_path": r"C:\old.mp4"}])
    App._populate_recent_menu(app)  # type: ignore[arg-type]
    labels = app._recent_menu.labels()
    assert any("new.mp4" in lbl for lbl in labels)
    assert not any("old.mp4" in lbl for lbl in labels)
    assert "Clear list" in labels


# ---------------------------------------------------------------------------
# Finding 8 — SMTV stream rejects empty (0-byte / chunked-dropped) downloads
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, chunks, content_length) -> None:  # noqa: ANN001
        self._chunks = list(chunks)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def read(self, _n):  # noqa: ANN001
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):  # noqa: ANN001
        return False


def _stream_svc():
    svc = DownloadService.__new__(DownloadService)
    svc.app = types.SimpleNamespace(  # type: ignore[attr-defined]
        download_events=types.SimpleNamespace(put=lambda _e: None),
    )
    return svc


def test_smtv_stream_rejects_zero_length_content(monkeypatch, tmp_path):
    """Content-Length: 0 (an error/edge body) used to slip past every
    `if total` gate and finalise a 0-byte file. It must now raise."""
    resp = _FakeResp(chunks=[], content_length=0)
    monkeypatch.setattr("app.services.download_service.urllib.request.urlopen",
                        lambda *a, **k: resp)
    svc = _stream_svc()
    task = types.SimpleNamespace(cancelled=False)
    dest = str(tmp_path / "out.part")
    with pytest.raises(RuntimeError, match="empty"):
        DownloadService._stream_smtv_file(svc, task, "http://cdn/x", dest)  # type: ignore[arg-type]


def test_smtv_stream_rejects_chunked_zero_bytes(monkeypatch, tmp_path):
    """No Content-Length (chunked) + a dropped connection that yielded 0
    bytes used to be treated as success. It must now raise."""
    resp = _FakeResp(chunks=[], content_length=None)
    monkeypatch.setattr("app.services.download_service.urllib.request.urlopen",
                        lambda *a, **k: resp)
    svc = _stream_svc()
    task = types.SimpleNamespace(cancelled=False)
    dest = str(tmp_path / "out.part")
    with pytest.raises(RuntimeError, match="empty"):
        DownloadService._stream_smtv_file(svc, task, "http://cdn/x", dest)  # type: ignore[arg-type]


def test_smtv_stream_accepts_chunked_nonempty(monkeypatch, tmp_path):
    """A real chunked download (no Content-Length, some bytes) still
    succeeds — we did not break the happy path."""
    resp = _FakeResp(chunks=[b"abc", b"def"], content_length=None)
    monkeypatch.setattr("app.services.download_service.urllib.request.urlopen",
                        lambda *a, **k: resp)
    svc = _stream_svc()
    task = types.SimpleNamespace(cancelled=False)
    dest = str(tmp_path / "out.part")
    DownloadService._stream_smtv_file(svc, task, "http://cdn/x", dest)  # type: ignore[arg-type]
    with open(dest, "rb") as f:
        assert f.read() == b"abcdef"


# ---------------------------------------------------------------------------
# Finding 9 — _split_dnd_paths handles filenames containing { and }
# ---------------------------------------------------------------------------


def test_split_dnd_brace_in_filename():
    raw = r"{C:\dir\my video {final}.mp4}"
    assert _split_dnd_paths(raw) == [r"C:\dir\my video {final}.mp4"]


def test_split_dnd_lone_close_brace_in_filename():
    raw = r"{C:\dir\weird }name.mp4}"
    assert _split_dnd_paths(raw) == [r"C:\dir\weird }name.mp4"]


def test_split_dnd_brace_file_then_plain_file():
    raw = r"{C:\dir\my video {v2}.mp4} C:\b.mp4"
    assert _split_dnd_paths(raw) == [r"C:\dir\my video {v2}.mp4", r"C:\b.mp4"]


def test_split_dnd_unc_with_space_still_intact():
    # Regression guard for the original UNC fix.
    raw = r"{\\server\share\my file.mp4}"
    assert _split_dnd_paths(raw) == [r"\\server\share\my file.mp4"]


def test_split_dnd_multi_mixed_with_brace():
    raw = r"C:\a.mp4 {\\server\share\my file.mp4} {C:\x\clip {hd}.mp4}"
    assert _split_dnd_paths(raw) == [
        r"C:\a.mp4",
        r"\\server\share\my file.mp4",
        r"C:\x\clip {hd}.mp4",
    ]


# ---------------------------------------------------------------------------
# Finding 10 — tray death while minimised un-strands the window
# ---------------------------------------------------------------------------


def _tray_controller(state: str, stopping: bool):
    from app.widgets.tray import TrayController

    tc = TrayController.__new__(TrayController)
    tc._icon = None  # type: ignore[attr-defined]
    tc._stopping = stopping  # type: ignore[attr-defined]
    calls = {"deiconify": 0, "lift": 0}
    fake_app = types.SimpleNamespace(
        tray=tc,
        state=lambda: state,
        deiconify=lambda: calls.__setitem__("deiconify", calls["deiconify"] + 1),
        lift=lambda: calls.__setitem__("lift", calls["lift"] + 1),
    )
    tc.app = fake_app  # type: ignore[attr-defined]
    return tc, fake_app, calls


def test_tray_crash_while_withdrawn_restores_window():
    """An unexpected tray death (not a deliberate stop) while the window
    was minimised-to-tray must deiconify it so the user isn't stranded."""
    tc, app, calls = _tray_controller(state="withdrawn", stopping=False)
    tc._on_runner_exit()
    assert app.tray is None          # controller marked dead
    assert calls["deiconify"] == 1   # window restored
    assert calls["lift"] == 1


def test_tray_clean_stop_while_withdrawn_leaves_window_alone():
    """A deliberate stop() (app exiting) must NOT re-show the window."""
    tc, app, calls = _tray_controller(state="withdrawn", stopping=True)
    tc._on_runner_exit()
    assert app.tray is None
    assert calls["deiconify"] == 0


def test_tray_crash_while_visible_does_not_touch_window():
    """If the window was visible (not withdrawn) when the tray died, leave
    it as-is."""
    tc, app, calls = _tray_controller(state="normal", stopping=False)
    tc._on_runner_exit()
    assert app.tray is None
    assert calls["deiconify"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
