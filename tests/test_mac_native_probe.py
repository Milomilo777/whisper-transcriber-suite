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


def test_a_step_that_raises_is_reported_under_its_own_name_and_fails_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe = _probe()
    probe._results.clear()

    def boom() -> None:
        raise RuntimeError("objc went away")

    crashed = probe.run_steps([("fine", lambda: None), ("show_help", boom)])
    assert crashed == ["show_help"]
    assert ("FAIL", "show_help", "check raised RuntimeError: objc went away") in probe._results
    assert "<lambda>" not in capsys.readouterr().out
    assert probe.exit_code(probe._results, crashed) == 1


def test_exit_code_fails_for_hooks_the_app_uses_only() -> None:
    probe = _probe()
    assert probe.exit_code([("PASS", "about", "ok"), ("FAIL", "dock_menu", "no")], []) == 0
    assert probe.exit_code([("FAIL", "apple_menu", "no")], []) == 0
    for hook in ("special_menus", "about", "show_preferences_createcommand"):
        assert probe.exit_code([("FAIL", hook, "no")], []) == 1, hook
    assert probe.exit_code([], ["menus"]) == 1


def test_main_names_every_step_creates_objc_in_the_guarded_block_and_always_destroys_the_root() -> None:
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    # the steps are (name, callable) pairs, never anonymous lambdas reported as "<lambda>"
    steps = next(n for n in ast.walk(main) if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Name) and n.target.id == "steps")
    assert isinstance(steps.value, ast.List) and steps.value.elts
    assert all(isinstance(e, ast.Tuple) and isinstance(e.elts[0], ast.Constant) for e in steps.value.elts)
    # _ObjC() is built inside a try block
    guarded = [t for t in ast.walk(main) if isinstance(t, ast.Try)
               and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_ObjC"
                       for stmt in t.body for c in ast.walk(stmt))]
    assert guarded
    # the root is destroyed in a finally block
    assert any(isinstance(t, ast.Try) and any(
        isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "destroy"
        for stmt in t.finalbody for c in ast.walk(stmt)) for t in ast.walk(main))


# ------------------------------------------------------------------ appearance (card C2.73)

class _FakeEventRoot:
    """Records the virtual-event bindings of the appearance probe and fires them by hand."""

    def __init__(self) -> None:
        self.bound: dict[str, Any] = {}

    def bind(self, sequence: str, func: Any, add: Any = None) -> None:
        self.bound[sequence] = func


def test_the_appearance_hooks_the_app_uses_are_the_ones_the_probe_proves() -> None:
    from app.theme import system_appearance, system_fonts

    probe = _probe()
    assert tuple(probe.APPEARANCE_EVENTS[:2]) == tuple(system_appearance.MAC_APPEARANCE_EVENTS)
    assert "<<TkSystemAppearanceChanged>>" in probe.APPEARANCE_EVENTS      # checked, reported, unused
    assert system_fonts.SYSTEM_UI_FAMILY in probe.SYSTEM_FONT_CANDIDATES
    for hook in ("appearance_isdark", "appearance_events", "system_font_name", "app_active"):
        assert hook in probe.USED_BY_APP


def test_the_flip_is_never_run_without_the_flag_and_changes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    probe = _probe()
    probe._results.clear()
    flips: list[bool] = []
    probe.set_system_dark_mode = flips.append  # type: ignore[assignment]
    probe.probe_appearance_events(_FakeEventRoot(), object(), flip=False)  # type: ignore[arg-type]
    assert flips == []
    assert probe._results[0][0] == "INFO" and "--flip-appearance" in probe._results[0][2]


def test_the_original_appearance_is_restored_even_when_no_event_arrives() -> None:
    probe = _probe()
    probe._results.clear()
    setting = {"dark": False}
    calls: list[bool] = []

    def set_mode(dark: bool) -> None:
        calls.append(dark)
        setting["dark"] = dark

    probe.system_dark_mode = lambda: setting["dark"]
    probe.set_system_dark_mode = set_mode
    probe.tk_isdark = lambda _root: setting["dark"]
    probe._pump = lambda *a, **k: None          # no event ever arrives
    probe.probe_appearance_events(_FakeEventRoot(), object(), flip=True)  # type: ignore[arg-type]
    assert setting["dark"] is False and calls[0] is True and calls[-1] is False
    statuses = {hook: status for status, hook, _d in probe._results}
    assert statuses["appearance_events"] == "FAIL"        # no event: a failure, not a pass
    assert statuses["appearance_restore"] == "PASS"


def test_the_original_appearance_is_restored_when_a_step_raises() -> None:
    probe = _probe()
    probe._results.clear()
    setting = {"dark": True}

    def set_mode(dark: bool) -> None:
        if dark is False and setting["dark"] is True:
            setting["dark"] = False       # the flip itself works ...
            return
        setting["dark"] = dark

    probe.system_dark_mode = lambda: setting["dark"]
    probe.set_system_dark_mode = set_mode

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("window server gone")

    probe._pump = boom
    with pytest.raises(RuntimeError):
        probe.probe_appearance_events(_FakeEventRoot(), object(), flip=True)  # type: ignore[arg-type]
    assert setting["dark"] is True        # the finally step put the original setting back
