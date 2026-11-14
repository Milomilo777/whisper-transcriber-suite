"""Compile both production installers and prove predecessor admission on hosted Windows.

Requires genuine embed_build and PyInstaller dist_onedir payloads, an elevated
disposable GitHub-hosted Windows VM and two explicit confirmation flags. Never
run on a developer host. No Pascal extraction or substitute payload is used.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import uuid

OLD_ID = '{734B46B9-5E70-4C4E-8833-0A7506A64376}_is1'
NEW_ID = '{BD640ACA-1EDB-4F9F-890E-C2DC04221871}_is1'
UNINSTALL = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
OWNER_VALUE = 'WTS disposable predecessor proof owner'
ALLOW_MARKER = 'Previous product retained; profile migration runs on first launch.'
REFUSE_MARKER = 'Choose a different folder from the earlier Whisper Project installation.'
PIPELINES = {'embed': 'installer_embed.iss', 'compact': 'installer.iss'}
SCENARIOS = ('different', 'same-case', 'parent', 'child', 'junction')


class GateError(RuntimeError):
    pass


class UnsafeTimeout(GateError):
    """The disposable VM must be discarded; do not run cleanup installers."""


def validate_context(context: dict, expected_head: str) -> None:
    if re.fullmatch('[0-9a-f]{40}', expected_head) is None:
        raise GateError('Require an exact full committed source hash')
    required = {'platform': 'nt', 'bits': 64, 'admin': True, 'GITHUB_ACTIONS': 'true',
                'RUNNER_OS': 'Windows', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'GITHUB_REPOSITORY': 'Milomilo777/whisper-transcriber-suite', 'GITHUB_SHA': expected_head}
    if any(context.get(k) != v for k, v in required.items()):
        raise GateError('Only elevated 64-bit disposable GitHub-hosted Windows is admitted; never developer hosts')
    if context.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch') or not str(context.get('GITHUB_RUN_ID', '')).isdigit():
        raise GateError('Require the explicit trusted push/manual CI job context')


def compile_command(iscc: Path, source: Path, tag: str, output: Path) -> list[str]:
    if tag not in PIPELINES:
        raise GateError('Unknown production installer pipeline')
    return [str(iscc), '/Qp', '/O' + str(output), '/Fp18-' + tag, str(source / PIPELINES[tag])]


def setup_command(installer: Path, target: Path, log: Path) -> list[str]:
    return [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
            '/ALLUSERS', '/TASKS=', '/DIR=' + str(target), '/LOG=' + str(log)]


def validate_setup_outcome(allow: bool, returncode: int, text: str) -> None:
    # Exit7 identifies Preparing to Install refusal; require the actual guard
    # message as well: https://jrsoftware.org/ishelp/topic_setupexitcodes.htm
    if allow:
        if returncode != 0 or ALLOW_MARKER not in text or REFUSE_MARKER in text:
            raise GateError('Compiled Setup did not prove the separate-folder allow path')
    elif returncode != 7 or REFUSE_MARKER not in text or ALLOW_MARKER in text:
        raise GateError('Require actual PrepareToInstall exit7 plus the production predecessor refusal message')


def validate_work_root(work, temporary):
    work, temporary = work.resolve(), temporary.resolve()
    if work == temporary or not work.is_relative_to(temporary) or work.exists():
        raise GateError('Require a fresh owned subdirectory of RUNNER_TEMP; never overwrite prior proof')
    return work


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_log(path: Path) -> str:
    data = path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')


def run_process(argv: list[str], cwd: Path, output: Path, *, setup=False, timeout=600) -> int:
    if setup:
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        code = ("$ErrorActionPreference='Stop';$p=Start-Process -WindowStyle Hidden -FilePath "
                + quote(argv[0]) + ' -ArgumentList ' + quote(subprocess.list2cmdline(argv[1:]))
                + ' -Wait -PassThru;exit $p.ExitCode')
        argv = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code]
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP'):
        env.pop(key, None)
    env.update(WTS_PROFILE_DIR=str(cwd / 'private-profile'), PYTHONDONTWRITEBYTECODE='1')
    with output.open('xb') as stream:
        try:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            raise UnsafeTimeout('Owned compiler/Setup wait timed out; discard this VM, no further Setup or cleanup uninstall') from error
    return result.returncode


class NativeRegistry:
    """Only marker-owned synthetic predecessor keys on an already admitted VM."""
    def __init__(self):
        import winreg
        self.wr = winreg
        self.views = {'64': winreg.KEY_WOW64_64KEY, '32': winreg.KEY_WOW64_32KEY}

    def exists(self, product, view, hive=None):
        wr = self.wr
        try:
            with wr.OpenKey(wr.HKEY_LOCAL_MACHINE if hive is None else hive,
                            UNINSTALL + '\\' + product, 0, wr.KEY_READ | self.views[view]):
                return True
        except FileNotFoundError:
            return False

    def require_clean(self):
        for view in self.views:
            for hive in (self.wr.HKEY_LOCAL_MACHINE, self.wr.HKEY_CURRENT_USER):
                for product in (OLD_ID, NEW_ID):
                    if self.exists(product, view, hive):
                        raise GateError('Clean VM required: product registration already exists; never overwrite it')

    def create_old(self, view, path, owner):
        wr = self.wr
        # RegCreateKeyEx disposition closes the absent-check/create race: an
        # existing key, including an empty one, is never claimed or modified.
        api = ctypes.windll.advapi32.RegCreateKeyExW
        api.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR,
                        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.DWORD)]
        api.restype = wintypes.LONG
        handle = wintypes.HANDLE()
        disposition = wintypes.DWORD()
        with wr.OpenKey(wr.HKEY_LOCAL_MACHINE, UNINSTALL, 0, wr.KEY_CREATE_SUB_KEY | self.views[view]) as parent:
            error = api(int(parent), OLD_ID, 0, None, 0, wr.KEY_READ | wr.KEY_WRITE | self.views[view],
                        None, ctypes.byref(handle), ctypes.byref(disposition))
        if error:
            raise OSError(error, 'Cannot create the owned predecessor registration')
        if handle.value is None or handle.value == 0:
            raise GateError('Registry creation returned no valid native handle; retain state for VM discard')
        wr.CloseKey(handle.value)
        if disposition.value != 1:
            raise GateError('Predecessor key already exists; no value was written')
        with wr.OpenKey(wr.HKEY_LOCAL_MACHINE, UNINSTALL + '\\' + OLD_ID, 0,
                        wr.KEY_SET_VALUE | self.views[view]) as key:
            for name, value in {OWNER_VALUE: owner, 'Inno Setup: App Path': str(path),
                                'DisplayName': 'Whisper Project (disposable P18 fixture)',
                                'UninstallString': '"' + str(path / 'never-run-predecessor-uninstaller.exe') + '"'}.items():
                wr.SetValueEx(key, name, 0, wr.REG_SZ, value)

    def remove_old(self, view, path, owner):
        wr = self.wr
        with wr.OpenKey(wr.HKEY_LOCAL_MACHINE, UNINSTALL + '\\' + OLD_ID, 0,
                        wr.KEY_READ | self.views[view]) as key:
            if wr.QueryValueEx(key, OWNER_VALUE)[0] != owner or wr.QueryValueEx(key, 'Inno Setup: App Path')[0] != str(path):
                raise GateError('Synthetic registration ownership changed; retain it for VM discard')
            if wr.QueryInfoKey(key)[0] != 0:
                raise GateError('Unexpected predecessor subkeys; do not delete them')
            names = {wr.EnumValue(key, index)[0] for index in range(wr.QueryInfoKey(key)[1])}
            if names != {OWNER_VALUE, 'Inno Setup: App Path', 'DisplayName', 'UninstallString'}:
                raise GateError('Unexpected predecessor values; retain the changed registration')
        wr.DeleteKeyEx(wr.HKEY_LOCAL_MACHINE, UNINSTALL + '\\' + OLD_ID, self.views[view], 0)

    def current_owned_at(self, target):
        found = False
        wr = self.wr
        for view in self.views:
            if not self.exists(NEW_ID, view):
                continue
            found = True
            with wr.OpenKey(wr.HKEY_LOCAL_MACHINE, UNINSTALL + '\\' + NEW_ID, 0,
                            wr.KEY_READ | self.views[view]) as key:
                if Path(wr.QueryValueEx(key, 'Inno Setup: App Path')[0]).resolve() != target.resolve():
                    raise GateError('Unexpected current-product location; never invoke an unrelated uninstaller')
        return found


def scenario_paths(root, scenario):
    old = root / 'WhisperProject'
    if scenario == 'different':
        return old, root / 'NewProduct', None
    if scenario == 'same-case':
        return old, Path(str(old).swapcase()), None
    if scenario == 'parent':
        target = root / 'NewParent'
        return target / 'WhisperProject', target, None
    if scenario == 'child':
        return old, old / 'NewChild', None
    if scenario == 'junction':
        return old, root / 'OwnedAlias/NewChild', root / 'OwnedAlias'
    raise GateError('Unknown native scenario')


def make_junction(alias, target, work, log):
    env = dict(os.environ, WTS_P18_ALIAS=str(alias), WTS_P18_TARGET=str(target))
    code = "$ErrorActionPreference='Stop';New-Item -ItemType Junction -Path $env:WTS_P18_ALIAS -Value $env:WTS_P18_TARGET | Out-Null"
    with log.open('xb') as stream:
        process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
            cwd=work, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode != 0 or alias.resolve() != target.resolve():
        raise GateError('Owned junction creation/identity failed')


def execute_case(tag, view, scenario, installer, payload, work, registry):
    identity = tag + '-' + view + '-' + scenario
    record_dir = work / 'cases' / identity
    record_dir.mkdir(parents=True)
    data = work / 'data' / identity
    data.mkdir(parents=True)
    old, target, alias = scenario_paths(data, 'same-case' if scenario == 'cross-view-mask' else scenario)
    for path in (old, target):
        if not path.resolve().is_relative_to(work.resolve()):
            raise GateError('Native target escaped fresh owned work root')
    old.mkdir(parents=True)
    sentinel = old / 'synthetic-retained-user-file.bin'
    sentinel.write_bytes(b'Owned P18 sentinel\x00' + os.urandom(32))
    sentinel_sha = digest(sentinel)
    owner = uuid.uuid4().hex
    owned = []
    row = {'pipeline': tag, 'view': view, 'scenario': scenario, 'status': 'FAILED',
           'predecessor': str(old), 'target': str(target), 'expected': 'ALLOW' if scenario == 'different' else 'REFUSE',
           'synthetic_registration_only': True, 'sentinel_sha256': sentinel_sha, 'cleanup_errors': []}
    unsafe = False
    try:
        if alias is not None:
            make_junction(alias, old, work, work / 'logs' / (identity + '-junction.log'))
        bindings = [('64', data / 'Separate64Product'), ('32', old)] if scenario == 'cross-view-mask' else [(view, old)]
        for selected_view, folder in bindings:
            folder.mkdir(parents=True, exist_ok=True)
            registry.create_old(selected_view, folder, owner)
            owned.append((selected_view, folder))
        row['registered_views'] = [{'view': v, 'path': str(p)} for v, p in owned]
        log = work / 'logs' / (identity + '-setup.log')
        args = setup_command(installer, target, log)
        row['setup_arguments'] = args
        code = run_process(args, work, work / 'logs' / (identity + '-setup-process.log'), setup=True)
        row['setup_exit'] = code
        text = read_log(log)
        row['setup_log'] = str(log)
        row['guard_log_lines'] = [line for line in text.splitlines() if ALLOW_MARKER in line or REFUSE_MARKER in line]
        validate_setup_outcome(scenario == 'different', code, text)
        if digest(sentinel) != sentinel_sha:
            raise GateError('Compiled Setup altered the retained predecessor sentinel')
        if scenario == 'different':
            if not registry.current_owned_at(target):
                raise GateError('Allowed Setup did not register the actual installed product')
            for relative, pin in payload.items():
                if not (target / relative).is_file() or digest(target / relative) != pin:
                    raise GateError('Allowed Setup did not install the genuine production payload: ' + relative)
        elif registry.current_owned_at(target) or any((target / relative).exists() for relative in payload):
            raise GateError('Refused Setup left a shipped app file or product registration')
        row['status'] = 'PASS'
    except UnsafeTimeout as error:
        unsafe = True
        row.update(error=str(error), discard_vm_required=True)
    except Exception as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        if not unsafe:
            try:
                if registry.current_owned_at(target):
                    uninstaller = target / 'unins000.exe'
                    if not uninstaller.is_file():
                        raise GateError('Owned installed product lacks its uninstaller')
                    row['uninstall_sha256'] = digest(uninstaller)
                    args = [str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                            '/LOG=' + str(work / 'logs' / (identity + '-uninstall.log'))]
                    code = run_process(args, work, work / 'logs' / (identity + '-uninstall-process.log'), setup=True)
                    row['uninstall_exit'] = code
                    if code or registry.current_owned_at(target) or any((target / name).exists() for name in payload):
                        raise GateError('Native uninstall did not remove the owned tracked app/registration')
            except UnsafeTimeout as error:
                unsafe = True
                row.update(discard_vm_required=True)
                row['cleanup_errors'].append(str(error))
            except Exception as error:
                row['cleanup_errors'].append(str(error))
            if not unsafe:
                for selected_view, folder in reversed(owned):
                    try:
                        registry.remove_old(selected_view, folder, owner)
                    except Exception as error:
                        row['cleanup_errors'].append(str(error))
                if alias is not None:
                    try:
                        attributes = alias.lstat().st_file_attributes
                        if alias.parent.resolve() != data.resolve() or not attributes & 0x400 or alias.resolve() != old.resolve():
                            raise GateError('Owned junction identity changed; retain it')
                        os.rmdir(alias)  # Remove this link only, never recurse into its target.
                    except Exception as error:
                        row['cleanup_errors'].append(str(error))
                try:
                    if digest(sentinel) != sentinel_sha:
                        raise GateError('Cleanup altered the synthetic retained original')
                    registry.require_clean()
                except Exception as error:
                    row['cleanup_errors'].append(str(error))
        row['cleanup_verified'] = not unsafe and not row['cleanup_errors']
        if not row['cleanup_verified']:
            row['status'] = 'FAILED'
            row['discard_vm_required'] = True
        with (record_dir / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(row, stream, indent=2)
    return row


def verify_source(source, expected_head):
    flags = subprocess.CREATE_NO_WINDOW
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], creationflags=flags).decode().strip()
    if actual != expected_head or source.resolve() != Path(os.environ['GITHUB_WORKSPACE']).resolve():
        raise GateError('Source checkout identity differs from the exact CI commit/workspace')
    subprocess.run(['git', '-C', str(source), 'diff', '--exit-code', 'HEAD', '--', *PIPELINES.values()],
                   check=True, creationflags=flags)


def payload_pins(source, tag):
    root = source / ('embed_build' if tag == 'embed' else 'dist_onedir/WhisperTranscriberSuite')
    names = ('python/python.exe', 'gui.py', 'core/__init__.py') if tag == 'embed' else ('WhisperTranscriberSuite.exe',)
    for name in names:
        path = root / name
        if not path.is_file() or not path.stat().st_size:
            raise GateError('Require the full genuine production build payload, no substitute: ' + str(path))
    return {name: digest(root / name) for name in names}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--confirm-disposable-vm', action='store_true', required=True)
    parser.add_argument('--confirm-clean-machine', action='store_true', required=True)
    args = parser.parse_args(argv)
    context: dict[str, object] = {k: os.environ.get(k) for k in ('GITHUB_ACTIONS', 'RUNNER_OS', 'RUNNER_ENVIRONMENT',
        'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_EVENT_NAME', 'GITHUB_RUN_ID')}
    context.update(platform=os.name, bits=struct.calcsize('P') * 8,
                   admin=bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == 'nt' else False)
    validate_context(context, args.expected_head)
    source = args.source.resolve()
    verify_source(source, args.expected_head)
    temporary = Path(os.environ['RUNNER_TEMP']).resolve()
    work = validate_work_root(args.work_dir, temporary)
    registry = NativeRegistry()
    registry.require_clean()
    default = Path(os.environ['ProgramFiles']) / 'WhisperTranscriberSuite'
    if default.exists():
        raise GateError('Default app folder already exists; run before other native gates, never remove their evidence')
    work.mkdir()
    (work / 'logs').mkdir()
    report = {'status': 'FAILED', 'expected_head': args.expected_head, 'context': context,
              'compiler': {'path': str(args.iscc.resolve()), 'sha256': digest(args.iscc.resolve())},
              'compiled': {}, 'cases': [], 'payload_mode': 'Unmodified full production ISS with real embed/onedir payloads; no substitution'}
    try:
        for tag, script in PIPELINES.items():
            payload = payload_pins(source, tag)
            output = work / 'compiled' / tag
            output.mkdir(parents=True)
            command = compile_command(args.iscc.resolve(), source, tag, output)
            code = run_process(command, source, work / 'logs' / ('compile-' + tag + '.log'))
            if code:
                raise GateError('Full production ISCC compile failed: ' + script)
            installer = output / ('p18-' + tag + '.exe')
            if not installer.is_file():
                raise GateError('Compiler did not produce its selected full Setup')
            report['compiled'][tag] = {'path': str(installer), 'sha256': digest(installer),
                'size': installer.stat().st_size, 'script': script, 'script_sha256': digest(source / script),
                'command': command, 'payload_pins': payload}
            for view, scenario in [(v, s) for v in ('64', '32') for s in SCENARIOS] + [('mixed32', 'cross-view-mask')]:
                registry.require_clean()
                row = execute_case(tag, view, scenario, installer, payload, work, registry)
                report['cases'].append(row)
                if row['status'] != 'PASS' or row['cleanup_verified'] is not True:
                    raise GateError('Compiled predecessor case failed: ' + tag + '/' + view + '/' + scenario)
        verify_source(source, args.expected_head)
        registry.require_clean()
        report.update(status='PASS', completed_cases=len(report['cases']),
                      native_registry_cleanup_verified=True, all_setup_cases_cleanup_verified=True)
    except UnsafeTimeout as error:
        report.update(error=str(error), discard_vm_required=True)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        if any(r.get('discard_vm_required') for r in report['cases']):
            report['discard_vm_required'] = True
    finally:
        with (work / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
