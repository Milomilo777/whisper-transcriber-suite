"""No native process is started or signalled by these ownership controls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tests.mac_path_alias import directory_alias


@pytest.fixture
def proof():
    path = Path(__file__).resolve().parents[1] / "platform/macos/pyinstaller/copied_gui_process.py"
    spec = importlib.util.spec_from_file_location("copied_gui_process_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.psutil = __import__("psutil")
    return module


class Process:
    def __init__(self, executable, *, created=1001, pid=42424, running=True, status="running"):
        self.executable = str(executable)
        self.created = created
        self.pid = pid
        self.running = running
        self.state = status
        self.terminated = False
        self.timeout = False

    def exe(self): return self.executable
    def create_time(self): return self.created
    def is_running(self): return self.running
    def status(self): return self.state
    def terminate(self): self.terminated = True
    def wait(self, timeout):
        if self.timeout:
            import psutil
            raise psutil.TimeoutExpired(timeout, self.pid)
        self.running = False


@pytest.mark.parametrize("kind", ["regex-path", "argument-only", "old", "zombie", "exited"])
def test_foreign_or_stale_process_never_qualifies(proof, tmp_path, monkeypatch, kind):
    target = tmp_path / "wts-apps.ABCDEF/Suite.app/Contents/MacOS/Suite"
    process = Process(target)
    if kind == "regex-path": process.executable = str(target).replace("apps.", "appsX").replace("Suite.app", "SuiteXapp")
    if kind == "argument-only": process.executable = str(tmp_path / "other"); process.arguments = [str(target)]
    if kind == "old": process.created = 999
    if kind == "zombie": process.state = proof.psutil.STATUS_ZOMBIE
    if kind == "exited": process.running = False
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([process]))
    receipt = tmp_path / "receipt.json"
    assert not proof.capture(str(target), 1000, receipt)
    assert json.loads(receipt.read_text())["processes"] == []
    assert not process.terminated


@pytest.mark.parametrize("change", ["none", "reused", "other-exe", "exited", "timeout", "denied"])
def test_cleanup_revalidates_captured_identity(proof, tmp_path, monkeypatch, change):
    target = tmp_path / "Suite.app/Contents/MacOS/Suite"
    original = Process(target)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), 1000, receipt)
    current = Process(target)
    if change == "reused": current.created += 1
    if change == "other-exe": current.executable = str(tmp_path / "foreign")
    if change == "exited": current.running = False
    if change == "timeout": current.timeout = True
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([current]))
    def lookup(pid):
        assert pid == original.pid
        if change == "denied": raise proof.psutil.AccessDenied(pid)
        return current
    monkeypatch.setattr(proof.psutil, "Process", lookup)
    assert proof.stop(str(target), 1000, receipt) == (change not in ("timeout", "denied", "reused"))
    assert current.terminated == (change in ("none", "timeout"))


def test_canonical_alias_matches_exact_executable(proof, tmp_path, monkeypatch):
    real = tmp_path / "real"; real.mkdir()
    alias = tmp_path / "alias"; directory_alias(alias, real)
    process = Process(real / "Suite")
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([process]))
    assert proof.capture(str(alias / "Suite"), 1000, tmp_path / "receipt.json")


def test_invalid_receipt_fails_before_any_signal(proof, tmp_path, monkeypatch):
    target = tmp_path / "Suite"
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"executable": str(target.resolve()), "started": 1000,
        "processes": [{"pid": 42424, "created": 1001}, {"pid": 1, "created": 1001}]}))
    def forbidden(pid): raise AssertionError("Invalid receipt reached process lookup")
    monkeypatch.setattr(proof.psutil, "Process", forbidden)
    with pytest.raises(ValueError): proof.stop(str(target), 1000, receipt)


def test_known_owned_but_uninspectable_state_is_unknown(proof, tmp_path, monkeypatch):
    target = tmp_path / "Suite"
    process = Process(target)
    def denied(): raise proof.psutil.AccessDenied(process.pid)
    process.status = denied
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([process]))
    receipt = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError): proof.capture(str(target), 1000, receipt)
    assert not receipt.exists()


@pytest.mark.parametrize("created", [999, 1002])
def test_late_bootloader_child_prevents_cleanup_without_signalling_it(proof, tmp_path, monkeypatch, created):
    target = tmp_path / "Suite"
    original = Process(target)
    late = Process(target, pid=42425, created=created)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), 1000, receipt)
    monkeypatch.setattr(proof.psutil, "Process", lambda pid: original)
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original, late]))
    assert not proof.stop(str(target), 1000, receipt)
    assert original.terminated
    assert not late.terminated


def test_missing_psutil_is_unknown_before_any_process_lookup():
    helper = Path(__file__).resolve().parents[1] / "platform/macos/pyinstaller/copied_gui_process.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run([sys.executable, "-S", str(helper), "preflight"],
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "ModuleNotFoundError" in result.stderr
    assert "Traceback" not in result.stderr


def test_preflight_accepts_the_dependency_environment(proof, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["copied_gui_process.py", "preflight"])
    assert proof.main() == 0


@pytest.mark.parametrize("phase,error_name", [
    ("lookup", "AccessDenied"), ("identity", "AccessDenied"),
    ("terminate", "AccessDenied"), ("wait", "AccessDenied"),
    ("wait", "TimeoutExpired"),
])
def test_unresolved_cleanup_reports_phase_and_exact_identity(
        proof, tmp_path, monkeypatch, capsys, phase, error_name):
    target = tmp_path / "Suite"
    original = Process(target, pid=43958, created=1794659727.278269)
    started = 1794659727.0
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), started, receipt)
    capsys.readouterr()
    def fail(*args, **kwargs):
        if error_name == "TimeoutExpired":
            raise proof.psutil.TimeoutExpired(3, original.pid)
        raise proof.psutil.AccessDenied(original.pid, "PRIVATE_EXCEPTION_MESSAGE")
    def lookup(pid):
        assert pid == original.pid
        if phase == "lookup":
            return fail()
        return original
    monkeypatch.setattr(proof.psutil, "Process", lookup)
    if phase != "lookup":
        monkeypatch.setattr(original, {"identity": "is_running", "terminate": "terminate", "wait": "wait"}[phase], fail)
    monkeypatch.setattr(proof, "owned_processes", lambda *args, **kwargs: [])
    assert not proof.stop(str(target), started, receipt)
    output = capsys.readouterr().err
    events = [json.loads(line)["copied_gui_cleanup"] for line in output.splitlines()]
    assert events[0] == {"phase": phase, "error_type": error_name,
                         "identity": {"pid": 43958, "created": 1794659727.278269}}
    assert events[-1] == {"phase": "complete", "outcome": "unresolved", "remaining": []}
    assert "PRIVATE_EXCEPTION_MESSAGE" not in output
    assert original.terminated == (phase == "wait")


def test_remaining_process_diagnostic_does_not_authorize_a_new_signal(
        proof, tmp_path, monkeypatch, capsys):
    target = tmp_path / "Suite"
    original, late = Process(target), Process(target, pid=42425, created=1002)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), 1000, receipt)
    capsys.readouterr()
    monkeypatch.setattr(proof.psutil, "Process", lambda pid: original)
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original, late]))
    assert not proof.stop(str(target), 1000, receipt)
    event = json.loads(capsys.readouterr().err)["copied_gui_cleanup"]
    assert event == {"phase": "complete", "outcome": "unresolved",
                     "remaining": [{"pid": late.pid, "created": late.created}]}
    assert original.terminated and not late.terminated


def test_unavailable_remaining_scan_emits_phase_before_propagating(
        proof, tmp_path, monkeypatch, capsys):
    target = tmp_path / "Suite"
    original = Process(target)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), 1000, receipt)
    capsys.readouterr()
    monkeypatch.setattr(proof.psutil, "Process", lambda pid: original)
    def unknown(*args, **kwargs):
        raise RuntimeError("PRIVATE_EXCEPTION_MESSAGE")
    monkeypatch.setattr(proof, "owned_processes", unknown)
    with pytest.raises(RuntimeError):
        proof.stop(str(target), 1000, receipt)
    output = capsys.readouterr().err
    assert json.loads(output)["copied_gui_cleanup"] == {
        "phase": "remaining_scan", "error_type": "RuntimeError"}
    assert "PRIVATE_EXCEPTION_MESSAGE" not in output


@pytest.mark.parametrize("sink_error", [OSError, BrokenPipeError, ValueError])
@pytest.mark.parametrize("outcome", ["resolved", "timeout", "lookup-error", "scan-error"])
def test_failed_diagnostic_sink_preserves_cleanup_outcome_and_exception(
        proof, tmp_path, monkeypatch, sink_error, outcome):
    target = tmp_path / "Suite"
    original = Process(target)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(proof.psutil, "process_iter", lambda: iter([original]))
    assert proof.capture(str(target), 1000, receipt)
    original_error = RuntimeError("Original ownership failure")
    def lookup(pid):
        if outcome == "lookup-error":
            raise original_error
        return original
    monkeypatch.setattr(proof.psutil, "Process", lookup)
    original.timeout = outcome == "timeout"
    def remaining(*args, **kwargs):
        if outcome == "scan-error":
            raise original_error
        return []
    monkeypatch.setattr(proof, "owned_processes", remaining)
    def failed_print(*args, **kwargs):
        assert kwargs["file"] is proof.sys.stderr
        raise sink_error("Diagnostic sink is unavailable")
    monkeypatch.setattr(proof, "print", failed_print, raising=False)
    if outcome.endswith("error"):
        with pytest.raises(RuntimeError) as caught:
            proof.stop(str(target), 1000, receipt)
        assert caught.value is original_error
    else:
        assert proof.stop(str(target), 1000, receipt) is (outcome == "resolved")
