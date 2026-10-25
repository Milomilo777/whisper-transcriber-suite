"""Optional webhook secret header and the per-delivery id.

Hermetic: the receiver is a loopback listener with the SSRF checks lifted,
exactly like tests/core/test_server_webhooks.py. No Tk.
"""
from __future__ import annotations

import http.server
import logging
import os
import re
import threading
import time
import types

import pytest

import gui
from core.config import DEFAULT_CONFIG
from core.server import jobs as jobs_mod
from core.server import netguard
from core.server.jobs import (
    STATUS_ERROR,
    STATUS_FINISHED,
    Job,
    JobManager,
    post_webhook,
    webhook_payload,
)

# Neutral dummy; never a real credential.
SECRET = "dummy-credential-A"


class _Receiver:
    """Loopback listener recording (headers, path) of every POST."""

    def __init__(self, status: int = 200):
        self.requests: list[dict[str, str]] = []
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or 0)
                self.rfile.read(length)
                outer.requests.append(
                    {k.lower(): v for k, v in self.headers.items()})
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):  # noqa: A002
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def wait(self, count: int = 1, timeout: float = 5.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and len(self.requests) < count:
            time.sleep(0.02)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda url: True)
    monkeypatch.setattr(
        netguard, "address_blocked", lambda ip, allow_private=True: False)
    rec = _Receiver()
    yield rec
    rec.close()


# --- header on the wire ------------------------------------------------------

def test_secret_header_sent_with_default_name(receiver):
    post_webhook(receiver.url, {"event": "job.finished"}, secret=SECRET)
    assert receiver.requests[0]["x-whisper-webhook-secret"] == SECRET


def test_secret_header_uses_custom_name(receiver):
    post_webhook(receiver.url, {}, secret=SECRET, header_name="X-N8n-Auth")
    headers = receiver.requests[0]
    assert headers["x-n8n-auth"] == SECRET
    assert "x-whisper-webhook-secret" not in headers


def test_no_header_when_secret_empty(receiver):
    post_webhook(receiver.url, {})
    post_webhook(receiver.url, {}, secret="", header_name="X-Anything")
    for headers in receiver.requests:
        assert "x-whisper-webhook-secret" not in headers
        assert "x-anything" not in headers
    assert len(receiver.requests) == 2


@pytest.mark.parametrize("name, secret", [
    ("X-Ok", "line1\r\nInjected: yes"),
    ("X-Ok", "café€"),
    ("Bad Name", SECRET),
    ("Content-Type", SECRET),
    ("X-Ok", " padded "),
])
def test_unusable_header_is_refused_without_leaking(
        receiver, caplog, name, secret):
    with caplog.at_level(logging.DEBUG):
        post_webhook(receiver.url, {}, secret=secret, header_name=name)
    assert receiver.requests == []
    assert secret.strip() not in caplog.text or not secret.strip()
    assert "Injected" not in caplog.text


# --- the secret never reaches the logs ---------------------------------------

def test_failed_delivery_does_not_log_the_secret(
        tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda url: True)
    monkeypatch.setattr(
        netguard, "address_blocked", lambda ip, allow_private=True: False)
    rec = _Receiver(status=500)
    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url=rec.url, webhook_secret=SECRET)
    mgr.start()
    try:
        with caplog.at_level(logging.DEBUG):
            mgr.submit_upload("clip.mp4", b"d", ["srt"])
            rec.wait()
            time.sleep(0.5)  # let the sender thread log the HTTP 500
    finally:
        mgr.stop()
        rec.close()
    assert rec.requests, "the webhook should have been attempted"
    assert "failed" in caplog.text, "the 500 should have been logged"
    assert SECRET not in caplog.text
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in str(record.exc_info)


def test_run_server_prints_header_name_but_not_secret(monkeypatch, capsys):
    import core.server as server_mod

    seen: dict = {}

    class _FakeHandle:
        _thread = None
        webhook_header = "X-Custom"

        def __init__(self, **_kw):
            pass

        def start(self, host, port, token, **kw):
            seen.update(kw)

        def urls(self):
            return []

        def stop(self):
            pass

    monkeypatch.setattr(server_mod, "ServerHandle", _FakeHandle)
    rc = server_mod.run_server(
        webhook_url="https://example.com/hook", webhook_secret=SECRET,
        webhook_header="X-Custom")
    out = capsys.readouterr().out
    assert rc == 0
    assert seen["webhook_secret"] == SECRET
    assert seen["webhook_header"] == "X-Custom"
    assert "secret set" in out.lower()
    assert "X-Custom" in out
    assert SECRET not in out


# --- delivery_id -------------------------------------------------------------

def test_delivery_id_is_a_fresh_uuid_hex_each_call():
    job = Job(job_id="x", kind="upload", formats=["srt"],
              status=STATUS_FINISHED)
    ids = [webhook_payload(job)["delivery_id"] for _ in range(50)]
    assert len(set(ids)) == 50
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    with open(f"{base}.srt", "w", encoding="utf-8") as f:
        f.write("dummy srt")
    task.output_paths = [f"{base}.srt"]
    if progress_cb:
        progress_cb(100)


def test_delivery_id_differs_per_posted_webhook(tmp_path):
    seen: list[dict] = []
    done = threading.Event()

    def sender(url, payload):
        seen.append(payload)
        if len(seen) == 2:
            done.set()

    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url="https://example.com/hook",
        webhook_sender=sender)
    mgr.start()
    try:
        mgr.submit_upload("a.mp4", b"d", ["srt"])
        mgr.submit_upload("b.mp4", b"d", ["srt"])
        assert done.wait(5.0)
    finally:
        mgr.stop()
    assert seen[0]["delivery_id"] != seen[1]["delivery_id"]
    assert all(len(p["delivery_id"]) == 32 for p in seen)


def test_manager_default_sender_sends_secret_header(tmp_path, receiver):
    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url=receiver.url,
        webhook_secret=SECRET, webhook_header="X-Hook-Auth")
    mgr.start()
    try:
        mgr.submit_upload("clip.mp4", b"d", ["srt"])
        receiver.wait()
    finally:
        mgr.stop()
    assert receiver.requests[0]["x-hook-auth"] == SECRET


def test_manager_without_secret_sends_no_header(tmp_path, receiver):
    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url=receiver.url)
    mgr.start()
    try:
        mgr.submit_upload("clip.mp4", b"d", ["srt"])
        receiver.wait()
    finally:
        mgr.stop()
    assert "x-whisper-webhook-secret" not in receiver.requests[0]


# --- config + CLI ------------------------------------------------------------

def test_config_defaults():
    assert DEFAULT_CONFIG["server_webhook_secret"] == ""
    assert (DEFAULT_CONFIG["server_webhook_header_name"]
            == "X-Whisper-Webhook-Secret")


def _fake_run_server(monkeypatch):
    import core.server as server_mod

    captured: dict = {}
    monkeypatch.setattr(
        server_mod, "run_server",
        lambda **kw: captured.update(kw) or 0)
    return captured


def test_cli_flags_win_over_config(monkeypatch):
    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "server_port": 8765, "server_webhook_secret": "from-config",
        "server_webhook_header_name": "X-Cfg"})
    args = gui._build_argparser().parse_args([
        "serve", "--webhook", "https://example.com/h",
        "--webhook-secret", SECRET, "--webhook-header", "X-Cli"])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == SECRET
    assert captured["webhook_header"] == "X-Cli"


def test_cli_falls_back_to_config(monkeypatch):
    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "server_port": 8765, "server_webhook_secret": SECRET,
        "server_webhook_header_name": "X-Cfg"})
    args = gui._build_argparser().parse_args(["serve"])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == SECRET
    assert captured["webhook_header"] == "X-Cfg"


def test_cli_explicit_empty_secret_overrides_config(monkeypatch):
    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "server_port": 8765, "server_webhook_secret": SECRET})
    args = gui._build_argparser().parse_args(["serve", "--webhook-secret="])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == ""


def test_cli_without_any_secret_passes_empty(monkeypatch):
    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {"server_port": 8765})
    args = gui._build_argparser().parse_args(["serve"])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == ""
    assert captured["webhook_header"] == ""


# --- the app's field saves to config (no Tk: unbound method on a stub) -------

class _Var:
    def __init__(self, value):
        self._v = value

    def get(self):
        return self._v


def test_app_save_prefs_stores_the_webhook_secret(monkeypatch):
    import sys

    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    import app.app as app_mod

    saved: dict = {}
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: saved.update(cfg))
    stub = types.SimpleNamespace(
        app_config={}, server_port_var=_Var(8765),
        server_share_lan_var=_Var(False), server_token_var=_Var(""),
        server_https_enabled_var=_Var(False),
        server_webhook_url_var=_Var("https://example.com/h"),
        server_webhook_secret_var=_Var(f"  {SECRET}  "),
        log=lambda *_a, **_k: None)
    app_mod.App._save_server_prefs(stub)  # type: ignore[arg-type]
    assert saved["server_webhook_secret"] == SECRET
    assert stub.app_config["server_webhook_secret"] == SECRET


def test_error_job_payload_also_has_delivery_id():
    job = Job(job_id="x", kind="url", formats=["srt"], status=STATUS_ERROR,
              error="boom")
    assert "delivery_id" in webhook_payload(job)


# --- review round: invalid secrets are refused, never shrunk to "no secret" --

BAD_SECRETS = ["\r\n", "\n", "   ", "\t", "dummy-credential-A\r\n",
               " dummy-credential-A", "dummy\x00credential"]


def _bad_id(secret: str) -> str:
    return repr(secret)


class _FakeHandle:
    """Stands in for ServerHandle in run_server tests."""

    _thread = None
    webhook_header = "X-Whisper-Webhook-Secret"
    started = 0

    def __init__(self, **_kw):
        pass

    def start(self, *a, **kw):
        type(self).started += 1

    def urls(self):
        return []

    def stop(self):
        pass


@pytest.mark.parametrize("secret", BAD_SECRETS, ids=_bad_id)
def test_manager_refuses_delivery_for_invalid_secret(
        tmp_path, receiver, caplog, secret):
    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url=receiver.url, webhook_secret=secret)
    mgr.start()
    try:
        with caplog.at_level(logging.DEBUG):
            mgr.submit_upload("clip.mp4", b"d", ["srt"])
            time.sleep(1.0)
    finally:
        mgr.stop()
    assert receiver.requests == [], "an invalid secret must not send anything"
    assert "cannot be used" in caplog.text
    assert "credential" not in caplog.text
    assert "dummy" not in caplog.text.replace("dummy srt", "")


@pytest.mark.parametrize("secret", BAD_SECRETS, ids=_bad_id)
def test_cli_passes_the_original_secret_and_run_server_refuses_it(
        monkeypatch, capsys, secret):
    import core.server as server_mod

    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {"server_port": 8765})
    args = gui._build_argparser().parse_args(
        ["serve", f"--webhook-secret={secret}"])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == secret, "must not be stripped"

    monkeypatch.undo()
    _FakeHandle.started = 0
    monkeypatch.setattr(server_mod, "ServerHandle", _FakeHandle)
    rc = server_mod.run_server(
        webhook_url="https://example.com/h", webhook_secret=secret)
    err = capsys.readouterr().err
    assert rc == 1 and _FakeHandle.started == 0
    assert "webhook secret cannot be used" in err
    assert "credential" not in err


@pytest.mark.parametrize("secret", BAD_SECRETS[:4], ids=_bad_id)
def test_config_value_is_passed_unstripped(monkeypatch, secret):
    captured = _fake_run_server(monkeypatch)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "server_port": 8765, "server_webhook_secret": secret})
    args = gui._build_argparser().parse_args(["serve"])
    assert gui._cli_serve(args) == 0
    assert captured["webhook_secret"] == secret


@pytest.mark.parametrize("typed, stored", [
    ("", ""),
    ("abc", "abc"),
    ("  abc  ", "abc"),
    ("\r\n", "\r\n"),
    ("   ", "   "),
    ("abc\r\n", "abc\r\n"),
    ("\tabc", "\tabc"),
], ids=_bad_id)
def test_gui_input_is_trimmed_of_spaces_only(typed, stored):
    from core.config import webhook_secret_from_input

    assert webhook_secret_from_input(typed) == stored
    assert webhook_secret_from_input(None) == ""


@pytest.mark.parametrize("typed", ["\r\n", "   ", "abc\r\n"], ids=_bad_id)
def test_app_save_never_turns_an_invalid_secret_into_a_different_one(
        monkeypatch, typed):
    import sys

    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    import app.app as app_mod
    from core.server.jobs import webhook_secret_valid

    monkeypatch.setattr(app_mod, "save_config", lambda cfg: None)
    stub = types.SimpleNamespace(
        app_config={}, server_port_var=_Var(8765),
        server_share_lan_var=_Var(False), server_token_var=_Var(""),
        server_https_enabled_var=_Var(False), server_webhook_url_var=_Var(""),
        server_webhook_secret_var=_Var(typed), log=lambda *_a, **_k: None)
    app_mod.App._save_server_prefs(stub)  # type: ignore[arg-type]
    saved = stub.app_config["server_webhook_secret"]
    assert saved == typed, "kept as typed, not stripped to empty"
    assert saved != "" and not webhook_secret_valid(saved)


# --- plain http:// warning ---------------------------------------------------

@pytest.mark.parametrize("url, secret, expect", [
    ("http://n8n.lan:5678/webhook/x", SECRET, True),
    ("HTTP://n8n.lan/x", SECRET, True),
    ("https://n8n.example.com/x", SECRET, False),
    ("http://n8n.lan/x", "", False),
])
def test_run_server_warns_about_plain_http_with_a_secret(
        monkeypatch, capsys, url, secret, expect):
    import core.server as server_mod

    monkeypatch.setattr(server_mod, "ServerHandle", _FakeHandle)
    server_mod.run_server(webhook_url=url, webhook_secret=secret)
    out = capsys.readouterr().out
    assert ("plain text" in out) is expect
    assert SECRET not in out


def test_handle_start_logs_the_plain_http_warning_without_the_secret(
        monkeypatch, caplog):
    import core.server as server_mod

    class _Stop(Exception):
        pass

    def _boom(*_a, **_k):
        raise _Stop()

    handle = server_mod.ServerHandle(
        transcribe_fn=lambda *a, **k: None, load_model=False)
    monkeypatch.setattr(server_mod, "JobManager", _boom)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_Stop):
            handle.start(port=0, webhook_url="http://n8n.lan/x",
                         webhook_secret=SECRET)
    assert "plain text" in caplog.text
    assert SECRET not in caplog.text


# --- delivery_id as received on the wire -------------------------------------

def test_two_real_deliveries_carry_distinct_uuid4_ids(tmp_path, monkeypatch):
    import json
    import uuid

    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda url: True)
    monkeypatch.setattr(
        netguard, "address_blocked", lambda ip, allow_private=True: False)
    bodies: list[dict] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or 0)
            bodies.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    mgr = JobManager(
        _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
        record_history=False, webhook_url=url, webhook_secret=SECRET)
    mgr.start()
    try:
        mgr.submit_upload("a.mp4", b"d", ["srt"])
        mgr.submit_upload("b.mp4", b"d", ["srt"])
        deadline = time.time() + 8
        while time.time() < deadline and len(bodies) < 2:
            time.sleep(0.05)
    finally:
        mgr.stop()
        server.shutdown()
        server.server_close()
    assert len(bodies) == 2
    ids = [b["delivery_id"] for b in bodies]
    assert ids[0] != ids[1]
    for did in ids:
        assert re.fullmatch(r"[0-9a-f]{32}", did)
        assert uuid.UUID(hex=did).version == 4
