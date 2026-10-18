"""Write the country -> website-language table used by site/functions/index.js.

From Unicode CLDR territory data (Babel): for each country, the website languages spoken by at least
MIN_SHARE of its people, most spoken first. English counts too, so in a country where many people
read English (India, the Emirates, Belgium) the visitor's browser language decides; where English
is not common (Iran, Germany, Brazil) the country's language is the default. Countries whose only
candidate is English are left out (English is the fallback).

    pip install babel==2.18.0        # only needed to regenerate; the table is committed
    python tools/site_country_lang.py          # rewrite the table inside site/functions/index.js
    python tools/site_country_lang.py --check  # exit 1 if it is stale (skipped without Babel)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "site", "functions", "index.js")
START, END = "// country-lang:start (tools/site_country_lang.py)", "// country-lang:end"
MIN_SHARE = 15.0
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
from make_i18n_readmes import LANGS  # noqa: E402

SUPPORTED = {c for c, _n in LANGS}


def site_code(cldr: str, territory: str) -> str | None:
    """CLDR language code -> website language code, or None when the site has no such language."""
    base = cldr.split("_")[0]
    if cldr in ("zh_Hant",) or (base == "zh" and territory in ("TW", "HK", "MO")):
        return "zh-TW"
    if base == "zh":
        return "zh-CN"
    if base == "pt":
        return "pt-BR" if territory == "BR" else "pt"
    if base in ("nb", "no"):
        return "nb"
    if base == "sr":
        return "sr"
    if base == "tl":
        return "fil"
    return base if base in SUPPORTED else None


def table() -> dict[str, list[str]]:
    from babel.languages import get_territory_language_info
    from babel.core import get_global

    out: dict[str, list[str]] = {}
    for territory in sorted(get_global("territory_languages")):
        if not re.fullmatch(r"[A-Z]{2}", territory):
            continue
        info = get_territory_language_info(territory)
        ranked = sorted(info.items(), key=lambda kv: -kv[1].get("population_percent", 0))
        codes: list[str] = []
        for cldr, data in ranked:
            if data.get("population_percent", 0) < MIN_SHARE:
                continue
            code = site_code(cldr, territory)
            if code and code not in codes:
                codes.append(code)
        if codes and codes != ["en"]:
            out[territory] = codes
    return out


def render(t: dict[str, list[str]]) -> str:
    rows = json.dumps(t, separators=(",", ":"), sort_keys=True)
    # one line per letter keeps the diff readable
    body = re.sub(r',"(?=[A-Z]{2}":)', ',\n  "', rows[1:-1])
    return f"{START}\nconst COUNTRY_LANGS = {{\n  {body}\n}};\n{END}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    try:
        block = render(table())
    except ImportError:
        print("Babel is not installed: skipped (pip install babel==2.18.0)")
        return 0
    with open(TARGET, encoding="utf-8", newline="") as f:
        js = f.read()
    i, j = js.find(START), js.find(END)
    if i == -1 or j == -1:
        print(f"markers not found in {TARGET}")
        return 1
    new = js[:i] + block + js[j + len(END):]
    if a.check:
        print("current" if new == js else "stale: run python tools/site_country_lang.py")
        return 0 if new == js else 1
    with open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"wrote {block.count(':[')} countries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
