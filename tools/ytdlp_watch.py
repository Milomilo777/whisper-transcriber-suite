"""Daily yt-dlp health check, run by .github/workflows/ytdlp-watch.yml (also runnable by hand).

It asks the installed yt-dlp for the metadata of a few stable public media pages (no download) and reports,
per site, one of: ok, blocked (the site refused the CI network: no verdict), fail (the extractor broke).
Exit code 1 when any site fails, or when no site gave a usable answer; blocked sites alone only warn.
Usage: python tools/ytdlp_watch.py [--urls tools/ytdlp_watch_urls.json] [--yt-dlp "python -m yt_dlp"]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
TIMEOUT_S = 150
# Text that means "the site did not like this network", not "yt-dlp is broken".
BLOCKED_RE = re.compile(
    r"sign in to confirm|not a bot|http error 429|too many requests|http error 403|captcha|"
    r"this video is not available from your location|video unavailable. this content isn't available",
    re.IGNORECASE,
)

Runner = Callable[[list[str]], tuple[int, str, str]]


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """Run one command; a timeout is reported as return code 124."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {TIMEOUT_S} s"
    except OSError as exc:  # program missing or not executable
        return 127, "", f"cannot start {cmd[0]}: {exc}"
    return done.returncode, done.stdout, done.stderr


def classify(rc: int, out: str, err: str) -> str:
    """'ok' when yt-dlp printed extractor and a real duration, 'blocked' for refusals, else 'fail'."""
    parts = [p.strip() for p in out.strip().splitlines()[-1:][0].split("|")] if out.strip() else []
    if rc == 0 and len(parts) >= 2 and parts[0] and parts[1] not in ("", "NA", "None"):
        return "ok"
    if BLOCKED_RE.search(err) or BLOCKED_RE.search(out):
        return "blocked"
    return "fail"


def check_site(entry: dict[str, str], base: list[str], runner: Runner) -> dict[str, str]:
    cmd = [*base, "--skip-download", "--no-warnings", "--no-playlist",
           "--print", "%(extractor)s|%(duration)s|%(title).60s", entry["url"]]
    rc, out, err = runner(cmd)
    status = classify(rc, out, err)
    detail = (out.strip().splitlines()[-1] if status == "ok" else (err.strip().splitlines() or ["no output"])[-1])[:200]
    return {"name": entry["name"], "status": status, "detail": detail}


def verdict(results: list[dict[str, str]]) -> int:
    if any(r["status"] == "fail" for r in results):
        return 1
    if not any(r["status"] == "ok" for r in results):
        return 1  # nothing usable at all: a broken runner or a total breakage
    return 0


def render(version: str, results: list[dict[str, str]], code: int) -> str:
    icon = {"ok": "OK", "blocked": "BLOCKED (no verdict)", "fail": "FAIL"}
    lines = [f"# yt-dlp watch: {'PROBLEM' if code else 'fine'}", f"Installed yt-dlp: `{version}`", "",
             "| Site | Result | Detail |", "|---|---|---|"]
    lines += [f"| {r['name']} | {icon[r['status']]} | {r['detail'].replace('|', '/')} |" for r in results]
    return "\n".join(lines) + "\n"


def main(argv: list[str], runner: Runner = run_command) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", default=str(HERE / "ytdlp_watch_urls.json"))
    ap.add_argument("--yt-dlp", dest="ytdlp", default=f'"{sys.executable}" -m yt_dlp')
    args = ap.parse_args(argv)
    entries = json.loads(Path(args.urls).read_text(encoding="utf-8"))
    # On Windows shlex keeps the quotes around a quoted path (non-POSIX mode): drop them.
    base = [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(args.ytdlp, posix=os.name != "nt")]
    rc, out, err = runner([*base, "--version"])
    if rc != 0:
        print(f"yt-dlp does not start: {err.strip()[:200]}")
        return 1
    version = out.strip().splitlines()[0]
    results = [check_site(e, base, runner) for e in entries]
    code = verdict(results)
    text = render(version, results, code)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    for r in results:
        if r["status"] == "fail":
            print(f"::error title=yt-dlp {version} cannot read {r['name']}::{r['detail']}")
        elif r["status"] == "blocked":
            print(f"::warning title=yt-dlp check blocked for {r['name']}::{r['detail']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
