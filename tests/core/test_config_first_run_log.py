"""First run: a missing config.json is logged once per path, at INFO; a corrupt one still warns."""
import os

from core.config import config_path, load_config


def test_first_run_log_once_at_info(caplog):
    caplog.set_level("INFO")
    # Ensure missing file on fresh run
    assert not os.path.exists(config_path())
    
    # Run load_config twice
    load_config(fetch_online=False)
    load_config(fetch_online=False)
    
    # Check logs
    info_records = [r for r in caplog.records if r.levelname == "INFO" and "config.json not found" in r.message]
    warn_records = [r for r in caplog.records if r.levelname == "WARNING" and "config.json not found" in r.message]
    
    assert len(warn_records) == 0, f"Expected 0 WARNINGs, got {len(warn_records)}: {warn_records}"
    assert len(info_records) == 1, f"Expected exactly 1 INFO, got {len(info_records)}: {info_records}"

def test_corrupt_file_still_logs_warning_or_error(caplog):
    caplog.set_level("INFO")
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{invalid_json:")
    
    load_config(fetch_online=False)
    
    warn_error_records = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR") and "config.json" in r.message]
    assert len(warn_error_records) > 0, "Expected WARNING or ERROR for corrupt config"

def test_first_run_log_second_path_logs_again(caplog, monkeypatch):
    caplog.set_level("INFO")
    
    load_config(fetch_online=False)
    
    # Change path
    original_config_path = config_path()
    new_path = original_config_path + "_second"
    monkeypatch.setattr("core.config.config_path", lambda: new_path)
    
    load_config(fetch_online=False)
    
    info_records = [r for r in caplog.records if r.levelname == "INFO" and "config.json not found" in r.message]
    assert len(info_records) == 2, f"Expected 2 INFOs (one for each path), got {len(info_records)}: {info_records}"
