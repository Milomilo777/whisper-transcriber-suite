"""Tiny offline controls; no macOS app, mount, download or token is used."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

SPEC=importlib.util.spec_from_file_location('retest',Path(__file__).resolve().parents[1]/'tools/mac_dmg_artifact_retest.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)
SHA='a'*40

class ArtifactRetestControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def metadata(self):
        run=dict(id=123,head_sha=SHA,status='completed',conclusion='success',path='.github/workflows/macos-app.yml')
        jobs=dict(total_count=2,jobs=[dict(name=f'Build + test macOS .app/.dmg ({a})',status='completed',conclusion='success') for a in ('x86_64','arm64')])
        row=dict(id=456,name='macos-dmg-x86_64',expired=False,size_in_bytes=123,digest='sha256:'+'b'*64,workflow_run=dict(id=123,head_sha=SHA))
        return run,jobs,dict(total_count=1,artifacts=[row])
    def test_inputs_reject_bad_source(self):
        with self.assertRaises(ValueError):m.validate_inputs('123','master','b'*64,'c'*64)
    def test_inputs_require_both_hashes(self):
        with self.assertRaises(ValueError):m.validate_inputs('123',SHA,'b'*64,'')
    def test_inputs_reject_shell_run_id(self):
        with self.assertRaises(ValueError):m.validate_inputs('123;echo x',SHA,'b'*64,'c'*64)
    def test_actual_run_and_unique_artifact(self):
        row=m.select_artifact(*self.metadata(),123,SHA,'x86_64');self.assertEqual(row['id'],456)
    def test_run_source_mismatch(self):
        r,j,a=self.metadata();r['head_sha']='d'*40
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
    def test_both_build_jobs_must_pass(self):
        r,j,a=self.metadata();j['jobs'][1]['conclusion']='failure'
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
    def test_artifact_source_binding(self):
        r,j,a=self.metadata();a['artifacts'][0]['workflow_run']['head_sha']='d'*40
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
    def test_artifact_unique(self):
        r,j,a=self.metadata();a['artifacts']*=2;a['total_count']=2
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
    def test_artifact_digest_required(self):
        r,j,a=self.metadata();a['artifacts'][0]['digest']=''
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
    def archive(self,names):
        path=self.root/'a.zip'
        with zipfile.ZipFile(path,'w') as z:
            for name in names:z.writestr(name,b'not executable DMG fixture')
        return path
    def test_zip_exact_one_regular_dmg(self):
        p=self.archive(['dist/app.dmg']);out=self.root/'artifact.dmg';m.extract_verified(p,out,hashlib.sha256(b'not executable DMG fixture').hexdigest());self.assertEqual(out.read_bytes(),b'not executable DMG fixture')
    def test_zip_unsafe_names(self):
        for name in ('../app.dmg','/app.dmg','C:/app.dmg','x\\app.dmg','dist/../app.dmg','dist/./app.dmg'):
            info=zipfile.ZipInfo('fixture.dmg');info.filename=name;info.orig_filename=name;info.file_size=1
            with self.assertRaises(ValueError):m.dmg_entry([info])
    def test_zip_symlink(self):
        info=zipfile.ZipInfo('app.dmg');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
        with self.assertRaises(ValueError):m.dmg_entry([info])
    def test_zip_extra_regular_file(self):
        p=self.archive(['app.dmg','other.txt'])
        with zipfile.ZipFile(p) as z,self.assertRaises(ValueError):m.dmg_entry(z.infolist())
    def test_inner_hash_before_native(self):
        p=self.archive(['app.dmg'])
        with self.assertRaises(ValueError):m.extract_verified(p,self.root/'out.dmg','0'*64)
    def test_native_command_has_gui_and_candidate_manifest(self):
        command=m.contract_command(Path('/candidate'),Path('/cache/a.dmg'),Path('/report/copy.json'),'/python3','arm64')
        self.assertNotIn('--no-gui',command);self.assertEqual(command[-2:],['--arch','arm64']);self.assertIn('--manifest',command)
    def test_mount_record_must_match_owned_path(self):
        data=plistlib.dumps({'system-entities':[{'mount-point':'/foreign','dev-entry':'/dev/disk2s1'}]})
        with self.assertRaises(ValueError):m.owned_mount(data,Path('/owned'))
    def test_success_requires_positive_marker_and_zero(self):
        with self.assertRaises(ValueError):m.require_contract_success(1,'DMG TEST PASSED')
        with self.assertRaises(ValueError):m.require_contract_success(0,'DMG PACKAGING CHECKS PASSED (GUI not validated)')
        m.require_contract_success(0,'DMG TEST PASSED\n')
    def test_timeout_retained_not_pass(self):
        runner=m.Commands(self.root,backend=Mock(side_effect=m.subprocess.TimeoutExpired(['fixed'],1,output=b'partial',stderr=b'err')))
        with self.assertRaises(TimeoutError):runner.run(['fixed'],1)
        self.assertEqual(runner.records[0]['returncode'],None);self.assertTrue(runner.records[0]['timed_out'])
    def test_nonzero_command_retained(self):
        backend=Mock(return_value=m.subprocess.CompletedProcess(['fixed'],7,b'out',b'err'));runner=m.Commands(self.root,backend=backend)
        with self.assertRaises(ValueError):runner.run(['fixed'],1)
        self.assertEqual(runner.records[0]['returncode'],7)

    def test_cleanup_detaches_only_proved_owned_mount(self):
        image=Path('/cache/a.dmg');mount=Path('/cache/mount')
        attached=plistlib.dumps({'images':[{'image-path':str(image),'system-entities':[{'mount-point':str(mount),'dev-entry':'/dev/disk4s1'}]}]})
        empty=plistlib.dumps({'images':[]})
        commands=Mock();commands.run.side_effect=[attached,b'',empty]
        m.detach_owned(commands,image,mount,'/dev/disk4s1')
        self.assertEqual(commands.run.call_args_list[1].args[0],['hdiutil','detach',str(mount)])
        self.assertNotIn('-force',str(commands.run.call_args_list))

    def test_cleanup_rejects_foreign_mount_without_detach(self):
        commands=Mock();commands.run.return_value=plistlib.dumps({'images':[{'image-path':str(Path('/cache/a.dmg')),'system-entities':[{'mount-point':'/foreign','dev-entry':'/dev/disk4'}]}]})
        with self.assertRaises(ValueError):m.detach_owned(commands,Path('/cache/a.dmg'),Path('/owned'),'/dev/disk4')
        self.assertEqual(commands.run.call_count,1)

    def test_cleanup_remaining_mount_cannot_pass(self):
        data=plistlib.dumps({'images':[{'image-path':str(Path('/cache/a.dmg')),'system-entities':[{'mount-point':str(Path('/owned')),'dev-entry':'/dev/disk4'}]}]})
        commands=Mock();commands.run.side_effect=[data,b'',data]
        with self.assertRaises(ValueError):m.detach_owned(commands,Path('/cache/a.dmg'),Path('/owned'),'/dev/disk4')
        self.assertEqual(commands.run.call_count,3)

    def test_cleanup_observation_timeout_cannot_pass(self):
        commands=Mock();commands.run.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):m.detach_owned(commands,Path('/cache/a.dmg'),Path('/owned'))
        self.assertEqual(commands.run.call_count,1)

    def test_cleanup_alias_image_path_cannot_hide_owned_mount(self):
        image=Path('/cache/a.dmg');mount=Path('/owned')
        aliased=plistlib.dumps({'images':[{'image-path':'/different-spelling/a.dmg',
            'system-entities':[{'mount-point':str(mount),'dev-entry':'/dev/disk4'}]}]})
        commands=Mock();commands.run.return_value=aliased
        with self.assertRaises(ValueError):m.detach_owned(commands,image,mount)
        self.assertFalse(any(call.args[0][:2]==['hdiutil','detach'] for call in commands.run.call_args_list))

    def test_cleanup_final_alias_mount_cannot_pass(self):
        image=Path('/cache/a.dmg');mount=Path('/owned')
        entity={'mount-point':str(mount),'dev-entry':'/dev/disk4'}
        initial=plistlib.dumps({'images':[{'image-path':str(image),'system-entities':[entity]}]})
        aliased=plistlib.dumps({'images':[{'image-path':'/different-spelling/a.dmg','system-entities':[entity]}]})
        commands=Mock();commands.run.side_effect=[initial,b'',aliased]
        with self.assertRaises(ValueError):m.detach_owned(commands,image,mount,'/dev/disk4')

    def test_cleanup_requires_actual_attach_device_and_rejects_replacement(self):
        image=Path('/cache/a.dmg');mount=Path('/owned')
        data=plistlib.dumps({'images':[{'image-path':str(image),'system-entities':[
            {'mount-point':str(mount),'dev-entry':'/dev/disk4'}]}]})
        for device in (None,'/dev/disk99'):
            commands=Mock();commands.run.return_value=data
            with self.subTest(device=device),self.assertRaises(ValueError):m.detach_owned(commands,image,mount,device)
            self.assertEqual(commands.run.call_count,1)

    def test_missing_inventory_is_not_an_empty_inventory(self):
        commands=Mock();commands.run.return_value=plistlib.dumps({})
        with self.assertRaises(ValueError):m.detach_owned(commands,Path('/cache/a.dmg'),Path('/owned'))
        self.assertEqual(commands.run.call_count,1)

    def test_unrelated_foreign_mount_does_not_prevent_owned_cleanup_proof(self):
        data=plistlib.dumps({'images':[{'image-path':'/foreign.dmg','system-entities':[
            {'mount-point':'/foreign-mount','dev-entry':'/dev/disk8'}]}]})
        m.require_unmounted(data,Path('/cache/a.dmg'),Path('/owned'),roots=(Path('/contract'),))

    def test_commands_strip_ephemeral_tokens(self):
        backend=Mock(return_value=m.subprocess.CompletedProcess(['fixed'],0,b'ok',b''))
        m.Commands(self.root,backend).run(['fixed'],env={'GH_TOKEN':'fixture','GITHUB_TOKEN':'fixture','SAFE':'1'})
        self.assertEqual(backend.call_args.kwargs['env'],{'SAFE':'1'})

    def test_api_zip_byte_count_and_digest_controls(self):
        row={'id':456,'size_in_bytes':3,'digest':'sha256:'+hashlib.sha256(b'zip').hexdigest()}
        with patch.object(m.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'zip')
            m.download('owner/repo',row,'fixture',self.root/'ok.zip')
            opener.return_value.open.return_value=io.BytesIO(b'bad')
            with self.assertRaises(ValueError):m.download('owner/repo',row,'fixture',self.root/'bad.zip')
            opener.return_value.open.return_value=io.BytesIO(b'zipp')
            with self.assertRaises(ValueError):m.download('owner/repo',row,'fixture',self.root/'long.zip')

    def test_expired_and_truncated_api_fail(self):
        r,j,a=self.metadata();a['artifacts'][0]['expired']=True
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')
        r,j,a=self.metadata();j['total_count']=3
        with self.assertRaises(ValueError):m.select_artifact(r,j,a,123,SHA,'x86_64')

    def test_candidate_cwd_reaches_actual_backend_and_log(self):
        backend=Mock(return_value=m.subprocess.CompletedProcess(['fixed'],0,b'ok',b''))
        runner=m.Commands(self.root,backend)
        runner.run(['fixed'],cwd=self.root/'candidate')
        self.assertEqual(backend.call_args.kwargs['cwd'],str(self.root/'candidate'))
        self.assertEqual(runner.records[0]['cwd'],str(self.root/'candidate'))

    def test_uncaptured_unreadable_attrs_record_scope_limit(self):
        process=Mock(pid=101);process.uids.return_value=Mock(real=7)
        process.exe.return_value=None;process.cmdline.return_value=None
        ps=Mock();ps.process_iter.return_value=[process];ps.AccessDenied=PermissionError;ps.NoSuchProcess=ProcessLookupError
        facts={};m.observe_process_cleanup([Path('/owned')],facts,ps,7)
        self.assertEqual(facts['post_contract_processes']['unscoped_unreadable_pids'],[101])
        self.assertEqual(process.exe.call_count,1)

    def test_uncaptured_denied_attribute_records_scope_limit(self):
        process=Mock(pid=101);process.uids.return_value=Mock(real=7);process.exe.side_effect=PermissionError()
        ps=Mock();ps.process_iter.return_value=[process];ps.AccessDenied=PermissionError;ps.NoSuchProcess=ProcessLookupError
        facts={};m.observe_process_cleanup([Path('/owned')],facts,ps,7)
        self.assertEqual(facts['post_contract_processes']['unscoped_unreadable_pids'],[101])

    def test_foreign_uid_does_not_need_unreadable_paths(self):
        process=Mock(pid=102);process.uids.return_value=Mock(real=0)
        ps=Mock();ps.process_iter.return_value=[process];ps.AccessDenied=PermissionError;ps.NoSuchProcess=ProcessLookupError
        m.observe_process_cleanup([Path('/owned')],{},ps,7)
        process.exe.assert_not_called()

    def test_mounted_minimum_is_observed_and_bound(self):
        app=self.root/'App.app';(app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion':'12.0'}))
        self.assertEqual(m.mounted_minimum(app,'x86_64'),'12.0')
        with self.assertRaises(ValueError):m.mounted_minimum(app,'arm64')
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({}))
        with self.assertRaises(ValueError):m.mounted_minimum(app,'x86_64')

    def test_mounted_minimum_accepts_actual_three_component_versions(self):
        app=self.root/'App.app';(app/'Contents').mkdir(parents=True)
        for arch,observed in (('x86_64','12.0.0'),('arm64','14.0.0'),('x86_64','12'),('arm64','14')):
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion':observed}))
            with self.subTest(arch=arch):self.assertEqual(m.mounted_minimum(app,arch),observed)

    def test_mounted_minimum_semantic_mismatch_and_malformed_rejected(self):
        app=self.root/'App.app';(app/'Contents').mkdir(parents=True)
        for observed in ('12.0.1','12.0.0.0','12.',' 12.0','12.0beta','+12.0','12..0','１２.０'):
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion':observed}))
            with self.subTest(observed=observed),self.assertRaises(ValueError):m.mounted_minimum(app,'x86_64')

    def test_cleanup_preserves_original_failure_and_phase(self):
        facts={}
        def body():raise ValueError('original')
        def cleanup():raise TimeoutError('cleanup')
        with self.assertRaises(ValueError):m.run_phase(facts,'baseline',body,cleanup)
        self.assertEqual(facts['primary_failure'],{'phase':'baseline','type':'ValueError'})
        self.assertEqual(facts['cleanup_failures'],[{'phase':'baseline','type':'TimeoutError'}])

    def test_contract_owned_identity_receipt_required(self):
        with self.assertRaises(ValueError):m.contract_identities('DMG TEST PASSED\n')
        with self.assertRaises(ValueError):m.contract_identities('{"owned_processes":[]}\n')
        self.assertEqual(m.contract_identities('{"owned_processes":[{"pid":101,"created":12.5}]}\n'),[{'pid':101,'created':12.5}])

    def identity_ps(self):
        ps=Mock();ps.AccessDenied=PermissionError;ps.NoSuchProcess=ProcessLookupError
        return ps

    def test_known_owned_denied_cannot_be_hidden_by_info_none(self):
        ps=self.identity_ps();ps.Process.return_value.info={'pid':101,'exe':None,'cmdline':None};ps.Process.return_value.create_time.side_effect=PermissionError()
        with self.assertRaises(TimeoutError):m.verify_owned_identities([{'pid':101,'created':12.5}],{},ps)

    def test_known_owned_same_creation_alive_rejected(self):
        ps=self.identity_ps();ps.Process.return_value.create_time.return_value=12.5
        with self.assertRaises(ValueError):m.verify_owned_identities([{'pid':101,'created':12.5}],{},ps)

    def test_known_owned_reused_pid_is_old_identity_gone(self):
        ps=self.identity_ps();ps.Process.return_value.create_time.return_value=13.5
        m.verify_owned_identities([{'pid':101,'created':12.5}],{},ps)

    def test_known_owned_missing_is_gone(self):
        ps=self.identity_ps();ps.Process.side_effect=ProcessLookupError()
        m.verify_owned_identities([{'pid':101,'created':12.5}],{},ps)

    def test_post_contract_changed_script_rejected(self):
        candidate=self.root/'candidate';base=candidate/'platform/macos/pyinstaller';base.mkdir(parents=True)
        names=('test_dmg.sh','verify_mac_bundle.sh','bundle_contract.py','copied_gui_process.py')
        for name in names:(base/name).write_text('original')
        commands=Mock();commands.run.side_effect=[(SHA+'\n').encode(),b'']
        before=m.candidate_attestation(candidate,SHA,commands)
        (base/'test_dmg.sh').write_text('changed after successful contract')
        commands.run.side_effect=[(SHA+'\n').encode(),b'']
        with self.assertRaises(ValueError):m.verify_candidate_unchanged(candidate,SHA,commands,before)

    def test_post_contract_changed_tracked_status_rejected(self):
        commands=Mock();commands.run.side_effect=[(SHA+'\n').encode(),b' M platform/macos/pyinstaller/test_dmg.sh\n']
        with self.assertRaises(ValueError):m.verify_candidate_unchanged(self.root,SHA,commands,{})

    def test_mock_native_candidate_context_and_detach_before_contract(self):
        candidate=self.root/'candidate';base=candidate/'platform/macos/pyinstaller';base.mkdir(parents=True)
        for name in ('test_dmg.sh','verify_mac_bundle.sh','bundle_contract.py','copied_gui_process.py'):(base/name).write_text('fixture')
        image=self.root/'image.dmg';image.write_bytes(b'fixture');mount=self.root/'baseline-mount'
        seen=[];state={'attached':False,'contract':False}
        self.native_seen=seen
        def backend(argv,**kwargs):
            seen.append(argv);out=b''
            if argv[0]=='git' or any(str(base) in arg for arg in argv):self.assertEqual(kwargs['cwd'],str(candidate))
            if argv[0]=='git' and 'rev-parse' in argv:out=SHA.encode()
            elif argv==['uname','-m']:out=b'x86_64'
            elif argv[0]=='sw_vers':out=b'15.7'
            elif argv[:2]==['hdiutil','attach']:
                state['attached']=True
                app=mount/'App.app';(app/'Contents').mkdir(parents=True)
                (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion':'12.0'}))
                out=plistlib.dumps({'system-entities':[{'mount-point':str(mount),'dev-entry':'/dev/disk4'}]})
            elif argv[:2]==['hdiutil','info']:
                images=[]
                if state['attached']:
                    reported='/alias/image.dmg' if getattr(self,'alias_at_attach',False) else str(image)
                    images=[{'image-path':reported,'system-entities':[{'mount-point':str(mount),'dev-entry':'/dev/disk4'}]}]
                elif state['contract'] and getattr(self,'alias_after_contract',False):
                    images=[{'image-path':'/alias/image.dmg','system-entities':[{
                        'mount-point':str(self.root/'contract-tmp/wts-dmg.fixture'),'dev-entry':'/dev/disk8'}]}]
                out=plistlib.dumps({'images':images})
            elif argv[:2]==['hdiutil','detach']:state['attached']=False
            elif any(arg.endswith('test_dmg.sh') for arg in argv):
                state['contract']=True
                self.assertTrue(any(row[:2]==['hdiutil','info'] for row in seen))
                self.assertTrue(any(row[:2]==['hdiutil','detach'] for row in seen))
                out=b'{"owned_processes":[{"pid":101,"created":12.5}]}\nDMG TEST PASSED\n'
            return m.subprocess.CompletedProcess(argv,0,out,b'')
        ps=self.identity_ps();ps.Process.side_effect=ProcessLookupError();ps.process_iter.return_value=[]
        facts={'source':SHA,'inner_dmg_sha256':m.digest(image)}
        with patch.object(m.platform,'system',return_value='Darwin'),patch.object(m.os,'getuid',return_value=7,create=True),patch.dict(m.sys.modules,{'psutil':ps}):
            m.native(candidate,image,self.root,'x86_64',m.Commands(self.root,backend),facts)
        self.assertEqual(facts['declared_minimum'],'12.0')
        self.assertIn('candidate_post_contract_attestation',facts)

    def test_native_requires_positive_image_binding_before_bundle_execution(self):
        self.alias_at_attach=True
        with self.assertRaises(ValueError):self.test_mock_native_candidate_context_and_detach_before_contract()
        self.assertFalse(any(row[0]=='codesign' for row in self.native_seen))

    def test_native_final_census_checks_contract_mounts_under_all_image_paths(self):
        self.alias_after_contract=True
        with self.assertRaises(TimeoutError):self.test_mock_native_candidate_context_and_detach_before_contract()

if __name__=='__main__':unittest.main()
