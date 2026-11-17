"""Run one deterministic, duration-balanced third of the hermetic test files.

The timing snapshot records approximate file wall times from Windows Python 3.11
CI on 2026-11-17. New files receive a small default weight automatically. Greedy
longest-first assignment balances time; execution keeps pytest's path ordering.
Refresh the snapshot from shard JUnit reports when CI timings drift.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARD_COUNT = 3
DEFAULT_SECONDS = 1.0


def load_durations() -> dict[str, float]:
    return json.loads(Path(__file__).with_name("ci_test_durations.json").read_text(encoding="utf-8"))


def split_suite(root: Path, durations: dict[str, float] | None = None) -> list[list[str]]:
    if durations is None:
        durations = load_durations()
    files = [
        p.relative_to(root).as_posix()
        for p in (root / "tests").rglob("*.py")
        if (p.name.startswith("test_") or p.name.endswith("_test.py"))
        and p.relative_to(root / "tests").parts[0] != "smoke"
    ]
    shards: list[list[str]] = [[] for _ in range(SHARD_COUNT)]
    totals = [0.0] * SHARD_COUNT
    for path in sorted(files, key=lambda p: (-durations.get(p, DEFAULT_SECONDS), p)):
        index = min(range(SHARD_COUNT), key=lambda i: (totals[i], i))
        shards[index].append(path)
        totals[index] += durations.get(path, DEFAULT_SECONDS)
    return [sorted(shard) for shard in shards]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", required=True, type=int, choices=range(1, SHARD_COUNT + 1))
    parser.add_argument("--list", action="store_true", help="Print selected paths without importing pytest")
    args = parser.parse_args(argv)
    files = split_suite(ROOT)[args.shard - 1]
    if not files:
        parser.error(f"shard {args.shard} is empty")
    print(f"Windows test shard {args.shard}/{SHARD_COUNT}: {len(files)} files", flush=True)
    if args.list:
        print("\n".join(files))
        return 0
    # In-process invocation avoids Windows' command-line length limit. Running
    # from the repository root also preserves imports and pytest configuration.
    import os
    import pytest

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    return int(pytest.main([
        *files, "-v", "--durations=25", f"--junitxml=ci-shard-{args.shard}.xml",
    ]))


if __name__ == "__main__":
    raise SystemExit(main())
