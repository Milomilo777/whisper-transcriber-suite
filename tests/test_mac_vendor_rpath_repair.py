"""Controlled native-tool commands; these are not native macOS bundle tests."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tests.mac_path_alias import directory_alias


ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "platform/macos/pyinstaller"
SPEC = MAC / "whisper_project_mac.spec"
VENDOR = "/opt/gfortran-darwin-arm64-cross/lib/gcc/arm64-apple-darwin20.0.0/11.3.0"


def load_helper(monkeypatch, name):
    monkeypatch.syspath_prepend(str(MAC))
    spec = importlib.util.spec_from_file_location(name, MAC / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    # Mach-O absolute paths are POSIX spellings; keep their modeled current
    # drive aligned with the fixture even when Windows CI checks out on D:.
    monkeypatch.chdir(tmp_path)
    app = tmp_path / "dist/Whisper Transcriber Suite.app"
    gui = app / "Contents/MacOS/Whisper Transcriber Suite"
    library = app / "Contents/Frameworks/numpy/__dot__dylibs/libopenblas64_.0.dylib"
    dependency = library.with_name("libgfortran.5.dylib")
    records = {}
    for path in (gui, library, dependency):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex("cffaedfe") + b"synthetic Mach-O fixture")
        records[str(path)] = {
            "architectures": ["arm64"],
            "description": "Mach-O 64-bit " + ("executable" if path == gui else "dynamically linked shared library"),
            "rpaths": ["@loader_path", VENDOR] if path == library else [],
            "dependencies": ["@rpath/libgfortran.5.dylib"] if path == library else ["/usr/lib/libSystem.B.dylib"],
        }
    state, log = tmp_path / "tool-state.json", tmp_path / "commands.jsonl"
    state.write_text(json.dumps(records), encoding="utf-8")
    shim = tmp_path / "native_tool.py"
    shim.write_text('''import json,sys
from pathlib import Path
state,log,tool,*args=sys.argv[1:]
p=Path(state); data=json.loads(p.read_text()); path=args[-1]
with Path(log).open('a') as f:f.write(json.dumps([tool,*args])+'\\n')
record=data.get(path,{}) if tool in ('codesign','lipo') else data[path]
if record.get('fail_tool')==tool:raise SystemExit(17)
if tool=='file':print(record['description'])
elif tool=='lipo':
 if '-thin' in args:
  original=data[args[0]]; arch=args[args.index('-thin')+1]
  if original.get('fail_stage'):raise SystemExit(33)
  record=dict(original,architectures=[arch],slice_rpaths={arch:original['slice_rpaths'][arch][:]})
  data[path]=record; Path(path).write_bytes(bytes.fromhex('cffaedfe')+b'synthetic slice')
  p.write_text(json.dumps(data))
 elif '-create' in args:
  parts=[data[v] for v in args[1:args.index('-output')]]
  record=dict(parts[0],architectures=[a for part in parts for a in part['architectures']],
              slice_rpaths={a:paths for part in parts for a,paths in part['slice_rpaths'].items()})
  if record.get('wrong_merge'):record['architectures']=record['architectures'][:1]
  data[path]=record; Path(path).write_bytes(bytes.fromhex('cafebabe')+b'synthetic merged')
  p.write_text(json.dumps(data))
 else:print(' '.join(record['architectures']))
elif tool=='otool':
 if '-L' in args:
  print(path+':')
  for value in record['dependencies']:print('\\t'+value+' (compatibility version 1.0.0, current version 1.0.0)')
 elif record.get('malformed_loads'):print('cmd LC_RPATH')
 else:
  print(path+':\\nLoad command 0\\n cmd LC_BUILD_VERSION\\n cmdsize 32\\n platform 1\\n minos 14.0')
  paths=record.get('slice_rpaths',{}).get(args[args.index('-arch')+1],record['rpaths'])
  for i,value in enumerate(paths,1):print(f'Load command {i}\\n cmd LC_RPATH\\n cmdsize 64\\n path {value} (offset 12)')
elif tool=='install_name_tool':
 deleted=[args[i+1] for i,arg in enumerate(args[:-1]) if arg=='-delete_rpath']
 if len(deleted)!=len(set(deleted)):raise SystemExit(31)
 slices=record.get('slice_rpaths',{a:record['rpaths'][:] for a in record['architectures']})
 if any(v not in paths for paths in slices.values() for v in deleted):raise SystemExit(32)
 if not record.get('ignore_edit'):
  for paths in slices.values():
   for value in deleted:paths.remove(value)
  if 'slice_rpaths' in record:record['slice_rpaths']=slices
  else:record['rpaths']=next(iter(slices.values()))
  p.write_text(json.dumps(data))
elif tool!='codesign':raise SystemExit(23)
''', encoding="utf-8")
    run = subprocess.run
    replace = os.replace

    def replace_with_native_metadata(source, destination):
        replace(source, destination)
        data = json.loads(state.read_text())
        if str(source) in data:
            data[str(destination)] = data.pop(str(source))
            state.write_text(json.dumps(data))

    monkeypatch.setattr(os, 'replace', replace_with_native_metadata)

    def native_run(argv, **kwargs):
        # Real controlled subprocesses model each requested native command.
        return run([sys.executable, str(shim), str(state), str(log), Path(argv[0]).name, *map(str, argv[1:])], **kwargs)

    return app, gui, library, dependency, state, log, native_run


@pytest.mark.parametrize('tool_failure', [None, 'install_name_tool', 'codesign'])
def test_spec_repairs_vendor_rpath_before_final_outer_signing(bundle, monkeypatch, tool_failure):
    app, _gui, library, _dependency, state, log, native_run = bundle
    checker = load_helper(monkeypatch, "check_bundle_paths")
    source = SPEC.read_text(encoding="utf-8")
    tail = source[source.index('# ---- Post-BUNDLE: byte-for-byte'):]

    def spec_run(argv, **kwargs):
        if len(argv) > 1 and str(argv[1]).endswith("repair_bundle_rpaths.py"):
            load_helper(monkeypatch, "repair_bundle_rpaths").repair_bundle(app, run=native_run)
            return subprocess.CompletedProcess(argv, 0)
        return native_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spec_run)
    namespace = dict(DISTPATH=str(app.parent), _POST_COPY_BINS=[], _BIN_DIR=str(app.parent / "bin"),
        _REPO_ROOT=str(ROOT), os=__import__('os'), _MIN_MACOS='14.0', _native_target='arm64',
        _minimum_sources=lambda *a: [], _require_native_components=lambda *a: None)
    # Bind the interpreter only under names actually imported by the full spec.
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == 'sys':
                    namespace[alias.asname or alias.name] = sys
    if tool_failure:
        change(state, library, fail_tool=tool_failure)
        with pytest.raises(subprocess.CalledProcessError):
            exec(compile(tail, str(SPEC), 'exec'), namespace)
        assert not any(args[:2]==['codesign','--force'] and args[-1]==str(app) for args in commands(log))
        return
    exec(compile(tail, str(SPEC), 'exec'), namespace)
    current = json.loads(state.read_text())
    # The unchanged strict checker is the oracle; baseline has no repair hook.
    values = []
    for path, record in current.items():
        links = native_run(['/usr/bin/otool', '-L', '-arch', 'arm64', path], check=True, capture_output=True, text=True).stdout
        loads = native_run(['/usr/bin/otool', '-l', '-arch', 'arm64', path], check=True, capture_output=True, text=True).stdout
        values.append((path, 'arm64', record['description'], links, loads))
    assert checker.audit_records(app, values) == []
    assert current[str(library)]['rpaths'] == ['@loader_path']
    recorded = commands(log)
    edited = next(i for i, args in enumerate(recorded) if args[0]=='install_name_tool')
    inner = next(i for i,args in enumerate(recorded) if args[:2]==['codesign','--force'] and args[-1]==str(library))
    outer = next(i for i,args in enumerate(recorded) if args[:2]==['codesign','--force'] and args[-1]==str(app))
    assert edited < inner < outer


def commands(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def change(state, path, **values):
    data = json.loads(state.read_text())
    data[str(path)].update(values)
    state.write_text(json.dumps(data))


def test_valid_loader_and_main_executable_context_paths_are_preserved(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    paths = ['@executable_path/../Frameworks', '@loader_path', VENDOR]
    change(state, library, rpaths=paths)
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 1
    assert json.loads(state.read_text())[str(library)]['rpaths'] == paths[:2]
    edits = [args for args in commands(log) if args[0]=='install_name_tool']
    assert edits == [['install_name_tool', '-delete_rpath', VENDOR, str(library)]]


@pytest.mark.parametrize('tool', ['file', 'lipo', 'otool', 'install_name_tool', 'codesign'])
def test_native_tool_failure_is_fatal(bundle, monkeypatch, tool):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, fail_tool=tool)
    with pytest.raises(subprocess.CalledProcessError):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    if tool != 'codesign':
        assert not any(args[0]=='codesign' for args in commands(log))


def test_noop_native_edit_is_not_signed_or_accepted(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, ignore_edit=True)
    with pytest.raises(ValueError, match='did not match'):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert not any(args[0]=='codesign' for args in commands(log))


@pytest.mark.parametrize('paths,dependencies,match', [
    ([VENDOR], ['@rpath/libgfortran.5.dylib'], 'unresolved'),
    (['@loader_path/../../../../../outside', VENDOR], ['/usr/lib/libSystem.B.dylib'], 'leaves'),
    (['@loader_path', VENDOR], ['/opt/vendor/libnotbundled.dylib'], 'External dependency'),
])
def test_missing_or_escaping_dependencies_fail_before_mutation(bundle, monkeypatch, paths, dependencies, match):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, rpaths=paths, dependencies=dependencies)
    with pytest.raises(ValueError, match=match):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert not any(args[0] in ('install_name_tool', 'codesign') for args in commands(log))
    assert json.loads(state.read_text())[str(library)]['rpaths'] == paths


def test_unknown_executable_context_is_not_invented(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    plugin = app / 'Contents/Frameworks/bin/unclaimed-plugin.dylib'
    plugin.parent.mkdir()
    library.rename(plugin)
    data = json.loads(state.read_text())
    data[str(plugin)] = data.pop(str(library))
    data[str(plugin)].update(rpaths=['@executable_path/../lib', VENDOR],
                             dependencies=['/usr/lib/libSystem.B.dylib'])
    state.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='context is not established'):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert not any(args[0]=='install_name_tool' for args in commands(log))


def test_already_contained_bundle_is_not_rewritten_or_resigned(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, rpaths=['@loader_path', '/usr/lib'])
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 0
    assert not any(args[0] in ('install_name_tool', 'codesign') for args in commands(log))


def test_fat_binary_is_inspected_per_slice_but_repaired_once(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    data = json.loads(state.read_text())
    for value in data.values():
        value['architectures'] = ['x86_64', 'arm64']
    state.write_text(json.dumps(data))
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 1
    assert len([args for args in commands(log) if args[0]=='install_name_tool']) == 1
    inspected = [args for args in commands(log) if args[:2]==['otool','-l'] and args[-1]==str(library)]
    assert {args[3] for args in inspected} == {'x86_64', 'arm64'}


@pytest.mark.parametrize('slices', [
    {'arm64': [VENDOR], 'x86_64': ['/opt/intel/lib']},
    {'arm64': [VENDOR], 'x86_64': []},
    {'arm64': [VENDOR, VENDOR]},
    {'arm64': [VENDOR, VENDOR], 'x86_64': [VENDOR]},
])
def test_slice_specific_and_duplicate_vendor_paths_are_repaired(bundle, monkeypatch, slices):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, architectures=list(slices),
           slice_rpaths={arch: ['@loader_path', *paths] for arch, paths in slices.items()})
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 1
    current = json.loads(state.read_text())[str(library)]
    assert current['architectures'] == list(slices)
    assert current['slice_rpaths'] == {arch: ['@loader_path'] for arch in slices}
    assert any(args[:2] == ['codesign', '--verify'] for args in commands(log))


@pytest.mark.parametrize('failure', ['fail_stage', 'wrong_merge', 'edit_failure', 'edit_noop'])
def test_failed_asymmetric_staging_preserves_original_and_does_not_sign(bundle, monkeypatch, failure):
    app, _gui, library, _dependency, state, log, run = bundle
    slices = {'arm64': ['@loader_path', VENDOR], 'x86_64': ['@loader_path']}
    injected = {'edit_failure': {'fail_tool': 'install_name_tool'},
                'edit_noop': {'ignore_edit': True}}.get(failure, {failure: True})
    change(state, library, architectures=list(slices), slice_rpaths=slices, **injected)
    original = library.read_bytes()
    original_mode = library.stat().st_mode
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert library.read_bytes() == original
    assert library.stat().st_mode == original_mode
    assert json.loads(state.read_text())[str(library)]['slice_rpaths'] == slices
    assert not list(library.parent.glob('.rpath-*'))
    assert not any(args[0] == 'codesign' for args in commands(log))
    if failure in ('edit_failure', 'edit_noop'):
        assert any(args[0] == 'install_name_tool' and '.rpath-' in args[-1] for args in commands(log))


@pytest.mark.parametrize('architecture', ['arm64', 'x86_64'])
def test_thin_release_does_not_enter_universal_staging(bundle, monkeypatch, architecture):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, architectures=[architecture])
    helper = load_helper(monkeypatch, 'repair_bundle_rpaths')
    def refuse_staging(*args, **kwargs):
        raise AssertionError('Thin release entered universal staging')
    monkeypatch.setattr(helper.tempfile, 'TemporaryDirectory', refuse_staging)
    assert helper.repair_bundle(app, run=run) == 1
    assert not any(args[0] == 'lipo' and '-output' in args for args in commands(log))


@pytest.mark.parametrize('broken', [False, True])
def test_final_verifier_rejects_post_seal_tool_failure(tmp_path, broken):
    from tests.test_mac_build_pins import _find_bash
    bash = _find_bash()
    if bash is None:
        pytest.skip('Bash required for the actual final tool verifier')
    tool = tmp_path / 'Contents/Frameworks/bin/yt-dlp'
    tool.parent.mkdir(parents=True)
    (tool.parent / 'yt-dlp_dist/_internal').mkdir(parents=True)
    tool.write_text('#!/bin/sh\necho synthetic-tool\nexit ' + ('17' if broken else '0') + '\n', newline='\n')
    tool.chmod(0o755)
    text = (MAC / 'verify_mac_bundle.sh').read_text()
    start = text.index('# yt-dlp must be')
    end = text.index('v="$("$B/deno"', start)
    script = tmp_path / 'post-seal-check.sh'
    script.write_text('set -uo pipefail\nbad=0\nB="$1/Contents/Frameworks/bin"\n'
                      'file() { echo "Mach-O synthetic"; }\n' + text[start:end]
                      + '\n[ "$bad" = 0 ]\n', newline='\n')
    result = subprocess.run([bash, str(script), tmp_path.as_posix()], capture_output=True, text=True, timeout=20)
    assert (result.returncode != 0) == broken, result.stdout + result.stderr
    assert ('yt-dlp FAILED' in result.stdout) == broken
    # Every shipped entry point invokes this guard after PyInstaller's seal.
    for path in (ROOT / 'platform/macos/build_mac.sh', ROOT / '.github/workflows/macos-app.yml'):
        source = path.read_text()
        assert source.index('pyinstaller --noconfirm') < source.index('bash platform/macos/pyinstaller/verify_mac_bundle.sh')
    assert 'verify_mac_bundle.sh' in (MAC / 'builddmg.command').read_text()


def test_path_with_spaces_remains_one_native_argument(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    vendor = '/opt/vendor compiler root/lib'
    change(state, library, rpaths=['@loader_path', vendor])
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 1
    assert ['install_name_tool', '-delete_rpath', vendor, str(library)] in commands(log)


def test_hardlinked_binary_cannot_modify_an_external_original(bundle, monkeypatch, tmp_path):
    app, _gui, library, _dependency, _state, log, run = bundle
    anchor = tmp_path / 'original-vendor.dylib'
    __import__('os').link(library, anchor)
    original = anchor.read_bytes()
    with pytest.raises(ValueError, match='hard-linked'):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert anchor.read_bytes() == original
    assert not any(args[0]=='install_name_tool' for args in commands(log))


@pytest.mark.parametrize('values,match', [
    ({'architectures': []}, 'architecture'),
    ({'malformed_loads': True}, 'Unparseable rpath'),
])
def test_incomplete_native_inspection_cannot_authorize_repair(bundle, monkeypatch, values, match):
    app, _gui, library, _dependency, state, log, run = bundle
    change(state, library, **values)
    with pytest.raises(ValueError, match=match):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert not any(args[0] in ('install_name_tool', 'codesign') for args in commands(log))


def native_absolute(path):
    value = path.as_posix()
    return value[2:] if value[1:3] == ':/' else value


@pytest.mark.parametrize('vendor', [False, True])
def test_absolute_inbundle_search_path_is_retained(bundle, monkeypatch, vendor):
    app, _gui, library, _dependency, state, log, run = bundle
    internal = native_absolute(library.parent)
    assert Path(internal).resolve() == library.parent.resolve()
    change(state, library, rpaths=[internal] + ([VENDOR] if vendor else []))
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == int(vendor)
    assert json.loads(state.read_text())[str(library)]['rpaths'] == [internal]
    assert not any(internal in args for args in commands(log) if args[0]=='install_name_tool')


def test_absolute_symlink_canonical_inside_bundle_is_retained(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    alias = app / 'Contents/Frameworks/local-library-alias'
    directory_alias(alias, library.parent)
    internal = native_absolute(alias)
    change(state, library, rpaths=[internal, VENDOR])
    assert load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run) == 1
    assert json.loads(state.read_text())[str(library)]['rpaths'] == [internal]
    assert not any(internal in args for args in commands(log) if args[0]=='install_name_tool')


@pytest.mark.parametrize('symlink', [False, True])
def test_bundle_spelled_absolute_escape_is_not_silently_deleted(bundle, monkeypatch, tmp_path, symlink):
    app, _gui, library, _dependency, state, log, run = bundle
    outside = tmp_path / 'outside'
    outside.mkdir()
    alias = app / 'Contents/Frameworks/escaping-alias'
    if symlink:
        directory_alias(alias, outside)
        escape = native_absolute(alias)
    else:
        escape = native_absolute(app / '..' / '..' / 'outside')
    change(state, library, rpaths=['@loader_path', escape, VENDOR])
    with pytest.raises(ValueError, match='leaves the bundle'):
        load_helper(monkeypatch, 'repair_bundle_rpaths').repair_bundle(app, run=run)
    assert not any(args[0] in ('install_name_tool', 'codesign') for args in commands(log))
