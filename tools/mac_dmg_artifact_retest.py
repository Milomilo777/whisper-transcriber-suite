"""Pinned artifact-only DMG retest. Mounted manifest is a copy baseline."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

LIMIT = 2 * 1024**3

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def validate_inputs(run, source, intel, arm):
    require(re.fullmatch(r'[1-9][0-9]*', str(run)), 'numeric run ID required')
    require(re.fullmatch(r'[0-9a-f]{40}', source), 'full source SHA required')
    for value in (intel, arm):
        require(re.fullmatch(r'[0-9a-f]{64}', value), 'both inner hashes required')

def select_artifact(run, jobs, artifacts, run_id, source, arch):
    require(arch in ('x86_64', 'arm64'), 'unsupported arch')
    require(run.get('id') == run_id and run.get('head_sha') == source, 'run source mismatch')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'run not successful')
    require(run.get('path') == '.github/workflows/macos-app.yml', 'wrong workflow')
    require(jobs.get('total_count') == len(jobs.get('jobs', [])), 'truncated jobs')
    for a in ('x86_64', 'arm64'):
        rows = [j for j in jobs['jobs'] if j.get('name') == f'Build + test macOS .app/.dmg ({a})']
        require(len(rows) == 1 and rows[0].get('status') == 'completed' and rows[0].get('conclusion') == 'success', 'both source builds must succeed uniquely')
    require(artifacts.get('total_count') == len(artifacts.get('artifacts', [])), 'truncated artifacts')
    rows = [a for a in artifacts['artifacts'] if a.get('name') == f'macos-dmg-{arch}']
    require(len(rows) == 1, 'artifact not unique')
    row = rows[0]
    require(row.get('expired') is False and isinstance(row.get('id'), int), 'invalid artifact')
    require(0 < row.get('size_in_bytes', 0) <= LIMIT, 'invalid artifact size')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', row.get('digest', '')), 'API ZIP digest required')
    binding = row.get('workflow_run', {})
    require(binding.get('id') == run_id and binding.get('head_sha') == source, 'artifact binding mismatch')
    return row

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()

def dmg_entry(entries):
    files = []
    for entry in entries:
        name = entry.filename
        require(entry.orig_filename == name, 'NUL in ZIP name')
        parts = name.rstrip('/').split('/')
        require(name and not name.startswith('/') and '\\' not in name and ':' not in name, 'unsafe ZIP name')
        require(all(p not in ('', '.', '..') and p.rstrip(' .') == p for p in parts), 'unsafe ZIP component')
        require(not any(ord(c) < 32 or ord(c) == 127 for c in name), 'ZIP control character')
        mode = stat.S_IFMT(entry.external_attr >> 16)
        require(mode in (0, stat.S_IFREG, stat.S_IFDIR), 'ZIP special entry')
        require(not entry.flag_bits & 1, 'encrypted ZIP')
        if not entry.is_dir():
            require(mode != stat.S_IFDIR, 'inconsistent directory')
            files.append(entry)
    require(len(files) == 1 and files[0].filename.endswith('.dmg'), 'exactly one regular DMG required')
    require(0 < files[0].file_size <= LIMIT, 'invalid inner size')
    return files[0]

def extract_verified(archive, destination, expected):
    with zipfile.ZipFile(archive) as z:
        entry = dmg_entry(z.infolist())
        count = 0
        with z.open(entry) as src, open(destination, 'xb') as dst:
            for block in iter(lambda: src.read(65536), b''):
                count += len(block)
                require(count <= entry.file_size and count <= LIMIT, 'inner size exceeded')
                dst.write(block)
        require(count == entry.file_size, 'inner truncated')
    require(digest(destination) == expected, 'inner DMG hash mismatch')

class Commands:
    def __init__(self, report, backend=subprocess.run):
        self.report, self.backend, self.records = Path(report), backend, []
    def run(self, argv, timeout=180, env=None, cwd=None):
        child_env = dict(os.environ if env is None else env)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN'):
            child_env.pop(key, None)
        record = dict(argv=list(map(str, argv)), cwd=str(cwd) if cwd else None, returncode=None, timed_out=False)
        self.records.append(record)
        try:
            result = self.backend(record['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=child_env, cwd=record['cwd'], check=False)
            record.update(returncode=result.returncode, stdout=result.stdout.decode('utf-8', 'replace'), stderr=result.stderr.decode('utf-8', 'replace'))
        except subprocess.TimeoutExpired as error:
            record.update(timed_out=True, stdout=(error.output or b'').decode('utf-8', 'replace'), stderr=(error.stderr or b'').decode('utf-8', 'replace'))
            raise TimeoutError('fixed command timed out') from None
        finally:
            (self.report/'commands.json').write_text(json.dumps(self.records, indent=2), encoding='utf-8')
        require(result.returncode == 0, 'fixed command failed; see commands.json')
        return result.stdout

def owned_mount(data, mount):
    rows = [r for r in plistlib.loads(data).get('system-entities', []) if r.get('mount-point') == str(mount)]
    require(len(rows) == 1 and rows[0].get('dev-entry', '').startswith('/dev/disk'), 'owned mount unproved')
    return rows[0]['dev-entry']

def contract_command(candidate, image, manifest, python, arch):
    return ['bash', str(candidate/'platform/macos/pyinstaller/test_dmg.sh'), str(image), '--manifest', str(manifest), '--verify-python', python, '--arch', arch]

def require_contract_success(rc, output):
    require(rc == 0 and 'DMG TEST PASSED' in output.splitlines(), 'positive GUI contract marker required')

def mounted_images(data):
    parsed = plistlib.loads(data)
    require(isinstance(parsed, dict) and isinstance(parsed.get('images'), list), 'mount inventory unavailable')
    images = parsed['images']
    for row in images:
        require(isinstance(row, dict) and isinstance(row.get('image-path'), str)
                and isinstance(row.get('system-entities'), list), 'invalid mount inventory')
        require(all(isinstance(entity, dict) for entity in row['system-entities']), 'invalid mount entities')
    return images


def image_mounts(data, image):
    return [r for r in mounted_images(data) if r['image-path'] == str(image)]


def mount_images(data, mount):
    return [r for r in mounted_images(data) if any(
        entity.get('mount-point') == str(mount) for entity in r['system-entities'])]


def require_image_binding(data, image, mount, device):
    rows = image_mounts(data, image)
    require(len(rows) == 1, 'unique attached image binding required')
    require(owned_mount(plistlib.dumps(rows[0]), mount) == device, 'attached device binding changed')
    owners = mount_images(data, mount)
    require(len(owners) == 1 and owners[0] == rows[0], 'ambiguous owned mount')


def require_unmounted(data, image, mount, roots=()):
    require(not image_mounts(data, image), 'image remains attached')
    for row in mounted_images(data):
        for entity in row['system-entities']:
            point = entity.get('mount-point')
            if point is None:
                continue
            require(isinstance(point, str) and point, 'invalid mount point')
            require(point != str(mount) and not any(
                Path(point).resolve().is_relative_to(Path(root).resolve()) for root in roots),
                'owned mount remains attached under an image alias')

def detach_owned(commands, image, mount, device=None):
    data = commands.run(['hdiutil', 'info', '-plist'])
    rows = image_mounts(data, image)
    if rows:
        require(device is not None, 'actual attachment device proof required')
        require_image_binding(data, image, mount, device)
        commands.run(['hdiutil', 'detach', str(mount)])
    else:
        require(not mount_images(data, mount), 'owned mount image identity unproved')
    require_unmounted(commands.run(['hdiutil', 'info', '-plist']), image, mount)


def mounted_minimum(app, arch):
    with open(app/'Contents/Info.plist', 'rb') as stream:
        observed = plistlib.load(stream).get('LSMinimumSystemVersion')
    require(isinstance(observed, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', observed), 'malformed mounted minimum')
    components = tuple(int(part) for part in observed.split('.'))
    normalized = components + (0,) * (3 - len(components))
    require(normalized == {'x86_64': (12, 0, 0), 'arm64': (14, 0, 0)}[arch], 'mounted declared minimum mismatch')
    return observed


def run_phase(facts, phase, body, cleanup):
    """Preserve original failures even when subsequent cleanup also fails."""
    primary = None
    try:
        body()
    except Exception as error:
        primary = error
        facts['primary_failure'] = {'phase': phase, 'type': type(error).__name__}
    try:
        cleanup()
    except Exception as error:
        facts.setdefault('cleanup_failures', []).append({'phase': phase, 'type': type(error).__name__})
        if primary is None:
            raise TimeoutError('cleanup not established; see structured receipt') from None
    if primary is not None:
        raise primary


def observe_process_cleanup(roots, facts, psutil, uid):
    """Read attributes explicitly: process_iter(attrs) hides AccessDenied as None.

    This census supplements exact contract-owned PID/create-time identities.
    Unreadable uncaptured processes remain an explicit scope limitation.
    """
    alive, uncertain = [], []
    for process in psutil.process_iter():
        try:
            if process.uids().real != uid:
                continue
            exe, argv = process.exe(), process.cmdline()
            if exe is None or argv is None:
                uncertain.append(process.pid)
                continue
            if any(str(root) in value for root in roots for value in [exe] + argv):
                alive.append(process.pid)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            uncertain.append(process.pid)
    facts['post_contract_processes'] = dict(matching_owned_paths=alive, unscoped_unreadable_pids=uncertain)
    facts['process_cleanup_scope'] = 'Captured contract PID/create-time identities plus readable owned-path census; uncaptured inaccessible children cannot be excluded.'
    require(not alive, 'owned-path process still alive')


def contract_identities(output):
    receipts = []
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and 'owned_processes' in row:
            receipts.append(row['owned_processes'])
    require(len(receipts) == 1 and isinstance(receipts[0], list) and receipts[0], 'unique nonempty contract identity receipt required')
    identities = receipts[0]
    for row in identities:
        require(isinstance(row, dict) and type(row.get('pid')) is int and row['pid'] > 1, 'invalid owned PID')
        require(type(row.get('created')) in (int, float) and math.isfinite(row['created']) and row['created'] > 0, 'invalid owned creation time')
    require(len({r['pid'] for r in identities}) == len(identities), 'duplicate owned PID')
    return identities


def verify_owned_identities(identities, facts, psutil):
    observations = []
    facts['captured_identity_exit_observations'] = observations
    for row in identities:
        try:
            created = psutil.Process(row['pid']).create_time()
            require(type(created) in (int, float) and math.isfinite(created), 'invalid observed creation time')
            if created == row['created']:
                observations.append(dict(row, state='SAME_IDENTITY_STILL_ALIVE'))
            require(created != row['created'], 'captured owned identity still alive')
            observations.append(dict(row, state='PID_REUSED_OLD_IDENTITY_GONE'))
        except psutil.NoSuchProcess:
            observations.append(dict(row, state='NO_SUCH_PROCESS'))
        except psutil.AccessDenied:
            observations.append(dict(row, state='ACCESS_DENIED_UNRESOLVED'))
            raise TimeoutError('captured owned identity inaccessible') from None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def api(repository, route, token):
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/{route}', headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

def download(repository, row, token, destination):
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/actions/artifacts/{row["id"]}/zip', headers={'Authorization': f'Bearer {token}'})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    except urllib.error.HTTPError as error:
        require(error.code in (301, 302, 303, 307, 308), 'artifact download refused')
        location = error.headers.get('Location', '')
        require(location.startswith('https://'), 'HTTPS redirect required')
        response = urllib.request.urlopen(location, timeout=60)
    count = 0
    with response, open(destination, 'xb') as target:
        for block in iter(lambda: response.read(65536), b''):
            count += len(block)
            require(count <= row['size_in_bytes'] and count <= LIMIT, 'ZIP size exceeded')
            target.write(block)
    require(count == row['size_in_bytes'], 'ZIP size mismatch')
    require(digest(destination) == row['digest'].split(':')[1], 'ZIP digest mismatch')

def candidate_attestation(candidate, source, commands):
    require(commands.run(['git', '-C', str(candidate), 'rev-parse', 'HEAD'], cwd=candidate).decode().strip() == source, 'candidate source mismatch')
    require(not commands.run(['git', '-C', str(candidate), 'status', '--porcelain', '--untracked-files=no'], cwd=candidate).strip(), 'candidate tracked mutation')
    base = candidate/'platform/macos/pyinstaller'
    return {p.name: digest(p) for p in (base/'test_dmg.sh', base/'verify_mac_bundle.sh', base/'bundle_contract.py', base/'copied_gui_process.py')}


def verify_candidate_unchanged(candidate, source, commands, before):
    require(candidate_attestation(candidate, source, commands) == before, 'candidate scripts changed during contract')


def native(candidate, image, report, arch, commands, facts):
    require(platform.system() == 'Darwin', 'macOS runner required')
    facts['script_hashes'] = candidate_attestation(candidate, facts['source'], commands)
    require(commands.run(['uname', '-m']).decode().strip() == arch, 'host arch mismatch')
    facts['host_os'] = commands.run(['sw_vers', '-productVersion']).decode().strip()
    facts['scope'] = 'Actual host OS only; no older-OS runtime proof. Process liveness is not visible-window rendering proof.'
    base = candidate/'platform/macos/pyinstaller'
    mount = image.parent/'baseline-mount'
    mount.mkdir()
    manifest = report/'mounted-copy-baseline.json'
    ownership = {}
    def baseline():
        data = commands.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', str(mount), '-plist', str(image)])
        ownership['device'] = owned_mount(data, mount)
        require_image_binding(commands.run(['hdiutil', 'info', '-plist']), image, mount, ownership['device'])
        apps = list(mount.glob('*.app'))
        require(len(apps) == 1 and apps[0].is_dir() and not apps[0].is_symlink(), 'unique real app required')
        app = apps[0]
        facts['declared_minimum'] = mounted_minimum(app, arch)
        commands.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)])
        commands.run(['bash', str(base/'verify_mac_bundle.sh'), str(app), arch, sys.executable], cwd=candidate)
        commands.run([sys.executable, str(base/'bundle_contract.py'), 'manifest', str(app), str(manifest)], cwd=candidate)
        commands.run([sys.executable, str(base/'bundle_contract.py'), 'verify', str(app), str(manifest)], cwd=candidate)
        facts['baseline_scope'] = 'COPY_BASELINE_FROM_SELECTED_READONLY_IMAGE_NOT_ORIGINAL_BUILD_MANIFEST'
    run_phase(facts, 'mounted-baseline', baseline, lambda: detach_owned(commands, image, mount, ownership.get('device')))
    env = dict(os.environ)
    temp = image.parent/'contract-tmp'
    temp.mkdir()
    env['TMPDIR'] = str(temp)+'/'
    def contract():
        output = commands.run(contract_command(candidate, image, manifest, sys.executable, arch), 1200, env, cwd=candidate)
        require_contract_success(0, output.decode('utf-8', 'replace'))
        facts['contract_owned_identities'] = contract_identities(output.decode('utf-8', 'replace'))
    def contract_cleanup():
        require_unmounted(commands.run(['hdiutil', 'info', '-plist']), image, mount, roots=(temp,))
        import psutil
        require(bool(facts.get('contract_owned_identities')), 'contract identity proof unavailable')
        verify_owned_identities(facts['contract_owned_identities'], facts, psutil)
        observe_process_cleanup([temp, mount], facts, psutil, os.getuid())
    run_phase(facts, 'copied-dmg-contract', contract, contract_cleanup)
    require(digest(image) == facts['inner_dmg_sha256'], 'DMG changed after native')
    verify_candidate_unchanged(candidate, facts['source'], commands, facts['script_hashes'])
    facts['candidate_post_contract_attestation'] = 'SOURCE_TRACKED_STATUS_AND_SCRIPT_HASHES_UNCHANGED'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-id', 'source', 'intel-sha', 'arm-sha'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--repository')
    parser.add_argument('--arch', choices=('x86_64', 'arm64'))
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    validate_inputs(args.run_id, args.source, args.intel_sha, args.arm_sha)
    if args.validate_only:
        return 0
    require(args.repository and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository), 'repository required')
    require(args.arch and args.candidate and args.output, 'paths and arch required')
    require(platform.system() == 'Darwin', 'macOS runner required')
    args.output.mkdir(parents=True, exist_ok=False)
    facts = dict(verdict='INCONCLUSIVE', source=args.source, run_id=int(args.run_id), repository=args.repository, arch=args.arch, inner_dmg_sha256=args.intel_sha if args.arch == 'x86_64' else args.arm_sha)
    commands = Commands(args.output)
    try:
        token = os.environ.get('GH_TOKEN', '')
        require(bool(token), 'ephemeral token required')
        prefix = f'actions/runs/{args.run_id}'
        row = select_artifact(api(args.repository, prefix, token), api(args.repository, prefix+'/jobs?per_page=100&filter=latest', token), api(args.repository, prefix+'/artifacts?per_page=100', token), int(args.run_id), args.source, args.arch)
        facts['artifact'] = {k: row[k] for k in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run')}
        cache = Path(tempfile.mkdtemp(prefix='pinned-dmg-retest-')).resolve()
        facts['cache'] = str(cache)
        archive, image = cache/'artifact.zip', cache/'artifact.dmg'
        download(args.repository, row, token, archive)
        extract_verified(archive, image, facts['inner_dmg_sha256'])
        facts['zip_and_inner_verified_before_native'] = True
        native(args.candidate.resolve(), image, args.output.resolve(), args.arch, commands, facts)
        facts['verdict'] = 'PASS'
    except Exception as error:
        # Exception values can contain signed URLs: retain type only.
        facts['failure_type'] = type(error).__name__
        facts['verdict'] = 'INCONCLUSIVE' if isinstance(error, TimeoutError) else 'FAIL'
    finally:
        (args.output/'result.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
    return 0 if facts['verdict'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
