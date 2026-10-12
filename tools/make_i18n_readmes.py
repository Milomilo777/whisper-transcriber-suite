"""Keep the language links of README.md and every docs/i18n/README.*.md in sync.

The translated READMEs are ordinary files edited by translators; this tool only owns the block of language links
between the ``language-links`` markers near the top of each file, so adding a language means one new row in
``LANGS`` and one run::

    python tools/make_i18n_readmes.py           # rewrite the blocks
    python tools/make_i18n_readmes.py --check   # exit 1 when a block is stale (the test suite runs this)

The first run also converts the older flag-image switcher (a ``<p>`` of flagcdn links) and the plain English
line in README.md into marked blocks. A translation records the English commit it follows in a
``<!-- translated from README.md at commit <sha> -->`` comment; ``git diff <sha> -- README.md`` shows what it lacks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "docs" / "i18n"
START, END = "<!-- language-links:start -->", "<!-- language-links:end -->"

sys.path.insert(0, str(ROOT))
from app.i18n import SUPPORTED_LANGUAGES  # noqa: E402  (standard library only, no Tk)

# app/i18n.py code -> README file code, for the codes whose README kept an older name.
APP_TO_FILE = {"zh-Hans": "zh-CN", "zh-Hant": "zh-TW", "pt-PT": "pt"}
# (README file code, native name) in the order of the interface-language picker, English first: the
# picker's own list is the single source, so a new interface language needs only its README file.
LANGS: list[tuple[str, str]] = [(APP_TO_FILE.get(lang.code, lang.code), lang.endonym) for lang in SUPPORTED_LANGUAGES]

_MARKED = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
_OLD_SWITCHER = re.compile(r"^<p>\n(?:.*\n)*?</p>$", re.M)  # the flag-image <p> block of the earlier generator
_OLD_EN_LINE = re.compile(r"^English · \[.*$", re.M)


def path_of(code: str) -> Path:
    return ROOT / "README.md" if code == "en" else I18N / f"README.{code}.md"


def block(current: str) -> str:
    if current == "en":
        links = ["**English**"] + [f"[{name}](docs/i18n/README.{code}.md)" for code, name in LANGS[1:]]
        body = " · ".join(links)
    else:
        links = [f"<b>{name}</b>" if code == current else
                 f'<a href="{"../../README.md" if code == "en" else f"README.{code}.md"}">{name}</a>'
                 for code, name in LANGS]
        body = "<p>\n" + " ·\n".join(links) + "\n</p>"
    return f"{START}\n\n{body}\n\n{END}"


def render(code: str, text: str) -> str:
    """``text`` with its language-link block replaced; ValueError when the file has no block to replace or a
    damaged one (unpaired markers, or an old switcher left next to the marked block)."""
    text = text.replace("\r\n", "\n")
    new = block(code)
    starts, ends = text.count(START), text.count(END)
    if starts or ends:
        if starts != 1 or ends != 1 or text.index(START) > text.index(END):
            raise ValueError(f"{path_of(code).relative_to(ROOT)}: {starts} start / {ends} end language-link markers")
        rest = _MARKED.sub("", text)
        if any("README." in m.group(0) for m in _OLD_SWITCHER.finditer(rest)) or _OLD_EN_LINE.search(rest):
            raise ValueError(f"{path_of(code).relative_to(ROOT)}: an old language switcher is left next to the block")
        return _MARKED.sub(lambda _m: new, text, count=1)
    # Older files carry either the flag-image <p> or a copy of the plain English line.
    old = None if code == "en" else next((m for m in _OLD_SWITCHER.finditer(text) if "README." in m.group(0)), None)
    old = old or _OLD_EN_LINE.search(text)
    if old is None:
        raise ValueError(f"{path_of(code).relative_to(ROOT)}: no language-link block found")
    return text[:old.start()] + new + text[old.end():]


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale, missing = [], []
    for code, _name in LANGS:
        path = path_of(code)
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
            continue
        # The repository stores LF; a Windows checkout with core.autocrlf shows CRLF, so compare and write LF.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        new = render(code, text)
        if new != text:
            stale.append(str(path.relative_to(ROOT)))
            if not check:
                path.write_text(new, encoding="utf-8", newline="\n")
    extra = sorted(p.name for p in I18N.glob("README.*.md")
                   if p.name[len("README."):-len(".md")] not in {c for c, _ in LANGS})
    for name in missing:
        print(f"missing: {name}")
    for name in extra:
        print(f"not in LANGS: docs/i18n/{name}")
    print(("stale: " if check else "rewrote: ") + (", ".join(stale) or "none"))
    return 1 if missing or extra or (check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
