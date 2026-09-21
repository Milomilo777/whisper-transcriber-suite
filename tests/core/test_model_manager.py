"""Tests for core.model_manager — pure helpers + ensure_model with mocked HTTP.

Uses ``responses`` to fake the model zip + md5 manifest endpoints. Builds a
trivial in-memory zip whose contents match the manifest, so the full
download → extract → verify happy path runs without touching the network.
"""
from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from pathlib import Path

import pytest
import requests
import responses

from core import model_manager as mm


def test_md5_file_matches_hashlib(tmp_path):
    payload = b"the quick brown fox jumps over the lazy dog"
    file = tmp_path / "sample.bin"
    file.write_bytes(payload)
    assert mm.md5_file(file) == hashlib.md5(payload).hexdigest()


def test_md5_file_respects_cancel(tmp_path):
    file = tmp_path / "big.bin"
    file.write_bytes(b"x" * (4 * 1024 * 1024))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(mm.DownloadCancelled):
        mm.md5_file(file, cancel)


def test_zip_name_from_url():
    assert mm._zip_name_from_url("https://example.com/path/model.zip") == "model.zip"
    assert mm._zip_name_from_url("https://example.com/with%20space.zip") == "with space.zip"
    assert mm._zip_name_from_url("https://example.com/") == "model.zip"


def test_parse_md5_manifest_handles_variants():
    # Real md5sum lines begin with a 32-hex digest.
    h1 = "0" * 32
    h2 = "1" * 32
    h3 = "ABCDEF0123456789abcdef0123456789"  # mixed case -> lowercased
    text = f"{h1} *file1.bin\n{h2}  ./sub/file2.bin\n  \n{h3} sub\\file3.bin\n"
    parsed = mm._parse_md5_manifest(text)
    assert (h1, "file1.bin") in parsed
    assert (h2, "sub/file2.bin") in parsed
    assert (h3.lower(), "sub/file3.bin") in parsed


def test_parse_md5_manifest_rejects_non_hex_lines():
    """An HTML / captive-portal body must not be mis-parsed as a manifest
    (it otherwise drives the bounded re-download loop to its cap)."""
    html = "<html><body>Error 407 proxy auth required</body></html>"
    assert mm._parse_md5_manifest(html) == []
    # Short / non-hex tokens are skipped; only a real 32-hex line survives.
    mixed = "abc123 file1.bin\n" + ("d" * 32) + " good.bin\n"
    parsed = mm._parse_md5_manifest(mixed)
    assert parsed == [("d" * 32, "good.bin")]


def test_fmt_bytes_units():
    assert mm._fmt_bytes(0) == "0 B"
    assert mm._fmt_bytes(2048).endswith("KB")
    assert mm._fmt_bytes(5 * 1024 * 1024).endswith("MB")


def test_fmt_time_handles_none_and_negative():
    assert mm._fmt_time(None) == "--:--"
    assert mm._fmt_time(-5) == "00:00"
    assert mm._fmt_time(3661) == "01:01:01"
    assert mm._fmt_time(125) == "02:05"


def _build_model_zip(extract_dir_name: str, files: dict[str, bytes]) -> bytes:
    """Make a zip whose top-level dir is extract_dir_name, containing files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in files.items():
            z.writestr(f"{extract_dir_name}/{rel}", data)
    return buf.getvalue()


@responses.activate
def test_ensure_model_full_download_and_verify(tmp_path):
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    file_a = b"file-a-bytes"
    file_b = b"file-b-bytes-longer"
    files = {"a.bin": file_a, "sub/b.bin": file_b}

    zip_bytes = _build_model_zip(model_dir_name, files)
    md5_text = "\n".join(
        [
            f"{hashlib.md5(file_a).hexdigest()} {model_dir_name}/a.bin",
            f"{hashlib.md5(file_b).hexdigest()} {model_dir_name}/sub/b.bin",
        ]
    )

    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"

    responses.add(responses.GET, zip_url, body=zip_bytes, status=200,
                  headers={"content-length": str(len(zip_bytes))})
    responses.add(responses.GET, md5_url, body=md5_text, status=200)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(cache_dir / model_dir_name),
    }

    statuses: list[str] = []
    progress_payloads: list[dict] = []
    result = mm.ensure_model(
        config,
        status_cb=statuses.append,
        progress_cb=progress_payloads.append,
    )
    assert Path(result) == cache_dir / model_dir_name
    assert (cache_dir / model_dir_name / "a.bin").read_bytes() == file_a
    assert (cache_dir / model_dir_name / "sub" / "b.bin").read_bytes() == file_b
    assert any(p.get("phase") == "ready" for p in progress_payloads)
    assert any("Model ready" in s for s in statuses)


@responses.activate
def test_ensure_model_already_installed_no_redownload(tmp_path):
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    file_a = b"already-here"

    cache_dir = tmp_path / "cache"
    model_dir = cache_dir / model_dir_name
    model_dir.mkdir(parents=True)
    (model_dir / "a.bin").write_bytes(file_a)

    md5_text = f"{hashlib.md5(file_a).hexdigest()} {model_dir_name}/a.bin"
    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"
    responses.add(responses.GET, md5_url, body=md5_text, status=200)
    # Note: zip_url not registered - if ensure_model tries to download we'd see ConnectionError

    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(model_dir),
    }
    progress_payloads: list[dict] = []
    result = mm.ensure_model(config, progress_cb=progress_payloads.append)
    assert Path(result) == model_dir
    assert any(p.get("phase") == "installed" for p in progress_payloads)


@responses.activate
def test_ensure_model_cancels_on_event(tmp_path):
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    cancel = threading.Event()
    cancel.set()

    config = {
        "model": {"name": model_name, "url": "https://fake.test/m.zip", "md5": "https://fake.test/m.md5"},
        "model_path": str(cache_dir / model_dir_name),
    }
    with pytest.raises(mm.DownloadCancelled):
        mm.ensure_model(config, cancel_event=cancel)


def test_unsafe_md5_path_raises(tmp_path):
    """Path traversal attempts in the manifest are rejected."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    md5_url = "https://fake.test/m.md5"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, md5_url,
                 body=f"{hashlib.md5(b'x').hexdigest()} ../escape.bin\n",
                 status=200)
        with pytest.raises(RuntimeError, match="Unsafe MD5 manifest path"):
            mm._verify_extracted_files(cache_dir, md5_url)


@responses.activate
def test_ensure_model_rejects_zip_slip_member(tmp_path):
    """Audit [15]: a tampered model archive with a traversal member must be
    rejected BEFORE extraction writes anything outside the cache dir."""
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{model_dir_name}/ok.bin", b"fine")
        z.writestr("../escape.bin", b"pwned")  # escapes the cache dir
    malicious = buf.getvalue()

    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"
    responses.add(responses.GET, zip_url, body=malicious, status=200,
                  headers={"content-length": str(len(malicious))})
    # The guard fires during extract, before MD5 verification — md5 body
    # is irrelevant, but register it so a stray fetch doesn't ConnectionError.
    responses.add(responses.GET, md5_url, body="", status=200)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(cache_dir / model_dir_name),
    }
    with pytest.raises(RuntimeError, match="Unsafe path in model archive"):
        mm.ensure_model(config)
    # Nothing escaped the cache dir.
    assert not (tmp_path / "escape.bin").exists()


@responses.activate
def test_ensure_model_bounded_retry_raises(tmp_path):
    """Audit [9]: a permanently-mismatching mirror must NOT re-download
    forever — after MAX_DOWNLOAD_ATTEMPTS it raises a terminal error."""
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    files = {"a.bin": b"actual-bytes"}
    zip_bytes = _build_model_zip(model_dir_name, files)
    # md5 lists a DIFFERENT digest → every verify mismatches.
    md5_text = f"{hashlib.md5(b'WRONG').hexdigest()} {model_dir_name}/a.bin"

    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"
    responses.add(responses.GET, zip_url, body=zip_bytes, status=200,
                  headers={"content-length": str(len(zip_bytes))})
    responses.add(responses.GET, md5_url, body=md5_text, status=200)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(cache_dir / model_dir_name),
    }
    with pytest.raises(RuntimeError, match="after .* attempts"):
        mm.ensure_model(config)


# ---------- R5: non-writable destination ------------------------------------


def test_is_permission_error_classifies_eacces_and_eperm():
    import errno as _errno

    assert mm._is_permission_error(PermissionError("denied")) is True
    assert mm._is_permission_error(OSError(_errno.EACCES, "Access is denied")) is True
    assert mm._is_permission_error(OSError(_errno.EPERM, "not permitted")) is True
    # An unrelated OSError (e.g. disk full) is NOT a permission problem.
    assert mm._is_permission_error(OSError(_errno.ENOSPC, "no space")) is False


def test_ensure_model_permission_error_surfaces_as_not_writable(tmp_path, monkeypatch):
    """R5 regression: a PermissionError while creating the model cache
    dir (the Program Files / non-admin trap) must surface as the typed
    ``ModelDestinationNotWritable`` carrying the offending directory —
    NOT a raw OSError the UI would print verbatim.

    No network is touched: ensure_model fails at the very first mkdir.
    """
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    cache_dir = tmp_path / "ProgramFiles" / "WhisperProject" / "hub"
    config = {
        "model": {
            "name": model_name,
            "url": "https://fake.test/model.zip",
            "md5": "https://fake.test/model.md5",
        },
        "model_path": str(cache_dir / model_dir_name),
    }

    real_mkdir = Path.mkdir

    def _boom_mkdir(self, *args, **kwargs):
        # Only block the model cache dir; let any other mkdir through.
        if str(self) == str(cache_dir):
            raise PermissionError(13, "Access is denied", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _boom_mkdir)

    with pytest.raises(mm.ModelDestinationNotWritable) as excinfo:
        mm.ensure_model(config)
    # The exception carries the offending directory for the UI message.
    assert excinfo.value.directory == str(cache_dir)


# ---------- HuggingFace fallback ---------------------------------------------


def test_repo_id_from_url_maps_registry_entries():
    assert mm._repo_id_from_url(
        "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip"
    ) == "Systran/faster-whisper-large-v3"
    assert mm._repo_id_from_url(
        "https://smch.ir/models/models--Systran--faster-whisper-large-v3-turbo.zip"
    ) == "Systran/faster-whisper-large-v3-turbo"
    assert mm._repo_id_from_url(
        "https://smch.ir/models/models--Systran--faster-distil-whisper-large-v3.5.zip"
    ) == "Systran/faster-distil-whisper-large-v3.5"
    assert mm._repo_id_from_url(
        "https://smch.ir/models/models--Systran--faster-whisper-medium.zip"
    ) == "Systran/faster-whisper-medium"


def test_repo_id_from_url_returns_none_for_unrecognised_names():
    assert mm._repo_id_from_url("https://smch.ir/models/not-a-model-archive.zip") is None
    assert mm._repo_id_from_url("https://smch.ir/models/models--solo.zip") is None


@responses.activate
def test_ensure_model_falls_back_to_huggingface_on_mirror_failure(tmp_path, monkeypatch):
    """When the smch.ir mirror 404s (or otherwise fails) ensure_model must
    fall back to HuggingFace and still return the model path successfully,
    WITHOUT running the smch.ir MD5 verification on the HF-downloaded tree.
    """
    model_name = "faster-whisper-medium"
    model_dir_name = f"models--Systran--{model_name}"
    zip_url = f"https://smch.ir/models/{model_dir_name}.zip"
    md5_url = f"{zip_url}.md5"

    # The mirror has no archive for this model — a real 404, like the bug report.
    responses.add(responses.GET, zip_url, status=404)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_path = cache_dir / model_dir_name
    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(model_path),
    }

    verify_calls: list[Path] = []

    def _fake_hf_download(name, src_zip_url, target_model_path, status_cb=None, progress_cb=None, cancel_event=None, hf_repo=None):
        assert name == "faster-whisper-medium"
        assert src_zip_url == zip_url
        assert Path(target_model_path) == model_path
        model_path.mkdir(parents=True)
        (model_path / "model.bin").write_bytes(b"hf-bytes")
        if status_cb:
            status_cb("Model downloaded from HuggingFace.")
        return True

    def _fake_verify(*args, **kwargs):
        verify_calls.append(args[0])
        return []

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)
    monkeypatch.setattr(mm, "_verify_extracted_files", _fake_verify)

    statuses: list[str] = []
    progress_payloads: list[dict] = []
    result = mm.ensure_model(
        config,
        status_cb=statuses.append,
        progress_cb=progress_payloads.append,
    )

    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"hf-bytes"
    assert any("HuggingFace" in s for s in statuses)
    assert any("Model ready" in s for s in statuses)
    assert any(p.get("phase") == "ready" for p in progress_payloads)
    # The smch.ir MD5 manifest must NOT be checked against the HF tree —
    # its layout doesn't match what _verify_extracted_files expects.
    assert verify_calls == []


def test_short_model_id_maps_registry_names():
    """Registry model names map to faster-whisper's short ids — the key fix
    for the 401: turbo/distil do NOT live under Systran, so a naive
    models--Systran--<repo> guess is wrong; the short id resolves the right
    upstream repo via faster-whisper's own download map."""
    assert mm._short_model_id("faster-whisper-large-v3") == "large-v3"
    assert mm._short_model_id("faster-whisper-large-v3-turbo") == "large-v3-turbo"
    assert mm._short_model_id("faster-distil-whisper-large-v3.5") == "distil-large-v3.5"
    assert mm._short_model_id("faster-whisper-medium") == "medium"
    assert mm._short_model_id("") is None
    assert mm._short_model_id("something-else") is None


def test_hf_model_ref_prefers_short_id_over_systran_guess():
    """When faster-whisper knows the short id, _hf_model_ref returns it
    (resolving the correct upstream repo) rather than the Systran-prefixed
    zip-name guess that 401s for turbo/distil."""
    ref = mm._hf_model_ref(
        "faster-whisper-large-v3-turbo",
        "https://smch.ir/models/models--Systran--faster-whisper-large-v3-turbo.zip",
    )
    # Either the short id (faster-whisper installed) or, if its internals
    # are unavailable, still the short id (the except branch returns it).
    assert ref == "large-v3-turbo"


@responses.activate
def test_ensure_model_raises_when_both_mirror_and_huggingface_fail(tmp_path, monkeypatch):
    model_name = "faster-whisper-medium"
    model_dir_name = f"models--Systran--{model_name}"
    zip_url = f"https://smch.ir/models/{model_dir_name}.zip"
    md5_url = f"{zip_url}.md5"

    responses.add(responses.GET, zip_url, status=404)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(cache_dir / model_dir_name),
    }

    monkeypatch.setattr(mm, "_download_via_huggingface", lambda *a, **k: False)

    with pytest.raises(RuntimeError, match=r"(?i)mirror.*huggingface|huggingface.*mirror"):
        mm.ensure_model(config)


# ---------- Full model catalog (v1.3.9) --------------------------------------


def test_model_registry_has_full_catalog():
    """Every model the maintainer specified must be present, each with a
    non-empty ``hf_repo``, ``label``, ``info``, and a positive
    ``approx_size_gb``."""
    expected_slugs = {
        "tiny.en", "tiny", "base.en", "base", "small.en", "small",
        "medium.en", "medium", "large-v1", "large-v2", "large-v3",
        "distil-small.en", "distil-medium.en", "distil-large-v2",
        "distil-large-v3", "distil-large-v3.5", "large-v3-turbo",
        "deepdml-large-v3-turbo",
    }
    assert set(mm.MODEL_REGISTRY.keys()) == expected_slugs
    for slug, entry in mm.MODEL_REGISTRY.items():
        assert entry.get("hf_repo"), f"{slug} missing hf_repo"
        assert entry.get("label"), f"{slug} missing label"
        assert entry.get("info"), f"{slug} missing info"
        assert entry.get("approx_size_gb", 0) > 0, f"{slug} missing approx_size_gb"
        assert isinstance(entry.get("url"), str)
        assert isinstance(entry.get("md5"), str)
        # Every entry must have a download source: a mirror url or hf_repo.
        assert entry["url"] or entry["hf_repo"]


def test_catalog_models_includes_all_new_slugs():
    slugs = {slug for slug, _label in mm.catalog_models(None)}
    assert "deepdml-large-v3-turbo" in slugs
    assert "tiny" in slugs
    assert "tiny.en" in slugs
    assert "large-v1" in slugs
    assert "large-v2" in slugs
    assert "distil-large-v2" in slugs
    assert "distil-large-v3" in slugs
    assert len(slugs) == len(mm.MODEL_REGISTRY)


def test_only_legacy_four_models_have_mirror_urls():
    """Only the four pre-existing entries keep their smch.ir mirror; every
    new model has url="" / md5="" and relies on hf_repo."""
    mirrored = {slug for slug, e in mm.MODEL_REGISTRY.items() if e["url"]}
    assert mirrored == {"large-v3", "large-v3-turbo", "distil-large-v3.5", "medium"}
    for slug, entry in mm.MODEL_REGISTRY.items():
        if slug not in mirrored:
            assert entry["url"] == ""
            assert entry["md5"] == ""


def test_hf_model_ref_resolves_deepdml_and_turbo_distinctly():
    """deepdml-large-v3-turbo and large-v3-turbo share faster-whisper's
    ``large-v3-turbo`` short id but live under DIFFERENT HF orgs — hf_repo
    must disambiguate them."""
    deepdml = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    turbo = mm.MODEL_REGISTRY["large-v3-turbo"]

    deepdml_ref = mm._hf_model_ref(deepdml["name"], deepdml["url"], deepdml["hf_repo"])
    turbo_ref = mm._hf_model_ref(turbo["name"], turbo["url"], turbo["hf_repo"])

    assert deepdml_ref == "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert turbo_ref == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


def test_catalog_resolve_entry_includes_hf_repo():
    entry = mm.catalog_resolve_entry(None, "deepdml-large-v3-turbo")
    assert entry is not None
    assert entry["hf_repo"] == "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert entry["url"] == ""
    assert entry["md5"] == ""


def test_catalog_entry_info_returns_label_and_info():
    info = mm.catalog_entry_info(None, "large-v3")
    assert info is not None
    assert "Large v3" in info["label"]
    assert info["info"]
    assert info["approx_size_gb"] == 3.0

    assert mm.catalog_entry_info(None, "no-such-slug") is None


@responses.activate
def test_ensure_model_no_mirror_downloads_via_huggingface(tmp_path, monkeypatch):
    """A registry entry with url="" must skip the mirror entirely and
    download straight from hf_repo via _download_via_huggingface."""
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    config = {
        "model": {"name": entry["name"], "url": entry["url"], "md5": entry["md5"], "hf_repo": entry["hf_repo"]},
        "model_path": str(model_path),
    }

    calls: list[str] = []

    def _fake_hf_download(name, src_zip_url, target_model_path, status_cb=None, progress_cb=None, cancel_event=None, hf_repo=None):
        calls.append(hf_repo or "")
        assert src_zip_url == ""
        Path(target_model_path).mkdir(parents=True)
        (Path(target_model_path) / "model.bin").write_bytes(b"deepdml-bytes")
        return True

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    statuses: list[str] = []
    result = mm.ensure_model(config, status_cb=statuses.append)

    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"deepdml-bytes"
    assert calls == ["deepdml/faster-whisper-large-v3-turbo-ct2"]
    assert any("Model ready" in s for s in statuses)


def test_ensure_model_no_mirror_already_installed_skips_download(tmp_path, monkeypatch):
    """An already-downloaded no-mirror model must NOT call the HuggingFace
    fallback again."""
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"already-here")

    config = {
        "model": {"name": entry["name"], "url": entry["url"], "md5": entry["md5"], "hf_repo": entry["hf_repo"]},
        "model_path": str(model_path),
    }

    def _boom(*a, **k):
        raise AssertionError("HuggingFace fallback should not be called")

    monkeypatch.setattr(mm, "_download_via_huggingface", _boom)

    progress_payloads: list[dict] = []
    result = mm.ensure_model(config, progress_cb=progress_payloads.append)
    assert Path(result) == model_path
    assert any(p.get("phase") == "installed" for p in progress_payloads)


# ---------- Offline / interrupted-transfer edge cases ------------------------


@responses.activate
def test_ensure_model_offline_uses_installed_model(tmp_path, monkeypatch):
    """An installed model whose .md5 manifest is unreachable must still be
    usable. Regression: the already-installed check called
    _verify_extracted_files BEFORE ensure_model's try/except, so a
    requests.ConnectionError (offline / mirror down / manifest 404) escaped
    as a hard failure — the first transcribe of every relaunch without a
    network failed even though the ~3 GB model was already on disk, breaking
    the app's "fully offline after the first download" promise.
    """
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    cache_dir = tmp_path / "cache"
    model_dir = cache_dir / model_dir_name
    model_dir.mkdir(parents=True)
    (model_dir / "a.bin").write_bytes(b"installed-bytes")

    md5_url = "https://fake.test/model.md5"
    # The manifest endpoint cannot be reached at all.
    responses.add(
        responses.GET, md5_url,
        body=requests.ConnectionError("simulated offline"),
    )

    config = {
        "model": {
            "name": model_name,
            "url": "https://fake.test/model.zip",
            "md5": md5_url,
        },
        "model_path": str(model_dir),
    }

    def _no_download(*a, **k):
        raise AssertionError("must not re-download an installed model")

    monkeypatch.setattr(mm, "_download_via_huggingface", _no_download)

    statuses: list[str] = []
    progress_payloads: list[dict] = []
    result = mm.ensure_model(
        config,
        status_cb=statuses.append,
        progress_cb=progress_payloads.append,
    )

    assert Path(result) == model_dir
    assert (model_dir / "a.bin").read_bytes() == b"installed-bytes"
    assert any("Could not verify" in s for s in statuses)
    assert any(p.get("phase") == "installed" for p in progress_payloads)


def test_ensure_model_no_mirror_partial_install_is_not_installed(tmp_path, monkeypatch):
    """A killed HuggingFace-only download can leave the model folder holding
    only some files (config.json but no model.bin — completed files land in
    model_path, in-progress blobs sit under its .cache). The old
    ``any(iterdir())`` check reported such a folder as an installed model,
    so every later load failed on the missing model.bin with no in-app way
    to recover. Require the CTranslate2 weights and re-download otherwise.
    """
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_bytes(b"{}")  # partial download

    config = {
        "model": {
            "name": entry["name"], "url": entry["url"],
            "md5": entry["md5"], "hf_repo": entry["hf_repo"],
        },
        "model_path": str(model_path),
    }

    calls: list[str] = []

    def _fake_hf_download(name, src_zip_url, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        calls.append(hf_repo or "")
        target = Path(target_model_path)
        # The stale partial files must have been cleared before re-download.
        assert not (target / "config.json").exists()
        target.mkdir(parents=True)
        (target / "model.bin").write_bytes(b"fresh-weights")
        return True

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    result = mm.ensure_model(config)
    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"fresh-weights"
    assert calls == [entry["hf_repo"]]


@responses.activate
def test_ensure_model_resumes_after_transient_download_error(tmp_path, monkeypatch):
    """A connection drop mid-download must resume the mirror download, not
    discard the partial archive and restart from zero on HuggingFace. The
    partial file on disk is what makes the retry an HTTP Range resume.
    """
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    file_a = b"resumed-bytes"
    zip_bytes = _build_model_zip(model_dir_name, {"a.bin": file_a})
    md5_text = f"{hashlib.md5(file_a).hexdigest()} {model_dir_name}/a.bin"

    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"
    responses.add(responses.GET, md5_url, body=md5_text, status=200)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    zip_path = cache_dir / "model.zip"
    zip_path.write_bytes(b"partial-bytes-from-the-dropped-transfer")

    config = {
        "model": {"name": model_name, "url": zip_url, "md5": md5_url},
        "model_path": str(cache_dir / model_dir_name),
    }

    calls: list[int] = []

    def _fake_download(src_url, target_path, progress_cb=None, cancel_event=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("connection reset by peer")
        Path(target_path).write_bytes(zip_bytes)
        return Path(target_path)

    monkeypatch.setattr(mm, "_download_zip", _fake_download)

    def _no_hf(*a, **k):
        raise AssertionError(
            "a transient mirror error with a partial archive must retry "
            "the mirror instead of jumping to HuggingFace"
        )

    monkeypatch.setattr(mm, "_download_via_huggingface", _no_hf)

    result = mm.ensure_model(config)
    assert len(calls) == 2
    assert Path(result) == cache_dir / model_dir_name
    assert (cache_dir / model_dir_name / "a.bin").read_bytes() == file_a


def test_ensure_model_no_partial_falls_back_immediately(tmp_path, monkeypatch):
    """With NOTHING downloaded there is no resume state, so a mirror
    connection error must still fall through to the HuggingFace fallback
    immediately (no pointless retries of a dead mirror)."""
    model_name = "faster-whisper-medium"
    model_dir_name = f"models--Systran--{model_name}"
    zip_url = f"https://smch.ir/models/{model_dir_name}.zip"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_path = cache_dir / model_dir_name

    config = {
        "model": {
            "name": model_name,
            "url": zip_url,
            "md5": f"{zip_url}.md5",
        },
        "model_path": str(model_path),
    }

    download_calls: list[int] = []

    def _boom_download(src_url, target_path, progress_cb=None, cancel_event=None):
        download_calls.append(1)
        raise requests.ConnectionError("connection refused")

    hf_calls: list[str] = []

    def _fake_hf_download(name, src_zip_url, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        hf_calls.append(hf_repo or "")
        Path(target_model_path).mkdir(parents=True)
        (Path(target_model_path) / "model.bin").write_bytes(b"hf-bytes")
        return True

    monkeypatch.setattr(mm, "_download_zip", _boom_download)
    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    result = mm.ensure_model(config)
    assert len(download_calls) == 1  # no retry without a partial archive
    assert len(hf_calls) == 1
    assert Path(result) == model_path


def test_ensure_model_no_mirror_cancel_during_hf_is_cancelled(tmp_path, monkeypatch):
    """Cancelling during a HuggingFace-only download must surface as
    DownloadCancelled, not as a "download failed" RuntimeError. hf_hub's
    download is not interruptible, so the cancellation is only observed
    after it returns; reporting it as a failure showed a scary error
    dialog for a download that may in fact have completed.
    """
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_path = cache_dir / f"models--Systran--{entry['name']}"

    config = {
        "model": {
            "name": entry["name"], "url": entry["url"],
            "md5": entry["md5"], "hf_repo": entry["hf_repo"],
        },
        "model_path": str(model_path),
    }

    cancel = threading.Event()

    def _fake_hf_download(name, src_zip_url, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        cancel.set()  # user pressed Cancel while hf_hub was downloading
        return False

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    with pytest.raises(mm.DownloadCancelled):
        mm.ensure_model(config, cancel_event=cancel)


@responses.activate
def test_ensure_model_mirror_cancel_during_hf_fallback_is_cancelled(tmp_path, monkeypatch):
    """Same as above on the mirror path: mirror fails (404), the user
    cancels during the HuggingFace fallback — DownloadCancelled, not the
    "both sources failed" RuntimeError."""
    model_name = "faster-whisper-medium"
    model_dir_name = f"models--Systran--{model_name}"
    zip_url = f"https://smch.ir/models/{model_dir_name}.zip"
    responses.add(responses.GET, zip_url, status=404)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    config = {
        "model": {
            "name": model_name,
            "url": zip_url,
            "md5": f"{zip_url}.md5",
        },
        "model_path": str(cache_dir / model_dir_name),
    }

    cancel = threading.Event()

    def _fake_hf_download(name, src_zip_url, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        cancel.set()
        return False

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    with pytest.raises(mm.DownloadCancelled):
        mm.ensure_model(config, cancel_event=cancel)


# ---------- Catalog name safety ----------------------------------------------


def test_ensure_model_successful_retry_after_mismatch_is_kept(tmp_path, monkeypatch):
    """A mirror retry that succeeds after one MD5 mismatch must be accepted.

    Regression: ``last_mismatches`` was never cleared on a successful
    attempt, so the loop's terminal ``if last_mismatches:`` raised for a
    model that was already extracted AND verified on disk. The outer
    handler then deleted the good model and re-downloaded it from
    HuggingFace (or failed outright where huggingface.co is blocked).
    """
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    file_a = b"eventually-good"
    zip_bytes = _build_model_zip(model_dir_name, {"a.bin": file_a})
    zip_url = "https://fake.test/model.zip"
    md5_url = "https://fake.test/model.md5"

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, zip_url, body=zip_bytes, status=200,
                 headers={"content-length": str(len(zip_bytes))})
        # First extraction verifies against a WRONG digest, the retry's
        # against the correct one.
        rsps.add(responses.GET, md5_url,
                 body=f"{hashlib.md5(b'WRONG').hexdigest()} {model_dir_name}/a.bin",
                 status=200)
        rsps.add(responses.GET, md5_url,
                 body=f"{hashlib.md5(file_a).hexdigest()} {model_dir_name}/a.bin",
                 status=200)

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        model_path = cache_dir / model_dir_name
        config = {
            "model": {"name": model_name, "url": zip_url, "md5": md5_url},
            "model_path": str(model_path),
        }

        hf_calls: list[int] = []

        def _fake_hf(*a, **k):
            hf_calls.append(1)
            return True

        monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf)

        progress_payloads: list[dict] = []
        result = mm.ensure_model(config, progress_cb=progress_payloads.append)

    assert Path(result) == model_path
    assert (model_path / "a.bin").read_bytes() == file_a
    assert hf_calls == []  # the verified retry is the final answer
    assert any(p.get("phase") == "ready" for p in progress_payloads)


def test_merged_catalog_ignores_unsafe_model_names():
    """An online/local catalog entry whose ``name`` escapes the hub must be
    ignored entirely (a built-in slug keeps its built-in entry), not merged
    into the effective catalog. ``model.name`` becomes the model directory
    under the hub via ``hub.model_folder_for``; a traversal name there is a
    path-escape (the download flow rmtree's that path before extracting).
    """
    cfg = {
        "model_catalog": {
            "evil-new": {
                "label": "Totally Legit",
                "name": "../../Documents",
                "url": "https://attacker.test/x.zip",
                "md5": "https://attacker.test/x.zip.md5",
            },
            "large-v3": {
                "label": "Hijacked",
                "name": "models--Systran--../../../../Users/Owner/Documents",
                "url": "https://attacker.test/x.zip",
                "md5": "",
                "hf_repo": "attacker/x",
            },
            "safe-new": {
                "label": "Safe",
                "name": "faster-whisper-safe-model",
                "url": "",
                "md5": "",
                "hf_repo": "Systran/faster-whisper-safe-model",
            },
        }
    }

    slugs = dict(mm.catalog_models(cfg))
    assert "evil-new" not in slugs
    # The built-in large-v3 entry survives the hijack attempt untouched.
    resolved = mm.catalog_resolve_entry(cfg, "large-v3")
    assert resolved is not None
    assert resolved["name"] == "faster-whisper-large-v3"
    assert mm.catalog_entry_info(cfg, "large-v3")["label"] != "Hijacked"
    # A safe online entry still merges normally.
    safe = mm.catalog_resolve_entry(cfg, "safe-new")
    assert safe is not None
    assert safe["name"] == "faster-whisper-safe-model"




def test_merged_catalog_coerces_hostile_display_field_types():
    """A compromised/MITM'd online catalog entry with wrong-typed display
    fields must not crash the Advanced dialog's info popup: ``_show_model_info``
    formats the size with ``f"{size_gb:g}"``, so a truthy non-numeric
    ``approx_size_gb`` (e.g. ``"huge"``) raises ``ValueError: Unknown format
    code 'g'``. The merge coerces hostile display values to safe defaults
    while keeping the entry's real fields intact.
    """
    cfg = {
        "model_catalog": {
            "odd": {
                "name": "faster-whisper-odd-model",
                "url": "https://mirror.test/odd.zip",
                "md5": "",
                "hf_repo": "Systran/faster-whisper-odd-model",
                "label": {"not": "a string"},
                "info": ["not", "a string"],
                "approx_size_gb": "huge",
            },
        }
    }
    info = mm.catalog_entry_info(cfg, "odd")
    assert info is not None
    assert info["label"] == "odd"
    assert info["info"] == ""
    assert info["approx_size_gb"] == 0.0
    # The :g: formatting the info popup does must now work.
    body = f"Approx. download size: ~{info['approx_size_gb']:g} GB"
    assert "0 GB" in body
    # Real fields survive the coercion.
    resolved = mm.catalog_resolve_entry(cfg, "odd")
    assert resolved is not None
    assert resolved["name"] == "faster-whisper-odd-model"
    assert resolved["hf_repo"] == "Systran/faster-whisper-odd-model"
