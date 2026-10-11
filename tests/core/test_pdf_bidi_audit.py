import pytest
from core.writers.pdf_bidi import layout, _load

def test_an_only_with_persian_prefix_stays_rtl():
    eng = _load()
    if eng is None:
        pytest.skip("arabic_reshaper or python-bidi missing")

    # "\u06af\u0648\u06cc\u0646\u062f\u0647: " is Persian prefix "Speaker: "
    prefix = "\u06af\u0648\u06cc\u0646\u062f\u0647: "
    body = "\u0661\u0662\u0663" # Arabic digits

    lines, rtl = layout(prefix, body, 100, lambda t, b: len(t), eng)
    # Master evaluates this as RTL because _has_strong(body) is False,
    # so it falls back to is_rtl_text(prefix) which is True.
    assert rtl is True
    # In RTL, bold prefix is the last item of the first line
    assert lines[0][-1][1] is True
