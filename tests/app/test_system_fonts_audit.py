from app.theme import system_fonts
from app import mac_native
from unittest.mock import MagicMock

def test_apply_mac(monkeypatch):
    """Characterization test for `apply` on macOS."""
    monkeypatch.setattr(mac_native, "is_aqua", lambda widget: True)
    
    mock_root = MagicMock()
    mock_root.tk.splitlist.return_value = ["SunValleyCaptionFont", "UnknownFont"]
    
    def mock_call(*args):
        if args[0] == "font" and args[1] == "names":
            return "SunValleyCaptionFont UnknownFont"
        if args[0] == "font" and args[1] == "configure":
            if len(args) == 4:
                if args[3] == "-family":
                    return "Segoe UI"
                if args[3] == "-weight":
                    return "normal"
            if len(args) == 8:
                return ""
        return ""
    
    mock_root.tk.call = mock_call
    assert system_fonts.apply(mock_root) is True

def test_apply_non_mac(monkeypatch):
    """Characterization test for `apply` on non-macOS."""
    monkeypatch.setattr(mac_native, "is_aqua", lambda widget: False)
    mock_root = MagicMock()
    # Should short-circuit and return False
    assert system_fonts.apply(mock_root) is False

def test_ui_font_mac(monkeypatch):
    """Characterization test for `ui_font` on macOS."""
    monkeypatch.setattr(mac_native, "is_aqua", lambda widget: True)
    mock_root = MagicMock()
    assert system_fonts.ui_font(mock_root, "Segoe UI", 12) == (system_fonts.SYSTEM_UI_FAMILY, 12)
    assert system_fonts.ui_font(mock_root, "Segoe UI Semibold", 12) == (system_fonts.SYSTEM_UI_FAMILY, 12, "bold")
    assert system_fonts.ui_font(mock_root, "Segoe UI", 12, "italic") == (system_fonts.SYSTEM_UI_FAMILY, 12, "italic")
    assert system_fonts.ui_font(mock_root, "Segoe UI Semibold", 12, "italic") == (system_fonts.SYSTEM_UI_FAMILY, 12, "bold italic")

def test_ui_font_non_mac(monkeypatch):
    """Characterization test for `ui_font` on non-macOS."""
    monkeypatch.setattr(mac_native, "is_aqua", lambda widget: False)
    mock_root = MagicMock()
    assert system_fonts.ui_font(mock_root, "Segoe UI", 12) == ("Segoe UI", 12)
    assert system_fonts.ui_font(mock_root, "Segoe UI", 12, "italic") == ("Segoe UI", 12, "italic")
    assert system_fonts.ui_font(mock_root, "Segoe UI Semibold", 12) == ("Segoe UI Semibold", 12)

