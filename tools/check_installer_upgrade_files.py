"""Reject overlay upgrades that would leave retired packaged source behind.

Run from a checkout with release tags before building an installer. The current
overlay policy intentionally preserves unknown files. A source deletion or
rename therefore needs a reviewed, ownership-safe retired-file cleanup before
this check can be updated to permit it.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

PACKAGED_PATHS = ("app", "core", "gui.py", "sitecustomize.py")


def _git(repo: Path, *arguments: str) -> str:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(repo), *arguments],
                            env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Git history unavailable; fetch release tags before checking upgrades")
    return result.stdout.decode("utf-8", errors="surrogateescape")


def check(repo: Path) -> tuple[str, list[str]]:
    releases = []
    for tag in _git(repo, "tag", "--list", "v*").splitlines():
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
        if match:
            releases.append((tuple(int(part) for part in match.groups()), tag))
    if not releases:
        raise RuntimeError("No release tags available; fetch release tags before checking upgrades")
    # Every published stable version remains an upgrade source. A newer
    # release (including a tag for the current tree) cannot erase the older
    # installation's inventory. Disable rename detection for each baseline.
    removed: set[str] = set()
    baselines = [tag for _, tag in sorted(releases)]
    for baseline in baselines:
        names = _git(repo, "diff", "--no-ext-diff", "--no-renames", "--name-only",
                     "-z", "--diff-filter=D", baseline, "--", *PACKAGED_PATHS)
        removed.update(name for name in names.split("\0") if name)
    return ", ".join(baselines), sorted(removed)



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    try:
        baseline, removed = check(arguments.repo)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 2
    if removed:
        print(f"Overlay upgrade from {baseline} requires reviewed retired-file cleanup:")
        for name in removed:
            print(name)
        return 1
    print(f"Overlay upgrade inventory from {baseline}: no retired packaged source files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
