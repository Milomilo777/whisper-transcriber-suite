"""File list of a build tree (path, size, SHA-256) and a comparison of two such lists.

  python tools/build_manifest.py write TREE OUT.json
  python tools/build_manifest.py compare A.json B.json [--strict PREFIX ...] [--tolerance 0.10]

`write` records every file under TREE. `compare` reports, per area (top-level folder, one entry
per package under Lib/site-packages), the files only in A, only in B and present in both with a
different size, plus the area's total size change. __pycache__ files are ignored. Exit 1 when a
path under a --strict prefix differs in any way (name, size or hash) or when the whole tree's
size changes by more than --tolerance (a fraction). The Windows installer workflow writes the
manifest of embed_build/ and dist_installer/ as an artifact so a CI build can be compared with a
local one (docs/BUILD.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def build(tree: Path) -> dict[str, Any]:
    files = {}
    for path in sorted(tree.rglob("*")):
        if path.is_file():
            rel = path.relative_to(tree).as_posix()
            files[rel] = {"size": path.stat().st_size, "sha256": _sha256(path)}
    return {"tree": tree.name, "files": files}


def area(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0].lower() == "lib" and parts[1].lower() == "site-packages":
        name = parts[2]
        for suffix in (".dist-info", ".data", ".libs"):
            if name.endswith(suffix):
                name = name[: -len(suffix)].split("-")[0]
        return f"Lib/site-packages/{name.split('.')[0].lower()}"
    return parts[0] if len(parts) > 1 else "(top level)"


def _relevant(files: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in files.items() if "__pycache__/" not in k}


def compare(a: dict[str, Any], b: dict[str, Any], strict: list[str],
            tolerance: float) -> tuple[list[str], list[str]]:
    """(report lines, failures)."""
    fa, fb = _relevant(a["files"]), _relevant(b["files"])
    areas: dict[str, dict[str, Any]] = {}
    for rel in sorted(set(fa) | set(fb)):
        s = areas.setdefault(area(rel), {"only_a": [], "only_b": [], "size": [], "hash": 0,
                                         "bytes_a": 0, "bytes_b": 0})
        if rel in fa:
            s["bytes_a"] += fa[rel]["size"]
        if rel in fb:
            s["bytes_b"] += fb[rel]["size"]
        if rel not in fb:
            s["only_a"].append(rel)
        elif rel not in fa:
            s["only_b"].append(rel)
        elif fa[rel]["size"] != fb[rel]["size"]:
            s["size"].append(rel)
        elif fa[rel]["sha256"] != fb[rel]["sha256"]:
            s["hash"] += 1
    lines = [f"A = {a['tree']} ({len(fa)} files), B = {b['tree']} ({len(fb)} files)"]
    failures = []
    for name, s in areas.items():
        if not (s["only_a"] or s["only_b"] or s["size"] or s["hash"]):
            continue
        delta = s["bytes_b"] - s["bytes_a"]
        lines.append(f"{name}: only A {len(s['only_a'])}, only B {len(s['only_b'])}, "
                     f"size differs {len(s['size'])}, same size other bytes {s['hash']}, "
                     f"bytes {s['bytes_a']} -> {s['bytes_b']} ({delta:+d})")
        for label, paths in (("only A", s["only_a"]), ("only B", s["only_b"]),
                             ("size differs", s["size"])):
            for rel in paths[:5]:
                lines.append(f"    {label}: {rel}")
            if len(paths) > 5:
                lines.append(f"    {label}: ... {len(paths) - 5} more")
    for rel in sorted(set(fa) | set(fb)):
        if any(rel.startswith(p) for p in strict) and fa.get(rel) != fb.get(rel):
            failures.append(f"strict path differs: {rel}")
    total_a = sum(v["size"] for v in fa.values())
    total_b = sum(v["size"] for v in fb.values())
    change = (total_b - total_a) / total_a if total_a else float("inf")
    lines.append(f"total bytes {total_a} -> {total_b} ({change:+.2%}, tolerance {tolerance:.0%})")
    if abs(change) > tolerance:
        failures.append(f"total size changed by {change:+.2%}, more than {tolerance:.0%}")
    return lines, failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or compare build-tree file lists.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("tree", type=Path)
    w.add_argument("out", type=Path)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--strict", action="append", default=[], metavar="PREFIX")
    c.add_argument("--tolerance", type=float, default=0.10)
    args = ap.parse_args(argv)
    if args.cmd == "write":
        if not args.tree.is_dir():
            print(f"not a folder: {args.tree}", file=sys.stderr)
            return 2
        args.out.parent.mkdir(parents=True, exist_ok=True)
        manifest = build(args.tree)
        args.out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{len(manifest['files'])} files -> {args.out}")
        return 0
    a = json.loads(args.a.read_text(encoding="utf-8"))
    b = json.loads(args.b.read_text(encoding="utf-8"))
    lines, failures = compare(a, b, args.strict, args.tolerance)
    print("\n".join(lines))
    for f in failures:
        print(f"FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
