"""Invoke real update callbacks with plain view state; no Tk window is created."""
from types import SimpleNamespace
import pytest
from core import distribution, yt_dlp_update

@pytest.fixture
def gui_updates(monkeypatch):
    from app import app as gui
    monkeypatch.setattr(distribution, "is_store_build", lambda: True)
    monkeypatch.setattr(gui, "_", lambda text, **values: text.format(**values))
    notices = []
    monkeypatch.setattr(gui, "notify", lambda parent, message, level="info", **kw: notices.append((message, level)))
    return gui, notices

def test_manual_store_check_explains_store_channel(gui_updates):
    gui, notices = gui_updates
    gui.App._on_update_result(SimpleNamespace(_closing=False), None, manual=True)
    assert len(notices) == 1
    assert "Microsoft Store" in notices[0][0]
    assert notices[0][1] == "info"

def test_quiet_store_check_stays_silent(gui_updates):
    gui, notices = gui_updates
    gui.App._on_update_result(SimpleNamespace(_closing=False), None, manual=False)
    assert notices == []

def test_direct_failed_check_keeps_connection_warning(gui_updates, monkeypatch):
    gui, notices = gui_updates
    monkeypatch.setattr(distribution, "is_store_build", lambda: False)
    gui.App._on_update_result(SimpleNamespace(_closing=False), None, manual=True)
    assert len(notices) == 1 and notices[0][1] == "warning"
    assert "server" in notices[0][0]

def test_store_outdated_download_callback_uses_store_advice(gui_updates, monkeypatch):
    gui, notices = gui_updates
    messages = []
    app = SimpleNamespace(_closing=False, _yt_dlp_bar_dismissed=False,
                          _yt_dlp_updating=False, app_config={}, log=messages.append)
    monkeypatch.setattr(yt_dlp_update, "looks_outdated", lambda reason: True)
    gui.App.offer_yt_dlp_update(app, "extractor outdated")
    assert messages == ["Note: " + yt_dlp_update.outdated_hint()]
    assert "Microsoft Store" in messages[0] and "https://" not in messages[0]
