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
                   magic="cffaedfe", plist_min="10.15", legacy_minimum=False,
                   want="x86_64", foreign_arm64=False, second_architecture="arm64",
                   build_platform="1", extra_loads="", lipo_warning="", second_tool_error="",
                   other_minimum="", minima_failure=""):
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
    failure = {'': '', 'remove': 'rm -f -- "$minima_list"\n',
               'truncate': ': >"$minima_list"\n'}[minima_failure]
    code = text[start:plist] + f'plist_min="{plist_min}"\n' + failure + text[end_plist:end]
    bash = _find_bash()
    if bash is None:
        pytest.skip("a working Bash is required for the actual inspector loop")
    dependency = "/opt/homebrew/lib/libbad.dylib" if foreign else "/usr/lib/libSystem.B.dylib"
    # Native otool defaults to the host slice unless -arch selects another.
    primary = ("Load command 0\n      cmd LC_VERSION_MIN_MACOSX\n  version " if legacy_minimum else f"Load command 0\n      cmd LC_BUILD_VERSION\n platform {build_platform}\n    minos ") + minimum + "\n" + extra_loads
    secondary = (f"Load command 0\n      cmd LC_BUILD_VERSION\n platform {build_platform}\n    minos " + second_minimum + "\n") if second_minimum else ""
    command = (
        '  selected=x86_64\n  if [ "${2:-}" = -arch ]; then selected="$3"; fi\n'
        f'  if [[ " {architectures} " != *" $selected "* ]]; then return 9; fi\n'
        f'  if [ "$selected" = "{second_architecture}" ] && [ "$1" = "{second_tool_error}" ]; then return 7; fi\n'
        + ("  if [ \"$1\" = -l ] && [[ \"$4\" == *Other.dylib ]]; then\ncat <<'OTHERLOADS'\n"
           + primary.replace(minimum, other_minimum) + 'OTHERLOADS\nreturn\nfi\n' if other_minimum else '')
        + '  if [ "$1" = -L ]; then\n'
        + ('    if [ "$selected" = arm64 ]; then printf "fixture:\\n\\t/opt/homebrew/lib/libbad.dylib (compatibility version 1.0.0)\\n"; return; fi\n' if foreign_arm64 else '')
        + f'    printf "fixture:\\n\\t{dependency} (compatibility version 1.0.0)\\n"\n'
        f"  elif [ \"$selected\" = {second_architecture} ]; then\ncat <<'ARMLOADS'\n" + secondary + 'ARMLOADS\n'
        "  else\ncat <<'INTELLOADS'\n" + primary + 'INTELLOADS\n  fi\n'
    )
    script = tmp_path / "inspect.sh"
    script.write_text(
        f'set -uo pipefail\nAPP="$1"\nWANT={want}\nVERIFY_PYTHON="$2"\n'
        f'file() {{ if [ "{tool_error}" = file ]; then return 7; fi; '
        'if [[ "$2" == *Other.dylib ]]; then printf "Mach-O x86_64\\n"; '
        f'else printf "%s\\n" "{description}"; fi; }}\n'
        f'lipo() {{ if [ "{tool_error}" = lipo ]; then return 7; fi; '
        f'printf "%s\\n" "{architectures}"; '
        + (f'printf "%s\\n" "{lipo_warning}" >&2; ' if lipo_warning else '') + '}\n'
        'otool() {\n'
        f'  if [ "$1" = "{tool_error}" ]; then return 7; fi\n'
        + command + '}\n'
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
    result = inspect_bundle(tmp_path, minimum=minimum, second_minimum=second,
                            architectures="x86_64 arm64", want="universal2")
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("minimum", ["10.13", "10.15"])
def test_compatible_system_linked_binary_passes(tmp_path, minimum):
    result = inspect_bundle(tmp_path, minimum=minimum)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Mach-O files scanned : 1" in result.stdout


@pytest.mark.parametrize("minimum", ["11.0", "12.0"])
def test_every_offending_file_is_reported_in_final_verdict(tmp_path, minimum):
    result = inspect_bundle(tmp_path, minimum=minimum, other_file=True)
    assert result.returncode != 0, result.stdout + result.stderr
    findings = [line for line in result.stdout.splitlines()
                if line.startswith("MINOS ") and "requires" in line]
    assert len(findings) == 2, result.stdout
    assert any("Library ü.dylib [x86_64]" in line for line in findings)
    assert any("Other.dylib [x86_64]" in line for line in findings)
    assert all(f"requires {minimum}, above the declared 10.15" in line for line in findings)


@pytest.mark.parametrize('failure', ['remove', 'truncate'])
def test_lost_minimum_records_cannot_make_incompatible_bundle_pass(tmp_path, failure):
    result = inspect_bundle(tmp_path, minimum='12.0', minima_failure=failure)
    assert result.returncode != 0, result.stdout + result.stderr


def test_smaller_offending_component_is_not_hidden_by_maximum(tmp_path):
    result = inspect_bundle(tmp_path, minimum='12.0', other_file=True, other_minimum='11.0')
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'Library ü.dylib [x86_64] requires 12.0' in result.stdout
    assert 'Other.dylib [x86_64] requires 11.0' in result.stdout


def test_both_offending_slices_are_reported(tmp_path):
    result = inspect_bundle(tmp_path, minimum='12.0', second_minimum='12.1',
                            architectures='x86_64 arm64', want='universal2')
    assert result.returncode != 0, result.stdout + result.stderr
    assert '[x86_64] requires 12.0' in result.stdout
    assert '[arm64] requires 12.1' in result.stdout


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


@pytest.mark.parametrize("want,plist", [("x86_64", "10.15"), ("arm64", "11.0")])
def test_native_slice_selection_matches_requested_os_target(tmp_path, want, plist):
    result = inspect_bundle(tmp_path, minimum="10.15", second_minimum="11.0",
                            architectures="x86_64 arm64",
                            want=want, plist_min=plist)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_slice_universal_target_still_rejects_higher_minimum(tmp_path):
    result = inspect_bundle(tmp_path, minimum="10.15", second_minimum="12.0",
                            architectures="x86_64 arm64",
                            want="universal2", plist_min="11.0")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "requires 12.0" in result.stdout


def test_native_slice_foreign_dependency_on_nonhost_slice_is_not_hidden(tmp_path):
    result = inspect_bundle(tmp_path, minimum="10.15", second_minimum="11.0",
                            architectures="x86_64 arm64",
                            foreign_arm64=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "/opt/homebrew/lib/libbad.dylib" in result.stdout


@pytest.mark.parametrize("want,architectures,minimum,second,plist,offender", [
    ("x86_64", "x86_64", "11.0", "", "10.15", "11.0"),
    ("arm64", "arm64", "11.0", "12.0", "11.0", "12.0"),
])
def test_thin_target_rejects_its_own_higher_minimum(tmp_path, want, architectures, minimum, second, plist, offender):
    result = inspect_bundle(tmp_path, want=want, architectures=architectures,
                            minimum=minimum, second_minimum=second, plist_min=plist)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"requires {offender}" in result.stdout


@pytest.mark.parametrize("want,architectures,second_arch,minimum,plist", [
    ("x86_64", "x86_64 x86_64h", "x86_64h", "10.15", "10.15"),
    ("arm64", "arm64 arm64e", "arm64e", "11.0", "11.0"),
])
def test_subarchitecture_minimum_cannot_escape_target_family(tmp_path, want, architectures, second_arch, minimum, plist):
    result = inspect_bundle(tmp_path, want=want, architectures=architectures,
                            second_architecture=second_arch, minimum=minimum,
                            second_minimum="12.0", plist_min=plist)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "requires 12.0" in result.stdout


@pytest.mark.parametrize("platform", ["2", "6", "UNKNOWN", ""])
def test_nonmac_or_missing_platform_cannot_supply_macos_minimum(tmp_path, platform):
    result = inspect_bundle(tmp_path, minimum="9.0", build_platform=platform)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "no macOS version" in result.stdout


@pytest.mark.parametrize("platform", ["MACOS", "macos"])
def test_named_macos_platform_is_accepted(tmp_path, platform):
    result = inspect_bundle(tmp_path, build_platform=platform)
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalyst_minimum_does_not_replace_verified_macos_command(tmp_path):
    result = inspect_bundle(tmp_path, minimum="10.15",
                            extra_loads="Load command 1\n cmd LC_BUILD_VERSION\n platform 6\n minos 13.1\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "highest minos        : 10.15" in result.stdout


def test_lipo_warning_is_not_treated_as_architecture_tokens(tmp_path):
    result = inspect_bundle(tmp_path, lipo_warning="warning: synthetic lipo diagnostic")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "problems             : 0" in result.stdout


def test_nonhost_load_failure_identifies_the_slice(tmp_path):
    result = inspect_bundle(tmp_path, architectures="x86_64 arm64", second_minimum="11.0",
                            second_tool_error="-l")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "[arm64]" in result.stdout and "load-command inspection failed" in result.stdout


def test_all_requested_slice_minima_are_reported(tmp_path):
    result = inspect_bundle(tmp_path, want="universal2", architectures="x86_64 arm64",
                            minimum="11.0", second_minimum="12.0", plist_min="10.15")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "[x86_64]: 11.0" in result.stdout
    assert "[arm64]: 12.0" in result.stdout


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
