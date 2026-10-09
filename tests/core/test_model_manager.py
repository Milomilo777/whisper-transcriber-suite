"""Tests for core.model_manager — pure helpers, the catalog and ensure_model.

The Hugging Face download is replaced by fakes; no test touches the network.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import responses

from core import model_manager as mm


def test_fmt_bytes_units():
    assert mm._fmt_bytes(0) == "0 B"
    assert mm._fmt_bytes(2048).endswith("KB")
    assert mm._fmt_bytes(5 * 1024 * 1024).endswith("MB")


@responses.activate
def test_ensure_model_cancels_on_event(tmp_path):
    model_name = "fakemodel"
    model_dir_name = f"models--Systran--{model_name}"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    cancel = threading.Event()
    cancel.set()

    config = {
        "model": {"name": model_name},
        "model_path": str(cache_dir / model_dir_name),
    }
    with pytest.raises(mm.DownloadCancelled):
        mm.ensure_model(config, cancel_event=cancel)


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
        "model": {"name": model_name},
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
    """Without an hf_repo, _hf_model_ref returns faster-whisper's short id
    (resolving the correct upstream repo) rather than a Systran-prefixed
    guess that 401s for turbo/distil."""
    ref = mm._hf_model_ref("faster-whisper-large-v3-turbo")
    # Either the short id (faster-whisper installed) or, if its internals
    # are unavailable, still the short id (the except branch returns it).
    assert ref == "large-v3-turbo"


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
        # The zip mirror is retired: no entry names another server.
        assert "url" not in entry and "md5" not in entry


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


def test_hf_model_ref_resolves_deepdml_and_turbo_distinctly():
    """deepdml-large-v3-turbo and large-v3-turbo share faster-whisper's
    ``large-v3-turbo`` short id but live under DIFFERENT HF orgs — hf_repo
    must disambiguate them."""
    deepdml = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    turbo = mm.MODEL_REGISTRY["large-v3-turbo"]

    deepdml_ref = mm._hf_model_ref(deepdml["name"], deepdml["hf_repo"])
    turbo_ref = mm._hf_model_ref(turbo["name"], turbo["hf_repo"])

    assert deepdml_ref == "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert turbo_ref == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


def test_catalog_resolve_entry_includes_hf_repo():
    entry = mm.catalog_resolve_entry(None, "deepdml-large-v3-turbo")
    assert entry is not None
    assert entry["hf_repo"] == "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert set(entry) == {"name", "hf_repo"}


def test_catalog_entry_info_returns_label_and_info():
    info = mm.catalog_entry_info(None, "large-v3")
    assert info is not None
    assert "Large v3" in info["label"]
    assert info["info"]
    assert info["approx_size_gb"] == 3.0

    assert mm.catalog_entry_info(None, "no-such-slug") is None


@responses.activate
def test_ensure_model_downloads_via_huggingface(tmp_path, monkeypatch):
    """A registry entry downloads straight from hf_repo via
    _download_via_huggingface."""
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    config = {
        "model": {"name": entry["name"], "hf_repo": entry["hf_repo"]},
        "model_path": str(model_path),
    }

    calls: list[str] = []

    def _fake_hf_download(name, target_model_path, status_cb=None, progress_cb=None, cancel_event=None, hf_repo=None):
        calls.append(hf_repo or "")
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
    """An already-downloaded model must NOT call the Hugging Face download
    again."""
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"already-here")

    config = {
        "model": {"name": entry["name"], "hf_repo": entry["hf_repo"]},
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


def test_ensure_model_no_mirror_partial_install_is_not_installed(tmp_path, monkeypatch):
    """A killed HuggingFace-only download can leave the model folder holding
    only some files (config.json but no model.bin — completed files land in
    model_path, in-progress blobs sit under its .cache). The old
    ``any(iterdir())`` check reported such a folder as an installed model,
    so every later load failed on the missing model.bin with no in-app way
    to recover. Require the CTranslate2 weights and download otherwise. The
    partial files are kept: huggingface_hub re-checks them and resumes its
    unfinished blobs (deleting them restarted a multi-GB download from zero).
    """
    entry = mm.MODEL_REGISTRY["deepdml-large-v3-turbo"]
    cache_dir = tmp_path / "cache"
    model_path = cache_dir / f"models--Systran--{entry['name']}"
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_bytes(b"{}")  # partial download

    config = {
        "model": {
            "name": entry["name"], "hf_repo": entry["hf_repo"],
        },
        "model_path": str(model_path),
    }

    calls: list[str] = []

    def _fake_hf_download(name, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        calls.append(hf_repo or "")
        target = Path(target_model_path)
        # The partial files are handed to the download to resume from.
        assert (target / "config.json").read_bytes() == b"{}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.bin").write_bytes(b"fresh-weights")
        return True

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    result = mm.ensure_model(config)
    assert Path(result) == model_path
    assert (model_path / "model.bin").read_bytes() == b"fresh-weights"
    assert calls == [entry["hf_repo"]]


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
            "name": entry["name"], "hf_repo": entry["hf_repo"],
        },
        "model_path": str(model_path),
    }

    cancel = threading.Event()

    def _fake_hf_download(name, target_model_path,
                          status_cb=None, progress_cb=None,
                          cancel_event=None, hf_repo=None):
        cancel.set()  # user pressed Cancel while hf_hub was downloading
        return False

    monkeypatch.setattr(mm, "_download_via_huggingface", _fake_hf_download)

    with pytest.raises(mm.DownloadCancelled):
        mm.ensure_model(config, cancel_event=cancel)


# ---------- Catalog name safety ----------------------------------------------


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




@pytest.mark.parametrize("size", [float("inf"), float("-inf"), float("nan"), 1e308])
def test_a_non_finite_catalog_size_means_unknown_not_a_crash(size):
    """JSON from the online catalog may say Infinity (Python's parser accepts it) or a
    number so large that its byte count overflows: the download then starts with no size
    estimate instead of raising OverflowError before the first byte."""
    name = "faster-whisper-odd-model"
    entry = {"name": name, "hf_repo": "Systran/faster-whisper-odd-model", "approx_size_gb": size}
    cfg = {"model_catalog": {"odd": entry}}
    assert mm._approx_model_bytes(cfg, name) == 0
    info = mm.catalog_entry_info(cfg, "odd")
    assert info is not None and info["approx_size_gb"] in (0.0, 1e308)
    sane = {"model_catalog": {"odd": {**entry, "approx_size_gb": 2.0}}}
    assert mm._approx_model_bytes(sane, name) == 2 * 1024 ** 3


@pytest.mark.parametrize("size", [-5, -0.5, 0, -1e300])
def test_a_negative_catalog_size_is_shown_as_unknown(size):
    """A size below zero is meaningless: the info popup said "~-5 GB"."""
    entry = {"name": "faster-whisper-odd-model", "hf_repo": "Systran/faster-whisper-odd-model",
             "approx_size_gb": size}
    info = mm.catalog_entry_info({"model_catalog": {"odd": entry}}, "odd")
    assert info is not None and info["approx_size_gb"] == 0.0
    assert f"{info['approx_size_gb']:g}" == "0"


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


# ---------- C2.51b: the zip mirror is retired ---------------------------------


def test_hand_edited_pin_cannot_bring_back_a_mirror_url():
    """A ``model_catalog`` pin kept in an old config.json (C2.50 keeps edited
    pins) may still hold ``url``/``md5``; they never reach the download."""
    cfg = {
        "model_catalog": {
            "large-v3": {
                "name": "faster-whisper-large-v3",
                "url": "https://mirror.test/models--Systran--faster-whisper-large-v3.zip",
                "md5": "https://mirror.test/models--Systran--faster-whisper-large-v3.zip.md5",
            },
            "mirror-only": {
                "name": "faster-whisper-mirror-only-model",
                "url": "https://mirror.test/x.zip",
                "md5": "",
            },
        }
    }
    merged = mm._merged_catalog(cfg)
    assert "url" not in merged["large-v3"] and "md5" not in merged["large-v3"]
    assert merged["large-v3"]["hf_repo"] == "Systran/faster-whisper-large-v3"
    # An entry whose only source was the mirror has no source left.
    assert "mirror-only" not in merged
    assert mm.catalog_resolve_entry(cfg, "large-v3") == {
        "name": "faster-whisper-large-v3",
        "hf_repo": "Systran/faster-whisper-large-v3",
    }


def test_renamed_pin_does_not_inherit_the_builtin_repo():
    cfg = {"model_catalog": {"large-v3": {"name": "faster-whisper-medium"}}}
    entry = mm.catalog_resolve_entry(cfg, "large-v3")
    assert entry is not None
    assert entry["hf_repo"] == ""
    # The download then resolves the repo from the name, not large-v3's.
    assert mm._hf_model_ref(entry["name"], entry["hf_repo"]) == "medium"


def test_old_config_without_hf_repo_downloads_its_own_model():
    """A config.json saved before ``hf_repo`` existed is deep-merged over the
    default model, so ``model`` holds its own name next to the DEFAULT
    model's ``hf_repo``. The catalog entry with that name decides."""
    model = {"name": "faster-whisper-medium", "hf_repo": "Systran/faster-whisper-large-v3"}
    assert mm._hf_repo_for({}, model) == "Systran/faster-whisper-medium"
    custom = {"name": "my-own-model", "hf_repo": "someone/my-own-model"}
    assert mm._hf_repo_for({}, custom) == "someone/my-own-model"


def test_default_config_names_no_mirror():
    from core import config as cfgmod

    assert set(cfgmod.DEFAULT_CONFIG["model"]) == {"name", "hf_repo"}
