"""Supreme Master TV episode scraper.

The site exposes per-episode video / audio download URLs through a
JavaScript ``videoPlayerData`` global on every episode page, and a
plain-text transcript inside ``<div class="article-text">``. This
module:

  * recognises SMTV episode URLs
  * fetches an episode page over HTTPS (stdlib urllib)
  * parses out every quality variant + the audio track + the
    transcript + the sibling-parts playlist
  * exposes helpers the download / format services use to populate
    the existing Download tab

No yt-dlp involvement. No new third-party dependency.

See ``docs/integrations/smtv-research.md`` for the URL / DOM contract
this module relies on, and ``docs/integrations/smtv-brief.md`` for
how it plugs into the Download tab.
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- regexes --

SMTV_HOST_RE = re.compile(r"^https?://(?:www\.)?suprememastertv\.com/", re.I)
# Anchor the path with ``.html`` but allow an optional ``?query`` /
# ``#fragment`` so real shareable links (autoplay/tracking params,
# browser-appended fragments) are still recognised as episodes instead
# of falling through to the yt-dlp probe, which rejects SMTV URLs.
SMTV_EPISODE_RE = re.compile(
    r"^https?://(?:www\.)?suprememastertv\.com/([a-z]{2,3})1/v/(\d{6,})\.html(?:[?#].*)?$",
    re.I,
)

_VIDEOFILE_RE = re.compile(
    r"""videoPlayerData\[\s*["']videoFile["']\s*\]\.push\(\s*new\s+Array\(\s*"""
    r"""['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\)"""
)
_POSTER_RE = re.compile(
    r"""videoPlayerData\[\s*["']videoPoster["']\s*\]\s*=\s*["']([^'"]+)["']"""
)
_YID_RE = re.compile(
    r"""videoPlayerData\[\s*["']youTubeUrl["']\s*\]\s*=\s*["']([^'"]*)["']"""
)
_LENGTH_RE = re.compile(
    r"""videoPlayerData\[\s*["']videoLength["']\s*\]\s*=\s*["']([^'"]+)["']"""
)
_ARTICLE_TITLE_RE = re.compile(
    r'<h1[^>]*id="article-title"[^>]*>(.*?)</h1>', re.S
)
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.S)
_ARTICLE_TEXT_RE = re.compile(
    r'<div\s+class="article-text"\s+id="article-text">(.*?)</div>'
    r'(?=\s*(?:<div[^>]*class="article-thumb"|</div>\s*</div>\s*</div>\s*</article>))',
    re.S,
)
_PLAYLIST_MARKER_RE = re.compile(
    r'<div\s+[^>]*class="playlist-contaner"', re.I
)
_PLAYLIST_END_RE = re.compile(r'<footer\b|id="footer"', re.I)
_PLAYLIST_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*?href="\.\./v/(\d+)\.html"[^>]*?title="([^"]+)"',
)
_PART_RE = re.compile(r"\bPart\s+(\d+)\s+of\s+(\d+)\b", re.I)

_CDN_PREFIX = "https://cf-vdo.suprememastertv.com/vod/video/download-mp4.php?file="
_DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperTranscriberSuite"
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------- types ----


class SmtvError(RuntimeError):
    """Raised when an SMTV page can't be parsed or fetched."""


@dataclass(frozen=True)
class SmtvFile:
    quality: str
    relative_path: str
    download_url: str


@dataclass(frozen=True)
class SmtvSibling:
    url: str
    title: str
    part: int | None
    total: int | None


@dataclass(frozen=True)
class SmtvEpisode:
    vid: str
    title: str
    page_url: str
    lang_prefix: str
    files: list[SmtvFile] = field(default_factory=list)
    transcript_text: str = ""
    transcript_html: str = ""
    siblings: list[SmtvSibling] = field(default_factory=list)
    poster_url: str | None = None
    youtube_id: str | None = None
    duration_seconds: int | None = None


# ---------------------------------------------------------- public funcs ---


def is_smtv_url(url: str) -> bool:
    """True for any URL on the suprememastertv.com host."""
    return bool(url) and bool(SMTV_HOST_RE.match(url.strip()))


def parse_episode_id(url: str) -> tuple[str, str] | None:
    """Return ``(lang_prefix, vid)`` for an SMTV episode URL or None."""
    if not url:
        return None
    m = SMTV_EPISODE_RE.match(url.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def fetch_episode(url: str, *, timeout: float = 30.0) -> SmtvEpisode:
    """HTTPS GET, parse, return an SmtvEpisode.

    Raises SmtvError on any failure shape so callers only need one
    except clause.
    """
    page_url = (url or "").strip()
    parsed_id = parse_episode_id(page_url)
    if parsed_id is None:
        raise SmtvError(f"not an SMTV episode URL: {page_url!r}")
    lang_prefix, vid = parsed_id

    html_text = _http_get(page_url, timeout=timeout)
    files = _extract_videofiles(html_text)
    if not files:
        raise SmtvError(
            "could not find videoPlayerData['videoFile'] entries on the "
            f"page — the site layout may have changed: {page_url}"
        )

    return SmtvEpisode(
        vid=vid,
        title=_extract_title(html_text) or vid,
        page_url=page_url,
        lang_prefix=lang_prefix,
        files=files,
        transcript_text=_extract_transcript_text(html_text),
        transcript_html=_extract_transcript_html(html_text),
        siblings=_extract_siblings(html_text, page_url),
        poster_url=_extract_poster(html_text, page_url),
        youtube_id=_extract_youtube_id(html_text),
        duration_seconds=_extract_duration(html_text),
    )


def best_url_for_mode(episode: SmtvEpisode, mode: str) -> str:
    """Return the CDN URL for the chosen mode.

    Modes:
      ``video-best`` — highest available video (1080p > 720p > 396p)
      ``video-1080``, ``video-720``, ``video-396`` — exact quality
      ``audio`` — the mp3 file

    Raises SmtvError if the mode is unavailable.
    """
    if not mode:
        raise SmtvError("empty mode")
    if mode == "audio":
        for f in episode.files:
            if f.quality == "audio":
                return f.download_url
        raise SmtvError(f"no audio track for episode {episode.vid}")

    if mode == "video-best":
        # ``max`` is SMTV's recent label for the original-quality
        # video file (sometimes 4K). Pick it first when present so
        # we don't fall back to a lower resolution.
        for want in ("max", "1080p", "720p", "396p"):
            for f in episode.files:
                if f.quality == want:
                    return f.download_url
        # Last-resort: any quality string ending in 'p' (covers future
        # additions like 480p / 2160p without code changes).
        for f in episode.files:
            if f.quality and f.quality.endswith("p"):
                return f.download_url
        raise SmtvError(f"no video file for episode {episode.vid}")

    quality_map = {
        "video-max": "max",
        "video-1080": "1080p",
        "video-720": "720p",
        "video-396": "396p",
    }
    if mode in quality_map:
        want = quality_map[mode]
        for f in episode.files:
            if f.quality == want:
                return f.download_url
        raise SmtvError(f"{want} not available for episode {episode.vid}")

    raise SmtvError(f"unknown mode: {mode!r}")


def filename_for(episode: SmtvEpisode, mode: str) -> str:
    """Suggested basename for the file at ``mode``.

    Uses the CDN basename when present, falling back to a title-based
    name with safe-character sanitisation.
    """
    url = best_url_for_mode(episode, mode)
    cdn_basename = _basename_from_cdn_url(url)
    if cdn_basename:
        # The CDN basename comes from the page's ?file= value, which is
        # attacker-influenceable; run it through the same sanitiser as the
        # title-based fallback so a colon (NTFS ADS) or a reserved device
        # stem (CON/PRN/…) can't reach os.path.join downstream.
        return _sanitise_filename(cdn_basename)
    ext = ".mp3" if mode == "audio" else ".mp4"
    return _sanitise_filename(episode.title) + ext


def transcript_filename(episode: SmtvEpisode) -> str:
    """Basename for the .txt transcript that mirrors the audio file,
    or the first video file if no audio is present."""
    for preferred in ("audio", "video-720", "video-1080", "video-396"):
        try:
            cdn_url = best_url_for_mode(episode, preferred)
        except SmtvError:
            continue
        base = _basename_from_cdn_url(cdn_url)
        if base:
            # Same attacker-influenceable CDN basename as filename_for():
            # sanitise the .txt name so an ADS colon / reserved stem can't
            # slip through the splitext path unguarded.
            return _sanitise_filename(os.path.splitext(base)[0] + ".txt")
    return _sanitise_filename(episode.title) + ".txt"


# ---------------------------------------------------- private extractors --


def _http_get(url: str, *, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _DEFAULT_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        raise SmtvError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SmtvError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise SmtvError(f"timeout fetching {url} after {timeout}s") from e
    except (ConnectionResetError, OSError) as e:
        # The docstring promises callers only need one except clause.
        # ConnectionResetError / generic OSError used to escape past
        # the URLError branch (the audit triggered them by killing
        # the socket mid-handshake).
        raise SmtvError(f"network error fetching {url}: {e}") from e


def _extract_videofiles(html_text: str) -> list[SmtvFile]:
    out: list[SmtvFile] = []
    seen: set[tuple[str, str]] = set()
    for m in _VIDEOFILE_RE.finditer(html_text):
        quality, relative_path = m.group(1), m.group(2)
        key = (quality, relative_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SmtvFile(
                quality=quality,
                relative_path=relative_path,
                download_url=_CDN_PREFIX + urllib.parse.quote(relative_path, safe="/"),
            )
        )
    return out


def _extract_title(html_text: str) -> str:
    m = _ARTICLE_TITLE_RE.search(html_text)
    if m:
        return _strip_tags(m.group(1)).strip()
    m = _TITLE_TAG_RE.search(html_text)
    if m:
        raw = _strip_tags(m.group(1)).strip()
        for sep in (" - Supreme Master Television", " | Supreme Master Television"):
            if raw.endswith(sep):
                return raw[: -len(sep)].strip()
        return raw
    return ""


def _extract_transcript_html(html_text: str) -> str:
    m = _ARTICLE_TEXT_RE.search(html_text)
    return m.group(1).strip() if m else ""


def _extract_transcript_text(html_text: str) -> str:
    html_chunk = _extract_transcript_html(html_text)
    if not html_chunk:
        return ""
    return _strip_tags(html_chunk).strip()


def _extract_siblings(html_text: str, page_url: str) -> list[SmtvSibling]:
    marker = _PLAYLIST_MARKER_RE.search(html_text)
    if not marker:
        return []
    end_match = _PLAYLIST_END_RE.search(html_text, marker.end())
    region = html_text[marker.end() : end_match.start()] if end_match else html_text[marker.end() :]

    my_id = parse_episode_id(page_url)
    my_vid = my_id[1] if my_id else None
    my_lang = my_id[0] if my_id else "en"

    seen: set[str] = set()
    candidates: list[tuple[int, SmtvSibling]] = []
    self_total: int | None = None
    self_prefix: str | None = None

    # First pass: find this episode's own anchor to capture series
    # prefix and total. The current episode appears in the playlist
    # too (as the "vboxcurrent" entry), so we can read it without an
    # extra request.
    for m in _PLAYLIST_ANCHOR_RE.finditer(region):
        sib_vid = m.group(1)
        if sib_vid != my_vid:
            continue
        sib_title = _html.unescape(m.group(2)).strip()
        _, self_total = _parse_part(sib_title)
        self_prefix = _title_prefix_before_part(sib_title)
        break

    for m in _PLAYLIST_ANCHOR_RE.finditer(region):
        sib_vid = m.group(1)
        if sib_vid == my_vid or sib_vid in seen:
            continue
        sib_title = _html.unescape(m.group(2)).strip()
        part, total = _parse_part(sib_title)

        if self_total is not None and total is not None and total != self_total:
            continue
        if self_prefix and not sib_title.startswith(self_prefix):
            continue

        seen.add(sib_vid)
        sib_url = f"https://suprememastertv.com/{my_lang}1/v/{sib_vid}.html"
        candidates.append(
            (
                part if part is not None else 10**9,
                SmtvSibling(url=sib_url, title=sib_title, part=part, total=total),
            )
        )

    candidates.sort(key=lambda kv: kv[0])
    return [sib for _, sib in candidates]


def _extract_poster(html_text: str, page_url: str) -> str | None:
    m = _POSTER_RE.search(html_text)
    if not m:
        return None
    return urllib.parse.urljoin(page_url, m.group(1))


def _extract_youtube_id(html_text: str) -> str | None:
    m = _YID_RE.search(html_text)
    if not m:
        return None
    yid = m.group(1).strip()
    return yid or None


def _extract_duration(html_text: str) -> int | None:
    m = _LENGTH_RE.search(html_text)
    if not m:
        return None
    parts = m.group(1).split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def _parse_part(title: str) -> tuple[int | None, int | None]:
    m = _PART_RE.search(title)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _title_prefix_before_part(title: str) -> str | None:
    m = _PART_RE.search(title)
    if not m:
        return None
    return title[: m.start()].rstrip(", ").strip()


def _basename_from_cdn_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    files = qs.get("file") or []
    if not files:
        return None
    return os.path.basename(files[0])


_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def _sanitise_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip()
    if not cleaned:
        return "smtv_episode"
    # Windows reserves CON / PRN / AUX / NUL / COM1-9 / LPT1-9 as
    # device names — writing a file with that stem fails with OSError.
    # Treat the stem (everything before the first dot) and prefix '_'
    # when it collides.
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned


class _TextStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._block_close = {"p", "div", "br", "li"}

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._block_close:
            self._chunks.append("\n\n")

    def handle_data(self, data):
        self._chunks.append(data)

    def handle_entityref(self, name):
        self._chunks.append(_html.unescape("&" + name + ";"))

    def handle_charref(self, name):
        self._chunks.append(_html.unescape("&#" + name + ";"))

    def value(self) -> str:
        raw = "".join(self._chunks)
        lines = [line.rstrip() for line in raw.split("\n")]
        cleaned: list[str] = []
        empty_streak = 0
        for line in lines:
            if line.strip():
                cleaned.append(line)
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak <= 1:
                    cleaned.append("")
        return "\n".join(cleaned).strip()


def _strip_tags(html_text: str) -> str:
    parser = _TextStripper()
    parser.feed(html_text)
    parser.close()
    return parser.value()


# ---------------------------------------------------------------- limits --


def warn_time_range_unsupported(url: str) -> None:
    """Log a single WARN explaining that SMTV ignores time-range slicing.

    The Download tab in v1.0.3 lets the user enter Start/End times to
    request only a slice of the source video. yt-dlp implements that
    via ``--download-sections``, but the SMTV scraper here downloads
    over plain HTTP from the CDN — no server-side slicing is
    available. The downloader still proceeds; this warning makes sure
    the user is told why they got the full clip.

    Documented in ``docs/integrations/smtv-brief.md`` under "Known
    limitations".
    """
    logger.warning(
        "Time-range download is not supported for Supreme Master TV URLs "
        "in this release; downloading the full clip. (url=%s)",
        url,
    )
