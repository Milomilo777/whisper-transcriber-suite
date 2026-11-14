"""Exercise the displayed update command and selector with network-free runtimes."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import venv
import zipfile

import pytest

from core.updates import update_command

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows updater entry points')
NAMES = ['Amp&ersand', 'Space Path', 'bang!folder', 'paren (1)', '100%done',
         "single'quote", 'dollar$folder', 'caret^folder']


def _fake_py(path, interpreter):
    # Uses distlib's Windows entry-point stub, installed with the test runner's
    # pip, only for a temporary fixture; no executable is shipped by this repo.
    # https://distlib.readthedocs.io/en/latest/overview.html#wrappers
    import pip._vendor.distlib
    stub = Path(pip._vendor.distlib.__file__).with_name('t64.exe' if struct.calcsize('P') == 8 else 't32.exe')
    code = '''import json,os,subprocess,sys
from pathlib import Path
args=sys.argv[1:]
with Path(os.environ['WTS_FAKE_PY_LOG']).open('a') as f:f.write(json.dumps(args)+'\\n')
if not args or args[0]!='-3':sys.exit(79)
if args[1:3]==['-m','pip'] and not Path('pip.py').read_text().startswith('# network-free updater fixture'):
    sys.exit(78)
result=subprocess.run([sys.executable,*args[1:]],capture_output=True,creationflags=0x08000000)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('__main__.py', code)
    shebang = f'#!"{interpreter}"\n'.encode('utf-8')
    path.write_bytes(stub.read_bytes() + shebang + buffer.getvalue())


def _layout(tmp_path, name, *, project=True, mutation=None):
    source = tmp_path / name
    script = source / 'platform/windows/update.bat'
    script.parent.mkdir(parents=True)
    text = (ROOT / 'platform/windows/update.bat').read_text()
    if mutation == 'priority':
        old = 'if exist "%REPO_ROOT%\\.venv\\Scripts\\python.exe" ('
        assert old in text
        text = text.replace(old, 'if 1==0 (', 1)
    elif mutation in ('bootstrap', 'requirements', 'sanity'):
        suffix = {'bootstrap': '-m pip install --upgrade pip wheel',
                  'requirements': '-m pip install --upgrade -r',
                  'sanity': '-c "import core, sys;'}[mutation]
        old = '"%PY%" %PY_ARGS% ' + suffix
        assert old in text
        text = text.replace(old, '"%PY%" ' + suffix, 1)
    script.write_text(text)
    (source / 'gui.py').write_text('')
    (source / 'requirements.txt').write_text('')
    (source / 'core').mkdir()
    (source / 'core/__init__.py').write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "Path('sanity-call.json').write_text(json.dumps({'prefix':sys.prefix,'executable':sys.executable}))\n"
        "__version__='fixture'\n")
    (source / 'pip.py').write_text(
        '# network-free updater fixture\nfrom pathlib import Path\nimport json,sys\n'
        "with Path('pip-calls.jsonl').open('a') as f:f.write(json.dumps("
        "{'argv':sys.argv[1:],'prefix':sys.prefix,'executable':sys.executable})+'\\n')\n")
    system = tmp_path / '_system-python'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(system)
    if project:
        venv.EnvBuilder(with_pip=False, symlinks=False).create(source / '.venv')
    binary = tmp_path / '_launcher'
    binary.mkdir()
    _fake_py(binary / 'py.exe', system / 'Scripts/python.exe')
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONSAFEPATH'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1',
               PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_CONFIG_FILE=os.devnull,
               WTS_FAKE_PY_LOG=str(tmp_path / 'launcher.jsonl'))
    # Only the synthetic native launcher and Windows commands are discoverable.
    env['PATH'] = str(binary) + os.pathsep + str(Path(env.get('COMSPEC', 'C:/Windows/System32/cmd.exe')).parent)
    return source, script, system, env


def _run(source, command, env, shell='cmd'):
    if shell == 'powershell':
        powershell = Path(env.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        args = [str(powershell), '-NoProfile', '-NonInteractive', '-Command', command]
    else:
        args = subprocess.list2cmdline([env.get('COMSPEC', 'cmd.exe')]) + ' /d /s /c ' + command
    return subprocess.run(args, cwd=source, env=env, capture_output=True,
                          timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)


def _assert_calls(result, source, prefix):
    assert result.returncode == 0, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace')
    calls = [json.loads(line) for line in (source / 'pip-calls.jsonl').read_text().splitlines()]
    assert [call['argv'] for call in calls] == [
        ['install', '--upgrade', 'pip', 'wheel'],
        ['install', '--upgrade', '-r', str(source / 'requirements.txt')]]
    assert all(Path(call['prefix']).resolve() == prefix.resolve() for call in calls), 'Wrong interpreter prefix'
    sanity = json.loads((source / 'sanity-call.json').read_text())
    assert Path(sanity['prefix']).resolve() == prefix.resolve(), 'Sanity check used the wrong interpreter'
    assert b'core version fixture' in result.stdout
    return calls


@pytest.mark.parametrize(('name', 'shell'), [(name, shell) for name in NAMES for shell in ('cmd', 'powershell')],
                         ids=[f'{shell}-{name}' for name in NAMES for shell in ('cmd', 'powershell')])
def test_advertised_command_runs_the_real_updater(tmp_path, name, shell):
    source, script, system, env = _layout(tmp_path, name)
    result = _run(source, update_command(source, sys_platform='win32'), env, shell)
    _assert_calls(result, source, source / '.venv')
    assert not Path(env['WTS_FAKE_PY_LOG']).exists(), 'Project venv must win over launcher fallback'


def test_no_venv_uses_selector_on_both_pip_calls_and_sanity(tmp_path):
    source, script, system, env = _layout(tmp_path, 'fallback', project=False)
    result = _run(source, update_command(source, sys_platform='win32'), env)
    _assert_calls(result, source, system)
    argv = [json.loads(line) for line in Path(env['WTS_FAKE_PY_LOG']).read_text().splitlines()]
    assert len(argv) == 3 and all(args[0] == '-3' for args in argv)
    assert argv[0][1:3] == argv[1][1:3] == ['-m', 'pip'] and argv[2][1] == '-c'


@pytest.mark.parametrize('mutation', ['bootstrap', 'requirements', 'sanity'])
def test_missing_selector_mutations_are_detected(tmp_path, mutation):
    source, script, system, env = _layout(tmp_path, 'fallback', project=False, mutation=mutation)
    result = _run(source, update_command(source, sys_platform='win32'), env)
    argv = [json.loads(line) for line in Path(env['WTS_FAKE_PY_LOG']).read_text().splitlines()]
    assert any(args[0] != '-3' for args in argv)
    with pytest.raises((AssertionError, FileNotFoundError)):
        _assert_calls(result, source, system)


def test_priority_mutation_passes_legacy_argv_checks_but_fails_identity(tmp_path):
    source, script, system, env = _layout(tmp_path, 'priority', mutation='priority')
    result = _run(source, update_command(source, sys_platform='win32'), env)
    assert result.returncode == 0
    calls = [json.loads(line) for line in (source / 'pip-calls.jsonl').read_text().splitlines()]
    assert [call['argv'] for call in calls] == [
        ['install', '--upgrade', 'pip', 'wheel'],
        ['install', '--upgrade', '-r', str(source / 'requirements.txt')]]
    assert all(Path(call['prefix']).resolve() == system.resolve() for call in calls)
    with pytest.raises(AssertionError, match='Wrong interpreter prefix'):
        _assert_calls(result, source, source / '.venv')


@pytest.mark.parametrize('shell', ['cmd', 'powershell'])
def test_paired_percent_path_fails_closed_before_environment_substitution(tmp_path, shell):
    source, script, system, env = _layout(tmp_path, 'literal%WTS_UPDATER_PATH_TOKEN%')
    env['WTS_UPDATER_PATH_TOKEN'] = 'replacement'
    decoy = source.parent / 'literalreplacement/platform/windows/update.bat'
    decoy.parent.mkdir(parents=True)
    decoy.write_text('@echo off\necho wrong checkout>"%~dp0decoy-ran.txt"\nexit /b 0\n')
    result = _run(source, update_command(source, sys_platform='win32'), env, shell)
    assert result.returncode == 1
    assert b'paired percent markers' in result.stdout
    assert not decoy.with_name('decoy-ran.txt').exists()
    assert not (source / 'pip-calls.jsonl').exists()
    assert not Path(env['WTS_FAKE_PY_LOG']).exists()
