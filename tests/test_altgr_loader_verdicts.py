"""Native acceptance plumbing exercised without a desktop or keyboard API."""
import ast
import ctypes
import importlib.util
import shutil
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest


HELPERS = Path(__file__).resolve().parents[1] / "tools/qa"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("rc,clean,status,missing,expected", [
    (0, True, "PASS", [], ("PASS", 0)),
    (0, False, "BLOCKED-ENV", [65], ("BLOCKED-ENV", 0)),
    (1, False, "BLOCKED-ENV", [65], ("FAIL", 1)),
    (0, False, "FAIL", [], ("FAIL", 1)),
    (0, False, "PASS", [], ("FAIL", 1)),
    (0, True, "PASS", [67], ("INCOMPLETE-KEY-COVERAGE", 1)),
])
def test_verdict_keeps_environment_distinct_from_failure(rc, clean, status, missing, expected):
    assert load("hosted_altgr_loader").final_verdict(rc, clean, status, missing, skipped_xml=not clean) == expected


def test_xml_failure_overrides_a_blocked_raw_receipt():
    assert load("hosted_altgr_loader").final_verdict(0, False, "BLOCKED-ENV", [], True) == ("FAIL", 1)


def test_only_expected_environment_errors_can_be_nonblocking():
    loader = load("hosted_altgr_loader")
    assert loader.exception_verdict(loader.HostedEnvironmentError("layout unavailable")) == ("BLOCKED-ENV", 0)
    for error in (RuntimeError("bug"), NameError("bug"), OSError("io failure"), KeyboardInterrupt()):
        assert loader.exception_verdict(error) == ("FAIL", 1)


def test_required_mode_keeps_environment_verdict_but_fails_the_gate():
    loader = load("hosted_altgr_loader")
    assert loader.final_verdict(0, False, "BLOCKED-ENV", [], skipped_xml=True, required=True) == ("BLOCKED-ENV", 1)
    assert loader.exception_verdict(loader.HostedEnvironmentError("missing E1"), required=True) == ("BLOCKED-ENV", 1)


@pytest.mark.parametrize("xml", [
    '<testsuite/>', '<testsuite><testcase/></testsuite>',
    '<testsuite><testcase><skipped/></testcase><testcase><skipped/></testcase></testsuite>',
    '<testsuite><testcase><skipped/><failure/></testcase></testsuite>',
])
def test_blocked_receipt_requires_exactly_one_consistent_skipped_case(xml):
    loader = load("hosted_altgr_loader")
    clean, failed, skipped = loader.junit_evidence(ET.fromstring(xml))
    assert loader.final_verdict(0, clean, "BLOCKED-ENV", [], failed, skipped_xml=skipped) == ("FAIL", 1)


def test_one_real_skipped_case_can_only_report_environment_status():
    loader = load("hosted_altgr_loader")
    clean, failed, skipped = loader.junit_evidence(ET.fromstring('<testsuite><testcase><skipped/></testcase></testsuite>'))
    assert (clean, failed, skipped) == (False, False, True)
    assert loader.final_verdict(0, clean, "BLOCKED-ENV", [65], failed, skipped_xml=skipped) == ("BLOCKED-ENV", 0)
    assert loader.final_verdict(0, clean, "PASS", [], failed, skipped_xml=skipped) == ("FAIL", 1)


def test_environment_skip_is_visible_in_actions_warning_and_summary(tmp_path, capsys):
    loader = load("hosted_altgr_loader")
    summary = tmp_path / "summary.md"
    loader.report_verdict({"status": "BLOCKED-ENV", "message": "missing E1\n::error::spoof"}, summary)
    assert "::warning title=AltGr acceptance BLOCKED-ENV::missing E1%0A::error::spoof" in capsys.readouterr().out
    assert "BLOCKED-ENV" in summary.read_text(encoding="utf-8")


def test_real_failure_is_visible_in_actions_error(tmp_path, capsys):
    load("hosted_altgr_loader").report_verdict({"status": "FAIL", "message": "hook failed"}, tmp_path / "summary.md")
    assert "::error title=AltGr acceptance FAIL::hook failed" in capsys.readouterr().out


def test_packet_writer_import_executes_the_hashed_packet_file(tmp_path, monkeypatch):
    loader = load("hosted_altgr_loader")
    monkeypatch.delitem(sys.modules, "receipt_io", raising=False)
    shutil.copyfile(HELPERS / "receipt_io.py", tmp_path / "receipt_io.py")
    writer = loader.load_packet_helper(tmp_path, "receipt_io")
    assert Path(writer.__file__).resolve() == (tmp_path / "receipt_io.py").resolve()
    writer.write_json_checkpoint(tmp_path / "probe.json", {"status": "PASS"})
    assert (tmp_path / "probe.json").read_text(encoding="utf-8").strip().startswith("{")
    with pytest.raises(RuntimeError, match="preloaded"):
        loader.load_packet_helper(tmp_path, "receipt_io")
    sys.modules.pop("receipt_io")


def test_missing_packet_writer_cannot_fall_back_to_cached_checkout_module(tmp_path, monkeypatch):
    loader = load("hosted_altgr_loader")
    monkeypatch.setitem(sys.modules, "receipt_io", SimpleNamespace())
    with pytest.raises(RuntimeError, match="preloaded"):
        loader.load_packet_helper(tmp_path, "receipt_io")
    sys.modules.pop("receipt_io")
    with pytest.raises(FileNotFoundError):
        loader.load_packet_helper(tmp_path, "receipt_io")
    assert "receipt_io" not in sys.modules


def test_packet_inventory_includes_every_native_sibling_import():
    loader = load("hosted_altgr_loader")
    tree = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    siblings = {node.module + ".py" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                and node.module and (HELPERS / (node.module + ".py")).is_file()}
    assert siblings == {"altgr_guards.py", "receipt_io.py"}
    assert siblings <= set(loader.PACKET_HELPERS)


def valid_row(key):
    return {"vk": key, "phase": "actual_app_hook", "text": "\u202f",
            "expected_altgr": "\u202f", "virtual_actions": [],
            "handler_results": [{"keycode": key, "state": 0x20004, "keysym": "a", "result": None}]}


def test_all_four_real_hook_rows_cover_the_required_keys():
    loader = load("hosted_altgr_loader")
    assert loader.covered_keys([valid_row(key) for key in loader.KEYS]) == list(loader.KEYS)


@pytest.mark.parametrize("change", [
    {"phase": "plain_entry_baseline"}, {"text": "wrong"},
    {"text": "", "expected_altgr": ""}, {"text": "\t", "expected_altgr": "\t"},
    {"virtual_actions": ["<<Copy>>"]}, {"handler_results": ["break"]},
    {"expected_altgr": None}, {"vk": 999}, {"handler_results": []}, {"handler_results": "x"},
])
def test_incomplete_or_intercepted_hook_row_is_not_coverage(change):
    assert load("hosted_altgr_loader").covered_keys([{**valid_row(65), **change}]) == []


@pytest.mark.parametrize("status,tag", [("BLOCKED-ENV", "skipped"), ("FAIL", "error"), ("FAIL-CLEANUP", "error")])
def test_fallback_junit_has_one_explicit_nonpassing_case(tmp_path, status, tag):
    loader = load("hosted_altgr_loader")
    loader.write_fallback_junit(tmp_path, status, "a <reason> & details")
    root = ET.parse(tmp_path / "results.xml").getroot()
    assert root.attrib["tests"] == "1"
    assert root.attrib["skipped"] == ("1" if tag == "skipped" else "0")
    assert root.attrib["errors"] == ("1" if tag == "error" else "0")
    cases = list(root.iter("testcase"))
    assert len(cases) == 1 and len(cases[0]) == 1
    assert cases[0][0].tag == tag
    assert cases[0][0].text == "a <reason> & details"
    assert cases[0][0].get("type") == status


def test_fallback_junit_preserves_existing_pytest_evidence(tmp_path):
    path = tmp_path / "results.xml"
    original = b'<testsuite tests="1"><testcase name="real" /></testsuite>'
    path.write_bytes(original)
    load("hosted_altgr_loader").write_fallback_junit(tmp_path, "FAIL", "fallback")
    assert path.read_bytes() == original


def test_left_control_and_extended_right_alt_use_mapped_physical_scans():
    guards = load("altgr_guards")
    calls = []

    def mapping(key, mode, hkl):
        calls.append((key, mode, hkl))
        return {0xA2: 0x1D, 0xA5: 0xE038, 65: 0x1E}[key]

    assert guards.keyboard_packets([(0xA2, 0), (0xA5, 1), (65, 0), (65, 2), (0xA5, 3), (0xA2, 2)], mapping, 123) == [
        (0xA2, 0x1D, 8), (0xA5, 0x38, 9), (65, 0x1E, 8),
        (65, 0x1E, 10), (0xA5, 0x38, 11), (0xA2, 0x1D, 10)]
    assert all(mode == 4 and hkl == 123 for _, mode, hkl in calls)


@pytest.mark.parametrize("key,scan", [(0xA2, 0), (0xA2, 0xE01D), (0xA5, 0x38), (65, 0)])
def test_unverified_scans_are_refused_before_sendinput(key, scan):
    guards = load("altgr_guards")
    with pytest.raises(guards.GuardError):
        guards.keyboard_packets([(key, 0)], lambda *args: scan, 123)


class LayoutAPI:
    def __init__(self, name="00020407", activated=True, readable=True):
        self.name, self.activated, self.readable = name, activated, readable
        self.current = 1

    def ActivateKeyboardLayout(self, target, flags):
        assert flags == 0
        if self.activated:
            self.current = target
        return 1 if self.activated else 0

    def GetKeyboardLayout(self, thread):
        assert thread == 0
        return self.current

    def GetKeyboardLayoutNameW(self, buffer):
        buffer.value = self.name
        return self.readable


def test_layout_activation_records_exact_e1_identity():
    result = load("hosted_altgr_loader").activate_layout_verdict(LayoutAPI(), 2, "00020407")
    assert result == {"status": "PASS", "active_klid": "00020407"}


@pytest.mark.parametrize("api", [LayoutAPI("00000407"), LayoutAPI(activated=False), LayoutAPI(readable=False)])
def test_layout_substitution_or_failure_records_blocked_verdict(api):
    result = load("hosted_altgr_loader").activate_layout_verdict(api, 2, "00020407")
    assert result["status"] == "BLOCKED-ENV"
    assert result["reason"]


def test_actual_native_sender_reuses_the_selected_layout_for_cleanup():
    tree = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    structures = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                  and n.name in {"Keyboard", "Mouse", "Payload", "Input"}]
    native = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Native")
    send = next(n for n in native.body if isinstance(n, ast.FunctionDef) and n.name == "send")
    calls, packets = [], []

    def mapping(key, mode, hkl):
        calls.append((key, mode, hkl))
        return {0xA2: 0x1D, 0xA5: 0xE038, 65: 0x1E}[key]

    def submit(count, values, size):
        packets.extend((p.payload.ki.vk, p.payload.ki.scan, p.payload.ki.flags) for p in values)
        return count

    namespace = {"ctypes": ctypes, "keyboard_packets": load("altgr_guards").keyboard_packets,
                 "user": SimpleNamespace(MapVirtualKeyExW=mapping, SendInput=submit),
                 "layout": SimpleNamespace(current=lambda: 999), "selection": {"selected": 123},
                 "data": {"injected_events": 0}}
    exec(compile(ast.Module(body=structures + [send], type_ignores=[]), "<actual-native-sender>", "exec"), namespace)
    assert namespace["send"](None, [(65, 2), (0xA5, 3), (0xA2, 2)]) == 3
    assert calls == [(65, 4, 123), (0xA5, 4, 123), (0xA2, 4, 123)]
    assert packets == [(65, 0x1E, 10), (0xA5, 0x38, 11), (0xA2, 0x1D, 10)]


def test_actual_probe_does_not_downgrade_cleanup_failure_to_environment_skip():
    guards = load("altgr_guards")
    tree = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    native_try = next(n for n in probe.body if isinstance(n, ast.Try))
    raises = ast.Raise(exc=ast.Name(id="injected", ctx=ast.Load()), cause=None)
    node = ast.Try(body=[raises], handlers=native_try.handlers, orelse=[], finalbody=[])

    def forbidden_skip(*args):
        pytest.fail("Cleanup errors must be FAIL, never SKIP")

    error = guards.GuardCleanupError("release incomplete")
    data = {}
    namespace = {"GuardCleanupError": guards.GuardCleanupError, "GuardError": guards.GuardError,
                 "injected": error, "data": data, "save": lambda: None,
                 "pytest": SimpleNamespace(skip=forbidden_skip)}
    with pytest.raises(guards.GuardCleanupError):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "<actual-native-handlers>", "exec"), namespace)
    assert data["status"] == "FAIL"


@pytest.mark.parametrize("phase", ["plain_entry_baseline", "actual_app_hook"])
def test_actual_probe_guard_failure_is_fatal_after_baseline_passes(phase):
    class EnvironmentSkip(RuntimeError):
        pass

    def skip(*args):
        raise EnvironmentSkip()

    guards = load("altgr_guards")
    tree = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    native_try = next(n for n in probe.body if isinstance(n, ast.Try))
    node = ast.Try(body=[ast.Raise(exc=ast.Name(id="injected", ctx=ast.Load()), cause=None)],
                   handlers=native_try.handlers, orelse=[], finalbody=[])
    data = {}
    namespace = {"GuardCleanupError": guards.GuardCleanupError, "GuardError": guards.GuardError,
                 "injected": guards.GuardError("focus moved"), "data": data, "save": lambda: None,
                 "pytest": SimpleNamespace(skip=skip), "phase": phase}
    expected = guards.GuardError if phase == "actual_app_hook" else EnvironmentSkip
    with pytest.raises(expected):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "<actual-native-handlers>", "exec"), namespace)
    assert data["status"] == ("FAIL" if phase == "actual_app_hook" else "BLOCKED-ENV")
