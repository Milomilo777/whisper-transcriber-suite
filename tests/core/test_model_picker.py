"""Tests for the v0.8 multi-model picker registry."""
from __future__ import annotations

import pytest

from core import model_manager as mm


def test_registry_contains_expected_models():
    """The v1.3.9 registry expanded to the full Systran faster-whisper
    family + the Large v3 Turbo variants (mobiuslabsgmbh + deepdml)."""
    assert set(mm.MODEL_REGISTRY.keys()) == {
        "tiny.en", "tiny", "base.en", "base", "small.en", "small",
        "medium.en", "medium", "large-v1", "large-v2", "large-v3",
        "distil-small.en", "distil-medium.en", "distil-large-v2",
        "distil-large-v3", "distil-large-v3.5", "large-v3-turbo",
        "deepdml-large-v3-turbo",
    }
    # The four originally-bundled models stay in the registry.
    assert {"large-v3", "large-v3-turbo", "distil-large-v3.5", "medium"} \
        <= set(mm.MODEL_REGISTRY.keys())


def test_default_slug_is_large_v3():
    assert mm.DEFAULT_MODEL_SLUG == "large-v3"
    assert mm.DEFAULT_MODEL_SLUG in mm.MODEL_REGISTRY


def test_list_models_returns_slug_label_pairs():
    items = mm.list_models()
    assert isinstance(items, list)
    assert len(items) == len(mm.MODEL_REGISTRY)
    for slug, label in items:
        assert isinstance(slug, str)
        assert isinstance(label, str)
        assert slug in mm.MODEL_REGISTRY


def test_resolve_model_entry_returns_dict_shape():
    entry = mm.resolve_model_entry("large-v3")
    assert entry is not None
    # Same shape as DEFAULT_CONFIG["model"] so callers can drop it straight
    # into config["model"]; the retired mirror keys are gone.
    assert set(entry.keys()) == {"name", "hf_repo"}
    assert entry["name"] == "faster-whisper-large-v3"
    assert entry["hf_repo"] == "Systran/faster-whisper-large-v3"


def test_resolve_model_entry_turbo_returns_distinct_repos():
    base = mm.resolve_model_entry("large-v3")
    turbo = mm.resolve_model_entry("large-v3-turbo")
    distil = mm.resolve_model_entry("distil-large-v3.5")
    assert base is not None and turbo is not None and distil is not None
    assert base["hf_repo"] != turbo["hf_repo"]
    assert base["hf_repo"] != distil["hf_repo"]
    assert turbo["hf_repo"] != distil["hf_repo"]
    assert base["name"] != turbo["name"] != distil["name"]


def test_resolve_model_entry_unknown_slug_returns_none():
    assert mm.resolve_model_entry("does-not-exist") is None
    assert mm.resolve_model_entry("") is None


@pytest.mark.parametrize("slug", list(mm.MODEL_REGISTRY.keys()))
def test_every_registry_entry_has_required_fields(slug):
    """Every entry downloads from its hf_repo on the Hugging Face Hub; no
    entry names another server (the zip mirror is retired)."""
    entry = mm.MODEL_REGISTRY[slug]
    assert "label" in entry and entry["label"]
    assert "name" in entry and entry["name"]
    assert "hf_repo" in entry and entry["hf_repo"]
    assert "url" not in entry and "md5" not in entry
    assert "approx_size_gb" in entry
    assert isinstance(entry["approx_size_gb"], (int, float))


def test_label_includes_size_so_user_sees_install_cost():
    """The dropdown label is the only place the user learns the install
    cost; ensure every label includes a GB hint."""
    for _slug, label in mm.list_models():
        assert "GB" in label, f"label {label!r} missing GB size hint"


def test_default_config_carries_new_keys():
    """The new whisper_model + hallucination_detect_enabled keys must
    ship in DEFAULT_CONFIG so a fresh install picks them up without
    needing the user to edit anything."""
    from core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG.get("whisper_model") == "large-v3"
    assert DEFAULT_CONFIG.get("hallucination_detect_enabled") is True


# ---------- P4-2: config-driven merged model catalog ------------------------


def test_catalog_models_includes_builtins_with_empty_config():
    """With no online catalog, the merged catalog is just the built-ins."""
    items = mm.catalog_models({})
    slugs = {slug for slug, _label in items}
    assert slugs == set(mm.MODEL_REGISTRY.keys())


def test_catalog_models_adds_online_model():
    """An online-added model (not in MODEL_REGISTRY) appears in the catalog
    so a new model can ship without an app update."""
    config = {
        "model_catalog": {
            "online-new": {
                "label": "Online New (~2 GB)",
                "name": "faster-whisper-online-new",
                "hf_repo": "SomeOrg/faster-whisper-online-new",
                "approx_size_gb": 2.0,
            }
        }
    }
    slugs = {slug for slug, _label in mm.catalog_models(config)}
    assert "online-new" in slugs
    assert set(mm.MODEL_REGISTRY.keys()).issubset(slugs)  # built-ins still there
    entry = mm.catalog_resolve_entry(config, "online-new")
    assert entry == {
        "name": "faster-whisper-online-new",
        "hf_repo": "SomeOrg/faster-whisper-online-new",
    }


def test_catalog_online_can_override_builtin_repo():
    """The online catalog may re-point a built-in slug's hf_repo without an
    app update, but never to a non-Hub server (url/md5 are dropped)."""
    config = {
        "model_catalog": {
            "large-v3": {
                "url": "https://newmirror/large-v3.zip",
                "md5": "https://newmirror/large-v3.zip.md5",
                "name": "faster-whisper-large-v3",
                "hf_repo": "SomeOrg/faster-whisper-large-v3",
            }
        }
    }
    entry = mm.catalog_resolve_entry(config, "large-v3")
    assert entry == {
        "name": "faster-whisper-large-v3",
        "hf_repo": "SomeOrg/faster-whisper-large-v3",
    }


def test_catalog_ignores_malformed_online_entries():
    """A malformed online entry (missing name/hf_repo, or not a dict) is skipped;
    the built-ins always survive a bad payload."""
    config = {
        "model_catalog": {
            "broken": {"label": "no source"},    # missing name/hf_repo
            "alsobad": "not-a-dict",              # not a dict
        }
    }
    slugs = {slug for slug, _label in mm.catalog_models(config)}
    assert "broken" not in slugs
    assert "alsobad" not in slugs
    assert set(mm.MODEL_REGISTRY.keys()).issubset(slugs)


def test_catalog_resolve_unknown_slug_returns_none():
    assert mm.catalog_resolve_entry({}, "does-not-exist") is None


def test_medium_is_a_builtin_model():
    """faster-whisper-medium ships as a built-in catalog entry."""
    entry = mm.resolve_model_entry("medium")
    assert entry is not None
    assert entry["name"] == "faster-whisper-medium"
    assert entry["hf_repo"] == "Systran/faster-whisper-medium"
