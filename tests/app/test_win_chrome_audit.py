import pytest
import tkinter as tk
from unittest.mock import MagicMock
from app.theme import win_chrome

def test_windows_build_fallback_logic(monkeypatch):
    """Characterization test for `windows_build` fallback logic."""
    monkeypatch.setattr(win_chrome, "_rtl_build", lambda: None)
    import platform
    monkeypatch.setattr(platform, "version", lambda: "10.0.19045")
    assert win_chrome.windows_build() == 19045

    monkeypatch.setattr(platform, "version", lambda: "broken")
    import sys
    
    class FakeGetWindowsVersion:
        build = 22000
    
    monkeypatch.setattr(sys, "getwindowsversion", lambda: FakeGetWindowsVersion(), raising=False)
    assert win_chrome.windows_build() == 22000

    monkeypatch.delattr(sys, "getwindowsversion", raising=False)
    assert win_chrome.windows_build() == 0

def test_colorref():
    """Characterization test for `colorref`."""
    assert win_chrome.colorref("#000000") == 0
    assert win_chrome.colorref("#ffffff") == 0xffffff
    assert win_chrome.colorref("#ff0000") == 0x0000ff  # RGB to BGR
    assert win_chrome.colorref("00ff00") == 0x00ff00
    assert win_chrome.colorref("#112233") == 0x332211

@pytest.fixture
def tk_root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    r.withdraw()
    yield r
    r.destroy()

def test_window_handle(tk_root):
    """Characterization test for `window_handle`."""
    mock_native = MagicMock()
    mock_native.parent.return_value = 12345
    assert win_chrome.window_handle(tk_root, native=mock_native) == 12345
    mock_native.parent.assert_called_once()
    assert isinstance(mock_native.parent.call_args[0][0], int)

def test_apply_success(tk_root, monkeypatch):
    """Characterization test for `apply`."""
    win_chrome.set_enabled(True)
    mock_native = MagicMock()
    mock_native.parent.return_value = 12345
    mock_native.set_attribute.return_value = 0 # S_OK
    
    results = win_chrome.apply(tk_root, "dark", native=mock_native, build=22000, platform="win32")
    
    assert results[win_chrome.DWMWA_USE_IMMERSIVE_DARK_MODE] == 0
    assert results[win_chrome.DWMWA_CAPTION_COLOR] == 0
    assert getattr(tk_root, win_chrome._MARK) == "dark"

def test_apply_all(tk_root, monkeypatch):
    """Characterization test for `apply_all`."""
    win_chrome.set_enabled(True)
    monkeypatch.setattr(win_chrome, "enabled", lambda p=None: True)
    
    apply_called = 0
    def mock_apply(widget, theme, **kwargs):
        nonlocal apply_called
        apply_called += 1
        return {1: 0}
        
    monkeypatch.setattr(win_chrome, "apply", mock_apply)
    
    assert win_chrome.apply_all(tk_root, "dark") == 1
    assert apply_called == 1
    assert win_chrome._theme == "dark"

