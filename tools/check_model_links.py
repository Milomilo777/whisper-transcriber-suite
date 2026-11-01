"""Weekly link check for the models and scripts the app and the website's Try page download.

Run by .github/workflows/model-links-weekly.yml (also by hand). It reads the Hugging Face repositories named in
core/model_manager.py, core/language_models.py and site/try/try-worker.js, plus the script URLs in site/try/, and asks
the hosts whether each still exists. Exit code 1 when a link is gone (404, 410, 401, 403) or unreachable after retries;
a rate limit (429) only warns.
Usage: python tools/check_model_links.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
HF_API = "https://huggingface.co/api/models/"
RETRIES = 3

Fetch = Callable[[str], tuple[int, bytes]]


def hf_repos(root: Path = ROOT) -> dict[str, str]:
    """Hugging Face repository ids mapped to where they were found."""
    found: dict[str, str] = {}
    for rel in ("core/model_manager.py", "core/language_models.py"):
        text = (root / rel).read_text(encoding="utf-8")
        for repo in re.findall(r'"hf_repo"\s*:\s*"([^"]+/[^"]+)"', text):
            found.setdefault(repo, rel)
    worker = (root / "site/try/try-worker.js").read_text(encoding="utf-8")
    for repo in re.findall(r"'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)'", worker):
        if repo.startswith("onnx-community/"):
            found.setdefault(repo, "site/try/try-worker.js")
    return found


def script_urls(root: Path = ROOT) -> dict[str, str]:
    """Script URLs (CDN) loaded by the Try page, mapped to the file that names them."""
    found: dict[str, str] = {}
    for path in (root / "site/try").glob("*"):
        if path.suffix not in (".js", ".html"):
            continue
        for url in re.findall(r"https://cdn\.jsdelivr\.net/[A-Za-z0-9@._/+-]+", path.read_text(encoding="utf-8")):
            found.setdefault(url, f"site/try/{path.name}")
    return found


def http_fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "wts-link-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def check(url: str, fetch: Fetch, sleep: Callable[[float], None] = time.sleep) -> tuple[int, bytes]:
    """Fetch with retries on network errors and 5xx; 429 is returned as it is (the caller warns)."""
    status, body = 0, b""
    for attempt in range(RETRIES):
        status, body = fetch(url)
        if status and status < 500:
            return status, body
        sleep(2 * (attempt + 1))
    return status, body


def run(fetch: Fetch = http_fetch, root: Path = ROOT, sleep: Callable[[float], None] = time.sleep) -> tuple[int, list[str]]:
    lines: list[str] = []
    bad = 0
    for repo, where in sorted(hf_repos(root).items()):
        status, body = check(HF_API + repo, fetch, sleep)
        ok = status == 200
        if ok:
            try:
                ok = bool(json.loads(body.decode("utf-8")).get("siblings"))  # the repo must list files
            except ValueError:
                ok = False
        if status == 429:
            lines.append(f"WARN  rate limited: {repo} ({where})")
        elif ok:
            lines.append(f"OK    {repo} ({where})")
        else:
            bad += 1
            lines.append(f"FAIL  {repo} ({where}): HTTP {status or 'unreachable'}" + ("" if status != 200 else ", no files listed"))
    for url, where in sorted(script_urls(root).items()):
        status, _ = check(url, fetch, sleep)
        if status == 200:
            lines.append(f"OK    {url} ({where})")
        elif status == 429:
            lines.append(f"WARN  rate limited: {url} ({where})")
        else:
            bad += 1
            lines.append(f"FAIL  {url} ({where}): HTTP {status or 'unreachable'}")
    return (1 if bad else 0), lines


def main() -> int:
    code, lines = run()
    text = "# Model and script links: " + ("PROBLEM" if code else "fine") + "\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    for line in lines:
        if line.startswith("FAIL"):
            print(f"::error title=Link problem::{line[6:]}")
    return code


if __name__ == "__main__":
    sys.exit(main())
