"""Prerequisite validation only; never starts compiler or Setup."""
from pathlib import Path
import os
import pytest

def require_file(platform, environ, name, expected_name):
    if platform != 'nt':
        return None
    value = environ.get(name, '')
    path = Path(value)
    if not value or not path.is_file() or path.name.casefold() != expected_name.casefold():
        raise RuntimeError(name + ' must name an existing ' + expected_name + ' for the Windows release smoke gate')
    return path.resolve()

def require_inno_compiler(platform, environ):
    return require_file(platform, environ, 'WHISPER_SMOKE_INNO_COMPILER', 'ISCC.exe')

def require_historical_script(platform, environ):
    return require_file(platform, environ, 'WHISPER_SMOKE_OLD_INSTALLER_SCRIPT', 'installer_embed.iss')

@pytest.fixture(scope='module')
def inno_compiler():
    return require_inno_compiler(os.name, os.environ)
