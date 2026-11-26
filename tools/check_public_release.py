"""Check public release text and an explicit release-asset upload list offline."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DRAFT_NOTES = Path("docs/releases/2.5.0.md")
DRAFT_FIELDS = (
    "RELEASE_DATE", "SIZE_INSTALLER", "SIZE_PORTABLE", "SIZE_ARM64", "SIZE_X64",
    "BUG_COUNT", "TOP_FIXES",
)
HASH = re.compile(r"(?i)\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b|\b[0-9]{40,64}\b")
DIGEST = re.compile(r"(?i)\b[0-9a-f]{40,64}\b")
SOURCE_ID = re.compile(r"(?i)(?:/(?:commit|blob|tree)/|[\"']?(?:source|commit|revision|sha)[\"']?\s*[:=]\s*[\"'`]?)" r"[0-9a-f]{7,40}\b")
METADATA = re.compile(r"(?i)sha[-_ ]?\d+|checksums?|\brelease[ _-]sha\b|\b(?:build|release)[ _-]source\s*[:|]")
ASSET = re.compile(
    r"WhisperTranscriberSuite-(?:Installer-Windows-v\d+\.\d+\.\d+\.exe|"
    r"Portable-Windows-v\d+\.\d+\.\d+\.zip|"
    r"v\d+\.\d+\.\d+-(?:macOS-(?:arm64|x64)\.dmg|source-ffmpeg-[\d.]+\.tar\.xz))"
)


def release_placeholders(notes: str) -> tuple[str, ...]:
    return tuple(field for field in DRAFT_FIELDS if re.search(rf"\b{field}\b", notes))


def check_release_notes(notes: str, *, allow_draft: bool = False) -> None:
    """Reject digests, source IDs and checksum links in any release body."""
    decoded = unquote(notes)
    assert not HASH.search(decoded) and not SOURCE_ID.search(decoded), "hash or commit ID in public release text"
    assert not METADATA.search(decoded), "verification metadata in public release text"
    if not allow_draft:
        placeholders = release_placeholders(notes)
        assert not placeholders, f"unfilled release placeholders: {', '.join(placeholders)}"
    count = r"(?:More than )?[1-9]\d*"
    if allow_draft:
        count = rf"(?:{count}|BUG_COUNT)"
    assert re.search(rf"^## 🐞 {count} bugs fixed\s*$", notes, re.M), "missing numbered bugs-fixed heading"


def check_release_assets(assets: list[str]) -> None:
    """Allow shipping packages and the GPL source archive, with no sidecars/globs."""
    assert assets, "an explicit release asset list is required"
    for asset in assets:
        assert not any(char in asset for char in "*?[]"), f"unsupported public release asset: {asset}"
        name = Path(asset.replace("\\", "/")).name
        assert ASSET.fullmatch(name), f"unsupported public release asset: {name}"


def check_public_surfaces(root: Path) -> tuple[str, ...]:
    draft_fields: tuple[str, ...] = ()
    for path in (root / "docs/releases").glob("*.md"):
        notes = path.read_text(encoding="utf-8")
        is_draft = path == root / DRAFT_NOTES
        check_release_notes(notes, allow_draft=is_draft)
        if is_draft:
            draft_fields = release_placeholders(notes)
    facts_text = (root / "site/facts.json").read_text(encoding="utf-8")
    facts = json.loads(facts_text)
    assert not DIGEST.search(facts_text) and not SOURCE_ID.search(facts_text), "hash in public facts"
    assert not METADATA.search(facts_text), "verification metadata in public facts"
    for row in facts["files"].values():
        assert set(row) == {"bytes"}, "public artifact facts must contain only byte sizes"
        assert type(row["bytes"]) is int and row["bytes"] > 0, "invalid artifact byte size"
    for path in (root / "site").rglob("*"):
        if path.suffix in {".html", ".txt"}:
            text = unquote(path.read_text(encoding="utf-8"))
            assert not DIGEST.search(text) and not SOURCE_ID.search(text), f"hash in public site output: {path}"
    return draft_fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--notes", type=Path, help="also check a proposed release body (strict when checking uploads)")
    parser.add_argument("--assets", nargs="+", help="exact paths intended for release upload")
    args = parser.parse_args()
    draft_fields = check_public_surfaces(args.root)
    if args.notes:
        is_draft = args.assets is None and args.notes.resolve() == (args.root / DRAFT_NOTES).resolve()
        check_release_notes(args.notes.read_text(encoding="utf-8"), allow_draft=is_draft)
    if args.assets is not None:
        check_release_assets(args.assets)
        if args.notes is None and draft_fields:
            draft_version = rf"-v{re.escape(DRAFT_NOTES.stem)}[.-]"
            assert not any(re.search(draft_version, Path(asset.replace("\\", "/")).name)
                           for asset in args.assets), "unfilled release placeholders: provide completed --notes"
    if draft_fields:
        print(f"Draft {DRAFT_NOTES.stem} has unfilled release placeholders: {', '.join(draft_fields)}")
    print("PASS: public release policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
