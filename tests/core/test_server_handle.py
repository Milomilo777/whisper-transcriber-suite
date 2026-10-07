"""Unit tests for the start/stop ServerHandle + the free-port helper.

Fast + offline: a stub transcribe is injected (no model loads), and the
handle binds an ephemeral loopback port (127.0.0.1) which is torn down at
the end of each test. No network egress.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.request

from core.server import ServerHandle, find_available_port


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    """Write a dummy output beside the input — never touches the model."""
    # The real engine reads these bare off the task; touch them so a future
    # missing attribute fails the hermetic suite, not only a live server job.
    assert hasattr(task, "paused")
    assert hasattr(task, "cancelled")
    _ = task.paused
    _ = task.cancelled
    base, _ = os.path.splitext(task.file_path)
    for fmt in (task.output_formats or ["srt"]):
        with open(f"{base}.{fmt}", "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
    if progress_cb:
        progress_cb(100)


# --- find_available_port -----------------------------------------------------

def test_free_port_returns_preferred_when_available():
    # Ask the OS for a free ephemeral port, release it, then assert the
    # finder hands that same port back (it is free again).
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()
    got = find_available_port(free, "127.0.0.1")
    assert got == free


def test_free_port_falls_back_when_preferred_is_taken():
    # Hold a port with a plain listener (no SO_REUSEADDR — models a real
    # conflicting app) so it is NOT bindable, then assert the finder
    # returns a DIFFERENT, still-bindable port instead of raising.
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    taken = holder.getsockname()[1]
    try:
        got = find_available_port(taken, "127.0.0.1")
        assert got != taken
        # The fallback port must itself be bindable right now.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", got))
        probe.close()
    finally:
        holder.close()


def test_free_port_rejects_out_of_range_preferred():
    # 0 / negative / >65535 are not valid preferred ports — the finder
    # must still return a usable ephemeral port.
    for bad in (0, -1, 70000):
        got = find_available_port(bad, "127.0.0.1")
        assert 1 <= got <= 65535


# --- ServerHandle lifecycle --------------------------------------------------

def test_handle_start_stop_lifecycle(tmp_path):
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    assert not handle.is_running()
    handle.start("127.0.0.1", 0, max_upload_mb=8)
    try:
        assert handle.is_running()
        assert handle.port > 0
        assert handle.host == "127.0.0.1"
        # urls() reflects the loopback bind.
        urls = handle.urls()
        assert urls == [f"http://127.0.0.1:{handle.port}/"]
        # Health endpoint answers over real HTTP.
        with urllib.request.urlopen(urls[0] + "api/health", timeout=5) as r:
            body = json.loads(r.read().decode("utf-8"))
            assert body["status"] == "ok"
    finally:
        handle.stop()
    assert not handle.is_running()
    assert handle.urls() == []


def test_handle_double_start_is_idempotent():
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    handle.start("127.0.0.1", 0)
    try:
        first_port = handle.port
        # Second start must NOT bind a new socket / replace the server.
        handle.start("127.0.0.1", 0)
        assert handle.port == first_port
        assert handle.is_running()
    finally:
        handle.stop()


def test_handle_stop_when_not_running_is_noop():
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    # Should not raise.
    handle.stop()
    assert not handle.is_running()


def test_handle_can_restart_after_stop():
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    handle.start("127.0.0.1", 0)
    handle.stop()
    assert not handle.is_running()
    handle.start("127.0.0.1", 0)
    try:
        assert handle.is_running()
        assert handle.port > 0
    finally:
        handle.stop()


def test_stop_does_not_wait_for_a_start_that_is_still_loading_the_model(monkeypatch):
    # start() used to hold the handle's lock through the first-run model download, so
    # is_running() and stop() (the app's exit path) blocked until the download ended.
    import threading

    import core.server as server_mod

    loading = threading.Event()
    release = threading.Event()

    def _slow_model_load():
        loading.set()
        release.wait(10)

    monkeypatch.setattr(server_mod, "_ensure_model_loaded", _slow_model_load)
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=True)
    starter = threading.Thread(
        target=lambda: handle.start("127.0.0.1", 0, auto_port=False), daemon=True)
    starter.start()
    try:
        assert loading.wait(5)
        t0 = time.monotonic()
        assert not handle.is_running()
        handle.stop(timeout=3.0)
        assert time.monotonic() - t0 < 1.0, "stop() waited for the model load"
    finally:
        release.set()
        starter.join(10)
    # The start that was stopped part-way must not begin serving afterwards.
    assert not starter.is_alive()
    assert not handle.is_running()
    assert handle.urls() == []


def _slow_loading_handle(monkeypatch):
    import threading

    import core.server as server_mod

    loads = []
    loading = threading.Event()
    release = threading.Event()

    def _slow_model_load():
        loads.append(1)
        loading.set()
        release.wait(10)

    monkeypatch.setattr(server_mod, "_ensure_model_loaded", _slow_model_load)
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=True)
    return handle, loads, loading, release


def _start_in_thread(handle):
    import threading

    thread = threading.Thread(
        target=lambda: handle.start("127.0.0.1", 0, auto_port=False), daemon=True)
    thread.start()
    return thread


def test_a_second_start_waits_for_the_first_and_does_not_load_again(monkeypatch):
    handle, loads, loading, release = _slow_loading_handle(monkeypatch)
    first = _start_in_thread(handle)
    try:
        assert loading.wait(5)
        second = _start_in_thread(handle)
        second.join(0.3)
        assert second.is_alive(), "the second start() returned before the server was up"
        release.set()
        first.join(10)
        second.join(10)
        assert loads == [1]
        assert handle.is_running()
    finally:
        release.set()
        handle.stop()


def test_a_start_after_a_stop_during_loading_still_starts(monkeypatch):
    # stop() cancels the start that is loading; a start() requested after that stop must
    # not be swallowed by the cancelled one.
    handle, loads, loading, release = _slow_loading_handle(monkeypatch)
    first = _start_in_thread(handle)
    try:
        assert loading.wait(5)
        handle.stop(timeout=1.0)
        second = _start_in_thread(handle)
        release.set()
        first.join(10)
        second.join(10)
        assert loads == [1, 1]
        assert handle.is_running(), "the last request was start, so a server must run"
    finally:
        release.set()
        handle.stop()


def test_handle_auto_port_avoids_busy_port():
    # Occupy a port (plain listener, no SO_REUSEADDR), then ask the handle
    # to start on it with auto_port: it must bind a different one rather
    # than failing.
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    busy = holder.getsockname()[1]
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    try:
        handle.start("127.0.0.1", busy, auto_port=True)
        assert handle.is_running()
        assert handle.port != busy
    finally:
        handle.stop()
        holder.close()


def test_handle_no_auto_port_raises_on_busy_port():
    # With auto_port off, binding a busy port must raise OSError (the CLI
    # path relies on this to report a clear "could not bind" message). Use
    # a plain listener so the server's allow_reuse_address can't dual-bind.
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    busy = holder.getsockname()[1]
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    try:
        raised = False
        try:
            handle.start("127.0.0.1", busy, auto_port=False)
        except OSError:
            raised = True
        assert raised, "expected OSError binding a busy port with auto_port off"
        # A failed start must leave the handle stopped (no leaked worker).
        assert not handle.is_running()
    finally:
        handle.stop()
        holder.close()


def test_handle_token_is_enforced():
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    handle.start("127.0.0.1", 0, token="letmein")
    try:
        base = handle.urls()[0]
        # No token -> 401.
        import urllib.error
        code = 0
        try:
            urllib.request.urlopen(base + "api/health", timeout=5)
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 401
        # With the token -> 200.
        with urllib.request.urlopen(
            base + "api/health?token=letmein", timeout=5
        ) as r:
            assert r.status == 200
    finally:
        handle.stop()


def test_handle_serves_a_full_upload_job(tmp_path):
    handle = ServerHandle(transcribe_fn=_writing_transcribe, load_model=False)
    handle.start("127.0.0.1", 0, max_upload_mb=8)
    try:
        base = handle.urls()[0]
        boundary = "----handleboundary"
        parts = [
            f"--{boundary}",
            'Content-Disposition: form-data; name="formats"',
            "", "srt",
            f"--{boundary}",
            'Content-Disposition: form-data; name="file"; filename="a.mp4"',
            "Content-Type: video/mp4",
            "", "RAWMEDIA",
            f"--{boundary}--", "",
        ]
        body = "\r\n".join(parts).encode("utf-8")
        req = urllib.request.Request(
            base + "api/jobs", data=body, method="POST",
            headers={"Content-Type":
                     f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            job_id = json.loads(r.read().decode("utf-8"))["job_id"]
        deadline = time.time() + 5
        final = None
        while time.time() < deadline:
            with urllib.request.urlopen(
                base + f"api/jobs/{job_id}", timeout=5
            ) as r:
                jb = json.loads(r.read().decode("utf-8"))
            if jb["status"] in ("finished", "error", "cancelled"):
                final = jb
                break
            time.sleep(0.05)
        assert final is not None and final["status"] == "finished"
        assert {o["fmt"] for o in final["outputs"]} == {"srt"}
    finally:
        handle.stop()
