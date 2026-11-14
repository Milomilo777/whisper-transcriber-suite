"""Mac review regressions on the actual spec policy and package contract."""
import ast
import importlib.util
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace,ModuleType
import pytest
from tests.test_mac_minimum_policy import declared_minimum,SPEC
ROOT=SPEC.parents[3]

def functions(*names,**extra):
 tree=ast.parse(SPEC.read_text(encoding='utf-8'))
 nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
 namespace=dict(os=os,**extra)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SPEC),'exec'),namespace)
 return namespace

@pytest.mark.parametrize('override',[None,'10.15'])
def test_uninspected_bundle_never_declares_a_default(override):
 with pytest.raises(SystemExit):declared_minimum({},override=override)

def fake_macholib(monkeypatch,parser):
 package=ModuleType('macholib');package.mach_o=SimpleNamespace(LC_BUILD_VERSION=0x32,LC_VERSION_MIN_MACOSX=0x24)
 module=ModuleType('macholib.MachO');module.MachO=parser
 monkeypatch.setitem(sys.modules,'macholib',package);monkeypatch.setitem(sys.modules,'macholib.MachO',module)

def test_macho_inspection_failure_never_drops_a_component(monkeypatch):
 def fail(path):raise ValueError('unreadable native header')
 fake_macholib(monkeypatch,fail)
 with pytest.raises(SystemExit):functions('_macho_minos')['_macho_minos']('deno')

def test_missing_macos_minimum_is_an_error(monkeypatch):
 fake_macholib(monkeypatch,lambda path:SimpleNamespace(headers=[SimpleNamespace(commands=[])]))
 with pytest.raises(SystemExit):functions('_macho_minos')['_macho_minos']('deno')

def test_patch_deployment_target_is_not_truncated(monkeypatch):
 header=SimpleNamespace(header=SimpleNamespace(cputype=0x01000007),commands=[(SimpleNamespace(cmd=0x32),SimpleNamespace(minos=0x000C0301,platform=1),None)])
 fake_macholib(monkeypatch,lambda path:SimpleNamespace(headers=[header]))
 assert functions('_macho_minos')['_macho_minos']('deno')==(12,3,1)

def test_recursive_verbatim_and_data_machos_enter_the_policy(tmp_path):
 nested=tmp_path/'bin/yt-dlp_dist/_internal/Python';nested.parent.mkdir(parents=True);nested.write_bytes(bytes.fromhex('cffaedfe'))
 datum=tmp_path/'data/high.so';datum.parent.mkdir();datum.write_bytes(bytes.fromhex('cffaedfe'))
 env=functions('_minimum_sources',_is_macho=lambda p:Path(p).read_bytes()[:4]==bytes.fromhex('cffaedfe'))
 env.update(a=SimpleNamespace(binaries=[],datas=[('high.so',str(datum),'DATA')]),_BIN_DIR=str(tmp_path/'bin'),_POST_COPY_BINS=('yt-dlp','deno'))
 node=next(n for n in ast.parse(SPEC.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_minos_files' for t in n.targets))
 exec(compile(ast.Module(body=[node],type_ignores=[]),str(SPEC),'exec'),env)
 assert str(nested) in env['_minos_files'] and str(datum) in env['_minos_files']

def test_missing_required_native_component_refuses_packaging():
 env=functions('_require_native_components')
 assert '_require_native_components' in env,'No mandatory native-component gate exists'
 with pytest.raises(SystemExit,match='onnxruntime'):env['_require_native_components'](['/site/numpy/core/x.so'],required=('onnxruntime',))

def test_optional_scipy_absence_does_not_reject_the_base_package(monkeypatch):
 from core import hardware_probe as probe
 import importlib
 def available(name):
  if name.startswith('scipy'):raise ModuleNotFoundError("No module named 'scipy'",name='scipy')
  return SimpleNamespace()
 monkeypatch.setattr(importlib,'import_module',available)
 assert probe._native_component_report()['native_components']
 paths=['/site/'+name+'/native.so' for name in ('numpy','ctranslate2','av','onnxruntime','PIL','bidi','google/_upb','sherpa_onnx','hf_xet')]
 paths += ['/bin/'+name for name in ('ffmpeg','ffprobe','yt-dlp','deno')]
 functions('_require_native_components')['_require_native_components'](paths)

@pytest.fixture
def contract():
 path=SPEC.with_name('bundle_contract.py')
 assert path.is_file(),'No verified-app/DMG identity contract exists'
 spec=importlib.util.spec_from_file_location('bundle_contract',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def app(tmp_path,version='2.4.0',minimum='12.0'):
 root=tmp_path/'App.app';(root/'Contents/MacOS').mkdir(parents=True)
 (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':version,'LSMinimumSystemVersion':minimum}))
 (root/'Contents/MacOS/App').write_bytes(b'native fixture')
 return root

def test_build_host_below_declared_floor_is_non_release(contract,tmp_path):
 with pytest.raises(ValueError,match='supported'):contract.require_supported_host(app(tmp_path),'10.15.7')

def test_manifest_rejects_old_dmg_minimum(contract,tmp_path):
 source=app(tmp_path/'source');expected=contract.bundle_manifest(source);other=app(tmp_path/'other',minimum='10.15')
 with pytest.raises(ValueError):contract.verify_manifest(other,expected)

def test_manifest_rejects_stale_same_version_code(contract,tmp_path):
 source=app(tmp_path/'source');expected=contract.bundle_manifest(source);other=app(tmp_path/'other');(other/'Contents/MacOS/App').write_bytes(b'stale code')
 with pytest.raises(ValueError):contract.verify_manifest(other,expected)

def test_manifest_accepts_exact_finder_copy(contract,tmp_path):
 import shutil
 source=app(tmp_path/'source');expected=contract.bundle_manifest(source);other=tmp_path/'copy.app';shutil.copytree(source,other)
 contract.verify_manifest(other,expected)


def test_foreign_platform_does_not_invent_a_macos_floor(monkeypatch):
 header=SimpleNamespace(commands=[(SimpleNamespace(cmd=0x32),SimpleNamespace(minos=0x00110000,platform=2),None)])
 fake_macholib(monkeypatch,lambda path:SimpleNamespace(headers=[header]))
 with pytest.raises(SystemExit):functions('_macho_minos')['_macho_minos']('foreign')

def test_non_target_slice_does_not_raise_the_target_floor(monkeypatch):
 headers=[SimpleNamespace(header=SimpleNamespace(cputype=cpu),commands=[(SimpleNamespace(cmd=0x32),SimpleNamespace(minos=value,platform=1),None)]) for cpu,value in ((0x01000007,0x000C0000),(0x0100000C,0x000D0000))]
 fake_macholib(monkeypatch,lambda path:SimpleNamespace(headers=headers))
 assert functions('_macho_minos')['_macho_minos']('fat','x86_64')==(12,0,0)

def test_missing_target_slice_refuses_build(monkeypatch):
 header=SimpleNamespace(header=SimpleNamespace(cputype=0x0100000C),commands=[])
 fake_macholib(monkeypatch,lambda path:SimpleNamespace(headers=[header]))
 with pytest.raises(SystemExit):functions('_macho_minos')['_macho_minos']('arm-only','x86_64')

def test_fat64_magic_is_not_skipped(tmp_path):
 path=tmp_path/'x';path.write_bytes(bytes.fromhex('cafebabf'))
 env=functions('_minimum_sources');empty=tmp_path/'bin';empty.mkdir()
 assert str(path) in env['_minimum_sources']([('x',str(path),'BINARY')],[],str(empty))

def test_native_import_failure_is_not_reported_as_complete(monkeypatch):
 from core import hardware_probe as probe
 import importlib
 def fail(name):raise ImportError('missing '+name)
 monkeypatch.setattr(importlib,'import_module',fail)
 with pytest.raises(RuntimeError,match="Required native component"):probe._native_component_report()


@pytest.mark.parametrize('magic',['feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca'])
def test_every_macho_magic_is_recognized_before_tool_fetch(tmp_path,magic):
 path=tmp_path/'native';path.write_bytes(bytes.fromhex(magic))
 assert functions('_is_macho')['_is_macho'](path)

def test_missing_source_walk_is_not_an_empty_success(tmp_path):
 env=functions('_minimum_sources')
 with pytest.raises(OSError):env['_minimum_sources']([],[],str(tmp_path/'missing'))


def test_strict_probe_runs_the_frozen_copy_not_the_build_python(contract,tmp_path,monkeypatch):
 from core import hardware_probe as probe
 calls=[]
 def run(command,result,timeout):
  calls.append(command)
  return {'native_components':list(probe.NATIVE_COMPONENT_MODULES)}
 monkeypatch.setattr(probe,'_run_command',run)
 root=app(tmp_path);contract.require_native_imports(root)
 assert calls[0][0]==str(root/'Contents/MacOS/Whisper Transcriber Suite')
 assert calls[0][1:3]==['--hardware-probe-worker','native-components']

def test_incomplete_frozen_component_report_fails_the_audit(contract,tmp_path,monkeypatch):
 from core import hardware_probe as probe
 monkeypatch.setattr(probe,'_run_command',lambda *args:{'native_components':[]})
 with pytest.raises(ValueError,match='incomplete'):contract.require_native_imports(app(tmp_path))

def test_package_checks_bind_copy_before_executing_it():
 script=SPEC.with_name('test_dmg.sh').read_text()
 binding=script.index('"$CONTRACT" verify "$APP" "$MANIFEST"')
 assert binding < script.index('"$SCRIPT_DIR/verify_mac_bundle.sh" "$APP"')
 assert binding < script.index('transcribe --help')

def test_packaging_refuses_a_stale_image_even_if_builder_returns_success():
 script=(ROOT/'platform/macos/build_mac.sh').read_text()
 assert script.index('rm -f -- "dist/Whisper Transcriber Suite-$SUFFIX.dmg" "dist/$OUT"') < script.index('WTS_DMG_SUFFIX="$SUFFIX" bash')
 assert 'PACKAGE_ARGS=(--manifest "$MANIFEST")' in script
 assert 'builddmg.command "${PACKAGE_ARGS[@]}"' in script
 packager=(ROOT/'platform/macos/pyinstaller/builddmg.command').read_text()
 assert packager.index('test_dmg.sh "${AUDIT_ARGS[@]}"') < packager.index('mv -n "$IMAGE" "$DMG"')

def test_supported_host_gate_precedes_package_creation():
 script=(ROOT/'platform/macos/build_mac.sh').read_text()
 assert script.index('"$CONTRACT" host "$APP" "$MACOS"') < script.index('say_step "6. .dmg"')
 assert 'not release validated' in script


def test_frozen_import_error_is_reported_without_unhandled_gui_exception(tmp_path,monkeypatch):
 from core import hardware_probe as probe
 import json
 def fail():raise RuntimeError('Required native component failed: example')
 monkeypatch.setattr(probe,'_native_component_report',fail)
 result=tmp_path/'result.json'
 monkeypatch.setattr(sys,'argv',['app','native-components',str(result)])
 probe.worker_main()
 assert 'example' in json.loads(result.read_text())['error']

def test_child_error_payload_fails_the_parent(tmp_path):
 from core import hardware_probe as probe
 import json
 result=tmp_path/'result.json';result.write_text(json.dumps({'error':'missing native provider'}))
 with pytest.raises(RuntimeError,match='missing native'):probe._run_command([sys.executable,'-c','pass'],result,2)


def test_manifest_preserves_owner_execute_permission(contract,tmp_path,monkeypatch):
 import os,stat
 root=app(tmp_path);payload=root/'Contents/MacOS/App';current=[0o755];original=Path.lstat
 def mode(path,*args,**kwargs):
  value=original(path,*args,**kwargs)
  if path==payload:
   fields=list(value);fields[0]=stat.S_IFREG|current[0];return os.stat_result(fields)
  return value
 monkeypatch.setattr(Path,'lstat',mode)
 expected=contract.bundle_manifest(root);current[0]=0o645
 with pytest.raises(ValueError):contract.verify_manifest(root,expected)
