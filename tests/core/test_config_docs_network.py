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
        model="m", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished", word_count=1,
    )
    missing = [k for k in payload if f"`{k}`" not in section]
    assert not missing, f"payload fields missing from docs/CONFIG.md: {missing}"


def _sent_table_fields(section: str) -> set[str]:
    """Field names in the first cell of the "What is sent" table."""
    table = section.split("What is sent", 1)[1].split("Never sent", 1)[0]
    fields: set[str] = set()
    for line in table.splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            fields.update(re.findall(r"`(\w+)`", first_cell))
    return fields


def test_no_documented_field_is_missing_from_the_payload(config_md: str) -> None:
    # The reverse direction: the docs must not claim a field the app no
    # longer sends (file_name was dropped from the payload).
    section = _section(config_md, "### Usage statistics (P4-4)")
    documented = _sent_table_fields(section)
    assert "model" in documented and "cpu_count" in documented  # parser control
    payload = stats.build_stats_payload(
        model="m", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished", word_count=1,
    )
    extra = sorted(documented - set(payload))
    assert not extra, f"docs/CONFIG.md lists fields the payload lacks: {extra}"


# Public texts that summarise the usage statistics in prose.
_STATS_SUMMARIES = [
    ROOT / "README.md",
    ROOT / "docs" / "COMPARISON.md",
    ROOT / "site" / "llms-full.txt",
]
_FILE_NAME = re.compile(r"file(?:'s)? ?name", re.I)
_NEGATION = re.compile(r"\b(?:no|never|not|without)\b[^.;:]{0,15}$", re.I)


def _stats_blocks(text: str) -> list[str]:
    """Paragraphs, list items and table rows that mention usage statistics."""
    blocks = re.split(r"\n\s*\n|\n(?=\s*[-*] )|\n(?=\|)", text)
    return [b for b in blocks if re.search(r"usage[- ]statistics", b, re.I)]


def _claims_file_name_is_sent(block: str) -> bool:
    return any(
        not _NEGATION.search(block[max(0, m.start() - 25):m.start()])
        for m in _FILE_NAME.finditer(block)
    )


def test_stats_file_name_guard_controls() -> None:
    assert _claims_file_name_is_sent("usage statistics: the file name, model")
    assert _claims_file_name_is_sent("usage-statistics row (it includes the file name)")
    assert not _claims_file_name_is_sent("usage statistics: model, never the file's name.")
    assert not _claims_file_name_is_sent("| Usage statistics on by default, no file name |")


def test_public_texts_never_say_the_file_name_is_sent() -> None:
    checked = 0
    for path in _STATS_SUMMARIES:
        for block in _stats_blocks(path.read_text(encoding="utf-8")):
            checked += 1
            assert not _claims_file_name_is_sent(block), (path.name, block)
    assert checked >= 4  # README, COMPARISON (2) and llms-full were found


def test_config_never_sent_line_names_the_file(config_md: str) -> None:
    section = _section(config_md, "### Usage statistics (P4-4)")
    never = section.split("Never sent:", 1)[1].split(".", 1)[0]
    assert "file's name" in never


def test_documented_defaults_match_the_code(config_md: str) -> None:
    assert f"`{DEFAULT_CONFIG['stats_url']}`" in _row(config_md, "stats_url")
    assert f"`{DEFAULT_CONFIG['config_url']}`" in _row(config_md, "config_url")
    expected = "`true`" if DEFAULT_CONFIG["telemetry_opt_in"] else "`false`"
    assert expected in _row(config_md, "telemetry_opt_in")


def test_network_table_names_every_default_endpoint(config_md: str) -> None:
    from core import js_runtime, updates, yt_dlp_update

    section = _section(config_md, "## Network use")
    endpoints = [
        DEFAULT_CONFIG["config_url"],
        DEFAULT_CONFIG["stats_url"],
        DEFAULT_CONFIG["llm_remote_base_url"],
        updates.latest_release_api_url(updates.GITHUB_OWNER, updates.GITHUB_REPO),
        js_runtime._RELEASE_BASE,
        yt_dlp_update.RELEASE_API_URL,
        yt_dlp_update.RELEASE_DOWNLOADS_URL,
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


# The translated READMEs once said "nothing is uploaded / sent" and "no
# telemetry by default", which the default-on usage statistics contradict.
_I18N_READMES = sorted((ROOT / "docs" / "i18n").glob("README.*.md"))
# Persian phrases as escapes: "nothing ... upload" and "telemetry".
_FA_NOTHING_UPLOADED = "\u0647\u06cc\u0686\u200c\u0686\u06cc\u0632 \u0622\u067e\u0644\u0648\u062f"
_FA_TELEMETRY = "\u062a\u0644\u0647\u200c\u0645\u062a\u0631\u06cc"
_NOTHING_IS_SENT = re.compile(
    "|".join([
        "Nichts wird hochgeladen", "keine Telemetrie",
        "Rien n'est envoy", "aucune télémétrie",
        "No se sube nada", "sin telemetría",
        "Nada é enviado", "sem telemetria",
        "何もアップロードされず", "テレメトリなし",
        "아무것도 업로드되지", "원격 수집 없음",
        "没有任何内容被上传", "不发送任何遥测",
        _FA_NOTHING_UPLOADED, _FA_TELEMETRY,
    ]),
    re.I,
)


def test_translated_readme_guard_controls() -> None:
    assert len(_I18N_READMES) == 8  # de es fa fr ja ko pt zh-CN
    assert _NOTHING_IS_SENT.search("Alle Backends laufen lokal. Nichts wird hochgeladen, ...")
    assert _NOTHING_IS_SENT.search("sin coste por minuto, sin telemetría por defecto")
    assert _NOTHING_IS_SENT.search("... " + _FA_NOTHING_UPLOADED + " ...")
    assert not _NOTHING_IS_SENT.search("Nutzungsstatistiken; abschalten unter Help")


@pytest.mark.parametrize("path", _I18N_READMES, ids=lambda p: p.name)
def test_translated_readmes_never_say_nothing_is_sent(path: Path) -> None:
    match = _NOTHING_IS_SENT.search(path.read_text(encoding="utf-8"))
    assert match is None, (path.name, match and match.group(0))


@pytest.mark.parametrize("path", _I18N_READMES, ids=lambda p: p.name)
def test_translated_readmes_name_the_stats_switch(path: Path) -> None:
    assert "**Help → Usage statistics**" in path.read_text(encoding="utf-8")
