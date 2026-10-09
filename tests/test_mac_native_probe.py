"""``tools/mac_native_probe.py``: the probe that decides which macOS hooks the app may use.

Its real run needs a Mac (Aqua Tk); these tests pin what can be checked anywhere:
it stays standard-library only, it covers every hook ``app/mac_native.py`` registers,
and it declines politely when Tk is not Aqua.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "tools" / "mac_native_probe.py"
MAC_NATIVE = ROOT / "app" / "mac_native.py"


def _probe() -> Any:
    spec = importlib.util.spec_from_file_location("_mac_native_probe_under_test", PROBE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_probe_imports_only_the_standard_library() -> None:
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_every_hook_the_app_registers_is_probed() -> None:
    probe_text = PROBE.read_text(encoding="utf-8")
    for command in ("tkAboutDialog", "::tk::mac::ShowPreferences", "::tk::mac::ShowHelp",
                    "::tk::mac::OpenDocument", "::tk::mac::ReopenApplication"):
        assert command in MAC_NATIVE.read_text(encoding="utf-8"), command
        assert command in probe_text, command


def test_every_hook_the_app_relies_on_is_reported_by_the_probe() -> None:
    probe = _probe()
    text = PROBE.read_text(encoding="utf-8")
    assert probe.USED_BY_APP
    for hook in probe.USED_BY_APP:
        # reported as a PASS/FAIL line under exactly this name
        assert re.search(rf'_report\([^)]*"{hook}"', text, re.S), hook


def test_the_probe_declines_when_tk_is_not_aqua(capsys: pytest.CaptureFixture[str]) -> None:
    import tkinter as tk

    root = tk.Tk()
    try:
        system = str(root.tk.call("tk", "windowingsystem"))
    finally:
        root.destroy()
    if system == "aqua":
        pytest.skip("this is a Mac: the real probe runs here, see docs/MACOS_BUILD_NOTES.md")
    assert _probe().main([]) == 2
    out = capsys.readouterr().out
    assert "Tk patchlevel" in out and "SKIP" in out


def test_the_macos_workflow_runs_the_probe_as_a_non_blocking_extra_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "macos-app.yml").read_text(encoding="utf-8")
    at = workflow.index("name: Probe native macOS hooks")
    step = workflow[at: workflow.index("\n      - name:", at + 10)]
    assert "tools/mac_native_probe.py" in step
    assert "continue-on-error: true" in step  # a runner that is not an app bundle must not fail the build
    assert "timeout-minutes:" in step
