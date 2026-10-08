"""Every "is the model installed?" gate treats an empty model.bin as not installed.

``core.hub.model_weights_present`` says it is the one check all gates use. A killed
download can leave a 0-byte ``model.bin``; the existence-only gates called such a model
installed, so the app skipped the download and the engine then failed on the empty file.
"""
from __future__ import annotations

import pytest

from core import live_model
from core import model_manager as mm
from core.hub import model_folder_for, model_weights_present


def _model_dir(tmp_path, slug: str = "tiny"):
    d = model_folder_for(tmp_path, mm.MODEL_REGISTRY[slug]["name"])
    d.mkdir(parents=True)
    return d


STATES = ["no_folder", "no_weights", "empty_weights", "real_weights", "weights_is_a_folder"]


def _make(tmp_path, state: str):
    d = model_folder_for(tmp_path, mm.MODEL_REGISTRY["tiny"]["name"])
    if state == "no_folder":
        return d
    d.mkdir(parents=True)
    if state == "empty_weights":
        (d / "model.bin").write_bytes(b"")
    elif state == "real_weights":
        (d / "model.bin").write_bytes(b"x")
    elif state == "weights_is_a_folder":
        (d / "model.bin").mkdir()
    return d


@pytest.mark.parametrize("state", STATES)
def test_model_downloaded_agrees_with_model_weights_present(tmp_path, state):
    d = _make(tmp_path, state)
    assert mm.model_downloaded({"hub_folder": str(tmp_path)}, "tiny") is model_weights_present(d)


@pytest.mark.parametrize("state", STATES)
def test_live_model_is_downloaded_agrees_with_model_weights_present(tmp_path, state):
    d = _make(tmp_path, state)
    assert live_model.is_downloaded({"model_path": str(d)}) is model_weights_present(d)


def test_an_empty_model_bin_is_not_installed(tmp_path):
    (_model_dir(tmp_path) / "model.bin").write_bytes(b"")
    assert mm.model_downloaded({"hub_folder": str(tmp_path)}, "tiny") is False
    assert live_model.is_downloaded(
        {"model_path": str(model_folder_for(tmp_path, mm.MODEL_REGISTRY["tiny"]["name"]))}
    ) is False


def test_live_model_without_a_path_is_not_downloaded_whatever_the_cwd_holds(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    assert live_model.is_downloaded({}) is False
    assert live_model.is_downloaded({"model_path": ""}) is False


def test_the_worker_ignores_a_live_model_whose_weights_are_empty(tmp_path, monkeypatch):
    d = _model_dir(tmp_path)
    (d / "model.bin").write_bytes(b"")
    monkeypatch.setenv(live_model.LIVE_MODEL_ENV, "tiny")
    cfg = {"hub_folder": str(tmp_path), "whisper_model": "base", "model_path": "keep"}
    assert live_model.apply_env_override(cfg) is None
    assert cfg["model_path"] == "keep"
    (d / "model.bin").write_bytes(b"x")
    assert live_model.apply_env_override(cfg) == "tiny"
