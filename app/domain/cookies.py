"""Browser-cookie option for yt-dlp -- shared by the Download tab, Advanced
settings, the format lookup and the download service.

Tk-free and dependency-free so both UI surfaces and both services use one
list, one validation rule and one set of error heuristics. Before this module
the Advanced dialog hard-coded its own browser list (without Safari, so a Mac
user could not pick it) and the format lookup ignored the setting entirely.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence

from app.i18n import _, pgettext

# What the config key ``cookies_from_browser`` may name (yt-dlp's supported
# browsers). The value may carry yt-dlp's ``+KEYRING``/``:PROFILE`` suffixes.
COOKIE_BROWSERS = frozenset({
    "brave", "chrome", "chromium", "edge", "firefox", "opera",
    "safari", "vivaldi", "whale",
})

# Dropdown entry that means "don't use browser cookies" (config value ""), in English. The
# dropdown shows it translated (off_label()); both map back to "".
COOKIES_OFF_LABEL = "(off)"

_DROPDOWN_BROWSERS: tuple[str, ...] = ("chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi")


def off_label() -> str:
    """The dropdown entry for "no browser cookies" in the interface language."""
    return pgettext("browser cookies", "(off)")


def file_entry_label() -> str:
    """The Download tab dropdown entry that opens a picker for a cookies.txt file."""
    return pgettext("browser cookies", "cookies.txt file…")


def cookie_browser_choices(
    current: str = "", platform: str = sys.platform, *, with_file_entry: bool = False,
) -> list[str]:
    """Dropdown values: "(off)" + the common browsers (Safari first on macOS).

    A hand-edited value the list does not show (e.g. ``firefox:work``) is
    appended so opening a dialog never silently drops it. ``with_file_entry``
    adds the last entry that picks a cookies.txt file (a chosen file's path is
    shown as its own value).
    """
    browsers: list[str] = list(_DROPDOWN_BROWSERS)
    if platform == "darwin":
        browsers.insert(0, "safari")
    values = [off_label(), *browsers]
    cur = (current or "").strip()
    if cur and cur not in values and cur != COOKIES_OFF_LABEL:
        values.append(cur)
    if with_file_entry:
        values.append(file_entry_label())
    return values


def cookie_browser_label(value: str | None) -> str:
    """Config value -> dropdown label ("" -> "(off)", translated)."""
    return (value or "").strip() or off_label()


def cookie_browser_value(label: str | None) -> str:
    """Dropdown label -> config value ("(off)", English or translated, -> "")."""
    raw = (label or "").strip()
    return "" if raw in ("", COOKIES_OFF_LABEL, off_label(), file_entry_label()) else raw


def _browser_token(value: str | None) -> str:
    return (value or "").strip().split("+", 1)[0].split(":", 1)[0].strip().lower()


def is_cookies_file(value: str | None) -> bool:
    """True when the cookies setting holds the path of an existing cookies.txt file (Netscape
    format, exported by a browser extension) instead of a browser name."""
    raw = (value or "").strip()
    return bool(raw) and _browser_token(raw) not in COOKIE_BROWSERS and os.path.isabs(raw) \
        and os.path.isfile(raw)


def cookies_from_browser_args(value: str | None) -> list[str]:
    """``--cookies-from-browser`` (or ``--cookies FILE``) args for yt-dlp, or [] when unset.

    Lets the app download login-walled / age-gated content (Facebook,
    Instagram, TikTok stories; some YouTube Shorts) using the user's
    logged-in browser session. ``value`` accepts yt-dlp's
    ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]`` syntax; the leading
    browser token is validated against the supported set so a typo in a
    hand-edited config can't pass a bogus flag. An absolute path of an
    existing file is a Netscape cookies.txt file and becomes ``--cookies``.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    if _browser_token(raw) in COOKIE_BROWSERS:
        return ["--cookies-from-browser", raw]
    if is_cookies_file(raw):
        return ["--cookies", raw]
    return []


_COPIES: list[str] = []
_MAX_COPIES = 40


def _remove_copies() -> None:
    while _COPIES:
        try:
            os.unlink(_COPIES.pop())
        except OSError:
            pass


atexit.register(_remove_copies)


def private_cookies_copy(value: str | None) -> str:
    """For a cookies.txt *value*, the path of a temporary copy; any other value unchanged.

    yt-dlp writes its cookie jar back into the file given with ``--cookies`` when it ends
    (YoutubeDL.save_cookies), which would rewrite the user's own file; a run gets a copy. The
    copies are deleted when the app ends (and the oldest when many pile up)."""
    raw = (value or "").strip()
    if not is_cookies_file(raw):
        return raw
    try:
        fd, tmp = tempfile.mkstemp(prefix="wts-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(raw, tmp)
    except OSError:
        return raw
    _COPIES.append(tmp)
    while len(_COPIES) > _MAX_COPIES:
        try:
            os.unlink(_COPIES.pop(0))
        except OSError:
            pass
    return tmp


def strip_cookie_args(command: Sequence[str]) -> list[str]:
    """*command* without its ``--cookies-from-browser X`` / ``--cookies X`` pairs (the options
    only: whatever follows ``--`` is a URL and stays)."""
    out: list[str] = []
    skip = False
    for i, arg in enumerate(command):
        if skip:
            skip = False
            continue
        if arg == "--":
            out.extend(command[i:])
            break
        if arg in ("--cookies-from-browser", "--cookies"):
            skip = True
            continue
        out.append(arg)
    return out


# Chromium-family browsers: since Chromium 127 their cookies carry "App-Bound Encryption" on
# Windows, which only the browser itself can undo (yt-dlp#10927). Firefox is unaffected.
CHROMIUM_BROWSERS = frozenset({"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"})


def _is_windows() -> bool:
    return sys.platform == "win32"


def is_chromium_browser(value: str | None) -> bool:
    return _browser_token(value) in CHROMIUM_BROWSERS


def cookies_unreadable_for_good(value: str | None, error_text: str) -> bool:
    """True when a cookie-read failure of *value* cannot be cured by the user closing the browser:
    a Chromium-family browser on Windows (any wording: "Could not copy ...", "Failed to decrypt
    ...") or the DPAPI wording on any browser."""
    if "dpapi" in (error_text or "").lower():
        return True
    return _is_windows() and is_chromium_browser(value)


def cookies_blocked_text() -> str:
    """Plain words for a browser whose cookies downloaders can no longer read."""
    return _(
        "This browser's cookies can no longer be read by video downloaders (browser "
        "encryption). Pick Firefox, or a cookies.txt file, under \"Log-in cookies\"."
    )


# What the app remembers for one run about browsers whose cookies it could not read: every later
# download then skips the doomed attempt (a second yt-dlp start, a retry and a log line each time).
# The memory lives on the app object, so it ends with the run; picking the setting again clears it.
_FAILED_ATTR = "_unreadable_cookie_sources"


def _failed_set(app: object, create: bool = False) -> set[str]:
    store = vars(app)  # the instance dict: getattr of a missing name on a Tk-less App recurses
    found = store.get(_FAILED_ATTR)
    if found is None:
        found = set()
        if create:
            store[_FAILED_ATTR] = found
    return found


def remember_cookie_failure(app: object, value: str | None) -> None:
    """Note that the cookies of browser *value* could not be read (a cookies file is not noted)."""
    raw = (value or "").strip()
    if raw and _browser_token(raw) in COOKIE_BROWSERS:
        _failed_set(app, create=True).add(raw)


def cookies_failed_before(app: object, value: str | None) -> bool:
    return (value or "").strip() in _failed_set(app)


def forget_cookie_failures(app: object) -> None:
    _failed_set(app).clear()


def usable_cookie_value(app: object, value: str | None) -> str:
    """*value*, or "" when its cookies could not be read earlier in this run."""
    raw = (value or "").strip()
    return "" if cookies_failed_before(app, raw) else raw


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
    r"|failed to decrypt\b.{0,40}\bdpapi"
    # a cookies.txt file yt-dlp cannot parse (not Netscape format, or JSON)
    r"|netscape format",
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


def looks_like_login_wall(error_text: str) -> bool:
    """True when *error_text* is the site refusing an anonymous request (not a cookie-jar or
    file-system failure)."""
    return bool(_LOGIN_WALL_RE.search(error_text or "")) and not is_cookie_extraction_error(error_text)


def login_required_hint(
    error_text: str, cookies_browser: str | None, *, cookies_unreadable: bool = False
) -> str:
    """One sentence telling the user how to get past a login wall, or "".

    ``cookies_browser`` is the current config value ("" = off).
    ``cookies_unreadable`` is True when reading the cookies has already failed.
    """
    if not _LOGIN_WALL_RE.search(error_text or "") or is_cookie_extraction_error(error_text):
        return ""
    browser = (cookies_browser or "").strip()
    if (_is_windows() and is_chromium_browser(browser)) and (
        cookies_unreadable or "could not be decrypted" in (error_text or "").lower()
    ):
        return cookies_blocked_text()  # its cookies cannot be read: "check you are logged in" is no help
    if is_cookies_file(browser):
        return _("The site still asks for a login: export a fresh cookies.txt file after logging in to it.")
    if not browser:
        return _(
            "This site wants you to be logged in: pick the browser you are "
            "logged in with under \"Log-in cookies\" and the link is checked "
            "again."
        )
    return _(
        "The site still asks for a login: check that you are logged in to it "
        "in {browser} (on Windows, close {browser} completely if it keeps "
        "failing).",
        browser=browser,
    )
