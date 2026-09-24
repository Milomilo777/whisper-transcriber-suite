"""Shared browser-cookie choices (Download tab + Advanced settings)."""
from __future__ import annotations

from app.domain import cookies as ck


def test_off_first_and_safari_only_on_macos():
    mac = ck.cookie_browser_choices(platform="darwin")
    win = ck.cookie_browser_choices(platform="win32")
    assert mac[0] == win[0] == ck.COOKIES_OFF_LABEL
    assert mac[1] == "safari"
    assert "safari" not in win
    assert {"chrome", "edge", "firefox"} <= set(win)


def test_hand_edited_value_is_kept_visible():
    values = ck.cookie_browser_choices("firefox:work", platform="win32")
    assert values[-1] == "firefox:work"


def test_label_and_value_round_trip():
    assert ck.cookie_browser_label("") == ck.COOKIES_OFF_LABEL
    assert ck.cookie_browser_value(ck.COOKIES_OFF_LABEL) == ""
    assert ck.cookie_browser_value(ck.cookie_browser_label("chrome")) == "chrome"


def test_every_dropdown_browser_is_accepted_by_yt_dlp_args():
    for label in ck.cookie_browser_choices(platform="darwin")[1:]:
        assert ck.cookies_from_browser_args(label) == ["--cookies-from-browser", label]


def test_login_hint_ignores_unrelated_errors_and_cookie_jar_failures():
    assert ck.login_required_hint("ERROR: Video unavailable", "") == ""
    assert ck.login_required_hint(
        "ERROR: could not find firefox cookies database in '/x'", "firefox",
    ) == ""
    assert "logged in" in ck.login_required_hint(
        "Sign in to confirm your age. Use --cookies-from-browser", "",
    )
