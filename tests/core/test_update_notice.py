"""The calm update notice: release excerpt, install kind, the right download,
the Later ladder, Skip this version, and keys the online config cannot set.

Pure logic from ``core.updates`` and ``core.config``: no Tk, no network.
The bar itself and its wiring into the app are in tests/app/test_update_bar.py.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import config as cfg
from core import updates as u

# Same layout as the published release notes (docs/RELEASE_PROCESS.md): title,
# intro paragraph, Download table, star line, Highlights, Fixes.
_BODY = """# Whisper Transcriber Suite v1.9.4

Faster model loading, a calmer update notice, and **fixes** for
[Windows](https://example.org/win) and macOS. (Nothing changes in your settings.)

## Download

| File | For | Size |
|---|---|---|
| [**A-Installer-Windows-v1.9.4.exe**](https://example.org/a) | Windows | 234 MB |

> Enjoying it? Click **Star** at the top of this page.

## Highlights

- **Models load in half the time.** The worker keeps the model warm between
  files, so the second file starts at once. A third sentence that is long enough to
  push this bullet past the per-item budget of two hundred characters for sure.
  - a nested detail that is not a highlight of its own
- **Quiet update bar** instead of a dialog: `What's new`, Download, Later.
* Third highlight with a [link](https://example.org/x).
- Fourth highlight, shown only for a major release.

## Fixes

- A fix that is not a highlight.
"""


def _release_json(**overrides: object) -> str:
    data: dict[str, object] = {
        "tag_name": "v1.9.4",
        "html_url": "https://github.com/o/r/releases/tag/v1.9.4",
        "body": _BODY,
        "assets": [
            {"name": "WhisperTranscriberSuite-Installer-Windows-v1.9.4.exe", "state": "uploaded"},
            {"name": "WhisperTranscriberSuite-Portable-Windows-v1.9.4.zip", "state": "uploaded"},
            {"name": "WhisperTranscriberSuite-v1.9.4-macOS-arm64.dmg", "state": "new"},
            "not an asset",
            {"name": ""},
        ],
    }
    data.update(overrides)
    return json.dumps(data)


# ------------------------------------------------------------ release excerpt

def test_headline_is_the_first_sentence_of_the_intro_as_plain_text() -> None:
    assert u.release_headline(_BODY) == (
        "Faster model loading, a calmer update notice, and fixes for Windows and macOS."
    )


def test_headline_reads_crlf_bodies_and_skips_leading_blank_lines() -> None:
    body = "\r\n\r\n" + _BODY.replace("\n", "\r\n")
    assert u.release_headline(body).startswith("Faster model loading")


@pytest.mark.parametrize("body", ["", "## Download\n\n| a | b |", "- only a list\n- here", "   "])
def test_no_intro_paragraph_gives_no_headline(body: str) -> None:
    assert u.release_headline(body) == ""


def test_a_long_intro_is_clipped_at_a_word() -> None:
    headline = u.release_headline("word " * 100)
    assert len(headline) <= 160 and headline.endswith("…")
    assert "  " not in headline


def test_highlights_are_the_first_three_top_level_bullets() -> None:
    highlights = u.release_highlights(_BODY)
    assert len(highlights) == 3
    first, second, third = highlights
    assert first.startswith("Models load in half the time. The worker keeps the model warm")
    assert "nested detail" not in first
    assert len(first) <= 200 and first.endswith(".")  # whole sentences only
    assert second == "Quiet update bar instead of a dialog: What's new, Download, Later."
    assert third == "Third highlight with a link."
    assert all("Fourth" not in h and "fix that" not in h for h in highlights)


def test_a_bullet_keeps_its_continuation_lines_but_not_nested_ones() -> None:
    body = (
        "## Highlights\n\n"
        "- First short.\n"
        "  More of the first.\n"
        "  - nested detail\n"
        "    nested continuation\n"
        "- Second.\n"
        "Unindented paragraph line.\n"
        "  orphan indented line\n"
        "1. Third.\n"
    )
    assert u.release_highlights(body) == ("First short. More of the first.", "Second.", "Third.")


@pytest.mark.parametrize(
    "heading", ["## Highlights", "### highlights", "## ✨ Highlights", "## What's new", "## What’s new",
                "## 🚀 Whats new"],
)
def test_highlights_heading_variants(heading: str) -> None:
    assert u.release_highlights(f"Intro.\n\n{heading}\n\n- One.\n") == ("One.",)


def test_plain_text_drops_paired_marks_only() -> None:
    body = "## Highlights\n\n- **Bold**, *italic*, `code` and a lone *.srt pattern, 2 * 3 = 6.\n"
    assert u.release_highlights(body) == ("Bold, italic, code and a lone *.srt pattern, 2 * 3 = 6.",)


def test_hostile_bodies_stay_fast_and_never_raise() -> None:
    import time

    for body in ("[" * 200_000, "## Highlights\n- " + "[" * 200_000, "(" * 200_000 + "]",
                 "## Highlights\n" + "- x\n" * 100_000, ("\x00" + chr(0xFEFF)) * 1000):
        start = time.monotonic()
        u.release_headline(body)
        u.release_highlights(body)
        assert time.monotonic() - start < 2.0


def test_highlights_stay_within_the_600_character_budget() -> None:
    long_bullets = "\n".join(f"- {'x' * 50} " * 8 for _ in range(5))
    highlights = u.release_highlights("## Highlights\n\n" + long_bullets)
    assert len(highlights) == 3
    assert sum(len(h) for h in highlights) <= 600


def test_no_highlights_section_gives_no_highlights() -> None:
    assert u.release_highlights("# Title\n\nIntro.\n\n## Fixes\n\n- a fix\n") == ()


def test_a_major_release_gets_five_highlights_within_1000_characters() -> None:
    long_bullets = "\n".join(f"- {'x' * 50} " * 8 for _ in range(7))
    highlights = u.release_highlights(
        "## Highlights\n\n" + long_bullets,
        count=u.MAJOR_HIGHLIGHT_COUNT, max_chars=u.MAJOR_HIGHLIGHTS_MAX_CHARS,
    )
    assert len(highlights) == 5
    assert sum(len(h) for h in highlights) <= 1000
    # The first three are exactly what a minor release shows.
    assert highlights[:3] == u.release_highlights("## Highlights\n\n" + long_bullets)


def test_parse_release_reads_excerpt_and_only_uploaded_assets() -> None:
    details = u.parse_release(_release_json())
    assert details.tag == "v1.9.4"
    assert details.headline.startswith("Faster model loading")
    # Up to five: the notice keeps three of them unless the release is a major jump.
    assert len(details.highlights) == 4
    assert details.assets == (
        "WhisperTranscriberSuite-Installer-Windows-v1.9.4.exe",
        "WhisperTranscriberSuite-Portable-Windows-v1.9.4.zip",
    )


@pytest.mark.parametrize("extra", [{"body": None, "assets": None}, {"body": 5, "assets": {"a": 1}}])
def test_odd_body_or_assets_only_empty_the_details(extra: dict) -> None:
    details = u.parse_release(_release_json(**extra))
    assert details.tag == "v1.9.4"
    assert details.headline == "" and details.highlights == () and details.assets == ()


@pytest.mark.parametrize(("tag", "count"), [("v999.0.0", 4), (None, 3)])
def test_check_for_update_carries_the_details(
    monkeypatch: pytest.MonkeyPatch, tag: str | None, count: int,
) -> None:
    from core import __version__ as local_version
    if tag is None:  # the next minor version of this build
        major, minor = u._version_tuple(local_version)[:2]
        tag = f"v{major}.{minor + 1}.0"
    body = _release_json(tag_name=tag).encode("utf-8")

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return body

    monkeypatch.setattr(u.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    info = u.check_for_update(timeout=1)
    assert info is not None and info.is_newer
    assert info.headline.startswith("Faster") and len(info.highlights) == count
    assert len(info.assets) == 2


# ------------------------------------------------------------ install kind

def _touch(folder: Path, *names: str) -> Path:
    for name in names:
        target = folder / name
        if name == ".git":
            target.mkdir()
        else:
            target.write_text("", encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    ("files", "platform", "frozen", "kind"),
    [
        (("unins000.exe", u.PORTABLE_LAUNCHER), "win32", False, u.INSTALL_WINDOWS_INSTALLER),
        ((u.PORTABLE_LAUNCHER,), "win32", False, u.INSTALL_WINDOWS_PORTABLE),
        ((), "darwin", True, u.INSTALL_MACOS_APP),
        ((".git",), "linux", False, u.INSTALL_SOURCE),
        ((".git",), "win32", False, u.INSTALL_SOURCE),
        ((".git",), "darwin", True, u.INSTALL_MACOS_APP),
        ((), "win32", True, u.INSTALL_UNKNOWN),
        ((), "linux", False, u.INSTALL_UNKNOWN),
        ((u.PORTABLE_LAUNCHER,), "linux", False, u.INSTALL_UNKNOWN),
    ],
)
def test_install_kind_comes_from_the_files_beside_the_app(
    tmp_path: Path, files: tuple[str, ...], platform: str, frozen: bool, kind: str,
) -> None:
    app_dir = _touch(tmp_path, *files)
    assert u.detect_install_kind(app_dir, sys_platform=platform, frozen=frozen) == kind


def test_a_missing_app_folder_is_unknown(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    assert u.detect_install_kind(missing, sys_platform="win32", frozen=False) == u.INSTALL_UNKNOWN


# ------------------------------------------------------------ the right download

_ASSETS = (
    "WhisperTranscriberSuite-Installer-Windows-v1.9.4.exe",
    "WhisperTranscriberSuite-Portable-Windows-v1.9.4.zip",
    "WhisperTranscriberSuite-v1.9.4-macOS-arm64.dmg",
    "WhisperTranscriberSuite-v1.9.4-macOS-x64.dmg",
)


@pytest.mark.parametrize(
    ("kind", "machine", "expected"),
    [
        (u.INSTALL_WINDOWS_INSTALLER, None, _ASSETS[0]),
        (u.INSTALL_WINDOWS_PORTABLE, None, _ASSETS[1]),
        (u.INSTALL_MACOS_APP, "arm64", _ASSETS[2]),
        (u.INSTALL_MACOS_APP, "x86_64", _ASSETS[3]),
        (u.INSTALL_SOURCE, None, None),
        (u.INSTALL_UNKNOWN, None, None),
    ],
)
def test_download_is_the_file_for_this_install(kind: str, machine: str | None, expected: str | None) -> None:
    assert u.pick_asset(kind, _ASSETS, machine=machine) == expected


def test_a_release_without_this_file_yet_has_no_download() -> None:
    windows_only = _ASSETS[:2]
    assert u.pick_asset(u.INSTALL_MACOS_APP, windows_only, machine="arm64") is None
    assert u.kind_has_a_release_file(u.INSTALL_MACOS_APP)
    assert not u.kind_has_a_release_file(u.INSTALL_SOURCE)
    assert not u.kind_has_a_release_file(u.INSTALL_UNKNOWN)


def test_download_url_points_at_this_repository_only() -> None:
    url = u.asset_download_url("v1.9.4", "a b/../c.exe")
    assert url == (
        f"https://github.com/{u.GITHUB_OWNER}/{u.GITHUB_REPO}/releases/download/"
        "v1.9.4/a%20b%2F..%2Fc.exe"
    )


def test_update_command_for_a_source_checkout(tmp_path: Path) -> None:
    (tmp_path / "platform" / "linux").mkdir(parents=True)
    (tmp_path / "platform" / "linux" / "update.sh").write_text("", encoding="utf-8")
    assert u.update_command(tmp_path, sys_platform="linux") == (
        f"bash {(tmp_path / 'platform' / 'linux' / 'update.sh').as_posix()}"
    )
    assert u.update_command(tmp_path, sys_platform="darwin").endswith("pull --ff-only")
    assert u.update_command(tmp_path, sys_platform="win32") == f'git -C "{tmp_path}" pull --ff-only'
    (tmp_path / "platform" / "windows").mkdir()
    (tmp_path / "platform" / "windows" / "update.bat").write_text("", encoding="utf-8")
    assert u.update_command(tmp_path, sys_platform="win32") == (
        f'cmd /c "{tmp_path / "platform" / "windows" / "update.bat"}"'
    )


# ------------------------------------------------------------ Later ladder

_TODAY = date(2026, 10, 6)


def _seen(version: str = "1.9.4", **extra: object) -> dict:
    config: dict = {"update_check_enabled": True}
    u.note_latest(config, version)
    config.update(extra)
    return config


def test_a_new_version_shows_the_bar() -> None:
    assert u.notice_level(_seen(), "1.9.3", _TODAY) == u.NOTICE_BAR


def test_later_snoozes_3_then_7_then_14_days_then_once_a_month() -> None:
    config = _seen()
    day = _TODAY
    for step in (3, 7, 14, 30, 30, 30):
        until = u.snooze(config, day)
        assert until == day + timedelta(days=step)
        assert u.notice_level(config, "1.9.3", day) == u.NOTICE_PASSIVE
        assert u.notice_level(config, "1.9.3", until - timedelta(days=1)) == u.NOTICE_PASSIVE
        assert u.notice_level(config, "1.9.3", until) == u.NOTICE_BAR
        assert u.passive_sign_version(config, "1.9.3", environ={}) == "1.9.4"
        day = until
    assert u.REMIND_EVERY_DAYS == 30


def test_the_monthly_reminder_comes_back_after_a_long_absence() -> None:
    # The ladder ran out, then the app was not opened for a year.
    config = _seen(update_snooze_count=4, update_snooze_until="2026-11-05")
    assert u.notice_level(config, "1.9.3", date(2027, 10, 6)) == u.NOTICE_BAR


def test_the_snooze_count_stops_growing_after_the_ladder() -> None:
    config = _seen()
    for _ in range(50):
        u.snooze(config, _TODAY)
    assert config["update_snooze_count"] == len(u.SNOOZE_LADDER_DAYS) + 1


def test_a_snooze_date_from_a_wrong_clock_does_not_hide_the_bar_for_months() -> None:
    config = _seen(update_snooze_count=1, update_snooze_until="2027-06-01")
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR
    config["update_snooze_until"] = "not a date"
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR


@pytest.mark.parametrize(
    ("count", "days_ahead", "level"),
    [
        (1, 3, u.NOTICE_PASSIVE), (1, 4, u.NOTICE_BAR),  # a step never hides longer than itself
        (2, 7, u.NOTICE_PASSIVE), (2, 8, u.NOTICE_BAR),
        (3, 14, u.NOTICE_PASSIVE), (3, 15, u.NOTICE_BAR),
        (4, 30, u.NOTICE_PASSIVE), (4, 31, u.NOTICE_BAR),  # the monthly reminder: 30 days
        (9, 30, u.NOTICE_PASSIVE), (9, 400, u.NOTICE_BAR),
        (0, 2, u.NOTICE_PASSIVE), (0, 4, u.NOTICE_BAR),  # an odd count: the shortest step
    ],
)
def test_the_clock_skew_guard_follows_the_step(count: int, days_ahead: int, level: str) -> None:
    config = _seen(
        update_snooze_count=count,
        update_snooze_until=(_TODAY + timedelta(days=days_ahead)).isoformat(),
    )
    assert u.notice_level(config, "1.9.3", _TODAY) == level


def test_skip_still_silences_a_version_in_the_monthly_phase() -> None:
    config = _seen()
    for _ in range(5):
        u.snooze(config, _TODAY)
    u.skip_version(config, "1.9.4")
    assert u.notice_level(config, "1.9.3", _TODAY + timedelta(days=400)) == u.NOTICE_NONE
    assert u.note_latest(config, "1.9.5") is True
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR


def test_a_newer_version_restarts_the_ladder_from_the_monthly_phase() -> None:
    config = _seen()
    for _ in range(6):
        u.snooze(config, _TODAY)
    assert u.note_latest(config, "v1.9.5") is True
    assert config["update_snooze_count"] == 0 and config["update_snooze_until"] == ""
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR
    assert u.snooze(config, _TODAY) == _TODAY + timedelta(days=3)


def test_skip_is_silent_for_that_version() -> None:
    config = _seen()
    u.skip_version(config, "v1.9.4")
    assert config["update_skipped_version"] == "1.9.4"
    assert u.is_skipped(config, "v1.9.4")
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_NONE
    assert u.passive_sign_version(config, "1.9.3", environ={}) == ""
    u.stop_skipping(config)
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR


def test_a_newer_version_resets_skip_and_the_ladder() -> None:
    config = _seen()
    u.skip_version(config, "1.9.4")
    for _ in range(4):
        u.snooze(config, _TODAY)
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_NONE
    assert u.note_latest(config, "v1.9.5") is True
    assert config["update_latest_seen"] == "1.9.5"
    assert config["update_snooze_count"] == 0 and config["update_snooze_until"] == ""
    assert not u.is_skipped(config, "v1.9.5")
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_BAR


def test_seeing_the_same_version_keeps_the_ladder() -> None:
    config = _seen()
    u.snooze(config, _TODAY)
    before = dict(config)
    assert u.note_latest(config, "v1.9.4") is False
    assert u.note_latest(config, "1.9.4.0") is False
    assert config == before


def test_a_withdrawn_release_hands_over_to_the_real_latest_one() -> None:
    # 1.10.0 was seen, then pulled: the latest release is 1.9.5 again. The bar,
    # Skip and the Help-menu dot must then all be about 1.9.5.
    config = _seen("1.10.0")
    u.snooze(config, _TODAY)
    assert u.note_latest(config, "v1.9.5") is True
    assert config["update_latest_seen"] == "1.9.5"
    assert config["update_snooze_count"] == 0
    assert u.passive_sign_version(config, "1.9.3", environ={}) == "1.9.5"
    u.skip_version(config, "v1.9.5")
    assert u.notice_level(config, "1.9.3", _TODAY) == u.NOTICE_NONE


def test_no_notice_once_this_version_is_installed() -> None:
    config = _seen()
    assert u.notice_level(config, "1.9.4", _TODAY) == u.NOTICE_NONE
    assert u.notice_level(config, "2.0.0", _TODAY) == u.NOTICE_NONE
    assert u.passive_sign_version(config, "1.9.4", environ={}) == ""
    assert u.notice_level({}, "1.9.3", _TODAY) == u.NOTICE_NONE


def test_turned_off_or_disabled_by_environment_shows_no_passive_sign() -> None:
    config = _seen()
    assert u.passive_sign_version(config, "1.9.3", environ={}) == "1.9.4"
    assert u.passive_sign_version(config, "1.9.3", environ={u.DISABLE_ENV_VAR: "1"}) == ""
    config["update_check_enabled"] = False
    assert u.passive_sign_version(config, "1.9.3", environ={}) == ""


@pytest.mark.parametrize(("value", "disabled"), [("1", True), ("TRUE", True), (" yes ", True),
                                                 ("on", True), ("0", False), ("", False), ("no", False)])
def test_environment_switch(value: str, disabled: bool) -> None:
    env = {u.DISABLE_ENV_VAR: value}
    assert u.disabled_by_environment(env) is disabled
    assert u.automatic_check_enabled({"update_check_enabled": True}, env) is (not disabled)


def test_bar_text() -> None:
    assert u.bar_text("v1.9.4", "1.9.3", "Faster.") == (
        "Version 1.9.4 is available (you have 1.9.3).  Faster."
    )
    assert u.bar_text("v1.9.4", "v1.9.3", "") == "Version 1.9.4 is available (you have 1.9.3)."
    assert u.bar_text("v2.1.0", "2.0.3", "") == "Version 2.1.0 is available (you have 2.0.3)."


@pytest.mark.parametrize(
    ("tag", "local", "text"),
    [
        ("v3.0.0", "2.4.1", "Version 3.0 is here: a major new release (you have 2.4.1)."),
        ("3.0", "v2.9.9", "Version 3.0 is here: a major new release (you have 2.9.9)."),
        ("v3.1.0", "2.4.1", "Version 3.1 is here: a major new release (you have 2.4.1)."),
        ("v3.0.2", "2.4.1", "Version 3.0.2 is here: a major new release (you have 2.4.1)."),
        ("v10.0.0", "9.12.0", "Version 10.0 is here: a major new release (you have 9.12.0)."),
        ("v3", "2.4.1", "Version 3.0 is here: a major new release (you have 2.4.1)."),
        ("v3.0.0-rc1", "2.4.1", "Version 3.0.0-rc1 is here: a major new release (you have 2.4.1)."),
    ],
)
def test_bar_text_of_a_major_release(tag: str, local: str, text: str) -> None:
    assert u.bar_text(tag, local, "") == text
    assert u.bar_text(tag, local, "Faster.") == f"{text}  Faster."


@pytest.mark.parametrize(
    ("remote", "local", "major"),
    [
        ("v3.0.0", "2.4.1", True), ("3", "2.9", True), ("v10.0.0", "9.99.99", True),
        ("v2.1.0", "2.0.0", False), ("v2.0.1", "2.0.0", False), ("v2.0.0", "2.0.0", False),
        ("v2.0.0", "3.0.0", False), ("garbage", "2.0.0", False), ("v3.0.0", "", False),
        ("v3.0.0", "garbage", False),
    ],
)
def test_is_major_jump(remote: str, local: str, major: bool) -> None:
    assert u.is_major_jump(remote, local) is major


def test_notice_highlights_keep_three_for_a_minor_release_and_five_for_a_major_one() -> None:
    five = ("a", "b", "c", "d", "e")
    assert u.notice_highlights(five, "v2.1.0", "2.0.0") == ("a", "b", "c")
    assert u.notice_highlights(five, "v3.0.0", "2.0.0") == five
    assert u.notice_highlights(five + ("f",), "v3.0.0", "2.0.0") == five


# ------------------------------------------------------------ config keys

_UPDATE_KEYS = (
    "update_check_enabled", "last_update_check", "update_latest_seen",
    "update_skipped_version", "update_snooze_count", "update_snooze_until",
)
# Every value differs from the default, so a key that leaks through from the
# online layer shows up.
_HOSTILE_ONLINE = {
    "update_check_enabled": False,
    "last_update_check": "1999-01-01",
    "update_latest_seen": "99.0.0",
    "update_skipped_version": "98.0.0",
    "update_snooze_count": 3,
    "update_snooze_until": "2099-01-01",
}
_LOCAL = {
    "update_check_enabled": False,
    "last_update_check": "2026-10-06",
    "update_latest_seen": "1.9.4",
    "update_skipped_version": "1.9.4",
    "update_snooze_count": 2,
    "update_snooze_until": "2026-10-13",
}


def test_every_update_key_has_a_default_and_is_local_only() -> None:
    for key in _UPDATE_KEYS:
        assert key in cfg.DEFAULT_CONFIG
        assert key in cfg.LOCAL_ONLY_KEYS
        assert key not in cfg.ONLINE_ALLOWED_KEYS


def test_online_config_cannot_set_the_update_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even if a later edit allowlisted them, the online layer must not win
    # over the defaults (no local file) ...
    monkeypatch.setattr(cfg, "ONLINE_ALLOWED_KEYS", cfg.ONLINE_ALLOWED_KEYS | set(_UPDATE_KEYS))
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, dict(_HOSTILE_ONLINE), None)
    for key in _UPDATE_KEYS:
        assert merged[key] == cfg.DEFAULT_CONFIG[key], key
    # ... nor undo the user's own choices (a local file).
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, dict(_HOSTILE_ONLINE), dict(_LOCAL))
    for key in _UPDATE_KEYS:
        assert merged[key] == _LOCAL[key], key


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every app folder at tmp_path; returns the config.json path."""
    for kind in ("config", "cache", "log", "data"):
        folder = tmp_path / kind
        folder.mkdir()
        monkeypatch.setattr(cfg, f"user_{kind}_dir", lambda folder=folder: folder)
    path = tmp_path / "config" / "config.json"
    monkeypatch.setattr(cfg, "config_path", lambda: str(path))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))
    return path


def test_load_config_ignores_update_keys_from_the_online_layer(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = isolated_config
    monkeypatch.setattr(cfg, "fetch_online_config", lambda *_a, **_k: dict(_HOSTILE_ONLINE))
    cfg._ONLINE_MEMO.clear()
    try:
        path.write_text(json.dumps({"theme": "dark", "update_skipped_version": "1.9.4"}), encoding="utf-8")
        loaded = cfg.load_config()
    finally:
        cfg._ONLINE_MEMO.clear()
    assert loaded["update_check_enabled"] is True  # the default, not the online value
    assert loaded["update_latest_seen"] == ""
    assert loaded["last_update_check"] == ""
    assert loaded["update_snooze_count"] == 0
    assert loaded["update_snooze_until"] == ""
    assert loaded["update_skipped_version"] == "1.9.4"  # the local file's own value


def test_the_update_state_survives_a_save_and_reload(isolated_config: Path) -> None:
    config = cfg.load_config(fetch_online=False)
    config.update(_LOCAL)
    cfg.save_config(config)
    again = cfg.load_config(fetch_online=False)
    for key in _UPDATE_KEYS:
        assert again[key] == _LOCAL[key], key
    assert isinstance(again["update_snooze_count"], int)
