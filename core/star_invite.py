"""The gentle GitHub star invitation: when it may appear, and what it remembers.

A user who has finished a few jobs and has used the app for a week sees one
quiet bar (``app.widgets.update_bar.StarBar``) saying a star on GitHub helps
other people find the app. It is asked at most twice, never again after "Don't
ask again" or after the page was opened, never while a job is running and never
in Work offline mode.

Everything here is a local counter in ``config.json``. Nothing is sent anywhere
and none of it joins the usage statistics (``core.stats`` builds its payload
from explicit fields only). The five keys are in
``core.config.LOCAL_ONLY_KEYS``, so the online config cannot set or clear them.

The functions are pure (a config mapping and a date go in), so the rules are
tested without Tk; the app glue is ``App._star_*``.
"""
from __future__ import annotations

from datetime import date
from typing import Any, MutableMapping

#: Successful jobs needed before the first invitation.
MIN_JOBS = 5
#: Days since the first launch needed before the first invitation.
MIN_DAYS = 7
#: The invitation appears at most this many times in total.
MAX_INVITES = 2
#: The second invitation comes at least this many days after the first.
MIN_GAP_DAYS = 30

KEY_FIRST_RUN = "star_first_run"
KEY_JOBS = "star_success_count"
KEY_SHOWN = "star_invites_shown"
KEY_LAST_SHOWN = "star_last_invite"
KEY_DONT_ASK = "star_dont_ask"

#: Every key this module owns (all local only).
KEYS = (KEY_FIRST_RUN, KEY_JOBS, KEY_SHOWN, KEY_LAST_SHOWN, KEY_DONT_ASK)

#: The repository page (the page has the Star button; ``/stargazers`` has none).
REPO_URL = "https://github.com/Milomilo777/whisper-transcriber-suite"

BAR_TEXT = "Enjoying it? A star on GitHub helps other people find it."
ABOUT_LINE = "Like the app? A star on its GitHub page helps other people find it."


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _count(config: MutableMapping[str, Any], key: str) -> int:
    value = config.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def ensure_first_run(config: MutableMapping[str, Any], today: date) -> bool:
    """Stamp the first-run date once. True when ``config`` changed.

    A missing, unreadable or future date (a wrong clock) is replaced by today,
    which only delays the invitation.
    """
    stored = _parse_date(config.get(KEY_FIRST_RUN))
    if stored is not None and stored <= today:
        return False
    config[KEY_FIRST_RUN] = today.isoformat()
    return True


def record_success(config: MutableMapping[str, Any], today: date) -> None:
    """Count one successful job (and stamp the first-run date if missing)."""
    ensure_first_run(config, today)
    config[KEY_JOBS] = _count(config, KEY_JOBS) + 1


def should_invite(
    config: MutableMapping[str, Any],
    today: date,
    *,
    job_running: bool,
    offline: bool,
) -> bool:
    """True when the bar may appear now."""
    if job_running or offline:
        return False
    if config.get(KEY_DONT_ASK) is True:
        return False
    shown = _count(config, KEY_SHOWN)
    if shown >= MAX_INVITES:
        return False
    if _count(config, KEY_JOBS) < MIN_JOBS:
        return False
    first = _parse_date(config.get(KEY_FIRST_RUN))
    if first is None or (today - first).days < MIN_DAYS:
        return False
    if shown:
        last = _parse_date(config.get(KEY_LAST_SHOWN))
        # An unreadable or future "last shown" date must not block for ever or
        # let the second ask through at once: treat it as "just now".
        if last is None or last > today or (today - last).days < MIN_GAP_DAYS:
            return False
    return True


def mark_shown(config: MutableMapping[str, Any], today: date) -> None:
    """The bar was put on screen: that is one of the two."""
    config[KEY_SHOWN] = _count(config, KEY_SHOWN) + 1
    config[KEY_LAST_SHOWN] = today.isoformat()


def decline(config: MutableMapping[str, Any]) -> None:
    """"Don't ask again", or the page was opened: never show the bar again."""
    config[KEY_DONT_ASK] = True
