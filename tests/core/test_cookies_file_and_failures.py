"""Log-in cookies: a cookies.txt file, the Chromium-on-Windows message, and the session memory.

Chrome-family browsers (Chrome, Edge, Brave, ...) encrypt their cookies with App-Bound Encryption
since Chromium 127, so yt-dlp cannot read them any more (yt-dlp#10927); a Netscape cookies.txt file
(exported by a browser extension) or Firefox still works. No Tk, no network.
"""
from __future__ import annotations

import types

import pytest

from app.domain import cookies as ck


@pytest.fixture
def cookie_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    return str(path)


# ----------------------------------------------------------------- cookies.txt file

def test_a_cookies_file_value_becomes_the_cookies_flag(cookie_file):
    assert ck.cookies_from_browser_args(cookie_file) == ["--cookies", cookie_file]
    assert ck.is_cookies_file(cookie_file)


def test_a_missing_or_relative_file_value_adds_nothing(tmp_path):
    assert ck.cookies_from_browser_args(str(tmp_path / "gone.txt")) == []
    assert ck.cookies_from_browser_args("cookies.txt") == []
    assert ck.cookies_from_browser_args("-evil") == []
    assert not ck.is_cookies_file(str(tmp_path))          # a folder is not a cookies file


def test_browser_values_are_unchanged(cookie_file):
    assert ck.cookies_from_browser_args("firefox:work") == ["--cookies-from-browser", "firefox:work"]
    assert ck.cookies_from_browser_args("") == []


def test_dropdown_offers_the_file_entry_only_where_asked(cookie_file):
    plain = ck.cookie_browser_choices(platform="win32")
    with_file = ck.cookie_browser_choices(platform="win32", with_file_entry=True)
    assert ck.file_entry_label() not in plain
    assert with_file[-1] == ck.file_entry_label()
    # a chosen file stays visible
    assert cookie_file in ck.cookie_browser_choices(cookie_file, platform="win32", with_file_entry=True)


def test_the_file_entry_itself_is_never_a_stored_value():
    assert ck.cookie_browser_value(ck.file_entry_label()) == ""


def test_a_broken_cookies_file_counts_as_a_cookie_read_failure():
    assert ck.is_cookie_extraction_error("ERROR: foo does not look like a Netscape format cookies file")
    assert ck.is_cookie_extraction_error("ERROR: Cookies file must be Netscape formatted, not JSON.")


# --------------------------------------------------------------- Chromium on Windows

@pytest.mark.parametrize("value", ["chrome", "brave", "edge", "chromium", "opera", "vivaldi", "whale",
                                   "brave:Profile 1", "chrome+gnomekeyring"])
def test_chromium_family_is_recognised(value):
    assert ck.is_chromium_browser(value)


@pytest.mark.parametrize("value", ["firefox", "safari", "", "firefox:work"])
def test_other_browsers_are_not_chromium(value):
    assert not ck.is_chromium_browser(value)


def test_the_blocked_text_is_for_chromium_on_windows_only(monkeypatch):
    monkeypatch.setattr(ck, "_is_windows", lambda: True)
    assert ck.cookies_unreadable_for_good("brave", "ERROR: Could not copy Chrome cookie database.")
    assert not ck.cookies_unreadable_for_good("firefox", "ERROR: Could not copy Chrome cookie database.")
    monkeypatch.setattr(ck, "_is_windows", lambda: False)
    assert not ck.cookies_unreadable_for_good("brave", "ERROR: Could not copy Chrome cookie database.")
    # the DPAPI wording is final on any browser
    assert ck.cookies_unreadable_for_good("edge", "ERROR: Failed to decrypt with DPAPI.")


def test_the_blocked_text_says_it_plainly_and_names_the_ways_out():
    text = ck.cookies_blocked_text().lower()
    assert "firefox" in text and "cookies.txt" in text
    assert "close" not in text


# -------------------------------------------------------------------- session memory

def _app():
    return types.SimpleNamespace()


def test_a_failure_is_remembered_per_value_until_reset():
    app = _app()
    assert ck.usable_cookie_value(app, "brave") == "brave"
    ck.remember_cookie_failure(app, "brave")
    assert ck.cookies_failed_before(app, "brave")
    assert ck.usable_cookie_value(app, "brave") == ""
    assert ck.usable_cookie_value(app, "firefox") == "firefox"       # another value is unaffected
    ck.forget_cookie_failures(app)
    assert ck.usable_cookie_value(app, "brave") == "brave"


def test_only_browsers_are_remembered_not_files(cookie_file):
    app = _app()
    ck.remember_cookie_failure(app, cookie_file)
    ck.remember_cookie_failure(app, "")
    assert ck.usable_cookie_value(app, cookie_file) == cookie_file


def test_two_apps_do_not_share_the_memory():
    a, b = _app(), _app()
    ck.remember_cookie_failure(a, "chrome")
    assert ck.usable_cookie_value(b, "chrome") == "chrome"


def test_strip_cookie_args_removes_both_flag_forms(cookie_file):
    cmd = ["yt-dlp", "--cookies-from-browser", "brave", "-o", "x", "--cookies", cookie_file, "--", "url"]
    assert ck.strip_cookie_args(cmd) == ["yt-dlp", "-o", "x", "--", "url"]
    # a URL after "--" that looks like the flag is left alone
    assert ck.strip_cookie_args(["yt-dlp", "--", "--cookies"]) == ["yt-dlp", "--", "--cookies"]


def test_login_wall_text_is_detected_but_not_a_file_error():
    assert ck.looks_like_login_wall("ERROR: Private video. Sign in if you've been granted access")
    assert ck.looks_like_login_wall("rate-limit reached or login required. Use --cookies")
    assert not ck.looks_like_login_wall("[Errno 22] Invalid argument: 'C:\\x.part'")
    assert not ck.looks_like_login_wall("ERROR: Could not copy Chrome cookie database. --cookies")
