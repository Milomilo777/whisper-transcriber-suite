"""Model downloads: half-finished folders, resumable downloads, clear errors.

Every test runs against local fakes (no real download): a fake
``faster_whisper.utils.download_model``, ``responses`` to prove no other
server is contacted, and monkeypatched disk-usage numbers.
"""
from __future__ import annotations

import errno
import os
import string
import sys
import types
from pathlib import Path

import pytest
import responses

from core import model_manager as mm
from core import offline
from core.hub import model_folder_for, model_weights_present


LARGE_ENTRY = mm.MODEL_REGISTRY["large-v3"]
HF_ONLY_ENTRY = mm.MODEL_REGISTRY["small"]
# What a config.json saved before the zip mirror was retired still holds.
RETIRED_URL = "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip"


def _config(model_path: Path, entry: dict, *, retired_mirror: bool = False) -> dict:
    model = {"name": entry["name"], "hf_repo": entry["hf_repo"]}
    if retired_mirror:
        model.update(url=RETIRED_URL, md5=RETIRED_URL + ".md5")
    return {"model": model, "model_path": str(model_path)}


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
        # huggingface_hub renames each finished blob into place.
        for blob in out.rglob("*.incomplete"):
            blob.unlink()
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
def test_retired_mirror_url_in_an_old_config_is_never_fetched(tmp_path, fake_hf):
    """C2.51b: models come only from the Hugging Face Hub, even when an old
    config.json still names the retired zip mirror."""
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    blob = _partial_hf_folder(model_path)
    result = mm.ensure_model(_config(model_path, LARGE_ENTRY, retired_mirror=True))
    assert Path(result) == model_path
    assert fake_hf["calls"] == [LARGE_ENTRY["hf_repo"]]
    assert fake_hf["seen_blobs"] == [[blob.name]]
    assert len(responses.calls) == 0


def test_installed_model_with_an_unfinished_blob_resumes(tmp_path, fake_hf):
    """model.bin alone is not the whole model: a download cut off while a
    tokenizer / vocabulary file was still an ``.incomplete`` blob resumes."""
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    blob = _partial_hf_folder(model_path)
    (model_path / "model.bin").write_bytes(b"weights")
    assert Path(mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))) == model_path
    assert fake_hf["seen_blobs"] == [[blob.name]]
    assert not mm._hf_download_unfinished(model_path)


def test_failed_resume_keeps_and_uses_the_installed_model(tmp_path, fake_hf):
    """An installed model is never deleted or refused because the resume of
    a leftover blob failed (huggingface.co unreachable)."""
    class ConnectError(Exception):
        pass

    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    _partial_hf_folder(model_path)
    (model_path / "model.bin").write_bytes(b"weights")
    fake_hf["raise"] = ConnectError("down")
    statuses: list[str] = []
    result = mm.ensure_model(_config(model_path, HF_ONLY_ENTRY), status_cb=statuses.append)
    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"weights"
    assert any("using the installed model" in m for m in statuses)


def test_offline_installed_model_with_an_unfinished_blob_is_used(tmp_path, fake_hf, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    _partial_hf_folder(model_path)
    (model_path / "model.bin").write_bytes(b"weights")
    assert Path(mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))) == model_path
    assert fake_hf["calls"] == []


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
def test_hf_failure_with_a_retired_mirror_url_names_only_huggingface(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    fake_hf["raise"] = OSError(errno.ENOSPC, "No space left on device")
    with pytest.raises(RuntimeError) as info:
        mm.ensure_model(_config(model_path, LARGE_ENTRY, retired_mirror=True))
    text = str(info.value)
    assert "disk space" in text.lower()
    assert "smch" not in text and "mirror" not in text.lower()
    assert len(responses.calls) == 0


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


# --- C2.51b M1 / M2: an installed model is used as it is ----------------


@responses.activate
def test_installed_model_is_used_without_any_network_call(tmp_path, fake_hf):
    """The retired mirror's checksum step deleted a healthy model on a
    mismatch before a replacement existed (M2), and an entry with ``url``
    but an empty ``md5`` wiped a fresh model (M1). Neither path exists now."""
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"weights")
    cfg = _config(model_path, LARGE_ENTRY, retired_mirror=True)
    cfg["model"]["md5"] = ""
    statuses: list[str] = []
    result = mm.ensure_model(cfg, status_cb=statuses.append)
    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"weights"
    assert fake_hf["calls"] == []
    assert len(responses.calls) == 0
    assert statuses == ["Model already installed"]


# --- S02-9: offline + partial folder --------------------------------


def test_offline_partial_folder_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_text("{}")
    with pytest.raises(offline.OfflineModeError):
        mm.ensure_model(_config(model_path, LARGE_ENTRY))
    # Offline nothing is deleted.
    assert (model_path / "config.json").exists()


def test_offline_installed_model_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"weights")
    assert Path(mm.ensure_model(_config(model_path, LARGE_ENTRY))) == model_path


def test_partial_folder_downloads_again(tmp_path, fake_hf):
    """A folder without model.bin is not 'installed'; its files are kept."""
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_text("{}")
    assert Path(mm.ensure_model(_config(model_path, LARGE_ENTRY))) == model_path
    assert fake_hf["calls"] == [LARGE_ENTRY["hf_repo"]]
    assert (model_path / "config.json").exists()


def test_installed_hf_model_is_not_downloaded_again(tmp_path, fake_hf):
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    (model_path / ".cache" / "huggingface" / "download").mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"hf-weights")
    assert Path(mm.ensure_model(_config(model_path, LARGE_ENTRY))) == model_path
    assert fake_hf["calls"] == []
    assert (model_path / "model.bin").read_bytes() == b"hf-weights"


# --- S02-12: free disk space before the download ----------------------------


def _fake_free(monkeypatch, free_bytes: int) -> None:
    usage = types.SimpleNamespace(total=free_bytes * 10, used=0, free=free_bytes)
    monkeypatch.setattr(mm.shutil, "disk_usage", lambda _p: usage)


def test_no_download_without_room_for_the_model(tmp_path, fake_hf, monkeypatch):
    model_path = tmp_path / "cache" / "models--Systran--faster-whisper-large-v3"
    _fake_free(monkeypatch, 1024 ** 3)  # 1 GB free, the model is ~3 GB
    with pytest.raises(mm.InsufficientDiskSpace) as info:
        mm.ensure_model(_config(model_path, LARGE_ENTRY))
    text = str(info.value)
    assert "disk space" in text.lower()
    assert str(model_path.parent) in text
    assert fake_hf["calls"] == []


def test_resumed_bytes_count_toward_the_free_space(tmp_path, fake_hf, monkeypatch):
    model_path = tmp_path / "cache" / f"models--Systran--{HF_ONLY_ENTRY['name']}"
    blob = _partial_hf_folder(model_path)
    blob.write_bytes(b"0" * 400_000)
    need = int(HF_ONLY_ENTRY["approx_size_gb"] * 1024 ** 3)
    _fake_free(monkeypatch, need - 300_000 + mm._FREE_SPACE_MARGIN)
    assert Path(mm.ensure_model(_config(model_path, HF_ONLY_ENTRY))) == model_path
    assert fake_hf["calls"] == [HF_ONLY_ENTRY["hf_repo"]]


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
