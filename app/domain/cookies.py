"""Browser-cookie option for yt-dlp -- shared by the Download tab, Advanced
settings, the format lookup and the download service.

Tk-free and dependency-free so both UI surfaces and both services use one
list, one validation rule and one set of error heuristics. Before this module
the Advanced dialog hard-coded its own browser list (without Safari, so a Mac
user could not pick it) and the format lookup ignored the setting entirely.
"""
from __future__ import annotations

import re
import sys

# What the config key ``cookies_from_browser`` may name (yt-dlp's supported
# browsers). The value may carry yt-dlp's ``+KEYRING``/``:PROFILE`` suffixes.
COOKIE_BROWSERS = frozenset({
    "brave", "chrome", "chromium", "edge", "firefox", "opera",
    "safari", "vivaldi", "whale",
})

# Dropdown entry that means "don't use browser cookies" (config value "").
COOKIES_OFF_LABEL = "(off)"

_DROPDOWN_BROWSERS: tuple[str, ...] = ("chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi")


def cookie_browser_choices(current: str = "", platform: str = sys.platform) -> list[str]:
    """Dropdown values: "(off)" + the common browsers (Safari first on macOS).

    A hand-edited value the list does not show (e.g. ``firefox:work``) is
    appended so opening a dialog never silently drops it.
    """
    browsers: list[str] = list(_DROPDOWN_BROWSERS)
    if platform == "darwin":
        browsers.insert(0, "safari")
    values = [COOKIES_OFF_LABEL, *browsers]
    cur = (current or "").strip()
    if cur and cur not in values:
        values.append(cur)
    return values


def cookie_browser_label(value: str | None) -> str:
    """Config value -> dropdown label ("" -> "(off)")."""
    return (value or "").strip() or COOKIES_OFF_LABEL


def cookie_browser_value(label: str | None) -> str:
    """Dropdown label -> config value ("(off)" -> "")."""
    raw = (label or "").strip()
    return "" if raw in ("", COOKIES_OFF_LABEL) else raw


def cookies_from_browser_args(value: str | None) -> list[str]:
    """``--cookies-from-browser`` args for yt-dlp, or [] when unset.

    Lets the app download login-walled / age-gated content (Facebook,
    Instagram, TikTok stories; some YouTube Shorts) using the user's
    logged-in browser session. ``value`` accepts yt-dlp's
    ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]`` syntax; the leading
    browser token is validated against the supported set so a typo in a
    hand-edited config can't pass a bogus flag.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    browser = raw.split("+", 1)[0].split(":", 1)[0].strip().lower()
    if browser not in COOKIE_BROWSERS:
        return []
    return ["--cookies-from-browser", raw]


# yt-dlp's own failure to read the local browser's cookie jar — e.g. "Could
# not copy Chrome cookie database" when the browser is still open and holds
# a lock on the file (see yt-dlp#7271), or "Failed to decrypt with DPAPI"
# when Chrome's encryption key can't be unwrapped (yt-dlp#10927, common when
# the profile/context differs from the one that wrote it) — is a LOCAL
# cookie-jar problem, not the target site rejecting an unauthenticated
# request. Most URLs (a public post, a public video) do not actually need
# the cookies at all, so this case is worth a same-process retry without
# them rather than failing outright.
#
# The DPAPI wording carries no "cookie" token (yt-dlp raises it from
# cookies.py during browser extraction), so it needs its own alternative:
# without it the retry never fired for that failure and every affected
# download just failed, even for public URLs that don't need cookies.
COOKIE_EXTRACTION_ERROR_RE = re.compile(
    r"could not (?:copy|find|load|extract)\b.{0,40}\bcookie"
    r"|failed to decrypt\b.{0,40}\bdpapi",
    re.IGNORECASE,
)


def is_cookie_extraction_error(text: str) -> bool:
    """True when yt-dlp failed to read the browser's cookie jar itself.

    Distinct from the target site genuinely requiring a logged-in session
    (that shows up as a normal auth/permission error from the site, not a
    local "could not copy/find the cookie database" failure).
    """
    return bool(COOKIE_EXTRACTION_ERROR_RE.search(text or ""))


# The site itself refusing an anonymous request. yt-dlp's wording varies by
# extractor, but nearly all of them end with "Use --cookies-from-browser or
# --cookies ..." (Instagram: "rate-limit reached or login required";
# Facebook: "only available for registered users"; YouTube: "Sign in to
# confirm your age / you're not a bot").
_LOGIN_WALL_RE = re.compile(
    r"login required|sign in to confirm|registered users|--cookies"
    r"|private (?:video|account|post)",
    re.IGNORECASE,
)


def login_required_hint(error_text: str, cookies_browser: str | None) -> str:
    """One sentence telling the user how to get past a login wall, or "".

    ``cookies_browser`` is the current config value ("" = off).
    """
    if not _LOGIN_WALL_RE.search(error_text or "") or is_cookie_extraction_error(error_text):
        return ""
    browser = (cookies_browser or "").strip()
    if not browser:
        return (
            "This site wants you to be logged in: pick the browser you are "
            "logged in with under \"Log-in cookies\" and the link is checked "
            "again."
        )
    return (
        f"The site still asks for a login: check that you are logged in to it "
        f"in {browser} (on Windows, close {browser} completely if it keeps "
        "failing)."
    )
