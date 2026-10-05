"""Repo hygiene gate: keeps moved-out material from coming back into the tracked tree.

Fails (exit 1) when `git ls-files` lists
  * a path on the deny list (session handoffs, agent briefs, generated repo maps, local notes,
    editor-agent settings, a nested local layer), or a gitlink (submodule entry), or
  * more than MAX_ROOT_FILES files directly in the repository root.

Usage: python tools/check_repo_hygiene.py [REPO_DIR]     (default: the repository containing this file)
CI runs it as the "repo hygiene" job; tests/test_repo_hygiene.py covers it on a throwaway repo.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Files directly in the repository root. Raising it is a deliberate, reviewed change.
MAX_ROOT_FILES = 24

DENY = re.compile(
    r"^(?:"
    r"OPENCODE_HANDOFF_[^/]*"
    r"|INTEGRATION_[^/]*"
    r"|PROJECT_INDEX[^/]*"
    r"|\.project_index[^/]*"
    r"|\.cursorrules"
    r"|docs/(?:history|roadmap|reports|release-notes)/.*"
    r"|docs/SESSION_[^/]*"
    r"|_local(?:/.*)?"
    r"|\.claude/.*"
    r")$"
    r"|(?:^|/)[^/]*\.local\.md$",
    re.IGNORECASE,
)


def tracked(repo: Path) -> list[tuple[str, str]]:
    """(mode, path) of every tracked entry."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-s", "-z"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", errors="replace")
    entries = []
    for rec in out.split("\0"):
        if not rec:
            continue
        meta, _, path = rec.partition("\t")
        entries.append((meta.split()[0], path))
    return entries


def problems(entries: list[tuple[str, str]]) -> list[str]:
    found = []
    root_files = [p for _, p in entries if "/" not in p]
    for mode, path in entries:
        if DENY.search(path):
            found.append(f"deny-listed path is tracked: {path}")
        if mode == "160000":
            found.append(f"gitlink (submodule entry) is tracked: {path}")
    if len(root_files) > MAX_ROOT_FILES:
        found.append(f"root holds {len(root_files)} tracked files, the limit is {MAX_ROOT_FILES}")
    return found


def main(argv: list[str]) -> int:
    repo = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    found = problems(tracked(repo))
    if found:
        print("repo hygiene check failed:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print("repo hygiene check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
