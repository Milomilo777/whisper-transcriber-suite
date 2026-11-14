"""Check dyld paths using inspected load commands, without loading native code."""
from pathlib import Path
import re
import sys


def rpaths(loads):
    return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset \d+\)', loads)


def inspect_paths(bundle, binary, links, loads, executable_loads='', executable_dir='',
                  inherited_paths=(), resolved=None, search_paths=None):
    bundle = Path(bundle).resolve()
    binary = Path(binary).resolve()
    executable = Path(executable_dir).resolve() if executable_dir else bundle / 'Contents/MacOS'
    errors = []

    def expand(value, loader):
        for token, base in (('@loader_path', loader), ('@executable_path', executable)):
            if value == token or value.startswith(token + '/'):
                return (base / value[len(token):].lstrip('/')).resolve()
        return Path(value).resolve() if value.startswith('/') else None

    def system(path):
        return path is not None and any(path == base or base in path.parents
            for base in (Path('/usr/lib').resolve(), Path('/System/Library').resolve()))

    def safe(path):
        return path is not None and (path == bundle or bundle in path.parents or system(path))

    search = []
    for commands, loader in ((loads, binary.parent), (executable_loads, executable)):
        for value in rpaths(commands):
            path = expand(value, loader)
            if not safe(path):
                errors.append('RPATH leaves the bundle: ' + value)
            else:
                search.append(path)
    search = list(dict.fromkeys(search + list(inherited_paths)))
    if search_paths is not None:
        search_paths.extend(search)
    identities = re.findall(r'cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.*?) \(offset \d+\)', loads)
    for value in re.findall(r'^\s+(.+?) \(compatibility version ', links, re.M):
        if value in identities:
            continue  # otool -L includes a dylib's own install name.
        if value.startswith('@rpath/'):
            candidates = [(base / value[len('@rpath/'):]).resolve() for base in search]
            # dyld searches in order. A later safe copy cannot hide the first
            # existing candidate resolving through an external symlink.
            path = next((path for path in candidates if system(path) or path.is_file()), None)
            if path is None or not safe(path):
                errors.append('DEP unresolved bundle rpath: ' + value)
            elif resolved is not None and not system(path):
                resolved.append(path)
        elif value.startswith('@'):
            path = expand(value, binary.parent)
            if not safe(path) or not (system(path) or path.is_file()):
                errors.append('DEP unresolved or escaping bundle path: ' + value)
            elif resolved is not None and not system(path):
                resolved.append(path)
    return errors


def audit_records(bundle, records):
    """Follow each executable's dependencies with its own dyld context.

    Records are inspected otool replies, not binaries to execute. Libraries
    reached by multiple executables must pass in every reaching context.
    """
    bundle = Path(bundle).resolve()
    indexed = {(Path(path).resolve(), arch): (description, links, loads)
               for path, arch, description, links, loads in records}
    errors, reached, visited = [], set(), set()

    def visit(path, arch, executable, inherited=()):
        key = (path, arch, executable, tuple(inherited))
        if key in visited:
            return
        if len(visited) >= 10000:
            errors.append('DYLD dependency contexts exceed inspection bound')
            return
        visited.add(key)
        reached.add((path, arch))
        if (path, arch) not in indexed:
            errors.append(f'DYLD {path} [{arch}]: dependency slice was not inspected')
            return
        _, links, loads = indexed[path, arch]
        dependencies, search = [], []
        findings = inspect_paths(bundle, path, links, loads, executable_dir=executable.parent,
                                 inherited_paths=inherited, resolved=dependencies, search_paths=search)
        errors.extend(f'DYLD {path} [{arch}] from {executable}: {finding}' for finding in findings)
        for dependency in dependencies:
            visit(dependency, arch, executable, tuple(search))

    for (path, arch), (description, _, _) in indexed.items():
        if 'executable' in description:
            visit(path, arch, path)

    # PyInstaller dynamically imports Python extensions. These two explicit
    # runtime domains are not represented by LC_LOAD_DYLIB graph edges.
    gui = bundle / 'Contents/MacOS/Whisper Transcriber Suite'
    tools = bundle / 'Contents/Frameworks/bin'
    # PyInstaller may move this runtime into Resources and symlink it from
    # Frameworks/bin. Match the same canonical paths used by the index.
    ytdlp = (tools / 'yt-dlp_dist/yt-dlp_macos').resolve()
    for (path, arch), (_, links, loads) in indexed.items():
        runtime = None
        if ytdlp.parent / '_internal' in path.parents:
            runtime = ytdlp
        elif tools not in path.parents and (
                bundle / 'Contents/Frameworks' in path.parents or gui.parent in path.parents):
            if (path, arch) not in reached or path.suffix == '.so':
                runtime = gui
        if runtime is not None and (runtime, arch) in indexed:
            inherited = []
            root_links, root_loads = indexed[runtime, arch][1:]
            inspect_paths(bundle, runtime, root_links, root_loads,
                          executable_dir=runtime.parent, search_paths=inherited)
            visit(path, arch, runtime, tuple(inherited))
        elif (path, arch) in reached:
            continue
        else:
            # Unknown dynamically loaded libraries get no invented executable
            # context. Loader-relative dependencies can still be checked.
            if '@executable_path' in links or '@executable_path' in loads:
                errors.append(f'DYLD {path} [{arch}]: executable context is not established')
            else:
                errors.extend(f'DYLD {path} [{arch}]: {finding}' for finding in
                              inspect_paths(bundle, path, links, loads, executable_dir=path.parent))
    return errors


if __name__ == '__main__':
    if sys.argv[1] == '--records':
        fields = Path(sys.argv[3]).read_bytes().split(b'\0')
        if fields[-1] or (len(fields) - 1) % 5:
            raise SystemExit('DYLD incomplete inspection records')
        values = [value.decode('utf-8') for value in fields[:-1]]
        findings = audit_records(sys.argv[2], [values[i:i + 5] for i in range(0, len(values), 5)])
    else:
        findings = inspect_paths(*sys.argv[1:4], sys.stdin.read(), *sys.argv[4:6])
    for finding in findings:
        print(finding)
    raise SystemExit(bool(findings))
