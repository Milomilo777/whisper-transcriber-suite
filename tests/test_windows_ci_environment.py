"""Exercise packaging assertions with Windows text and directory aliases."""
import codecs
import locale
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ANSI decoding control")
def test_bundle_audit_preserves_unicode_with_legacy_windows_stdio(tmp_path):
    if codecs.lookup(locale.getencoding()).name == "utf-8":
        pytest.skip("Windows ANSI code page is already UTF-8")
    env = os.environ | {"PYTHONUTF8": "0", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-m", "pytest", "-p", "no:cacheprovider",
         "-o", "addopts=", "-q", "tests/test_mac_bundle_audit.py", "-k",
         "every_offending_file or smaller_offending_component",
         "--basetemp", str(tmp_path / "nested")],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory alias control")
def test_store_build_preserves_inputs_through_temp_directory_alias(tmp_path):
    target = tmp_path / "long temporary directory"
    target.mkdir()
    alias = tmp_path / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                   capture_output=True, check=True)
    try:
        env = os.environ | {"TEMP": str(alias), "TMP": str(alias),
                            "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
             "-o", "addopts=", "-q",
             "tests/test_store_build_spec.py", "-k",
             "delegated_spec_preserves_root_build or launcher_records_inputs"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            capture_output=True, encoding="utf-8", timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "2 passed" in result.stdout, result.stdout + result.stderr
    finally:
        alias.rmdir()
