from app.theme import script_fonts
from unittest.mock import MagicMock

def test_script_of():
    """Characterization test for script_of."""
    assert script_fonts.script_of("a") is None
    assert script_fonts.script_of("1") is None
    assert script_fonts.script_of("\u0D85") == "sinhala" # Sinhala
    assert script_fonts.script_of("\u4E00") == "han" # Han
    assert script_fonts.script_of("\u1000") == "myanmar" # Myanmar

def test_text_script():
    """Characterization test for text_script."""
    assert script_fonts.text_script("hello world") is None
    assert script_fonts.text_script("hello \u0D85") == "sinhala"
    assert script_fonts.text_script("\u4E00\u4E01") == "han"

def test_han_region():
    """Characterization test for han_region."""
    assert script_fonts.han_region("zh") == "zh-hans"
    assert script_fonts.han_region("zh-TW") == "zh-hant"
    assert script_fonts.han_region("ja") == "ja"
    assert script_fonts.han_region("ko") is None
    assert script_fonts.han_region("en") is None

def test_font_key():
    """Characterization test for font_key."""
    assert script_fonts.font_key("hello") is None
    assert script_fonts.font_key("\u0D85") == "sinhala"
    assert script_fonts.font_key("\u4E00", "zh-TW") == "zh-hant"

def test_installed_families_mock(monkeypatch):
    """Characterization test for installed_families with caching."""
    # Reset cache
    monkeypatch.setattr(script_fonts, "_families", None)
    
    mock_root = MagicMock()
    mock_root.tk.splitlist.return_value = ["Segoe UI", "Arial"]
    mock_root.tk.call.return_value = "Segoe UI Arial"
    
    families = script_fonts.installed_families(mock_root)
    assert families == frozenset({"Segoe UI", "Arial"})
    assert mock_root.tk.call.call_count == 1
    
    # Second call should use cache
    families2 = script_fonts.installed_families(mock_root)
    assert families2 == frozenset({"Segoe UI", "Arial"})
    assert mock_root.tk.call.call_count == 1

def test_run_pieces_infinite_loop():
    """Defect: run_pieces enters an infinite loop if a character is larger than the limit.
    Note: this only applies to limits below one character's byte size (never in production)."""
    pieces = script_fonts.run_pieces("אב", limit=1)
    assert pieces == [(0, 1), (1, 2)]
    
    # Ensure pieces tile the line losslessly
    line = "אב"
    reconstructed = "".join(line[s:e] for s, e in pieces)
    assert reconstructed == line
