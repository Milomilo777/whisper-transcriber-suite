"""config.json durability, second round: holes found in review of the first one.

A BOM file, a backup that re-enables the network, worker counters refreshed
from disk, the baseline after a save, quarantine of a file another process
just replaced, a lock held past its deadline, re-entry from update_config,
writes over an unreadable or unrepairable file, plain-dict copies, nested
objects, fail-closed from the read state, the stats re-enable, the .bak
rotation, the core.offline cache and a project file that grows after its stat.
"""
from __future__ import annotations

import ast
import builtins
import codecs
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import core.config as cfgmod
from core import offline

REPO = Path(__file__).resolve().parents[2]
_CLOSED = {"work_offline": True, "telemetry_opt_in": False, "update_check_enabled": False}


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setattr(cfgmod, "user_config_dir", lambda: d)
    monkeypatch.setattr(cfgmod, "_legacy_config_path", lambda: str(tmp_path / "no-legacy.json"))
    cfgmod._forget_last_good()
    return d


def _write(d: Path, data: Any) -> Path:
    p = d / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _disk(d: Path) -> dict[str, Any]:
    return json.loads((d / "config.json").read_text(encoding="utf-8"))


def _switches(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: cfg.get(k) for k in _CLOSED}


def _refuse_moving_to_corrupt(monkeypatch) -> None:
    real = os.replace

    def replace(src, dst):  # noqa: ANN001
        if str(dst).endswith(".corrupt"):
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)

    monkeypatch.setattr(cfgmod.os, "replace", replace)


# --- 1. A10: a UTF-8 BOM ----------------------------------------------------


def test_a_bom_file_is_read_by_every_reader_and_never_quarantined(cfg_dir):
    p = cfg_dir / "config.json"
    # What PowerShell 5.1 ``Set-Content -Encoding utf8`` writes.
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"work_offline": True, "theme": "dark"}).encode())
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["work_offline"] is True and cfg["theme"] == "dark"
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
    finally:
        offline.set_offline(False)
    cfgmod._set_local_hub_folder("D:/hub")
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    disk = _disk(cfg_dir)
    assert disk["work_offline"] is True and disk["theme"] == "light" and disk["hub_folder"] == "D:/hub"
    assert not (cfg_dir / "config.json.corrupt").exists()


# --- 2. A08: an older .bak is not consent to go online -----------------------


def test_a_backup_restore_closes_every_privacy_switch(cfg_dir):
    pin = {"mine": {"name": "mine"}}
    _write(cfg_dir, {"theme": "dark", "work_offline": False, "telemetry_opt_in": True,
                     "update_check_enabled": True, "model_catalog": pin})
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["work_offline"] = True  # the user goes offline; .bak keeps the old False
    cfgmod.save_config(cfg)
    bak = json.loads((cfg_dir / "config.json.bak").read_text(encoding="utf-8"))
    assert bak["work_offline"] is False
    (cfg_dir / "config.json").write_text('{"theme": "da', encoding="utf-8")
    cfgmod._forget_last_good()
    again = cfgmod.load_config(fetch_online=False)
    assert _switches(again) == _CLOSED
    assert again["theme"] == "dark"
    # Written back as config.json, so every process reads the same.
    disk = _disk(cfg_dir)
    assert _switches(disk) == _CLOSED and disk["theme"] == "dark"
    assert disk["model_catalog"] == pin  # the hand pin came back with it
    assert (cfg_dir / "config.json.corrupt").read_text(encoding="utf-8") == '{"theme": "da'
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
    finally:
        offline.set_offline(False)
    # The next save keeps the closed switches and the pin.
    again["theme"] = "light"
    cfgmod.save_config(again)
    disk = _disk(cfg_dir)
    assert _switches(disk) == _CLOSED and disk["model_catalog"] == pin


def test_a_missing_file_next_to_a_newer_corrupt_restores_the_backup_closed(cfg_dir):
    bak = cfg_dir / "config.json.bak"
    bak.write_text(json.dumps({"theme": "dark", "work_offline": False}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(bak, (old, old))
    # An older version moved the damaged file aside and wrote nothing.
    (cfg_dir / "config.json.corrupt").write_text("{", encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"
    assert _switches(cfg) == _CLOSED
    disk = _disk(cfg_dir)
    assert disk["theme"] == "dark" and _switches(disk) == _CLOSED


def test_a_file_deleted_after_later_saves_is_a_fresh_start_with_closed_switches(cfg_dir):
    corrupt = cfg_dir / "config.json.corrupt"
    corrupt.write_text("{", encoding="utf-8")
    old = time.time() - 3600
    os.utime(corrupt, (old, old))
    (cfg_dir / "config.json.bak").write_text(json.dumps({"custom_note": "old"}), encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    assert "custom_note" not in cfg
    assert _switches(cfg) == _CLOSED
    assert not (cfg_dir / "config.json").exists()
    # A counter cannot write a tiny file over settings it cannot see...
    with pytest.raises(cfgmod.ConfigSaveError):
        cfgmod.update_config(lambda d: d.__setitem__("n", 1))
    # ...but the app's own save writes everything, the switches explicitly.
    cfgmod.save_config(cfg)
    assert _switches(_disk(cfg_dir)) == _CLOSED


def test_a_backup_that_cannot_be_written_back_does_not_crash_a_launch(cfg_dir):
    # A JSON escape of a lone surrogate: valid JSON, but not encodable as UTF-8.
    lone_surrogate = chr(92) + "ud800"
    (cfg_dir / "config.json.bak").write_text(
        '{"theme": "dark", "note": "' + lone_surrogate + '"}', encoding="utf-8")
    (cfg_dir / "config.json").write_text('{"theme": "da', encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"
    assert _switches(cfg) == _CLOSED


def test_a_bom_project_file_applies(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / cfgmod.PROJECT_FILE_NAME).write_bytes(codecs.BOM_UTF8 + b'{"initial_prompt": "hi"}')
    assert cfgmod.load_project_overrides(proj / "media.mp4") == {"initial_prompt": "hi"}


# --- 4. A05: the baseline is the snapshot that was written --------------------


def test_the_baseline_after_a_save_is_what_was_written(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    cfg = cfgmod.load_config(fetch_online=False)
    real = cfgmod._write_disk_dict

    def racing(path: str, data: dict[str, Any]) -> None:
        cfg["note"] = "typed while the save ran"  # another thread
        real(path, data)

    monkeypatch.setattr(cfgmod, "_write_disk_dict", racing)
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    monkeypatch.setattr(cfgmod, "_write_disk_dict", real)
    assert "note" not in _disk(cfg_dir)
    cfgmod.save_config(cfg)
    assert _disk(cfg_dir)["note"] == "typed while the save ran"


# --- 6. A01 + 7. A06: the lock and re-entry ----------------------------------


def test_update_config_function_cannot_reenter(cfg_dir):
    _write(cfg_dir, {"theme": "dark"})

    def save(d: dict[str, Any]) -> None:
        cfgmod.save_config(d)

    def update(_d: dict[str, Any]) -> None:
        cfgmod.update_config(lambda _e: None)

    def load(_d: dict[str, Any]) -> None:
        cfgmod.load_config(fetch_online=False)

    for inner in (save, update, load):
        with pytest.raises(RuntimeError, match="inside an update_config"):
            cfgmod.update_config(inner)
    assert _disk(cfg_dir) == {"theme": "dark"}
    cfg = cfgmod.load_config(fetch_online=False)  # the guard was reset
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    assert _disk(cfg_dir)["theme"] == "light"


# --- 8. A03: never write over a file that cannot be read or repaired ----------


def test_a_damaged_file_whose_repair_fails_is_never_written_over(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark", "work_offline": True})
    cfgmod.load_config(fetch_online=False)  # leaves a last-good copy in memory
    p = cfg_dir / "config.json"
    p.write_text('{"theme": "da', encoding="utf-8")
    _refuse_moving_to_corrupt(monkeypatch)
    with pytest.raises(cfgmod.ConfigSaveError):
        cfgmod.save_config({"theme": "light", "work_offline": False})
    with pytest.raises(cfgmod.ConfigSaveError):
        cfgmod.update_config(lambda d: d.__setitem__("n", 1))
    assert p.read_text(encoding="utf-8") == '{"theme": "da'


# --- 10. A02: copies of the loaded dict ---------------------------------------


def test_a_copy_of_the_loaded_dict_still_merges(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "cloud_stt_minutes_used": 1.0})
    cfg = cfgmod.load_config(fetch_online=False)
    assert isinstance(cfg, cfgmod.LoadedConfig)
    assert isinstance(cfg.copy(), cfgmod.LoadedConfig)
    assert isinstance(copy.copy(cfg), cfgmod.LoadedConfig)
    dup = cfg.copy()
    assert isinstance(dup, cfgmod.LoadedConfig)
    cfgmod.update_config(lambda d: d.__setitem__("cloud_stt_minutes_used", 7.5))
    dup["theme"] = "light"
    cfgmod.save_config(dup)
    disk = _disk(cfg_dir)
    assert disk["theme"] == "light" and disk["cloud_stt_minutes_used"] == 7.5
    # The copy's baseline is its own: saving it did not move the original's.
    assert cfg._config_baseline is not dup._config_baseline


def _plain_copy_saves(tree: ast.AST) -> list[int]:
    def name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and name(node.func) == "save_config" and node.args:
            arg = node.args[0]
            if (isinstance(arg, ast.Call) and name(arg.func) == "dict") or (
                isinstance(arg, ast.Dict) and None in arg.keys
            ):
                lines.append(node.lineno)
    return lines


def test_no_caller_saves_a_plain_dict_copy_of_the_settings():
    # The check itself: it finds both shapes.
    assert _plain_copy_saves(ast.parse("save_config(dict(c))\nc.save_config({**c})")) == [1, 2]
    assert _plain_copy_saves(ast.parse("save_config(c)\nsave_config(c.copy())")) == []
    offenders = []
    files = [*(REPO / "app").rglob("*.py"), *(REPO / "core").rglob("*.py"), REPO / "gui.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.relative_to(REPO)}:{n}" for n in _plain_copy_saves(tree)]
    assert offenders == []


def test_a_plain_dict_save_warns_once(cfg_dir, caplog, monkeypatch):
    monkeypatch.setattr(cfgmod, "_PLAIN_DICT_WARNED", False)
    _write(cfg_dir, {"theme": "dark"})
    with caplog.at_level("WARNING", logger="core.config"):
        cfgmod.save_config({"theme": "light"})
        cfgmod.save_config({"theme": "blue"})
    assert sum("plain dict" in r.getMessage() for r in caplog.records) == 1


# --- 11. A04: nested objects merge per leaf -----------------------------------


def test_a_nested_change_keeps_the_leaves_another_process_saved(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "model": {"name": "A", "compute": "int8"},
                     "custom_obj": {"a": 1, "b": 2}, "output_formats": ["srt"]})
    gui = cfgmod.load_config(fetch_online=False)

    def other(d: dict[str, Any]) -> None:
        d["model"]["compute"] = "float16"
        d["custom_obj"]["c"] = 3
        d["output_formats"] = ["json"]

    cfgmod.update_config(other)
    gui["model"] = {**gui["model"], "name": "B"}
    del gui["custom_obj"]["b"]
    gui["output_formats"] = ["srt", "vtt"]
    cfgmod.save_config(gui)
    disk = _disk(cfg_dir)
    assert disk["model"]["name"] == "B" and disk["model"]["compute"] == "float16"
    assert disk["custom_obj"] == {"a": 1, "c": 3}
    assert disk["output_formats"] == ["srt", "vtt"]  # lists are one value


# --- 12. A11: fail closed from the read state ---------------------------------


def test_a_non_object_file_that_cannot_be_moved_still_reads_closed(cfg_dir, monkeypatch):
    (cfg_dir / "config.json").write_text("[]", encoding="utf-8")
    _refuse_moving_to_corrupt(monkeypatch)
    cfg = cfgmod.load_config(fetch_online=False)
    assert not (cfg_dir / "config.json.corrupt").exists()
    assert _switches(cfg) == _CLOSED


def test_an_unreadable_file_with_no_last_good_copy_reads_closed(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark", "work_offline": False, "telemetry_opt_in": True})
    monkeypatch.setattr(cfgmod, "_READ_RETRY_SECONDS", 0.05)
    real = builtins.open

    def locked(file, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(file).endswith("config.json"):
            raise PermissionError(13, "The process cannot access the file", str(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(cfgmod, "open", locked, raising=False)
    urls: list[str] = []
    monkeypatch.setattr(cfgmod, "fetch_online_config", lambda url, **k: urls.append(url) or {})
    cfgmod.refresh_online_config()
    offline.set_offline(None)
    try:
        cfg = cfgmod.load_config()
    finally:
        offline.set_offline(False)
        cfgmod.refresh_online_config()
    assert _switches(cfg) == _CLOSED
    assert all(u == "" for u in urls)
    monkeypatch.delattr(cfgmod, "open")
    # A failed read is not a choice: a later save does not write it.
    cfg["custom_note"] = "x"
    cfgmod.save_config(cfg)
    disk = _disk(cfg_dir)
    assert disk["custom_note"] == "x" and disk["theme"] == "dark"
    # (telemetry_opt_in True is the default, so a save may leave it out.)
    assert disk["work_offline"] is False and disk.get("telemetry_opt_in", True) is True


# --- 13. N1: turning stats back on is saved -----------------------------------


def test_turning_usage_statistics_back_on_is_saved(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "telemetry_opt_in": False})
    cfg = cfgmod.load_config(fetch_online=False)
    stale = cfgmod.load_config(fetch_online=False)
    cfg["telemetry_opt_in"] = True
    cfgmod.save_config(cfg)
    stale["theme"] = "light"  # a copy that never touched the switch
    cfgmod.save_config(stale)
    cfgmod._forget_last_good()
    assert cfgmod.load_config(fetch_online=False)["telemetry_opt_in"] is True


# --- 14. optional: .bak rotation, offline cache, bounded project read ----------


def test_a_backup_copy_cut_off_keeps_the_previous_backup(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    assert json.loads((cfg_dir / "config.json.bak").read_text(encoding="utf-8"))["theme"] == "dark"

    def torn(src, dst, *a, **k):  # noqa: ANN001, ANN002, ANN003
        Path(dst).write_text("{", encoding="utf-8")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cfgmod.shutil, "copy2", torn)
    cfg["theme"] = "blue"
    cfgmod.save_config(cfg)
    assert _disk(cfg_dir)["theme"] == "blue"
    assert json.loads((cfg_dir / "config.json.bak").read_text(encoding="utf-8"))["theme"] == "dark"
    assert not (cfg_dir / "config.json.bak.tmp").exists()


def test_the_offline_cache_rereads_an_in_place_edit_after_a_while(cfg_dir, monkeypatch):
    p = cfg_dir / "config.json"
    p.write_text('{"work_offline": true }', encoding="utf-8")
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
        st = os.stat(p)
        with open(p, "r+b") as f:  # same size, same file, mtime put back
            f.write(b'{"work_offline": false}')
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        monkeypatch.setattr(offline, "_CACHE_SECONDS", 0.0)
        assert offline.is_offline() is False
    finally:
        offline.set_offline(False)


def test_a_project_file_that_grew_after_its_stat_is_refused(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    big = proj / cfgmod.PROJECT_FILE_NAME
    big.write_text('{"initial_prompt": "' + "x" * (2 * 1024 * 1024) + '"}', encoding="utf-8")
    real_stat = Path.stat

    def small(self: Path, *a: Any, **k: Any) -> os.stat_result:
        st = real_stat(self, *a, **k)
        if self.name != cfgmod.PROJECT_FILE_NAME:
            return st
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid,
                               st.st_gid, 10, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))

    monkeypatch.setattr(Path, "stat", small)
    assert cfgmod.load_project_overrides(proj / "media.mp4") == {}


# --- two real processes: 3. A19, 5. A07 -----------------------------------------

_UPDATER = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import core.config as c
d = Path(sys.argv[2])
c.user_config_dir = lambda: d
c._legacy_config_path = lambda: str(d / "no-legacy.json")
c._legacy_app_dirs = lambda: None
key, n = sys.argv[3], int(sys.argv[4])
for _ in range(n):
    c.update_config(lambda cfg: cfg.__setitem__(key, int(cfg.get(key, 0)) + 1))
"""

_REPLACER = r"""
import os, sys
path, body = sys.argv[1], sys.argv[2]
with open(path + ".writer.tmp", "w", encoding="utf-8") as f:
    f.write(body)
os.replace(path + ".writer.tmp", path)
"""


def _child(*args: str) -> None:
    done = subprocess.run([sys.executable, "-c", *args], capture_output=True, timeout=240)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]


def test_a_counter_refreshed_from_disk_is_not_written_back_stale(cfg_dir):
    """A19: Advanced refreshes the worker's counter; the GUI's save keeps the newest."""
    _write(cfg_dir, {"theme": "dark"})
    gui = cfgmod.load_config(fetch_online=False)
    _child(_UPDATER, str(REPO), str(cfg_dir), "n", "12")
    cfgmod.sync_from_disk(gui, ("n",))
    assert gui["n"] == 12
    _child(_UPDATER, str(REPO), str(cfg_dir), "n", "12")
    gui["theme"] = "light"
    cfgmod.save_config(gui)
    disk = _disk(cfg_dir)
    assert disk["n"] == 24 and disk["theme"] == "light"


@pytest.mark.parametrize("at_read", [1, 2])
def test_a_file_another_process_replaced_is_never_quarantined(cfg_dir, monkeypatch, at_read):
    """A07: the damaged file was replaced by a good one between the failed read
    and the move (1: before the lock is taken; 2: while it is held, by a writer
    that could not use the lock)."""
    p = cfg_dir / "config.json"
    p.write_text('{"theme": "da', encoding="utf-8")
    good = json.dumps({"theme": "light", "n": 120})
    real = cfgmod._read_config_file_keyed
    reads = {"n": 0}

    def read_then_replace(path: str, *, retry_seconds: float):  # noqa: ANN202
        result = real(path, retry_seconds=retry_seconds)
        if path == str(p) and result[0] == "corrupt":
            reads["n"] += 1
            if reads["n"] == at_read:
                _child(_REPLACER, str(p), good)
        return result

    monkeypatch.setattr(cfgmod, "_read_config_file_keyed", read_then_replace)
    cfgmod.load_config(fetch_online=False)
    assert reads["n"] == at_read
    assert p.read_text(encoding="utf-8") == good
    assert not (cfg_dir / "config.json.corrupt").exists()
