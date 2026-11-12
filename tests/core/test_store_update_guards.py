"""Store update entry points must refuse work before network or disk probes."""
from unittest.mock import Mock

import pytest

from core import distribution, updates, yt_dlp_update


@pytest.fixture
def store_mode(monkeypatch):
    monkeypatch.setattr(distribution, "is_store_build", lambda: True)


def test_store_disables_automatic_update_checks(store_mode):
    assert not updates.automatic_check_enabled({"update_check_enabled": True}, {})


def test_store_manual_check_never_requests_release_metadata(store_mode, monkeypatch):
    network = Mock(side_effect=AssertionError("Store update network must be unreachable"))
    monkeypatch.setattr(updates, "urlopen_https_only", network)
    assert updates.check_for_update() is None
    network.assert_not_called()


def test_store_downloader_update_capability_has_no_tool_probe(store_mode, monkeypatch):
    probe = Mock(side_effect=AssertionError("Store updater must not probe executables"))
    monkeypatch.setattr(yt_dlp_update, "bundled_binary", probe)
    assert not yt_dlp_update.can_self_update()
    probe.assert_not_called()


def test_store_direct_downloader_update_has_no_tool_or_cache_work(store_mode, monkeypatch):
    probe = Mock(side_effect=AssertionError("Store updater must not touch tools"))
    monkeypatch.setattr(yt_dlp_update, "bundled_binary", probe)
    result = yt_dlp_update.update_cached_copy()
    assert result.status == "unsupported"
    probe.assert_not_called()


def test_store_update_cache_refresh_has_no_cleanup_or_probe(store_mode, monkeypatch):
    cleanup = Mock(side_effect=AssertionError("Store updater must not prune tool copies"))
    monkeypatch.setattr(yt_dlp_update, "prune_old_installs", cleanup)
    assert not yt_dlp_update.refresh_state_if_stale()
    cleanup.assert_not_called()


def test_direct_build_keeps_automatic_check_setting(monkeypatch):
    monkeypatch.setattr(distribution, "is_store_build", lambda: False)
    assert updates.automatic_check_enabled({"update_check_enabled": True}, {})
    assert not updates.automatic_check_enabled({"update_check_enabled": False}, {})


def test_store_outdated_advice_uses_only_the_store(store_mode):
    advice = yt_dlp_update.outdated_hint()
    assert "Microsoft Store" in advice
    assert "https://" not in advice
    assert "installer" not in advice


def test_direct_build_keeps_existing_outdated_advice(monkeypatch):
    monkeypatch.setattr(distribution, "is_store_build", lambda: False)
    assert yt_dlp_update.outdated_hint() == yt_dlp_update.OUTDATED_HINT
