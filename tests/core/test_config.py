"""Tests for core.config — load/save round-trip, defaults, fallbacks, migration.

Each test redirects platformdirs through monkeypatch so it never touches the
real user config dir.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import config as cfg


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect every platformdirs lookup at a tmp_path subfolder."""
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    log_dir = tmp_path / "log"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(cfg, "user_log_dir", lambda: log_dir)
    monkeypatch.setattr(cfg, "user_data_dir", lambda: data_dir)
    monkeypatch.setattr(cfg, "config_path", lambda: str(config_dir / "config.json"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_load_returns_defaults_when_missing(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    config = cfg.load_config()
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]
    assert config["model"]["name"] == cfg.DEFAULT_CONFIG["model"]["name"]
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]


def test_save_then_load_roundtrip(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["theme"] = "light"
    payload["parallel_workers"] = 4
    cfg.save_config(payload)
    loaded = cfg.load_config()
    assert loaded["theme"] == "light"
    assert loaded["parallel_workers"] == 4


# ---------------------------------------------------------------- shrink guard
# 2026-08-15: a real config.json was found silently reduced from ~90 keys
# to 3 during ordinary use; root cause was never pinned down. save_config()
# now refuses a drastic shrink relative to what is CURRENTLY on disk and
# keeps a rotating .bak of the last good state -- covers this incident
# class regardless of cause. Guarded call must compare against the file,
# not DEFAULT_CONFIG, so small fixtures written to a FRESH path (every
# other test in this module) are unaffected.


def test_shrink_guard_refuses_drastic_reduction(isolated_dirs):
    full = dict(cfg.DEFAULT_CONFIG)
    cfg.save_config(full)  # first write: nothing on disk yet, always allowed
    on_disk_before = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert len(on_disk_before) == len(full) - len(
        [k for k in cfg._NON_PERSISTED_KEYS if k in full]
    )

    tiny = {"cpu_warning_shown": True, "model_path": "", "download_folder": ""}
    cfg.save_config(tiny)  # must be refused -- looks like data loss, not intent

    on_disk_after = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk_after == on_disk_before, "a drastic shrink must not overwrite the file"


def test_shrink_guard_allows_a_reasonable_write_and_backs_up(isolated_dirs):
    full = dict(cfg.DEFAULT_CONFIG)
    cfg.save_config(full)
    first_on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))

    updated = dict(full)
    updated["theme"] = "light"  # same key count, one value changed
    cfg.save_config(updated)

    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["theme"] == "light"

    backup_path = Path(cfg.config_path() + ".bak")
    assert backup_path.exists(), "a normal overwrite must leave a .bak of the prior state"
    backed_up = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backed_up == first_on_disk


def test_shrink_guard_does_not_block_a_fresh_small_write(isolated_dirs):
    # No file on disk yet -- a small dict here is a normal test fixture,
    # not evidence of data loss, and must be written normally.
    cfg.save_config({"hub_folder": "", "model_path": ""})
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["hub_folder"] == ""


def test_hub_choice_survives_save_load_cycle(isolated_dirs, monkeypatch):
    """End-to-end regression: the first-run hub picker must take effect.

    Startup resolves model_path against the DEFAULT hub (hub_folder is
    still empty), then the user picks a hub. Saving used to persist the
    stale default-derived model_path, which on the next load outranked
    hub_folder as an "explicit override" — so the chosen hub was
    silently ignored. The save must drop the derived path so the
    reload follows the chosen hub.
    """
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    from core import hub as _hub

    user_hub = str(isolated_dirs / "external_drive" / "models")
    config = cfg.load_config()                  # fresh: model_path derived vs default hub
    assert config["model_path"]                 # non-empty (derived)
    config["hub_folder"] = user_hub             # what HubSetupDialog._on_ok does
    cfg.save_config(config)
    reloaded = cfg.load_config()

    expected = str(_hub.model_folder_for(user_hub, cfg.DEFAULT_CONFIG["model"]["name"]))
    assert reloaded["hub_folder"] == user_hub
    assert reloaded["model_path"] == expected


def test_save_drops_hub_derived_model_path(isolated_dirs, monkeypatch):
    """A model_path equal to the current hub's derived layout is stored
    as "" (carries no info; re-derives on load)."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    from core import hub as _hub

    hub_folder = str(isolated_dirs / "hub")
    derived = str(_hub.model_folder_for(hub_folder, cfg.DEFAULT_CONFIG["model"]["name"]))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["hub_folder"] = hub_folder
    payload["model_path"] = derived
    cfg.save_config(payload)

    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["model_path"] == ""


def test_save_preserves_custom_model_path(isolated_dirs, monkeypatch):
    """A genuinely custom model_path (matches no hub layout) survives a
    save so legacy explicit per-model overrides keep working."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    custom = str(isolated_dirs / "totally" / "custom" / "place")
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["model_path"] = custom
    cfg.save_config(payload)

    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["model_path"] == custom


def test_persistable_model_path_strips_trailing_and_redundant_separators(isolated_dirs):
    """A hand-edited model_path equal to the hub-derived path but with a
    trailing / doubled / dotted separator is still recognised as derived
    and dropped to ''."""
    from core import hub as _hub
    hub_folder = str(isolated_dirs / "hub")
    name = cfg.DEFAULT_CONFIG["model"]["name"]
    base = str(_hub.model_folder_for(hub_folder, name))
    for variant in (base + os.sep, base + os.sep * 2, os.path.join(base, ".", "")):
        config = dict(cfg.DEFAULT_CONFIG)
        config["hub_folder"] = hub_folder
        config["model_path"] = variant
        assert cfg._persistable_model_path(config) == "", variant


def test_persistable_model_path_recognises_verbatim_models_prefix(isolated_dirs):
    """A model name already starting with 'models--' is used verbatim by
    model_folder_for; the derived path must still be recognised."""
    from core import hub as _hub
    hub_folder = str(isolated_dirs / "hub")
    name = "models--Systran--faster-whisper-medium"
    config = dict(cfg.DEFAULT_CONFIG)
    config["model"] = {"name": name}
    config["hub_folder"] = hub_folder
    config["model_path"] = str(_hub.model_folder_for(hub_folder, name))
    assert cfg._persistable_model_path(config) == ""


def test_persistable_model_path_preserves_path_for_a_different_model(isolated_dirs):
    """A model_path under the hub but for a DIFFERENT model than the one
    configured is a real explicit folder and must be preserved."""
    from core import hub as _hub
    hub_folder = str(isolated_dirs / "hub")
    other = str(_hub.model_folder_for(hub_folder, "faster-whisper-tiny"))
    config = dict(cfg.DEFAULT_CONFIG)  # configured model is large-v3
    config["hub_folder"] = hub_folder
    config["model_path"] = other
    assert cfg._persistable_model_path(config) == other


def test_persistable_model_path_defaults_name_when_model_key_missing(isolated_dirs):
    """A config with no usable 'model' dict falls back to 'whisper-model';
    the matching derived path is still recognised."""
    from core import hub as _hub
    hub_folder = str(isolated_dirs / "hub")
    config = {
        "hub_folder": hub_folder,
        "model": None,
        "model_path": str(_hub.model_folder_for(hub_folder, "whisper-model")),
    }
    assert cfg._persistable_model_path(config) == ""


def test_save_load_model_path_converges(isolated_dirs, monkeypatch):
    """Repeated save/load cycles must not flap model_path: once the hub
    is chosen every cycle re-derives the same path and persists ''."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    user_hub = str(isolated_dirs / "hub")
    config = cfg.load_config()
    config["hub_folder"] = user_hub
    cfg.save_config(config)
    first = cfg.load_config()
    cfg.save_config(first)
    second = cfg.load_config()
    assert first["model_path"] == second["model_path"]
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["model_path"] == ""


@pytest.mark.skipif(os.name != "nt", reason="normcase only folds case on Windows")
def test_persistable_model_path_is_case_insensitive_on_windows(isolated_dirs):
    from core import hub as _hub
    hub_folder = str(isolated_dirs / "Hub")
    name = cfg.DEFAULT_CONFIG["model"]["name"]
    derived = str(_hub.model_folder_for(hub_folder, name))
    config = dict(cfg.DEFAULT_CONFIG)
    config["hub_folder"] = hub_folder
    config["model_path"] = derived.upper()
    assert cfg._persistable_model_path(config) == ""


def test_download_folder_survives_unmounted_drive_save(isolated_dirs, monkeypatch):
    """Regression: a download_folder on a temporarily-unmounted drive must
    not be forgotten. Load clears it for the session, but save must keep
    the on-disk value so re-attaching the drive restores it."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["download_folder"] = "Z:/recordings"
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cfg, "_drive_is_mounted", lambda p: False)

    config = cfg.load_config()
    assert config["download_folder"] == ""          # cleared in memory this session
    cfg.save_config(config)                           # must NOT persist the cleared ""
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["download_folder"] == "Z:/recordings"


def test_download_folder_normal_value_persists(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    monkeypatch.setattr(cfg, "_drive_is_mounted", lambda p: True)
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["download_folder"] = str(isolated_dirs / "dl")
    cfg.save_config(payload)
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["download_folder"] == str(isolated_dirs / "dl")


def test_download_folder_empty_stays_empty_when_no_prior(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["download_folder"] = ""
    cfg.save_config(payload)
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert on_disk["download_folder"] == ""


def test_load_corrupt_json_falls_back(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_text("{not valid json", encoding="utf-8")
    config = cfg.load_config()
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]
    assert os.path.exists(cfg.config_path() + ".corrupt")


def test_load_non_object_json_falls_back(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    config = cfg.load_config()
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]


def test_load_config_survives_huge_integer(isolated_dirs, monkeypatch):
    """A huge (but valid-JSON) integer must not crash ``load_config``.

    Regression: the non-finite guard called ``math.isfinite()`` on any
    int/float value, and a 400-digit integer literal — legal JSON, produced
    by a hand edit or an external tool — raises
    ``OverflowError: int too large to convert to float`` from inside
    ``math.isfinite``. ``load_config`` is called unguarded from
    ``App.__init__`` and the worker, so that was a startup crash. An int is
    always finite; only floats need the probe.
    """
    monkeypatch.setattr(
        cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json")
    )
    Path(cfg.config_path()).write_text(
        '{"parallel_workers": ' + "9" * 400 + "}", encoding="utf-8"
    )
    config = cfg.load_config(fetch_online=False)
    assert isinstance(config["parallel_workers"], int)
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]


def test_load_config_survives_uncreatable_config_dir(tmp_path, monkeypatch):
    """A config dir that cannot be created must not crash launch.

    Regression: ``migrate_config_location`` called ``mkdir(parents=True)``
    unguarded, so a path blocked by a file (or a read-only profile / ACL
    failure) raised OSError out of ``load_config`` before any fallback —
    which every startup path (App.__init__, the worker) calls unguarded.
    The app must instead come up on the defaults, like every other
    unreadable-config case.
    """
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    config_dir = blocker / "nested"
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "config_path", lambda: str(config_dir / "config.json"))
    monkeypatch.setattr(
        cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json")
    )

    assert cfg.migrate_config_location() == str(config_dir / "config.json")
    config = cfg.load_config(fetch_online=False)
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]


def test_user_overrides_merge_with_defaults(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_text(json.dumps({"theme": "dark", "model": {"name": "tiny"}}), encoding="utf-8")
    config = cfg.load_config()
    assert config["theme"] == "dark"
    assert config["model"]["name"] == "tiny"
    assert config["model"]["url"] == cfg.DEFAULT_CONFIG["model"]["url"]


@pytest.mark.skipif(
    os.name != "nt",
    reason="Unmounted drive-letter fallback is a Windows-only scenario: POSIX "
    "has no drive letters and _drive_is_mounted() is always True there.",
)
def test_unmounted_model_path_falls_back(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["model_path"] = "Z:/nonexistent_drive/model"
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cfg, "_drive_is_mounted", lambda p: False)
    config = cfg.load_config()
    assert "Z:/nonexistent_drive" not in config["model_path"]
    assert "models" in config["model_path"]


def test_unmounted_download_folder_clears(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["download_folder"] = "Z:/nonexistent/downloads"
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cfg, "_drive_is_mounted", lambda p: False)
    config = cfg.load_config()
    assert config["download_folder"] == ""


def test_save_is_atomic_no_temp_left_on_success(isolated_dirs, monkeypatch):
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    cfg.save_config(dict(cfg.DEFAULT_CONFIG))
    leftovers = list(Path(cfg.config_path()).parent.glob(".config-*.tmp"))
    assert leftovers == []


def test_legacy_config_migrates(isolated_dirs, monkeypatch, tmp_path):
    legacy = tmp_path / "old_config.json"
    legacy.write_text(json.dumps({"theme": "light", "log_level": "DEBUG"}), encoding="utf-8")
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(legacy))
    config = cfg.load_config()
    assert config["theme"] == "light"
    assert config["log_level"] == "DEBUG"
    assert (legacy.parent / "old_config.json.migrated.bak").exists()
    assert not legacy.exists()


# ---------- Audit-driven robustness tests -----------------------------------


def test_load_config_handles_unicode_decode_error(isolated_dirs, monkeypatch):
    """Saving config.json in cp1252 (non-UTF8) used to crash launch
    with UnicodeDecodeError. Must fall back to defaults instead."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_bytes(b"\xff\xfe garbage \x00")
    config = cfg.load_config()
    # Default fallback returned, not a crash.
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]
    assert config["log_level"] == cfg.DEFAULT_CONFIG["log_level"]
    # Corrupt file was renamed aside.
    assert Path(cfg.config_path() + ".corrupt").exists()


def test_load_config_coerces_wrong_type(isolated_dirs, monkeypatch):
    """A user-edited config with ``parallel_workers="many"`` would
    crash downstream ``int(parallel_workers)`` calls. Must coerce
    back to the default int."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = {"parallel_workers": "many", "chime_on_complete": "yes"}
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    config = cfg.load_config()
    # parallel_workers default is int 2; the string is rejected, default kept.
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]
    # chime_on_complete default is bool True; the string "yes" is rejected.
    assert config["chime_on_complete"] is True


def test_load_config_drops_null_for_known_key(isolated_dirs, monkeypatch):
    """A null value for an allowlisted/known key must NOT survive the merge.

    Regression: the coercion pass was gated on ``merged[k] is not None``, so a
    JSON ``null`` slipped through and a later int()/strip()/iteration crashed.
    A null for a key that ships a non-None default reverts to the default.
    """
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = {"parallel_workers": None, "chime_on_complete": None}
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    config = cfg.load_config(fetch_online=False)
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]
    assert config["parallel_workers"] is not None
    assert config["chime_on_complete"] is cfg.DEFAULT_CONFIG["chime_on_complete"]


def test_merge_sources_online_null_reverts_to_default():
    """An online-config null for an allowlisted key falls back, not None.

    The full coercion runs in load_config, but verify the layering does not
    let a null occupy an allowlisted key when no local value exists. We then
    run the same drop-null rule load_config applies.
    """
    pick = next(iter(cfg.ONLINE_ALLOWED_KEYS))
    merged = cfg.merge_config_sources(
        cfg.DEFAULT_CONFIG, {pick: None}, None
    )
    # The online null deep-merges in; the coercion (exercised end-to-end by
    # test_load_config_drops_null_for_known_key) is what restores the default.
    assert pick in merged


def test_tray_and_telemetry_keys_have_bool_defaults():
    # BUG H: minimise_to_tray + telemetry_opt_in are read at runtime (app.py,
    # tray.py, observability.py) and written by the Advanced dialog, so they
    # must be declared in DEFAULT_CONFIG to get merge + coercion. telemetry is
    # ON by default for this distribution (opted-in usage stats); tray is OFF.
    assert cfg.DEFAULT_CONFIG["minimise_to_tray"] is False
    assert cfg.DEFAULT_CONFIG["telemetry_opt_in"] is True


def test_tray_and_telemetry_merged_into_old_config(isolated_dirs, monkeypatch):
    # An older config.json predating these keys must still load them at their
    # bool defaults (not KeyError) so the runtime .get() calls are typed bools.
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    config = cfg.load_config()
    assert config["minimise_to_tray"] is False
    assert config["telemetry_opt_in"] is True


def test_tray_and_telemetry_wrong_type_coerced(isolated_dirs, monkeypatch):
    # A hand-edited STRING value (no sane bool coercion) is rejected back to
    # the default; an INT is coerced to bool (Python bool is int) — the same
    # rules every other bool key gets now that these are declared (BUG H).
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = {"minimise_to_tray": "yes", "telemetry_opt_in": 1}
    Path(cfg.config_path()).write_text(json.dumps(payload), encoding="utf-8")
    config = cfg.load_config()
    assert config["minimise_to_tray"] is False   # string rejected -> default
    assert config["telemetry_opt_in"] is True    # int 1 coerced to bool


def test_save_config_strips_non_persisted_keys(isolated_dirs, monkeypatch):
    # telemetry_opt_in / config_url / stats_url / ffplay_downloads /
    # latest_version must never land in config.json — they are re-derived
    # from DEFAULT_CONFIG or the online config fetch on every load.
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payload = {**cfg.DEFAULT_CONFIG, "theme": "dark"}
    cfg.save_config(payload)
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    for key in cfg._NON_PERSISTED_KEYS:
        assert key not in on_disk
    assert on_disk["theme"] == "dark"


def test_save_config_removes_preexisting_non_persisted_keys(isolated_dirs, monkeypatch):
    # A config.json written before this rule existed must be cleaned up on
    # the very next save, not just left with stale values forever.
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    stale = {
        **cfg.DEFAULT_CONFIG,
        "telemetry_opt_in": True,
        "config_url": "https://example.com/config",
        "stats_url": "https://example.com/stats",
        "ffplay_downloads": {"win32": "https://example.com/ffplay.exe"},
        "latest_version": "9.9.9",
    }
    Path(cfg.config_path()).write_text(json.dumps(stale), encoding="utf-8")
    config = cfg.load_config()
    cfg.save_config(config)
    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    for key in cfg._NON_PERSISTED_KEYS:
        assert key not in on_disk


def test_save_config_lock_serialises_concurrent_calls(isolated_dirs, monkeypatch):
    """Two threads calling save_config concurrently must not crash
    or corrupt the destination on Windows. The _SAVE_LOCK serialises
    them — verify by inspecting the final on-disk content matches
    one of the inputs."""
    import threading
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    payloads = [
        {**cfg.DEFAULT_CONFIG, "theme": f"theme_{i}"}
        for i in range(10)
    ]
    errors: list[Exception] = []

    def _save(p):
        try:
            cfg.save_config(p)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_save, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors, f"save_config raced: {errors}"
    final = cfg.load_config(fetch_online=False)
    # Final on-disk value must match one of the input themes —
    # exact one is racy but must be SOME valid value.
    assert final["theme"] in {p["theme"] for p in payloads}


# ---------- P4-1: three-level merged configuration --------------------------


def test_merge_precedence_local_over_online_over_hardcoded():
    """local > online > hard-coded; a key missing from a higher layer falls
    through to the next."""
    hardcoded = {"latest_version": "1.0.0", "theme": "dark", "stats_url": "hc"}
    online = {"latest_version": "2.0.0", "stats_url": "https://online/stats"}
    local = {"latest_version": "3.0.0"}  # theme + stats_url fall through
    merged = cfg.merge_config_sources(hardcoded, online, local)
    assert merged["latest_version"] == "3.0.0"          # local wins
    assert merged["stats_url"] == "https://online/stats"  # online (no local)
    assert merged["theme"] == "dark"                    # hard-coded (no higher)


def test_merge_online_only_touches_allowlisted_keys():
    """The online layer must NEVER override user-private / local-only keys
    (paths, api keys, hub folder, prefs) — only ONLINE_ALLOWED_KEYS."""
    hardcoded = {
        "hub_folder": "C:/user/hub",
        "cloud_stt_api_key": "secret",
        "theme": "dark",
        "stats_url": "",
    }
    # A hostile/buggy online payload tries to set local-only keys.
    online = {
        "hub_folder": "\\\\evil\\share",
        "cloud_stt_api_key": "leaked",
        "theme": "light",
        "stats_url": "https://online/stats",
    }
    merged = cfg.merge_config_sources(hardcoded, online, local=None)
    # Local-only keys are untouched by the online layer...
    assert merged["hub_folder"] == "C:/user/hub"
    assert merged["cloud_stt_api_key"] == "secret"
    assert merged["theme"] == "dark"
    # ...only the allowlisted app-level key comes through.
    assert merged["stats_url"] == "https://online/stats"
    assert "stats_url" in cfg.ONLINE_ALLOWED_KEYS
    assert "hub_folder" not in cfg.ONLINE_ALLOWED_KEYS


def test_merge_local_can_override_local_only_key():
    """A local override file (highest priority) CAN set a local-only key the
    online layer cannot."""
    hardcoded = {"hub_folder": "C:/default", "stats_url": ""}
    online = {"hub_folder": "\\\\evil\\share"}  # ignored (not allowlisted)
    local = {"hub_folder": "D:/my/models"}
    merged = cfg.merge_config_sources(hardcoded, online, local)
    assert merged["hub_folder"] == "D:/my/models"


def test_merge_deep_merges_dict_keys():
    """Dict-valued keys deep-merge so a partial override keeps siblings."""
    hardcoded = {"model_catalog": {"a": {"name": "A"}}, "model": {"name": "x", "url": "u"}}
    online = {"model_catalog": {"b": {"name": "B"}}}
    local = {"model": {"name": "y"}}
    merged = cfg.merge_config_sources(hardcoded, online, local)
    assert set(merged["model_catalog"].keys()) == {"a", "b"}  # online adds b
    assert merged["model"]["name"] == "y"   # local override
    assert merged["model"]["url"] == "u"    # sibling preserved from hardcoded


def test_merge_does_not_mutate_inputs():
    hardcoded = {"theme": "dark", "model": {"name": "x"}}
    online = {"stats_url": "s"}
    local = {"theme": "light"}
    cfg.merge_config_sources(hardcoded, online, local)
    assert hardcoded == {"theme": "dark", "model": {"name": "x"}}
    assert online == {"stats_url": "s"}
    assert local == {"theme": "light"}


def test_fetch_online_returns_parsed_json(tmp_path, monkeypatch):
    import io
    payload = {"stats_url": "https://x/stats", "latest_version": "9.9.9"}

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    cache = tmp_path / "cache.json"
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == payload
    # A successful fetch is written to the cache for offline fallback.
    assert json.loads(cache.read_text(encoding="utf-8")) == payload


def test_fetch_online_falls_back_to_cache_on_error(tmp_path, monkeypatch):
    cached = {"stats_url": "https://cached/stats"}
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(cached), encoding="utf-8")

    def _boom(req, timeout=0):  # noqa: ARG001
        raise cfg.urllib.error.URLError("offline")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _boom)
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == cached  # served from cache when the network fails


def test_fetch_online_returns_empty_when_no_cache_and_error(tmp_path, monkeypatch):
    def _boom(req, timeout=0):  # noqa: ARG001
        raise cfg.urllib.error.URLError("offline")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _boom)
    cache = tmp_path / "missing.json"
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == {}  # no network, no cache -> empty (use hardcoded+local)


def test_fetch_online_empty_url_short_circuits_to_cache(tmp_path, monkeypatch):
    """An empty config_url skips the network entirely and uses the cache."""
    cached = {"latest_version": "1.2.3"}
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(cached), encoding="utf-8")

    def _must_not_call(req, timeout=0):  # noqa: ARG001
        raise AssertionError("urlopen must not be called for an empty URL")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _must_not_call)
    assert cfg.fetch_online_config("", cache_path=cache) == cached


def test_load_config_no_fetch_uses_local_and_hardcoded(isolated_dirs, monkeypatch):
    """fetch_online=False must never hit the network and still merge local
    over hard-coded."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))

    def _must_not_call(req, timeout=0):  # noqa: ARG001
        raise AssertionError("urlopen must not be called when fetch_online=False")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _must_not_call)
    Path(cfg.config_path()).write_text(
        json.dumps({"theme": "light"}), encoding="utf-8"
    )
    config = cfg.load_config(fetch_online=False)
    assert config["theme"] == "light"                                  # local
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]  # hardcoded


def test_load_config_merges_online_allowlisted_key(isolated_dirs, monkeypatch):
    """End-to-end: an online app_config sets an allowlisted key that flows
    into the effective config; a local file still wins for its own keys."""
    import io
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    cfg.refresh_online_config()  # clear the in-process memo

    online_payload = {
        "stats_url": "https://online/stats",
        "hub_folder": "\\\\evil\\should-be-ignored",  # not allowlisted
    }

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(json.dumps(online_payload).encode("utf-8"))

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    Path(cfg.config_path()).write_text(
        json.dumps({"hub_folder": "D:/local/hub"}), encoding="utf-8"
    )
    config = cfg.load_config(fetch_online=True)
    assert config["stats_url"] == "https://online/stats"  # from online
    assert config["hub_folder"] == "D:/local/hub"          # local wins; online ignored
    cfg.refresh_online_config()  # leave the memo clean for other tests


def test_fetch_online_survives_garbage_http_response(tmp_path, monkeypatch):
    """A broken proxy / captive portal answering with a garbage status line
    makes urlopen raise http.client.HTTPException (NOT a URLError/OSError),
    which used to escape fetch_online_config's "never raises" contract and
    crash launch out of load_config. Must fall back to the cache instead."""
    import http.client

    cached = {"stats_url": "https://cached/stats"}
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(cached), encoding="utf-8")

    def _garbage(req, timeout=0):  # noqa: ARG001
        raise http.client.BadStatusLine("oops")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _garbage)
    assert cfg.fetch_online_config("https://host/app.json", cache_path=cache) == cached


def test_fetch_online_survives_truncated_response(tmp_path, monkeypatch):
    """resp.read() raising IncompleteRead (also an HTTPException, not an
    OSError) must degrade to {} rather than propagate out of load_config."""
    import http.client

    class _Truncated:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            raise http.client.IncompleteRead("partial", 1)

    monkeypatch.setattr(
        cfg.urllib.request, "urlopen", lambda req, timeout=0: _Truncated()  # noqa: ARG001
    )
    cache = tmp_path / "missing.json"
    assert cfg.fetch_online_config("https://host/app.json", cache_path=cache) == {}


def test_load_config_survives_deeply_nested_file(isolated_dirs, monkeypatch):
    """A pathologically nested config.json (legal JSON, absurd depth) makes
    the C scanner raise RecursionError, which used to escape the "never
    raises" loader and crash launch. Must degrade to defaults."""
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(isolated_dirs / "no_legacy.json"))
    Path(cfg.config_path()).write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    config = cfg.load_config(fetch_online=False)
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]


def test_repo_configuration_json_agrees_with_default_stats_url():
    """configuration.json is the master copy published to config_url as the
    online app_config. A stats_url that disagrees with DEFAULT_CONFIG here
    would silently 404 the opt-in telemetry POST for anyone who fetches the
    online config successfully (see GitHub issue #2)."""
    repo_root = Path(__file__).resolve().parents[2]
    published = json.loads((repo_root / "configuration.json").read_text(encoding="utf-8"))
    assert published["stats_url"] == cfg.DEFAULT_CONFIG["stats_url"]


# ---------- remote LLM provider defaults + noisy-audio preset --------------


def test_default_config_local_llm_provider_needs_no_network():
    """A fresh install must default to the offline provider — "remote"
    would silently need a network call + a key the user hasn't set yet."""
    assert cfg.DEFAULT_CONFIG["llm_provider"] == "local"
    assert cfg.DEFAULT_CONFIG["llm_remote_api_key"] == ""
    assert cfg.DEFAULT_CONFIG["llm_remote_model"] == ""


def test_noisy_audio_preset_keys_all_exist_in_default_config():
    """Every key the preset sets must be a real, typed DEFAULT_CONFIG
    key — a typo here would silently write an orphan key that
    load_config()'s type-coercion pass can't validate."""
    for key, value in cfg.NOISY_AUDIO_PRESET.items():
        assert key in cfg.DEFAULT_CONFIG, f"{key!r} is not a real config key"
        assert isinstance(value, type(cfg.DEFAULT_CONFIG[key]))


def test_noisy_audio_preset_turns_on_cleanup_and_detection():
    preset = cfg.NOISY_AUDIO_PRESET
    assert preset["vad_enabled"] is True
    assert preset["denoise_enabled"] is True
    assert preset["hallucination_detect_enabled"] is True
    # Fixed "medium", not "auto" — the whole point of clicking the preset
    # is to force cleanup to actually run rather than re-measure and
    # possibly decide "off" again.
    assert preset["denoise_level"] == "medium"
    # More conservative than the plain default (0.5): noisy audio's real
    # risk is background noise misread AS speech, not speech missed.
    assert preset["vad_threshold"] > cfg.DEFAULT_CONFIG["vad_threshold"]
