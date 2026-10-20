"""core/phone_link.py: the phone link of the Web / LAN page and its QR code."""
from __future__ import annotations

import base64
import builtins
import urllib.parse

import pytest

from core import phone_link


def test_no_password_keeps_the_address():
    assert phone_link.phone_url("http://192.168.1.5:8765/") == "http://192.168.1.5:8765/"
    assert phone_link.phone_url("http://192.168.1.5:8765/", "   ") == "http://192.168.1.5:8765/"


@pytest.mark.parametrize("token", ["s3cret", "a+b c", "pä/ss?&=#", "رمز"])
def test_password_round_trips_through_the_query(token):
    url = phone_link.phone_url("https://10.0.0.7:9000/", token)
    query = urllib.parse.urlsplit(url).query
    # the page reads it with URLSearchParams, which turns a bare "+" into a space
    assert "+" not in query and " " not in query
    assert urllib.parse.parse_qs(query) == {"token": [token]}


def test_existing_query_gets_an_ampersand():
    assert phone_link.phone_url("http://h:1/?x=1", "t") == "http://h:1/?x=1&token=t"


def test_qr_is_a_regular_png_qr_code():
    segno = pytest.importorskip("segno")
    url = "http://192.168.1.5:8765/"
    data = base64.b64decode(phone_link.qr_png_base64(url))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # segno picks a Micro QR for short text unless told otherwise; phone cameras cannot read those
    assert not segno.make_qr(url).is_micro


def test_qr_scale_changes_the_size():
    pytest.importorskip("segno")
    small = base64.b64decode(phone_link.qr_png_base64("http://h:1/", scale=2))
    big = base64.b64decode(phone_link.qr_png_base64("http://h:1/", scale=6))
    width = lambda png: int.from_bytes(png[16:20], "big")  # noqa: E731 - IHDR width
    assert width(big) == 3 * width(small)


def test_missing_segno_gives_no_qr(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "segno":
            raise ImportError("no segno")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert phone_link.qr_png_base64("http://h:1/") == ""
