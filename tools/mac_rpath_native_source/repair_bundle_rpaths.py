"""Remove redundant vendor build-directory rpaths from a completed app bundle.

Only external absolute non-system search paths are removed. Relative dyld tokens and
dependency install names are retained and checked in their actual executable
contexts before any edit and again before the changed binaries are re-signed.
"""
from pathlib import Path, PurePosixPath
from collections import Counter
import os
import posixpath
import re
import subprocess
import sys
import tempfile

from check_bundle_paths import audit_records, rpaths
from list_macho import candidates


def _system(value):
    path = PurePosixPath(posixpath.normpath(value))
    return any(path == base or base in path.parents
               for base in (PurePosixPath('/usr/lib'), PurePosixPath('/System/Library')))


def _external_absolute_rpath(value, bundle):
    if not value.startswith('/') or _system(value):
        return False
    if Path(value).resolve().is_relative_to(bundle):
        return False  # Includes aliases whose canonical target is bundled.
    # A path spelled inside the bundle but escaping through '..' or a symlink
    # is not a vendor cleanup candidate: retain it for the strict audit to fail.
    spelled = Path(Path.cwd().anchor) / value
    return not spelled.is_relative_to(bundle)


def _inspect(bundle, command, paths=None):
    records = []
    for candidate in sorted(candidates(bundle) if paths is None else paths):
        path = candidate.resolve()
        if not path.is_relative_to(bundle):
            raise ValueError('Mach-O candidate leaves the bundle: ' + str(candidate))
        description = command('file', '-b', path)
        if 'compiled Java class' in description:
            continue
        if 'Mach-O' not in description:
            raise ValueError('Unrecognized Mach-O candidate: ' + str(path))
        architectures = command('lipo', '-archs', path).split()
        if (not architectures or len(set(architectures)) != len(architectures)
                or any(not re.fullmatch(r'[A-Za-z0-9_]+', arch) for arch in architectures)):
            raise ValueError('Invalid architecture inspection: ' + str(path))
        for arch in architectures:
            links = command('otool', '-L', '-arch', arch, path)
            loads = command('otool', '-l', '-arch', arch, path)
            if not links.strip() or not re.search(r'\bcmd LC_', loads):
                raise ValueError('Incomplete load-command inspection: ' + str(path))
            if len(re.findall(r'\bcmd LC_RPATH\b', loads)) != len(rpaths(loads)):
                raise ValueError('Unparseable rpath inspection: ' + str(path))
            identities = re.findall(r'cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.*?) \(offset \d+\)', loads)
            for dependency in re.findall(r'^\s+(.+?) \(compatibility version ', links, re.M):
                if dependency not in identities and not dependency.startswith('@') and not _system(dependency):
                    raise ValueError('External dependency cannot be repaired by rpath removal: ' + dependency)
            records.append((str(path), arch, description, links, loads))
    if not records:
        raise ValueError('No native binaries inspected')
    return records


def _without_rpaths(loads, removed):
    kept = []
    for block in re.split(r'(?m)(?=^Load command \d+\r?$)', loads):
        values = rpaths(block)
        if len(values) > 1:
            raise ValueError('Cannot isolate rpath load commands')
        if not values or values[0] not in removed:
            kept.append(block)
    return ''.join(kept)


# Adapted from PyInstaller (https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/utils/osx.py)
# — batch distinct rpath deletions, repeated as required by Apple's tool.
def _delete_paths(path, counts, command):
    # Apple's tool requires each requested path in every slice and removes
    # only its first occurrence. Repeated flags in one command are rejected.
    # https://github.com/apple-oss-distributions/cctools/blob/main/misc/install_name_tool.c
    for occurrence in range(max(counts.values(), default=0)):
        arguments = [arg for value in sorted(counts) if counts[value] > occurrence
                     for arg in ('-delete_rpath', value)]
        command('install_name_tool', *arguments, path)


def _repair_file(path, slices, expected, bundle, command):
    counts = list(slices.values())
    if all(value == counts[0] for value in counts):
        _delete_paths(path, counts[0], command)
        return
    # Standard lipo extraction/reassembly keeps asymmetric universal binaries
    # supported without asking install_name_tool to delete an absent path.
    with tempfile.TemporaryDirectory(prefix='.rpath-', dir=Path(path).parent) as temporary:
        temporary = Path(temporary)
        parts = []
        for arch, removals in slices.items():
            part = temporary / arch
            command('lipo', path, '-thin', arch, '-output', part)
            _delete_paths(part, removals, command)
            parts.append(part)
        merged = temporary / 'merged'
        command('lipo', '-create', *parts, '-output', merged)
        staged = _inspect(bundle, command, [merged])
        semantic = lambda rows: {a: (links.splitlines()[1:], rpaths(loads))
                                 for _p, a, _d, links, loads in rows}
        if semantic(staged) != semantic(expected):
            raise ValueError('Staged universal rpath edit did not match the inspected repair plan')
        # Build-only, before sealing: preserve mode, not extended attributes
        # or an old signature. The changed binary is re-signed below.
        merged.chmod(Path(path).stat().st_mode)
        os.replace(merged, path)


def repair_bundle(bundle, *, run=None):
    if run is None and sys.platform != 'darwin':
        raise RuntimeError('Bundle rpath repair requires macOS native tools')
    run = subprocess.run if run is None else run
    bundle = Path(bundle).resolve(strict=True)
    if not bundle.is_dir():
        raise ValueError('Bundle directory does not exist')

    def command(tool, *args):
        result = run(['/usr/bin/' + tool, *map(str, args)], check=True,
                     capture_output=True, text=True, timeout=60)
        return result.stdout

    before = _inspect(bundle, command)
    planned, expected = {}, []
    for path, arch, description, links, loads in before:
        removed = Counter(value for value in rpaths(loads) if _external_absolute_rpath(value, bundle))
        if removed:
            if Path(path).stat().st_nlink != 1:
                raise ValueError('Refusing to edit a hard-linked binary: ' + path)
            planned.setdefault(path, {})
        expected.append((path, arch, description, links, _without_rpaths(loads, removed)))
    for path, arch, _description, _links, loads in before:
        if path in planned:
            planned[path][arch] = Counter(value for value in rpaths(loads)
                                          if _external_absolute_rpath(value, bundle))
    findings = audit_records(bundle, expected)
    if findings:
        raise ValueError('Rpath removal does not produce a self-contained bundle:\n' + '\n'.join(findings))

    for path, slices in sorted(planned.items()):
        _repair_file(path, slices, [row for row in expected if row[0] == path], bundle, command)
    if not planned:
        return 0
    after = _inspect(bundle, command)
    semantic = lambda rows: {(p, a): (links, rpaths(loads)) for p, a, _d, links, loads in rows}
    if semantic(after) != semantic(expected):
        raise ValueError('Native rpath edit did not match the inspected repair plan')
    findings = audit_records(bundle, after)
    if findings:
        raise ValueError('Repaired dependency contexts failed:\n' + '\n'.join(findings))
    for path in sorted(planned):
        command('codesign', '--force', '--sign', '-', path)
        command('codesign', '--verify', '--strict', path)
    return len(planned)


if __name__ == '__main__':
    count = repair_bundle(sys.argv[1])
    print(f'[mac-spec] repaired vendor rpaths in {count} bundled binaries')
