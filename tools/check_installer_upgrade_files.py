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
BASELINE_MANIFEST = Path("tools/installer_upgrade_baselines.txt")
STABLE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _required_releases(repo: Path) -> dict[str, tuple[str, str]]:
    try:
        lines = (repo / BASELINE_MANIFEST).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Published release tags manifest unavailable") from error
    tags: dict[str, tuple[str, str]] = {}
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        fields = value.split()
        if (len(fields) != 3 or STABLE_TAG.fullmatch(fields[0]) is None
                or any(re.fullmatch(r"[0-9a-f]{40}", item) is None for item in fields[1:])
                or fields[0] in tags):
            raise RuntimeError("Published release tags manifest has invalid or duplicate entries")
        tag, tag_object, commit = fields
        tags[tag] = (tag_object, commit)
    if not tags:
        raise RuntimeError("Published release tags manifest is empty")
    return tags


def _git(repo: Path, *arguments: str) -> str:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    # Local replacement refs must not substitute content behind a pinned ID.
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *arguments],
                            env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Git history unavailable; fetch release tags before checking upgrades")
    return result.stdout.decode("utf-8", errors="surrogateescape")


def check(repo: Path) -> tuple[str, list[str]]:
    releases = []
    for tag in _git(repo, "tag", "--list", "v*").splitlines():
        match = STABLE_TAG.fullmatch(tag)
        if match:
            releases.append((tuple(int(part) for part in match.groups()), tag))
    if not releases:
        raise RuntimeError("No release tags available; fetch release tags before checking upgrades")
    present = {tag for _, tag in releases}
    required = _required_releases(repo)
    if required.keys() - present:
        raise RuntimeError("Published release tags missing from this checkout: "
                           + ", ".join(sorted(required.keys() - present)))
    for tag, expected in required.items():
        tag_object = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}").strip()
        commit = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").strip()
        if (tag_object, commit) != expected:
            raise RuntimeError(f"Known release tag object or commit changed: {tag}")
    # Every published stable version remains an upgrade source. A newer
    # release (including a tag for the current tree) cannot erase the older
    # installation's inventory. Disable rename detection for each baseline.
    removed: set[str] = set()
    baselines = [tag for _, tag in sorted(releases)]
    for baseline in baselines:
        revision = required[baseline][1] if baseline in required else baseline
        names = _git(repo, "diff", "--no-ext-diff", "--no-renames", "--name-only",
                     "-z", "--diff-filter=D", revision, "--", *PACKAGED_PATHS)
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
