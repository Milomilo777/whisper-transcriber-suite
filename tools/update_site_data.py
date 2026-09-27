"""Refresh the release facts baked into the website from the GitHub API.

Fills the ``data-auto`` / ``data-auto-href`` markers in site/index.html
(version, release date, file sizes, direct download links, total downloads)
plus the matching lines in the JSON-LD block and both llms.txt files, so
search engines and AI crawlers see current numbers without running any
JavaScript.

    python tools/update_site_data.py            # rewrite files in place
    python tools/update_site_data.py --check    # exit 1 if anything is stale

Uses GITHUB_TOKEN from the environment when present (higher rate limit);
works anonymously otherwise. Run by .github/workflows/site-data.yml on every
published release and once a week.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

REPO = "Milomilo777/whisper-transcriber-suite"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "site", "index.html")
LLMS = [os.path.join(ROOT, "site", "llms.txt"), os.path.join(ROOT, "llms.txt")]

# Release file name patterns (see docs/BUILD.md "Release file names").
ASSETS = {
    "installer": re.compile(r"-Installer-Windows-v[\d.]+\.exe$"),
    "portable": re.compile(r"-Portable-Windows-v[\d.]+\.zip$"),
    "mac-arm64": re.compile(r"-macOS-arm64\.dmg$"),
    "mac-x64": re.compile(r"-macOS-x64\.dmg$"),
}


def _get(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "site-data"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch() -> dict:
    latest = _get(f"https://api.github.com/repos/{REPO}/releases/latest")
    total = 0
    page = 1
    while True:
        batch = _get(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}")
        if not batch:
            break
        for rel in batch:
            total += sum(a["download_count"] for a in rel["assets"] if not a["name"].endswith(".sha256"))
        page += 1
    files = {}
    for key, pat in ASSETS.items():
        asset = next((a for a in latest["assets"] if pat.search(a["name"])), None)
        if asset:
            files[key] = {"url": asset["browser_download_url"], "mb": round(asset["size"] / 1048576)}
    return {
        "version": latest["tag_name"],
        "released": latest["published_at"][:10],
        "downloads": total,
        "files": files,
    }


def downloads_label(n: int) -> str:
    """Round down so the page never overstates: 912 -> '900+', 1234 -> '1,200+'."""
    if n < 100:
        return str(n)
    return f"{n // 100 * 100:,}+"


def _set_text(html: str, key: str, value: str) -> str:
    pat = re.compile(r'(<(\w+)[^>]*\bdata-auto="%s"[^>]*>)(.*?)(</\2>)' % re.escape(key), re.S)
    return pat.sub(lambda m: m.group(1) + value + m.group(4), html)


def _set_href(html: str, key: str, url: str) -> str:
    pat = re.compile(r'<a\b[^>]*\bdata-auto-href="%s"[^>]*>' % re.escape(key))
    return pat.sub(lambda m: re.sub(r'(?<![\w-])href="[^"]*"', f'href="{url}"', m.group(0), count=1), html)


def render_page(html: str, d: dict) -> str:
    html = _set_text(html, "version", d["version"])
    html = _set_text(html, "released", d["released"])
    html = _set_text(html, "downloads", downloads_label(d["downloads"]))
    for key, f in d["files"].items():
        html = _set_text(html, f"size-{key}", f"~{f['mb']}&nbsp;MB")
        html = _set_href(html, key, f["url"])
    html = re.sub(r'"softwareVersion": "[^"]*"', f'"softwareVersion": "{d["version"].lstrip("v")}"', html)
    html = re.sub(r'"dateModified": "[^"]*"', f'"dateModified": "{d["released"]}"', html)
    html = re.sub(r'"userInteractionCount": \d+', f'"userInteractionCount": {d["downloads"]}', html)
    return html


def render_llms(text: str, d: dict) -> str:
    text = re.sub(r"\): v[\d.]+ — free Windows installer", f"): {d['version']} — free Windows installer", text)
    text = re.sub(r"Latest version v[\d.]+, released \d{4}-\d{2}-\d{2}",
                  f"Latest version {d['version']}, released {d['released']}", text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the website's release data from GitHub.")
    ap.add_argument("--check", action="store_true", help="report stale files instead of writing")
    args = ap.parse_args()

    data = fetch()
    print(f"{data['version']} released {data['released']}, {data['downloads']} downloads, "
          f"files: {', '.join(sorted(data['files']))}")
    stale = []
    for path, render in [(PAGE, render_page)] + [(p, render_llms) for p in LLMS]:
        with open(path, encoding="utf-8", newline="") as fh:
            old = fh.read()
        new = render(old, data)
        if new != old:
            stale.append(os.path.relpath(path, ROOT))
            if not args.check:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
    print(("stale: " if args.check else "updated: ") + (", ".join(stale) or "nothing"))
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
