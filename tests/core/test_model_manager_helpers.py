"""Helpers of ``core.model_manager``: catalog sizes, tree size, error text.

The catalog can come from an online or hand-edited config, so a size that is
not a plain positive finite number (text, a bool, ``Infinity``) must mean
"unknown", never a crash or a nonsense size. Hermetic: no network, no model.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from core import model_manager as mm

_SLUG = "large-v3"
_ENTRY = mm.MODEL_REGISTRY[_SLUG]


def _config(size) -> dict:
    """A catalog that overrides the built-in entry's size (name and repo kept)."""
    return {"model_catalog": {_SLUG: {
        "name": _ENTRY["name"], "hf_repo": _ENTRY["hf_repo"], "approx_size_gb": size,
    }}}


# --- catalog sizes ----------------------------------------------------------


def test_built_in_catalog_gives_the_size_of_a_model():
    assert mm._approx_model_bytes({}, _ENTRY["name"]) == int(3.0 * 1024 ** 3)


def test_catalog_can_override_the_size():
    assert mm._approx_model_bytes(_config(1.5), _ENTRY["name"]) == int(1.5 * 1024 ** 3)
    assert mm.approx_download_size_text(_config(1.5), _SLUG) == "about 1.5 GB"
    assert mm.approx_download_size_text(_config(0.5), _SLUG) == "about 500 MB"


def test_an_unknown_model_has_no_size():
    assert mm._approx_model_bytes({}, "not-a-model") == 0


@pytest.mark.parametrize("size", ["1.5", True, -1, 0, None, math.inf, -math.inf, math.nan, 10 ** 400])
def test_an_unusable_size_means_unknown(size):
    assert mm._approx_model_bytes(_config(size), _ENTRY["name"]) == 0
    assert mm.approx_download_size_text(_config(size), _SLUG) == ""


# --- folder size ------------------------------------------------------------


def test_tree_size_sums_files_in_nested_folders(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "top.bin").write_bytes(b"x" * 10)
    (tmp_path / "a" / "mid.bin").write_bytes(b"x" * 20)
    (tmp_path / "a" / "b" / "deep.bin").write_bytes(b"x" * 30)
    assert mm._tree_size(tmp_path) == 60


def test_tree_size_of_a_single_file_and_of_nothing(tmp_path):
    single = tmp_path / "model.bin"
    single.write_bytes(b"x" * 7)
    assert mm._tree_size(single) == 7
    assert mm._tree_size(tmp_path / "missing") == 0
    assert mm._tree_size(tmp_path / "empty-folder-that-does-not-exist") == 0


def test_tree_size_of_an_empty_folder_is_zero(tmp_path):
    (tmp_path / "empty").mkdir()
    assert mm._tree_size(tmp_path / "empty") == 0


# --- error text -------------------------------------------------------------


def test_a_download_error_names_its_type_and_message():
    text = mm._describe_download_error(ValueError("boom"), Path("models"), "huggingface.co")
    assert text == "ValueError: boom"


def test_a_very_long_error_message_is_cut_to_300_characters():
    text = mm._describe_download_error(
        RuntimeError("x" * 500), Path("models"), "huggingface.co"
    )
    assert len(text) == 300
    assert text.endswith("...")


def test_a_network_error_says_the_site_could_not_be_reached():
    class ConnectError(Exception):
        pass

    text = mm._describe_download_error(
        ConnectError("down"), Path("models"), "huggingface.co"
    )
    assert text.startswith("Could not reach huggingface.co")
    assert text.endswith("[ConnectError: down]")
