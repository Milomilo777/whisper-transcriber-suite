"""Model downloads: half-finished folders, resumable downloads, clear errors.

Every test runs against local fakes (no real download): a fake
``faster_whisper.utils.download_model``, ``responses`` for the mirror and
monkeypatched disk-usage numbers.
"""
from __future__ import annotations

import errno
import hashlib
import io
import os
import string
import sys
import types
import zipfile
from pathlib import Path

import pytest
import responses

from core import model_manager as mm
from core import offline
from core.hub import model_folder_for, model_weights_present


MIRROR_ENTRY = mm.MODEL_REGISTRY["large-v3"]
HF_ONLY_ENTRY = mm.MODEL_REGISTRY["small"]


def _config(model_path: Path, entry: dict) -> dict:
    return {
        "model": {
            "name": entry["name"], "url": entry["url"],
            "md5": entry["md5"], "hf_repo": entry["hf_repo"],
        },
        "model_path": str(model_path),
    }


def _partial_hf_folder(model_path: Path) -> Path:
    """What a killed HuggingFace download leaves: small files done,
    model.bin still an ``.incomplete`` blob under ``.cache``."""
    dl = model_path / ".cache" / "huggingface" / "download"
    dl.mkdir(parents=True)
    (model_path / "config.json").write_text("{}")
    blob = dl / "model.bin.0123abcd.incomplete"
    blob.write_bytes(b"0" * 4096)
    return blob


@pytest.fixture
def fake_hf(monkeypatch):
    """Replace ``faster_whisper.utils.download_model`` with a recorder.

    ``state["raise"]`` (an exception) makes the next call fail with it;
    otherwise the call writes model.bin into ``output_dir``.
    """
    state: dict = {"calls": [], "raise": None, "seen_blobs": []}

    def download_model(ref, output_dir=None, **_kw):
        out = Path(output_dir)
        state["calls"].append(ref)
        state["seen_blobs"].append(sorted(p.name for p in out.rglob("*.incomplete")))
        if state["raise"] is not None:
            raise state["raise"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_bytes(b"weights")
        return str(out)

    fake = types.ModuleType("faster_whisper.utils")
    fake.download_model = download_model  # type: ignore[attr-defined]
    fake._MODELS = {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", fake)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    return state


# --- S02-1 / S06-5: a folder without model.bin is not an installed model ----


def test_model_weights_present_needs_a_non_empty_model_bin(tmp_path):
    folder = tmp_path / "m"
    assert model_weights_present(folder) is False
    folder.mkdir()
    (folder / "config.json").write_text("{}")
    assert model_weights_present(folder) is False
    (folder / "model.bin").write_bytes(b"")
    assert model_weights_present(folder) is False
    (folder / "model.bin").write_bytes(b"x")
    assert model_weights_present(folder) is True
    assert model_weights_present("") is False
    assert model_weights_present(None) is False


def _bare_app(cfg: dict):
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App
    return App, types.SimpleNamespace(app_config=cfg)


@pytest.mark.parametrize("via", ["model_path", "hub_folder"])
def test_app_gate_offers_download_for_partial_folder(tmp_path, via):
    hub = tmp_path / "hub"
    folder = model_folder_for(hub, "faster-whisper-large-v3")
    _partial_hf_folder(folder)
    cfg = {"model_path": str(folder) if via == "model_path" else "",
           "hub_folder": str(hub), "model": {"name": "faster-whisper-large-v3"}}
    App, a = _bare_app(cfg)
    assert App._model_bytes_present(a) is False
    (folder / "model.bin").write_bytes(b"x")
    assert App._model_bytes_present(a) is True


@pytest.mark.parametrize("via", ["model_path", "hub_folder"])
def test_engine_status_does_not_count_partial_folder(tmp_path, via):
    from core.backends import availability

    hub = tmp_path / "hub"
    folder = model_folder_for(hub, "faster-whisper-small")
    _partial_hf_folder(folder)
    cfg = {"model_path": str(folder) if via == "model_path" else "",
           "hub_folder": str(hub), "model": {"name": "faster-whisper-small"}}
    assert availability._faster_whisper_model_present(cfg) is False
    (folder / "model.bin").write_bytes(b"x")
    assert availability._faster_whisper_model_present(cfg) is True


def test_load_existing_model_names_the_missing_weights(tmp_path, monkeypatch):
    from core import transcriber

    folder = tmp_path / "models--Systran--faster-whisper-small"
    _partial_hf_folder(folder)
    monkeypatch.setitem(transcriber.config, "model_path", str(folder))
    monkeypatch.setitem(transcriber.config, "transcribe_backend", "faster_whisper")

    def _never(*_a, **_k):
        raise AssertionError("must not try to load a model without model.bin")

    monkeypatch.setattr(transcriber, "_load_whisper_model_self_healing", _never)
    messages: list[str] = []
    assert transcriber.load_existing_model(messages.append) is False
    assert "model.bin" in (transcriber.MODEL_ERROR or "")
    assert "download" in (transcriber.MODEL_ERROR or "").lower()


# --- S02-5: a retry resumes the HuggingFace download -----------------------


def test_hf_only_retry_keeps_the_partial_blobs(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    blob = _partial_hf_folder(model_path)
    result = mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    assert Path(result) == model_path
    assert fake_hf["seen_blobs"] == [[blob.name]]
    assert model_weights_present(model_path)


@responses.activate
def test_mirror_fallback_keeps_the_partial_hf_blobs(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    blob = _partial_hf_folder(model_path)
    responses.add(responses.GET, MIRROR_ENTRY["url"], status=404)
    result = mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    assert Path(result) == model_path
    assert fake_hf["seen_blobs"] == [[blob.name]]
    # The manifest of the zip mirror is never checked against a folder the
    # HuggingFace download owns.
    assert all(".md5" not in c.request.url for c in responses.calls)


@responses.activate
def test_half_extracted_mirror_model_is_not_kept_for_the_fallback(tmp_path, monkeypatch):
    """Review of dfcc857: a mirror unpack that died midway left a truncated
    model.bin; with huggingface.co unreachable, huggingface_hub returns the
    local files without error, so the broken model was reported ready."""
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.parent.mkdir(parents=True)
    good = b"w" * 300_000
    zip_path = model_path.parent / mm._zip_name_from_url(MIRROR_ENTRY["url"])
    zip_path.write_bytes(_zip_bytes(model_path.name, {"model.bin": good}))
    responses.add(responses.GET, MIRROR_ENTRY["url"], status=416)

    def _extract_dies_midway(self, path=None, members=None, pwd=None):
        target = Path(path) / model_path.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.bin").write_bytes(good[:1000])  # truncated
        raise zipfile.BadZipFile("Bad CRC-32 for file 'model.bin'")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", _extract_dies_midway)
    seen: list[bool] = []

    def _hf_offline_returns_local(name, zip_url, target, status_cb=None,
                                  progress_cb=None, cancel_event=None, hf_repo=None):
        # What huggingface_hub does when the Hub is unreachable but files
        # exist locally: return them without an error.
        seen.append((Path(target) / "model.bin").exists())
        return True

    monkeypatch.setattr(mm, "_download_via_huggingface", _hf_offline_returns_local)
    with pytest.raises(RuntimeError, match="(?i)did not complete"):
        mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    assert seen == [False], "the half-unpacked mirror files must be removed first"


def test_unfinished_resume_does_not_claim_the_download_finished(tmp_path, fake_hf, monkeypatch):
    """Review of dfcc857: a resume with the Hub unreachable returns without
    error and without model.bin; the message must not say 'finished'."""
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    _partial_hf_folder(model_path)

    def _returns_local(ref, output_dir=None, **_kw):
        return str(output_dir)

    monkeypatch.setattr(sys.modules["faster_whisper.utils"], "download_model", _returns_local)
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    text = str(info.value).lower()
    assert "download finished" not in text
    assert "did not complete" in text
    assert "connection" in text


def test_hf_file_in_use_is_not_a_folder_permission_problem(tmp_path, fake_hf):
    """Review of dfcc857: a sharing violation (antivirus holding an
    .incomplete file) is a PermissionError on Windows but not a folder
    without write access; offering another folder would mislead."""
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    err = PermissionError(errno.EACCES, "The process cannot access the file")
    err.winerror = 32  # type: ignore[attr-defined]
    fake_hf["raise"] = err
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    assert not isinstance(info.value, mm.ModelDestinationNotWritable)
    assert "in use by another program" in str(info.value)


# --- S02-6: the HuggingFace reason reaches the error box -------------------


def test_hf_disk_full_is_named_in_the_error(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    fake_hf["raise"] = OSError(errno.ENOSPC, "No space left on device")
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    text = str(info.value)
    assert "disk space" in text.lower()
    assert str(model_path.parent) in text


def test_hf_windows_disk_full_is_named_in_the_error(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    err = OSError(28, "There is not enough space on the disk")
    err.winerror = 112  # type: ignore[attr-defined]
    err.errno = None  # type: ignore[assignment]
    fake_hf["raise"] = err
    with pytest.raises(RuntimeError, match="(?i)disk space"):
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))


def test_hf_network_block_is_named_in_the_error(tmp_path, fake_hf):
    class ConnectError(Exception):
        """Same name as httpx's connection error."""

    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    fake_hf["raise"] = ConnectError("[Errno 11001] getaddrinfo failed")
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    text = str(info.value)
    assert "could not reach huggingface.co" in text.lower()
    assert "getaddrinfo failed" in text


@responses.activate
def test_both_sources_failing_names_both_reasons(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    responses.add(responses.GET, MIRROR_ENTRY["url"], status=404)
    fake_hf["raise"] = OSError(errno.ENOSPC, "No space left on device")
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    text = str(info.value)
    assert "404" in text
    assert "disk space" in text.lower()


def test_hf_permission_error_offers_another_folder(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    fake_hf["raise"] = PermissionError(errno.EACCES, "Access is denied")
    with pytest.raises(mm.ModelDestinationNotWritable):
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))


# --- S02-7: a hub folder on a drive that is not there ----------------------


def test_missing_folder_raises_the_repick_error(tmp_path, monkeypatch):
    model_path = tmp_path / "gone" / "models--Systran--faster-whisper-small"
    real_mkdir = Path.mkdir

    def _mkdir(self, *a, **k):
        if self == model_path.parent:
            raise FileNotFoundError(3, "The system cannot find the path specified", str(self))
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", _mkdir)
    with pytest.raises(mm.ModelDestinationNotWritable) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    assert info.value.reason == "missing"
    assert info.value.directory == str(model_path.parent)


@pytest.mark.skipif(os.name != "nt", reason="drive letters exist only on Windows")
def test_missing_drive_letter_raises_the_repick_error():
    free = next((d for d in reversed(string.ascii_uppercase)
                 if not os.path.exists(f"{d}:\\")), None)
    if free is None:
        pytest.skip("every drive letter is in use")
    model_path = Path(f"{free}:\\hub\\models--Systran--faster-whisper-small")
    with pytest.raises(mm.ModelDestinationNotWritable) as info:
        mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))
    assert info.value.reason == "missing"


def test_permission_reason_is_the_default():
    assert mm.ModelDestinationNotWritable("X").reason == "permission"


@pytest.mark.parametrize("reason, title, phrase", [
    ("missing", "Model folder not available", "unplugged or disconnected"),
    ("permission", "Model folder not writable", "administrator rights"),
])
def test_download_dialog_names_the_reason(monkeypatch, reason, title, phrase):
    import queue
    import threading

    from app.dialogs import model_download as md

    dlg = md.ModelDownloadDialog.__new__(md.ModelDownloadDialog)
    dlg.events = queue.Queue()  # type: ignore[attr-defined]
    dlg.cancel_event = threading.Event()  # type: ignore[attr-defined]
    dlg.not_writable_dir = None  # type: ignore[attr-defined]
    dlg.not_writable_reason = "permission"  # type: ignore[attr-defined]

    def _raise(*_a, **_k):
        raise mm.ModelDestinationNotWritable("Q:\\hub", reason=reason)

    monkeypatch.setattr(md, "ensure_model", _raise)
    monkeypatch.setattr(md, "load_config", lambda: {})
    dlg._worker()
    assert dlg.not_writable_dir == "Q:\\hub"
    assert dlg.not_writable_reason == reason

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(md.messagebox, "askyesno",
                        lambda t, b, **_k: shown.append((t, b)) or False)
    assert dlg._handle_not_writable("Q:\\hub") is False
    assert shown[0][0] == title
    assert phrase in shown[0][1]


# --- S02-8: an HTML answer for the .md5 list is a network problem ----------


@responses.activate
def test_installed_model_survives_a_captive_portal_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"weights")
    responses.add(responses.GET, MIRROR_ENTRY["md5"], status=200,
                  body="<html><body>Please log in to the wifi</body></html>")
    statuses: list[str] = []
    result = mm.ensure_model(_config(model_path, MIRROR_ENTRY), status_cb=statuses.append)
    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"weights"
    assert any("Could not verify" in s for s in statuses)


def test_manifest_without_checksums_is_a_request_exception(tmp_path, monkeypatch):
    class _Resp:
        text = "<html>login</html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(mm.requests, "get", lambda *a, **k: _Resp())
    with pytest.raises(mm.requests.RequestException):
        mm._verify_extracted_files(tmp_path, "https://fake.test/x.md5")


# --- S02-9: offline + partial mirror folder --------------------------------


def test_offline_partial_mirror_folder_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_text("{}")
    with pytest.raises(offline.OfflineModeError):
        mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    # Offline nothing is deleted.
    assert (model_path / "config.json").exists()


def test_offline_installed_mirror_model_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"weights")
    assert Path(mm.ensure_model(_config(model_path, MIRROR_ENTRY))) == model_path


@responses.activate
def test_unverifiable_partial_folder_downloads_again(tmp_path, monkeypatch):
    """Manifest unreachable (mirror down) + no model.bin: not 'installed'."""
    from requests import ConnectionError as RequestsConnectionError

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_text("{}")
    responses.add(responses.GET, MIRROR_ENTRY["md5"], body=RequestsConnectionError("down"))
    calls: list[str] = []

    def _hf(name, zip_url, target, status_cb=None, progress_cb=None,
            cancel_event=None, hf_repo=None):
        calls.append(name)
        Path(target).mkdir(parents=True, exist_ok=True)
        (Path(target) / "model.bin").write_bytes(b"weights")
        return True

    def _zip_fails(*_a, **_k):
        raise mm.requests.ConnectionError("mirror down")

    monkeypatch.setattr(mm, "_download_zip", _zip_fails)
    monkeypatch.setattr(mm, "_download_via_huggingface", _hf)
    assert Path(mm.ensure_model(_config(model_path, MIRROR_ENTRY))) == model_path
    assert calls == [MIRROR_ENTRY["name"]]


# --- S02-10: a model from the HuggingFace fallback is not checked against
# the zip mirror's manifest on the next launch -----------------------------


@responses.activate
def test_hf_installed_mirror_model_is_not_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    (model_path / ".cache" / "huggingface" / "download").mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"hf-weights")
    # A manifest in the zip layout that does not match the HuggingFace files.
    responses.add(responses.GET, MIRROR_ENTRY["md5"], status=200,
                  body=f"{hashlib.md5(b'zip-weights').hexdigest()} "
                       f"{model_path.name}/model.bin\n")

    def _no_download(*_a, **_k):
        raise AssertionError("an installed model must not be downloaded again")

    monkeypatch.setattr(mm, "_download_zip", _no_download)
    monkeypatch.setattr(mm, "_download_via_huggingface", _no_download)
    assert Path(mm.ensure_model(_config(model_path, MIRROR_ENTRY))) == model_path
    assert (model_path / "model.bin").read_bytes() == b"hf-weights"


# --- S02-12: free disk space before the zip download and the unpacking ----


def _zip_bytes(model_dir_name: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in files.items():
            z.writestr(f"{model_dir_name}/{rel}", data)
    return buf.getvalue()


def _fake_free(monkeypatch, free_bytes: int) -> None:
    usage = types.SimpleNamespace(total=free_bytes * 10, used=0, free=free_bytes)
    monkeypatch.setattr(mm.shutil, "disk_usage", lambda _p: usage)


@responses.activate
def test_no_zip_download_without_room_for_zip_and_unpacking(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    size = 3 * 1024 ** 3
    responses.add(responses.GET, MIRROR_ENTRY["url"], status=200, body=b"",
                  headers={"content-length": str(size)}, auto_calculate_content_length=False)
    _fake_free(monkeypatch, size + 100 * 1024 ** 2)  # room for the zip, not the unpacking

    def _no_hf(*_a, **_k):
        raise AssertionError("no fallback download while the disk is full")

    monkeypatch.setattr(mm, "_download_via_huggingface", _no_hf)
    with pytest.raises(mm.InsufficientDiskSpace) as info:
        mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    text = str(info.value)
    assert "disk space" in text.lower()
    assert str(model_path.parent) in text
    zip_path = model_path.parent / mm._zip_name_from_url(MIRROR_ENTRY["url"])
    assert not zip_path.exists() or zip_path.stat().st_size == 0


@responses.activate
def test_downloaded_zip_is_kept_when_unpacking_does_not_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.parent.mkdir(parents=True)
    payload = b"w" * 50_000
    zip_path = model_path.parent / mm._zip_name_from_url(MIRROR_ENTRY["url"])
    zip_path.write_bytes(_zip_bytes(model_path.name, {"model.bin": payload}))
    # The archive is already complete on disk: the server answers 416.
    responses.add(responses.GET, MIRROR_ENTRY["url"], status=416)
    _fake_free(monkeypatch, 10_000)  # less than the 50 KB to unpack

    monkeypatch.setattr(mm, "_download_via_huggingface",
                        lambda *a, **k: pytest.fail("no fallback while the disk is full"))
    with pytest.raises(mm.InsufficientDiskSpace):
        mm.ensure_model(_config(model_path, MIRROR_ENTRY))
    assert zip_path.exists(), "the finished download must be kept for the next try"
    assert not model_weights_present(model_path)


def test_free_space_check_skips_when_the_disk_cannot_be_read(tmp_path, monkeypatch):
    def _boom(_p):
        raise OSError("no such volume")

    monkeypatch.setattr(mm.shutil, "disk_usage", _boom)
    mm._require_free_space(tmp_path, 10 ** 15, "the model")  # no raise


# --- S11-9: the AI Layer model download refuses a short read ---------------


def test_llm_download_refuses_a_truncated_file(tmp_path, monkeypatch):
    from core import llm

    class _Short:
        headers = {"content-length": "10000"}

        def __init__(self):
            self._left = 4000

        def read(self, n):
            if self._left <= 0:
                return b""
            chunk = b"x" * min(n, self._left)
            self._left -= len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: _Short())
    dest = tmp_path / "m.gguf"
    with pytest.raises(RuntimeError, match="(?i)truncated"):
        llm.download_default_model(dest=dest, chunk_size=1024)
    assert not dest.exists()
    assert not (tmp_path / "m.gguf.part").exists()
