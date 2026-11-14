"""Headless controls for the disposable Windows keyboard acceptance runner."""
import ast
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tools" / "qa"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    return {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_OS": "Windows", "QA_EXPECTED_HEAD": "a" * 40,
            "GITHUB_SHA": "a" * 40, "QA_ALTGR_KLID": "00020407"}


def test_admit_preselected_extended_layout_on_disposable_runner():
    loader = load("hosted_altgr_loader")
    assert loader.validate_hosted_context(environment(), "a" * 40, "", "win32")["klid"] == "00020407"


class Mapping:
    def __init__(self, values):
        self.values = values

    def current(self):
        return 1

    def loaded(self):
        return [1]

    def translate(self, hkl, vk, alt):
        return self.values.get(vk, "") if alt else chr(vk).lower()


def test_extended_mapping_includes_real_nonbreaking_space_case():
    guards = load("altgr_guards")
    # Mapping from Microsoft's German Extended E1 Ctrl+Alt table:
    # https://learn.microsoft.com/en-us/globalization/keyboards/kbdgre1.html
    mapping = Mapping({65: "\u263a", 67: "\u202f", 88: "\u00bb", 86: "\u00ab"})
    result = guards.select_loaded_layout(mapping)
    assert set(result["eligible_keys"]) == {65, 67, 88, 86}


def target_selector(selection):
    # Execute the real nested selector with inert dependencies, never main().
    tree = ast.parse((HELPERS / "hosted_altgr_loader.py").read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "select_target_only")
    namespace = {"original_select": lambda api: selection, "target": 1,
                 "identity": {}, "KEYS": (65, 67, 88, 86), "save": lambda: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<real-target-selector>", "exec"), namespace)
    return namespace["select_target_only"](None)


def test_partial_target_mapping_is_refused_before_native_input():
    selection = {"probes": [{"hkl": "0x1", "keys": [
        {"vk": 65, "eligible": True}, {"vk": 67, "eligible": False},
        {"vk": 88, "eligible": True}, {"vk": 86, "eligible": True}]}]}
    assert target_selector(selection)["selected"] is None


def test_complete_target_mapping_is_admitted():
    selection = {"probes": [{"hkl": "0x1", "keys": [
        {"vk": key, "eligible": True} for key in (65, 67, 88, 86)]}]}
    assert target_selector(selection)["selected"] == 1


@pytest.mark.parametrize("text", ["", "\t", "\n", "\x00", "\u200d", "\ud800"])
def test_ineligible_mapping_cannot_become_native_test_input(text):
    guards = load("altgr_guards")
    assert guards.select_loaded_layout(Mapping({65: text}))["selected"] is None


@pytest.mark.parametrize("change", [
    {"GITHUB_ACTIONS": "false"}, {"RUNNER_ENVIRONMENT": "self-hosted"},
    {"RUNNER_OS": "Linux"}, {"GITHUB_SHA": "b" * 40},
    {"QA_EXPECTED_HEAD": "a" * 8}, {"QA_ALTGR_KLID": "00000407"},
])
def test_invalid_hosted_context_is_refused(change):
    with pytest.raises(RuntimeError):
        load("hosted_altgr_loader").validate_hosted_context({**environment(), **change}, "a" * 40, "", "win32")


@pytest.mark.parametrize("rc,clean,status,missing", [
    (1, True, "PASS", []), (0, False, "PASS", []),
    (1, False, "BLOCKED-ENV", []), (0, True, "PASS", [67]),
])
def test_incomplete_native_evidence_never_passes(rc, clean, status, missing):
    assert load("hosted_altgr_loader").final_verdict(rc, clean, status, missing)[1] != 0


@pytest.mark.parametrize("head,dirty,platform", [
    ("b" * 40, "", "win32"), ("a" * 40, " M app/app.py", "win32"),
    ("a" * 40, "", "linux"),
])
def test_wrong_checkout_or_platform_is_refused(head, dirty, platform):
    with pytest.raises(RuntimeError):
        load("hosted_altgr_loader").validate_hosted_context(environment(), head, dirty, platform)


def test_disposable_step_preserves_built_artifacts_and_timeout_evidence():
    workflow = yaml.safe_load((ROOT / ".github/workflows/windows-installer.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build"]["steps"]
    names = [step["name"] for step in steps]
    native = names.index("Hosted native AltGr acceptance at the exact source SHA")
    assert names.index("Upload the installer and the Portable ZIP") < native
    assert native < names.index("Upload the build manifest")
    step = steps[native]
    assert step["timeout-minutes"] == 3
    assert {name: value for name, value in step["env"].items() if name != "QA_ALTGR_REQUIRED"} == {
        "QA_EXPECTED_HEAD": "${{ github.sha }}", "QA_ALTGR_KLID": "00020407"}
    assert step["env"]["QA_ALTGR_REQUIRED"] in {"0", "1"}
    upload = steps[names.index("Upload the build manifest")]
    assert upload["if"] == "always()"
    assert "${{ runner.temp }}/wts-altgr/**" in upload["with"]["path"]


def test_native_baseline_uses_same_separator_aware_mapping_rule():
    tree = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    checks = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                      and call.func.id == "is_altgr_text" for call in ast.walk(n.test))]
    assert len(checks) == 1
    assert "value != expected" in ast.unparse(checks[0].test)
    assert "virtual_actions" in ast.unparse(checks[0].test)


def require_uploadable_patterns(paths):
    for line in paths.splitlines():
        assert not {".", ".."}.intersection(re.split(r"[/\\]", line)), line


def test_uploaded_evidence_has_no_forbidden_parent_path_components():
    workflow = yaml.safe_load((ROOT / ".github/workflows/windows-installer.yml").read_text(encoding="utf-8"))
    uploads = [step for job in workflow["jobs"].values() for step in job["steps"]
               if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) >= 2
    for upload in uploads:
        require_uploadable_patterns(upload["with"]["path"])


def test_parent_path_regression_control_is_rejected():
    with pytest.raises(AssertionError):
        require_uploadable_patterns("${{ github.workspace }}/../wts-hosted-altgr-123-1.altgr.json")


def assignment(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name for target in n.targets))


def test_native_probe_and_loader_write_same_always_uploaded_raw_file(tmp_path):
    native = ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))
    loader = ast.parse((HELPERS / "hosted_altgr_loader.py").read_text(encoding="utf-8"))
    env = {"RUNNER_TEMP": str(tmp_path)}
    namespace = {"Path": Path, "os": SimpleNamespace(environ=env), "env": env}
    exec(compile(ast.Module(body=[assignment(native, "output")], type_ignores=[]), "<actual-native-output>", "exec"), namespace)
    native_output = namespace["output"]
    exec(compile(ast.Module(body=[assignment(loader, "output"), assignment(loader, "raw")], type_ignores=[]), "<actual-loader-output>", "exec"), namespace)
    assert native_output == namespace["raw"] == tmp_path / "wts-altgr" / "raw.json"
    assert "shutil.copyfile(raw" not in (HELPERS / "hosted_altgr_loader.py").read_text(encoding="utf-8")
