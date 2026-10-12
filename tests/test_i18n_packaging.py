"""Every build ships app/i18n.py and the app/locales catalogs."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    "whisper_project_onefile.spec": "('app/locales', 'app/locales')",
    "whisper_project_onedir.spec": "('app/locales', 'app/locales')",
    "platform/macos/pyinstaller/whisper_project_mac.spec":
        "(os.path.join(_REPO_ROOT, 'app', 'locales'), 'app/locales')",
}


def _datas_and_hidden(text: str) -> tuple[str, list[str]]:
    """The source of the Analysis datas list and the string entries of hiddenimports."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Analysis":
            kw = {k.arg: k.value for k in node.keywords}
            datas = ast.get_source_segment(text, kw["datas"]) or ""
            hidden = [e.value for e in getattr(kw["hiddenimports"], "elts", [])
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            return datas, hidden
    raise AssertionError("no Analysis(...) call")


@pytest.mark.parametrize("spec,entry", sorted(SPECS.items()))
def test_spec_ships_the_locales_folder_and_the_module(spec: str, entry: str) -> None:
    text = (ROOT / spec).read_text(encoding="utf-8")
    datas, hidden = _datas_and_hidden(text)
    assert entry in datas
    assert "app.i18n" in hidden


def test_embed_build_copies_app_with_its_catalogs() -> None:
    bat = (ROOT / "build_embed_installer.bat").read_text(encoding="utf-8")
    app_copy = next(line for line in bat.splitlines()
                    if line.startswith('robocopy "%ROOT%app" "%BUILD%\\app"'))
    assert " /E " in app_copy
    # Only bytecode is excluded; JSON catalogs must not be.
    excluded = re.findall(r"/XF ([^/]+)", app_copy)
    assert all("json" not in x.lower() for x in excluded)
    assert 'if not exist "%BUILD%\\app\\locales\\en.json"' in bat


def test_source_catalog_is_where_the_builds_take_it_from() -> None:
    assert (ROOT / "app" / "locales" / "en.json").is_file()
