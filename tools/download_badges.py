"""Generate static release download badges from the GitHub REST API."""
from __future__ import annotations

import argparse
from html import escape
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


API_HOST = "api.github.com"
TEAL = "207a80"
GREY = "8a8a8a"
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
PORTABLE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+-]{0,229}")
WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)

# Approximate Verdana glyph widths at 11 px, with padding for each segment.
CHAR_WIDTH = dict.fromkeys(" .'ilIjtfr", 4) | dict.fromkeys("mwMW@%", 10)
CHAR_WIDTH.update(dict.fromkeys("-+/:()[]", 5))
CHAR_WIDTH.update(dict.fromkeys("ABCDEFGHKNOPQRSTUVWXYZ", 8))


def format_count(count: int) -> str:
    if count < 1000:
        return str(count)
    scale = 1000
    for suffix in "kMBT":
        # Round with integers so a tie behaves consistently at every scale.
        if count < 10 * scale:
            tenths = (10 * count + scale // 2) // scale
        else:
            tenths = 10 * ((count + scale // 2) // scale)
        if tenths < 10_000 or suffix == "T":
            whole, fraction = divmod(tenths, 10)
            return f"{whole}.{fraction}{suffix}" if fraction else f"{whole}{suffix}"
        scale *= 1000
    raise AssertionError("Missing largest badge count unit")


def text_width(text: str) -> int:
    return sum(CHAR_WIDTH.get(char, 7) for char in text) + 10


def render_badge(label: str, value: str, color: str) -> bytes:
    left, right = text_width(label), text_width(value)
    width = left + right
    title = escape(f"{label}: {value}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  <clipPath id="rounded"><rect width="{width}" height="20" rx="3"/></clipPath>
  <g clip-path="url(#rounded)">
    <rect width="{left}" height="20" fill="#555"/>
    <rect x="{left}" width="{right}" height="20" fill="#{color}"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="{left / 2:g}" y="14">{escape(label)}</text>
    <text x="{left + right / 2:g}" y="14">{escape(value)}</text>
  </g>
</svg>
'''.encode("utf-8")


def release_counts(repository: str, token: str) -> dict[str, int]:
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub repository in OWNER/REPO format")
    endpoint = f"/repos/{repository}/releases"
    url = f"https://{API_HOST}{endpoint}?per_page=100"
    visited: set[str] = set()
    published: dict[str, int] = {}
    drafts: set[str] = set()
    while url:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != API_HOST or
                (parts.path != endpoint and not re.fullmatch(r"/repositories/\d+/releases", parts.path))):
            raise ValueError("Unexpected GitHub release pagination URL")
        if url in visited:
            raise ValueError("GitHub release pagination repeated a page")
        visited.add(url)
        request = Request(url, headers={"Accept": "application/vnd.github+json"})
        # Do not send credentials along with an automatic redirect.
        request.add_unredirected_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=30) as response:
            page = json.load(response)
            next_link = NEXT_LINK.search(response.headers.get("Link", ""))
        if not isinstance(page, list):
            raise ValueError("Expected a GitHub release list")
        for release in page:
            tag = release["tag_name"]
            draft = release["draft"]
            if type(draft) is not bool:
                raise ValueError("Invalid draft flag in GitHub release list")
            if draft and tag in (None, ""):
                continue  # An untagged draft has no badge URL yet.
            if (not isinstance(tag, str) or not PORTABLE_TAG.fullmatch(tag) or
                    WINDOWS_DEVICE.fullmatch(tag.split(".", 1)[0])):
                raise ValueError("GitHub release tag cannot be used as a portable badge filename")
            if draft:
                drafts.add(tag)
                continue
            assets = release["assets"]
            if not isinstance(assets, list):
                raise ValueError("Expected a GitHub release asset list")
            counts = [asset["download_count"] for asset in assets]
            if any(type(count) is not int or count < 0 for count in counts):
                raise ValueError("Invalid download count in GitHub release list")
            count = sum(counts)
            if published.setdefault(tag, count) != count:
                raise ValueError("GitHub returned conflicting counts for a release tag")
        url = next_link[1] if next_link else ""
    if not (drafts or published):
        raise ValueError("GitHub returned no tagged releases")
    return dict.fromkeys(drafts, 0) | published


def badge_files(counts: dict[str, int]) -> dict[str, bytes]:
    total = format_count(sum(counts.values()))
    files = {"total.svg": render_badge("downloads", total, TEAL),
             "total-all-versions.svg": render_badge("all versions", total, TEAL)}
    filenames = set(files)
    for tag, count in sorted(counts.items()):
        value = format_count(count)
        for name, label, color in ((f"{tag}.svg", tag, TEAL),
                                   (f"{tag}-grey.svg", tag, GREY),
                                   (f"{tag}-this-version.svg", "this version", TEAL)):
            if name.casefold() in filenames:
                raise ValueError(f"Badge filename collision: {name}")
            filenames.add(name.casefold())
            files[name] = render_badge(label, value, color)
    return files


def write_badges(output: Path, files: dict[str, bytes]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".badges-", dir=output) as temporary:
        # Stage complete files on the same volume before replacing existing ones.
        staged = Path(temporary)
        for name, data in files.items():
            destination = output / name
            if not destination.is_symlink() and destination.is_file() and destination.read_bytes() == data:
                continue
            (staged / name).write_bytes(data)
        for path in staged.iterdir():
            path.replace(output / path.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="GitHub OWNER/REPO")
    parser.add_argument("output", type=Path, help="directory for generated SVG files")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required to read draft releases", file=sys.stderr)
        return 1
    try:
        files = badge_files(release_counts(args.repository, token))
        write_badges(args.output, files)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Download badges: {exc}", file=sys.stderr)
        return 1
    print(f"Generated {len(files)} download badges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
