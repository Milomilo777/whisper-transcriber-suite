"""The README's "Downloads by version" list must carry a badge for the current version.

A release that forgets its per-version badge leaves its downloads uncounted on the
project page (2.4.0 shipped without one). Bumping ``core.__version__`` without adding
the badge now fails here instead.
"""
import re
from pathlib import Path

from core import __version__

ROOT = Path(__file__).resolve().parents[1]
REPO = "Milomilo777/whisper-transcriber-suite"


def _badge_line(readme: str, tag: str, *, badge_path: str = "master/docs/badges") -> bool:
    image = f"https://raw.githubusercontent.com/{REPO}/{badge_path}/{tag}.svg"
    link = f"https://github.com/{REPO}/releases/tag/{tag}"
    pattern = rf"\[!\[{re.escape(tag)}\]\({re.escape(image)}\)\]\({re.escape(link)}\)"
    return re.search(pattern, readme) is not None


def test_readme_lists_the_current_version_badge():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("**Downloads by version**", 1)
    assert len(section) == 2, "README lost its 'Downloads by version' list"
    tag = f"v{__version__}"
    # The README still uses the existing branch until the first master badge run succeeds.
    assert _badge_line(section[1], tag, badge_path="badges"), f"README 'Downloads by version' has no badge for {tag}"


def test_badge_check_rejects_a_missing_or_wrong_badge():
    good = (f"[![v9.9.9](https://raw.githubusercontent.com/{REPO}/master/docs/badges/v9.9.9.svg)]"
            f"(https://github.com/{REPO}/releases/tag/v9.9.9)")
    assert _badge_line(good, "v9.9.9")
    assert not _badge_line(good, "v9.9.8")
    assert not _badge_line(good.replace("badges/v9.9.9.svg", "badges/v9.9.8.svg"), "v9.9.9")
    assert not _badge_line(good.replace("/master/docs/badges/", "/badges/"), "v9.9.9")
    assert not _badge_line(good.replace("tag/v9.9.9", "tag/v9.9.8"), "v9.9.9")
