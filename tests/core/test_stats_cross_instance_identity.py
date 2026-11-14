"""A second app cannot send an identity replaced by another instance."""
import json
import uuid
import pytest
from core import config, offline, stats


@pytest.mark.parametrize("saved_id", ["rotated", "erased", "same", "changed-during-send"])
def test_sender_rechecks_shared_profile_identity(tmp_path, monkeypatch, saved_id):
    old = str(uuid.uuid4())
    current = old if saved_id in ("same", "changed-during-send") else (str(uuid.uuid4()) if saved_id == "rotated" else "")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"telemetry_opt_in": True, "install_id": current}), encoding="utf-8")
    pending, posted = [], []
    class Deferred:
        def __init__(self, target, args=(), **kwargs):
            pending.append(lambda: target(*args))
        def start(self):
            pass
    monkeypatch.setattr(stats.threading, "Thread", Deferred)
    monkeypatch.setattr(offline, "is_offline", lambda: False)
    monkeypatch.setattr(config, "config_path", lambda: str(path))
    monkeypatch.setattr(stats, "_post", lambda u, row, t: posted.append(dict(row)))
    def normalise(value):
        if saved_id == "changed-during-send":
            path.write_text(json.dumps({"telemetry_opt_in": True, "install_id": str(uuid.uuid4())}), encoding="utf-8")
        return "base"
    monkeypatch.setattr(stats, "public_model_name", normalise)
    cfg = {"telemetry_opt_in": True, "install_id": old, "stats_url": "https://example.invalid/v1/runs"}
    assert stats.post_stats_async(cfg, {"status": "finished", "model": "base", "install_id": old})
    pending[0]()
    assert bool(posted) is (saved_id == "same")


@pytest.mark.parametrize("state", ["malformed", "oversized", "unreadable", "missing"])
def test_saved_identity_read_failures_and_new_profile(tmp_path, monkeypatch, state):
    path = tmp_path / "config.json"
    identity = str(uuid.uuid4())
    if state != "missing":
        path.write_text("{" if state != "oversized" else " " * (1024 * 1024 + 1), encoding="utf-8")
    if state == "unreadable":
        from pathlib import Path
        original = Path.open
        def open_file(p, *args, **kwargs):
            if p == path:
                raise PermissionError("synthetic sharing denial")
            return original(p, *args, **kwargs)
        monkeypatch.setattr(Path, "open", open_file)
    assert stats._saved_identity_matches(path, identity) is (state == "missing")
