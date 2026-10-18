"""Keep imports and all test scratch inside the spike, from either working directory."""
import os
from pathlib import Path
import sys
import shutil
import uuid

import pytest

SPIKE = Path(os.path.relpath(Path(__file__).parent.parent))
sys.path.insert(0, str(SPIKE))


@pytest.fixture
def tmp_path():
    scratch = SPIKE / "tests/.tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    # Python 3.13+ mkdir(mode=0o700), used by TemporaryDirectory, gives an ACL
    # that excludes this Windows sandbox's restricted token. Inherit the parent ACL.
    directory = scratch / ("case-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if directory.is_symlink() or not directory.resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError("Unsafe test scratch cleanup path")
        shutil.rmtree(directory)
