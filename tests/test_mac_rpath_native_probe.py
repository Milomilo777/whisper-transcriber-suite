"""Offline controls for native diagnostic orchestration; no native tools run."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class NativeRpathProbeTests(unittest.TestCase):
    def test_frozen_source_checkout_preserves_manifest_bytes_with_autocrlf(self):
        """Git checkout must not rewrite the byte-pinned source snapshot."""
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / 'repository'
            repository.mkdir()
            (repository / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            source = Path('tools/mac_rpath_native_source')
            (repository / source).mkdir(parents=True)
            expected = {}
            for path in (ROOT / source).glob('*.py'):
                expected[path.name] = path.read_text(encoding='utf-8').encode('utf-8')
                (repository / source / path.name).write_bytes(expected[path.name])
            def git(*arguments):
                subprocess.run(['git', '-c', 'core.autocrlf=true', '-C', str(repository),
                                *arguments], check=True, capture_output=True)
            git('init', '-q')
            git('add', '.gitattributes', str(source))
            checkout = Path(directory) / 'checkout'
            git('checkout-index', '--all', '--prefix=' + checkout.as_posix() + '/')
            for name, content in expected.items():
                self.assertEqual((checkout / source / name).read_bytes(), content, name)

    def setUp(self):
        path = ROOT / 'tools/mac_rpath_native_probe.py'
        spec = importlib.util.spec_from_file_location('native_rpath_under_test', path)
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)

    def rows(self, *, repaired=False):
        probe = self.probe
        result = []
        for arch, vendor in [('x86_64', [probe.A, probe.A, probe.B]), ('arm64', [probe.A])]:
            paths = [probe.RELATIVE, probe.SYSTEM] + ([] if repaired else vendor)
            loads = ''.join(f'Load command {i}\n cmd LC_RPATH\n cmdsize 48\n path {path} (offset 12)\n'
                            for i, path in enumerate(paths))
            result.append(('libprobe.dylib', arch, 'Mach-O dynamically linked shared library',
                           'fixture:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n', loads))
        return result

    def test_snapshot_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            shutil.copytree(ROOT / 'tools/mac_rpath_native_source', source)
            (source / 'repair_bundle_rpaths.py').write_text('changed fixture', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'snapshot|SHA|hash'):
                self.probe.verify_snapshot(source)

    def test_exact_snapshot_manifest_passes(self):
        manifest = self.probe.verify_snapshot(ROOT / 'tools/mac_rpath_native_source')
        self.assertEqual(manifest['source_commit'], 'b78593fdf4db419f96deb1c40be0455f35ab86d3')

    def test_actual_duplicate_and_asymmetry_are_required(self):
        before = self.probe.summarize(self.rows())
        self.probe.require_fixture(before)
        before['x86_64']['rpaths'].remove(self.probe.A)
        with self.assertRaises(self.probe.NotExercised):
            self.probe.require_fixture(before)

    def test_symmetric_fat_fixture_is_not_claimed_exercised(self):
        before = self.probe.summarize(self.rows())
        before['arm64']['rpaths'] = list(before['x86_64']['rpaths'])
        with self.assertRaises(self.probe.NotExercised):
            self.probe.require_fixture(before)

    def test_final_requires_both_architectures_and_unchanged_relative_paths(self):
        before, after = map(self.probe.summarize, (self.rows(), self.rows(repaired=True)))
        self.probe.require_result(before, after)
        after['arm64']['rpaths'].remove(self.probe.RELATIVE)
        with self.assertRaises(ValueError):
            self.probe.require_result(before, after)
        del after['arm64']
        with self.assertRaises(ValueError):
            self.probe.require_result(before, after)

    def test_changed_dependencies_are_rejected(self):
        before, after = map(self.probe.summarize, (self.rows(), self.rows(repaired=True)))
        after['arm64']['dependencies'] = ['external changed fixture']
        with self.assertRaises(ValueError):
            self.probe.require_result(before, after)

    def test_recorder_preserves_failed_command_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value=SimpleNamespace(returncode=7, stdout='out', stderr='bad native tool'))
            recorder = self.probe.Recorder(Path(directory), run=run)
            with self.assertRaises(subprocess.CalledProcessError):
                recorder(['/usr/bin/lipo', '-archs', 'fixture'], check=True)
            event = json.loads((Path(directory) / 'commands.jsonl').read_text().splitlines()[0])
            self.assertEqual((event['returncode'], event['stdout'], event['stderr']), (7, 'out', 'bad native tool'))
            self.assertEqual(event['argv'], ['/usr/bin/lipo', '-archs', 'fixture'])

    def test_non_darwin_never_launches_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(side_effect=AssertionError('native command on non-Darwin'))
            result = self.probe.run_probe(Path(directory), host_system='Windows', run=run)
            self.assertEqual(result['verdict'], 'NOT_EXERCISED')
            run.assert_not_called()
            self.assertEqual(json.loads((Path(directory) / 'result.json').read_text())['verdict'], 'NOT_EXERCISED')

    def test_timeout_bytes_are_preserved_as_text(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(side_effect=subprocess.TimeoutExpired(['fixture'], 1, output=b'partial', stderr=b'error'))
            recorder = self.probe.Recorder(Path(directory), run=run)
            with self.assertRaises(subprocess.TimeoutExpired):
                recorder(['/usr/bin/lipo', '-archs', 'fixture'])
            event = json.loads((Path(directory) / 'commands.jsonl').read_text())
            self.assertEqual((event['stdout'], event['stderr']), ('partial', 'error'))

    def test_native_branch_requires_actual_staged_commands(self):
        with self.assertRaises(ValueError):
            self.probe.require_native_branch([], Path('/fixture/libprobe.dylib'))

    def test_mocked_darwin_orchestration_calls_snapshot_with_recording_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def repair_bundle(bundle, *, run):
                calls.append((bundle, run))
                library = bundle / 'Contents/Frameworks/libprobe.dylib'
                stage = library.parent / '.rpath-mocked'
                for arch in ('x86_64', 'arm64'):
                    run(['/usr/bin/lipo', str(library), '-thin', arch, '-output', str(stage / arch)], check=True)
                for arch in ('x86_64', 'x86_64', 'arm64'):
                    run(['/usr/bin/install_name_tool', '-delete_rpath', self.probe.A, str(stage / arch)], check=True)
                run(['/usr/bin/lipo', '-create', str(stage / 'x86_64'), str(stage / 'arm64'),
                     '-output', str(stage / 'merged')], check=True)
                return 1
            source = SimpleNamespace(_inspect=Mock(side_effect=[self.rows(), self.rows(repaired=True)]),
                                     repair_bundle=repair_bundle)
            run = Mock(return_value=SimpleNamespace(returncode=0, stdout='mock native version', stderr=''))
            with patch.object(self.probe, 'load_snapshot', return_value=source):
                result = self.probe.run_probe(Path(directory), host_system='Darwin', run=run)
            self.assertEqual(result['verdict'], 'PASS', result.get('reason'))
            self.assertEqual(len(calls), 1)
            self.assertIsInstance(calls[0][1], self.probe.Recorder)
            self.assertEqual(result['native_branch']['staged_edit_count'], 3)
            self.assertEqual(len(result['post_edit_signature_observations']), 3)

    def mock_normalized_probe(self, second_valid, classic_unavailable=False):
        normalized = self.rows()
        path, arch, description, links, loads = normalized[0]
        first = loads.index('Load command 3\n')
        end = loads.index('Load command 4\n')
        normalized[0] = (path, arch, description, links, loads[:first] + loads[end:])
        with tempfile.TemporaryDirectory() as directory:
            inspections = [normalized, self.rows() if second_valid else normalized]
            if second_valid:
                inspections.append(self.rows(repaired=True))
            def repair_bundle(bundle, *, run):
                library = bundle / 'Contents/Frameworks/libprobe.dylib'
                stage = library.parent / '.rpath-mocked'
                for arch in ('x86_64', 'arm64'):
                    run(['/usr/bin/lipo', str(library), '-thin', arch, '-output', str(stage / arch)], check=True)
                for arch in ('x86_64','x86_64','arm64'):
                    run(['/usr/bin/install_name_tool','-delete_rpath',self.probe.A,str(stage / arch)],check=True)
                run(['/usr/bin/lipo','-create',str(stage/'x86_64'),str(stage/'arm64'),'-output',str(stage/'merged')],check=True)
                return 1
            source = SimpleNamespace(_inspect=Mock(side_effect=inspections), repair_bundle=Mock(side_effect=repair_bundle))
            run = Mock(side_effect=lambda argv, **kwargs: SimpleNamespace(
                returncode=7 if classic_unavailable and '-Wl,-ld_classic' in argv else 0,
                stdout='mock native version', stderr='classic unavailable' if classic_unavailable else ''))
            with patch.object(self.probe,'load_snapshot',return_value=source):
                result = self.probe.run_probe(Path(directory),host_system='Darwin',run=run)
            return result, run, source

    def test_normalized_default_retries_valid_classic_fixture(self):
        result, run, source = self.mock_normalized_probe(True)
        self.assertEqual(result['verdict'], 'PASS', result.get('reason'))
        self.assertEqual(len(result['fixture_attempts']), 2)
        self.assertEqual(result['fixture_attempts'][0]['before']['x86_64']['rpath_counts'][self.probe.A], 1)
        self.assertTrue(any('-Wl,-ld_classic' in call.args[0] for call in run.call_args_list))
        self.assertEqual(source.repair_bundle.call_count, 1)

    def test_both_linkers_normalized_remains_not_exercised(self):
        result, run, source = self.mock_normalized_probe(False)
        self.assertEqual(result['verdict'], 'NOT_EXERCISED')
        self.assertEqual(len(result['fixture_attempts']), 2)
        self.assertFalse(result['native_case_pass'])
        source.repair_bundle.assert_not_called()

    def test_unavailable_classic_remains_not_exercised(self):
        result, run, source = self.mock_normalized_probe(False, classic_unavailable=True)
        self.assertEqual(result['verdict'], 'NOT_EXERCISED')
        self.assertEqual(len(result['fixture_attempts']), 2)
        self.assertFalse(result['native_case_pass'])
        source.repair_bundle.assert_not_called()


if __name__ == '__main__':
    unittest.main()
