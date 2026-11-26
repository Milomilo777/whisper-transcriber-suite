"""Checks for the 2.5 public notes and their in-app excerpt."""
import subprocess
import sys

import pytest

from core.updates import release_headline, release_highlights
from tools import check_public_release as policy
from tools import check_release_page as page

NOTES_PATH = page.ROOT / "docs/releases/2.5.0.md"
PLACEHOLDERS = (
    "RELEASE_DATE", "SIZE_INSTALLER", "SIZE_PORTABLE", "SIZE_ARM64", "SIZE_X64",
    "BUG_COUNT", "TOP_FIXES",
)


@pytest.fixture
def notes():
    return NOTES_PATH.read_text(encoding="utf-8")


def test_promo_has_current_callouts():
    svg = (page.ROOT / "docs/img/promo-release.svg").read_text(encoding="utf-8")
    assert '>Pick the audio track · 2.5</text>' in svg
    assert '>Compare a re-run</text>' in svg


@pytest.fixture
def draft_path(tmp_path):
    previous_notes = (page.ROOT / "docs/releases/2.4.0.md").read_text(encoding="utf-8")
    draft_path = tmp_path / "docs/releases/2.5.0.md"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(previous_notes.replace("More than 33 bugs fixed", "BUG_COUNT bugs fixed"),
                          encoding="utf-8")
    (tmp_path / "site").mkdir()
    (tmp_path / "site/facts.json").write_bytes((page.ROOT / "site/facts.json").read_bytes())
    return draft_path


def test_release_page_250_cli_reports_draft(tmp_path, draft_path):
    command = [sys.executable, str(page.ROOT / "tools/check_public_release.py"),
               "--root", str(tmp_path), "--notes", str(draft_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Draft 2.5.0" in result.stdout and "BUG_COUNT" in result.stdout


def test_notes_match_update_excerpt(notes):
    assert page.check_release_page_250(notes) == tuple(token for token in PLACEHOLDERS if token in notes)
    assert release_headline(notes) == notes.splitlines()[0].replace("**", "")
    assert tuple(line.split(".", 1)[0] for line in release_highlights(notes)) == (
        "Audio track choice", "Damaged media recovery", "Transcript editing",
    )


@pytest.mark.parametrize("extra", ["\n[Build](https://example.org/commit/1234567)", "\nSHA-256"])
def test_notes_reject_verification_metadata_in_draft(notes, extra):
    with pytest.raises(AssertionError, match="hash|verification metadata"):
        page.check_release_page_250(notes + extra)


@pytest.mark.parametrize("include_notes", [True, False])
def test_draft_rejected_for_upload(tmp_path, draft_path, include_notes):
    command = [sys.executable, str(page.ROOT / "tools/check_public_release.py"),
               "--root", str(tmp_path), "--assets", "WhisperTranscriberSuite-Installer-Windows-v2.5.0.exe"]
    if include_notes:
        command.extend(("--notes", str(draft_path)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "unfilled release placeholders" in result.stderr


def test_draft_can_be_filled(notes):
    values = ("2026-11-26", "238 MB", "355 MB", "277 MB", "304 MB", "64", "Downloads resume.")
    for token, value in zip(PLACEHOLDERS, values):
        notes = notes.replace(token, value)
    assert page.check_release_page_250(notes) == ()
    policy.check_release_notes(notes)


def test_highlight_limit_counts_separated_bullets(notes):
    bad_notes = notes.replace("- **Compare a re-run.**", "\n- **Compare a re-run.**", 1)
    screenshot = '\n\n<p align="center"><img src="https://raw.githubusercontent.com/Milomilo777/whisper-transcriber-suite/master/docs/img/screenshot-macos.png"'
    assert bad_notes.count(screenshot) == 1
    # Keep the extra bullet within the release body's length limit.
    bad_notes = bad_notes.replace(screenshot, "\n\n- **Extra.** x" + screenshot, 1)
    with pytest.raises(AssertionError, match="invalid highlight bullets"):
        page.check_release_page_250(bad_notes)


@pytest.mark.parametrize("old,new,message", [
    ("/master/docs/badges/", "/badges/", "missing badge"),
    ("v2.5.0-this-version.svg", "v2.4.0-this-version.svg", "missing badge"),
    ("/download/v2.5.0/WhisperTranscriberSuite-Installer", "/download/v2.4.0/WhisperTranscriberSuite-Installer",
     "invalid download"),
])
def test_notes_reject_stale_release_urls(notes, old, new, message):
    assert old in notes
    with pytest.raises(AssertionError, match=message):
        page.check_release_page_250(notes.replace(old, new))
