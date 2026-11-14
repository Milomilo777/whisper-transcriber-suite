"""Compile each unmodified installer script; never execute an installer."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.smoke.inno_prerequisites import inno_compiler

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows-only Inno smoke gate')


@pytest.mark.parametrize('installer', ['installer_embed.iss', 'installer.iss'])
def test_complete_installer_script_compiles_with_fixture_payload(tmp_path, installer, inno_compiler):
    # Keep all directives and Pascal code intact. Only the packaged application
    # bytes are synthetic: this checks compilation, not installation or launch.
    script = tmp_path / installer
    script.write_bytes((ROOT / installer).read_bytes())
    shutil.copytree(ROOT / 'assets', tmp_path / 'assets')
    for relative in ('embed_build', 'dist_onedir/WhisperTranscriberSuite'):
        payload = tmp_path / relative
        payload.mkdir(parents=True)
        (payload / 'compile-fixture.txt').write_text('Compile-only fixture.\n')
    result = subprocess.run(
        [str(inno_compiler), '/Qp', '/O' + str(tmp_path / 'output'), str(script)],
        cwd=tmp_path, capture_output=True, timeout=45,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors='replace')
    assert list((tmp_path / 'output').glob('*.exe'))
