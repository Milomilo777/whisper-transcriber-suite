"""Release draft checks, including causal mutations on copies of the real inputs."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from tools import check_release_page as release_checks

from tools.check_release_page import LANGUAGES, ROOT, animation_timing, check_page, check_svg

BASELINE = json.loads((ROOT / "tests/fixtures/promo-release-timing-2.3.1.json").read_text())
RELEASE_SHA = "7197cd21af46574aeb4c302b733076be78dfdade"


def test_promo_timing_and_resources():
    svg = (ROOT / "docs/img/promo-release.svg").read_text(encoding="utf-8")
    check_svg(svg, BASELINE)
    assert animation_timing(svg)["cycle"] == 36
    assert "Saved presets" in svg and "Subtitle quality review" in svg


def test_shortened_real_hold_is_rejected():
    svg = (ROOT / "docs/img/promo-release.svg").read_text(encoding="utf-8")
    # The first visibility hold is 0..10.2381% of 33.6 seconds in the old asset.
    # Shorten that hold alone to 0..1% while keeping the 36-second cycle intact.
    pattern = r"(@keyframes bar1Vis \{.*?)(10\.2381%)(.*?\})"
    damaged, count = re.subn(pattern, r"\g<1>1%\g<3>", svg, count=1)
    assert count == 1
    assert animation_timing(damaged)["cycle"] == 36
    with pytest.raises(AssertionError, match="shortened hold: bar1Vis/opacity"):
        check_svg(damaged, BASELINE)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_language_release_block_and_links(lang):
    relative = Path("index.html") if lang == "en" else Path(lang) / "index.html"
    check_page((ROOT / "site" / relative).read_text(encoding="utf-8"), lang, ROOT / "site", relative)


def test_missing_one_feature_is_rejected():
    relative = Path("fil/index.html")
    html = (ROOT / "site" / relative).read_text(encoding="utf-8")
    damaged, count = re.subn(r'<article[^>]*data-release-feature="subtitle-quality"[^>]*>.*?</article>', "", html, count=1, flags=re.S)
    assert count == 1
    assert 'data-release-feature="presets"' in damaged
    assert 'data-release-feature="download-limit"' in damaged
    with pytest.raises(AssertionError, match="missing 2.4.0 feature block: fil"):
        check_page(damaged, "fil", ROOT / "site", relative)


def test_second_animation_shortening_is_rejected():
    svg = (ROOT / "docs/img/promo-release.svg").read_text(encoding="utf-8")
    damaged = svg.replace("quoteScale 36s", "quoteScale 0.1s", 1)
    assert damaged != svg and "quoteVis 36s" in damaged
    with pytest.raises(AssertionError, match="inconsistent animation cycles"):
        check_svg(damaged, BASELINE)


def test_feature_outside_release_section_is_rejected():
    relative = Path("index.html")
    html = (ROOT / "site" / relative).read_text(encoding="utf-8")
    article = re.search(r'<article[^>]*data-release-feature="subtitle-quality"[^>]*>.*?</article>', html, re.S)[0]
    damaged = html.replace(article, "", 1).replace("</body>", article + "</body>")
    with pytest.raises(AssertionError, match="feature outside release section"):
        check_page(damaged, "en", ROOT / "site", relative)


def test_release_block_in_wrong_section_is_rejected():
    relative = Path("index.html")
    html = (ROOT / "site" / relative).read_text(encoding="utf-8")
    block = re.search(r'<div data-release="2.4.0">.*?</div>\s*</div>', html, re.S)[0]
    damaged = html.replace(block, "", 1).replace("</body>", block + "</body>")
    with pytest.raises(AssertionError, match="release block outside whats-new section"):
        check_page(damaged, "en", ROOT / "site", relative)


def test_draft_artifact_rows_retain_final_build_provenance():
    notes = (ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    assert "Released 2026-11-15" in notes
    assert "TODO-FINAL-SHA" not in notes
    rows = [line for line in notes.splitlines() if line.startswith("| [")]
    assert len(rows) == 4
    release_checks.check_release_artifacts(notes, RELEASE_SHA)
    assert "## 🐞 Bugs fixed" in notes
    assert "32 bugs" not in notes


def artifact_copy(*, source=RELEASE_SHA, row=0, digest="a" * 64):
    notes = (ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    lines = notes.splitlines()
    indices = [i for i, text in enumerate(lines) if text.startswith("| [")]
    cells = [part.strip() for part in lines[indices[row]].strip("|").split("|")]
    lines[indices[row]] = "| " + " | ".join(cells[:2] + ["10 B", digest, source]) + " |"
    return "\n".join(lines)


@pytest.mark.parametrize("row", range(4))
def test_artifact_hash_from_a_different_release_source_is_rejected(row):
    notes = artifact_copy(source="16df0244ae43454d34c97a388754446fc3ab99ff", row=row)
    with pytest.raises(AssertionError, match="artifact source differs"):
        release_checks.check_release_artifacts(notes, RELEASE_SHA)


def test_artifact_hash_from_the_expected_release_source_is_accepted():
    release_checks.check_release_artifacts(artifact_copy(), RELEASE_SHA)


def test_pending_hash_does_not_waive_source_identity():
    notes = artifact_copy(source="0" * 40, digest="TODO-FINAL-SHA")
    with pytest.raises(AssertionError, match="artifact source differs"):
        release_checks.check_release_artifacts(notes, RELEASE_SHA)


def test_release_facts_and_notes_name_the_frozen_candidate():
    facts = json.loads((ROOT / "site/facts.json").read_text(encoding="utf-8"))
    assert facts["release_sha"] == RELEASE_SHA
    release_checks.check_release_artifacts((ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8"), facts["release_sha"])


def test_machine_readable_release_facts():
    facts = json.loads((ROOT / "site/facts.json").read_text(encoding="utf-8"))
    assert facts["version"] == "v2.4.0"
    assert facts["release_status"] == "published"
    assert facts["released"] == "2026-11-15"
    assert set(facts["website_languages"]) == set(LANGUAGES)
    for name in ("llms.txt", "llms-full.txt"):
        text = (ROOT / "site" / name).read_text(encoding="utf-8")
        summary = text.split("# Full text", 1)[0]
        assert "2.4.0" in summary and "Unpublished draft" not in summary
        assert "v2.3.1" not in summary
    ET = __import__("xml.etree.ElementTree", fromlist=["ElementTree"])
    ET.parse(ROOT / "site/sitemap.xml")


def test_readiness_document_is_explicitly_a_draft():
    text = (ROOT / "RELEASE-PAGE-READY.md").read_text(encoding="utf-8")
    assert "PUBLICATION METADATA / ARTIFACTS VERIFIED" in text
    assert "Persian interface" in text
    assert "Persian approval is OPEN" not in text
    assert "TODO-FINAL-SHA" in text


def test_cli_accepts_original_svg_baseline(tmp_path):
    original = tmp_path / "old.svg"
    original.write_text((ROOT / "docs/img/promo-release.svg").read_text(encoding="utf-8").replace("36s", "33.6s"), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "tools/check_release_page.py"),
                             "--root", str(ROOT), "--baseline-svg", str(original)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "320 holds" in result.stdout and "42 language home pages" in result.stdout
