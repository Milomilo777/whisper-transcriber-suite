"""Compiler-free checks of the actual shortcut smoke fixture construction."""
import re
from types import SimpleNamespace

import pytest

from tests.smoke import test_inno_shortcut_upgrade as fixture


@pytest.fixture(autouse=True)
def forbid_compiler_or_setup(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Hermetic fixture construction must not execute a process')
    monkeypatch.setattr(fixture, 'subprocess', SimpleNamespace(run=forbidden))


@pytest.mark.parametrize('script_name', ['installer_embed.iss', 'installer.iss'])
@pytest.mark.parametrize('target_kind', ['private', 'commonpf'])
def test_fixture_keeps_real_guard_and_maps_only_cleanup_and_icons(tmp_path, script_name, target_kind):
    source = (fixture.ROOT / script_name).read_text(encoding='utf-8')
    app, menu, desktop, script = fixture.build_shortcut_fixture(tmp_path, script_name, target_kind)
    actual = script.read_text(encoding='utf-8')
    guard = source[source.index('type\n  TPredecessorFileInfo = record\n'):
                   source.index('// Versioned shortcut maintenance.')]
    cleanup = source.split('// Versioned shortcut maintenance.\n', 1)[1].split(
        '// End versioned shortcut maintenance.', 1)[0]
    icons = source.split('[Icons]', 1)[1].split('[Tasks]', 1)[0]

    assert guard in actual
    assert 'TPredecessorFileInfo = record' in actual
    assert 'function SharesPredecessorFolder' in actual
    assert 'PredecessorFolderOverlaps(HKLM32)' in actual
    assert 'procedure CleanupVersionedShortcuts' in actual
    assert len(re.findall(r'\bconst\s+OldAppId\s*=', actual)) == 1
    target = str(app) if target_kind == 'private' else r'{commonpf}\WhisperShortcutReadOnlyFixture'
    for original in (cleanup, icons):
        mapped = original.replace('{app}', target).replace('{group}', str(menu)).replace(
            '{commondesktop}', str(desktop))
        assert mapped in actual
    assert (app / 'python/pythonw.exe').read_bytes() == b'synthetic target, never executed'


@pytest.mark.parametrize('script_name', ['installer_embed.iss', 'installer.iss'])
@pytest.mark.parametrize('anchor,message', [
    ('type\n  TPredecessorFileInfo = record\n', 'Missing predecessor guard'),
    ('// End versioned shortcut maintenance.', 'Missing versioned shortcut cleanup'),
])
def test_missing_guard_or_cleanup_anchor_fails_closed(tmp_path, monkeypatch, script_name, anchor, message):
    source = (fixture.ROOT / script_name).read_text(encoding='utf-8')
    assert source.count(anchor) == 1
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / script_name).write_text(source.replace(anchor, '// removed fixture anchor\n'), encoding='utf-8')
    monkeypatch.setattr(fixture, 'ROOT', scripts)
    target = tmp_path / 'build'
    target.mkdir()

    with pytest.raises(ValueError, match=message):
        fixture.build_shortcut_fixture(target, script_name, 'private')
