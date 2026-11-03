"""Pinned model transfers against real loopback HTTP servers; no Tk or Hub access."""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import socket
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
        self.sent = threading.Event()
        self.release = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_HEAD(self):
                owner.heads.append(self.path)
                if head_stall:
                    owner.release.wait(3)
                self.send_response(200)
                self.send_header("Content-Length", str(len(owner.data)))
                self.end_headers()

            def do_GET(self):
                owner.gets.append((self.path, self.headers.get("Range")))
                action = owner.actions.pop(0) if owner.actions else {}
                if action.get("stall_headers"):
                    owner.release.wait(3)
                status = action.get("status", 206 if self.headers.get("Range") else 200)
                body = action.get("data", owner.data)
                start = int(self.headers.get("Range", "bytes=0-")[6:-1]) if status == 206 else 0
                self.send_response(status)
                if "redirect" in action:
                    self.send_header("Location", action["redirect"])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
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
                        self.wfile.write(b"\r\n0\r\n\r\n")
                    self.wfile.flush()
                    owner.sent.set()
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
    return md.ModelDownloader(hosts=list(hosts), retry_delays=(), **kw)


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
        assert first.gets[0][1] == "bytes=11000-"
        assert second.gets[0][1] is None
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
        with pytest.raises(mm.HuggingFaceDownloadError, match="existing model file"):
            downloader(server.url).download(REPO, tmp_path, entry())
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


def test_complete_model_ignores_old_cache_and_makes_no_connection(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(PAYLOAD)
    cache = tmp_path / ".cache" / "huggingface" / "download" / "old.incomplete"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"legacy prefix")
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
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


def test_attack_renamed_unverified_weights_not_usable(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"x" * len(PAYLOAD))
    monkeypatch.setattr(md, "load_manifest", lambda: {REPO: entry()})
    with pytest.raises(RuntimeError, match="pinned checksum"):
        mm.ensure_model({"model": {"name": "fixture", "hf_repo": REPO}, "model_path": str(tmp_path)})


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


def test_probe_timeout_falls_back_once(tmp_path):
    with Server(head_stall=True) as bad, Server() as good:
        assert downloader(bad.url, good.url, probe_timeout=0.12).download(REPO, tmp_path, entry())
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
