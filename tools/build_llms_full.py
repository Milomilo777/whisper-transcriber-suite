"""Build site/llms-full.txt: the whole project story in one plain-text fetch.

llms.txt is the short index; llms-full.txt inlines the FAQ from the website's
FAQPage JSON-LD and the README (with badges, images and HTML stripped), so an
AI assistant gets complete context without following links to GitHub.

    python tools/build_llms_full.py            # rewrite site/llms-full.txt
    python tools/build_llms_full.py --check    # exit 1 if it is stale

Run by .github/workflows/site-data.yml alongside update_site_data.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://whisper-transcriber-suite.pages.dev"
REPO = "https://github.com/Milomilo777/whisper-transcriber-suite"
OUT = os.path.join(ROOT, "site", "llms-full.txt")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def faq_block(html: str) -> str:
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        data = json.loads(raw)
        if data.get("@type") == "FAQPage":
            qa = [f"### {q['name']}\n\n{q['acceptedAnswer']['text']}" for q in data["mainEntity"]]
            return "## Frequently asked questions\n\n" + "\n\n".join(qa)
    return ""


def clean_readme(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"<(div|p|details|summary|sub|br|img|picture|source|a)\b[^>]*>|</(div|p|details|summary|sub|a|picture)>", "", md)
    md = re.sub(r"^\s*\[!\[.*$", "", md, flags=re.M)          # badge lines
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)                # inline images
    md = re.sub(r"\]\((?!https?://|#|mailto:)([^)]+)\)", lambda m: f"]({REPO}/blob/master/{m.group(1)})", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def build() -> str:
    head = _read("site", "llms.txt").strip()
    return (
        f"{head}\n\n"
        f"---\n\n"
        f"# Full text\n\n"
        f"Website: {SITE}/ · Source: {REPO}\n\n"
        f"{faq_block(_read('site', 'index.html'))}\n\n"
        f"---\n\n"
        f"# README\n\n"
        f"{clean_readme(_read('README.md'))}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Build site/llms-full.txt.")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    new = build()
    old = _read("site", "llms-full.txt") if os.path.exists(OUT) else ""
    if args.check:
        print("stale" if new != old else "current")
        return 1 if new != old else 0
    if new != old:
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        print("updated: site/llms-full.txt")
    else:
        print("site/llms-full.txt already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
