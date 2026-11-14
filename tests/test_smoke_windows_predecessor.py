"""Pure runner boundaries/protocol controls; no registry/compiler/installer use."""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import sys

import pytest

PATH = Path(__file__).resolve().parents[1] / 'tools/smoke_windows_predecessor.py'
SPEC = importlib.util.spec_from_file_location('smoke_windows_predecessor', PATH)
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)
HEAD = 'a' * 40


def context():
    return {'platform': 'nt', 'bits': 64, 'admin': True, 'GITHUB_ACTIONS': 'true',
            'RUNNER_OS': 'Windows', 'RUNNER_ENVIRONMENT': 'github-hosted',
            'GITHUB_REPOSITORY': 'Milomilo777/whisper-transcriber-suite',
            'GITHUB_SHA': HEAD, 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ID': '123'}


def test_exact_elevated_hosted_vm_context_passes():
    gate.validate_context(context(), HEAD)


@pytest.mark.parametrize('field,value', [('platform', 'posix'), ('bits', 32), ('admin', False),
    ('GITHUB_ACTIONS', ''), ('RUNNER_ENVIRONMENT', 'self-hosted'), ('GITHUB_SHA', 'b' * 40),
    ('GITHUB_REPOSITORY', 'foreign/repo'), ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_RUN_ID', '')])
def test_developer_unprivileged_foreign_or_unknown_context_refused(field, value):
    row = context(); row[field] = value
    with pytest.raises(gate.GateError): gate.validate_context(row, HEAD)


@pytest.mark.parametrize('head', ['HEAD', 'abc123', 'A' * 40])
def test_head_must_be_full_lowercase_commit(head):
    with pytest.raises(gate.GateError): gate.validate_context(context(), head)


@pytest.mark.parametrize('tag,script', [('embed', 'installer_embed.iss'), ('compact', 'installer.iss')])
def test_compile_uses_full_production_iss_without_code_extraction_or_defines(tag, script):
    command = gate.compile_command(Path('ISCC.exe'), Path('checkout'), tag, Path('owned-output'))
    assert command[-1] == str(Path('checkout') / script)
    assert command == ['ISCC.exe', '/Qp', '/Oowned-output', '/Fp18-' + tag, str(Path('checkout') / script)]
    assert not any(part.startswith('/D') for part in command)


def test_compiled_allow_requires_zero_exit_and_production_allow_log():
    gate.validate_setup_outcome(True, 0, gate.ALLOW_MARKER)
    for code, text in [(0, ''), (7, gate.ALLOW_MARKER), (0, gate.ALLOW_MARKER + gate.REFUSE_MARKER)]:
        with pytest.raises(gate.GateError): gate.validate_setup_outcome(True, code, text)


def test_expected_overlap_accepts_only_exact_prepare_to_install_refusal():
    gate.validate_setup_outcome(False, 7, gate.REFUSE_MARKER)


def test_arbitrary_nonzero_error_is_not_overlap_proof():
    with pytest.raises(gate.GateError): gate.validate_setup_outcome(False, 5, 'Access denied')


def test_missing_production_refusal_log_is_not_overlap_proof():
    with pytest.raises(gate.GateError): gate.validate_setup_outcome(False, 7, 'Different prepare failure')


def test_setup_is_silent_uses_selected_target_and_never_launches_app():
    args = gate.setup_command(Path('real-compiled.exe'), Path('owned/target'), Path('owned/log'))
    assert '/ALLUSERS' in args and '/VERYSILENT' in args and '/TASKS=' in args
    assert '/DIR=' + str(Path('owned/target')) in args
    assert all('postinstall' not in arg.lower() for arg in args)


def test_workroot_is_fresh_and_bounded(tmp_path):
    temporary = tmp_path / 'runner-temp'; temporary.mkdir()
    selected = temporary / 'owned-proof'
    assert gate.validate_work_root(selected, temporary) == selected
    for bad in (temporary, tmp_path / 'outside'):
        with pytest.raises(gate.GateError): gate.validate_work_root(bad, temporary)
    selected.mkdir()
    with pytest.raises(gate.GateError): gate.validate_work_root(selected, temporary)


@pytest.mark.parametrize('scenario', ['different', 'same-case', 'parent', 'child', 'junction'])
def test_fixture_cases_select_both_overlap_directions_without_reimplementing_pascal(scenario, tmp_path):
    old, new, alias = gate.scenario_paths(tmp_path, scenario)
    if scenario == 'different': assert old.parent == new.parent and old != new
    elif scenario == 'same-case': assert str(old).casefold() == str(new).casefold() and str(old) != str(new)
    elif scenario == 'parent': assert old.parent == new
    elif scenario == 'child': assert new.parent == old
    else: assert alias == new.parent and alias.parent == old.parent


def test_same_case_alias_preserves_exact_owned_parent_spelling(tmp_path):
    root = tmp_path / 'Owned-Mixed-Work'
    old, target, alias = gate.scenario_paths(root, 'same-case')
    assert str(target.parent) == str(root)
    assert target.name == old.name.swapcase() and str(target) != str(old)
    assert alias is None


def test_same_case_alias_remains_lexically_inside_a_posix_work_root():
    root = PurePosixPath('/tmp/Owned-Mixed-Work')
    old, target, _ = gate.scenario_paths(root, 'same-case')
    assert target.is_relative_to(root)
    assert target.parent == old.parent == root
    assert target.name == old.name.swapcase()


class RegistryProtocol:
    """Synthetic protocol only; no winreg/Win32 calls exist in these tests."""
    def __init__(self):
        self.old = {}; self.current = None; self.removed = []; self.checked = 0

    def create_old(self, view, path, owner):
        assert view not in self.old
        self.old[view] = (path, owner)

    def remove_old(self, view, path, owner):
        assert self.old[view] == (path, owner)
        del self.old[view]; self.removed.append(view)

    def current_owned_at(self, target):
        assert self.current is None or self.current == target
        return self.current is not None

    def require_clean(self):
        self.checked += 1
        assert not self.old and self.current is None


def workspace(tmp_path):
    (tmp_path / 'logs').mkdir()
    return tmp_path


def test_unrelated_setup_failure_is_failed_but_owned_registration_cleanup_runs(tmp_path, monkeypatch):
    registry = RegistryProtocol()
    def failed(args, cwd, output, **kwargs):
        Path(next(a[5:] for a in args if a.startswith('/LOG='))).write_text('Access denied')
        return 5
    monkeypatch.setattr(gate, 'run_process', failed)
    row = gate.execute_case('embed', '64', 'same-case', Path('not-executed.exe'), {'gui.py': '0' * 64},
                            workspace(tmp_path), registry)
    assert row['status'] == 'FAILED' and row['setup_exit'] == 5
    assert registry.removed == ['64'] and row['cleanup_verified'] is True


def test_unknown_child_timeout_never_runs_uninstaller_or_removes_registration(tmp_path, monkeypatch):
    registry = RegistryProtocol(); calls = []
    def timeout(*args, **kwargs):
        calls.append(args)
        raise gate.UnsafeTimeout('synthetic unknown child')
    monkeypatch.setattr(gate, 'run_process', timeout)
    row = gate.execute_case('embed', '32', 'same-case', Path('not-executed.exe'), {'gui.py': '0' * 64},
                            workspace(tmp_path), registry)
    assert row['status'] == 'FAILED' and row['discard_vm_required'] is True
    assert row['cleanup_verified'] is False and registry.removed == [] and len(calls) == 1


def test_32bit_overlap_case_keeps_nonoverlap_64bit_registration_visible(tmp_path, monkeypatch):
    registry = RegistryProtocol(); observed = []
    def refused(args, cwd, output, **kwargs):
        observed.append(dict(registry.old))
        Path(next(a[5:] for a in args if a.startswith('/LOG='))).write_text(gate.REFUSE_MARKER)
        return 7
    monkeypatch.setattr(gate, 'run_process', refused)
    row = gate.execute_case('compact', 'mixed32', 'cross-view-mask', Path('not-executed.exe'),
                            {'WhisperTranscriberSuite.exe': '0' * 64}, workspace(tmp_path), registry)
    assert row['status'] == 'PASS' and row['cleanup_verified'] is True
    assert set(observed[0]) == {'64', '32'} and observed[0]['64'][0] != observed[0]['32'][0]
    assert registry.removed == ['32', '64']


def test_allowed_full_payload_is_measured_then_native_uninstall_protocol_is_required(tmp_path, monkeypatch):
    registry = RegistryProtocol(); calls = []; content = b'synthetic protocol payload'
    def process(args, cwd, output, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            target = Path(next(a[5:] for a in args if a.startswith('/DIR='))); target.mkdir()
            (target / 'gui.py').write_bytes(content)
            (target / 'unins000.exe').write_bytes(b'synthetic non-executed uninstaller')
            registry.current = target
            Path(next(a[5:] for a in args if a.startswith('/LOG='))).write_text(gate.ALLOW_MARKER)
        else:
            (registry.current / 'gui.py').unlink(); (registry.current / 'unins000.exe').unlink()
            registry.current = None
        return 0
    monkeypatch.setattr(gate, 'run_process', process)
    row = gate.execute_case('embed', '64', 'different', Path('not-executed.exe'),
                            {'gui.py': hashlib.sha256(content).hexdigest()}, workspace(tmp_path), registry)
    assert row['status'] == 'PASS' and row['uninstall_exit'] == 0 and row['cleanup_verified'] is True
    assert len(calls) == 2 and Path(calls[1][0]).name == 'unins000.exe'


def test_changed_registry_owner_makes_cleanup_fail_closed(tmp_path, monkeypatch):
    registry = RegistryProtocol()
    def refused(args, cwd, output, **kwargs):
        Path(next(a[5:] for a in args if a.startswith('/LOG='))).write_text(gate.REFUSE_MARKER)
        return 7
    def foreign(*args): raise gate.GateError('synthetic ownership changed')
    monkeypatch.setattr(gate, 'run_process', refused)
    monkeypatch.setattr(registry, 'remove_old', foreign)
    row = gate.execute_case('embed', '64', 'same-case', Path('not-executed.exe'), {'gui.py': '0' * 64},
                            workspace(tmp_path), registry)
    assert row['status'] == 'FAILED' and row['cleanup_verified'] is False and row['discard_vm_required'] is True


def test_escaped_target_is_refused_before_registry_or_setup(tmp_path, monkeypatch):
    work = tmp_path / 'OwnedWork'
    work.mkdir()
    outside = tmp_path / 'OutsideWork'
    registry = RegistryProtocol()
    monkeypatch.setattr(gate, 'scenario_paths', lambda root, scenario: (root / 'old', outside, None))
    monkeypatch.setattr(gate, 'run_process', lambda *a, **k: pytest.fail('Escaped target reached Setup'))
    with pytest.raises(gate.GateError, match='Native target escaped'):
        gate.execute_case('embed', '64', 'same-case', Path('not-executed.exe'), {}, workspace(work), registry)
    assert not registry.old and not registry.removed and not outside.exists()
