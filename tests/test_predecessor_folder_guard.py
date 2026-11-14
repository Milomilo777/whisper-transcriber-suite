"""Pure source-contract coverage for cross-AppId installation separation."""
from pathlib import Path
from types import SimpleNamespace
import ctypes
import ntpath
import os
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def directory_alias(alias, target):
    if os.name != 'nt':
        alias.symlink_to(target, target_is_directory=True)
        return
    environment = os.environ.copy()
    environment.update(WTS_TEST_ALIAS=str(alias.absolute()), WTS_TEST_TARGET=str(target.resolve()))
    executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:WTS_TEST_ALIAS -Target $env:WTS_TEST_TARGET | Out-Null"
    result = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
        env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    assert alias.resolve() == target.resolve()


def function(source, name):
    match = re.search(r'(?ms)^function ' + name + r'\b.*?^end;', source)
    assert match, name + ' missing'
    return match.group(0)


@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
def test_predecessor_overlap_refused_before_upgrade_success(installer):
    source = (ROOT / installer).read_text(encoding='utf-8')
    prepare = function(source, 'PrepareToInstall')
    assert 'if SharesPredecessorFolder() then begin' in prepare
    refusal = prepare.split('if SharesPredecessorFolder() then begin', 1)[1].split('end;', 1)[0]
    assert "Result := '" in refusal and 'Exit;' in refusal
    assert prepare.index('SharesPredecessorFolder()') < prepare.index('GetUninstallString()')
    lookup = function(source, 'PredecessorFolderOverlaps')
    assert "'Inno Setup: App Path'" in lookup
    assert 'RegQueryStringValue(RootKey,' in lookup
    assert 'if not RegKeyExists(RootKey, UninstPath) then Exit;' in lookup
    assert "if not RegQueryStringValue(RootKey, UninstPath, 'Inno Setup: App Path', OldDir) then begin Result := True; Exit; end;" in lookup
    assert 'Exec(' not in prepare and 'DelTree(' not in prepare


@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
@pytest.mark.parametrize('old,new,expected', [
    (r'C:\Apps\WhisperProject', r'C:\Apps\WhisperProject', True),
    (r'C:\Apps\WhisperProject', 'c:\\apps\\WHISPERPROJECT\\', True),
    (r'C:\Apps\WhisperProject', r'C:\Apps\WhisperProject\Suite', True),
    (r'C:\Apps\WhisperProject\Old', r'C:\Apps\WhisperProject', True),
    (r'C:\Apps\WhisperProject', r'C:\Apps\WhisperProjectSuite', False),
    (r'C:\Apps\WhisperProject', r'C:\Apps\WhisperTranscriberSuite', False),
    (r'C:\Apps\WhisperProject', r'C:\Apps\Other\..\WhisperProject', True),
])
def test_overlap_comparison_uses_component_boundaries(installer, old, new, expected):
    """Evaluate only the actual pure Pos expression; not an Inno runtime claim."""
    source = (ROOT / installer).read_text(encoding='utf-8')
    guard = function(source, 'PredecessorFolderOverlaps')
    assert " + OldAppId + '_is1'" in guard
    assert "if OldDir = '' then begin Result := True; Exit; end;" in guard
    assert 'CanonicalPredecessorFolder(OldDir, OldPhysical)' in guard
    assert 'OldDir := OldPhysical;' in guard
    assert "CanonicalPredecessorFolder(ExpandConstant('{app}'), NewDir)" in guard
    assert 'Result := PredecessorPathsOverlap(OldDir, NewDir);' in guard
    canonical = lambda p: ntpath.normpath(p).rstrip('\\') + '\\'
    assert paths_overlap(source, canonical(old), canonical(new)) is expected



@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
def test_registry_views_cannot_mask_each_others_predecessor_folder(installer):
    guard = function((ROOT / installer).read_text(encoding='utf-8'), 'SharesPredecessorFolder')
    assert 'PredecessorFolderOverlaps(HKLM)' in guard
    assert 'PredecessorFolderOverlaps(HKLM32)' in guard


@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
@pytest.mark.parametrize('views', [
    {'HKLM': r'C:\Other', 'HKLM32': r'C:\Apps\WhisperProject'},
    {'HKLM': r'C:\Apps\WhisperProject', 'HKLM32': r'C:\Other'},
    {'HKLM32': r'C:\Apps\WhisperProject'},
])
def test_each_registered_view_contributes_to_refusal(installer, views):
    """Evaluate actual guard call order without accessing either registry hive."""
    source = (ROOT / installer).read_text(encoding='utf-8')
    guard = function(source, 'SharesPredecessorFolder')
    calls = re.findall(r'PredecessorFolderOverlaps\((HKLM32|HKLM)\)', guard)
    assert calls == ['HKLM', 'HKLM32']
    target = r'C:\Apps\WhisperProject'
    assert any(views.get(view) == target for view in calls)


def test_physical_path_resolver_contract_is_identical_in_both_installers():
    values = []
    for installer in ('installer.iss', 'installer_embed.iss'):
        source = (ROOT / installer).read_text(encoding='utf-8')
        resolver = function(source, 'CanonicalPredecessorFolder')
        assert 'PredecessorOpenPath(Current, 0, 7, 0, 3, $02000000, 0)' in resolver
        assert 'PredecessorFinalPath(Handle, Buffer, Length(Buffer), 2)' in resolver
        assert 'if (Error <> 2) and (Error <> 3) then Exit;' in resolver
        assert 'if Attributes <> $FFFFFFFF then Exit;' in resolver
        assert 'Info.Attributes and FILE_ATTRIBUTE_DIRECTORY' in resolver
        assert 'finally\n        PredecessorClosePath(Handle);' in resolver
        assert "Suffix := Leaf + '\\' + Suffix;" in resolver
        guard = function(source, 'PredecessorFolderOverlaps')
        for call in ('CanonicalPredecessorFolder(OldDir, OldPhysical)',
                     "CanonicalPredecessorFolder(ExpandConstant('{app}'), NewDir)"):
            assert 'if not ' + call + ' then begin Result := True; Exit; end;' in guard
        assert "if (OldNamespace = '') or (NewNamespace = '') then begin Result := True; Exit; end;" in guard
        assert '(PredecessorCompareNames(OldNamespace, Length(OldNamespace), NewNamespace, Length(NewNamespace), 1) <> 2) then begin Result := True; Exit; end;' in guard
        assert "Pos('\\device\\mup\\', OldNamespace)" in guard
        assert "Pos('\\device\\mup\\', NewNamespace)" in guard
        for api in ('CreateFileW', 'GetFinalPathNameByHandleW', 'GetFileInformationByHandle',
                    'CloseHandle', 'GetFileAttributesW', 'GetLastError', 'GetDriveTypeW', 'CompareStringOrdinal'):
            assert "external '" + api + '@kernel32.dll stdcall' in source
        values.append(resolver + function(source, 'PredecessorNamespace') + function(source, 'PredecessorPathsOverlap'))
    assert values[0] == values[1]


class DirectoryMetadata:
    """Actual read-only directory metadata; no installer or registry execution."""
    def __init__(self):
        if os.name != 'nt':
            return
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
            wintypes.DWORD, wintypes.DWORD]
        self.kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        self.kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        self.kernel.GetFileAttributesW.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        self.kernel.GetDriveTypeW.restype = wintypes.DWORD
        self.kernel.CompareStringOrdinal.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int]
        self.kernel.CompareStringOrdinal.restype = ctypes.c_int
        class FileInfo(ctypes.Structure):
            _fields_ = [('attributes', ctypes.c_uint32), ('times', ctypes.c_uint32 * 6),
                        ('remaining', ctypes.c_uint32 * 6)]
        self.FileInfo = FileInfo
        self.kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
        self.kernel.GetFileInformationByHandle.restype = wintypes.BOOL

    def open(self, path):
        if os.name != 'nt':
            try:
                if not Path(path).is_dir():
                    Path(path).stat()
                    return None, 5
                return path, 0
            except FileNotFoundError:
                return None, 2
            except NotADirectoryError:
                return None, 5
        handle = self.kernel.CreateFileW(path, 0, 7, None, 3, 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            return None, ctypes.get_last_error()
        return handle, 0

    def final(self, handle):
        if os.name != 'nt':
            return '\\Device\\portable' + str(Path(handle).resolve(strict=True)).replace('/', '\\')
        info = self.FileInfo()
        if not self.kernel.GetFileInformationByHandle(handle, ctypes.byref(info)) or not info.attributes & 16:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        count = self.kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 2)
        return buffer.value if 0 < count < len(buffer) else None

    def attributes(self, path):
        if os.name != 'nt':
            try:
                Path(path).lstat()
                return 16, 0
            except FileNotFoundError:
                return None, 2
            except NotADirectoryError:
                return None, 5
        attributes = self.kernel.GetFileAttributesW(path)
        return (None, ctypes.get_last_error()) if attributes == 0xFFFFFFFF else (attributes, 0)

    def close(self, handle):
        if os.name == 'nt':
            assert self.kernel.CloseHandle(handle)

    def compare(self, first, first_length, second, second_length):
        if os.name == 'nt':
            return self.kernel.CompareStringOrdinal(first, first_length, second, second_length, 1)
        def prefix(text, count):
            return text if count < 0 else text.encode('utf-16-le', 'surrogatepass')[:count * 2].decode('utf-16-le', 'surrogatepass')
        # Model only these source-control examples off Windows; the Windows
        # branch above is the real ordinal API, not Python's Unicode folding.
        a, b = prefix(first, first_length).lower(), prefix(second, second_length).lower()
        return 2 if a == b else 1 if a < b else 3

    def drive_type(self, path):
        if os.name != 'nt':
            return 3
        root = ntpath.splitdrive(str(path))[0] + '\\'
        return self.kernel.GetDriveTypeW(root)


@pytest.mark.parametrize('operation', ['open', 'attributes'])
@pytest.mark.parametrize('error,expected', [(FileNotFoundError, 2), (NotADirectoryError, 5)])
def test_portable_metadata_distinguishes_missing_from_file_parent(monkeypatch, operation, error, expected):
    """Exercise POSIX errors even when the test host is Windows."""
    class UnavailablePath:
        def __init__(self, path): pass
        def is_dir(self): return False
        def stat(self): raise error('controlled path lookup')
        def lstat(self): raise error('controlled path lookup')

    monkeypatch.setitem(globals(), 'os', SimpleNamespace(name='posix'))
    monkeypatch.setitem(globals(), 'Path', UnavailablePath)
    assert getattr(DirectoryMetadata(), operation)('ordinary-file/Suite') == (None, expected)


def physical_folder(path, api=None):
    """Model the checked Pascal walk with real handle APIs on Windows.

    Source-contract assertions above pin the API flags and failure branches.
    This does not execute Inno Pascal or establish a native Setup pass.
    """
    api = api or DirectoryMetadata()
    path = str(path)
    paths = ntpath if ntpath.splitdrive(path)[0] else os.path
    current = paths.normpath(path)
    suffix = []
    while current:
        handle, error = api.open(current)
        if handle is not None:
            try:
                final = api.final(handle)
                if not final:
                    return None
                return (final.rstrip('\\/') + '\\' + '\\'.join(suffix)).rstrip('\\') + '\\'
            finally:
                api.close(handle)
        if error not in (2, 3):
            return None
        attributes, error = api.attributes(current)
        if attributes is not None or error not in (2, 3):
            return None
        parent, leaf = paths.dirname(current), paths.basename(current)
        if not parent or not leaf or parent == current:
            return None
        suffix.insert(0, leaf)
        current = parent
    return None


def path_namespace(source, canonical, original, api):
    resolver = function(source, 'PredecessorNamespace')
    assert "if Lowercase(Copy(Canonical, 1, 8)) <> '\\device\\' then Exit;" in resolver
    assert "if (DriveType = 0) or (DriveType = 1) or (DriveType = 4) then Exit;" in resolver
    assert "if (Device = '') or (Device = 'lanmanredirector') or (Device = 'webdavredirector') then Exit;" in resolver
    parts = canonical.split('\\')
    if len(parts) < 4 or [part.lower() for part in parts[:2]] != ['', 'device']:
        return None
    device = parts[2].lower()
    if device == 'mup':
        if len(parts) < 5 or not parts[3] or not parts[4] or any(c in parts[3] for c in ';:'):
            return None
        return '\\device\\mup\\' + parts[3] + '\\' + parts[4] + '\\'
    if api.drive_type(original) in (0, 1, 4) or device in ('', 'lanmanredirector', 'webdavredirector'):
        return None
    return '\\device\\' + device + '\\'


def physical_guard(source, old, new, api=None):
    guard = function(source, 'PredecessorFolderOverlaps')
    assert 'CanonicalPredecessorFolder(OldDir, OldPhysical)' in guard
    assert 'OldDir := OldPhysical;' in guard
    assert "CanonicalPredecessorFolder(ExpandConstant('{app}'), NewDir)" in guard
    api = api or DirectoryMetadata()
    old_raw, new_raw = old, new
    old, new = physical_folder(old, api), physical_folder(new, api)
    if old is None or new is None:
        return True
    old_namespace = path_namespace(source, old, old_raw, api)
    new_namespace = path_namespace(source, new, new_raw, api)
    if not old_namespace or not new_namespace:
        return True
    if (old_namespace.startswith('\\device\\mup\\') or new_namespace.startswith('\\device\\mup\\')) and DirectoryMetadata().compare(old_namespace, -1, new_namespace, -1) != 2:
        return True
    assert 'Result := PredecessorPathsOverlap(OldDir, NewDir);' in guard
    return paths_overlap(source, old, new)


def paths_overlap(source, old, new):
    comparison = function(source, 'PredecessorPathsOverlap')
    assert 'Result := True;' in comparison and 'Result := False;' in comparison
    assert 'SecondLength: Integer; IgnoreCase: Integer): Integer;' in source
    assert 'PredecessorCompareNames(OldDir, Length(OldDir), NewDir, Length(OldDir), 1)' in comparison
    assert 'PredecessorCompareNames(NewDir, Length(NewDir), OldDir, Length(NewDir), 1)' in comparison
    assert comparison.count('if (Comparison <> 1) and (Comparison <> 3) then Exit;') == 2
    api = DirectoryMetadata()
    length = lambda text: len(text.encode('utf-16-le', 'surrogatepass')) // 2
    for prefix, value in ((old, new), (new, old)):
        if length(prefix) <= length(value) and api.compare(prefix, length(prefix), value, length(prefix)) not in (1, 3):
            return True
    return False



@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
@pytest.mark.parametrize('route', ['new-existing', 'new-missing', 'old-alias', 'safe-alias'])
def test_directory_aliases_use_physical_ownership(tmp_path, installer, route):
    old = tmp_path / 'predecessor-α'; old.mkdir()
    assets = old / 'assets'; assets.mkdir()
    outside = tmp_path / 'separate-β'; outside.mkdir()
    alias = tmp_path / 'alias'
    directory_alias(alias, outside if route == 'safe-alias' else assets)
    new = alias / 'Suite' / 'not-created-yet'
    if route == 'new-existing':
        new.mkdir(parents=True)
    if route == 'old-alias':
        old, new = alias, assets / 'Suite' / 'not-created-yet'
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert physical_guard(source, old, new) is (route != 'safe-alias')
    assert alias.resolve() == (outside if route == 'safe-alias' else assets).resolve()


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
def test_broken_directory_alias_is_unknown_and_refused(tmp_path, installer):
    old = tmp_path / 'old'; old.mkdir()
    target = tmp_path / 'target'; target.mkdir()
    alias = tmp_path / 'broken'
    directory_alias(alias, target)
    target.rmdir()  # Only the owned empty fixture target, never user data.
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert physical_guard(source, old, alias / 'Suite')


@pytest.mark.parametrize('error,attributes', [(5, None), (3, 0x410), (3, None)])
def test_unknown_existing_ancestor_never_becomes_a_safe_missing_path(error, attributes):
    class Unknown:
        def open(self, path): return None, error
        def attributes(self, path): return attributes, 5 if attributes is None else 0
    assert physical_folder(r'C:\unresolved\Suite', Unknown()) is None


def test_mapped_and_unc_spellings_share_the_normalized_nt_namespace():
    class Network:
        def open(self, path): return path, 0
        def final(self, handle): return r'\Device\Mup\server\share\old'
        def close(self, handle): pass
    assert physical_folder(r'Z:\old', Network()) == physical_folder(r'\\server\share\old', Network())


def test_short_and_long_unicode_paths_share_the_final_identity(tmp_path, request):
    folder = tmp_path / 'Long predecessor directory α'; folder.mkdir()
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        kernel.GetShortPathNameW.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        count = kernel.GetShortPathNameW(str(folder), buffer, len(buffer))
        assert 0 < count < len(buffer)
        short = buffer.value
        request.node.user_properties.append(('distinct_short_spelling', short != str(folder)))
        assert physical_folder(folder).lower().startswith('\\device\\')
        assert physical_folder(folder) == physical_folder(short)
    else:
        class ShortNames:
            def open(self, path): return path, 0
            def final(self, handle): return r'\Device\Volume\Long predecessor directory α'
            def close(self, handle): pass
        assert physical_folder(r'C:\LONGPR~1', ShortNames()) == physical_folder(
            r'C:\Long predecessor directory α', ShortNames())


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
def test_existing_file_is_not_a_safe_parent_for_a_new_folder(tmp_path, installer):
    old = tmp_path / 'old'; old.mkdir()
    file = tmp_path / 'ordinary-file'; file.write_text('owned fixture')
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert physical_guard(source, old, file / 'Suite')


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
def test_physical_sibling_prefix_is_not_an_overlap(tmp_path, installer):
    old = tmp_path / 'Product'; old.mkdir()
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert not physical_guard(source, old, tmp_path / 'ProductSuite' / 'new')


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
@pytest.mark.parametrize('old_final,new_final,refused', [
    (r'\Device\Mup\server\share\old', r'\Device\Mup\server\share\old\Suite', True),
    (r'\Device\Mup\server\share\old', r'\Device\Mup\server\share\separate', False),
    (r'\Device\Mup\server\share\old', r'\Device\Mup\dns-alias\share\separate', True),
    (r'\Device\Mup\server\share\old', r'\Device\Mup\server\other-share\separate', True),
    (r'\Device\HarddiskVolume3\old', r'\Device\Mup\localhost\share\separate', True),
    (r'\Device\HarddiskVolume3\old', r'\Device\HarddiskVolume4\separate', False),
    (r'\Device\HarddiskVolume3\old', r'\Device\LanmanRedirector\unknown\separate', True),
])
def test_ambiguous_network_namespaces_are_refused_without_network_queries(installer, old_final, new_final, refused):
    old, new = r'C:\old-route', r'Z:\new-route'
    final = {old: old_final, new: new_final}
    class Controlled:
        def open(self, path): return path, 0
        def final(self, handle): return final[handle]
        def close(self, handle): pass
        def drive_type(self, path):
            return 4 if any(word in final[str(path)] for word in ('Mup', 'LanmanRedirector')) else 3
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert physical_guard(source, old, new, Controlled()) is refused


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
@pytest.mark.parametrize('old_leaf,new_leaf,refused', [
    ('Σ-missing', 'σ-missing/Suite', True),
    ('Σ-missing', 'ς-missing/Suite', False),
    ('Σ-missing', 'ς-missing-Suite', False),
    ('😀-missing', '😀-missing/Suite', True),
    ('α-missing', 'α-missing-Suite', False),
])
def test_missing_unicode_tails_use_windows_ordinal_case_rules(tmp_path, installer, old_leaf, new_leaf, refused):
    old, new = tmp_path / old_leaf, tmp_path / new_leaf
    assert not old.exists() and not new.exists()
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert physical_guard(source, old, new) is refused


@pytest.mark.parametrize('unknown', [0, 4])
@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
def test_failed_ordinal_comparison_is_not_treated_as_no_overlap(monkeypatch, unknown, installer):
    monkeypatch.setattr(DirectoryMetadata, 'compare', lambda *args: unknown)
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert paths_overlap(source, 'old\\', 'new\\')


@pytest.mark.parametrize('installer', ['installer.iss', 'installer_embed.iss'])
def test_ordinal_api_receives_literal_numeric_true(installer):
    source = (ROOT / installer).read_text(encoding='utf-8')
    assert 'SecondLength: Integer; IgnoreCase: Integer): Integer;' in source
    calls = [line for line in source.splitlines()
             if 'PredecessorCompareNames(' in line and not line.startswith('function ')]
    numeric_fifth_argument = (
        r'\bPredecessorCompareNames\(\s*\w+\s*,\s*Length\(\w+\)\s*,'
        r'\s*\w+\s*,\s*Length\(\w+\)\s*,\s*1\s*\)'
    )
    assert len(calls) == 3 and all(re.search(numeric_fifth_argument, line) for line in calls)
    assert not any(re.search(r'\bPredecessorCompareNames\([^\n]*,\s*True\s*\)', line)
                   for line in calls)
    if os.name == 'nt':
        api = DirectoryMetadata()
        assert api.kernel.CompareStringOrdinal('A', 1, 'a', 1, 1) == 2
