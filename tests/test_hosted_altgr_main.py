"""Exercise the real hosted loader without native APIs or nested pytest."""
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


HELPERS = Path(__file__).resolve().parents[1] / "tools/qa"
HEAD = "a" * 40


class Function:
    """A Python callable that accepts the loader's ctypes declarations."""
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class FakeLibraries:
    def __init__(self, unload=True):
        self.accesses = []
        self.calls = []
        self.current = 1
        self.unload = unload
        self.user32 = SimpleNamespace(**{
            name: Function(callback) for name, callback in {
                "GetKeyboardLayout": lambda thread: self.current,
                "GetKeyboardLayoutList": self.inventory,
                "LoadKeyboardLayoutW": lambda name, flags: 2,
                "ActivateKeyboardLayout": self.activate,
                "GetKeyboardLayoutNameW": self.layout_name,
                "UnloadKeyboardLayout": self.unload_layout,
            }.items()})
        self.kernel32 = SimpleNamespace(GetCurrentThreadId=Function(lambda: 42))

    def __getattribute__(self, name):
        if name in {"user32", "kernel32"}:
            object.__getattribute__(self, "accesses").append(name)
        return object.__getattribute__(self, name)

    def inventory(self, count, values):
        if values is not None:
            values[0] = 1
        return 1

    def activate(self, target, flags):
        self.calls.append(("activate", target, flags))
        previous, self.current = self.current, target
        return previous

    def layout_name(self, buffer):
        buffer.value = "00020407"
        return 1

    def unload_layout(self, target):
        self.calls.append(("unload", target))
        return int(self.unload)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("hosted_main_under_test", HELPERS / "hosted_altgr_loader.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    workspace, temporary = tmp_path / "workspace", tmp_path / "runner"
    workspace.mkdir()
    temporary.mkdir()
    for name, value in {
        "GITHUB_WORKSPACE": str(workspace), "RUNNER_TEMP": str(temporary),
        "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Windows", "QA_EXPECTED_HEAD": HEAD, "GITHUB_SHA": HEAD,
        "QA_ALTGR_KLID": "00020407", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(loader, "sys", SimpleNamespace(platform="win32", modules=sys.modules))

    def git(command, **kwargs):
        assert command[:3] == ["git", "-C", str(workspace)]
        if command[3:] == ["rev-parse", "HEAD"]:
            return HEAD + "\n"
        assert command[3:] == ["status", "--porcelain", "--untracked-files=no"]
        return ""

    monkeypatch.setattr(loader.subprocess, "check_output", git)
    output = temporary / "wts-altgr"
    nested_runs = []

    def blocked_pytest(arguments):
        nested_runs.append(arguments)
        receipt = getattr(loader, "_qa_test_receipt", {
            "status": "BLOCKED-ENV", "reason": "inert fixture has no desktop", "observations": []
        })
        (output / "raw.json").write_text(json.dumps(receipt), encoding="utf-8")
        (output / "results.xml").write_text(
            getattr(loader, "_qa_test_xml", '<testsuite tests="1" skipped="1" failures="0" errors="0">'
                    '<testcase name="inert"><skipped message="no desktop"/></testcase></testsuite>'), encoding="utf-8")
        return getattr(loader, "_qa_test_rc", 0)

    monkeypatch.setitem(sys.modules, "pytest", SimpleNamespace(main=blocked_pytest))
    previous = {name: sys.modules.pop(name, None) for name in ("receipt_io", "altgr_guards")}
    try:
        yield loader, output, nested_runs
    finally:
        for name, module in previous.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module


@pytest.mark.parametrize("required,expected_exit", [("0", 0), ("1", 1)])
def test_main_wires_required_mode_to_blocked_native_receipt(harness, monkeypatch, required, expected_exit):
    loader, output, nested_runs = harness
    libraries = FakeLibraries()
    monkeypatch.setattr(ctypes, "windll", libraries, raising=False)
    monkeypatch.setenv("QA_ALTGR_REQUIRED", required)
    assert loader.main() == expected_exit
    identity = json.loads((output / "loaderidentity.json").read_text(encoding="utf-8"))
    assert identity["required"] is (required == "1")
    assert identity["status"] == "BLOCKED-ENV"
    assert identity["pytest_exit"] == 0
    assert identity["original_layout_restored"] is True
    assert identity["new_layout_unloaded"] is True
    assert len(nested_runs) == 1
    assert libraries.calls == [("activate", 2, 0), ("activate", 1, 0), ("unload", 2)]


def test_main_rejects_invalid_required_mode_before_native_access(harness, monkeypatch):
    loader, output, nested_runs = harness
    libraries = FakeLibraries()
    monkeypatch.setattr(ctypes, "windll", libraries, raising=False)
    monkeypatch.setenv("QA_ALTGR_REQUIRED", "true")
    with pytest.raises(RuntimeError, match="QA_ALTGR_REQUIRED must be 0 or 1"):
        loader.main()
    assert libraries.accesses == []
    assert libraries.calls == []
    assert nested_runs == []
    assert not output.exists()


def test_main_cleanup_failure_overrides_nonblocking_environment_skip(harness, monkeypatch):
    loader, output, nested_runs = harness
    libraries = FakeLibraries(unload=False)
    monkeypatch.setattr(ctypes, "windll", libraries, raising=False)
    monkeypatch.setenv("QA_ALTGR_REQUIRED", "0")
    assert loader.main() == 1
    identity = json.loads((output / "loaderidentity.json").read_text(encoding="utf-8"))
    assert identity["required"] is False
    assert identity["status"] == "FAIL-CLEANUP"
    assert identity["cleanup_errors"] == ["Newly loaded layout could not be unloaded"]
    assert identity["original_layout_restored"] is True
    assert len(nested_runs) == 1


def test_main_propagates_raw_failure_message_to_annotation(harness, monkeypatch, capsys):
    loader, output, nested_runs = harness
    monkeypatch.setattr(ctypes, "windll", FakeLibraries(), raising=False)
    monkeypatch.setenv("QA_ALTGR_REQUIRED", "0")
    loader._qa_test_receipt = {"status": "FAIL", "message": "Owned focus/layout changed after chord", "observations": []}
    loader._qa_test_rc = 1
    loader._qa_test_xml = '<testsuite><testcase name="inert"><failure message="focus moved"/></testcase></testsuite>'
    assert loader.main() == 1
    assert "::error title=AltGr acceptance FAIL::Owned focus/layout changed after chord" in capsys.readouterr().out
    assert len(nested_runs) == 1
