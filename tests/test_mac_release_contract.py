"""Causal, windowless controls for macOS release and replacement policy."""
import ast
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from core import updates
from tests.test_mac_bundle_audit import inspect_bundle
from tests.test_mac_build_pins import ROOT, SPEC, _find_bash


@pytest.mark.parametrize('claim,plist,accepted', [('10.15', '12.0', False),
    ('12.0', '12.0', True), ('14.0', '12.0', True), ('bad', '12.0', False)])
def test_published_minimum_limits_built_bundle(tmp_path, monkeypatch, claim, plist, accepted):
    monkeypatch.setenv('WTS_CLAIMED_MACOS_MIN', claim)
    result = inspect_bundle(tmp_path, minimum=plist, plist_min=plist)
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr


def test_target_slice_and_platform_control(monkeypatch):
    tree = ast.parse(SPEC.read_text(encoding='utf-8'))
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_macho_minos')
    def command(platform, minimum):
        return (SimpleNamespace(cmd=1), SimpleNamespace(platform=platform, minos=minimum), None)
    headers = [SimpleNamespace(header=SimpleNamespace(cputype=0x01000007),
                commands=[command(1, 0x000A0F00), command(6, 0x00100000)]),
               SimpleNamespace(header=SimpleNamespace(cputype=0x0100000C),
                commands=[command(1, 0x000B0000)])]
    macho = ModuleType('macholib.MachO')
    macho.MachO = lambda path: SimpleNamespace(headers=headers)
    package = ModuleType('macholib')
    package.mach_o = SimpleNamespace(LC_BUILD_VERSION=1, LC_VERSION_MIN_MACOSX=2)
    monkeypatch.setitem(sys.modules, 'macholib', package)
    monkeypatch.setitem(sys.modules, 'macholib.MachO', macho)
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SPEC), 'exec'), namespace)
    assert namespace['_macho_minos']('fixture', 'x86_64') == (10, 15, 0)
    assert namespace['_macho_minos']('fixture', 'universal2') == (11, 0, 0)


@pytest.mark.parametrize('version,expected', [('13.6.9', 'macos-x64.dmg'),
    ('14.0', 'macos-arm64.dmg'), ('', 'macos-x64.dmg'), ('10.16', 'macos-x64.dmg')])
def test_rosetta_respects_native_bundle_floor(monkeypatch, version, expected):
    monkeypatch.setattr(updates._platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(updates._platform, 'version', lambda: 'RELEASE_ARM64_T8103')
    monkeypatch.setattr(updates._platform, 'mac_ver', lambda: (version, '', ''))
    assert updates.pick_asset(updates.INSTALL_MACOS_APP,
        ('macos-arm64.dmg', 'macos-x64.dmg')) == expected


@pytest.mark.parametrize('mode', ['success', 'running', 'copy-failure'])
def test_terminal_update_replaces_instead_of_merging(tmp_path, mode):
    bash = _find_bash()
    assert bash, 'Bash required for the replacement control'
    notes = (ROOT / 'docs/releases/2.4.0.md').read_text(encoding='utf-8')
    command = re.search(r'```bash\n(.*?)\n```', notes, re.S).group(1)
    app = 'Whisper Transcriber Suite.app'
    destination = tmp_path / 'Applications' / app
    destination.mkdir(parents=True)
    (destination / 'old-only').write_text('old')
    (destination / 'executable').write_text('old executable')
    old_inode = (destination / 'executable').stat().st_ino
    mounted = tmp_path / 'wts-dmg' / app
    mounted.mkdir(parents=True)
    (mounted / 'executable').write_text('new executable')
    (tmp_path / 'wts.dmg').write_text('fixture')
    home = tmp_path / 'home'
    (home / '.Trash').mkdir(parents=True)
    command = command.replace('/Applications', (tmp_path / 'Applications').as_posix())
    command = command.replace('/tmp/wts-dmg', (tmp_path / 'wts-dmg').as_posix())
    command = command.replace('/tmp/wts.dmg', (tmp_path / 'wts.dmg').as_posix())
    script = tmp_path / 'replace.sh'
    script.write_text('HOME="' + home.as_posix() + '"\n'
        'uname(){ echo x86_64; }; sw_vers(){ echo 13.6; }; curl(){ echo called >"$HOME/network-called"; }; '
        'hdiutil(){ :; }; open(){ :; }; pgrep(){ return ' + ('0' if mode == 'running' else '1') + '; };\n'
        + ('cp(){ return 7; };\n' if mode == 'copy-failure' else '') + command + '\n',
        encoding='utf-8', newline='\n')
    result = subprocess.run([bash, str(script)], capture_output=True, text=True, timeout=30)
    if mode != 'success':
        assert (destination / 'old-only').read_text() == 'old'
        assert (destination / 'executable').read_text() == 'old executable'
        assert (destination / 'executable').stat().st_ino == old_inode
        if mode == 'running':
            assert not (home / 'network-called').exists()
            assert 'Quit' in result.stdout
        else:
            assert result.returncode != 0
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (destination / 'old-only').exists(), 'old bundle contents survived replacement'
    assert (destination / 'executable').stat().st_ino != old_inode
    assert list((home / '.Trash').rglob('old-only')), 'old bundle is not recoverable'
    assert 'Quit' in notes


@pytest.mark.parametrize('rpath,accepted', [('/opt/homebrew/lib', False),
    ('@loader_path', True), ('@loader_path/../../../../outside', False)])
def test_rpath_cannot_escape_bundle(tmp_path, rpath, accepted):
    loads = f'Load command 1\n cmd LC_RPATH\n cmdsize 48\n path {rpath} (offset 12)\n'
    result = inspect_bundle(tmp_path, extra_loads=loads)
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr


@pytest.mark.parametrize('dependency,accepted', [('@rpath/missing.dylib', False),
    ('@rpath/Library ü.dylib', True), ('@loader_path/Library ü.dylib', True),
    ('@loader_path/../../../../outside.dylib', False)])
def test_rpath_dependency_must_resolve_inside_bundle(tmp_path, dependency, accepted):
    result = inspect_bundle(tmp_path, dependency_override=dependency,
        extra_loads='Load command 1\n cmd LC_RPATH\n cmdsize 48\n path @loader_path (offset 12)\n')
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr


def test_release_minimums_match_verifier_and_rosetta_policy():
    notes = (ROOT / 'docs/releases/2.4.0.md').read_text(encoding='utf-8')
    workflow = (ROOT / '.github/workflows/macos-app.yml').read_text(encoding='utf-8')
    claims = re.findall(r'suffix: (arm64|x64)\s+claimed_min: "(\d+)\.0"', workflow)
    assert dict(claims) == {'arm64': str(updates.MACOS_ARM64_MIN_MAJOR), 'x64': '12'}
    assert 'WTS_CLAIMED_MACOS_MIN: ${{ matrix.claimed_min }}' in workflow
    assert f'Apple-silicon Mac, macOS {updates.MACOS_ARM64_MIN_MAJOR}+' in notes
    assert 'Intel Mac, macOS 12+' in notes
    assert f'-ge {updates.MACOS_ARM64_MIN_MAJOR}' in notes


@pytest.fixture
def dyld_paths():
    path = ROOT / 'platform/macos/pyinstaller/check_bundle_paths.py'
    spec = importlib.util.spec_from_file_location('bundle_paths_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dylib_install_name_is_not_an_unresolved_dependency(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    binary = bundle / 'Contents/Frameworks/libx.dylib'
    loads = 'Load command 0\n cmd LC_ID_DYLIB\n cmdsize 48\n name @rpath/libx.dylib (offset 24)\n'
    links = 'fixture:\n\t@rpath/libx.dylib (compatibility version 1.0.0)\n'
    assert not dyld_paths.inspect_paths(bundle, binary, links, loads)


def test_executable_path_is_relative_to_the_program_being_launched(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    gui = bundle / 'Contents/MacOS'
    tools = bundle / 'Contents/Frameworks/bin'
    gui.mkdir(parents=True)
    tools.mkdir(parents=True)
    (gui / 'only-gui.dylib').write_bytes(b'fixture')
    links = 'fixture:\n\t@executable_path/only-gui.dylib (compatibility version 1.0.0)\n'
    assert dyld_paths.inspect_paths(bundle, tools / 'deno', links, '', '', tools)
    (tools / 'only-gui.dylib').write_bytes(b'tool dependency')
    assert not dyld_paths.inspect_paths(bundle, tools / 'deno', links, '', '', tools)


def test_app_inherited_runpath_resolves_a_bundled_library(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    frameworks = bundle / 'Contents/Frameworks'
    frameworks.mkdir(parents=True)
    (frameworks / 'libx.dylib').write_bytes(b'fixture')
    links = 'fixture:\n\t@rpath/libx.dylib (compatibility version 1.0.0)\n'
    inherited = 'Load command 1\n cmd LC_RPATH\n cmdsize 48\n path @executable_path/../Frameworks (offset 12)\n'
    assert not dyld_paths.inspect_paths(bundle, frameworks / 'plugin.so', links, '', inherited)


def test_first_existing_runpath_cannot_be_bypassed_by_later_safe_copy(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    first, second = bundle / 'first', bundle / 'second'
    first.mkdir(parents=True)
    second.mkdir()
    external = tmp_path / 'outside.dylib'
    external.write_bytes(b'external fixture')
    (first / 'libx.dylib').symlink_to(external)
    (second / 'libx.dylib').write_bytes(b'internal fixture')
    loads = ''.join(f'Load command {i}\n cmd LC_RPATH\n cmdsize 48\n path @loader_path/{name} (offset 12)\n'
                    for i, name in enumerate(('first', 'second')))
    links = 'fixture:\n\t@rpath/libx.dylib (compatibility version 1.0.0)\n'
    assert dyld_paths.inspect_paths(bundle, bundle / 'program', links, loads)


def test_auxiliary_library_uses_its_reaching_executable_context(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    tools = bundle / 'Tools'
    tools.mkdir(parents=True)
    for name in ('deno', 'plugin.dylib', 'helper.dylib'):
        (tools / name).write_bytes(b'fixture')
    records = [
        [str(tools / 'deno'), 'arm64', 'Mach-O executable',
         'deno:\n\t@loader_path/plugin.dylib (compatibility version 1.0.0)\n', ''],
        [str(tools / 'plugin.dylib'), 'arm64', 'Mach-O dynamically linked shared library',
         'plugin:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', ''],
        [str(tools / 'helper.dylib'), 'arm64', 'Mach-O dynamically linked shared library', '', ''],
    ]
    findings = dyld_paths.audit_records(bundle, records)
    assert not findings, findings


def test_shared_library_must_pass_every_reaching_executable_context(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    one, two, shared = [bundle / name for name in ('one', 'two', 'shared')]
    for directory in (one, two, shared):
        directory.mkdir(parents=True)
    for path in (one / 'program', two / 'program', shared / 'plugin.dylib', one / 'helper.dylib'):
        path.write_bytes(b'fixture')
    root_links = 'fixture:\n\t@loader_path/../shared/plugin.dylib (compatibility version 1.0.0)\n'
    records = [[str(path / 'program'), 'arm64', 'Mach-O executable', root_links, ''] for path in (one, two)]
    records += [[str(shared / 'plugin.dylib'), 'arm64', 'Mach-O shared library',
        'fixture:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', ''],
        [str(one / 'helper.dylib'), 'arm64', 'Mach-O shared library', '', '']]
    findings = dyld_paths.audit_records(bundle, records)
    assert any(str(two / 'program') in finding and 'unresolved' in finding for finding in findings)


def test_ytdlp_dynamic_extension_has_explicit_runtime_context(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    runtime = bundle / 'Contents/Frameworks/bin/yt-dlp_dist'
    extension = runtime / '_internal/package/plugin.so'
    extension.parent.mkdir(parents=True)
    for path in (runtime / 'yt-dlp_macos', extension, runtime / 'helper.dylib'):
        path.write_bytes(b'fixture')
    records = [[str(runtime / 'yt-dlp_macos'), 'arm64', 'Mach-O executable', '', ''],
        [str(extension), 'arm64', 'Mach-O shared library',
         'fixture:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', ''],
        [str(runtime / 'helper.dylib'), 'arm64', 'Mach-O shared library', '', '']]
    assert not dyld_paths.audit_records(bundle, records)


def test_unreached_auxiliary_library_cannot_borrow_any_executable_context(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    tools = bundle / 'Tools'
    tools.mkdir(parents=True)
    for name in ('deno', 'plugin.dylib', 'helper.dylib'):
        (tools / name).write_bytes(b'fixture')
    records = [[str(tools / 'deno'), 'arm64', 'Mach-O executable', '', ''],
        [str(tools / 'plugin.dylib'), 'arm64', 'Mach-O shared library',
         'fixture:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', ''],
        [str(tools / 'helper.dylib'), 'arm64', 'Mach-O shared library', '', '']]
    assert any('context is not established' in finding for finding in dyld_paths.audit_records(bundle, records))


def test_known_dynamic_runtime_is_checked_even_if_another_root_reaches_extension(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    gui = bundle / 'Contents/MacOS/Whisper Transcriber Suite'
    runtime = bundle / 'Contents/Frameworks/bin/yt-dlp_dist'
    extension = runtime / '_internal/plugin.so'
    gui.parent.mkdir(parents=True)
    extension.parent.mkdir(parents=True)
    for path in (gui, gui.parent / 'helper.dylib', runtime / 'yt-dlp_macos', extension):
        path.write_bytes(b'fixture')
    gui_links = 'fixture:\n\t@loader_path/../Frameworks/bin/yt-dlp_dist/_internal/plugin.so (compatibility version 1.0.0)\n'
    records = [[str(gui), 'arm64', 'Mach-O executable', gui_links, ''],
        [str(gui.parent / 'helper.dylib'), 'arm64', 'Mach-O shared library', '', ''],
        [str(runtime / 'yt-dlp_macos'), 'arm64', 'Mach-O executable', '', ''],
        [str(extension), 'arm64', 'Mach-O shared library',
         'fixture:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', '']]
    assert any('unresolved' in finding and 'yt-dlp_macos' in finding
               for finding in dyld_paths.audit_records(bundle, records))


def test_ytdlp_dynamic_domain_follows_frameworks_to_resources_symlink(tmp_path, dyld_paths):
    bundle = tmp_path / 'Example.app'
    resources = bundle / 'Contents/Resources/yt-dlp_dist'
    extension = resources / '_internal/package/plugin.so'
    extension.parent.mkdir(parents=True)
    public = bundle / 'Contents/Frameworks/bin/yt-dlp_dist'
    public.parent.mkdir(parents=True)
    public.symlink_to(resources, target_is_directory=True)
    for path in (resources / 'yt-dlp_macos', extension, resources / 'helper.dylib'):
        path.write_bytes(b'fixture')
    records = [[str(public / 'yt-dlp_macos'), 'arm64', 'Mach-O executable', '', ''],
        [str(public / '_internal/package/plugin.so'), 'arm64', 'Mach-O shared library',
         'fixture:\n\t@executable_path/helper.dylib (compatibility version 1.0.0)\n', ''],
        [str(public / 'helper.dylib'), 'arm64', 'Mach-O shared library', '', '']]
    assert not dyld_paths.audit_records(bundle, records)
