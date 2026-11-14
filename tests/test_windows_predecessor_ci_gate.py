"""Workflow contracts and real PowerShell promotion checks; never run Setup."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/windows-installer.yml'


def workflow_steps():
    text = WORKFLOW.read_text(encoding='utf-8')
    matches = list(re.finditer(r'^      - name: (.+)$', text, re.MULTILINE))
    return {match[1]: text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
            for i, match in enumerate(matches)}


def step(name):
    steps = workflow_steps()
    assert name in steps, f'Required Windows build gate missing: {name}'
    return steps[name]


def test_workflow_builds_real_compact_payload_in_isolated_python_environment():
    body = step('Build the real Compact payload')
    assert 'python -m venv $venv' in body
    assert "Join-Path $env:RUNNER_TEMP 'wts-compact-venv'" in body
    assert "Join-Path $venv 'Scripts/python.exe'" in body
    assert '& $compactPython -m pip install -r requirements.txt pyinstaller' in body
    assert ('& $compactPython -m PyInstaller --noconfirm --clean --distpath dist_onedir' in body)
    assert '--workpath "$env:RUNNER_TEMP/wts-compact-pyinstaller" whisper_project_onedir.spec' in body
    assert "dist_onedir/WhisperTranscriberSuite/WhisperTranscriberSuite.exe" in body
    assert 'pip list --format freeze' in body
    assert 'compact-site-packages.txt' in body and 'compact-build.json' in body
    assert '-m PyInstaller --version' in body


def test_workflow_compiled_gate_requires_disposable_vm_and_exact_source():
    body = step('Compile both installers and verify predecessor isolation')
    assert 'python tools/smoke_windows_predecessor.py' in body
    for argument in ('--source "$env:GITHUB_WORKSPACE"', '--iscc "$env:ISCC"',
                     '--expected-head "${{ github.sha }}"',
                     '--work-dir "$env:RUNNER_TEMP/wts-predecessor-compiled"',
                     '--confirm-disposable-vm', '--confirm-clean-machine'):
        assert argument in body
    assert 'if ($LASTEXITCODE -ne 0)' in body
    assert '& $env:ISCC /Qp installer_embed.iss' not in WORKFLOW.read_text(encoding='utf-8')


def test_workflow_guarded_binary_precedes_manifest_and_all_smokes():
    names = list(workflow_steps())
    ordered = ['Build the real Compact payload',
               'Compile both installers and verify predecessor isolation',
               'Promote the guard-tested embed installer', 'Zip the Portable build',
               'Write the build manifest', 'Smoke test the Portable tree (embed_build)',
               'Real v2.3.1 upgrade and uninstall at default Program Files']
    assert [names.index(name) for name in ordered] == sorted(names.index(name) for name in ordered)
    promotion = step('Promote the guard-tested embed installer')
    assert '$result.compiled.embed.path' in promotion
    assert '$result.compiled.embed.sha256' in promotion
    assert 'WhisperTranscriberSuite-Installer-Windows-v$env:APP_VERSION.exe' in promotion
    publish = step('Upload the installer and the Portable ZIP')
    assert 'dist_installer/*.exe' in publish and 'dist_installer/*.zip' in publish
    assert 'dist_onedir' not in publish and 'compiled/compact' not in publish


def test_workflow_retains_failure_records_without_uploading_native_payloads():
    artifact = step('Upload the build manifest')
    assert 'if: always()' in artifact
    for pattern in ('${{ runner.temp }}/wts-predecessor-compiled/result.json',
                    '${{ runner.temp }}/wts-predecessor-compiled/**/*.json',
                    '${{ runner.temp }}/wts-predecessor-compiled/**/*.log',
                    '${{ runner.temp }}/wts-compact-build.log'):
        assert pattern in artifact
    for line in artifact.splitlines():
        if 'wts-predecessor-compiled/' in line:
            assert line.strip().endswith(('.json', '.log')), line
    assert 'compiled/**/*.exe' not in artifact and 'dist_onedir/' not in artifact


def test_workflow_rebuilds_when_either_installer_or_compact_recipe_changes():
    triggers = WORKFLOW.read_text(encoding='utf-8').split('\non:\n', 1)[1].split('\npermissions:', 1)[0]
    for path in ('installer.iss', 'whisper_project_onedir.spec', 'tools/smoke_windows_predecessor.py'):
        assert f'      - {path}\n' in triggers


@pytest.mark.parametrize('problem', ['none', 'source-hash', 'result-head', 'result-status', 'outside-work', 'copy-corruption'])
def test_workflow_promotion_executes_hash_bound_copy_and_refuses_invalid_proof(tmp_path, problem):
    """Execute only the workflow's copy/hash step against synthetic files."""
    shell = shutil.which('pwsh')
    if shell is None:
        pytest.skip('PowerShell is required to execute the Windows promotion step')
    body = step('Promote the guard-tested embed installer')
    script = textwrap.dedent(body.split('        run: |\n', 1)[1])
    work = tmp_path / 'runner' / 'wts-predecessor-compiled'
    binary = work / 'compiled' / 'embed' / 'p18-embed.exe'
    binary.parent.mkdir(parents=True)
    payload = b'synthetic unit-test installer bytes; never executed'
    binary.write_bytes(payload)
    if problem == 'outside-work':
        binary = tmp_path / 'foreign.exe'
        binary.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    head = 'a' * 40
    record = {'status': 'PASS', 'expected_head': head,
              'compiled': {'embed': {'path': str(binary), 'sha256': sha, 'size': len(payload)}}}
    if problem == 'source-hash':
        binary.write_bytes(b'changed after native acceptance')
    elif problem == 'result-head':
        record['expected_head'] = 'b' * 40
    elif problem == 'result-status':
        record['status'] = 'FAIL'
    (work / 'result.json').write_text(json.dumps(record), encoding='utf-8')
    probe = tmp_path / 'promote.ps1'
    prefix = "$ErrorActionPreference = 'Stop'\n"
    if problem == 'copy-corruption':
        prefix += ("function Copy-Item { param([string]$LiteralPath, [string]$Destination, [switch]$Force)\n"
                   "  [IO.File]::WriteAllBytes($Destination, [byte[]](1, 2, 3))\n}\n")
    probe.write_text(prefix + script, encoding='utf-8')
    environment = dict(os.environ, RUNNER_TEMP=str(tmp_path / 'runner'),
                       GITHUB_SHA=head, GITHUB_WORKSPACE=str(tmp_path), APP_VERSION='9.8.7')
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(probe)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    target = tmp_path / 'dist_installer' / 'WhisperTranscriberSuite-Installer-Windows-v9.8.7.exe'
    if problem == 'none':
        assert result.returncode == 0, result.stdout + result.stderr
        assert target.read_bytes() == payload
        assert hashlib.sha256(target.read_bytes()).hexdigest() == sha
    else:
        assert result.returncode != 0, 'Invalid native acceptance proof was promoted'
        if problem == 'copy-corruption':
            assert target.exists() and target.read_bytes() != payload
        else:
            assert not target.exists()


def test_workflow_compiler_environment_is_exported_before_native_smokes():
    sdk = step('Install the pinned Inno Setup')
    assert '"WHISPER_SMOKE_INNO_COMPILER=$iscc" >> $env:GITHUB_ENV' in sdk
    names = list(workflow_steps())
    assert names.index('Install the pinned Inno Setup') < names.index('Run compiled Windows smoke regressions')


def test_workflow_records_actual_compiler_engine_and_binary_identity():
    sdk = step('Install the pinned Inno Setup')
    for field in ('declared_package_version', 'declared_package_sha256', 'runtime_engine_version',
                  'compiler_file_version', 'compiler_product_version', 'iscc_sha256', 'iscmplr_sha256'):
        assert field in sdk
    assert "[str(iscc), '-']" in sdk and "input=b''" in sdk
    assert 'Compiler engine version:' in sdk and 'inno-compiler.json' in sdk
    assert 'inno-compiler-probe.stdout.log' in sdk and 'inno-compiler-probe.stderr.log' in sdk
    assert '6.7.3' not in sdk, 'Read the declared compiler version from the unchanged pin file'


def test_workflow_explicitly_runs_all_three_compiled_smoke_files():
    install = step('Install pytest for compiled Windows smoke checks')
    assert '& $smokePython -m pip install pytest pytest-timeout' in install
    body = step('Run compiled Windows smoke regressions')
    assert '& $smokePython -m pytest' in body
    for name in ('test_inno_compile.py', 'test_inno_data_preservation.py', 'test_inno_shortcut_upgrade.py'):
        assert 'tests/smoke/' + name in body
    assert '--junitxml=' in body and '--basetemp=' in body
    assert "findall('.//testcase')" in body
    assert 'Compiled smoke cases must execute and pass without skips' in body
    assert 'if ($LASTEXITCODE -ne 0)' in body


def test_workflow_native_smokes_follow_predecessor_clean_machine_checks():
    names = list(workflow_steps())
    assert (names.index('Compile both installers and verify predecessor isolation')
            < names.index('Promote the guard-tested embed installer')
            < names.index('Install pytest for compiled Windows smoke checks')
            < names.index('Run compiled Windows smoke regressions')
            < names.index('Real v2.3.1 upgrade and uninstall at default Program Files'))


def test_workflow_native_smoke_xml_and_logs_are_always_retained():
    artifact = step('Upload the build manifest')
    assert 'if: always()' in artifact
    for pattern in ('${{ runner.temp }}/wts-inno-smoke/*.xml',
                    '${{ runner.temp }}/wts-inno-smoke/**/*.log'):
        assert pattern in artifact
    assert 'build-manifest/' in artifact


def test_workflow_supplies_a_real_historical_script_before_native_smokes():
    install = step('Install pytest for compiled Windows smoke checks')
    assert 'v2.3.1:installer_embed.iss' in install
    assert 'write_bytes(subprocess.check_output' in install
    assert '"WHISPER_SMOKE_OLD_INSTALLER_SCRIPT=$oldScript" >> $env:GITHUB_ENV' in install


@pytest.mark.parametrize('compiler', ['', 'not-a-file'])
def test_workflow_native_smoke_preflight_fails_without_compiler(tmp_path, compiler):
    shell = shutil.which('pwsh')
    if shell is None:
        pytest.skip('PowerShell is required for the native smoke preflight')
    body = step('Run compiled Windows smoke regressions')
    script = textwrap.dedent(body.split('        run: |\n', 1)[1])
    probe = tmp_path / 'missing-compiler.ps1'
    probe.write_text("$ErrorActionPreference = 'Stop'\n" + script, encoding='utf-8')
    environment = dict(os.environ, WHISPER_SMOKE_INNO_COMPILER=compiler,
                       RUNNER_TEMP=str(tmp_path), GITHUB_WORKSPACE=str(tmp_path))
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(probe)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode != 0
    assert 'Pinned Inno compiler is required for Windows smoke checks' in result.stderr


@pytest.mark.parametrize('banner_version', ['6.7.3', '7.0.0', 'missing'])
def test_workflow_compiler_probe_uses_real_banner_not_zero_file_version(tmp_path, monkeypatch, banner_version):
    """Exercise metadata/probe logic with a fake subprocess, never a compiler."""
    body = step('Install the pinned Inno Setup')
    assert "$probe = @'\n" in body
    code = textwrap.dedent(body.split("$probe = @'\n", 1)[1].split("          '@", 1)[0])
    iscc = tmp_path / 'sdk' / 'ISCC.exe'
    iscc.parent.mkdir()
    iscc.write_bytes(b'synthetic compiler bytes; never executed')
    iscc.with_name('ISCmplr.dll').write_bytes(b'synthetic engine bytes')
    pin_file = tmp_path / 'platform/windows/build-deps.json'
    pin_file.parent.mkdir(parents=True)
    pin_file.write_text(json.dumps({'deps': [{'name': 'inno-setup', 'version': '6.7.3', 'sha256': 'f' * 64}]}))
    (tmp_path / 'build-manifest').mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setattr(sys, 'argv', ['-', str(iscc), '0.0.0.0', '0.0.0.0', '0.0.0.0', '0.0.0.0'])
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0, raising=False)

    def probe(command, **kwargs):
        assert command == [str(iscc), '-'] and kwargs['input'] == b''
        assert kwargs['capture_output'] and kwargs['timeout'] == 30
        banner = ('Compiler engine version: Inno Setup ' + banner_version + '\n').encode()
        return subprocess.CompletedProcess(command, 2, banner, b'Required [Setup] directive AppName not specified.')

    monkeypatch.setattr(subprocess, 'run', probe)
    if banner_version == '6.7.3':
        exec(compile(code, '<workflow SDK probe>', 'exec'), {})
    else:
        with pytest.raises(SystemExit, match='runtime engine identity probe failed'):
            exec(compile(code, '<workflow SDK probe>', 'exec'), {})
    record = json.loads((tmp_path / 'build-manifest/inno-compiler.json').read_text())
    assert record['compiler_file_version'] == '0.0.0.0'
    assert record['engine_file_version'] == '0.0.0.0'
    assert record['runtime_engine_version'] == (None if banner_version == 'missing' else banner_version)
    assert record['iscc_sha256'] == hashlib.sha256(iscc.read_bytes()).hexdigest()
    assert record['iscmplr_sha256'] == hashlib.sha256(iscc.with_name('ISCmplr.dll').read_bytes()).hexdigest()
