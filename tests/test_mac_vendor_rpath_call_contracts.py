"""Native-tool call contracts using synthetic files and the existing Python shim."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


_support_spec = importlib.util.spec_from_file_location(
    "_vendor_rpath_contract_support", Path(__file__).with_name("test_mac_vendor_rpath_repair.py")
)
_support = importlib.util.module_from_spec(_support_spec)
_support_spec.loader.exec_module(_support)
bundle = _support.bundle
VENDOR = _support.VENDOR
SECOND_VENDOR = VENDOR + "/secondary-vendor"


def edits(log):
    return [row for row in _support.commands(log) if row[0] == "install_name_tool"]


@pytest.mark.parametrize("copies", [2, 3], ids=["two-copies", "three-copies"])
def test_repeated_vendor_path_uses_one_deletion_per_pass(bundle, monkeypatch, copies):
    app, _gui, library, _dependency, state, log, run = bundle
    _support.change(state, library, rpaths=["@loader_path", *([VENDOR] * copies)])

    helper = _support.load_helper(monkeypatch, "repair_bundle_rpaths")
    assert helper.repair_bundle(app, run=run) == 1

    assert edits(log) == [
        ["install_name_tool", "-delete_rpath", VENDOR, str(library)]
        for _ in range(copies)
    ]
    assert json.loads(state.read_text())[str(library)]["rpaths"] == ["@loader_path"]


def test_asymmetric_fat_original_is_never_edited_directly(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    _support.change(
        state, library, architectures=["arm64", "x86_64"],
        slice_rpaths={"arm64": ["@loader_path", VENDOR], "x86_64": ["@loader_path"]},
    )

    def refuse_original_edit(argv, **kwargs):
        if Path(argv[0]).name == "install_name_tool":
            assert argv[-1] != str(library), "Asymmetric fat original must only be replaced after staged validation"
        return run(argv, **kwargs)

    helper = _support.load_helper(monkeypatch, "repair_bundle_rpaths")
    assert helper.repair_bundle(app, run=refuse_original_edit) == 1

    calls = edits(log)
    assert len(calls) == 1
    assert calls[0][:-1] == ["install_name_tool", "-delete_rpath", VENDOR]
    assert Path(calls[0][-1]).parent.name.startswith(".rpath-")
    assert all(row[-1] != str(library) for row in calls)
    assert json.loads(state.read_text())[str(library)]["slice_rpaths"] == {
        "arm64": ["@loader_path"], "x86_64": ["@loader_path"],
    }


def test_mixed_vendor_counts_batch_only_remaining_paths(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    _support.change(state, library, rpaths=["@loader_path", VENDOR, SECOND_VENDOR, VENDOR])

    helper = _support.load_helper(monkeypatch, "repair_bundle_rpaths")
    assert helper.repair_bundle(app, run=run) == 1

    assert edits(log) == [
        ["install_name_tool", "-delete_rpath", VENDOR, "-delete_rpath", SECOND_VENDOR, str(library)],
        ["install_name_tool", "-delete_rpath", VENDOR, str(library)],
    ]
    assert json.loads(state.read_text())[str(library)]["rpaths"] == ["@loader_path"]


def test_second_planned_file_edit_failure_prevents_all_signing(bundle, monkeypatch):
    app, _gui, library, _dependency, state, log, run = bundle
    second = library.with_name("zz-second.dylib")
    second.write_bytes(library.read_bytes())
    data = json.loads(state.read_text())
    data[str(second)] = copy.deepcopy(data[str(library)])
    data[str(second)]["fail_tool"] = "install_name_tool"
    state.write_text(json.dumps(data))

    helper = _support.load_helper(monkeypatch, "repair_bundle_rpaths")
    with pytest.raises(subprocess.CalledProcessError):
        helper.repair_bundle(app, run=run)

    assert [row[-1] for row in edits(log)] == [str(library), str(second)]
    assert not any(row[0] == "codesign" for row in _support.commands(log))
    current = json.loads(state.read_text())
    assert current[str(library)]["rpaths"] == ["@loader_path"]
    assert current[str(second)]["rpaths"] == ["@loader_path", VENDOR]
