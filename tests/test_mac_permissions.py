"""Microphone permission helper for macOS (``app/mac_permissions.py``).

Windowless: the platform and the AVFoundation query are passed in as fakes, so
this runs on Windows and Linux. What the real query returns on a Mac is proved
by ``tools/mac_mic_permission_probe.py`` in the macOS VM.
"""
from __future__ import annotations

import subprocess
from typing import Any

import pytest

from app import mac_permissions as mp


@pytest.mark.parametrize("code, expected", [
    (0, mp.NOT_DETERMINED), (1, mp.RESTRICTED), (2, mp.DENIED), (3, mp.AUTHORIZED),
    (7, mp.UNKNOWN), (-1, mp.UNKNOWN),
])
def test_status_maps_avfoundation_codes(code: int, expected: str) -> None:
    assert mp.microphone_status(platform="darwin", query=lambda: code) == expected


def test_status_unknown_when_query_fails_or_has_no_answer() -> None:
    def boom() -> int:
        raise OSError("no AVFoundation")

    assert mp.microphone_status(platform="darwin", query=boom) == mp.UNKNOWN
    assert mp.microphone_status(platform="darwin", query=lambda: None) == mp.UNKNOWN


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_status_off_macos_never_asks(platform: str) -> None:
    def must_not_run() -> int:
        raise AssertionError("queried AVFoundation off macOS")

    assert mp.microphone_status(platform=platform, query=must_not_run) == mp.UNKNOWN


def test_settings_url_is_the_microphone_pane() -> None:
    assert mp.MICROPHONE_SETTINGS_URL == (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")


@pytest.mark.parametrize("status, seen, silent, expected", [
    (mp.DENIED, False, False, mp.REASON_BLOCKED),
    (mp.DENIED, True, False, mp.REASON_BLOCKED),
    (mp.RESTRICTED, True, False, mp.REASON_BLOCKED),
    (mp.AUTHORIZED, False, True, mp.REASON_BLOCKED),
    (mp.UNKNOWN, True, True, mp.REASON_BLOCKED),
    (mp.NOT_DETERMINED, False, False, mp.REASON_FIRST_USE),
    (mp.UNKNOWN, False, False, mp.REASON_FIRST_USE),
    (mp.NOT_DETERMINED, True, False, None),
    (mp.UNKNOWN, True, False, None),
    (mp.AUTHORIZED, False, False, None),
    (mp.AUTHORIZED, True, False, None),
])
def test_notice_reason_on_macos(status: str, seen: bool, silent: bool, expected: Any) -> None:
    assert mp.notice_reason(status, seen=seen, silent=silent, platform="darwin") == expected


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("status", [mp.DENIED, mp.NOT_DETERMINED, mp.UNKNOWN, mp.AUTHORIZED])
@pytest.mark.parametrize("silent", [False, True])
def test_notice_reason_never_off_macos(platform: str, status: str, silent: bool) -> None:
    assert mp.notice_reason(status, seen=False, silent=silent, platform=platform) is None


def test_open_settings_runs_open_with_the_deep_link() -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    assert mp.open_microphone_settings(platform="darwin", run=run) is True
    assert calls == [["open", mp.MICROPHONE_SETTINGS_URL]]


def test_open_settings_reports_failure_without_raising() -> None:
    def broken(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        raise OSError("no open command")

    def nonzero(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1)

    assert mp.open_microphone_settings(platform="darwin", run=broken) is False
    assert mp.open_microphone_settings(platform="darwin", run=nonzero) is False


def test_open_settings_off_macos_does_nothing() -> None:
    def must_not_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("ran open off macOS")

    assert mp.open_microphone_settings(platform="win32", run=must_not_run) is False
