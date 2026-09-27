"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver, Yep) the website changed.

The key is public by design: IndexNow verifies ownership by fetching
site/<key>.txt from the live site, so the script first waits for that file
to be served (i.e. for Cloudflare Pages to finish deploying), then submits
the site's URLs once. Google does not take part in IndexNow; it reads
sitemap.xml instead.

    python tools/indexnow_ping.py [--wait SECONDS]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HOST = "whisper-transcriber-suite.pages.dev"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URLS = ["/", "/llms.txt", "/llms-full.txt", "/sitemap.xml"]
# Cloudflare answers 403 to urllib's default "Python-urllib" user agent.
UA = {"User-Agent": "whisper-transcriber-suite-indexnow/1.0 (+https://github.com/Milomilo777/whisper-transcriber-suite)"}


def find_key() -> str:
    for path in glob.glob(os.path.join(ROOT, "site", "*.txt")):
        name = os.path.basename(path)[:-4]
        if re.fullmatch(r"[0-9a-f]{32}", name):
            return name
    raise SystemExit("no IndexNow key file (site/<32 hex>.txt) found")


def live_key_ok(key: str) -> bool:
    try:
        req = urllib.request.Request(f"https://{HOST}/{key}.txt", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", "replace").strip() == key
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Submit the website to IndexNow.")
    ap.add_argument("--wait", type=int, default=300, help="max seconds to wait for the deploy (default 300)")
    args = ap.parse_args()

    key = find_key()
    deadline = time.monotonic() + args.wait
    while not live_key_ok(key):
        if time.monotonic() > deadline:
            print("key file not live yet; skipping the ping")
            return 0
        time.sleep(15)

    body = json.dumps({
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": [f"https://{HOST}{u}" for u in URLS],
    }).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8", **UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"IndexNow: HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        # 200/202 = accepted; 4xx is reported but never fails the workflow.
        print(f"IndexNow: HTTP {exc.code} {exc.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
