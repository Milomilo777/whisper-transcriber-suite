"""Optional, opt-in GitHub "update available" check (Tk-free).

This module is pure engine code: it never imports tkinter and is safe
to call from a background daemon thread. The UI glue in ``app/`` is
responsible for marshalling the result back onto the Tk main thread
and for showing any dialog.

Behaviour contract (deliberately conservative — this must never nag):

  * It only ever NOTIFIES. It never downloads or installs anything;
    the UI offers to open the releases page in a browser, nothing more.
  * Every network / HTTP / JSON / parsing error is swallowed and the
    public ``check_for_update`` returns ``None``. A PRIVATE repo's
    ``releases/latest`` endpoint returns HTTP 404 — that path must be
    silent (return ``None``), never crash and never surface an error.
  * The version comparison is tolerant of a leading ``v`` and of odd
    or pre-release tags (e.g. ``v1.4.0-rc1``); it never raises on a
    malformed tag, it just compares the numeric dotted prefix.

The in-place Standard installer upgrade is a SEPARATE concern (the
installer uses a stable AppId, so running a newer Setup upgrades over
the old install with no uninstall). This module does not touch that;
it only points the user at the download page.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import NamedTuple

logger = logging.getLogger(__name__)

# --- Repository coordinates ------------------------------------------------
# HANDOVER NOTE: change these two constants if the project moves to a
# different GitHub owner / repository. They are the single source of
# truth for both the API URL and the human-facing releases page.
GITHUB_OWNER = "Milomilo777"
GITHUB_REPO = "whisper-transcriber-suite"

# Human-facing page the UI opens on the user's request. ``/releases/latest``
# redirects to the newest published release's page.
RELEASES_PAGE_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)

# A short, honest User-Agent. GitHub's REST API rejects requests with no
# User-Agent header (HTTP 403), so this is required, not cosmetic.
_USER_AGENT = "WhisperTranscriberSuite-update-check"

# Default network timeout, in seconds, for the single GET. Kept small so
# the daemon thread never lingers on a dead network.
_DEFAULT_TIMEOUT_S = 8


class UpdateInfo(NamedTuple):
    """The outcome of a successful release lookup.

    ``is_newer`` is the only field the caller needs to decide whether to
    prompt; ``latest_tag`` / ``html_url`` feed the message + the browser
    open. ``html_url`` falls back to :data:`RELEASES_PAGE_URL` when the
    API response omits it.
    """

    latest_tag: str
    html_url: str
    is_newer: bool


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted version string into a tuple of ints, leniently.

    Strips a single leading ``v``/``V``, splits on ``.``, and reads the
    leading run of digits from each component (so ``1.4.0-rc1`` →
    ``(1, 4, 0)`` and ``v1.3.10`` → ``(1, 3, 10)``). A component with no
    leading digit contributes ``0`` and STOPS parsing the rest, so a
    wildly malformed tag degrades to a short tuple instead of raising.
    Returns ``()`` for an empty / all-garbage string.

    ``str.isdigit()`` is broader than ``int()`` will accept: it also
    matches Unicode digits such as superscripts (``²``) and other exotic
    digit code points that ``int()`` rejects with ``ValueError``. The
    ``int()`` conversion is therefore guarded so such a tag degrades to a
    short tuple (the offending component ends the numeric prefix) instead
    of raising — preserving the never-raise contract of the public API.
    """
    s = version.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    parts: list[int] = []
    for chunk in s.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            # First non-numeric component ends the numeric prefix.
            break
        try:
            value = int(digits)
        except ValueError:
            # ``isdigit()`` accepted a Unicode digit (e.g. a superscript)
            # that ``int()`` cannot parse. Stop here rather than raise.
            break
        parts.append(value)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    """Return True when ``remote`` is a strictly newer version than ``local``.

    Tolerant of a leading ``v`` on either side and of trailing
    non-numeric / pre-release suffixes. Shorter tuples are zero-padded
    for the comparison so ``1.4`` > ``1.3.10`` and ``1.4`` == ``1.4.0``.
    Never raises on odd input — an unparseable tag compares as ``()``,
    which is never newer than a real version.
    """
    r = _version_tuple(remote)
    l = _version_tuple(local)
    if not r:
        # Couldn't read a numeric version out of the remote tag — be
        # conservative and treat it as "not newer" so we never nag on
        # a tag we don't understand.
        return False
    width = max(len(r), len(l))
    r_padded = r + (0,) * (width - len(r))
    l_padded = l + (0,) * (width - len(l))
    return r_padded > l_padded


def latest_release_api_url(owner: str, repo: str) -> str:
    """Build the GitHub REST URL for a repo's latest published release."""
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def parse_release_json(text: str) -> tuple[str, str]:
    """Parse a GitHub ``releases/latest`` JSON body into ``(tag, html_url)``.

    A pure, network-free seam for testing. Returns the ``tag_name`` and
    the release's ``html_url`` (falling back to
    :data:`RELEASES_PAGE_URL` when the body omits ``html_url``). Raises
    ``ValueError`` on malformed JSON or a non-object / tag-less body; the
    caller in :func:`check_for_update` turns any raise into a silent
    ``None``.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as e:
        raise ValueError(f"malformed release JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("release JSON is not an object")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("release JSON has no usable tag_name")
    html_url = data.get("html_url")
    if not isinstance(html_url, str) or not html_url.strip():
        html_url = RELEASES_PAGE_URL
    return tag.strip(), html_url.strip()


def check_for_update(timeout: int = _DEFAULT_TIMEOUT_S) -> UpdateInfo | None:
    """Look up the latest GitHub release and compare it to this build.

    GETs the ``releases/latest`` JSON over stdlib urllib (no third-party
    deps), parses the tag + page URL, and compares the tag against
    ``core.__version__``.

    Returns an :class:`UpdateInfo` on success (``is_newer`` tells the
    caller whether to prompt). Returns ``None`` on ANY failure —
    network down, DNS failure, timeout, non-2xx HTTP (including the 404
    a PRIVATE repo returns), or unparseable JSON. Failure is always
    silent here; the UI decides whether a *manual* check should show a
    gentle "couldn't reach the server" note.
    """
    url = latest_release_api_url(GITHUB_OWNER, GITHUB_REPO)
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", errors="replace")
        tag, html_url = parse_release_json(text)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        # URLError covers DNS / connection / timeout; HTTPError covers
        # 404 (private repo / no release yet) and other non-2xx. All
        # silent — a private repo must never crash or nag.
        logger.info("Update check skipped (network/HTTP): %s", e)
        return None
    except (ValueError, OSError) as e:
        # ValueError = bad JSON / missing tag; OSError = odd socket path.
        logger.info("Update check skipped (parse/IO): %s", e)
        return None
    except Exception as e:  # noqa: BLE001 — never let a check crash the app.
        logger.info("Update check skipped (unexpected): %s", e)
        return None

    from core import __version__ as local_version
    newer = is_newer(tag, local_version)
    return UpdateInfo(latest_tag=tag, html_url=html_url, is_newer=newer)
