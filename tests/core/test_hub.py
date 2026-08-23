"""Tests for the model-hub folder resolution layer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core import hub


# ---------- resolve_app_dir ---------------------------------------------------


def test_resolve_app_dir_source_returns_repo_root(monkeypatch):
    """In dev / source mode (sys.frozen unset), app_dir is the repo root."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    p = hub.resolve_app_dir()
    # core/hub.py → core → repo root
    expected = Path(hub.__file__).resolve().parent.parent
    assert p == expected


def test_resolve_app_dir_frozen_returns_exe_dir(monkeypatch, tmp_path):
    """When sys.frozen is True, app_dir is dirname(sys.executable)."""
    fake_exe = tmp_path / "fakeapp.exe"
    fake_exe.write_text("not really")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert hub.resolve_app_dir() == tmp_path


# ---------- tiling_tab_enabled ------------------------------------------------


def test_tiling_tab_enabled_when_no_marker(monkeypatch, tmp_path):
    """No no_tiling.flag in the app dir → Video Tiling is enabled (the
    default; this is the dev / opted-in case)."""
    monkeypatch.setattr(hub, "resolve_app_dir", lambda: tmp_path)
    assert (tmp_path / hub.NO_TILING_MARKER).exists() is False
    assert hub.tiling_tab_enabled() is True


def test_tiling_tab_disabled_when_marker_present(monkeypatch, tmp_path):
    """A no_tiling.flag marker in the app dir (installer opt-out) →
    Video Tiling is disabled / the tab is hidden."""
    (tmp_path / hub.NO_TILING_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setattr(hub, "resolve_app_dir", lambda: tmp_path)
    assert hub.tiling_tab_enabled() is False


def test_tiling_tab_enabled_defaults_on_filesystem_error(monkeypatch):
    """A filesystem error while probing the marker must never block
    startup — it defaults to enabled (the feature stays on)."""
    def _boom() -> Path:
        raise OSError("simulated FS failure")

    monkeypatch.setattr(hub, "resolve_app_dir", _boom)
    assert hub.tiling_tab_enabled() is True


# ---------- default_hub_folder -------------------------------------------------


def test_default_hub_folder_is_under_user_cache_not_app_dir(monkeypatch, tmp_path):
    """The default hub must live under user_cache_dir() —
    %LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\models on Windows — NEVER under
    the install / app dir. A Program Files default was not writable for
    a standard (non-admin) user, so the first-run model download failed
    with "Access is denied". Regression for R5.
    """
    from core import config as _cfg
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: cache_root)
    # Point resolve_app_dir() somewhere DIFFERENT so we can prove the
    # default no longer derives from it.
    app_dir = tmp_path / "app"
    monkeypatch.setattr(hub, "resolve_app_dir", lambda: app_dir)

    result = hub.default_hub_folder()
    assert result == cache_root / hub.HUB_SUBFOLDER_NAME
    # And it must NOT be under the app/install dir.
    assert not hub.is_path_inside(result, app_dir)


def test_default_hub_matches_model_cache_fallback():
    """The default hub MUST equal model_folder_for's empty-hub fallback
    (``user_cache_dir() / "models"``) so an existing model already in
    %LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\models is reused, not silently
    re-downloaded (~3 GB) into a divergent folder. Regression for the R5
    follow-up (the original fix used a separate 'hub' sub-folder).
    """
    assert hub.HUB_SUBFOLDER_NAME == "models"
    # The bare fallback and the configured default must point to the same
    # per-model directory.
    assert hub.model_folder_for(None, "x") == hub.model_folder_for(
        str(hub.default_hub_folder()), "x"
    )


# ---------- is_hub_configured -------------------------------------------------


def test_is_hub_configured_false_for_empty_string():
    assert hub.is_hub_configured({"hub_folder": ""}) is False


def test_is_hub_configured_false_for_missing_key():
    assert hub.is_hub_configured({}) is False


def test_is_hub_configured_false_for_whitespace_only():
    assert hub.is_hub_configured({"hub_folder": "   "}) is False


def test_is_hub_configured_true_for_any_non_blank_value():
    """Permissive on purpose: folder existence is verified later by
    the download flow. As long as the user picked something, the
    first-run dialog should not fire again."""
    assert hub.is_hub_configured({"hub_folder": "/some/path/that/does/not/exist"}) is True


# ---------- normalise_hub_path -------------------------------------------------


def test_normalise_hub_path_empty_returns_default(monkeypatch, tmp_path):
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    assert hub.normalise_hub_path("") == str(tmp_path / hub.HUB_SUBFOLDER_NAME)
    assert hub.normalise_hub_path(None) == str(tmp_path / hub.HUB_SUBFOLDER_NAME)  # type: ignore[arg-type]


def test_normalise_hub_path_expands_user(tmp_path):
    out = hub.normalise_hub_path("~/whisper_hub")
    # ~ is expanded — the resulting path should not start with ~.
    assert not out.startswith("~")


def test_normalise_hub_path_strips_whitespace(tmp_path):
    raw = f"   {tmp_path}   "
    assert hub.normalise_hub_path(raw) == str(tmp_path.resolve())


# ---------- model_folder_for --------------------------------------------------


def test_model_folder_for_hub_plus_systran_name(tmp_path):
    out = hub.model_folder_for(tmp_path, "faster-whisper-large-v3")
    assert out == tmp_path / "models--Systran--faster-whisper-large-v3"


def test_model_folder_for_already_prefixed_name(tmp_path):
    out = hub.model_folder_for(tmp_path, "models--Custom--my-model")
    assert out == tmp_path / "models--Custom--my-model"


def test_model_folder_for_empty_hub_uses_cache(monkeypatch, tmp_path):
    # When hub is empty/None, fallback path lives under user_cache_dir.
    from core import config as _cfg
    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: tmp_path)
    out = hub.model_folder_for(None, "faster-whisper-large-v3")
    assert out == tmp_path / "models" / "models--Systran--faster-whisper-large-v3"


def test_model_folder_for_empty_model_name_raises(tmp_path):
    with pytest.raises(ValueError):
        hub.model_folder_for(tmp_path, "")
    with pytest.raises(ValueError):
        hub.model_folder_for(tmp_path, "   ")


# ---------- is_path_inside ----------------------------------------------------


def test_is_path_inside_true_for_child_of_parent(tmp_path):
    parent = tmp_path
    child = tmp_path / "sub" / "dir"
    child.mkdir(parents=True)
    assert hub.is_path_inside(child, parent) is True


def test_is_path_inside_true_for_identical_paths(tmp_path):
    assert hub.is_path_inside(tmp_path, tmp_path) is True


def test_is_path_inside_false_for_sibling(tmp_path):
    sib_a = tmp_path / "a"
    sib_b = tmp_path / "b"
    sib_a.mkdir()
    sib_b.mkdir()
    assert hub.is_path_inside(sib_a, sib_b) is False


def test_is_path_inside_false_for_unrelated_paths():
    assert hub.is_path_inside("/nowhere/at/all", "/elsewhere/entirely") is False


# ---------- derive_hub_from_model_path -----------------------------------------


def test_derive_hub_from_legacy_model_path():
    """Reverse-derive: hub = parent(model_path) when model_path looks
    like ``hub/models--Systran--<name>``. Build the path with the native
    separator (via Path) so the test exercises real derivation on both
    Windows and POSIX; a hardcoded Windows string is one component on POSIX
    and would never parse into parent parts."""
    model_path = str(
        Path("hub_root", "models", "models--Systran--faster-whisper-large-v3")
    )
    out = hub.derive_hub_from_model_path(model_path)
    assert out.endswith("models")
    assert "Systran" not in out


def test_derive_hub_from_already_hub_shaped_path():
    """If the input doesn't look like a model dir, treat it as the
    hub itself (don't strip a real folder name). Use str(Path(...))
    so the comparison survives Windows / POSIX separator differences."""
    plain = str(Path("/srv/whisper/hub"))
    assert hub.derive_hub_from_model_path(plain) == plain


def test_derive_hub_from_empty_returns_empty():
    assert hub.derive_hub_from_model_path("") == ""
    assert hub.derive_hub_from_model_path("   ") == ""


# ---------- migration via load_config -----------------------------------------


def test_load_config_migrates_model_path_to_hub_folder(tmp_path, monkeypatch):
    """A legacy config with ``model_path`` set but no ``hub_folder``
    must auto-populate ``hub_folder = parent(model_path)`` on first
    load — without forcing the user through the first-run dialog
    when they've clearly already configured a model location."""
    from core import config as cfg

    legacy_model_path = str(tmp_path / "models--Systran--faster-whisper-large-v3")
    Path(legacy_model_path).mkdir(parents=True)
    # Provide a legacy config that omits hub_folder entirely.
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"model_path": legacy_model_path}),
                            encoding="utf-8")

    loaded = cfg.load_config()
    assert loaded.get("hub_folder") == str(tmp_path)
    # model_path is preserved (override semantics).
    assert loaded.get("model_path") == legacy_model_path


def test_load_config_default_has_empty_hub_folder():
    """DEFAULT_CONFIG must ship empty hub_folder so the dialog fires
    on every fresh install per the user spec."""
    from core.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.get("hub_folder") == ""


def test_apply_runtime_fallbacks_uses_hub_when_model_path_blank(tmp_path):
    """When hub_folder is set and model_path is blank, the fallback
    derivation must use the hub instead of user_cache_dir."""
    from core.config import _apply_runtime_fallbacks
    cfg = {
        "hub_folder": str(tmp_path),
        "model_path": "",
        "model": {"name": "faster-whisper-large-v3"},
        "download_folder": "",
    }
    out = _apply_runtime_fallbacks(cfg)
    assert out["model_path"] == str(
        tmp_path / "models--Systran--faster-whisper-large-v3"
    )


def test_apply_runtime_fallbacks_empty_hub_matches_dialog_default(monkeypatch, tmp_path):
    """When hub_folder is empty, the resolved model_path must sit
    under default_hub_folder() — the same path the first-run dialog
    suggests as its default. If these diverge, the worker downloads
    the model into the wrong directory and the next launch (with
    hub_folder now saved) re-downloads it. Regression for the
    "3 GB re-download on every launch" bug.
    """
    from core import config as cfg_mod
    from core import hub as _hub

    # Pin default_hub_folder() to a tmp path so the assertion is
    # stable regardless of where the test runs from.
    monkeypatch.setattr(_hub, "default_hub_folder", lambda: tmp_path / "hub")

    cfg = {
        "hub_folder": "",
        "model_path": "",
        "model": {"name": "faster-whisper-large-v3"},
        "download_folder": "",
    }
    out = cfg_mod._apply_runtime_fallbacks(cfg)
    expected = str(
        tmp_path / "hub" / "models--Systran--faster-whisper-large-v3"
    )
    assert out["model_path"] == expected, (
        f"empty hub_folder must resolve under default_hub_folder() "
        f"({expected}), got {out['model_path']}"
    )
