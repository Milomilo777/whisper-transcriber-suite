"""webhook_secret_valid must reject the C1 control characters of Latin-1.

The docstring promises "Printable Latin-1 only (no control characters, so a
line break cannot split the header)". Latin-1's 0x80-0x9F block is control
characters too, and U+0085 (NEXT LINE) is a line break, so a secret holding
one of them must be refused, exactly like U+0009 or U+007F are.
"""
from core.config import webhook_secret_valid


def test_rejects_each_c1_control_character():
    for code in range(0x80, 0xA0):
        assert not webhook_secret_valid(f"a{chr(code)}b"), hex(code)


def test_still_accepts_printable_latin1_and_ascii():
    assert webhook_secret_valid("abc-123_a.A!~")
    assert webhook_secret_valid("clé secrets ÿþ")
