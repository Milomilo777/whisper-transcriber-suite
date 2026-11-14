"""Pure release-prerequisite checks; no compiler, registry or Setup execution."""
import ast
import importlib.util
from pathlib import Path
import pytest

HELPER = Path(__file__).parent / 'smoke/inno_prerequisites.py'
SPEC = importlib.util.spec_from_file_location('inno_prerequisites', HELPER)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

@pytest.mark.parametrize('function,name,basename', [
    (gate.require_inno_compiler, 'WHISPER_SMOKE_INNO_COMPILER', 'ISCC.exe'),
    (gate.require_historical_script, 'WHISPER_SMOKE_OLD_INSTALLER_SCRIPT', 'installer_embed.iss'),
])
@pytest.mark.parametrize('kind', ['unset', 'empty', 'missing', 'directory', 'wrong-name'])
def test_windows_missing_or_invalid_prerequisite_is_failure(tmp_path, function, name, basename, kind):
    path = tmp_path / basename
    env = {}
    if kind == 'empty': env[name] = ''
    if kind == 'missing': env[name] = str(path)
    if kind == 'directory': path.mkdir(); env[name] = str(path)
    if kind == 'wrong-name':
        path = tmp_path / 'wrong.txt'; path.write_text('fixture'); env[name] = str(path)
    with pytest.raises(RuntimeError, match=name): function('nt', env)

@pytest.mark.parametrize('function,name,basename', [
    (gate.require_inno_compiler, 'WHISPER_SMOKE_INNO_COMPILER', 'ISCC.exe'),
    (gate.require_historical_script, 'WHISPER_SMOKE_OLD_INSTALLER_SCRIPT', 'installer_embed.iss'),
])
def test_windows_accepts_existing_named_file_without_execution(tmp_path, function, name, basename):
    path = tmp_path / basename; path.write_bytes(b'not executed')
    assert function('nt', {name: str(path)}) == path.resolve()

@pytest.mark.parametrize('function', [gate.require_inno_compiler, gate.require_historical_script])
def test_nonwindows_prerequisites_are_optional(function):
    assert function('posix', {}) is None

@pytest.mark.parametrize('filename', ['test_inno_compile.py', 'test_inno_data_preservation.py', 'test_inno_shortcut_upgrade.py'])
def test_every_windows_smoke_requires_compiler_fixture_and_only_platform_skip(filename):
    tree = ast.parse((HELPER.parent / filename).read_text(encoding='utf-8'))
    tests = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    assert tests and all('inno_compiler' in [arg.arg for arg in node.args.args] for node in tests)
    marks = [node.value for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'pytestmark' for target in node.targets)]
    assert len(marks) == 1
    assert ast.dump(marks[0].args[0]) == ast.dump(ast.parse("os.name != 'nt'", mode='eval').body)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == 'skip' for node in ast.walk(tree))

def test_first_upgrade_requires_historical_file_before_read_or_install():
    tree = ast.parse((HELPER.parent / 'test_inno_data_preservation.py').read_text(encoding='utf-8'))
    test = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == 'test_first_upgrade_and_later_uninstall_preserve_old_user_additions')
    first = test.body[0]
    assert isinstance(first, ast.Assign) and isinstance(first.value, ast.Call)
    assert first.value.func.id == 'require_historical_script'
