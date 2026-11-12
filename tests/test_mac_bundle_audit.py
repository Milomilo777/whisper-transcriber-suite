"""Execute the real bundle inspection loop with deterministic native-tool replies.

These are inspector controls, not native macOS artifact validation. No bundle
executable is run. The shell and filesystem traversal are real.
"""
from pathlib import Path
import importlib.util
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_mac_build_pins import ROOT, VERIFY, _find_bash


@pytest.fixture
def scanner():
    path = VERIFY.with_name("list_macho.py")
    spec = importlib.util.spec_from_file_location("bundle_candidate_scanner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_bundle(tmp_path, *, executable=True, minimum="10.15", tool_error="",
                   second_minimum="", foreign=False, architectures="x86_64",
                   description="Mach-O 64-bit executable x86_64", other_file=False,
                   magic="cffaedfe", plist_min="10.15", legacy_minimum=False):
    bundle = tmp_path / "Example ü.app"
    # NTFS does not expose chmod's execute bit to Git Bash find. A .dylib
    # baseline is deliberately selected by the old scanner too; only the
    # non-executable framework control uses its real suffix-less shape.
    binary = bundle / "Contents/Frameworks" / ("Library ü.dylib" if executable else "Python")
    binary.parent.mkdir(parents=True)
    binary.write_bytes(bytes.fromhex(magic) + b"synthetic Mach-O fixture")
    binary.chmod(0o755 if executable else 0o644)
    if other_file:
        (binary.parent / "Other.dylib").write_bytes(bytes.fromhex("cffaedfe"))
    text = VERIFY.read_text(encoding="utf-8")
    start = text.index("n=0;")
    plist = text.index('plist_min="$(')
    # Inject only the plist read. The actual scan and compatibility decision
    # come from the production script, with all its exit/error behavior intact.
    end_plist = text.index("\n", plist)
    end = text.index('\nB="$APP/Contents/Frameworks/bin"', end_plist)
    code = text[start:plist] + f'plist_min="{plist_min}"\n' + text[end_plist:end]
    bash = _find_bash()
    if bash is None:
        pytest.skip("a working Bash is required for the actual inspector loop")
    loads = "Load command 0\n      cmd LC_BUILD_VERSION\n    minos " + minimum + "\n"
    if second_minimum:
        loads += "Load command 0\n      cmd LC_BUILD_VERSION\n    minos " + second_minimum + "\n"
    if legacy_minimum:
        loads = "Load command 0\n      cmd LC_VERSION_MIN_MACOSX\n  version " + minimum + "\n"
    dependency = "/opt/homebrew/lib/libbad.dylib" if foreign else "/usr/lib/libSystem.B.dylib"
    script = tmp_path / "inspect.sh"
    script.write_text(
        'set -uo pipefail\nAPP="$1"\nWANT=x86_64\nVERIFY_PYTHON="$2"\n'
        f'file() {{ if [ "{tool_error}" = file ]; then return 7; fi; '
        'if [[ "$2" == *Other.dylib ]]; then printf "Mach-O x86_64\\n"; '
        f'else printf "%s\\n" "{description}"; fi; }}\n'
        f'lipo() {{ if [ "{tool_error}" = lipo ]; then return 7; fi; '
        f'printf "%s\\n" "{architectures}"; }}\n'
        'otool() {\n'
        f'  if [ "$1" = "{tool_error}" ]; then return 7; fi\n'
        '  if [ "$1" = "-L" ]; then\n'
        f'    printf "fixture:\\n\\t{dependency} (compatibility version 1.0.0, current version 1.0.0)\\n"\n'
        '  else\ncat <<\'LOADS\'\n' + loads + 'LOADS\n  fi\n}\n'
        + code + '\n[ "$bad" = 0 ]\n', encoding="utf-8", newline="\n",
    )
    return subprocess.run([bash, str(script), bundle.as_posix(), Path(sys.executable).as_posix()],
                          cwd=ROOT, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("tool_error", ["-L", "-l", "file", "lipo"])
def test_native_inspection_failure_is_not_green(tmp_path, tool_error):
    result = inspect_bundle(tmp_path, tool_error=tool_error)
    assert result.returncode != 0, result.stdout + result.stderr


def test_framework_binary_without_execute_bit_is_inspected(tmp_path):
    result = inspect_bundle(tmp_path, executable=False, foreign=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Python" in result.stdout


@pytest.mark.parametrize("minimum,second", [("11.0", ""), ("10.13", "12.0")])
def test_every_architecture_minimum_must_fit_plist(tmp_path, minimum, second):
    result = inspect_bundle(tmp_path, minimum=minimum, second_minimum=second)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("minimum", ["10.13", "10.15"])
def test_compatible_system_linked_binary_passes(tmp_path, minimum):
    result = inspect_bundle(tmp_path, minimum=minimum)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Mach-O files scanned : 1" in result.stdout


def test_executable_foreign_dependency_is_still_rejected(tmp_path):
    result = inspect_bundle(tmp_path, foreign=True)
    assert result.returncode != 0, result.stdout + result.stderr


def test_missing_minimum_for_one_slice_is_not_green(tmp_path):
    result = inspect_bundle(tmp_path, architectures="x86_64 arm64")
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("description", ["", "data"])
def test_unknown_magic_candidate_is_not_silently_skipped(tmp_path, description):
    result = inspect_bundle(tmp_path, description=description, other_file=True)
    assert result.returncode != 0, result.stdout + result.stderr


def test_java_class_magic_is_not_mistaken_for_mach_o(tmp_path):
    result = inspect_bundle(tmp_path, magic="cafebabe", description="compiled Java class data",
                            other_file=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("minimum,plist", [("10.15.0", "10.15"), ("11.0.0", "11.0")])
def test_equivalent_version_components_pass(tmp_path, minimum, plist):
    result = inspect_bundle(tmp_path, minimum=minimum, plist_min=plist)
    assert result.returncode == 0, result.stdout + result.stderr


def test_legacy_minimum_command_is_still_supported(tmp_path):
    result = inspect_bundle(tmp_path, minimum="10.13", legacy_minimum=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_compatible_two_slice_binary_passes(tmp_path):
    result = inspect_bundle(tmp_path, minimum="10.13", second_minimum="10.15",
                            architectures="x86_64 arm64")
    assert result.returncode == 0, result.stdout + result.stderr


def test_scanner_reads_all_magic_variants_without_resource_false_positives(tmp_path, scanner):
    expected = set()
    for index, magic in enumerate(scanner.MAGICS):
        path = tmp_path / f"framework {index}"
        path.write_bytes(magic)
        expected.add(path)
    (tmp_path / "resource.txt").write_text("ordinary bundled text", encoding="utf-8")
    assert set(scanner.candidates(tmp_path)) == expected


def test_scanner_does_not_open_nonregular_files(tmp_path, scanner):
    (tmp_path / "pipe").write_bytes(bytes.fromhex("cffaedfe"))
    scanner.os = SimpleNamespace(walk=os.walk,
                                 stat=lambda *a, **kw: SimpleNamespace(st_mode=stat.S_IFIFO))
    assert list(scanner.candidates(tmp_path)) == []


def test_disappearing_candidate_aborts_enumeration(tmp_path, scanner):
    scanner.os = SimpleNamespace(walk=lambda *a, **kw: [(str(tmp_path), [], ["vanished"])],
                                 stat=os.stat)
    with pytest.raises(FileNotFoundError):
        list(scanner.candidates(tmp_path))
