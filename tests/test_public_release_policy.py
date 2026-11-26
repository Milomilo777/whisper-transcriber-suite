"""Public release surfaces must not disclose build digests or provenance IDs."""
import json
import re
from pathlib import Path

import pytest
from tools import check_public_release as policy

ROOT = Path(__file__).resolve().parents[1]


def test_public_release_notes_have_no_hashes():
    notes = (ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    assert not re.search(r"(?i)sha[-_ ]?256|checksum|build source|release source:|\b[0-9a-f]{40,64}\b", notes)
    assert "## 🐞 More than 33 bugs fixed" in notes


def test_public_facts_have_no_hashes():
    facts = json.loads((ROOT / "site/facts.json").read_text(encoding="utf-8"))
    assert "release_sha" not in facts
    assert all(set(row) == {"bytes"} for row in facts["files"].values())


def test_llm_release_summaries_have_no_provenance_ids():
    for name in ("llms.txt", "llms-full.txt"):
        summary = (ROOT / "site" / name).read_text(encoding="utf-8").split("# Full text", 1)[0]
        assert not re.search(r"(?i)\b[0-9a-f]{40,64}\b|hashes|sha[-_ ]?256", summary)


@pytest.mark.parametrize("extra", [
    "\nSHA-256: " + "a" * 64,
    "\nBuild source: `" + "b" * 40 + "`",
    "\nRelease source: `abcdef1`",
    "\n[checksums](SHA256SUMS.txt)",
    "\n[verify](files/package.sha512)",
    "\n[source](https://example.org/commit/" + "c" * 40 + ")",
    "\n[source](https://example.org/commit/1234567)",
    "\nRevision: `1234567`",
    "\n[verify](files/package%2Esha256)",
])
def test_release_guard_rejects_verification_metadata(extra):
    notes = (ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        policy.check_release_notes(notes + extra)


@pytest.mark.parametrize("heading", ["## 🐞 Bugs fixed", "## 🐞 0 bugs fixed", "## Bug fixes"])
def test_release_guard_requires_numbered_fixes(heading):
    notes = (ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="numbered"):
        policy.check_release_notes(notes.replace("## 🐞 More than 33 bugs fixed", heading))


@pytest.mark.parametrize("asset", [
    "SHA256SUMS.txt", "checksums.txt", "checksums.zip", "package.md5",
    "WhisperTranscriberSuite-v2.4.0-macOS-arm64.dmg.sha256",
    "WhisperTranscriberSuite-v2.4.0-macOS-arm64.dmg*",
    "dist/*", "digest.json",
    "dist/*/WhisperTranscriberSuite-Installer-Windows-v2.4.0.exe",
])
def test_upload_guard_rejects_checksum_files_and_globs(asset):
    with pytest.raises(AssertionError, match="unsupported"):
        policy.check_release_assets([asset])


def test_upload_guard_keeps_packages_and_gpl_source():
    policy.check_release_assets([
        "dist/WhisperTranscriberSuite-Installer-Windows-v2.4.0.exe",
        r"dist\WhisperTranscriberSuite-Portable-Windows-v2.4.0.zip",
        "WhisperTranscriberSuite-v2.4.0-macOS-arm64.dmg",
        "WhisperTranscriberSuite-v2.4.0-macOS-x64.dmg",
        "WhisperTranscriberSuite-v2.4.0-source-ffmpeg-9.0.2.tar.xz",
    ])


def test_upload_guard_requires_explicit_assets():
    with pytest.raises(AssertionError, match="explicit"):
        policy.check_release_assets([])


def test_repository_public_release_surfaces():
    policy.check_public_surfaces(ROOT)


def test_policy_check_is_in_ci():
    assert "run: python3 tools/check_public_release.py" in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

@pytest.mark.parametrize("surface", ["facts", "llms", "html"])
def test_public_surfaces_reject_short_commit_ids(tmp_path, surface):
    (tmp_path / "docs/releases").mkdir(parents=True)
    site = tmp_path / "site"
    site.mkdir()
    facts = {"files": {"installer": {"bytes": 123456789}}}
    if surface == "facts":
        facts["source"] = "abcdef1"
    (site / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    if surface != "facts":
        name = "llms.txt" if surface == "llms" else "index.html"
        (site / name).write_text("https://example.org/commit/abcdef1", encoding="utf-8")
    with pytest.raises(AssertionError, match="hash"):
        policy.check_public_surfaces(tmp_path)

@pytest.mark.parametrize("asset,accepted", [
    ("WhisperTranscriberSuite-v2.4.0-source-ffmpeg-9.0.2.tar.xz", True),
    ("SHA256SUMS.txt", False),
])
def test_public_release_cli_checks_upload_list(asset, accepted):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/check_public_release.py"),
         "--notes", str(ROOT / "docs/releases/2.4.0.md"), "--assets", asset],
        capture_output=True, text=True, timeout=30,
    )
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr
