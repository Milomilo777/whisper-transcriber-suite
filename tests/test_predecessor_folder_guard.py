"""Pure source-contract coverage for cross-AppId installation separation."""
from pathlib import Path
import ntpath
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
def test_overlap_expression_uses_component_boundaries(installer, old, new, expected):
    """Evaluate only the actual pure Pos expression; not an Inno runtime claim."""
    source = (ROOT / installer).read_text(encoding='utf-8')
    guard = function(source, 'PredecessorFolderOverlaps')
    assert " + OldAppId + '_is1'" in guard
    assert "if OldDir = '' then Exit;" in guard
    assert 'OldDir := Lowercase(AddBackslash(ExpandFileName(OldDir)));' in guard
    assert "NewDir := Lowercase(AddBackslash(ExpandFileName(ExpandConstant('{app}'))));" in guard
    expression = re.findall(r'Result := (.*);', guard)[-1]
    assert expression == '(Pos(OldDir, NewDir) = 1) or (Pos(NewDir, OldDir) = 1)'
    canonical = lambda p: ntpath.normpath(p).rstrip('\\').lower() + '\\'
    values = {'OldDir': canonical(old), 'NewDir': canonical(new)}
    clauses = re.findall(r'Pos\((OldDir|NewDir), (OldDir|NewDir)\) = 1', expression)
    actual = any(values[haystack].find(values[needle]) == 0 for needle, haystack in clauses)
    assert actual is expected


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
