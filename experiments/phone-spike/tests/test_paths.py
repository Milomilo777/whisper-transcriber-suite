import importlib.util
import os
from pathlib import Path

import pytest

from engines import engine_registry

SPIKE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("filename,attribute", [
    ("bench.py", "RUNNER"), ("run_all.py", "ROOT"), ("setup.py", "ROOT"),
    ("download_data.py", "ROOT"), ("engines/vosk_engine.py", "ROOT"),
    ("engines/sherpa_engine.py", "ROOT"), ("engines/whispercpp_engine.py", "ROOT"),
])
def test_resource_paths_do_not_use_cross_drive_relpath(monkeypatch, filename, attribute):
    def cross_drive(*args, **kwargs):
        raise ValueError("path is on a different drive from the current directory")
    monkeypatch.setattr(os.path, "relpath", cross_drive)
    # Loading isolated copies must not replace the real test registry's engines.
    monkeypatch.setattr(engine_registry, "register", lambda name: lambda cls: cls)
    spec = importlib.util.spec_from_file_location("engines._path_probe", SPIKE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = getattr(module, attribute)
    assert actual.is_absolute()
    assert actual == (SPIKE / "runner.py" if attribute == "RUNNER" else SPIKE)
