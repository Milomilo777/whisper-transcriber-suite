"""Compile and exercise the installer's actual model-cache cleanup functions.

Windows only. Uses a supplied Inno compiler and a NEW scratch directory. Every
deletion target and junction target is created inside that directory; fixtures
are retained for inspection. This does not install or uninstall the application.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


def junction(link: Path, target: Path) -> None:
    def quoted(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    code = ("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "
            + quoted(link) + " -Target " + quoted(target) + " | Out-Null")
    encoded = base64.b64encode(code.encode("utf-16le")).decode("ascii")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   check=True, capture_output=True, timeout=20,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def check(compiler: Path, script: Path, scratch: Path) -> dict:
    if os.name != "nt":
        raise RuntimeError("Native Windows is required")
    compiler = compiler.resolve(strict=True)
    script = script.resolve(strict=True)
    scratch = scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=False)
    nonce = uuid.uuid4().hex
    (scratch / "owner-marker.txt").write_text(nonce, encoding="ascii")
    source = script.read_text(encoding="utf-8")
    has_guard = "function CanDeletePrivateHub(" in source
    first = source.index("function HubCacheAttributes(" if has_guard else "function DeleteHubModels(")
    last = source.index("procedure CurUninstallStepChanged", first)
    functions = source[first:last]

    def routine(name: str) -> str:
        match = re.search(r"(?ms)^(?:function|procedure) " + re.escape(name) + r"\b.*?^end;", source)
        if match is None:
            raise ValueError(f"Missing installer routine {name}")
        return match.group(0)

    marker = re.search(r"(?m)^\s*NoVoiceCloneMarker\s*=\s*([^;]+);", source)
    declarations = "const NoVoiceCloneMarker = " + marker[1] + ";\n" if marker else ""
    support = routine("ExtractHubFolder") + "\n" + routine("IsPathInside") + "\n"
    callback = routine("CurUninstallStepChanged")
    cases = [
        ("private", "private/models", "private/models"),
        ("custom", "custom", "private/models"),
        ("sibling", "private/models-other", "private/models"),
        ("root_link", "root-link", "root-link"),
        ("parent_link", "parent-link/child/models", "parent-link/child/models"),
        ("nested_link", "nested/models", "nested/models"),
        ("missing", "missing/models", "missing/models"),
    ]
    for folder in ("private/models", "custom", "private/models-other",
                   "root-target", "parent-target/child/models", "nested/models"):
        model = scratch / folder / "models--synthetic"
        model.mkdir(parents=True)
        (model / "synthetic.bin").write_bytes(b"synthetic model fixture")
    (scratch / "private/models/notes.txt").write_text("unrelated file", encoding="utf-8")
    outside = scratch / "outside-nested-target"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("retain this target", encoding="utf-8")
    junction(scratch / "root-link", scratch / "root-target")
    junction(scratch / "parent-link", scratch / "parent-target")
    junction(scratch / "nested/models/models--synthetic/link", outside)
    # Resolve EVERY eventual recursive-delete target before the executable can
    # run. Links intentionally point to other owned fixture directories.
    for _, candidate, expected in cases:
        for value in (candidate, expected):
            (scratch / value).resolve().relative_to(scratch)
    cleanup_args = "Hub, Expected" if has_guard else "Hub"
    calls = "\n".join(
        "  RecordCleanup('" + name + "', Root + '\\" + candidate.replace("/", "\\")
        + "', Root + '\\" + expected.replace("/", "\\") + "');"
        for name, candidate, expected in cases)
    harness = """[Setup]
AppName=Whisper model cache contract test
AppVersion=1
DefaultDirName={tmp}\\WhisperCacheContract
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
UsePreviousLanguage=no
DisableStartupPrompt=yes
[Code]
""" + declarations + support + functions + callback + """
var Root: string;
procedure RecordCleanup(Name, Hub, Expected: string);
var Value: string;
begin
  if DeleteHubModels(""" + cleanup_args + """) then Value := '1' else Value := '0';
  SaveStringToFile(Root + '\\observed.txt', Name + '=' + Value + #13#10, True);
end;
function InitializeSetup(): Boolean;
var Marker: AnsiString;
begin
  Result := False;
  Root := ExpandConstant('{param:TESTROOT|}');
  if Root = '' then Exit;
  if not LoadStringFromFile(Root + '\\owner-marker.txt', Marker) then Exit;
  if Marker <> '""" + nonce + """' then Exit;
""" + calls + """
  SaveStringToFile(Root + '\\observed.txt', 'complete=1' + #13#10, True);
end;
"""
    test_source = scratch / "contract.iss"
    test_source.write_text(harness, encoding="utf-8-sig")
    build = subprocess.run([str(compiler), "/Qp", "/O" + str(scratch), "/Fcontract", str(test_source)],
                           capture_output=True, text=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    (scratch / "compile.local.log").write_text(build.stdout + build.stderr, encoding="utf-8")
    if build.returncode:
        raise RuntimeError("Native contract compilation failed; inspect compile.local.log")
    program = scratch / "contract.exe"
    result = subprocess.run([str(program), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES",
                             "/NORESTART", "/TESTROOT=" + str(scratch),
                             "/LOG=" + str(scratch / "run.local.log")],
                            capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    lines = (scratch / "observed.txt").read_text(encoding="ascii").splitlines()
    observed = dict(line.split("=", 1) for line in lines)
    if observed.get("complete") != "1":
        raise RuntimeError("Native contract did not finish; no cleanup verdict")
    # InitializeSetup deliberately returns False: no installer operation runs.
    if result.returncode != 1:
        raise RuntimeError(f"Unexpected test-only setup exit {result.returncode}")
    checks = {
        "private_cache_removed": not (scratch / "private/models/models--synthetic").exists(),
        "private_unrelated_file_kept": (scratch / "private/models/notes.txt").is_file(),
        "custom_models_kept": (scratch / "custom/models--synthetic/synthetic.bin").is_file(),
        "sibling_models_kept": (scratch / "private/models-other/models--synthetic/synthetic.bin").is_file(),
        "root_junction_target_kept": (scratch / "root-target/models--synthetic/synthetic.bin").is_file(),
        "parent_junction_target_kept": (scratch / "parent-target/child/models/models--synthetic/synthetic.bin").is_file(),
        "nested_junction_target_kept": (outside / "sentinel.txt").is_file(),
        "nested_private_model_removed": not (scratch / "nested/models/models--synthetic").exists(),
        "custom_cleanup_rejected": observed.get("custom") == "0",
        "missing_cleanup_rejected": observed.get("missing") == "0",
    }
    receipt = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
               "setup_exit": result.returncode, "app_install_performed": False,
               "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
               "function_sha256": hashlib.sha256(functions.encode()).hexdigest(),
               "callback_sha256": hashlib.sha256(callback.encode()).hexdigest(),
               "compiler_sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
               "native_harness_sha256": hashlib.sha256(program.read_bytes()).hexdigest()}
    (scratch / "result.local.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    receipt = check(args.compiler, args.script, args.scratch)
    print(json.dumps({"verdict": receipt["verdict"], "checks": receipt["checks"]}, indent=2))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
