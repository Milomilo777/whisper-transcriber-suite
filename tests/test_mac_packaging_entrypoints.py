"""Execute the documented packaging entry with controlled Mac-tool replies."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from tests.test_mac_build_pins import _find_bash
from tests.test_mac_review_regressions import app,SPEC

def run_entry(tmp_path,host='10.15.7',audit=0,*,image=False,copied_audit=0,mutation=None,args='',existing=False,suffix='x64',thin=False):
 bash=_find_bash()
 if bash is None:pytest.skip('A working Bash is required')
 root=tmp_path/'repo';tools=root/'platform/macos/pyinstaller';tools.mkdir(parents=True)
 for name in ('builddmg.command','bundle_contract.py'):shutil.copyfile(SPEC.with_name(name),tools/name)
 native_mutation = 'printf changed >> "dist/Whisper Transcriber Suite.app/Contents/MacOS/App"\n' if mutation=='audit' else ''
 architecture_gate = '[ "$2" = x86_64 ] || exit 1\n' if thin else ''
 (tools/'verify_mac_bundle.sh').write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$2" >> native-audit.args\n'+architecture_gate+native_mutation+'exit '+str(audit)+'\n')
 # A stub-copy audit still has to be reached through the production entry.
 (tools/'test_dmg.sh').write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > copied-audit.args\nexit '+str(copied_audit)+'\n')
 app(root/'dist');(root/'dist/App.app').rename(root/'dist/Whisper Transcriber Suite.app')
 marker=root/'packaged';env=os.environ.copy();env.update(ENTRY=str(tools/'builddmg.command').replace('\\','/'),TEST_PY=sys.executable.replace('\\','/'),PACKAGE_MARKER=str(marker).replace('\\','/'))
 output=root/'dist/Whisper Transcriber Suite-x64.dmg'
 if existing:output.write_bytes(b'previous image')
 build_image = 'printf image > "${@: -2:1}"; ' if image else ''
 build_mutation = 'printf changed >> "dist/Whisper Transcriber Suite.app/Contents/MacOS/App"; ' if mutation=='builder' else ''
 code='sw_vers() { echo "$TEST_HOST"; }\nuname() { echo x86_64; }\ncreate-dmg() { echo called > "$PACKAGE_MARKER"; '+build_image+build_mutation+'}\nexport -f sw_vers uname create-dmg\nexport PYTHON="$TEST_PY"\nsource "$ENTRY" '+args+'\n'
 env['TEST_HOST']=host
 env['WTS_DMG_SUFFIX']=suffix
 result=subprocess.run([bash,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=15)
 return result,marker

def test_standalone_packager_refuses_unsupported_host(tmp_path):
 result,marker=run_entry(tmp_path)
 assert result.returncode!=0 and not marker.exists(),result.stdout+result.stderr

def test_standalone_packager_requires_native_audit(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',audit=1)
 assert result.returncode!=0 and not marker.exists(),result.stdout+result.stderr

def test_successful_image_builder_without_new_image_is_failure(tmp_path):
 result,_=run_entry(tmp_path,host='13.7.8')
 assert result.returncode!=0,result.stdout+result.stderr


def test_fresh_image_is_copied_audited_once_before_success(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True)
 assert result.returncode==0,result.stdout+result.stderr
 assert marker.exists()
 root=marker.parent
 assert (root/'dist/Whisper Transcriber Suite-x64.dmg').read_bytes()==b'image'
 audit=(root/'copied-audit.args').read_text()
 assert '--manifest\n' in audit and '--verify-python\n' in audit
 assert '--no-gui' not in audit
 assert not list((root/'dist').glob('.wts-dmg.*'))


def test_failed_copied_image_audit_cannot_publish_output(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,copied_audit=1)
 assert result.returncode!=0,result.stdout+result.stderr
 assert marker.exists() and (marker.parent/'copied-audit.args').exists()
 assert not (marker.parent/'dist/Whisper Transcriber Suite-x64.dmg').exists()


@pytest.mark.parametrize('mutation',['audit','builder'])
def test_source_changes_cannot_escape_immutable_manifest(tmp_path,mutation):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,mutation=mutation)
 assert result.returncode!=0,result.stdout+result.stderr
 assert not (marker.parent/'dist/Whisper Transcriber Suite-x64.dmg').exists()
 assert not (marker.parent/'copied-audit.args').exists()


def test_explicit_no_gui_stays_packaging_only(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,args='--no-gui')
 assert result.returncode==0,result.stdout+result.stderr
 assert '--no-gui' in (marker.parent/'copied-audit.args').read_text()
 assert 'not release validated' in result.stdout


def test_preexisting_image_is_preserved_without_running_builder(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,existing=True)
 assert result.returncode!=0,result.stdout+result.stderr
 assert not marker.exists()
 assert (marker.parent/'dist/Whisper Transcriber Suite-x64.dmg').read_bytes()==b'previous image'


def test_universal_label_requires_both_slices_before_building(tmp_path):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,suffix='universal',thin=True)
 assert result.returncode!=0 and not marker.exists(),result.stdout+result.stderr
 assert (marker.parent/'native-audit.args').read_text().splitlines()==['universal2']


@pytest.mark.parametrize('suffix,wanted',[('x64','x86_64'),('arm64','arm64'),('universal','universal2')])
def test_image_suffix_drives_source_and_copy_architecture_audits(tmp_path,suffix,wanted):
 result,marker=run_entry(tmp_path,host='13.7.8',image=True,suffix=suffix)
 assert result.returncode==0,result.stdout+result.stderr
 assert (marker.parent/'native-audit.args').read_text().splitlines()==[wanted]
 arguments=(marker.parent/'copied-audit.args').read_text().splitlines()
 assert arguments[arguments.index('--arch')+1]==wanted


@pytest.mark.parametrize('copied',[False,True],ids=['reference','copied-image'])
@pytest.mark.parametrize('wanted',[None,'x86_64','arm64','universal2'])
def test_real_image_audit_uses_requested_architecture_at_each_native_gate(tmp_path,copied,wanted):
 bash=_find_bash()
 if bash is None:pytest.skip('A working Bash is required')
 tools=tmp_path/'tools';tools.mkdir()
 shutil.copyfile(SPEC.with_name('test_dmg.sh'),tools/'test_dmg.sh')
 # Stop at the real script's strict native gate, before any CLI/GUI launch.
 (tools/'verify_mac_bundle.sh').write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$2" > "$ARCH_LOG"\nexit 77\n')
 image=tmp_path/'image.dmg';image.write_bytes(b'fixture')
 fixture=tmp_path/'Whisper Transcriber Suite.app';fixture.mkdir()
 log=tmp_path/'arch.log'
 env=os.environ.copy()
 env.update(ENTRY=str(tools/'test_dmg.sh').replace('\\','/'),IMAGE=str(image).replace('\\','/'),
            FIXTURE=str(fixture).replace('\\','/'),ARCH_LOG=str(log).replace('\\','/'))
 options=' --manifest fixture.json' if copied else ''
 if wanted is not None:options+=' --arch '+wanted
 code='''uname() { echo x86_64; }
sw_vers() { echo 13.7.8; }
python_stub() { return 0; }
hdiutil() {
  if [ "$1" = attach ]; then
    while [ "$#" -gt 0 ]; do
      if [ "$1" = -mountpoint ]; then cp -R "$FIXTURE" "$2/"; return 0; fi
      shift
    done
  fi
}
export -f uname sw_vers python_stub hdiutil
export PYTHON=python_stub
source "$ENTRY" "$IMAGE" --no-gui'''+options+'\n'
 result=subprocess.run([bash,'-c',code],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=15)
 assert result.returncode!=0,result.stdout+result.stderr
 assert log.exists(),result.stdout+result.stderr
 assert log.read_text().splitlines()==[wanted or 'x86_64']
