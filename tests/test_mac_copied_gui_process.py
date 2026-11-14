"""No native process is started or signalled by these ownership controls."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def proof():
    path = Path(__file__).resolve().parents[1] / "platform/macos/pyinstaller/copied_gui_process.py"
    spec = importlib.util.spec_from_file_location("copied_gui_process_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
    alias = tmp_path / "alias"; alias.symlink_to(real, target_is_directory=True)
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
