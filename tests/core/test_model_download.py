"""Pinned model transfers against real loopback HTTP servers; no Tk or Hub access."""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import model_download as md
from core import model_manager as mm


REPO = "fixture/tiny"
COMMIT = "a" * 40
PAYLOAD = bytes(range(256)) * 4096


def entry(data=PAYLOAD, **files):
    return md.parse_entry({
        "commit": COMMIT,
        "files": {name: {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                  for name, body in {"model.bin": data, **files}.items()},
        "hosts": [],
    })


class Server:
    """Each GET can cut, stall, redirect, ignore Range, or lie about its headers."""

    def __init__(self, data=PAYLOAD, actions=(), head_stall=False):
        self.data = data
        self.actions = list(actions)
        self.gets = []
        self.heads = []
        self.head_entered = threading.Event()
        self.sent = threading.Event()
        self.release = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def reset_connection(self):
                linger = struct.pack("HH" if os.name == "nt" else "ii", 1, 0)
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                self.close_connection = True
                self.connection.close()

            def do_HEAD(self):
                owner.heads.append(self.path)
                owner.head_entered.set()
                if head_stall:
                    owner.release.wait(3)
                self.send_response(200)
                self.send_header("Content-Length", str(len(owner.data)))
                self.end_headers()

            def do_GET(self):
                owner.gets.append((self.path, self.headers.get("Range")))
                action = owner.actions.pop(0) if owner.actions else {}
                if action.get("reset_headers"):
                    self.reset_connection()
                    return
                if action.get("stall_headers"):
                    owner.release.wait(3)
                status = action.get("status", 206 if self.headers.get("Range") else 200)
                body = action.get("data", owner.data)
                start = int(self.headers.get("Range", "bytes=0-")[6:-1]) if status == 206 else 0
                self.send_response(status)
                if "redirect" in action:
                    self.send_header("Location", action["redirect"])
                    redirect_body = action.get("redirect_body", b"")
                    self.send_header("Content-Length", str(len(redirect_body)))
                    self.end_headers()
                    with contextlib.suppress(OSError):
                        self.wfile.write(redirect_body)
                    return
                if status not in (200, 206):
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = body[start:]
                if status == 206:
                    self.send_header("Content-Range", action.get(
                        "range", f"bytes {start}-{len(owner.data)-1}/{len(owner.data)}"))
                if action.get("chunked"):
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Content-Length", str(action.get("length", len(body))))
                self.end_headers()
                cut = action.get("cut", len(body))
                try:
                    if action.get("chunked"):
                        self.wfile.write(f"{len(body):x};extension=".encode())
                        for _ in range(20 if action.get("drip") else 0):
                            self.wfile.write(b"x")
                            self.wfile.flush()
                            time.sleep(action["drip"])
                        self.wfile.write(b"\r\n")
                    self.wfile.write(body[:cut])
                    if action.get("chunked"):
                        if "trailer_gate" in action:
                            self.wfile.flush()
                            action["trailer_gate"].wait(3)
                        self.wfile.write(b"\r\n0\r\n\r\n")
                    self.wfile.flush()
                    owner.sent.set()
                    if action.get("reset"):
                        # Real abortive TCP close, rather than a clean short response.
                        time.sleep(0.03)
                        self.reset_connection()
                        return
                    if action.get("stall"):
                        owner.release.wait(3)
                    if cut < len(body) or action.get("stall"):
                        self.close_connection = True
                        with contextlib.suppress(OSError):
                            self.connection.shutdown(socket.SHUT_RDWR)
                except (OSError, ConnectionError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(3)


def downloader(*hosts, **kw):
    return md.ModelDownloader(hosts=list(hosts), retry_delays=(), allow_loopback_redirects=True, **kw)


def expire_stalled_probe(monkeypatch, server):
    """Expire only the known stalled HEAD, once the server has accepted it."""
    read = md._SocketReader.readinto

    def controlled_read(reader, buffer):
        if (reader.deadline is not None
                and reader.sock.getpeername()[1] == server.httpd.server_port):
            assert server.head_entered.wait(10), "HEAD never reached the stalled server"
            raise md._Stalled("controlled probe timeout")
        return read(reader, buffer)

    monkeypatch.setattr(md._SocketReader, "readinto", controlled_read)


def test_drop_at_6mb_fresh_instance_resumes(tmp_path):
    data = bytes(range(256)) * (16 * 4096)
    cut = 6 * 1024 * 1024
    with Server(data, [{"cut": cut}]) as server:
        with pytest.raises(mm.HuggingFaceDownloadError):
            downloader(server.url).download(REPO, tmp_path, entry(data))
        assert (tmp_path / "model.bin.part").stat().st_size == cut
        assert not (tmp_path / "model.bin").exists()
        assert downloader(server.url).download(REPO, tmp_path, entry(data))
        assert server.gets[1][1] == f"bytes={cut}-"
    assert (tmp_path / "model.bin").read_bytes() == data


def test_ignored_range_restarts_cleanly(tmp_path):
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:12345])
    with Server(actions=[{"status": 200}]) as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets[0][1] == "bytes=12345-"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_stall_reconnects_without_retry_budget(tmp_path):
    with Server(actions=[{"cut": 65536, "stall": True}]) as server:
        assert downloader(server.url, stall_timeout=0.15).download(REPO, tmp_path, entry())
        assert [r for _, r in server.gets] == [None, "bytes=65536-"]
        assert len(server.heads) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_primary_502_falls_back(tmp_path):
    with Server(actions=[{"status": 502}]) as primary, Server() as mirror:
        assert downloader(primary.url, mirror.url).download(REPO, tmp_path, entry())
        assert len(primary.gets) == len(mirror.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_wrong_hash_never_installed_and_next_host_used(tmp_path):
    with Server(b"x" * len(PAYLOAD)) as bad, Server() as good:
        original = md.os.replace

        def checked_replace(src, dst):
            assert Path(src).read_bytes() == PAYLOAD
            assert good.gets, "bad host installed a final file"
            return original(src, dst)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(md.os, "replace", checked_replace)
            assert downloader(bad.url, good.url).download(REPO, tmp_path, entry())
        assert good.gets[0][1] is None
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_redirect_to_third_port_is_verified(tmp_path):
    with Server(b"x" * len(PAYLOAD)) as bad, Server() as good:
        with Server(actions=[{"status": 302, "redirect": bad.url + "/blob"}]) as primary:
            assert downloader(primary.url, good.url).download(REPO, tmp_path, entry())
        assert bad.gets and good.gets
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("oversized", [False, True])
def test_416_and_oversized_part_restart(tmp_path, oversized):
    prefix = PAYLOAD + b"extra" if oversized else PAYLOAD[:12345]
    (tmp_path / "model.bin.part").write_bytes(prefix)
    with Server(actions=[] if oversized else [{"status": 416}]) as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets[-1][1] is None
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_disk_check_before_any_connection(tmp_path, monkeypatch):
    def full(*_args):
        raise mm.InsufficientDiskSpace("disk space")

    monkeypatch.setattr(mm, "_require_free_space", full)
    with Server() as server:
        with pytest.raises(mm.InsufficientDiskSpace):
            downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets == server.heads == []


def test_cancel_transfer_keeps_part_and_returns_false(tmp_path):
    cancel = threading.Event()
    with Server(actions=[{"cut": 65536, "stall": True}]) as server:
        result = []
        worker = threading.Thread(target=lambda: result.append(
            downloader(server.url).download(REPO, tmp_path, entry(), cancel_event=cancel)))
        worker.start()
        assert server.sent.wait(3)
        deadline = time.monotonic() + 3
        while not (tmp_path / "model.bin.part").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
        worker.join(1)
        assert not worker.is_alive(), "cancellation blocked behind a stalled read"
        assert result == [False]
    assert (tmp_path / "model.bin.part").is_file()
    assert not (tmp_path / "model.bin").exists()


def test_replace_permission_error_twice_then_success(tmp_path, monkeypatch):
    original = md.os.replace
    calls = []

    def held(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(errno.EACCES, "antivirus")
        return original(src, dst)

    monkeypatch.setattr(md.os, "replace", held)
    with Server() as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
    assert len(calls) == 3
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_non_ascii_and_spaces_in_destination(tmp_path):
    destination = tmp_path / "\u6a21\u578b with spaces" / "tiny"
    with Server() as server:
        assert downloader(server.url).download(REPO, destination, entry())
    assert (destination / "model.bin").read_bytes() == PAYLOAD


def test_no_manifest_uses_legacy_function(tmp_path, monkeypatch):
    from faster_whisper import utils

    legacy = Mock()
    monkeypatch.setattr(utils, "download_model", legacy)
    monkeypatch.setattr(md, "load_manifest", lambda: {})
    assert mm._download_via_huggingface("custom", tmp_path, hf_repo="custom/repo")
    legacy.assert_called_once_with("custom/repo", output_dir=str(tmp_path))


def test_builder_pins_every_registry_repo_and_hashes_small_files():
    from tools.build_model_manifest import build_manifest

    calls = []
    data = b"{}"

    def fetch(url):
        calls.append(url)
        if "/api/models/" in url:
            return json.dumps({"sha": COMMIT, "siblings": [
                {"rfilename": "model.bin", "size": len(PAYLOAD), "lfs": {
                    "size": len(PAYLOAD), "sha256": hashlib.sha256(PAYLOAD).hexdigest()}},
                {"rfilename": "config.json", "size": len(data)},
                {"rfilename": "README.md", "size": 999},
            ]}).encode()
        assert f"/resolve/{COMMIT}/config.json" in url
        return data

    built = build_manifest(fetch)
    assert set(built) == {item["hf_repo"] for item in mm.MODEL_REGISTRY.values()}
    for raw in built.values():
        parsed = md.parse_entry(raw)
        assert parsed.files["config.json"].sha256 == hashlib.sha256(data).hexdigest()
    assert not any("README" in url for url in calls)


def test_fixture_and_empty_safe_manifest_loader(tmp_path, caplog):
    fixture = md.load_manifest(Path("tests/fixtures/model_manifest.json"))
    assert fixture[REPO].files["model.bin"].size == len(b"fixture weights\n")
    assert md.load_manifest(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    assert md.load_manifest(bad) == {}
    assert "manifest" in caplog.text.lower()


def test_hypothesis_any_cut_resumes_identical_bytes(tmp_path):
    hypothesis = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st

    @hypothesis.settings(max_examples=12, deadline=None, database=None)
    @hypothesis.given(st.binary(min_size=2, max_size=200000), st.data())
    def run(data, choices):
        cut = choices.draw(st.integers(min_value=1, max_value=len(data) - 1))
        final = tmp_path / "model.bin"
        final.unlink(missing_ok=True)
        with Server(data, [{"cut": cut}]) as server:
            with pytest.raises(mm.HuggingFaceDownloadError):
                downloader(server.url).download(REPO, tmp_path, entry(data))
            assert downloader(server.url).download(REPO, tmp_path, entry(data))
            assert server.gets[1][1] == f"bytes={cut}-"
        assert final.read_bytes() == data

    run()


@pytest.mark.parametrize("headers", [
    {"length": len(PAYLOAD) + 1},
    {"length": len(PAYLOAD) - 1},
    {"range": f"bytes 1-{len(PAYLOAD)-1}/{len(PAYLOAD)}"},
    {"range": f"bytes 12345-{len(PAYLOAD)-2}/{len(PAYLOAD)}"},
    {"range": f"bytes 12345-{len(PAYLOAD)-1}/{len(PAYLOAD)+1}"},
])
def test_attack_lying_length_and_range_never_installed(tmp_path, headers):
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:12345])
    with Server(actions=[headers]) as bad, Server() as good:
        assert downloader(bad.url, good.url).download(REPO, tmp_path, entry())
        assert good.gets, "accepted the lying response"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_attack_wrong_bytes_never_renamed(tmp_path, monkeypatch):
    rename = Mock(wraps=md.os.replace)
    monkeypatch.setattr(md.os, "replace", rename)
    with Server(b"x" * len(PAYLOAD)) as server:
        with pytest.raises(mm.HuggingFaceDownloadError, match="checksum"):
            downloader(server.url).download(REPO, tmp_path, entry())
    rename.assert_not_called()
    assert not (tmp_path / "model.bin").exists()
    assert not (tmp_path / "model.bin.part").exists()


def test_attack_part_from_another_version(tmp_path):
    (tmp_path / "model.bin.part").write_bytes(b"old version" * 1000)
    with Server() as first, Server() as second:
        assert downloader(first.url, second.url).download(REPO, tmp_path, entry())
        assert [value for _, value in first.gets] == ["bytes=11000-", None]
        assert second.gets == []
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_attack_missing_hash_uses_primary_legacy_only(tmp_path, monkeypatch):
    from faster_whisper import utils

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({REPO: {"commit": COMMIT, "files": {
        "model.bin": {"size": 1}}, "hosts": ["https://untrusted.example"]}}))
    monkeypatch.setattr(md, "MANIFEST_PATH", manifest)
    legacy = Mock()
    monkeypatch.setattr(utils, "download_model", legacy)
    assert mm._download_via_huggingface("custom", tmp_path / "model", hf_repo=REPO)
    legacy.assert_called_once_with(REPO, output_dir=str(tmp_path / "model"))


def test_attack_disk_full_keeps_part_and_plain_message(tmp_path, monkeypatch):
    def full(_fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(md.os, "fsync", full)
    with Server() as server:
        with pytest.raises(mm.HuggingFaceDownloadError, match="disk space"):
            downloader(server.url).download(REPO, tmp_path, entry())
    assert (tmp_path / "model.bin.part").read_bytes() == PAYLOAD
    assert not (tmp_path / "model.bin").exists()


@pytest.mark.parametrize("rename_succeeds", [False, True])
def test_attack_cancel_during_final_rename(tmp_path, monkeypatch, rename_succeeds):
    cancel = threading.Event()
    original = md.os.replace

    def cancel_rename(src, dst):
        cancel.set()
        if rename_succeeds:
            return original(src, dst)
        raise PermissionError(errno.EACCES, "scanner")

    monkeypatch.setattr(md.os, "replace", cancel_rename)
    with Server() as server:
        assert downloader(server.url).download(REPO, tmp_path, entry(), cancel_event=cancel) is False
    saved = tmp_path / ("model.bin" if rename_succeeds else "model.bin.part")
    assert saved.read_bytes() == PAYLOAD


def test_attack_two_downloads_one_model_are_exclusive(tmp_path):
    with Server(actions=[{"cut": 65536, "stall": True}]) as server:
        cancel = threading.Event()
        result = []
        worker = threading.Thread(target=lambda: result.append(
            downloader(server.url).download(REPO, tmp_path, entry(), cancel_event=cancel)))
        worker.start()
        try:
            assert server.sent.wait(3)
            with pytest.raises(mm.HuggingFaceDownloadError, match="already being downloaded"):
                downloader(server.url).download(REPO, tmp_path, entry())
            assert len(server.gets) == 1
        finally:
            cancel.set()
            worker.join(2)
        assert not worker.is_alive()
        assert result == [False]
        server.release.set()
        assert downloader(server.url).download(REPO, tmp_path, entry())
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_attack_finished_model_and_user_files_never_deleted(tmp_path):
    final = tmp_path / "model.bin"
    final.write_bytes(b"user's older finished model")
    keep = tmp_path / "keep.txt"
    keep.write_bytes(b"user data")
    with Server() as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets == server.heads == []
    assert final.read_bytes() == b"user's older finished model"
    assert keep.read_bytes() == b"user data"


def test_attack_cancel_backoff_immediately(tmp_path):
    cancel = threading.Event()
    with Server(actions=[{"status": 502}]) as server:
        result = []
        worker = threading.Thread(target=lambda: result.append(md.ModelDownloader(
            hosts=[server.url], retry_delays=(32,)).download(
                REPO, tmp_path, entry(), cancel_event=cancel)))
        worker.start()
        deadline = time.monotonic() + 3
        while not server.gets and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
        worker.join(1)
        assert not worker.is_alive()
        assert result == [False]


def test_preferred_host_probe_once_per_download(tmp_path):
    with Server(actions=[{"status": 403}]) as primary, Server() as good:
        pinned = entry(**{"config.json": PAYLOAD})
        assert downloader(primary.url, good.url).download(REPO, tmp_path, pinned)
        assert len(primary.gets) == 1
        assert len(good.gets) == 2
        assert len(primary.heads) == len(good.heads) == 1


def test_complete_files_preserve_old_cache_and_make_no_connection(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(PAYLOAD)
    cache = tmp_path / ".cache" / "huggingface" / "download" / "old.incomplete"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"legacy prefix")
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    assert mm._hf_download_unfinished(tmp_path)
    assert not mm._hf_download_unfinished(tmp_path, REPO)
    with Server() as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets == server.heads == []
    assert cache.read_bytes() == b"legacy prefix"


def test_manifest_manager_checks_missing_tokenizer_and_progress(tmp_path, monkeypatch):
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(PAYLOAD)
    (model / "config.json.part").write_bytes(PAYLOAD[:65536])
    pinned = entry(**{"config.json": PAYLOAD})
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: pinned})
    messages = []
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        assert Path(mm.ensure_model({"model": {"name": "fixture", "hf_repo": REPO},
                                     "model_path": str(model)}, progress_cb=messages.append)) == model
        assert [r for _, r in server.gets] == ["bytes=65536-"]
        assert not mm._hf_download_unfinished(model, REPO)
    assert any(p.get("percent") == 100 for p in messages)
    assert (model / "config.json").read_bytes() == PAYLOAD


def test_part_counts_toward_tree_size_and_unfinished(tmp_path):
    part = tmp_path / "model.bin.part"
    part.write_bytes(b"retained prefix")
    assert mm._tree_size(tmp_path) == len(b"retained prefix")
    assert mm._hf_download_unfinished(tmp_path)


def test_error_unwraps_local_entry_and_names_only_hosts(tmp_path):
    class LocalEntryNotFoundError(Exception):
        pass

    try:
        try:
            raise ConnectionError("plain connection failure")
        except ConnectionError as cause:
            raise LocalEntryNotFoundError("wrapper") from cause
    except LocalEntryNotFoundError as exc:
        message = mm._describe_download_error(exc, tmp_path, "huggingface.co")
    assert "LocalEntryNotFoundError" not in message
    assert "plain connection failure" in message
    with Server(actions=[{"status": 404}]) as first, Server(actions=[{"status": 403}]) as second:
        with pytest.raises(mm.HuggingFaceDownloadError) as caught:
            downloader(first.url, second.url).download(REPO, tmp_path, entry())
    assert "127.0.0.1" in str(caught.value)
    assert "http://" not in str(caught.value) and "/resolve/" not in str(caught.value)


def test_existing_weights_are_not_rejected_by_new_pins(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"x" * len(PAYLOAD))
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        assert Path(mm.ensure_model({"model": {"name": "fixture", "hf_repo": REPO},
                                     "model_path": str(tmp_path)})) == tmp_path
        assert server.heads == server.gets == []
    assert (tmp_path / "model.bin").read_bytes() == b"x" * len(PAYLOAD)


@pytest.mark.parametrize("drip", [0, 0.03])
def test_attack_chunk_framing_does_not_reset_payload_watchdog(tmp_path, drip):
    with Server(actions=[{"chunked": True, "drip": drip}]) as first, Server() as second:
        assert downloader(first.url, second.url, stall_timeout=0.12, max_stalls=1).download(
            REPO, tmp_path, entry())
        assert bool(second.gets) == bool(drip), "chunk framing kept an idle model transfer alive"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_attack_header_stall_reconnects_without_retry_budget(tmp_path):
    with Server(actions=[{"stall_headers": True}]) as server:
        assert downloader(server.url, stall_timeout=0.12).download(REPO, tmp_path, entry())
        assert len(server.gets) == 2 and len(server.heads) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_probe_timeout_falls_back_once(tmp_path, monkeypatch):
    with Server(head_stall=True) as bad, Server() as good:
        expire_stalled_probe(monkeypatch, bad)
        assert downloader(bad.url, good.url).download(REPO, tmp_path, entry())
        assert len(bad.heads) == 1 and not bad.gets
        assert len(good.gets) == 1


@pytest.mark.parametrize("host", ["https://mirror.test:bad", "https://mirror .test", "https://mirror.test:99999"])
def test_attack_bad_manifest_host_uses_legacy(tmp_path, host):
    manifest = tmp_path / "bad-host.json"
    raw = {"commit": COMMIT, "files": {"model.bin": {
        "size": 1, "sha256": "0" * 64}}, "hosts": [host]}
    manifest.write_text(json.dumps({REPO: raw}), encoding="utf-8")
    assert md.load_manifest(manifest) == {}


def test_retry_budget_is_six_tries_with_expected_backoff(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr(md.ModelDownloader, "_wait", staticmethod(lambda delay, event: delays.append(delay)))
    with Server(actions=[{"status": 502}] * 8) as bad, Server() as good:
        assert md.ModelDownloader(hosts=[bad.url, good.url]).download(REPO, tmp_path, entry())
        assert len(bad.gets) == 6
        assert delays == [1, 2, 4, 8, 16, 32]
        assert len(good.gets) == 1


def test_repeated_stalls_fall_back_with_range(tmp_path):
    with Server(actions=[{"cut": 65536, "stall": True}] * 3) as bad, Server() as good:
        assert downloader(bad.url, good.url, stall_timeout=0.12).download(REPO, tmp_path, entry())
        assert len(bad.gets) == 3
        assert good.gets[0][1] == "bytes=196608-"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_automatic_telemetry_contains_no_hostnames_or_urls(tmp_path, monkeypatch):
    from core import failure_clue

    monkeypatch.setattr(failure_clue, "context_clue", lambda *args, **kw: {})
    with Server(actions=[{"status": 403}]) as server:
        try:
            downloader(server.url).download(REPO, tmp_path, entry())
        except mm.HuggingFaceDownloadError as exc:
            row = failure_clue.worker_clue(exc, site="worker.model")
        else:
            pytest.fail("expected a real transfer failure")
    text = json.dumps(row)
    assert row
    assert "127.0.0.1" not in text and "http" not in text and "Tried:" not in text


def test_builtin_without_explicit_repo_still_uses_manifest(tmp_path, monkeypatch):
    from faster_whisper import utils

    legacy = Mock()
    monkeypatch.setattr(utils, "download_model", legacy)
    repo = mm.MODEL_REGISTRY["tiny"]["hf_repo"]
    monkeypatch.setattr(md, "load_manifest", lambda: {repo: entry()})
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        assert mm._download_via_huggingface("faster-whisper-tiny", tmp_path)
    legacy.assert_not_called()
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_installed_ensure_never_hashes_finished_files(tmp_path, monkeypatch):
    pinned = entry(**{"config.json": b"{}"})
    (tmp_path / "model.bin").write_bytes(PAYLOAD)
    (tmp_path / "config.json").write_bytes(b"{}")
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: pinned})
    hashes = Mock(wraps=md.verified.file_sha256)
    monkeypatch.setattr(md.verified, "file_sha256", hashes)
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config)) == tmp_path
        assert Path(mm.ensure_model(config)) == tmp_path
        assert server.heads == server.gets == []
    assert hashes.call_count == 0


@pytest.mark.parametrize("leftover", ["model.bin.part", ".cache/huggingface/download/old.incomplete"])
def test_pinned_installed_folder_with_leftover_is_unfinished(tmp_path, monkeypatch, leftover):
    (tmp_path / "model.bin").write_bytes(PAYLOAD)
    partial = tmp_path / leftover
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"prefix")
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    assert mm._hf_download_unfinished(tmp_path)
    assert mm._hf_download_unfinished(tmp_path, REPO) == (leftover == "model.bin.part")


@pytest.mark.parametrize("offline_mode", [False, True])
@pytest.mark.parametrize("weight_variant", ["same-size", "different-size"])
def test_older_installed_model_survives_missing_file_fetch_failure(
    tmp_path, monkeypatch, offline_mode, weight_variant,
):
    data = b"pinned weights"
    weights = data[::-1] if weight_variant == "same-size" else b"working older model"
    pinned = entry(data, **{"config.json": b"{}", "tokenizer.json": b"tokenizer"})
    (tmp_path / "model.bin").write_bytes(weights)
    (tmp_path / "config.json").write_bytes(b"different old config")
    (tmp_path / "extra.json").write_bytes(b"extra from older revision")
    # This case explicitly resumes an interrupted pinned attempt, not an old install.
    (tmp_path / "tokenizer.json.part").write_bytes(b"partial")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: pinned})
    monkeypatch.setattr(md.offline, "is_offline", lambda: offline_mode)
    statuses = []
    with Server(actions=[{"status": 403}]) as first, Server(actions=[{"status": 404}]) as second:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (first.url, second.url))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config, status_cb=statuses.append)) == tmp_path
        if offline_mode:
            assert first.heads == first.gets == second.heads == second.gets == []
        else:
            assert len(first.gets) == len(second.gets) == 1
    for name, snapshot in before.items():
        final = tmp_path / name
        assert (final.read_bytes(), final.stat().st_mtime_ns) == snapshot
    assert any("installed model" in message or "offline mode" in message for message in statuses)


@pytest.mark.parametrize("failure", [mm.InsufficientDiskSpace("full"), PermissionError("denied")])
def test_installed_model_survives_resume_storage_failure(tmp_path, monkeypatch, failure):
    (tmp_path / "model.bin").write_bytes(b"working old weights")
    (tmp_path / "config.json.part").write_bytes(b"partial")
    pinned = entry(**{"config.json": b"{}"})
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: pinned})

    def fail_space(*_args):
        raise failure

    monkeypatch.setattr(mm, "_require_free_space", fail_space)
    statuses = []
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config, status_cb=statuses.append)) == tmp_path
        assert server.heads == server.gets == []
    assert (tmp_path / "model.bin").read_bytes() == b"working old weights"
    assert "using the installed model" in statuses[-1]


def test_eight_tcp_resets_with_progress_resume_on_single_host(tmp_path):
    cut = 65536
    with Server(actions=[{"cut": cut, "reset": True}] * 8) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,) * 6, chunk_size=cut)
        assert client.download(REPO, tmp_path, entry())
        assert [value for _, value in server.gets] == [None] + [
            f"bytes={cut * attempt}-" for attempt in range(1, 9)]
        assert len(server.heads) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_tcp_resets_without_progress_exhaust_budget_then_fall_back(tmp_path):
    with Server(actions=[{"cut": 0, "reset": True}] * 8) as bad, Server() as good:
        client = md.ModelDownloader(hosts=[bad.url, good.url], retry_delays=(0,) * 6)
        assert client.download(REPO, tmp_path, entry())
        assert len(bad.gets) == 6
        assert [value for _, value in good.gets] == [None]
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("offset", [11000, len(PAYLOAD)])
def test_bad_resumed_partial_restarts_same_host_from_zero(tmp_path, offset):
    (tmp_path / "model.bin.part").write_bytes(b"!" * offset)
    with Server() as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert [value for _, value in server.gets] == (
            [f"bytes={offset}-", None] if offset < len(PAYLOAD) else [None])
        assert len(server.heads) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("seed_partial", [False, True])
def test_bad_fresh_hash_moves_to_next_host_even_if_range_was_ignored(tmp_path, seed_partial):
    if seed_partial:
        (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:11000])
    with Server(data=b"!" * len(PAYLOAD), actions=[{"status": 200}]) as bad, Server() as good:
        assert downloader(bad.url, good.url).download(REPO, tmp_path, entry())
        assert len(bad.gets) == 1
        assert [value for _, value in good.gets] == (["bytes=11000-"] if seed_partial else [None])
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_only_host_with_timed_out_head_still_serves_get(tmp_path):
    with Server(head_stall=True) as server:
        assert downloader(server.url, probe_timeout=0.12).download(REPO, tmp_path, entry())
        assert len(server.heads) == len(server.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_failed_probe_host_is_tried_after_other_host_fails(tmp_path, monkeypatch):
    with Server(head_stall=True) as patient, Server(actions=[{"status": 403}]) as bad:
        expire_stalled_probe(monkeypatch, patient)
        assert downloader(patient.url, bad.url).download(REPO, tmp_path, entry())
        assert len(patient.gets) == len(bad.gets) == 1
        assert len(patient.heads) == len(bad.heads) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("stall_timeout", [0.7, 45])
def test_get_connect_timeout_is_independent_of_probe(tmp_path, monkeypatch, stall_timeout):
    connect = socket.create_connection
    timeouts = []

    def record_connection(address, timeout=None, *args, **kwargs):
        timeouts.append(timeout)
        return connect(address, timeout, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", record_connection)
    with Server() as server:
        assert downloader(server.url, stall_timeout=stall_timeout, probe_timeout=0.3).download(
            REPO, tmp_path, entry())
    assert timeouts == [0.3, min(30, stall_timeout)]


@pytest.mark.parametrize("installed", [False, True])
def test_builtin_short_name_uses_same_pins_for_ensure_and_transfer(tmp_path, monkeypatch, installed):
    repo = mm.MODEL_REGISTRY["tiny"]["hf_repo"]
    pinned = entry(**{"config.json": PAYLOAD})
    monkeypatch.setattr(md, "load_manifest", lambda: {repo: pinned})
    if installed:
        (tmp_path / "model.bin").write_bytes(PAYLOAD)
        (tmp_path / "config.json.part").write_bytes(PAYLOAD[:65536])
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        config = {"model": {"name": "tiny"}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config)) == tmp_path
        assert len(server.gets) == (1 if installed else 2)
        assert all(path.startswith(f"/{repo}/resolve/{COMMIT}/") for path, _ in server.gets)
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD
    assert (tmp_path / "config.json").read_bytes() == PAYLOAD
    (tmp_path / "config.json").unlink()
    (tmp_path / "config.json.part").write_bytes(b"partial")
    assert mm._hf_download_unfinished(tmp_path, "tiny")


def test_fallback_progress_does_not_claim_primary_host_served_model(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    statuses = []
    progress = []
    with Server(actions=[{"status": 403}]) as primary, Server() as fallback:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (primary.url, fallback.url))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config, status_cb=statuses.append, progress_cb=progress.append)) == tmp_path
        assert len(primary.gets) == len(fallback.gets) == 1
    text = json.dumps([statuses, progress]).lower()
    assert "huggingface.co" not in text
    assert "from hugging face" not in text
    assert progress[-1]["percent"] == 100


def test_round2_cancel_during_reset_retry_wait_keeps_resumable_bytes(tmp_path, monkeypatch):
    cancel = threading.Event()
    waiting = threading.Event()
    result = []
    errors = []
    cut = 65536
    with Server(actions=[{"cut": cut, "reset": True}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(32,) * 6)
        wait = client._wait

        def observed_wait(delay, event):
            waiting.set()
            wait(delay, event)

        monkeypatch.setattr(client, "_wait", observed_wait)

        def run():
            try:
                result.append(client.download(REPO, tmp_path, entry(), cancel_event=cancel))
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            assert waiting.wait(3), "never reached retry backoff"
            started = time.monotonic()
            cancel.set()
            worker.join(1)
            assert not worker.is_alive()
            assert time.monotonic() - started < 1
            assert not errors and result == [False]
            assert not (tmp_path / "model.bin").exists()
            assert (tmp_path / "model.bin.part").read_bytes() == PAYLOAD[:cut]
            assert downloader(server.url).download(REPO, tmp_path, entry())
            assert server.gets[-1][1] == f"bytes={cut}-"
        finally:
            cancel.set()
            worker.join(3)
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("cut", [len(PAYLOAD) - 1, len(PAYLOAD)])
def test_round2_reset_at_final_byte(tmp_path, cut):
    with Server(actions=[{"cut": cut, "reset": True}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,) * 6)
        assert client.download(REPO, tmp_path, entry())
        values = [value for _, value in server.gets]
        # A TCP reset may discard bytes the client received but has not read yet
        # (seen under load on Windows), so the exact offset is not guaranteed here.
        # Exact resume offsets are asserted with a clean close elsewhere in this file.
        assert values[0] is None and len(values) <= 2
        assert len(values) == 2 or cut == len(PAYLOAD)
        if len(values) == 2 and values[1] is not None:
            assert 0 < int(values[1].removeprefix("bytes=").removesuffix("-")) <= cut
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_round2_reset_then_ignored_range_restarts_cleanly(tmp_path):
    with Server(actions=[{"cut": 65536, "reset": True}, {"status": 200}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,) * 6)
        assert client.download(REPO, tmp_path, entry())
        assert [value for _, value in server.gets] == [None, "bytes=65536-"]
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_round2_ensure_on_unicode_path(tmp_path, monkeypatch):
    folder = tmp_path / "models with spaces \u6a21\u578b \u0622\u0632\u0645\u0648\u0646"
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(folder)}
        assert Path(mm.ensure_model(config)) == folder
        assert len(server.gets) == 1
    assert (folder / "model.bin").read_bytes() == PAYLOAD


def test_round2_two_threads_ensure_same_model(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
    results = []
    errors = []
    second_started = threading.Event()

    def run(started=None):
        try:
            if started is not None:
                started.set()
            results.append(mm.ensure_model(config))
        except BaseException as exc:
            errors.append(exc)

    with Server(actions=[{"cut": 65536, "stall": True}]) as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        first = threading.Thread(target=run)
        second = threading.Thread(target=run, args=(second_started,))
        first.start()
        try:
            assert server.sent.wait(3)
            second.start()
            assert second_started.wait(3)
            second.join(0.1)
            assert second.is_alive(), "second ensure did not wait for the first"
            assert len(server.gets) == 1
        finally:
            server.release.set()
            first.join(5)
            if second.ident is not None:
                second.join(5)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
        assert results == [str(tmp_path), str(tmp_path)]
        assert [value for _, value in server.gets] == [None, "bytes=65536-"]
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_round2_reset_after_connect_before_headers_retries_same_host(tmp_path):
    with Server(actions=[{"reset_headers": True}] * 8) as bad, Server() as good:
        client = md.ModelDownloader(hosts=[bad.url, good.url], retry_delays=(0,) * 6)
        assert client.download(REPO, tmp_path, entry())
        assert len(bad.gets) == 6
        assert len(good.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_round2_failed_connect_moves_to_next_host_without_retry(tmp_path, monkeypatch):
    connect = socket.create_connection
    addresses = []

    def record_connection(address, *args, **kwargs):
        addresses.append(address)
        return connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", record_connection)
    with Server(head_stall=True) as patient, Server(actions=[{"status": 403}]) as rejected:
        with Server() as closed:
            unavailable = closed.url
            address = ("127.0.0.1", closed.httpd.server_port)
        client = md.ModelDownloader(hosts=[unavailable, rejected.url, patient.url],
                                    retry_delays=(0,) * 6, probe_timeout=0.12, stall_timeout=2)
        assert client.download(REPO, tmp_path, entry())
        # One HEAD probe and one real GET connection attempt; neither is retried.
        assert addresses.count(address) == 2
        assert len(patient.gets) == len(rejected.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_weights_are_installed_last_so_a_cut_download_never_looks_installed(tmp_path, monkeypatch):
    # The weights are the smallest file here, so size alone would install them first.
    bodies = {"model.bin": b"w", "config.json": b"cc", "vocabulary.json": b"vvv"}
    pinned = md.parse_entry({
        "commit": COMMIT,
        "files": {n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in bodies.items()},
    })
    installed = []

    def transfer(_self, _url, part, _info, _cancel):
        name = part.name[:-len(".part")]
        if name == "model.bin":
            raise md._HostUnavailable("cut")
        part.write_bytes(bodies[name])
        installed.append(name)
        return None

    monkeypatch.setattr(md.ModelDownloader, "_probe", lambda *_a: True)
    monkeypatch.setattr(md.ModelDownloader, "_transfer", transfer)
    with pytest.raises(mm.HuggingFaceDownloadError):
        md.ModelDownloader(hosts=["https://example.test"]).download(REPO, tmp_path, pinned)
    assert installed == ["config.json", "vocabulary.json"]
    assert not (tmp_path / "model.bin").exists()


@pytest.mark.parametrize("leftover", ["orphan.part", ".cache/huggingface/download/old.incomplete"])
def test_r3_pinned_install_ignores_unrelated_remnants(tmp_path, monkeypatch, leftover):
    remnant = tmp_path / leftover
    remnant.parent.mkdir(parents=True, exist_ok=True)
    remnant.write_bytes(b"keep me")
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        assert Path(mm.ensure_model(config)) == tmp_path
        assert Path(mm.ensure_model(config)) == tmp_path
        assert len(server.heads) == len(server.gets) == 1
    assert not mm._hf_download_unfinished(tmp_path, REPO)
    assert remnant.read_bytes() == b"keep me"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("cancelled", [False, True])
def test_r3_older_install_missing_new_file_needs_no_network(tmp_path, monkeypatch, cancelled):
    weights = tmp_path / "model.bin"
    weights.write_bytes(b"older working weights")
    snapshot = (weights.read_bytes(), weights.stat().st_mtime_ns)
    pinned = entry(**{"tokenizer.json": b"new tokenizer"})
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: pinned})
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    with Server() as server:
        monkeypatch.setattr(md, "DEFAULT_HOSTS", (server.url,))
        config = {"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)}
        assert Path(mm.ensure_model(config, cancel_event=cancel)) == tmp_path
        assert Path(mm.ensure_model(config)) == tmp_path
        assert server.heads == server.gets == []
    assert not mm._hf_download_unfinished(tmp_path, REPO)
    assert (weights.read_bytes(), weights.stat().st_mtime_ns) == snapshot
    assert not (tmp_path / "tokenizer.json").exists()


def test_r3_redirect_body_is_never_read(tmp_path, monkeypatch):
    reads = []
    original = md.http.client.HTTPResponse.read

    def observed(response, amount=None):
        if response.status in (301, 302, 303, 307, 308):
            reads.append(amount)
        return original(response, amount)

    monkeypatch.setattr(md.http.client.HTTPResponse, "read", observed)
    with Server() as target:
        with Server(actions=[{"status": 302, "redirect": target.url + "/blob",
                              "redirect_body": b"x" * (8 * 1024 * 1024)}]) as redirect:
            assert downloader(redirect.url).download(REPO, tmp_path, entry())
    assert reads == [], "urllib drained the redirect body before the download limit"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3_private_redirect_refused_by_default(tmp_path):
    with Server() as target:
        with Server(actions=[{"status": 302, "redirect": target.url + "/blob"}]) as redirect:
            with pytest.raises(mm.HuggingFaceDownloadError):
                md.ModelDownloader(hosts=[redirect.url], retry_delays=()).download(REPO, tmp_path, entry())
        assert target.gets == target.heads == []


@pytest.mark.parametrize("address, allowed", [
    ("198.18.0.1", True), ("100.64.0.1", True), ("10.0.0.1", True),
    ("192.168.1.1", True), ("8.8.8.8", True),
    ("127.0.0.1", False), ("::1", False), ("169.254.169.254", False),
    ("0.0.0.0", False), ("224.0.0.1", False), ("ff02::1", False),
    ("192.168.1.2", True),
])
def test_r3b_redirect_address_policy(monkeypatch, address, allowed):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])
    request = md.urllib.request.Request("https://public.test/file")
    redirects = md._ModelRedirects()
    if allowed:
        redirected = redirects.redirect_request(request, None, 302, "Found", {}, "https://target.test/blob")
        assert redirected.full_url == "https://target.test/blob"
    else:
        with pytest.raises(md._HostUnavailable, match="invalid model host"):
            redirects.redirect_request(request, None, 302, "Found", {}, "https://target.test/blob")


def test_r3b_redirect_dns_failure_uses_transfer_retry(tmp_path, monkeypatch):
    resolve = socket.getaddrinfo
    failures = []

    def transient_dns(host, *args, **kwargs):
        if host == "target.test":
            failures.append(host)
            raise socket.gaierror(socket.EAI_AGAIN, "temporary resolver failure")
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", transient_dns)
    with Server(actions=[{"status": 302, "redirect": "https://target.test/blob"}]) as server:
        client = md.ModelDownloader(hosts=[server.url], retry_delays=(0,))
        waits = []
        monkeypatch.setattr(client, "_wait", lambda delay, cancel: waits.append(delay))
        assert client.download(REPO, tmp_path, entry())
        assert waits == [0], "redirect DNS failure bypassed the transfer retry branch"
        assert len(server.gets) == 2 and failures == ["target.test"]
        assert not client.unavailable
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("url", ["ftp://target.test/blob", "https://user:password@target.test/blob",
                                 "https://target.test:invalid/blob", "https://[invalid/blob"])
def test_r3b_invalid_redirect_url_is_host_unavailable(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("invalid URL reached DNS"))
    request = md.urllib.request.Request("https://public.test/file")
    with pytest.raises(md._HostUnavailable, match="invalid model host"):
        md._ModelRedirects().redirect_request(request, None, 302, "Found", {}, url)


def test_r3_oscillating_200_cannot_reset_retry_budget(tmp_path):
    actions = [{"status": 200, "cut": n} for n in [1, 0] * 8]
    with Server(actions=actions) as bad, Server() as good:
        client = md.ModelDownloader(hosts=[bad.url, good.url], retry_delays=(0,) * 6)
        assert client.download(REPO, tmp_path, entry())
        assert good.gets and len(bad.gets) <= 7, "repeated old bytes renewed the retry budget"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3_one_byte_reconnects_hit_minimum_rate(tmp_path, monkeypatch):
    elapsed = [0.0]
    with Server(actions=[{"cut": 1}] * 10) as bad, Server() as good:
        client = md.ModelDownloader(hosts=[bad.url, good.url], retry_delays=(0,) * 6)
        monkeypatch.setattr(client, "_rate_clock", lambda: elapsed[0], raising=False)
        fetch = client._fetch

        def paced(url, *args):
            try:
                return fetch(url, *args)
            finally:
                if url.startswith(bad.url):
                    elapsed[0] += 30

        monkeypatch.setattr(client, "_fetch", paced)
        assert client.download(REPO, tmp_path, entry())
        assert good.gets and len(bad.gets) == 4, "one byte per reconnect never failed over"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("steady", [False, True])
def test_r3_payload_rate_window(tmp_path, monkeypatch, steady):
    data = PAYLOAD * 3 if steady else PAYLOAD[:4096]
    elapsed = [0.0]
    with Server(data) as first, Server(data) as second:
        client = md.ModelDownloader(hosts=[first.url, second.url], retry_delays=(),
                                    chunk_size=256 * 1024 if steady else 1)
        monkeypatch.setattr(client, "_rate_clock", lambda: elapsed[0], raising=False)
        open_response = client._open
        reads = []

        def paced(url, *args, **kwargs):
            response = open_response(url, *args, **kwargs)
            if not kwargs.get("probe") and url.startswith(first.url):
                read = response.read1

                def read1(size):
                    chunk = read(size)
                    # Virtual time changes only after actual payload reads.
                    elapsed[0] += len(chunk) / (12 * 1024) if steady else 29
                    reads.append(len(chunk))
                    return chunk

                response.read1 = read1
            return response

        monkeypatch.setattr(client, "_open", paced)
        assert client.download(REPO, tmp_path, entry(data))
        assert bool(second.gets) == (not steady)
        if not steady:
            assert len(reads) <= 5
    assert (tmp_path / "model.bin").read_bytes() == data


@pytest.mark.parametrize("slow_read", ["last_chunk", "eof"])
@pytest.mark.parametrize("chunked", [False, True])
def test_r3b_completed_small_file_ignores_rate_floor(tmp_path, monkeypatch, slow_read, chunked):
    config = b"c" * 2048
    elapsed = [0.0]
    reads = []
    with Server(actions=[{"data": config, "chunked": chunked}]) as server:
        client = downloader(server.url, chunk_size=4096)
        monkeypatch.setattr(client, "_rate_clock", lambda: elapsed[0])
        open_response = client._open

        def slow_completion(url, *args, **kwargs):
            response = open_response(url, *args, **kwargs)
            if not kwargs.get("probe") and url.endswith("/config.json"):
                read = response.read1
                received = 0

                def read1(size):
                    nonlocal received
                    chunk = read(size)
                    received += len(chunk)
                    reads.append(len(chunk))
                    if ((slow_read == "last_chunk" and received == len(config))
                            or (slow_read == "eof" and not chunk)):
                        elapsed[0] = 121.0
                    return chunk

                response.read1 = read1
            return response

        monkeypatch.setattr(client, "_open", slow_completion)
        assert client.download(REPO, tmp_path, entry(**{"config.json": config}))
        assert len(server.gets) == 2 and not client.unavailable
    assert reads[-1] == 0 and sum(reads) == len(config)
    assert elapsed[0] == 121.0
    assert (tmp_path / "config.json").read_bytes() == config
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3b_completed_chunked_file_ignores_trailer_rate_check(tmp_path, monkeypatch):
    data = b"c" * 2048
    trailers = threading.Event()
    elapsed = [0.0]
    with Server(data, [{"chunked": True, "trailer_gate": trailers}]) as server:
        client = downloader(server.url)
        monkeypatch.setattr(client, "_rate_clock", lambda: elapsed[0])
        open_response = client._open

        def delayed_trailers(*args, **kwargs):
            response = open_response(*args, **kwargs)
            if not kwargs.get("probe"):
                read = response.read1
                received = 0

                def read1(size):
                    nonlocal received
                    chunk = read(size)
                    received += len(chunk)
                    if received == len(data):
                        elapsed[0] = 121.0
                        trailers.set()
                    return chunk

                response.read1 = read1
            return response

        monkeypatch.setattr(client, "_open", delayed_trailers)
        try:
            assert client.download(REPO, tmp_path, entry(data))
        finally:
            trailers.set()
        assert len(server.gets) == 1 and not client.unavailable
    assert (tmp_path / "model.bin").read_bytes() == data


@contextlib.contextmanager
def hold_download_file(path, monkeypatch, release_after=None):
    """A real Windows handle permits reads but denies writes and deletion."""
    held = threading.Event()
    release = threading.Event()
    errors = []

    def hold():
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                               wintypes.HANDLE]
                kernel.CreateFileW.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    held.set()
                    release.wait(release_after)
                finally:
                    kernel.CloseHandle(handle)
            else:
                # POSIX does not deny rename for open files; reproduce that OS contract.
                replace = md.os.replace

                def blocked(source, target):
                    if Path(source) == path and not release.is_set():
                        raise PermissionError(errno.EACCES, "in use")
                    return replace(source, target)

                monkeypatch.setattr(md.os, "replace", blocked)
                held.set()
                release.wait(release_after)
        except BaseException as exc:
            errors.append(exc)
            held.set()
        finally:
            release.set()

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert held.wait(5), "file holder never started"
        assert not errors
        yield release
    finally:
        release.set()
        thread.join(5)
        assert not thread.is_alive() and not errors


@pytest.mark.parametrize("operation", ["rename", "reopen", "unlink"])
def test_r3_windows_file_lock_released_after_delay(tmp_path, monkeypatch, operation):
    part = tmp_path / "model.bin.part"
    data = {"rename": PAYLOAD, "reopen": PAYLOAD[:12345], "unlink": PAYLOAD + b"extra"}[operation]
    part.write_bytes(data)
    with Server() as server:
        with hold_download_file(part, monkeypatch, release_after=0.9):
            assert downloader(server.url).download(REPO, tmp_path, entry())
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3_windows_lock_past_limit_then_cancel(tmp_path, monkeypatch):
    part = tmp_path / "model.bin.part"
    part.write_bytes(PAYLOAD)
    monkeypatch.setattr(md, "_FILE_RETRY_TIMEOUT", 0.3, raising=False)
    cancel = threading.Event()
    with Server() as server:
        with hold_download_file(part, monkeypatch):
            started = time.monotonic()
            with pytest.raises(mm.HuggingFaceDownloadError, match="in use"):
                downloader(server.url).download(REPO, tmp_path, entry())
            assert time.monotonic() - started < 2
            cancel.set()
            assert downloader(server.url).download(REPO, tmp_path, entry(), cancel_event=cancel) is False
            cancel.clear()
            waiting = threading.Event()
            client = downloader(server.url)
            wait = client._wait

            def observed_wait(delay, event):
                waiting.set()
                wait(delay, event)

            monkeypatch.setattr(client, "_wait", observed_wait)
            results = []
            errors = []

            def run():
                try:
                    results.append(client.download(REPO, tmp_path, entry(), cancel_event=cancel))
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run)
            worker.start()
            try:
                assert waiting.wait(3)
                cancel.set()
                worker.join(1)
                assert not worker.is_alive() and not errors and results == [False]
            finally:
                cancel.set()
                worker.join(3)
    assert part.read_bytes() == PAYLOAD
    assert not (tmp_path / "model.bin").exists()


def test_r3_rename_winerror5_is_in_use_only_for_rename(tmp_path, monkeypatch):
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD)
    monkeypatch.setattr(md, "_FILE_RETRY_TIMEOUT", 0.2, raising=False)

    def denied(*args):
        error = PermissionError(errno.EACCES, "scanner")
        error.winerror = 5
        raise error

    monkeypatch.setattr(md.os, "replace", denied)
    with Server() as server:
        with pytest.raises(mm.HuggingFaceDownloadError, match="in use"):
            downloader(server.url).download(REPO, tmp_path, entry())


def test_r3_nonrename_access_denied_remains_folder_error(tmp_path, monkeypatch):
    import builtins

    part = tmp_path / "model.bin.part"
    part.write_bytes(PAYLOAD[:12345])
    monkeypatch.setattr(md, "_FILE_RETRY_TIMEOUT", 0.2)
    original = builtins.open

    def denied(file, mode="r", *args, **kwargs):
        if Path(file) == part and mode == "ab":
            error = PermissionError(errno.EACCES, "denied")
            error.winerror = 5
            raise error
        return original(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied)
    with Server() as server:
        with pytest.raises(mm.ModelDestinationNotWritable):
            downloader(server.url).download(REPO, tmp_path, entry())


@pytest.mark.parametrize("rejection", ["checksum", "oversize", "short"])
def test_r3_ignored_range_rejection_preserves_good_prefix(tmp_path, monkeypatch, rejection):
    prefix = PAYLOAD[:12345]
    part = tmp_path / "model.bin.part"
    part.write_bytes(prefix)
    action = {"status": 200, "data": b"!" * len(PAYLOAD)}
    if rejection == "oversize":
        action.update(data=b"!" * (len(PAYLOAD) + 1), chunked=True)
    if rejection == "short":
        action.update(cut=65536)
    with Server(actions=[action]) as bad, Server() as good:
        client = downloader(bad.url, good.url)
        fetch = client._fetch

        def preserved(url, *args):
            if url.startswith(good.url):
                assert part.read_bytes() == prefix, "a rejected 200 destroyed the saved prefix"
            return fetch(url, *args)

        monkeypatch.setattr(client, "_fetch", preserved)
        assert client.download(REPO, tmp_path, entry())
        assert good.gets[0][1] == f"bytes={len(prefix)}-"
        assert len(bad.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("seed", [False, True])
def test_r3_rejected_host_does_not_leave_appended_bad_bytes(tmp_path, monkeypatch, seed):
    prefix = PAYLOAD[:12345] if seed else b""
    part = tmp_path / "model.bin.part"
    if seed:
        part.write_bytes(prefix)
    with Server(data=b"!" * (len(PAYLOAD) + 1), actions=[{"chunked": True,
                "range": f"bytes {len(prefix)}-{len(PAYLOAD)-1}/{len(PAYLOAD)}"}]) as bad, Server() as good:
        client = downloader(bad.url, good.url, chunk_size=65536)
        fetch = client._fetch

        def preserved(url, *args):
            if url.startswith(good.url):
                assert (part.read_bytes() if part.exists() else b"") == prefix
            return fetch(url, *args)

        monkeypatch.setattr(client, "_fetch", preserved)
        assert client.download(REPO, tmp_path, entry())
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def process_fixture(root):
    pinned = entry(**{"config.json": PAYLOAD})
    (root / "manifest.json").write_text(json.dumps({REPO: {
        "commit": pinned.commit,
        "files": {n: {"size": i.size, "sha256": i.sha256} for n, i in pinned.files.items()},
    }}), encoding="utf-8")
    return str(root)


def process_command(mode, root, url):
    return [sys.executable, "-B", "tests/core/model_download_process.py", mode, root, url]


def wait_for_process_gate(root, process):
    deadline = time.monotonic() + 10
    while not (root / "ready").exists() and process.poll() is None:
        assert time.monotonic() < deadline, "download process did not reach its gate"
        time.sleep(0.01)
    assert (root / "ready").exists(), process.communicate(timeout=2)


def test_r3_second_process_does_not_accept_unfinished_download(tmp_path, request):
    root = process_fixture(tmp_path)
    with Server() as server:
        command = process_command("download-gated", root, server.url)
        if request.config.getoption("--r3-weights-first", default=False):
            command.append("--weights-first")
        first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            wait_for_process_gate(tmp_path, first)
            second = subprocess.run(process_command("check", root, server.url), capture_output=True,
                                    text=True, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert second.returncode == 0, second.stderr
            report = json.loads(second.stdout)
            assert not report["installed"], "second process accepted the unfinished download"
            assert "already being downloaded" in report["error"]
            assert first.poll() is None
            assert not (tmp_path / "model" / "model.bin").exists()
            (tmp_path / "release").touch()
            stdout, stderr = first.communicate(timeout=10)
            assert first.returncode == 0, stderr
            assert json.loads(stdout)["installed"]
        finally:
            if first.poll() is None:
                first.kill()
                first.communicate(timeout=5)
    assert (tmp_path / "model" / "model.bin").read_bytes() == PAYLOAD
    assert (tmp_path / "model" / "config.json").read_bytes() == PAYLOAD


def test_r3_attack_redirect_loop_falls_back(tmp_path):
    with Server() as loop, Server() as good:
        loop.actions[:] = [{"status": 302, "redirect": loop.url + "/loop"}] * 20
        assert downloader(loop.url, good.url).download(REPO, tmp_path, entry())
        assert len(loop.gets) <= 10 and len(good.gets) == 1
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3_attack_alternating_200_206_falls_back(tmp_path, monkeypatch):
    prefix = PAYLOAD[:12345]
    (tmp_path / "model.bin.part").write_bytes(prefix)
    actions = [{"status": status, "cut": 1} for status in [200, 206] * 10]
    elapsed = [0.0]
    with Server(actions=actions) as bad, Server() as good:
        client = md.ModelDownloader(hosts=[bad.url, good.url], retry_delays=(0,) * 6)
        monkeypatch.setattr(client, "_rate_clock", lambda: elapsed[0])
        fetch = client._fetch

        def paced(url, *args):
            try:
                return fetch(url, *args)
            finally:
                if url.startswith(bad.url):
                    elapsed[0] += 30

        monkeypatch.setattr(client, "_fetch", paced)
        assert client.download(REPO, tmp_path, entry())
        assert len(bad.gets) == 4
        assert good.gets[0][1] == f"bytes={len(prefix)+2}-"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


@pytest.mark.parametrize("ignore_range", [False, True])
def test_r3_attack_crash_side_file_is_never_trusted(tmp_path, ignore_range):
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:12345])
    side = tmp_path / ".model.bin.part.restart"
    side.write_bytes(b"crashed, unverified bytes")
    unrelated = {name: b"keep this file" for name in (
        ".other.bin.part.restart", "model.bin.part.restart", ".model.bin.part.restart.keep")}
    for name, data in unrelated.items():
        (tmp_path / name).write_bytes(data)
    with Server(actions=[{"status": 200}] if ignore_range else []) as server:
        assert downloader(server.url).download(REPO, tmp_path, entry())
        assert server.gets[0][1] == "bytes=12345-"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD
    assert not side.exists()
    for name, data in unrelated.items():
        assert (tmp_path / name).read_bytes() == data


def test_r3b_cancel_restart_removes_side_file(tmp_path, monkeypatch):
    prefix = PAYLOAD[:12345]
    part = tmp_path / "model.bin.part"
    part.write_bytes(prefix)
    side = tmp_path / ".model.bin.part.restart"
    unrelated = tmp_path / ".unrelated.part.restart"
    unrelated.write_bytes(b"keep me")
    cancel = threading.Event()
    with Server(actions=[{"status": 200}]) as server:
        client = downloader(server.url, chunk_size=4096)
        open_response = client._open

        def cancel_mid_transfer(*args, **kwargs):
            response = open_response(*args, **kwargs)
            if not kwargs.get("probe"):
                read = response.read1

                def read1(size):
                    chunk = read(size)
                    assert chunk and side.exists(), "restart transfer did not begin"
                    cancel.set()
                    return chunk

                response.read1 = read1
            return response

        monkeypatch.setattr(client, "_open", cancel_mid_transfer)
        assert not client.download(REPO, tmp_path, entry(), cancel_event=cancel)
        assert server.gets[0][1] == "bytes=12345-"
    assert not side.exists(), "cancel retained the restart side file"
    assert part.read_bytes() == prefix
    assert not (tmp_path / "model.bin").exists()
    assert unrelated.read_bytes() == b"keep me"


def test_r3b_stale_side_files_removed_before_entry_download(tmp_path, monkeypatch):
    pinned = entry(**{"config.json": b"existing config"})
    (tmp_path / "config.json").write_bytes(b"existing config")
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:12345])
    sides = [tmp_path / ("." + name + ".part.restart") for name in pinned.files]
    for side in sides:
        side.write_bytes(b"stale restart")
    with Server() as server:
        client = downloader(server.url)
        fetch = client._fetch

        def no_stale_sides(*args):
            assert not any(side.exists() for side in sides), "stale side survived entry setup"
            return fetch(*args)

        monkeypatch.setattr(client, "_fetch", no_stale_sides)
        assert client.download(REPO, tmp_path, pinned)
        assert server.gets[0][1] == "bytes=12345-"
    assert not any(side.exists() for side in sides)
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD
    assert (tmp_path / "config.json").read_bytes() == b"existing config"


def test_r3b_side_file_removed_after_install(tmp_path, monkeypatch):
    side = tmp_path / ".model.bin.part.restart"
    with Server() as server:
        client = downloader(server.url)
        replace = client._replace

        def install_with_leftover(part, final, cancel):
            replace(part, final, cancel)
            if final.name == "model.bin":
                side.write_bytes(b"leftover at install")

        monkeypatch.setattr(client, "_replace", install_with_leftover)
        assert client.download(REPO, tmp_path, entry())
    assert not side.exists(), "successful install retained a side file"
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_r3_attack_kill_after_hash_before_rename_resumes(tmp_path):
    root = process_fixture(tmp_path)
    with Server() as server:
        first = subprocess.Popen(process_command("hash-gated", root, server.url),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            wait_for_process_gate(tmp_path, first)
            assert not (tmp_path / "model" / "model.bin").exists()
            assert (tmp_path / "model" / "model.bin.part").read_bytes() == PAYLOAD
            first.kill()
            first.communicate(timeout=5)
            second = subprocess.run(process_command("check", root, server.url),
                                    capture_output=True, text=True, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert second.returncode == 0, second.stderr
            assert json.loads(second.stdout)["installed"]
            assert len(server.gets) == 2, "verified complete partial was downloaded again"
        finally:
            if first.poll() is None:
                first.kill()
                first.communicate(timeout=5)
    assert (tmp_path / "model" / "model.bin").read_bytes() == PAYLOAD


def test_r3_cancel_during_blocked_connect_waits_for_connect_return(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    cancel = threading.Event()
    connect = socket.create_connection
    results = []
    errors = []

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return connect(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", blocked)
    with Server() as server:
        def run():
            try:
                results.append(downloader(server.url).download(REPO, tmp_path, entry(), cancel_event=cancel))
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            assert entered.wait(3)
            cancel.set()
            worker.join(0.1)
            assert worker.is_alive(), "connect unexpectedly became cancellable; update this limitation test"
        finally:
            release.set()
            worker.join(3)
        assert not worker.is_alive() and not errors
        assert results == [False]
        assert not (tmp_path / "model.bin").exists()


def test_r3_attack_oversized_checkpoint_drops_rejected_bytes(tmp_path, monkeypatch):
    part = tmp_path / "model.bin.part"
    part.write_bytes(PAYLOAD + b"old extra bytes")
    with Server(data=b"!" * (len(PAYLOAD) + 1), actions=[{"chunked": True}]) as bad, Server() as good:
        client = downloader(bad.url, good.url, chunk_size=65536)
        fetch = client._fetch

        def preserved(url, *args):
            if url.startswith(good.url):
                assert not part.exists(), "an oversized old checkpoint retained rejected host bytes"
            return fetch(url, *args)

        monkeypatch.setattr(client, "_fetch", preserved)
        assert client.download(REPO, tmp_path, entry())
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD
