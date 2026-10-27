#!/usr/bin/env python3
"""Documentation checker (links, record front matter, stray control characters in Markdown).

Usage (also: --self-test, --types dossier,glossary):
    python tools/docs_check.py . [--english-only] [--report] [--all]

Checks (exit 1 on any problem):
  1. every relative Markdown link in the repo's Markdown files resolves (anchors ignored);
  2. every record under docs/{decisions,experiments,investigations,proposals}/ (a *.md file, or a
     folder with README.md) has front matter with type, status, created; a finished experiment has
     a verdict; status "superseded" has superseded_by;
  3. every record is LINKED (a Markdown link, not a mention) from its folder's README.md;
     type / status / verdict / created use the standard's vocabularies;
  4. no control or invisible characters (U+FFFD, zero-width, BOM) in Markdown;
  5. with --english-only: no Arabic-script letters in tracked-docs Markdown (two-layer rule:
     owner-facing Persian lives in *.local.md, which is skipped).
--report also lists Markdown files under docs/ that nothing links to (orphans; never a failure).
Warnings (never a failure): AGENTS.md / CLAUDE.md over 200 lines, CLAUDE.md not starting with
'@AGENTS.md'.

Standard library only. tests/test_docs_check.py runs it over the tracked Markdown files. Do not
pass --english-only here: the translated READMEs and the README's language list are meant to
hold non-Latin scripts.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

RECORD_DIRS = ("decisions", "experiments", "investigations", "proposals", "incidents")
TYPES = {"tutorial", "how-to", "reference", "explanation", "adr", "experiment",
         "investigation", "proposal", "incident", "roadmap", "dossier"}
STATUSES = {"draft", "active", "proposed", "accepted", "rejected", "parked", "done",
            "concluded", "abandoned", "deprecated", "superseded", "moved",
            "archived"}
VERDICTS = {"supported", "rejected", "inconclusive", "n/a"}
OPEN_STATUSES = {"draft", "active", "proposed"}  # an experiment may lack a verdict only then
AGENT_FILE_MAX_LINES = 200  # Anthropic's guidance for CLAUDE.md; same cap for AGENTS.md
REQUIRED = ("type", "status", "created")
# frozen history ("archive") and scratch ("notes") are not checked unless --all is given
HISTORY_PARTS = {"archive", "notes"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "site-packages",
              ".mypy_cache", ".ruff_cache", "dist", "build", "templates", "evidence"}
# Link target: no whitespace or ')', except ')' inside balanced parentheses (one
# level, like CommonMark allows), so [x](a_(b).md) keeps its full file name.
_TARGET = r"((?:[^()\s]|\([^)\s]*\))*)"
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(" + _TARGET + r"(?:\s+\"[^\"]*\")?\)")
IMG_RE = re.compile(r"!\[[^\]]*\]\(" + _TARGET + r"\)")
FENCE_RE = re.compile(r"^(```|~~~)")
ARABIC_RE = re.compile("[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
# U+FFFD = a decoding accident. Zero-width joiners are NOT flagged in Markdown: ZWNJ (U+200C)
# is correct Persian orthography and ZWJ builds emoji.
INVISIBLE = {chr(0xFFFD)}


def markdown_files(root: Path, include_history: bool = False) -> list[Path]:
    skip = SKIP_PARTS if include_history else SKIP_PARTS | HISTORY_PARTS
    out = []
    for p in root.rglob("*.md"):
        rel = p.relative_to(root).parts
        if any(part in skip for part in rel) or p.name.endswith(".local.md"):
            continue
        out.append(p)
    return sorted(out)


def front_matter(text: str) -> dict[str, str] | None:
    """Minimal YAML front matter reader: top-level ``key: value`` lines only."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*(?:#.*)?$", line)
        if m:
            data[m.group(1)] = m.group(2).strip().strip("'\"")
    return data


def _links(text: str) -> list[str]:
    """Link targets outside fenced code blocks and inline code."""
    targets: list[str] = []
    fenced = False
    for line in text.splitlines():
        if FENCE_RE.match(line.strip()):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        targets += LINK_RE.findall(line) + IMG_RE.findall(line)
    return targets


def check(
    root: Path,
    english_only: bool = False,
    include_history: bool = False,
    extra_types: frozenset[str] = frozenset(),
) -> tuple[list[str], set[Path]]:
    problems: list[str] = []
    linked: set[Path] = set()
    for md in markdown_files(root, include_history):
        text = md.read_text(encoding="utf-8", errors="replace")
        rel_md = md.relative_to(root)
        fenced = False
        for n, line in enumerate(text.splitlines(), 1):
            if any((ord(c) < 32 and ord(c) != 9) or c in INVISIBLE for c in line):
                problems.append(f"{rel_md}:{n}: control character or U+FFFD")
            if FENCE_RE.match(line.strip()):
                fenced = not fenced
                continue
            prose = "" if fenced else re.sub(r"`[^`]*`", "", line)  # samples belong in code
            if english_only and ARABIC_RE.search(prose):
                problems.append(
                    f"{rel_md}:{n}: Arabic-script prose in a tracked doc "
                    "(quote samples as code, or keep it in *.local.md)"
                )
        for target in _links(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue  # http:, mailto:, file:, anchors
            path_part = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path_part:
                continue
            dest = (md.parent / path_part).resolve()
            if not dest.exists():
                problems.append(f"{rel_md}: broken link -> {target}")
            else:
                linked.add(dest)
    docs = root / "docs"
    for folder in RECORD_DIRS:
        d = docs / folder
        if not d.is_dir():
            continue
        readme_path = d / "README.md"
        readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
        if not readme:
            problems.append(f"docs/{folder}/README.md missing (the register of this record type)")
        records = [p for p in d.glob("*.md") if p.name != "README.md"]
        # a folder is a record of its own only when no sibling <folder>.md exists (otherwise it
        # holds that record's appendices/evidence)
        records += [
            p / "README.md"
            for p in d.iterdir()
            if p.is_dir() and (p / "README.md").is_file() and not (d / f"{p.name}.md").exists()
        ]
        for rec in sorted(records):
            rel = rec.relative_to(root)
            name = rec.parent.name if rec.name == "README.md" else rec.name
            fm = front_matter(rec.read_text(encoding="utf-8", errors="replace"))
            if fm is None:
                problems.append(f"{rel}: missing front matter")
                continue
            for key in REQUIRED:
                if not fm.get(key):
                    problems.append(f"{rel}: front matter lacks '{key}'")
            if fm.get("type") and fm["type"] not in TYPES | extra_types:
                problems.append(f"{rel}: unknown type '{fm['type']}'")
            if fm.get("status") and fm["status"] not in STATUSES:
                problems.append(f"{rel}: unknown status '{fm['status']}'")
            if fm.get("created") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fm["created"]):
                problems.append(f"{rel}: created is not YYYY-MM-DD")
            if fm.get("type") == "experiment":
                verdict = fm.get("verdict", "")
                if verdict and verdict not in VERDICTS:
                    problems.append(f"{rel}: unknown verdict '{verdict}'")
                if not verdict and fm.get("status") not in OPEN_STATUSES:
                    problems.append(f"{rel}: experiment without verdict")
            if fm.get("status") == "superseded" and not fm.get("superseded_by"):
                problems.append(f"{rel}: status superseded without superseded_by")
            register_links = {t.split('#', 1)[0].rstrip('/') for t in _links(readme)}
            if not ({name, f"{name}/README.md", f"./{name}"} & register_links):
                problems.append(f"{rel}: not linked from docs/{folder}/README.md")
    return problems, linked


def agent_file_warnings(root: Path) -> list[str]:
    """AGENTS.md / CLAUDE.md hygiene (warnings): size cap, CLAUDE.md imports AGENTS.md."""
    out: list[str] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        f = root / name
        if not f.is_file():
            out.append(f"{name} missing")
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > AGENT_FILE_MAX_LINES:
            out.append(f"{name}: {len(lines)} lines > {AGENT_FILE_MAX_LINES} (move procedures to skills,"
                       " history to records)")
        if name == "CLAUDE.md" and (root / "AGENTS.md").is_file():
            first = next((ln.strip() for ln in lines if ln.strip()), "")
            if first != "@AGENTS.md":
                out.append("CLAUDE.md: first line should be '@AGENTS.md' (Claude Code does not read"
                           " AGENTS.md when CLAUDE.md exists)")
    return out


def self_test() -> int:
    """Plant one defect of each kind in a temporary repo and require the checker to catch it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dec = root / "docs" / "decisions"
        exp = root / "docs" / "experiments"
        dec.mkdir(parents=True)
        exp.mkdir(parents=True)
        fm = "---\ntitle: t\ntype: adr\nstatus: accepted\ncreated: 2026-01-01\n---\n"
        (dec / "0001-ok.md").write_text(fm + "[x](0002-missing.md)\n", encoding="utf-8")
        (dec / "0003-unlisted.md").write_text(fm, encoding="utf-8")
        (dec / "0004-bad-status.md").write_text(fm.replace("accepted", "maybe"), encoding="utf-8")
        (dec / "README.md").write_text(
            "[a](0001-ok.md) [b](0004-bad-status.md) 0003-unlisted.md in prose only\n"
            "```\n[ignored](nowhere.md)\n```\n",
            encoding="utf-8",
        )
        (exp / "2026-01-01-x.md").write_text(
            fm.replace("type: adr", "type: experiment").replace("accepted", "done"), encoding="utf-8"
        )
        (exp / "README.md").write_text("[x](2026-01-01-x.md)\n", encoding="utf-8")
        (root / "notes.md").write_text("bad " + chr(0xFFFD) + " char\n", encoding="utf-8")
        problems, _ = check(root)
    expected = ["broken link -> 0002-missing.md", "0003-unlisted.md: not linked",
                "unknown status 'maybe'", "experiment without verdict", "U+FFFD"]
    missed = [e for e in expected if not any(e in p for p in problems)]
    false = [p for p in problems if "nowhere.md" in p]
    print("self-test:", "ok" if not missed and not false else f"missed={missed} false={false}")
    return 0 if not missed and not false else 1


def orphans(root: Path, linked: set[Path]) -> list[str]:
    docs = root / "docs"
    if not docs.is_dir():
        return []
    out = []
    for md in markdown_files(docs):
        if md.resolve() not in linked and md.name != "index.md":
            out.append(str(md.relative_to(root)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--english-only", action="store_true")
    ap.add_argument("--report", action="store_true", help="also list orphan docs (never fails)")
    ap.add_argument("--all", action="store_true", help="also check archive/ and notes/ folders")
    ap.add_argument("--types", default="", help="extra front-matter types, comma-separated")
    ap.add_argument("--self-test", action="store_true", help="plant defects, require detection")
    args = ap.parse_args(argv)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8", errors="replace")
    if args.self_test:
        return self_test()
    root = Path(args.repo).resolve()
    extra = frozenset(t.strip() for t in args.types.split(",") if t.strip())
    problems, linked = check(
        root, english_only=args.english_only, include_history=args.all, extra_types=extra
    )
    for w in agent_file_warnings(root):
        print(f"warning: {w}")
    for p in problems:
        print(p)
    if args.report:
        for o in orphans(root, linked):
            print(f"orphan (nothing links to it): {o}")
    print(f"docs check: {len(problems)} problem(s) in {root}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
