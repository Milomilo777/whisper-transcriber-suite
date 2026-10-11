import pytest
from core.writers.pdf_fonts import build_chain

NEW_CANDIDATES = [
    "NotoSansDevanagari-Regular.ttf",
    "Lohit-Devanagari.ttf",
    "Gargi.ttf",
    "Devanagari Sangam MN.ttc",
    "NotoSansThai-Regular.ttf",
    "Garuda.ttf",
    "Kinnari.ttf",
    "Thonburi.ttc"
]

@pytest.mark.parametrize("filename", NEW_CANDIDATES)
def test_font_candidates_fallback(tmp_path, filename):
    # build_chain takes dirs
    (tmp_path / filename).touch()

    chain = build_chain([str(tmp_path)])

    # Assert chain.fonts has exactly one font whose path ends with that file name
    matches = [f for f in chain.fonts if f.path.endswith(filename)]
    assert len(matches) == 1

def test_font_candidates_windows_wins(tmp_path):
    (tmp_path / "nirmala.ttf").touch()
    (tmp_path / "Lohit-Devanagari.ttf").touch()

    chain = build_chain([str(tmp_path)])
    names = [f.path for f in chain.fonts]

    assert any("nirmala.ttf" in p for p in names)
    assert not any("Lohit-Devanagari.ttf" in p for p in names)

def test_font_candidates_empty(tmp_path):
    chain = build_chain([str(tmp_path)])
    assert len(chain.fonts) == 0
