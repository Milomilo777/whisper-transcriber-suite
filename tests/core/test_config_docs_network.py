"""docs/CONFIG.md must describe the usage stats and network use as the code does.

The stats switch is on by default, so the docs and the code comments around
it must not call it "anonymous", "opt-in" or "off by default", and the
documented defaults and payload fields must match the code. These checks
read the real files, so a code change that is not reflected in the docs
(a new payload field, a new default URL) fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import stats
from core.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[2]
CONFIG_MD = ROOT / "docs" / "CONFIG.md"

# Wording that is false for a switch that is on by default.
_BANNED = re.compile(r"\banonymous\b|\bopt-in\b|\bopted[- ]in\b|off by default", re.I)


def _section(markdown: str, heading: str) -> str:
    """Text from ``heading`` up to the next heading of the same or higher level."""
    lines = markdown.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = lines.index(heading)
    out: list[str] = []
    for line in lines[start + 1:]:
        m = re.match(r"(#+) ", line)
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    return "\n".join(out)


def _row(markdown: str, key: str) -> str:
    """The table row whose first cell is ``key`` (backticked)."""
    for line in markdown.splitlines():
        if line.startswith(f"| `{key}` |"):
            return line
    raise AssertionError(f"no table row for {key!r} in docs/CONFIG.md")


@pytest.fixture(scope="module")
def config_md() -> str:
    return CONFIG_MD.read_text(encoding="utf-8")


def test_every_payload_field_is_documented(config_md: str) -> None:
    section = _section(config_md, "### Usage statistics (P4-4)")
    payload = stats.build_stats_payload(
        file_name="a.wav", model="m", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished", word_count=1,
    )
    missing = [k for k in payload if f"`{k}`" not in section]
    assert not missing, f"payload fields missing from docs/CONFIG.md: {missing}"


def test_documented_defaults_match_the_code(config_md: str) -> None:
    assert f"`{DEFAULT_CONFIG['stats_url']}`" in _row(config_md, "stats_url")
    assert f"`{DEFAULT_CONFIG['config_url']}`" in _row(config_md, "config_url")
    expected = "`true`" if DEFAULT_CONFIG["telemetry_opt_in"] else "`false`"
    assert expected in _row(config_md, "telemetry_opt_in")


def test_network_table_names_every_default_endpoint(config_md: str) -> None:
    from core import js_runtime, updates

    section = _section(config_md, "## Network use")
    endpoints = [
        DEFAULT_CONFIG["config_url"],
        DEFAULT_CONFIG["stats_url"],
        DEFAULT_CONFIG["llm_remote_base_url"],
        updates.latest_release_api_url(updates.GITHUB_OWNER, updates.GITHUB_REPO),
        js_runtime._RELEASE_BASE,
    ]
    missing = [u for u in endpoints if u not in section]
    assert not missing, f"default endpoints missing from Network use: {missing}"


@pytest.mark.parametrize(
    "heading", ["### Usage statistics (P4-4)", "## Network use"],
)
def test_stats_docs_avoid_false_wording(config_md: str, heading: str) -> None:
    hits = _BANNED.findall(_section(config_md, heading))
    assert not hits, f"{heading}: {hits}"


@pytest.mark.parametrize(
    "rel_path", ["core/stats.py", "app/observability.py"],
)
def test_stats_modules_avoid_false_wording(rel_path: str) -> None:
    text = (ROOT / rel_path).read_text(encoding="utf-8")
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _BANNED.search(line)
    ]
    assert not hits, f"{rel_path}: {hits}"


def test_about_dialog_privacy_text_avoids_false_wording() -> None:
    pytest.importorskip("tkinter")
    from app.app import build_about_sections

    text = "\n".join(
        "\n".join([title, *(sub for sub, _ in subs),
                   *(b for _, bullets in subs for b in bullets)])
        for title, subs in build_about_sections()
    )
    assert not re.search(r"\banonymous\b|opt-in telemetry", text, re.I)
    assert "no network call" not in text.lower()
    assert "nothing leaves your computer" not in text.lower()
