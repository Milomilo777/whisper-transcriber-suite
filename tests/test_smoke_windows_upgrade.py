from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import struct
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_workflow_gates_the_real_historical_installer_at_default_location():
    workflow = (ROOT / '.github/workflows/windows-installer.yml').read_text()
    assert 'tools/smoke_windows_upgrade.py' in workflow, 'CI only upgrades the new installer over itself; historical recursive uninstall records are untested'
    assert '--confirm-clean-machine' in workflow
    assert '--expected-version' in workflow
    assert 'wts-historical-upgrade/*.log' in workflow
    assert workflow.index('tools/smoke_windows_upgrade.py `') < workflow.index('name: Smoke test (silent install')
    paths = workflow.split('    paths:', 1)[1].split('  workflow_dispatch:', 1)[0]
    assert '      - tools/smoke_windows_upgrade.py' in paths
    assert '      - tools/smoke_windows_install.py' in paths
    assert '      - tools/check_installer_upgrade_files.py' in paths
    assert 'fetch-depth: 0' in workflow
    assert workflow.index('python tools/check_installer_upgrade_files.py') < workflow.index('run: call build_embed_installer.bat')
    lifecycle = workflow.split('name: Real v2.3.1 upgrade', 1)[1].split('      - name:', 1)[0]
    assert 'continue-on-error' not in lifecycle and 'if ($LASTEXITCODE -ne 0) { throw' in lifecycle


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location('upgrade_gate', ROOT / 'tools/smoke_windows_upgrade.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case(gate, tmp_path, monkeypatch):
    old = tmp_path / 'old.exe'
    old.write_bytes(b'old installer')
    new = tmp_path / 'new.exe'
    new.write_bytes(b'new installer')
    work = tmp_path / 'logs with spaces'
    work.mkdir()
    root = tmp_path / 'Program Files' / 'WhisperTranscriberSuite'
    group = tmp_path / 'Start Menu' / gate.APP_NAME
    desktop = tmp_path / 'Public Desktop'
    desktop.mkdir()
    commands, versions, faults = [], [], set()
    report = {'status': 'FAILED'}
    monkeypatch.setattr(gate, 'BASELINE_SHA256', hashlib.sha256(old.read_bytes()).hexdigest())
    monkeypatch.setattr(gate, 'BASELINE_SIZE', old.stat().st_size)
    monkeypatch.setattr(gate, 'require_windows_admin', lambda: None)
    monkeypatch.setattr(gate, 'default_paths', lambda: (root, group, desktop))
    monkeypatch.setattr(gate, 'registered_versions', lambda: versions[:])
    monkeypatch.setattr(gate.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('offline test reached network'))

    def links(version):
        return [group / f'{gate.APP_NAME} {version}.lnk', desktop / f'{gate.APP_NAME} {version}.lnk']

    def fake_run(argv, label, output, *, installer=False):
        commands.append((label, argv, installer))
        if label in faults:
            raise gate.GateError(f'{label} failed synthetically')
        if label == 'old-install':
            assert Path(argv[0]) == old
            for folder in gate.SENTINEL_FOLDERS:
                (root / folder).mkdir(parents=True)
            for rel in ['python/python.exe', 'python/pythonw.exe', 'core/__init__.py', 'gui.py', 'unins000.exe']:
                (root / rel).write_bytes(b'tracked app')
            group.mkdir(parents=True)
            for path in links('2.3.1'):
                path.write_bytes(b'old shortcut')
            versions[:] = ['2.3.1']
        elif label == 'upgrade':
            assert Path(argv[0]) == new
            assert len(list(root.glob('*/user-preservation-*.bin'))) == 6
            versions[:] = ['2.4.0']
            if 'old-shortcut' not in faults:
                for path in links('2.3.1'):
                    path.unlink()
            if 'missing-shortcut' not in faults:
                for path in links('2.4.0'):
                    path.write_bytes(b'new shortcut')
        elif label == 'uninstall':
            for rel in ['python/python.exe', 'python/pythonw.exe', 'core/__init__.py', 'gui.py', 'unins000.exe']:
                if rel not in faults:
                    (root / rel).unlink()
            if 'registration' not in faults:
                versions.clear()
            for path in links('2.4.0'):
                if 'current-shortcut' not in faults:
                    path.unlink()
        if label in ('upgrade', 'uninstall'):
            sentinel = next(root.glob('*/user-preservation-*.bin'))
            if label + '-delete' in faults:
                sentinel.unlink()
            if label + '-modify' in faults:
                sentinel.write_bytes(b'changed user data')

    monkeypatch.setattr(gate, 'run_checked', fake_run)
    return SimpleNamespace(old=old, new=new, work=work, root=root, group=group,
                           desktop=desktop, commands=commands, versions=versions,
                           faults=faults, report=report, links=links)


def test_published_baseline_pin_is_exact(gate):
    assert gate.BASELINE_VERSION == '2.3.1'
    assert gate.BASELINE_URL == 'https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v2.3.1/WhisperTranscriberSuite-Installer-Windows-v2.3.1.exe'
    assert gate.BASELINE_SHA256 == '97d86d9cda0ed1eb2d7edf967b374dc59a3c7a472bc43f9e4f3c20432054f435'
    assert gate.BASELINE_SIZE == 251072859


def test_lifecycle_uses_different_installers_no_directory_override_and_hashes_twice(gate, case):
    gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert [c[0] for c in case.commands] == ['old-install', 'old-version', 'upgrade', 'new-version', 'installed-smoke', 'uninstall']
    assert case.report['status'] == 'PASS'
    assert len(case.report['completed']) == 3
    assert len(case.report['sentinels']) == 6
    for label, argv, native in case.commands:
        if label in ('old-install', 'upgrade'):
            assert native and '/ALLUSERS' in argv and '/TASKS=desktopicon' in argv
            assert not any(arg.upper().startswith('/DIR') for arg in argv)
        if label.endswith('version'):
            assert str(case.root / 'python/python.exe') == argv[0]
            assert 'core.__version__' in argv[-1]
    for path, digest in case.report['sentinels'].items():
        assert gate.sha256_file(Path(path)) == digest
    assert case.root.is_dir()  # User additions are deliberately retained.


@pytest.mark.parametrize('fault', ['upgrade-delete', 'upgrade-modify', 'uninstall-delete', 'uninstall-modify'])
def test_gate_rejects_loss_at_each_phase_before_reporting_success(gate, case, fault):
    case.faults.add(fault)
    with pytest.raises(gate.GateError, match='destroyed or changed sentinel'):
        gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert case.report['status'] == 'FAILED'
    if fault.startswith('upgrade'):
        assert 'uninstall' not in [c[0] for c in case.commands]


@pytest.mark.parametrize('fault', ['old-shortcut', 'missing-shortcut', 'current-shortcut', 'registration', 'python/python.exe', 'python/pythonw.exe', 'gui.py', 'core/__init__.py'])
def test_gate_rejects_stale_links_registration_or_owned_app_files(gate, case, fault):
    case.faults.add(fault)
    with pytest.raises(gate.GateError):
        gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert case.report['status'] == 'FAILED'


@pytest.mark.parametrize('phase', ['old-version', 'new-version', 'installed-smoke', 'uninstall'])
def test_failed_native_or_installed_check_cannot_be_reported_as_pass(gate, case, phase):
    case.faults.add(phase)
    with pytest.raises(gate.GateError, match=phase):
        gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert case.report['status'] == 'FAILED'
    if phase != 'uninstall':
        assert 'uninstall' not in [c[0] for c in case.commands]


@pytest.mark.parametrize('existing', ['root', 'group', 'desktop', 'registry'])
def test_existing_installation_or_user_files_are_refused_without_execution(gate, case, existing):
    if existing in ('root', 'group'):
        getattr(case, existing).mkdir(parents=True)
    elif existing == 'desktop':
        case.links('2.3.1')[1].write_bytes(b'pre-existing user shortcut')
    else:
        case.versions.append('2.3.1')
    with pytest.raises(gate.GateError, match='clean machine'):
        gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert not case.commands


def test_wrong_cached_historical_hash_never_executes(gate, case):
    case.old.write_bytes(b'bad installer')
    with pytest.raises(gate.GateError, match='size/SHA-256'):
        gate.execute_gate(case.new, '2.4.0', case.work, case.old, case.report)
    assert not case.commands


def test_same_historical_installer_cannot_stand_in_for_new_build(gate, case):
    with pytest.raises(gate.GateError, match='same-installer upgrade'):
        gate.execute_gate(case.old, '2.4.0', case.work, case.old, case.report)
    assert not case.commands


@pytest.mark.parametrize('version', ['2.3.1', '2.0.0', '2.4.0-rc1'])
def test_wrong_new_version_is_rejected_before_execution(gate, case, version):
    with pytest.raises(gate.GateError):
        gate.execute_gate(case.new, version, case.work, case.old, case.report)
    assert not case.commands


def test_download_checks_pinned_url_size_and_hash(gate, tmp_path, monkeypatch):
    data = b'old installer'
    monkeypatch.setattr(gate, 'BASELINE_SIZE', len(data))
    monkeypatch.setattr(gate, 'BASELINE_SHA256', hashlib.sha256(data).hexdigest())
    calls = []
    def opener(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(data)
    monkeypatch.setattr(gate.urllib.request, 'urlopen', opener)
    path = gate.baseline_installer(tmp_path, None)
    assert path.read_bytes() == data
    assert calls == [(gate.BASELINE_URL, 60)]


@pytest.mark.parametrize('body', [b'too short', b'oversized historical installer payload'])
def test_unpinned_download_is_rejected(gate, tmp_path, monkeypatch, body):
    monkeypatch.setattr(gate, 'BASELINE_SIZE', 13)
    monkeypatch.setattr(gate.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(body))
    with pytest.raises(gate.GateError):
        gate.baseline_installer(tmp_path, None)


def test_installer_waits_for_process_tree_and_preserves_quoted_arguments(gate, tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gate.subprocess, 'run', run)
    monkeypatch.setenv('PYTHONHOME', 'unwanted')
    gate.run_checked(["C:/setup's folder/old.exe", '/VERYSILENT', '/LOG=C:/log folder/old.log'], 'fixture', tmp_path, installer=True)
    argv, kwargs = calls[0]
    assert argv[:4] == ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command']
    assert '-Wait -PassThru' in argv[-1] and '-WindowStyle Hidden' in argv[-1]
    assert "setup''s folder" in argv[-1] and '"/LOG=C:/log folder/old.log"' in argv[-1]
    assert 'ExecutionPolicy' not in argv[-1]
    assert 'PYTHONHOME' not in kwargs['env'] and not kwargs.get('shell')


def test_main_writes_exact_blocker_and_nonzero_status(gate, tmp_path, monkeypatch):
    def blocked():
        raise gate.GateError('Exact fixture blocker: administrator token unavailable')
    monkeypatch.setattr(gate, 'require_windows_admin', blocked)
    work = tmp_path / 'report'
    rc = gate.main(['--installer', 'new.exe', '--expected-version', '2.4.0', '--work-dir', str(work), '--confirm-clean-machine'])
    report = json.loads((work / 'result.json').read_text())
    assert rc == 1 and report['status'] == 'FAILED'
    assert report['error'] == 'GateError: Exact fixture blocker: administrator token unavailable'


def test_clean_machine_confirmation_is_required(gate, tmp_path):
    with pytest.raises(SystemExit) as error:
        gate.main(['--installer', 'new.exe', '--expected-version', '2.4.0', '--work-dir', str(tmp_path / 'unused')])
    assert error.value.code == 2 and not (tmp_path / 'unused').exists()


@pytest.mark.skipif(os.name != 'nt' or struct.calcsize('P') != 8, reason='64-bit Windows shell folders')
def test_default_location_resolves_the_native_64_bit_program_files_folder(gate):
    root, group, desktop = gate.default_paths()
    assert root.is_absolute() and root.name == 'WhisperTranscriberSuite'
    assert root.parent == gate.shell_folder(0x26)
    assert group.parent == gate.shell_folder(0x17) and desktop == gate.shell_folder(0x19)


def test_native_timeout_is_an_explicit_discard_machine_failure(gate, tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise gate.subprocess.TimeoutExpired(args[0], 600)
    monkeypatch.setattr(gate.subprocess, 'run', timeout)
    with pytest.raises(gate.GateTimeout, match='Abort and discard this VM'):
        gate.run_checked(['owned-fixture.exe'], 'timeout', tmp_path, installer=True)


def test_timeout_report_cannot_allow_a_following_installer_step(gate, tmp_path, monkeypatch):
    def blocked(*args):
        raise gate.GateTimeout('owned fixture timed out; discard VM')
    monkeypatch.setattr(gate, 'execute_gate', blocked)
    work = tmp_path / 'timeout-report'
    rc = gate.main(['--installer', 'fixture.exe', '--expected-version', '2.4.0', '--work-dir', str(work), '--confirm-clean-machine'])
    report = json.loads((work / 'result.json').read_text())
    assert rc == 1 and report['status'] == 'FAILED' and report['discard_machine_required'] is True


def test_existing_registration_without_display_version_is_not_ignored(gate, monkeypatch):
    class Key:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    def open_key(hive, key, reserved, access):
        if hive == 1 and access == (4 | 16):
            return Key()
        raise FileNotFoundError('no registration in this view')
    def missing_value(handle, name):
        raise FileNotFoundError('registration exists but DisplayVersion is missing')
    winreg = SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
                             KEY_READ=4, KEY_WOW64_64KEY=16, KEY_WOW64_32KEY=32,
                             OpenKey=open_key, QueryValueEx=missing_value)
    monkeypatch.setitem(sys.modules, 'winreg', winreg)
    versions = gate.registered_versions()
    assert len(versions) == 1, 'An existing malformed registration must block clean-machine admission'
    assert versions[0] != gate.BASELINE_VERSION
