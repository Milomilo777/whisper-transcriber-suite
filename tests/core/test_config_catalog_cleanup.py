"""Stale shipped ``model_catalog`` copies are removed from config.json.

Versions before ``model_catalog`` became disk-only saved the merged catalog
into config.json, where it shadowed every later fix to the online catalog.
load_config drops such a copy once, only when it is unedited (equal, as JSON,
to a catalog a released version shipped), and keeps the file as it was in
``config.json.bak``. A copy with any edit stays.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest

import core.config as cfgmod

REPO = Path(__file__).resolve().parents[2]
SHIPPED_ONLINE = json.loads((REPO / "configuration.json").read_text(encoding="utf-8"))["model_catalog"]


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setattr(cfgmod, "user_config_dir", lambda: d)
    monkeypatch.setattr(cfgmod, "_legacy_config_path", lambda: str(tmp_path / "no-legacy.json"))
    monkeypatch.setattr(cfgmod, "_CATALOG_CLEANUP_TRIED", set())
    cfgmod._forget_last_good()
    return d


def _next_launch(monkeypatch) -> None:
    monkeypatch.setattr(cfgmod, "_CATALOG_CLEANUP_TRIED", set())
    cfgmod._forget_last_good()


def _write(d: Path, data: Any, **dump_kwargs: Any) -> Path:
    p = d / "config.json"
    p.write_text(json.dumps(data, **dump_kwargs), encoding="utf-8")
    return p


def _disk(d: Path, name: str = "config.json") -> dict[str, Any]:
    return json.loads((d / name).read_text(encoding="utf-8"))


def test_every_shipped_catalog_is_known():
    # Old versions in use still pin whatever the hosted file holds: a new
    # online catalog in configuration.json needs its digest in the set.
    assert cfgmod._catalog_digest(SHIPPED_ONLINE) in cfgmod._SHIPPED_MODEL_CATALOG_DIGESTS
    assert (
        cfgmod._catalog_digest(cfgmod.DEFAULT_CONFIG["model_catalog"])
        in cfgmod._SHIPPED_MODEL_CATALOG_DIGESTS
    )


@pytest.mark.parametrize("catalog", [SHIPPED_ONLINE, {}], ids=["online", "default"])
def test_an_unedited_shipped_copy_is_removed_and_backed_up(cfg_dir, catalog, caplog):
    original = {"theme": "dark", "work_offline": True, "model_catalog": catalog}
    _write(cfg_dir, original, indent=2)
    with caplog.at_level(logging.INFO, logger=cfgmod.logger.name):
        cfg = cfgmod.load_config(fetch_online=False)
    disk = _disk(cfg_dir)
    assert "model_catalog" not in disk
    assert disk == {"theme": "dark", "work_offline": True}
    assert _disk(cfg_dir, "config.json.bak") == original
    assert cfg["model_catalog"] == {}  # the built-in default, no stale overlay
    removed = [r for r in caplog.records if "shipped model catalog" in r.getMessage()]
    assert len(removed) == 1
    assert "tiny" not in removed[0].getMessage()  # no values in the log


def test_key_order_and_spacing_do_not_count_as_an_edit(cfg_dir):
    reordered = {slug: dict(reversed(list(entry.items())))
                 for slug, entry in reversed(list(SHIPPED_ONLINE.items()))}
    p = cfg_dir / "config.json"
    p.write_text(json.dumps({"model_catalog": reordered, "theme": "dark"}, indent=4), encoding="utf-8")
    cfgmod.load_config(fetch_online=False)
    assert "model_catalog" not in _disk(cfg_dir)


def test_whole_numbers_written_without_a_decimal_point_still_match(cfg_dir):
    # The shipped catalog has approx_size_gb 3.0; a host or editor may write 3.
    assert SHIPPED_ONLINE["large-v3"]["approx_size_gb"] == 3.0
    text = json.dumps({"model_catalog": SHIPPED_ONLINE}).replace(
        '"approx_size_gb": 3.0', '"approx_size_gb": 3')
    assert '"approx_size_gb": 3,' in text
    (cfg_dir / "config.json").write_text(text, encoding="utf-8")
    cfgmod.load_config(fetch_online=False)
    assert "model_catalog" not in _disk(cfg_dir)


def test_a_second_load_writes_nothing(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark", "model_catalog": SHIPPED_ONLINE})
    cfgmod.load_config(fetch_online=False)
    files = {p.name: p.read_bytes() for p in cfg_dir.iterdir() if p.is_file()}
    _next_launch(monkeypatch)
    cfgmod.load_config(fetch_online=False)
    assert {p.name: p.read_bytes() for p in cfg_dir.iterdir() if p.is_file()} == files


def _edited(change):
    catalog = copy.deepcopy(SHIPPED_ONLINE)
    change(catalog)
    return catalog


@pytest.mark.parametrize("catalog", [
    _edited(lambda c: c["tiny"].update(hf_repo="me/my-tiny")),
    _edited(lambda c: c.pop("tiny")),
    _edited(lambda c: c.update(mine={"name": "mine", "hf_repo": "me/mine"})),
    _edited(lambda c: c["tiny"].update(approx_size_gb=0.0751)),
    {"mine": {"name": "mine", "hf_repo": "me/mine"}},
], ids=["changed-field", "removed-model", "added-model", "changed-number", "own-catalog"])
def test_a_hand_edited_catalog_stays(cfg_dir, catalog):
    _write(cfg_dir, {"theme": "dark", "model_catalog": catalog})
    cfg = cfgmod.load_config(fetch_online=False)
    assert _disk(cfg_dir)["model_catalog"] == catalog
    assert not (cfg_dir / "config.json.bak").exists()  # nothing was written
    for slug in catalog:
        assert slug in cfg["model_catalog"]


def test_after_the_cleanup_the_online_catalog_reaches_the_user(cfg_dir, monkeypatch):
    fixed = copy.deepcopy(SHIPPED_ONLINE)
    fixed["tiny"]["hf_repo"] = "Systran/faster-whisper-tiny-fixed"
    monkeypatch.setattr(cfgmod, "fetch_online_config", lambda *a, **k: {"model_catalog": fixed})
    cfgmod.refresh_online_config()
    try:
        _write(cfg_dir, {"theme": "dark", "model_catalog": SHIPPED_ONLINE})
        cfg = cfgmod.load_config()
        assert cfg["model_catalog"]["tiny"]["hf_repo"] == "Systran/faster-whisper-tiny-fixed"
        cfg["theme"] = "light"
        cfgmod.save_config(cfg)
        assert "model_catalog" not in _disk(cfg_dir)  # and no save pins it again
    finally:
        cfgmod.refresh_online_config()


def test_a_busy_file_is_left_alone_and_cleaned_on_the_next_launch(cfg_dir, monkeypatch):
    original = {"theme": "dark", "model_catalog": SHIPPED_ONLINE}
    _write(cfg_dir, original)
    real_lock = cfgmod._config_file_lock

    def busy(*a: Any, **k: Any):
        raise cfgmod.ConfigBusyError(0, "held by another process")

    monkeypatch.setattr(cfgmod, "_config_file_lock", busy)
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["model_catalog"] == {}  # still ignored for this session
    assert _disk(cfg_dir) == original
    monkeypatch.setattr(cfgmod, "_config_file_lock", real_lock)
    _next_launch(monkeypatch)
    cfgmod.load_config(fetch_online=False)
    assert "model_catalog" not in _disk(cfg_dir)


def test_without_a_backup_the_copy_stays_on_disk(cfg_dir, monkeypatch):
    original = {"theme": "dark", "model_catalog": SHIPPED_ONLINE}
    _write(cfg_dir, original)
    old_bak = {"theme": "old"}
    (cfg_dir / "config.json.bak").write_text(json.dumps(old_bak), encoding="utf-8")

    def no_copy(*a: Any, **k: Any):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cfgmod.shutil, "copy2", no_copy)
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["model_catalog"] == {}
    assert _disk(cfg_dir) == original
    assert _disk(cfg_dir, "config.json.bak") == old_bak


def test_a_failing_write_is_tried_once_per_launch(cfg_dir, monkeypatch, caplog):
    original = {"theme": "dark", "model_catalog": SHIPPED_ONLINE}
    _write(cfg_dir, original)
    calls = []

    def refuse(*a: Any, **k: Any):
        calls.append(1)
        raise cfgmod.ConfigSaveError(0, "read-only")

    monkeypatch.setattr(cfgmod, "_write_disk_dict", refuse)
    with caplog.at_level(logging.WARNING, logger=cfgmod.logger.name):
        for _ in range(3):
            cfg = cfgmod.load_config(fetch_online=False)
            assert cfg["model_catalog"] == {}
    assert len(calls) == 1
    assert len([r for r in caplog.records if "stale model catalog" in r.getMessage()]) == 1
    assert _disk(cfg_dir) == original


def test_while_a_damaged_file_is_kept_the_backup_is_not_replaced(cfg_dir):
    # A damaged config.json is put back from its .bak with the privacy
    # switches closed; the .bak is then the only copy of the saved switches
    # and must not be replaced by the cleanup's own backup.
    bak = {"theme": "dark", "work_offline": False, "telemetry_opt_in": True,
           "model_catalog": SHIPPED_ONLINE}
    (cfg_dir / "config.json.bak").write_text(json.dumps(bak), encoding="utf-8")
    (cfg_dir / "config.json").write_text('{"theme": "da', encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["model_catalog"] == {}
    assert cfg["work_offline"] is True and cfg["telemetry_opt_in"] is False
    assert _disk(cfg_dir, "config.json.bak") == bak
    assert (cfg_dir / "config.json.corrupt").exists()


def test_a_copy_edited_by_another_process_meanwhile_stays(cfg_dir, monkeypatch):
    # The first read saw the shipped copy; by the time the lock is held the
    # file holds an edited one: the re-check under the lock keeps it.
    edited = _edited(lambda c: c["tiny"].update(hf_repo="me/my-tiny"))
    _write(cfg_dir, {"theme": "dark", "model_catalog": edited})
    monkeypatch.setattr(
        cfgmod, "_read_local_config",
        lambda: {"theme": "dark", "model_catalog": copy.deepcopy(SHIPPED_ONLINE)},
    )
    cfgmod.load_config(fetch_online=False)
    assert _disk(cfg_dir)["model_catalog"] == edited


def test_no_file_and_no_catalog_write_nothing(cfg_dir):
    cfgmod.load_config(fetch_online=False)
    assert not (cfg_dir / "config.json").exists()
    _write(cfg_dir, {"theme": "dark"})
    before = (cfg_dir / "config.json").read_bytes()
    cfgmod.load_config(fetch_online=False)
    assert (cfg_dir / "config.json").read_bytes() == before
    assert not (cfg_dir / "config.json.bak").exists()


def test_a_value_json_cannot_hold_has_no_digest():
    assert cfgmod._catalog_digest({"x": float("nan")}) is None
    assert cfgmod._catalog_digest({"x": object()}) is None
