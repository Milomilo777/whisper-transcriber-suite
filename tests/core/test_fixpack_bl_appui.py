r"""Regression tests for the frontend-edge backlog cluster (appui).

Each test pins a fix made in ``app/app.py``; all are hermetic — no Tk root,
no network, no model. UI methods are exercised as unbound functions on a bare
``App.__new__(App)`` object with only the attributes the method touches stubbed
(the App.__new__ + stubbed-attrs pattern from test_fixpack_frontend_edges.py).

Covered:
  (a) Re-run / Resume dedup — a finished row re-run twice (or re-run while a
      prior re-run of the same file is still pending) must NOT enqueue a second
      concurrent transcription of the same file.
  (c) _start_server_async clamps an out-of-range typed port (0 / >65535) to the
      default before binding, mirroring _save_server_prefs.
  (g) _on_server_started gives a DISTINCT status when LAN sharing was requested
      but the network address couldn't be detected (no misleading
      "Running on this computer.").
  (d/e/f) _on_drop logs a clear message for a no-op drop (folder / dead path),
      for a multi-URL drop (only the first used), recognises file:// URIs, and
      flags unsupported schemes (ftp:/magnet:/smb:) instead of swallowing them.
  _file_uri_to_path conversion.
"""
from __future__ import annotations

import os
import sys
import types

import pytest


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


class _Svc:
    def ensure_worker_ready(self, app):  # noqa: ARG002
        return True


def _bare_app(App):
    a = App.__new__(App)
    a.queue = []
    a.transcription_service = _Svc()
    a.refresh = lambda *x, **k: None
    a.logs = []
    a.log = a.logs.append
    return a


def _task(file="movie.wav", status="finished"):
    from core.task import TranscriptionTask
    t = TranscriptionTask(file)
    t.status = status
    return t


# --- (a) Re-run / Resume dedup ----------------------------------------------

def test_rerun_blocked_when_same_file_still_pending(App):
    a = _bare_app(App)
    # A non-terminal task for the same file is already queued.
    a.queue.append(_task("movie.wav", status="waiting"))
    App._rerun_task(a, _task("movie.wav", status="finished"))
    # No second concurrent task was enqueued.
    assert len(a.queue) == 1
    assert any("already in the queue" in m for m in a.logs)


def test_rerun_allowed_when_only_terminal_dups(App):
    a = _bare_app(App)
    # Prior runs of the same file are all terminal — a fresh re-run is fine.
    a.queue.append(_task("movie.wav", status="finished"))
    App._rerun_task(a, _task("movie.wav", status="finished"))
    assert len(a.queue) == 2


def test_resume_blocked_when_same_file_running(App):
    a = _bare_app(App)
    a.queue.append(_task("clip.wav", status="running"))
    App.resume_task(a, _task("clip.wav", status="cancelled"))
    assert len(a.queue) == 1
    assert any("already in the queue" in m for m in a.logs)


def test_bulk_rerun_skips_pending_dup_only(App):
    a = _bare_app(App)
    a.queue.append(_task("a.wav", status="running"))   # blocks a.wav
    App._bulk_rerun(a, [_task("a.wav"), _task("b.wav")])
    # a.wav skipped, b.wav enqueued.
    files = [t.file_path for t in a.queue]
    assert files.count("a.wav") == 1 and "b.wav" in files


def test_bulk_resume_skips_pending_dup_only(App):
    a = _bare_app(App)
    a.queue.append(_task("a.wav", status="paused"))
    App._bulk_resume(a, [_task("a.wav"), _task("b.wav")])
    files = [t.file_path for t in a.queue]
    assert files.count("a.wav") == 1 and "b.wav" in files


def test_rerun_of_distinct_file_not_blocked(App):
    a = _bare_app(App)
    a.queue.append(_task("other.wav", status="running"))
    App._rerun_task(a, _task("movie.wav", status="finished"))
    assert len(a.queue) == 2


# --- (c) server port clamp ---------------------------------------------------

class _Var:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Btn:
    def config(self, **k):  # noqa: ARG002
        pass


def _make_fake_core_server(recorder):
    mod = types.ModuleType("core.server")
    mod.HOST_LAN = "0.0.0.0"
    mod.HOST_LOOPBACK = "127.0.0.1"

    class _Handle:
        def __init__(self):
            self.port = 0

        def start(self, host, port, token, *, max_upload_mb=512,  # noqa: ARG002
                  https=False, webhook_url=""):
            recorder["host"] = host
            recorder["port"] = port
            recorder["https"] = https
            recorder["webhook_url"] = webhook_url
            # Mimic auto_port: an in-range port binds verbatim.
            self.port = port

        def urls(self):
            if recorder["host"] == "0.0.0.0":
                # Simulate the share-LAN case with LAN-IP detection available.
                return [f"http://127.0.0.1:{self.port}/",
                        f"http://192.168.1.5:{self.port}/"]
            return [f"http://127.0.0.1:{self.port}/"]

    mod.ServerHandle = _Handle
    return mod


def _server_app(App, typed_port):
    a = App.__new__(App)
    a.app_config = {}
    a.server_port_var = _Var(typed_port)
    a.server_share_lan_var = _Var(False)
    a.server_token_var = _Var("")
    a.server_https_enabled_var = _Var(False)
    a.server_webhook_url_var = _Var("")
    a.server_toggle_btn = _Btn()
    a.server_status_var = _Var("")
    a.server_url_var = _Var("")
    a._server_busy = False
    a.post_to_main = lambda fn: fn()
    a._on_server_started = lambda *x: None
    a._on_server_failed = lambda *x: None
    return a


def _run_start_sync(App, monkeypatch, a):
    """Drive _start_server_async with the worker thread running inline."""
    import threading as real_threading

    class _SyncThread:
        def __init__(self, target=None, name=None, daemon=None):  # noqa: ARG002
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(real_threading, "Thread", _SyncThread)
    App._start_server_async(a)


def test_start_server_clamps_overflow_port(App, monkeypatch):
    rec: dict = {}
    monkeypatch.setitem(sys.modules, "core.server",
                        _make_fake_core_server(rec))
    a = _server_app(App, typed_port=99999)
    _run_start_sync(App, monkeypatch, a)
    # 99999 is out of range -> clamped to the 8765 default, not passed raw.
    assert rec["port"] == 8765


def test_start_server_clamps_zero_port(App, monkeypatch):
    rec: dict = {}
    monkeypatch.setitem(sys.modules, "core.server",
                        _make_fake_core_server(rec))
    a = _server_app(App, typed_port=0)
    _run_start_sync(App, monkeypatch, a)
    assert rec["port"] == 8765


def test_start_server_keeps_valid_port(App, monkeypatch):
    rec: dict = {}
    monkeypatch.setitem(sys.modules, "core.server",
                        _make_fake_core_server(rec))
    a = _server_app(App, typed_port=8080)
    _run_start_sync(App, monkeypatch, a)
    assert rec["port"] == 8080


# --- (g) LAN-detection-failed status ----------------------------------------

def _started_app(App):
    a = App.__new__(App)
    a.app_config = {}
    a.server_port_var = _Var(8765)
    a.server_toggle_btn = _Btn()
    a.server_open_btn = _Btn()
    a.server_status_var = _Var("")
    a.server_url_var = _Var("")
    a._server_busy = True
    a.logs = []
    a.log = a.logs.append
    return a


def test_lan_share_with_failed_ip_gives_distinct_status(App):
    a = _started_app(App)
    # share_lan requested, but reachable_urls returned only the loopback URL
    # (LAN-IP detection failed) -> single-element urls list.
    App._on_server_started(a, ["http://127.0.0.1:8765/"], 8765, True)
    status = a.server_status_var.get()
    assert "couldn't be detected" in status
    assert status != "Running on this computer."


def test_lan_share_with_ip_reports_network(App):
    a = _started_app(App)
    App._on_server_started(
        a, ["http://127.0.0.1:8765/", "http://192.168.1.5:8765/"], 8765, True)
    assert "your network" in a.server_status_var.get()


def test_loopback_only_reports_local(App):
    a = _started_app(App)
    App._on_server_started(a, ["http://127.0.0.1:8765/"], 8765, False)
    assert a.server_status_var.get() == "Running on this computer."


# --- (d/e/f) drop edges ------------------------------------------------------

class _Nb:
    def __init__(self):
        self.selected = None

    def select(self, tab):
        self.selected = tab


def _drop_app(App):
    a = App.__new__(App)
    a.fv = _Var("")
    a.download_url_var = _Var("")
    a.nb = _Nb()
    a.t1 = "transcribe"
    a.t3 = "download"
    a.logs = []
    a.log = a.logs.append
    a.enqueued = []

    def _bulk(paths):
        a.enqueued.extend(paths)
        return len(paths)

    a._bulk_enqueue = _bulk
    return a


def test_drop_dead_path_is_flagged_not_silent(App, monkeypatch):
    # A path that is neither a file nor an existing folder is itemised in
    # the "Ignored N dropped item(s)" log line (it used to fall through to
    # the generic "Nothing to do" catch-all; folders are now expanded into
    # their media files instead — covered in tests/core/test_dnd_paths.py).
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: False)
    monkeypatch.setattr("app.app.os.path.isdir", lambda s: False)
    a = _drop_app(App)
    App._on_drop(a, types.SimpleNamespace(data=r"C:\some\folder"))
    assert any("Ignored 1 dropped item" in m for m in a.logs)


def test_drop_multi_url_notes_only_first_used(App, monkeypatch):
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: False)
    a = _drop_app(App)
    App._on_drop(a, types.SimpleNamespace(
        data="https://a.example/v1 https://b.example/v2"))
    assert a.download_url_var.get() == "https://a.example/v1"
    assert any("Only the first" in m for m in a.logs)


def test_drop_unsupported_scheme_flagged(App, monkeypatch):
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: False)
    monkeypatch.setattr("app.app.os.path.isdir", lambda s: False)
    a = _drop_app(App)
    App._on_drop(a, types.SimpleNamespace(data="ftp://host/clip.mp4"))
    assert any("Ignored 1 dropped item" in m for m in a.logs)
    # Nothing was enqueued or routed.
    assert a.enqueued == [] and a.download_url_var.get() == ""


def test_drop_magnet_scheme_flagged(App, monkeypatch):
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: False)
    monkeypatch.setattr("app.app.os.path.isdir", lambda s: False)
    a = _drop_app(App)
    App._on_drop(a, types.SimpleNamespace(data="magnet:?xt=urn:btih:abc"))
    assert any("Ignored 1 dropped item" in m for m in a.logs)


@pytest.mark.skipif(
    os.name != "nt",
    reason="file:///C:/... resolves to a Windows path only on Windows; on POSIX "
    "url2pathname yields '/C:/...', which is not a real local file.",
)
def test_drop_file_uri_resolves_to_local_path(App, monkeypatch):
    real = r"C:\videos\clip.mp4"
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s == real)
    a = _drop_app(App)
    App._on_drop(a, types.SimpleNamespace(data="file:///C:/videos/clip.mp4"))
    # Resolved + treated as a single dropped file (lands in the file field).
    assert a.fv.get() == real
    assert a.nb.selected == a.t1


# --- _file_uri_to_path -------------------------------------------------------

@pytest.mark.skipif(
    os.name != "nt",
    reason="url2pathname maps file:///C:/... to a Windows path only on Windows.",
)
def test_file_uri_to_path_windows():
    from app.app import _file_uri_to_path
    assert _file_uri_to_path("file:///C:/videos/my%20clip.mp4") == \
        r"C:\videos\my clip.mp4"


def test_file_uri_to_path_non_file_uri_returns_empty():
    from app.app import _file_uri_to_path
    assert _file_uri_to_path("ftp://host/x") == ""
    assert _file_uri_to_path(r"C:\plain\path.mp4") == ""


def test_model_bytes_present_accepts_hub_folder_fallback(App, tmp_path):
    from core.hub import model_folder_for

    a = App.__new__(App)
    hub = tmp_path / "Cache" / "models"
    model_dir = model_folder_for(hub, "faster-whisper-large-v3")
    model_dir.mkdir(parents=True)
    a.app_config = {
        "model_path": "",
        "hub_folder": str(hub),
        "model": {"name": "faster-whisper-large-v3"},
    }
    assert App._model_bytes_present(a) is True


# --- download range slider clamp -------------------------------------------


class _Scale:
    def __init__(self):
        self.values: list[float] = []

    def set(self, value):
        self.values.append(value)


def _download_range_app(App):
    a = App.__new__(App)
    a._download_duration = 120.0
    a._suppress_scale_cb = False
    a.download_start_time_var = _Var("0:00:30")
    a.download_end_time_var = _Var("0:01:00")
    a.download_start_scale = _Scale()
    a.download_end_scale = _Scale()
    return a


def test_download_start_slider_clamps_past_end(App):
    a = _download_range_app(App)
    App._on_download_scale(a, "start", "90")
    assert a.download_start_time_var.get() == "0:01:30"
    assert a.download_end_time_var.get() == "0:01:30"
    assert a.download_end_scale.values == [90.0]


def test_download_end_slider_clamps_before_start(App):
    a = _download_range_app(App)
    App._on_download_scale(a, "end", "15")
    assert a.download_end_time_var.get() == "0:00:15"
    assert a.download_start_time_var.get() == "0:00:15"
    assert a.download_start_scale.values == [15.0]


# --- _sync_download_scale_from_text: typing a Start/End field must move
# the paired slider too (2026-08-14, self-review). Before this fix,
# _on_download_scale only wrote slider -> field; a value typed directly
# left the slider at its stale (usually 0:00:00) position, and the next
# drag on EITHER knob silently snapped the typed value back to wherever
# that slider still visually sat.


def test_typing_start_field_syncs_the_start_slider(App):
    a = _download_range_app(App)
    a.download_start_time_var.set("0:00:45")
    App._sync_download_scale_from_text(a, "start")
    assert a.download_start_scale.values == [45.0]


def test_typing_end_field_syncs_the_end_slider(App):
    a = _download_range_app(App)
    a.download_end_time_var.set("0:01:30")
    App._sync_download_scale_from_text(a, "end")
    assert a.download_end_scale.values == [90.0]


def test_sync_ignores_unparseable_text(App):
    """Mid-typing / garbled text must not snap the slider to a meaningless
    position -- it should just leave the slider where it was."""
    a = _download_range_app(App)
    a.download_start_time_var.set("garbage")
    App._sync_download_scale_from_text(a, "start")
    assert a.download_start_scale.values == []


def test_sync_is_a_noop_while_suppressed(App):
    """_on_download_scale's cross-snap path raises _suppress_scale_cb
    before writing the OTHER field's var -- the sync must not re-drive a
    slider that code path is already positioning explicitly (would be
    redundant at best, a feedback loop at worst)."""
    a = _download_range_app(App)
    a._suppress_scale_cb = True
    a.download_start_time_var.set("0:00:45")
    App._sync_download_scale_from_text(a, "start")
    assert a.download_start_scale.values == []


def test_sync_ignored_when_duration_unknown(App):
    """No probed video length yet -- there is nothing meaningful to sync
    the (disabled) slider to."""
    a = _download_range_app(App)
    a._download_duration = 0.0
    a.download_start_time_var.set("0:00:45")
    App._sync_download_scale_from_text(a, "start")
    assert a.download_start_scale.values == []


# --- (h) _save_transcribe_prefs must not clobber Advanced-dialog hotwords ----
#
# hotwords_var has no matching widget on the Transcribe tab (see
# build_transcribe_tab's "vars without a matching widget are simply not
# packed" note) -- it is frozen at whatever config.json held when the tab
# was built. AdvancedDialog._save_and_close is the real editor of
# cfg["hotwords"]. Before the 2026-08-15 fix, _save_transcribe_prefs
# unconditionally wrote hotwords_var's stale value back into
# app_config["hotwords"] -- so editing hotwords in Advanced, then merely
# touching the language dropdown or a checkbox on the Transcribe tab
# (either one calls this same method), silently reverted the edit and
# persisted the revert to disk.


def _transcribe_prefs_app(App, *, hotwords_var_value, cfg_hotwords):
    a = App.__new__(App)
    a.app_config = {"hotwords": cfg_hotwords}
    a.vad_enabled_var = _Var(True)
    a.word_timestamps_var = _Var(False)
    a.hotwords_var = _Var(hotwords_var_value)
    # Explicit None (not just absent): tk.Misc.__getattr__ (App's base
    # class) proxies any truly-missing attribute to self.tk, which recurses
    # forever on a bare App.__new__(App) with no real Tcl interpreter. The
    # method's own getattr(self, name, None) guards need a REAL attribute
    # to find so they never fall through to that proxy.
    a.diarization_var = None
    a.device_var = None
    a.compute_type_var = None
    a.log = lambda *a_, **k: None
    return a


def test_save_transcribe_prefs_does_not_touch_hotwords(App, monkeypatch):
    monkeypatch.setattr("app.app.save_config", lambda _cfg: None)
    # hotwords_var still holds whatever was in config.json at app launch;
    # app_config["hotwords"] already holds a NEWER value an Advanced-dialog
    # save just wrote. They deliberately differ to prove the stale var
    # cannot win.
    a = _transcribe_prefs_app(
        App,
        hotwords_var_value="stale startup-time value",
        cfg_hotwords="fresh value just saved in Advanced",
    )
    App._save_transcribe_prefs(a)
    assert a.app_config["hotwords"] == "fresh value just saved in Advanced"


def test_save_transcribe_prefs_still_saves_word_timestamps(App, monkeypatch):
    """The fix must remove only the vad_enabled/hotwords writes (both now
    solely owned by AdvancedDialog), not the whole method."""
    saved = {}
    monkeypatch.setattr("app.app.save_config", lambda cfg: saved.update(cfg))
    a = _transcribe_prefs_app(App, hotwords_var_value="x", cfg_hotwords="")
    a.word_timestamps_var.set(True)
    App._save_transcribe_prefs(a)
    assert a.app_config["word_timestamps"] is True
    assert saved == a.app_config


def test_save_transcribe_prefs_does_not_touch_vad_enabled(App, monkeypatch):
    """vad_enabled_var has no widget either (same shape as hotwords_var,
    added 2026-08-15 alongside the new Advanced-dialog "Enable VAD"
    checkbox) -- must not clobber a fresher cfg["vad_enabled"] either."""
    monkeypatch.setattr("app.app.save_config", lambda _cfg: None)
    a = _transcribe_prefs_app(App, hotwords_var_value="x", cfg_hotwords="")
    a.app_config["vad_enabled"] = False  # fresher value, just saved in Advanced
    a.vad_enabled_var = _Var(True)  # stale startup-time value
    App._save_transcribe_prefs(a)
    assert a.app_config["vad_enabled"] is False
