"""GitHub "update available" check (Tk-free; on by default, notify-only).

This module is pure engine code: it never imports tkinter and is safe
to call from a background daemon thread. The UI glue in ``app/`` is
responsible for marshalling the result back onto the Tk main thread
and for showing the quiet update bar (``app.widgets.update_bar``).

Behaviour contract (deliberately conservative — this must never nag):

  * It only ever NOTIFIES. It never downloads or installs anything;
    the UI offers to open the right download in a browser, nothing more.
  * Every network / HTTP / JSON / parsing error is swallowed and the
    public ``check_for_update`` returns ``None``. A PRIVATE repo's
    ``releases/latest`` endpoint returns HTTP 404 — that path must be
    silent (return ``None``), never crash and never surface an error.
  * The version comparison is tolerant of a leading ``v`` and of odd
    or pre-release tags (e.g. ``v1.4.0-rc1``); it never raises on a
    malformed tag, it just compares the numeric dotted prefix.
  * The notice rules (Later = snooze 3 / 7 / 14 days, then only passive
    signs; Skip this version = silent until a newer one) are pure
    functions over the config dict, so they are testable without Tk.
    Their keys are local-only: the online config can never set them
    (``core.config.LOCAL_ONLY_KEYS``).

The in-place Standard installer upgrade is a SEPARATE concern (the
installer uses a stable AppId, so running a newer Setup upgrades over
the old install with no uninstall). This module does not touch that;
it only points the user at the download for their kind of install.
"""
from __future__ import annotations

import json
import logging
import os
import platform as _platform
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, MutableMapping, NamedTuple

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
    show a notice; ``latest_tag`` / ``html_url`` feed the message + the
    "Full release notes" link. ``html_url`` falls back to
    :data:`RELEASES_PAGE_URL` when the API response omits it.
    ``headline`` / ``highlights`` come from the release body (see
    :func:`release_headline` / :func:`release_highlights`) and ``assets``
    lists the names of the release's fully uploaded files.
    """

    latest_tag: str
    html_url: str
    is_newer: bool
    headline: str = ""
    highlights: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()


class ReleaseDetails(NamedTuple):
    """Everything the update notice reads from one ``releases/latest`` answer."""

    tag: str
    html_url: str
    headline: str
    highlights: tuple[str, ...]
    assets: tuple[str, ...]


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
    details = parse_release(text)
    return details.tag, details.html_url


def parse_release(text: str) -> ReleaseDetails:
    """Parse a GitHub ``releases/latest`` JSON body into :class:`ReleaseDetails`.

    Same errors as :func:`parse_release_json`. A missing or odd ``body`` /
    ``assets`` field only empties the headline, highlights or asset list:
    the tag alone is enough for a notice. Assets still being uploaded
    (``state`` other than ``"uploaded"``) are left out, so a release whose
    file for this computer is not there yet looks like one without it.
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
    body = data.get("body")
    if not isinstance(body, str):
        body = ""
    names: list[str] = []
    assets = data.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            state = asset.get("state")
            if state is not None and state != "uploaded":
                continue
            names.append(name.strip())
    return ReleaseDetails(
        tag=tag.strip(),
        html_url=html_url.strip(),
        headline=release_headline(body),
        highlights=release_highlights(body),
        assets=tuple(names),
    )


# --- Release notes excerpt ---------------------------------------------------
# The published release notes start with a "# <name> vX.Y.Z" title, a
# one-paragraph intro and the "## Download" table, then "## Highlights" bullets
# (docs/RELEASE_PROCESS.md, step 3). The bar shows the intro's first sentence;
# "What's new" shows the first three highlights as plain text.

_HEADLINE_MAX_CHARS = 160
_HIGHLIGHT_COUNT = 3
_HIGHLIGHTS_MAX_CHARS = 600
# Only the start of the body is read: the excerpt lives there.
_MAX_BODY_CHARS = 20_000
# "## Highlights", "## ✨ Highlights", "## What's new", "## What’s new".
_HIGHLIGHTS_HEADING = re.compile(
    r"^#{1,6}\s*(?:[^\w\s]+\s*)?(highlights|what['’]?s new)\b", re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^([-*+]|\d+[.)])\s+(.*)$")
# No "[" inside the link text, so a long run of unmatched "[" stays linear.
_MD_IMAGE_OR_LINK = re.compile(r"!?\[([^\[\]]*)\]\([^()]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_MD_STRONG = re.compile(r"\*\*(.+?)\*\*")
_MD_EMPHASIS = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_MD_CODE = re.compile(r"`([^`]*)`")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def _body_lines(body: str) -> list[str]:
    return body[:_MAX_BODY_CHARS].replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _plain_text(markdown: str) -> str:
    """Inline Markdown to plain text: links keep their text, paired bold /
    italic / code marks and HTML tags go (a lone ``*`` as in ``*.srt`` stays),
    whitespace collapses to single spaces."""
    text = _MD_IMAGE_OR_LINK.sub(r"\1", markdown)
    text = _HTML_TAG.sub("", text)
    text = _MD_STRONG.sub(r"\1", text)
    text = _MD_EMPHASIS.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    return " ".join(text.split())


def _clip(text: str, max_chars: int) -> str:
    """Cut ``text`` to at most ``max_chars`` characters at a word boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def _clip_sentences(text: str, max_chars: int) -> str:
    """Keep whole sentences while they fit; word-clip a first sentence that is
    longer than ``max_chars`` on its own."""
    if len(text) <= max_chars:
        return text
    kept = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        kept = candidate
    return kept or _clip(text, max_chars)


def _starts_block(line: str) -> bool:
    """True for a stripped line that opens a table, quote, list, fence or comment."""
    return (
        line.startswith(("|", ">", "```", "~~~", "<!--"))
        or _LIST_ITEM.match(line) is not None
    )


def release_headline(body: str) -> str:
    """The first sentence of the release body's intro paragraph, as plain text.

    Leading headings (the release title) and blank lines are skipped; a body
    that starts with a table, list, quote or code block has no intro and
    gives ``""``. Capped at about 160 characters.
    """
    lines = _body_lines(body)
    paragraph: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not paragraph:
            if not line or line.startswith("#"):
                continue
            if _starts_block(line):
                return ""
            paragraph.append(line)
        elif not line or line.startswith("#") or _starts_block(line):
            break
        else:
            paragraph.append(line)
    text = _plain_text(" ".join(paragraph))
    if not text:
        return ""
    first = _SENTENCE_END.split(text, maxsplit=1)[0]
    return _clip(first, _HEADLINE_MAX_CHARS)


def release_highlights(body: str) -> tuple[str, ...]:
    """The first three top-level bullets of the "Highlights" section, as plain text.

    A bullet's indented continuation lines belong to it; nested bullets and
    lines of a following section do not. Each bullet keeps whole sentences
    up to a third of the 600-character budget. No such section gives ``()``.
    """
    lines = _body_lines(body)
    in_section = False
    items: list[list[str]] = []
    closed = False  # the current bullet ended (a nested bullet or an unindented line)
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            if in_section:
                break
            in_section = _HIGHLIGHTS_HEADING.match(line) is not None
            continue
        if not in_section or not line:
            continue
        indented = raw[:1].isspace()
        item = _LIST_ITEM.match(line)
        if item and not indented:
            items.append([item.group(2)])
            closed = False
        elif items and indented and not item and not closed:
            items[-1].append(line)
        else:
            closed = True
    per_item = _HIGHLIGHTS_MAX_CHARS // _HIGHLIGHT_COUNT
    out: list[str] = []
    for parts in items:
        text = _plain_text(" ".join(parts))
        if text:
            out.append(_clip_sentences(text, per_item))
        if len(out) == _HIGHLIGHT_COUNT:
            break
    return tuple(out)


# --- Kind of install and the matching download -------------------------------

INSTALL_WINDOWS_INSTALLER = "windows-installer"
INSTALL_WINDOWS_PORTABLE = "windows-portable"
INSTALL_MACOS_APP = "macos-app"
INSTALL_SOURCE = "source"
INSTALL_UNKNOWN = "unknown"

#: Kinds that have their own release file; the notice waits until it is uploaded.
_KINDS_WITH_A_FILE = frozenset({
    INSTALL_WINDOWS_INSTALLER, INSTALL_WINDOWS_PORTABLE, INSTALL_MACOS_APP,
})

#: The launcher build_embed_installer.bat writes into the embed tree (installer
#: and Portable ZIP); only the installer adds its uninstaller (unins000.exe).
PORTABLE_LAUNCHER = "Run Whisper Transcriber Suite.bat"

# Release file names (docs/BUILD.md, "Release file names").
_ASSET_PATTERNS: dict[str, re.Pattern[str]] = {
    INSTALL_WINDOWS_INSTALLER: re.compile(r"installer.*windows.*\.exe$", re.IGNORECASE),
    INSTALL_WINDOWS_PORTABLE: re.compile(r"portable.*windows.*\.zip$", re.IGNORECASE),
}


def detect_install_kind(
    app_dir: Path,
    *,
    sys_platform: str | None = None,
    frozen: bool | None = None,
) -> str:
    """Which kind of copy is running, from the files beside it.

    ``app_dir`` is ``core.hub.resolve_app_dir()``. Windows installer: an Inno
    uninstaller (``unins000.exe``) in it; Windows Portable: the launcher batch
    file and no uninstaller; macOS app: a frozen build on ``darwin``; source:
    a git checkout. Anything else (or a filesystem error) is ``unknown``,
    whose Download button opens the release page.
    """
    sys_platform = sys.platform if sys_platform is None else sys_platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    try:
        if sys_platform == "darwin" and frozen:
            return INSTALL_MACOS_APP
        if sys_platform == "win32":
            if any(app_dir.glob("unins0*.exe")):
                return INSTALL_WINDOWS_INSTALLER
            if (app_dir / PORTABLE_LAUNCHER).is_file():
                return INSTALL_WINDOWS_PORTABLE
        if not frozen and (app_dir / ".git").exists():
            return INSTALL_SOURCE
    except OSError:
        logger.debug("Could not inspect %s for the install kind", app_dir, exc_info=True)
    return INSTALL_UNKNOWN


def kind_has_a_release_file(kind: str) -> bool:
    """True when this kind of install downloads its own file from the release."""
    return kind in _KINDS_WITH_A_FILE


def pick_asset(kind: str, asset_names: tuple[str, ...], *, machine: str | None = None) -> str | None:
    """The release file for this kind of install, or ``None``.

    macOS picks the dmg for this CPU (``arm64`` on Apple silicon, else
    ``x64``); source and unknown installs have no file.
    """
    if kind == INSTALL_MACOS_APP:
        cpu = (machine if machine is not None else _platform.machine()).lower()
        arch = "arm64" if cpu in ("arm64", "aarch64") else "x64"
        pattern: re.Pattern[str] | None = re.compile(rf"macos-{arch}\.dmg$", re.IGNORECASE)
    else:
        pattern = _ASSET_PATTERNS.get(kind)
    if pattern is None:
        return None
    for name in asset_names:
        if pattern.search(name):
            return name
    return None


def asset_download_url(tag: str, name: str) -> str:
    """Direct download link of one release file, built from the pinned repo.

    Built from the tag and the file name rather than taken from the API
    answer, so the link can only point at this repository's releases.
    """
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
        f"{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(name, safe='')}"
    )


def update_command(app_dir: Path, *, sys_platform: str | None = None) -> str:
    """The command that updates a source checkout (shown, never run).

    Linux: ``platform/linux/update.sh``; Windows: ``platform\\windows\\update.bat``;
    otherwise a plain fast-forward ``git pull``.
    """
    sys_platform = sys.platform if sys_platform is None else sys_platform
    if sys_platform == "win32":
        script = app_dir / "platform" / "windows" / "update.bat"
        if script.is_file():
            # "cmd /c" runs it from cmd and from PowerShell alike (PowerShell
            # only prints a bare quoted path).
            return f'cmd /c "{script}"'
        return f'git -C "{app_dir}" pull --ff-only'
    script = app_dir / "platform" / "linux" / "update.sh"
    if sys_platform.startswith("linux") and script.is_file():
        return f"bash {shlex.quote(script.as_posix())}"
    return f"git -C {shlex.quote(app_dir.as_posix())} pull --ff-only"


# --- Notice rules (pure; the keys are local-only, see core.config) -----------

#: Days the bar stays away after the 1st, 2nd and 3rd "Later" for one version.
#: After the 4th "Later" only the passive signs remain (Help menu dot, About line).
SNOOZE_LADDER_DAYS: tuple[int, ...] = (3, 7, 14)

NOTICE_BAR = "bar"
NOTICE_PASSIVE = "passive"
NOTICE_NONE = "none"

#: Set to 1 (or true / yes / on) to turn the automatic check off on a managed
#: machine. The Help menu item still checks when asked.
DISABLE_ENV_VAR = "WTS_DISABLE_UPDATER"


def version_label(tag: str) -> str:
    """``v1.9.4`` -> ``1.9.4`` (the form shown to users and stored in config)."""
    s = tag.strip()
    return s[1:] if s[:1] in ("v", "V") else s


def disabled_by_environment(environ: Mapping[str, str] | None = None) -> bool:
    """True when :data:`DISABLE_ENV_VAR` asks for no automatic check."""
    env = os.environ if environ is None else environ
    return env.get(DISABLE_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def automatic_check_enabled(
    config: Mapping[str, Any], environ: Mapping[str, str] | None = None,
) -> bool:
    """The quiet launch check and the passive signs run only when this is True."""
    return bool(config.get("update_check_enabled", True)) and not disabled_by_environment(environ)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def note_latest(config: MutableMapping[str, Any], tag: str) -> bool:
    """Remember the latest release a check found. Another version restarts the ladder.

    Usually that is a newer release; an older one means the newer release was
    withdrawn, and the bar, Skip and the Help-menu dot must then talk about
    the release that really is the latest. Returns True when ``config``
    changed (the caller saves it).
    """
    seen = str(config.get("update_latest_seen") or "")
    if seen and not is_newer(tag, seen) and not is_newer(seen, tag):
        return False  # the same version
    config["update_latest_seen"] = version_label(tag)
    config["update_snooze_count"] = 0
    config["update_snooze_until"] = ""
    return True


def is_skipped(config: Mapping[str, Any], tag: str) -> bool:
    """True when the user chose "Skip this version" for ``tag`` (or a newer one)."""
    skipped = str(config.get("update_skipped_version") or "")
    return bool(skipped) and not is_newer(tag, skipped)


def skip_version(config: MutableMapping[str, Any], tag: str) -> None:
    """"Skip this version": silent for ``tag`` until a newer version appears."""
    config["update_skipped_version"] = version_label(tag)


def stop_skipping(config: MutableMapping[str, Any]) -> None:
    config["update_skipped_version"] = ""


def snooze(config: MutableMapping[str, Any], today: date) -> date | None:
    """"Later": the next step of the 3 / 7 / 14 day ladder.

    Returns the day the bar may come back, or ``None`` once the ladder is
    used up (from then on only the passive signs remain for this version).
    """
    count = max(0, _as_int(config.get("update_snooze_count"))) + 1
    config["update_snooze_count"] = count
    if count > len(SNOOZE_LADDER_DAYS):
        config["update_snooze_until"] = ""
        return None
    until = today + timedelta(days=SNOOZE_LADDER_DAYS[count - 1])
    config["update_snooze_until"] = until.isoformat()
    return until


def _snoozed(config: Mapping[str, Any], today: date) -> bool:
    try:
        until = date.fromisoformat(str(config.get("update_snooze_until") or ""))
    except ValueError:
        return False
    # A date further out than the longest step (a clock that was wrong when
    # Later was clicked) must not hide the bar for months.
    return today < until <= today + timedelta(days=max(SNOOZE_LADDER_DAYS))


def notice_level(config: Mapping[str, Any], local_version: str, today: date) -> str:
    """How loudly to tell the user about the newest version seen.

    :data:`NOTICE_BAR` (the bar may show), :data:`NOTICE_PASSIVE` (snoozed or
    the ladder is used up: Help menu dot and About line only) or
    :data:`NOTICE_NONE` (up to date, nothing seen, or this version skipped).
    """
    latest = str(config.get("update_latest_seen") or "")
    if not latest or not is_newer(latest, local_version) or is_skipped(config, latest):
        return NOTICE_NONE
    if _as_int(config.get("update_snooze_count")) > len(SNOOZE_LADDER_DAYS):
        return NOTICE_PASSIVE
    if _snoozed(config, today):
        return NOTICE_PASSIVE
    return NOTICE_BAR


def passive_sign_version(
    config: Mapping[str, Any],
    local_version: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    """The version the Help menu dot and the About line name, or ``""``.

    Shown for any newer, unskipped version seen while automatic checks are on
    (no network: it reads the stored ``update_latest_seen``).
    """
    if not automatic_check_enabled(config, environ):
        return ""
    latest = str(config.get("update_latest_seen") or "")
    if not latest or not is_newer(latest, local_version) or is_skipped(config, latest):
        return ""
    return version_label(latest)


def bar_text(tag: str, local_version: str, headline: str) -> str:
    """The one line the update bar shows."""
    text = (
        f"Version {version_label(tag)} is available "
        f"(you have {version_label(local_version)})."
    )
    return f"{text}  {headline}" if headline else text


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
    gentle "couldn't reach the server" note. Work offline returns ``None``
    without a request (the Help menu item says so before it gets here).
    """
    from core import offline
    if offline.is_offline():
        logger.info("Update check skipped: offline mode is on")
        return None
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
        details = parse_release(text)
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
    return UpdateInfo(
        latest_tag=details.tag,
        html_url=details.html_url,
        is_newer=is_newer(details.tag, local_version),
        headline=details.headline,
        highlights=details.highlights,
        assets=details.assets,
    )
