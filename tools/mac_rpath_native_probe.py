"""Native-only universal2 fixture diagnostic; never changes a candidate app."""
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback

PIN = 'b78593fdf4db419f96deb1c40be0455f35ab86d3'
SOURCE = Path(__file__).with_name('mac_rpath_native_source')
A = '/opt/wts-rpath-native-A'
B = '/opt/wts-rpath-native-B'
RELATIVE = '@loader_path'
SYSTEM = '/usr/lib'


class NotExercised(RuntimeError):
    """The native linker did not emit the necessary branch-covering fixture."""


def verify_snapshot(source=SOURCE):
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    names = {'repair_bundle_rpaths.py', 'check_bundle_paths.py', 'list_macho.py'}
    if manifest.get('source_commit') != PIN or set(manifest.get('files', {})) != names:
        raise ValueError('Invalid snapshot source pin or file inventory')
    for name, expected in manifest['files'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Snapshot SHA256 mismatch: ' + name)
    return manifest


def load_snapshot():
    verify_snapshot()
    # This runs in its own diagnostic process, apart from the app/observer.
    sys.path.insert(0, str(SOURCE))
    for name in ('repair_bundle_rpaths', 'check_bundle_paths', 'list_macho'):
        existing = sys.modules.get(name)
        if existing is not None and Path(existing.__file__).resolve() != (SOURCE / (name + '.py')).resolve():
            raise ValueError('Unexpected preloaded source module: ' + name)
    return importlib.import_module('repair_bundle_rpaths')


class Recorder:
    """Record every real native command, including failing commands, immediately."""
    def __init__(self, out, *, run=None):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run = subprocess.run if run is None else run
        self.signature_observations = []
        self.phase = 'initial'

    def __call__(self, argv, **kwargs):
        argv = list(map(str, argv))
        check = kwargs.pop('check', False)
        kwargs.setdefault('capture_output', True)
        kwargs.setdefault('text', True)
        kwargs.setdefault('timeout', 60)
        start = time.monotonic()
        readable = lambda value: value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
        try:
            result = self.run(argv, check=False, **kwargs)
            event = dict(argv=argv, phase=self.phase, returncode=result.returncode, stdout=result.stdout,
                         stderr=result.stderr, seconds=time.monotonic() - start)
        except Exception as error:
            event = dict(argv=argv, phase=self.phase, returncode=None, stdout=readable(getattr(error, 'stdout', None)),
                         stderr=readable(getattr(error, 'stderr', None)), error=repr(error),
                         seconds=time.monotonic() - start)
            with (self.out / 'commands.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n')
            raise
        with (self.out / 'commands.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, argv, result.stdout, result.stderr)
        if Path(argv[0]).name == 'install_name_tool' and result.returncode == 0:
            # Observe stale signatures after the real staged edit, before the
            # exact repair source performs its final ad-hoc re-signing.
            signature = self(['/usr/bin/codesign', '--verify', '--strict', '--all-architectures', argv[-1]])
            self.signature_observations.append(dict(path=argv[-1], returncode=signature.returncode,
                                                    stdout=signature.stdout, stderr=signature.stderr))
        return result


def summarize(records):
    result = {}
    for _path, arch, description, links, loads in records:
        if arch in result:
            raise ValueError('Fixture has multiple binaries for one architecture')
        paths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset \d+\)', loads)
        result[arch] = dict(description=description, rpaths=paths,
                            rpath_counts=dict(Counter(paths)), dependencies=links.splitlines()[1:])
    return result


def require_fixture(before):
    if set(before) != {'x86_64', 'arm64'}:
        raise NotExercised('Fixture did not retain both required architectures')
    expected = {'x86_64': Counter({A: 2, B: 1}), 'arm64': Counter({A: 1})}
    for arch, row in before.items():
        actual = Counter(value for value in row['rpaths'] if value in (A, B))
        if actual != expected[arch] or RELATIVE not in row['rpaths'] or SYSTEM not in row['rpaths']:
            raise NotExercised('Native linker did not preserve duplicate/asymmetric vendor rpaths: ' + arch)


def require_result(before, after):
    if set(after) != {'x86_64', 'arm64'}:
        raise ValueError('Repair lost a required architecture')
    for arch, row in after.items():
        if any(value in (A, B) for value in row['rpaths']):
            raise ValueError('Repair left a vendor rpath: ' + arch)
        expected = [value for value in before[arch]['rpaths'] if value not in (A, B)]
        if row['rpaths'] != expected or row['dependencies'] != before[arch]['dependencies']:
            raise ValueError('Repair changed retained rpaths or dependency install names: ' + arch)


def require_native_branch(events, library):
    commands = [event['argv'] for event in events if event.get('returncode') == 0]
    extractions = [argv for argv in commands if Path(argv[0]).name == 'lipo' and '-thin' in argv]
    arches = [argv[argv.index('-thin') + 1] for argv in extractions]
    edits = [argv for argv in commands if Path(argv[0]).name == 'install_name_tool']
    merges = [argv for argv in commands if Path(argv[0]).name == 'lipo' and '-create' in argv
              and '.rpath-' in argv[-1]]
    if (Counter(arches) != Counter({'x86_64': 1, 'arm64': 1}) or len(merges) != 1
            or len(edits) != 3 or any(argv[-1] == str(library) or '.rpath-' not in argv[-1] for argv in edits)):
        raise ValueError('Recorded real commands do not establish the required staged universal2 branch')
    return dict(thin_architectures=arches, staged_merge_count=len(merges), staged_edit_count=len(edits))


def run_probe(out, *, host_system=None, run=None):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = dict(verdict='RUNNING', source_commit=PIN, native_case_pass=False, fixture_exercised=False,
                  host=dict(system=host_system or platform.system(), machine=platform.machine(),
                            platform=platform.platform(), python=sys.version))
    def save():
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    save()
    recorder = Recorder(out, run=run)
    try:
        result['snapshot'] = verify_snapshot()
        if result['host']['system'] != 'Darwin':
            raise NotExercised('This native fixture requires Darwin; no tool was launched')
        repair = load_snapshot()
        def command(tool, *args):
            return recorder(['/usr/bin/' + tool, *map(str, args)], check=True).stdout
        result['native_versions'] = {
            'uname': command('uname', '-a'), 'macos': command('sw_vers'),
            'clang': command('xcrun', 'clang', '--version'), 'sdk': command('xcrun', '--show-sdk-path'),
        }
        result['fixture_attempts'] = []
        def build_fixture(label, classic=False):
            recorder.phase = 'fixture-' + label
            attempt = dict(linker=label, verdict='RUNNING')
            result['fixture_attempts'].append(attempt)
            save()
            try:
                build = out / 'fixture-build' / label
                build.mkdir(parents=True)
                bundle = out / ('Universal2 Rpath Fixture ' + label + '.app')
                library = bundle / 'Contents/Frameworks/libprobe.dylib'
                library.parent.mkdir(parents=True)
                source = build / 'probe.c'
                source.write_text('int native_rpath_probe(void) { return 42; }\n', encoding='utf-8')
                parts = []
                for arch, vendor in [('x86_64', [A, A, B]), ('arm64', [A])]:
                    part = build / (arch + '.dylib')
                    arguments = ['clang', '-arch', arch, '-dynamiclib', source, '-o', part,
                                 '-Wl,-install_name,@rpath/libprobe.dylib', '-Wl,-headerpad_max_install_names']
                    if classic:
                        arguments.append('-Wl,-ld_classic')
                    arguments += ['-Wl,-rpath,' + value for value in [RELATIVE, SYSTEM, *vendor]]
                    command('xcrun', *arguments)
                    parts.append(part)
                command('lipo', '-create', *parts, '-output', library)
                command('codesign', '--force', '--sign', '-', library)
                command('codesign', '--verify', '--strict', '--all-architectures', library)
                attempt['initial_signature'] = 'verified strict all architectures after ad-hoc signing'
                attempt['before'] = summarize(repair._inspect(bundle.resolve(), command))
                attempt['verdict'] = 'INSPECTED'
                save()
                return bundle, library, attempt
            except Exception as error:
                attempt.update(verdict='FAIL', reason=str(error))
                save()
                raise
        bundle, library, attempt = build_fixture('default')
        try:
            require_fixture(attempt['before'])
        except NotExercised as error:
            attempt.update(verdict='NOT_EXERCISED', reason=str(error))
            before = attempt['before']
            # Retry only the observed duplicate-normalization shape. Missing
            # slices or other unexpected fixture changes are not reinterpreted.
            normalized = (set(before) == {'x86_64', 'arm64'}
                and Counter(value for value in before['x86_64']['rpaths'] if value in (A, B)) == Counter({A: 1, B: 1})
                and Counter(value for value in before['arm64']['rpaths'] if value in (A, B)) == Counter({A: 1})
                and all(RELATIVE in row['rpaths'] and SYSTEM in row['rpaths'] for row in before.values()))
            if not normalized:
                raise
            result['fallback_reason'] = 'Default linker normalized the repeated vendor rpath'
            save()
            try:
                bundle, library, attempt = build_fixture('classic', classic=True)
            except Exception as retry_error:
                raise NotExercised('Classic linker fixture unavailable: ' + str(retry_error)) from retry_error
            try:
                require_fixture(attempt['before'])
            except NotExercised as retry_error:
                attempt.update(verdict='NOT_EXERCISED', reason=str(retry_error))
                raise
        attempt['verdict'] = 'EXERCISED'
        result['selected_fixture'] = attempt['linker']
        result['before'] = attempt['before']
        result['initial_signature'] = attempt['initial_signature']
        result['fixture_exercised'] = True
        save()
        recorder.phase = 'repair'
        result['repaired_files'] = repair.repair_bundle(bundle, run=recorder)
        recorder.phase = 'post-repair'
        result['after'] = summarize(repair._inspect(bundle.resolve(), command))
        require_result(result['before'], result['after'])
        if result['repaired_files'] != 1 or not recorder.signature_observations:
            raise ValueError('Expected one actual staged native edit with signature observations')
        events = [json.loads(line) for line in (out / 'commands.jsonl').read_text(encoding='utf-8').splitlines()]
        result['native_branch'] = require_native_branch([event for event in events if event.get('phase') == 'repair'], library)
        command('codesign', '--verify', '--strict', '--all-architectures', library)
        result.update(verdict='PASS', native_case_pass=True,
                      final_signature='verified strict all architectures')
    except NotExercised as error:
        result.update(verdict='NOT_EXERCISED', reason=str(error))
    except Exception as error:
        result.update(verdict='FAIL', reason=str(error), traceback=traceback.format_exc())
    finally:
        result['post_edit_signature_observations'] = recorder.signature_observations
        save()
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: mac_rpath_native_probe.py OUTPUT_DIRECTORY')
    outcome = run_probe(Path(sys.argv[1]))
    print(json.dumps(dict(verdict=outcome['verdict'], native_case_pass=outcome['native_case_pass'])))
    raise SystemExit(0 if outcome['native_case_pass'] else 1)
