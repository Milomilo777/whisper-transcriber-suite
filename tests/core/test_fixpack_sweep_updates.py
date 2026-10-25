"""Regression: a Unicode-digit version component must not crash the check.

Hermetic + pure: NO Tk root, NO live network. The full-path test
monkeypatches ``urlopen`` so the SILENT-failure contract is proven
without any socket.

``str.isdigit()`` is broader than ``int()`` accepts: it matches Unicode
digits such as the superscript ``²`` (U+00B2), which ``int()`` rejects
with ``ValueError``. Before the fix, ``_version_tuple`` fed such a
component straight into ``int()``, so the ``ValueError`` escaped
``is_newer`` and ``check_for_update`` — breaking the documented
never-raise / return-None-on-any-problem contract and silently killing
the update check. These tests fail on the pre-fix code.
"""
from __future__ import annotations

import urllib.request

import pytest

from core import updates
from core.updates import UpdateInfo, check_for_update, is_newer

# Superscript two (U+00B2): ``'²'.isdigit()`` is True but
# ``int('²')`` raises ValueError. Subscript three (U+2083) behaves
# the same way — both are the kind of "weird digit" a stray tag could
# carry.
_SUPERSCRIPT_TWO = "²"
_SUBSCRIPT_THREE = "₃"


def test_superscript_digit_is_a_digit_int_rejects() -> None:
    # Documents the exact stdlib quirk this fix guards against, so the
    # regression is self-explaining if the test ever trips.
    assert _SUPERSCRIPT_TWO.isdigit() is True
    with pytest.raises(ValueError):
        int(_SUPERSCRIPT_TWO)


@pytest.mark.parametrize(
    "tag",
    [
        f"1.{_SUPERSCRIPT_TWO}.0",   # exotic digit mid-version
        f"1.4.{_SUBSCRIPT_THREE}",   # exotic digit in the patch slot
        f"{_SUPERSCRIPT_TWO}.0.0",   # exotic digit leads the tag
        f"v1.{_SUPERSCRIPT_TWO}",    # with a leading v
    ],
)
def test_version_tuple_does_not_raise_on_unicode_digit(tag: str) -> None:
    # _version_tuple must degrade gracefully, never raise, and return a
    # plain tuple of plain ints (the offending component ends the prefix).
    result = updates._version_tuple(tag)
    assert isinstance(result, tuple)
    assert all(isinstance(p, int) for p in result)


def test_version_tuple_truncates_at_unicode_digit() -> None:
    # The leading clean component is kept; parsing stops at the bad one.
    assert updates._version_tuple(f"1.{_SUPERSCRIPT_TWO}.5") == (1,)
    assert updates._version_tuple(f"v3.4.{_SUBSCRIPT_THREE}") == (3, 4)


def test_is_newer_does_not_raise_on_unicode_digit_tag() -> None:
    # The public comparison must stay total (returns a bool, never raises)
    # even when the remote tag carries a Unicode-but-not-int digit.
    result = is_newer(f"1.{_SUPERSCRIPT_TWO}.0", "1.3.7")
    assert isinstance(result, bool)
    # A bare exotic-digit tag reads as an empty numeric prefix → not newer.
    assert is_newer(f"{_SUPERSCRIPT_TWO}.0.0", "1.3.7") is False


def test_check_for_update_silent_on_unicode_digit_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end: a release whose tag carries a superscript digit must NOT
    # crash check_for_update. It returns a sane UpdateInfo (with
    # is_newer=False, since the exotic prefix is never newer) — proving the
    # ValueError no longer escapes the comparison.
    body = (
        b'{"tag_name": "v1.\xc2\xb2.0", '
        b'"html_url": "https://github.com/o/r/releases/tag/v1"}'
    )

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    info = check_for_update(timeout=1)
    assert isinstance(info, UpdateInfo)
    assert info.is_newer is False
