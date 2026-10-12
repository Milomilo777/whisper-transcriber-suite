"""Release-notes layout audit for the update notice: the headline, the
highlights and the macOS download, checked against odd but valid bodies and
against two recorded answers of this repository's real releases.

Pure logic from ``core.updates``: no Tk, no network.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from core.updates import (
    INSTALL_MACOS_APP,
    INSTALL_WINDOWS_INSTALLER,
    INSTALL_WINDOWS_PORTABLE,
    parse_release,
    pick_asset,
    release_headline,
    release_highlights,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "releases"

_ASSETS = (
    "installer-windows.exe",
    "portable-windows.zip",
    "macos-arm64.dmg",
    "macos-x64.dmg",
)


def _load_release(tag: str) -> str:
    return (_FIXTURES / f"release-{tag}.json").read_text(encoding="utf-8")


# ------------------------------------------------------------------ headline

@pytest.mark.parametrize(
    "table",
    [
        "File | Size\n--- | ---\nApp | 10\n",
        "File | Size\n---|:---:\nApp | 10\n",
        "File | Size |\n|---|---|\n",
        "| File |\n| --- |\n",
    ],
)
def test_a_table_without_a_leading_pipe_is_not_the_headline(table: str) -> None:
    assert release_headline("# Title\n\n" + table) == ""
    assert release_headline("# Title\n## Download\n" + table) == ""


def test_a_table_right_after_the_intro_ends_the_paragraph() -> None:
    body = "# Title\nThe intro sentence\nFile | Size\n--- | ---\nApp | 10\n"
    assert release_headline(body) == "The intro sentence"


def test_an_intro_that_contains_a_pipe_is_still_the_headline() -> None:
    body = "# Title\n\nFaster | smaller | calmer: the update notice got a rework.\n\n## Download\n"
    assert release_headline(body) == "Faster | smaller | calmer: the update notice got a rework."


def test_a_subheading_title_before_the_intro_is_skipped() -> None:
    body = "## Whisper Transcriber Suite v2.1.0\n\nA calmer update notice.\n\n## Download\n"
    assert release_headline(body) == "A calmer update notice."


def test_a_leading_quote_still_has_no_headline() -> None:
    assert release_headline("# Title\n> **Enjoying it?**\n") == ""


def test_a_byte_order_mark_does_not_turn_the_title_into_the_headline() -> None:
    assert release_headline("\ufeff# Title\r\n\r\nThe intro.\r\n") == "The intro."


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", ""),
        ("\r\n\r\n", ""),
        ("Hello &amp; welcome.", "Hello &amp; welcome."),
        ("| Col1 | Col2 |\n|---|---|", ""),
        ("```\nimport os\n```", ""),
    ],
)
def test_headline_edge_cases(body: str, expected: str) -> None:
    assert release_headline(body) == expected


def test_highlights_skip_the_download_section() -> None:
    body = (
        "# Title\n## Download\n* Download 1\n\n"
        "## Highlights\n* Feature 1\n* Feature 2\n* Feature 3\n* Feature 4\n\n"
        "## Installing on a Mac\n* Install step 1\n"
    )
    assert release_highlights(body, count=3) == ("Feature 1", "Feature 2", "Feature 3")


# ------------------------------------------------------------ macOS download

def test_pick_asset_by_install_kind() -> None:
    assert pick_asset(INSTALL_WINDOWS_INSTALLER, _ASSETS) == "installer-windows.exe"
    assert pick_asset(INSTALL_WINDOWS_PORTABLE, _ASSETS) == "portable-windows.zip"
    assert pick_asset(INSTALL_MACOS_APP, _ASSETS, machine="arm64") == "macos-arm64.dmg"
    assert pick_asset(INSTALL_MACOS_APP, _ASSETS, machine="x86_64") == "macos-x64.dmg"
    assert pick_asset(INSTALL_WINDOWS_INSTALLER, ("portable-windows.zip",)) is None
    assert pick_asset("some-unknown-kind", ("file.exe",)) is None
    assert pick_asset(INSTALL_WINDOWS_INSTALLER, ()) is None


def _under_rosetta(monkeypatch: pytest.MonkeyPatch) -> None:
    # An x64 process translated by Rosetta: the CPU reads as x86_64, the
    # kernel version names the Apple-silicon (ARM64) kernel.
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        platform, "version",
        lambda: "Darwin Kernel Version 21.6.0: root:xnu-8020.141.5~2/RELEASE_ARM64_T8101",
    )


def test_rosetta_prefers_the_arm64_dmg(monkeypatch: pytest.MonkeyPatch) -> None:
    _under_rosetta(monkeypatch)
    assert pick_asset(INSTALL_MACOS_APP, _ASSETS) == "macos-arm64.dmg"


def test_rosetta_falls_back_to_the_x64_dmg(monkeypatch: pytest.MonkeyPatch) -> None:
    _under_rosetta(monkeypatch)
    assert pick_asset(INSTALL_MACOS_APP, ("installer-windows.exe", "macos-x64.dmg")) == "macos-x64.dmg"


def test_an_intel_mac_never_gets_the_arm64_dmg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        platform, "version",
        lambda: "Darwin Kernel Version 19.6.0: root:xnu-6153.141.1~1/RELEASE_X86_64",
    )
    assert pick_asset(INSTALL_MACOS_APP, _ASSETS) == "macos-x64.dmg"
    assert pick_asset(INSTALL_MACOS_APP, ("macos-arm64.dmg",)) is None


def test_native_arm64_does_not_fall_back_to_x64() -> None:
    # A native arm64 app whose dmg is not uploaded yet waits for it rather
    # than being moved onto the x64 build.
    assert pick_asset(INSTALL_MACOS_APP, ("macos-x64.dmg",), machine="arm64") is None


# ------------------------------------------------------------- parse_release

def test_drafts_and_prereleases_are_refused() -> None:
    with pytest.raises(ValueError, match="draft"):
        parse_release(json.dumps({"tag_name": "v1.0", "draft": True}))
    with pytest.raises(ValueError, match="prerelease"):
        parse_release(json.dumps({"tag_name": "v1.0", "prerelease": True}))


def test_parse_release_survives_a_long_mixed_body() -> None:
    body = "A" * 25000 + "\r\n" + "\U0001F600" + "\r\n" + "\u0645\u0631\u062d\u0628\u0627" + "\r\n" + "<!-- c -->"
    assert parse_release(json.dumps({"tag_name": "v1.0", "body": body})).tag == "v1.0"


@pytest.mark.parametrize("text", ["", "{malformed:"])
def test_parse_release_rejects_bad_json(text: str) -> None:
    with pytest.raises(ValueError):
        parse_release(text)


# ------------------------------------------------- recorded real releases

def test_real_v1_9_1_body_bom_and_crlf() -> None:
    details = parse_release(_load_release("v1.9.1"))
    assert details.tag == "v1.9.1"
    assert details.headline == "A small patch release on top of v1.9.0 for Windows and macOS."
    assert details.highlights == ()  # this release has "## Changes", no "## Highlights"
    assert pick_asset(INSTALL_MACOS_APP, details.assets, machine="arm64") == (
        "WhisperTranscriberSuite-v1.9.1-macOS-arm64.dmg"
    )


def test_real_v1_8_0_only_x64_dmg(monkeypatch: pytest.MonkeyPatch) -> None:
    details = parse_release(_load_release("v1.8.0"))
    assert details.headline.startswith("A features + reliability release on top of v1.7.0:")
    assert details.highlights[0] == "Remote LLM provider."
    assert pick_asset(INSTALL_WINDOWS_INSTALLER, details.assets) is None  # old file names
    _under_rosetta(monkeypatch)
    assert pick_asset(INSTALL_MACOS_APP, details.assets) == "WhisperProject-v1.5.0-macOS-x64.dmg"
