"""Every dialog the first tabs can open closes on Escape, doing what its close button does.

A click-through test (2026-10-21) found windows that ignored Escape. The model download
and model loading windows are left out on purpose: their close button cancels a large
download, which an accidental Escape must not do. Windowless: reads the source.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# file -> what Escape must call: the WM_DELETE_WINDOW handler, or destroy where the
# window has none (its close button destroys it).
CASES = {
    "app/dialogs/caption_choice.py": "pick(CHOICE_CANCEL)",
    "app/dialogs/hub_setup.py": "self._on_cancel()",
    "app/dialogs/model_advisor.py": "self.destroy()",
    "app/dialogs/quick_start.py": "self.skip()",
    "app/dialogs/statistics.py": "top.destroy()",
    "app/widgets/hardware_wizard.py": "self._on_close()",
    "app/widgets/offline_status.py": "self.destroy()",
}


def _escape_handlers(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "bind"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "<Escape>"
                and len(node.args) > 1 and isinstance(node.args[1], ast.Lambda)):
            found.append(ast.unparse(node.args[1].body))
    return found


@pytest.mark.parametrize("rel, handler", sorted(CASES.items()))
def test_escape_does_what_the_close_button_does(rel: str, handler: str) -> None:
    assert handler in _escape_handlers(ROOT / rel)


@pytest.mark.parametrize("rel", ["app/dialogs/caption_choice.py", "app/dialogs/hub_setup.py",
                                 "app/dialogs/quick_start.py", "app/widgets/hardware_wizard.py"])
def test_the_close_button_runs_the_same_handler(rel: str) -> None:
    source = (ROOT / rel).read_text(encoding="utf-8")
    handler = CASES[rel].removesuffix("()")
    assert f'protocol("WM_DELETE_WINDOW", {handler})' in source or \
        f'protocol("WM_DELETE_WINDOW", lambda: {CASES[rel]})' in source
