"""tools/render_graphics.py: the board-name handling of its command line (no Chrome needed)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("render_graphics", ROOT / "tools" / "render_graphics.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["render_graphics"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load()


def test_an_unknown_board_name_is_a_usage_error_not_a_traceback(capsys, monkeypatch):
    """A typo on the command line must exit 2 with the valid names, not raise KeyError."""
    monkeypatch.setattr(sys, "argv", ["render_graphics.py", "heroes"])
    assert rg.main() == 2
    err = capsys.readouterr().err
    assert "heroes" in err and "hero" in err
