"""Extra edge cases for tools/docs_check.py beyond tests/test_docs_check.py.

Each case pins one input the checker must handle: the file exists, so no
problem may be reported for it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("docs_check_extra", ROOT / "tools" / "docs_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["docs_check_extra"] = mod
    spec.loader.exec_module(mod)
    return mod


dc = _load()


def test_link_target_with_balanced_parentheses_resolves(tmp_path: Path) -> None:
    (tmp_path / "a_(b).md").write_text("ok\n", encoding="utf-8")
    (tmp_path / "doc.md").write_text("[x](a_(b).md)\n", encoding="utf-8")
    problems, linked = dc.check(tmp_path)
    assert not [p for p in problems if "broken link" in p], problems
    assert (tmp_path / "a_(b).md").resolve() in linked
