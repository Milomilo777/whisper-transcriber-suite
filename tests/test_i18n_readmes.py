"""The translated READMEs: one per interface language, language links current, relative links that resolve."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.i18n import SUPPORTED_LANGUAGES

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_i18n_readmes", ROOT / "tools" / "make_i18n_readmes.py")
assert _spec and _spec.loader
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def test_every_interface_language_has_a_readme_and_no_other() -> None:
    assert tool.LANGS[0] == ("en", "English") and len(tool.LANGS) == len(SUPPORTED_LANGUAGES)
    assert [p.name for p in map(tool.path_of, (c for c, _ in tool.LANGS)) if not p.exists()] == []
    on_disk = {p.name[len("README."):-len(".md")] for p in (ROOT / "docs" / "i18n").glob("README.*.md")}
    assert on_disk == {c for c, _ in tool.LANGS[1:]}


def test_language_links_are_current() -> None:
    stale = [code for code, _name in tool.LANGS
             if tool.render(code, tool.path_of(code).read_text(encoding="utf-8"))
             != tool.path_of(code).read_text(encoding="utf-8")]
    assert stale == [], "run: python tools/make_i18n_readmes.py"


def test_block_marks_the_current_language_and_links_every_other() -> None:
    text = tool.block("de")
    assert "<b>Deutsch</b>" in text and 'href="README.de.md"' not in text
    assert text.count("<a href=") == len(tool.LANGS) - 1
    assert '<a href="../../README.md">English</a>' in text


def test_render_converts_the_old_flag_switcher_once() -> None:
    old = ('<div align="center">\n\n<p>\n  <a href="../../README.md"><img src="https://flagcdn.com/16x12/us.png"'
           ' alt="" width="16" height="12"> English</a> ∙\n  <b>Deutsch</b>\n</p>\n\n</div>\n')
    once = tool.render("de", old)
    assert tool.START in once and "flagcdn" not in once
    assert tool.render("de", once) == once
    assert tool.render("de", once.replace("\n", "\r\n")) == once


@pytest.mark.parametrize("damage", ["drop_end", "second_start", "old_switcher_left"])
def test_render_refuses_a_damaged_block(damage: str) -> None:
    good = tool.render("de", '<div align="center">\n\n<p>\n  <a href="README.fr.md">Français</a>\n</p>\n\n</div>\n')
    bad = {
        "drop_end": good.replace(tool.END, ""),
        "second_start": good + tool.START + "\n",
        "old_switcher_left": good + '\n<p>\n  <a href="README.fr.md">Français</a>\n</p>\n',
    }[damage]
    with pytest.raises(ValueError):
        tool.render("de", bad)


def test_translations_name_the_licence_holder_of_readme() -> None:
    # Machine translations once invented other copyright holders; the line must match README.md.
    holder = re.search(r"Copyright \(c\) (\d{4} [\w-]+)", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert holder
    wrong = [p.name for p in sorted((ROOT / "docs" / "i18n").glob("README.*.md"))
             if f"(c) {holder.group(1)} (" not in p.read_text(encoding="utf-8")]
    assert wrong == []


def test_relative_links_in_translations_resolve() -> None:
    broken = []
    for path in sorted((ROOT / "docs" / "i18n").glob("README.*.md")):
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r'\]\(([^()\s]+)\)|(?:href|src)="([^"]+)"', text):
            url = next(t for t in target if t)
            if re.match(r"^[a-z]+:|^#", url):
                continue
            if not (path.parent / url.split("#")[0]).exists():
                broken.append(f"{path.name}: {url}")
    assert broken == []
