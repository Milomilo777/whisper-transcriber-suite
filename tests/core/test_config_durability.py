"""config.json durability: settings are never lost, privacy switches fail closed.

Covers the read path (a transient lock, a cp1252 file, a torn file with and
without ``config.json.bak``), the write path (``os.replace`` retries, the
shrink guard, a cross-process lock), merge-on-save (a stale in-memory dict
must not revert keys another process saved) and the fail-closed coercion of
``work_offline`` / ``telemetry_opt_in`` / ``update_check_enabled``.
"""
from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import core.config as cfgmod
from core import offline

REPO = Path(__file__).resolve().parents[2]


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


def _flaky_open(path_suffix: str, failures: int):
    """An ``open`` that raises PermissionError ``failures`` times for one file."""
    state = {"left": failures}
    real = builtins.open

    def fake(file, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(file).endswith(path_suffix) and state["left"] > 0:
            state["left"] -= 1
            raise PermissionError(13, "The process cannot access the file", str(file))
        return real(file, *args, **kwargs)

    return fake, state


# --- S05-1: a transient read error is not corruption ------------------------


def test_transient_read_error_keeps_the_file_and_its_settings(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark", "work_offline": True})
    fake, state = _flaky_open("config.json", 2)
    monkeypatch.setattr(cfgmod, "open", fake, raising=False)
    local = cfgmod._read_local_config()
    assert local.get("theme") == "dark"
    assert state["left"] == 0
    assert (cfg_dir / "config.json").exists()
    assert not (cfg_dir / "config.json.corrupt").exists()


def test_a_lasting_read_error_never_renames_the_file(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    assert cfgmod._read_local_config()["theme"] == "dark"  # remembered as last good
    monkeypatch.setattr(cfgmod, "_READ_RETRY_SECONDS", 0.05)
    fake, _ = _flaky_open("config.json", 10_000)
    monkeypatch.setattr(cfgmod, "open", fake, raising=False)
    local = cfgmod._read_local_config()
    assert local.get("theme") == "dark"
    assert not (cfg_dir / "config.json.corrupt").exists()


# --- S05-7: a cp1252 file is read, and the next save is UTF-8 ---------------


def test_cp1252_file_is_read_and_saved_back_as_utf8(cfg_dir):
    p = cfg_dir / "config.json"
    p.write_bytes('{"download_folder": "C:\\\\Users\\\\Ren\xe9", "theme": "dark"}'.encode("cp1252"))
    local = cfgmod._read_local_config()
    assert local["download_folder"].endswith("Ren\xe9")
    assert not (cfg_dir / "config.json.corrupt").exists()
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    raw = p.read_bytes()
    assert json.loads(raw.decode("utf-8"))["theme"] == "light"
    assert "Ren\xe9" in raw.decode("utf-8")


# --- torn file: .bak first, else the privacy switches close -----------------


def test_truncated_file_with_good_backup_uses_the_backup(cfg_dir):
    (cfg_dir / "config.json.bak").write_text(
        json.dumps({"theme": "dark", "work_offline": True, "telemetry_opt_in": False}),
        encoding="utf-8",
    )
    (cfg_dir / "config.json").write_text('{"theme": "da', encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"
    assert cfg["work_offline"] is True
    assert cfg["telemetry_opt_in"] is False
    # A second process (or the next launch) sees the same values.
    cfgmod._forget_last_good()
    again = cfgmod.load_config(fetch_online=False)
    assert again["theme"] == "dark" and again["work_offline"] is True
    assert (cfg_dir / "config.json.corrupt").exists()


def test_truncated_file_without_backup_closes_the_switches(cfg_dir):
    (cfg_dir / "config.json").write_text('{"work_offline": fal', encoding="utf-8")
    first = cfgmod.load_config(fetch_online=False)
    assert first["work_offline"] is True
    assert first["telemetry_opt_in"] is False
    assert first["update_check_enabled"] is False
    # After the rename the file is "missing": still closed, in this process,
    # in a second one and for core.offline's own read.
    cfgmod._forget_last_good()
    second = cfgmod.load_config(fetch_online=False)
    assert second["work_offline"] is True and second["telemetry_opt_in"] is False
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
    finally:
        offline.set_offline(False)
    # A save while the evidence exists writes the closed switches explicitly.
    cfgmod.save_config(second)
    disk = _disk(cfg_dir)
    assert disk["work_offline"] is True
    assert disk["telemetry_opt_in"] is False
    assert disk["update_check_enabled"] is False


def test_offline_flag_keeps_its_value_on_a_torn_file(cfg_dir):
    _write(cfg_dir, {"work_offline": True})
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
        (cfg_dir / "config.json").write_text('{"work_offl', encoding="utf-8")
        assert offline.is_offline() is True
    finally:
        offline.set_offline(False)


def test_offline_unknown_at_start_is_offline(cfg_dir, monkeypatch):
    _write(cfg_dir, {"work_offline": False})
    monkeypatch.setattr(offline, "_last_saved", True)
    monkeypatch.setattr(offline, "_cache_key", None, raising=False)
    monkeypatch.setattr(cfgmod, "_READ_RETRY_SECONDS", 0.0)
    fake, _ = _flaky_open("config.json", 10_000)
    monkeypatch.setattr(cfgmod, "open", fake, raising=False)
    offline.set_offline(None)
    try:
        assert offline.is_offline() is True
    finally:
        offline.set_offline(False)


# --- S05-8: privacy switches fail closed ------------------------------------

_CLOSED = {"work_offline": True, "telemetry_opt_in": False, "update_check_enabled": False}


@pytest.mark.parametrize(
    "raw, expect",
    [
        ("true", True), ("false", False), ("True", True), ("FALSE", False),
        ("yes", True), ("no", False), ("on", True), ("off", False),
        ("1", True), ("0", False), (1, True), (0, False), (True, True), (False, False),
        ("junk", None), ("", None), (None, None), ([], None), ({}, None), (float("nan"), None),
    ],
)
@pytest.mark.parametrize("key", sorted(_CLOSED))
def test_privacy_switch_values_are_coerced_and_unknown_is_closed(cfg_dir, key, raw, expect):
    p = cfg_dir / "config.json"
    # NaN cannot come from the file (rejected at parse time); test it in memory.
    if isinstance(raw, float):
        assert offline.coerce_flag(raw, _CLOSED[key]) is _CLOSED[key]
        return
    p.write_text(json.dumps({key: raw, "theme": "dark"}), encoding="utf-8")
    cfg = cfgmod.load_config(fetch_online=False)
    want = _CLOSED[key] if expect is None else expect
    assert cfg[key] is want
    if key == "work_offline":
        assert offline.flag_from({key: raw}) is want


# --- S05-2: os.replace retries a sharing violation -------------------------


def test_save_retries_a_sharing_violation(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    real = os.replace
    state = {"left": 3}

    def flaky(src, dst):  # noqa: ANN001
        if str(dst).endswith("config.json") and state["left"] > 0:
            state["left"] -= 1
            err = PermissionError(13, "Access is denied")
            err.winerror = 5  # type: ignore[attr-defined]
            raise err
        return real(src, dst)

    monkeypatch.setattr(cfgmod.os, "replace", flaky)
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    assert state["left"] == 0
    assert _disk(cfg_dir)["theme"] == "light"


def test_a_lasting_sharing_violation_raises_a_typed_error(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    monkeypatch.setattr(cfgmod, "_REPLACE_RETRY_SECONDS", 0.1)

    def always(src, dst):  # noqa: ANN001
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(cfgmod.os, "replace", always)
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    with pytest.raises(cfgmod.ConfigSaveError):
        cfgmod.save_config(cfg)
    assert not list(cfg_dir.glob(".config-*.tmp"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_save_waits_out_a_real_reader(cfg_dir):
    p = _write(cfg_dir, {"theme": "dark"})
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    reader = open(p, encoding="utf-8")  # noqa: SIM115 - held open on purpose
    timer = threading.Timer(0.2, reader.close)
    timer.start()
    try:
        cfgmod.save_config(cfg)
    finally:
        timer.cancel()
        reader.close()
    assert _disk(cfg_dir)["theme"] == "light"


def test_shrink_guard_raises_instead_of_returning(cfg_dir):
    _write(cfg_dir, {f"k{i}": i for i in range(20)})
    with pytest.raises(cfgmod.ConfigSaveError):
        cfgmod.save_config({"only": 1})
    assert len(_disk(cfg_dir)) == 20


# --- S05-3 / S06-2: merge on save -------------------------------------------


def test_stale_gui_dict_does_not_revert_a_worker_counter(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "cloud_stt_minutes_used": 1.0})
    gui = cfgmod.load_config(fetch_online=False)
    # The worker records minutes in its own process.
    cfgmod.update_config(lambda d: d.__setitem__("cloud_stt_minutes_used", 7.5))
    cfgmod.update_config(lambda d: d.update(gcloud_stt_minutes_used=3.0, gcloud_stt_minutes_month="2026-10"))
    gui["theme"] = "light"
    cfgmod.save_config(gui)  # after a job / at exit
    disk = _disk(cfg_dir)
    assert disk["theme"] == "light"
    assert disk["cloud_stt_minutes_used"] == 7.5
    assert disk["gcloud_stt_minutes_used"] == 3.0
    assert disk["gcloud_stt_minutes_month"] == "2026-10"
    # A second save of the same dict changes nothing it did not change.
    cfgmod.update_config(lambda d: d.__setitem__("cloud_stt_minutes_used", 9.0))
    cfgmod.save_config(gui)
    assert _disk(cfg_dir)["cloud_stt_minutes_used"] == 9.0


def test_a_removed_key_is_removed_on_disk(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "custom_note": "x"})
    cfg = cfgmod.load_config(fetch_online=False)
    del cfg["custom_note"]
    cfgmod.save_config(cfg)
    assert "custom_note" not in _disk(cfg_dir)


def test_a_plain_dict_copy_still_writes_everything(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "cloud_stt_minutes_used": 1.0})
    copy = dict(cfgmod.load_config(fetch_online=False))
    copy["theme"] = "light"
    cfgmod.save_config(copy)
    disk = _disk(cfg_dir)
    assert disk["theme"] == "light"
    assert len(disk) > 20  # today's whole-dict write, never a tiny file


def test_yt_dlp_mode_migration_survives_a_merged_save(cfg_dir):
    _write(cfg_dir, {"theme": "dark", "auto_update_yt_dlp": True})
    cfg = cfgmod.load_config(fetch_online=False)
    assert cfg["yt_dlp_update_mode"] == "auto"
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    disk = _disk(cfg_dir)
    assert "auto_update_yt_dlp" not in disk
    assert disk["yt_dlp_update_mode"] == "auto"


# --- S05-4: online-only keys are not pinned; config_url is the user's own ---


def test_online_model_catalog_is_not_pinned_by_a_save(cfg_dir, monkeypatch):
    _write(cfg_dir, {"theme": "dark"})
    monkeypatch.setattr(cfgmod, "fetch_online_config", lambda *a, **k: {"model_catalog": {"x": {"name": "x"}}})
    cfgmod.refresh_online_config()
    cfg = cfgmod.load_config()
    assert "x" in cfg["model_catalog"]
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    assert "model_catalog" not in _disk(cfg_dir)
    cfgmod.save_config(dict(cfg))  # the whole-dict path too
    assert "model_catalog" not in _disk(cfg_dir)
    cfgmod.refresh_online_config()


def test_a_hand_written_catalog_pin_survives(cfg_dir):
    pin = {"mine": {"name": "mine", "url": "https://example.invalid/m.zip"}}
    _write(cfg_dir, {"theme": "dark", "model_catalog": pin})
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    cfgmod.save_config(dict(cfg))
    assert _disk(cfg_dir)["model_catalog"] == pin


@pytest.mark.parametrize("value", ["", "https://staging.example.invalid/app_config.json"])
def test_users_own_config_url_survives_a_save(cfg_dir, value):
    _write(cfg_dir, {"theme": "dark", "config_url": value})
    cfg = cfgmod.load_config(fetch_online=False)
    cfg["theme"] = "light"
    cfgmod.save_config(cfg)
    assert _disk(cfg_dir)["config_url"] == value
    cfgmod.save_config(dict(cfg))
    assert _disk(cfg_dir)["config_url"] == value


def test_default_config_url_is_never_written(cfg_dir):
    cfg = cfgmod.load_config(fetch_online=False)
    cfgmod.save_config(cfg)
    assert "config_url" not in _disk(cfg_dir)


# --- the hub-folder writer shares the tolerant reader + retrying writer ------


def test_set_local_hub_folder_reads_a_cp1252_file(cfg_dir):
    p = cfg_dir / "config.json"
    p.write_bytes('{"download_folder": "Ren\xe9"}'.encode("cp1252"))
    cfgmod._set_local_hub_folder("D:/hub")
    disk = _disk(cfg_dir)
    assert disk["hub_folder"] == "D:/hub"
    assert disk["download_folder"] == "Ren\xe9"


def test_only_the_config_module_writes_config_json():
    """Every write of config.json goes through core.config's writer."""
    offenders = []
    for root in ("app", "core"):
        for path in (REPO / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name == "config.py" and path.parent.name == "core":
                continue
            if "config_path()" in text and any(
                marker in text for marker in ("os.replace(", '"w"', "'w'", "write_text(")
            ):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
    src = (REPO / "core" / "config.py").read_text(encoding="utf-8")
    # One replace of config.json: inside _replace_with_retry.
    assert src.count("_replace_with_retry(tmp") == 1
    assert "os.replace(tmp" not in src


# --- two real processes ------------------------------------------------------

_CHILD = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import core.config as c
d = Path(sys.argv[2])
c.user_config_dir = lambda: d
c._legacy_config_path = lambda: str(d / "no-legacy.json")
c._legacy_app_dirs = lambda: None
mode, key, n = sys.argv[3], sys.argv[4], int(sys.argv[5])
for i in range(n):
    if mode == "update":
        c.update_config(lambda cfg: cfg.__setitem__(key, int(cfg.get(key, 0)) + 1))
    else:
        cfg = c.load_config(fetch_online=False)
        cfg[key] = i + 1
        c.save_config(cfg)
"""


def _run_children(cfg_dir: Path, args: list[tuple[str, str, int]]) -> None:
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(REPO), str(cfg_dir), mode, key, str(n)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        for mode, key, n in args
    ]
    errors = []
    for p in procs:
        _, err = p.communicate(timeout=240)
        if p.returncode != 0:
            errors.append(err.decode("utf-8", "replace")[-2000:])
    assert errors == []


def test_two_processes_increment_without_losing_one(cfg_dir):
    _write(cfg_dir, {"theme": "dark"})
    _run_children(cfg_dir, [("update", "n", 50), ("update", "n", 50)])
    assert _disk(cfg_dir)["n"] == 100


def test_two_processes_saving_disjoint_keys_keep_both(cfg_dir):
    _write(cfg_dir, {"theme": "dark"})
    _run_children(cfg_dir, [("save", "a", 30), ("save", "b", 30)])
    disk = _disk(cfg_dir)
    assert disk["a"] == 30 and disk["b"] == 30
    assert disk["theme"] == "dark"


def test_a_held_lock_delays_but_never_blocks_a_save(cfg_dir, monkeypatch, caplog):
    _write(cfg_dir, {"theme": "dark"})
    monkeypatch.setattr(cfgmod, "_LOCK_DEADLINE_SECONDS", 0.2)
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(REPO), str(cfg_dir / "config.json.lock")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == b"locked"
        cfg = cfgmod.load_config(fetch_online=False)
        cfg["theme"] = "light"
        t0 = time.monotonic()
        with caplog.at_level("WARNING", logger="core.config"):
            cfgmod.save_config(cfg)
        assert time.monotonic() - t0 < 5
        assert _disk(cfg_dir)["theme"] == "light"
        assert any("lock" in r.getMessage().lower() for r in caplog.records)
    finally:
        holder.kill()
        holder.wait(timeout=30)


_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
fh = open(sys.argv[2], "a+b")
if sys.platform == "win32":
    import msvcrt
    fh.seek(0)
    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
print("locked", flush=True)
time.sleep(60)
"""


# --- item 11: .whisperproject.json size cap ----------------------------------


def test_oversized_project_file_is_refused_fast(tmp_path, caplog):
    proj = tmp_path / "proj"
    proj.mkdir()
    big = proj / cfgmod.PROJECT_FILE_NAME
    with open(big, "w", encoding="utf-8") as f:
        f.write('{"initial_prompt": "')
        f.write("x" * (2 * 1024 * 1024))
        f.write('"}')
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="core.config"):
        assert cfgmod.load_project_overrides(proj / "media.mp4") == {}
    assert time.monotonic() - t0 < 1.0
    assert any("too large" in r.getMessage() for r in caplog.records)
    assert all("xxxx" not in r.getMessage() for r in caplog.records)


def test_small_project_file_still_applies(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / cfgmod.PROJECT_FILE_NAME).write_text('{"initial_prompt": "hi"}', encoding="utf-8")
    assert cfgmod.load_project_overrides(proj / "media.mp4") == {"initial_prompt": "hi"}
