import pytest
from core.writers.base import is_rtl_text
from core.writers.pdf_bidi import needs_bidi, _has_strong

def test_pdf_text_audit():
    # Arabic-Indic digits
    assert needs_bidi("\u0661\u0662\u0663") is False
    assert _has_strong("\u0661\u0662\u0663") is False

    # Mixed Persian/English runs
    # By design: counting rule
    assert is_rtl_text("\u0645\u06a9\u0627\u0646 123 English") is False

def test_zwnj_handling():
    pytest.importorskip("arabic_reshaper", reason="arabic_reshaper missing")
    pytest.importorskip("bidi.algorithm", reason="python-bidi missing")

    from core.writers.pdf_bidi import _load, _clusters
    eng = _load()
    if eng is None:
        pytest.skip("engine failed to load")

    # ZWNJ should not be dropped before reshaping, so letters don't wrongly join.
    # "\u0645\u06cc\u200c\u0631\u0648\u0645" is Meem Yeh + ZWNJ + Reh Waw Meem
    zwnj = "\u200c"
    text = "\u0645\u06cc" + zwnj + "\u0631\u0648\u0645"
    reshaped = eng.reshape(text)

    # Assert relations instead of literals
    assert zwnj in reshaped
    idx = reshaped.index(zwnj)
    assert reshaped[:idx] == eng.reshape("\u0645\u06cc")
    assert reshaped[idx+1:] == eng.reshape("\u0631\u0648\u0645")

    # _clusters should keep ZWNJ with the preceding letter
    # "\u0645\u06a9\u0627\u0646\u200c\u0647\u0627" is Meem Kaf Alef Noon + ZWNJ + Heh Alef
    clusters = _clusters("\u0645\u06a9\u0627\u0646" + zwnj + "\u0647\u0627")
    assert clusters == ["\u0645", "\u06a9", "\u0627", "\u0646" + zwnj, "\u0647", "\u0627"]

def test_is_rtl_edge_cases():
    assert is_rtl_text(None) is False
    assert is_rtl_text("") is False
    assert is_rtl_text("\U0001f60a") is False # emoji
