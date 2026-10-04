"""Stats payload privacy: OS-region country code, no computer name, no IP.

``region_country`` reads only the local OS region setting. The payload must
never carry ``platform_node`` (the computer name) or anything that looks
like an IP address; the property test below drives the builder with many
generated inputs while the computer name is forced to an IP-shaped value.
"""
from __future__ import annotations

import ipaddress
import os
import plistlib
import random
import re
import sys
from typing import Any

import pytest

from core import stats

_COUNTRY_RE = re.compile(r"[A-Z]{2}")

# A dotted quad that is not part of a longer dotted-number run (so kernel
# build strings like "xnu-10063.141.1.700.5" are not mistaken for one).
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _looks_like_ip(value: str) -> bool:
    if _IPV4_RE.search(value):
        return True
    for token in re.split(r"[\s/,;()\[\]<>\"']+", value):
        candidate = token.split("%", 1)[0]
        if ":" not in candidate and "." not in candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def _payload(**overrides: Any) -> dict[str, str]:
    kwargs: dict[str, Any] = dict(
        file_name="a.mp4", model="m", language="en",
        audio_duration=1.0, transcription_time=1.0, status="finished",
    )
    kwargs.update(overrides)
    return stats.build_stats_payload(**kwargs)


# --- payload ------------------------------------------------------------------

def test_payload_has_no_computer_name(monkeypatch):
    monkeypatch.setattr(stats.platform, "node", lambda: "OWNERS-DESKTOP-42")
    p = _payload()
    assert "platform_node" not in p
    assert all("OWNERS-DESKTOP-42" not in v for v in p.values())


def test_payload_country_is_empty_or_two_uppercase_letters():
    country = _payload()["country"]
    assert country == "" or _COUNTRY_RE.fullmatch(country)


def test_payload_country_comes_from_region_country(monkeypatch):
    monkeypatch.setattr(stats, "region_country", lambda: "IR")
    assert _payload()["country"] == "IR"


def test_ip_detector_controls():
    for ip_like in ("192.168.1.23", "::1", "fe80::1%eth0", "host 10.0.0.5 x",
                    "2001:db8::7"):
        assert _looks_like_ip(ip_like), ip_like
    for plain in ("1.9.3", "10.0.19045", "123.456", "large-v3", "AMD64",
                  "xnu-10063.141.1.700.5~1/RELEASE_ARM64", "22:22:05", ""):
        assert not _looks_like_ip(plain), plain


def _random_text(rng: random.Random, alphabet: str, max_len: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, max_len)))


def test_property_no_payload_value_looks_like_an_ip(monkeypatch):
    # Force the computer name to an IP-shaped value: if any field ever reads
    # it again, the property fails.
    monkeypatch.setattr(stats.platform, "node", lambda: "192.168.1.23")
    rng = random.Random(20261004)
    alphabet = "abcXYZ019 ._-()فایل"
    checked = 0
    for _ in range(300):
        name = _random_text(rng, alphabet, 30) + rng.choice(
            ["", ".mp4", ".wav", ".mkv"])
        file_name = os.path.join(_random_text(rng, "abc19", 8) or "d", name)
        model = rng.choice(["tiny", "large-v3", "distil-large-v3",
                            _random_text(rng, alphabet, 20)])
        language = rng.choice(["", "en", "fa", "auto",
                               _random_text(rng, "abcxyz", 3)])
        inputs = (file_name, model, language)
        if any(_looks_like_ip(s) for s in inputs):
            continue  # the property is about what the module ADDS
        p = _payload(
            file_name=file_name, model=model, language=language,
            audio_duration=rng.uniform(0, 1e5),
            transcription_time=rng.uniform(0, 1e4),
            status=rng.choice(["finished", "error", "cancelled"]),
            word_count=rng.randint(0, 10**6),
        )
        bad = {k: v for k, v in p.items() if _looks_like_ip(v)}
        assert not bad, bad
        checked += 1
    assert checked >= 250


# --- region_country -----------------------------------------------------------

def test_region_country_on_this_os_is_empty_or_two_uppercase_letters():
    code = stats.region_country()
    assert code == "" or _COUNTRY_RE.fullmatch(code)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows region API")
def test_windows_region_reads_the_geo_setting():
    code = stats._windows_region()
    assert code == "" or _COUNTRY_RE.fullmatch(code)


@pytest.mark.parametrize("name, expected", [
    ("fa_IR.UTF-8", "IR"),
    ("en_US", "US"),
    ("de_de.utf8", "DE"),
    ("sr_RS.UTF-8@latin", "RS"),
    ("zh_Hant_TW", "TW"),
    ("en-GB", "GB"),
    ("en_US@rg=gbzzzz", "GB"),
    ("en_US@calendar=persian;rg=irzzzz", "IR"),
    ("es_419", ""),
    ("C", ""),
    ("C.UTF-8", ""),
    ("POSIX", ""),
    ("en", ""),
    ("", ""),
])
def test_region_from_locale_name(name, expected):
    assert stats._region_from_locale_name(name) == expected


@pytest.mark.parametrize("environ, expected", [
    ({"LC_ALL": "de_DE.UTF-8", "LANG": "fa_IR.UTF-8"}, "DE"),
    ({"LANG": "fa_IR.UTF-8"}, "IR"),
    ({"LC_ALL": "", "LANG": "en_GB.UTF-8"}, "GB"),
    ({"LC_ALL": "C", "LANG": "fa_IR.UTF-8"}, ""),
    ({}, ""),
])
def test_env_region(environ, expected):
    assert stats._env_region(environ) == expected


@pytest.mark.parametrize("fmt", [plistlib.FMT_BINARY, plistlib.FMT_XML])
@pytest.mark.parametrize("prefs, expected", [
    ({"AppleLocale": "fa_IR"}, "IR"),
    ({"AppleLocale": "en_US@rg=gbzzzz"}, "GB"),
    ({"AppleLocale": "en"}, ""),
    ({"AppleLanguages": ["en-US"]}, ""),
    ({"AppleLocale": 42}, ""),
])
def test_macos_region_from_prefs(tmp_path, fmt, prefs, expected):
    path = tmp_path / ".GlobalPreferences.plist"
    path.write_bytes(plistlib.dumps(prefs, fmt=fmt))
    assert stats._macos_region(path) == expected


def test_macos_region_unreadable_prefs(tmp_path):
    assert stats._macos_region(tmp_path / "missing.plist") == ""
    garbage = tmp_path / "garbage.plist"
    garbage.write_bytes(b"\x00not a plist\xff")
    assert stats._macos_region(garbage) == ""


def test_macos_falls_back_to_locale_env(monkeypatch):
    monkeypatch.setattr(stats, "_macos_region", lambda: "")
    monkeypatch.setattr(stats.os, "environ", {"LANG": "nl_NL.UTF-8"})
    assert stats._region_for("darwin") == "NL"


def test_linux_uses_locale_env(monkeypatch):
    monkeypatch.setattr(stats.os, "environ", {"LANG": "pt_BR.UTF-8"})
    assert stats._region_for("linux") == "BR"


@pytest.mark.parametrize("platform_name, helper", [
    ("win32", "_windows_region"),
    ("darwin", "_macos_region"),
    ("linux", "_env_region"),
])
def test_region_lookup_never_raises(monkeypatch, platform_name, helper):
    def boom(*_a, **_k):
        raise RuntimeError("simulated OS API failure")

    monkeypatch.setattr(stats, helper, boom)
    assert stats._region_for(platform_name) == ""
