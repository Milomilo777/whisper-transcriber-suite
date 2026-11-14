"""Adversarial package-identity and native-floor tests; no Mac runtime needed."""
import builtins
import copy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_mac_review_regressions import app, contract, fake_macholib, functions


@pytest.mark.parametrize("target", ["outside", "dangling"])
def test_manifest_refuses_nonlocal_or_unresolved_links(contract, tmp_path, target):
    root = app(tmp_path)
    outside = tmp_path / "outside.dylib"
    if target == "outside":
        outside.write_bytes(b"external native payload")
    (root / "Contents/MacOS/native-link").symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        contract.bundle_manifest(root)


def test_manifest_binds_internal_symlink_destination_even_for_identical_bytes(contract, tmp_path):
    root = app(tmp_path)
    for name in ("first", "second"):
        (root / "Contents/MacOS" / name).write_bytes(b"identical")
    link = root / "Contents/MacOS/selected"
    link.symlink_to("first")
    expected = contract.bundle_manifest(root)
    link.unlink()
    link.symlink_to("second")
    with pytest.raises(ValueError):
        contract.verify_manifest(root, expected)


def test_same_version_model_data_substitution_is_rejected(contract, tmp_path):
    root = app(tmp_path)
    model = root / "Contents/model.onnx"
    model.write_bytes(b"trusted model")
    expected = contract.bundle_manifest(root)
    model.write_bytes(b"stale-- model")
    with pytest.raises(ValueError):
        contract.verify_manifest(root, expected)


@pytest.mark.parametrize("mutation", ["schema", "version", "minimum", "digest", "omission", "extra"])
def test_manifest_does_not_accept_mutated_identity(contract, tmp_path, mutation):
    root = app(tmp_path)
    expected = copy.deepcopy(contract.bundle_manifest(root))
    if mutation in ("schema", "version", "minimum"):
        expected[mutation] = {"schema": 2, "version": "2.3.9", "minimum": "10.15"}[mutation]
    elif mutation == "digest":
        next(row for row in expected["entries"] if row["kind"] == "file")["sha256"] = "0" * 64
    elif mutation == "omission":
        expected["entries"].pop()
    else:
        expected["entries"].append({"path": "Contents/stale", "kind": "directory"})
    with pytest.raises(ValueError):
        contract.verify_manifest(root, expected)


def test_manifest_rejects_payload_changed_during_hash(contract, tmp_path, monkeypatch):
    root = app(tmp_path)
    payload = root / "Contents/MacOS/App"
    original = contract.hashlib.file_digest

    def change_after_read(stream, algorithm):
        digest = original(stream, algorithm)
        if Path(stream.name) == payload:
            with payload.open("ab") as writer:
                writer.write(b"changed while audited")
        return digest

    monkeypatch.setattr(contract.hashlib, "file_digest", change_after_read)
    with pytest.raises(ValueError, match="changed"):
        contract.bundle_manifest(root)


def test_collected_required_source_unreadable_is_not_dropped(tmp_path, monkeypatch):
    native = tmp_path / "required.so"
    native.write_bytes(bytes.fromhex("cffaedfe"))
    tools = tmp_path / "bin"
    tools.mkdir()
    original = builtins.open

    def denied(path, *args, **kwargs):
        if os.fspath(path) == str(native):
            raise PermissionError("required native source is unreadable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied)
    with pytest.raises((OSError, SystemExit)):
        functions("_minimum_sources")["_minimum_sources"](
            [("required.so", str(native), "BINARY")], [], str(tools)
        )


def test_dangling_native_entry_cannot_disappear_from_source_walk(tmp_path):
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "required.dylib").symlink_to(tools / "missing.dylib")
    with pytest.raises((OSError, SystemExit, ValueError)):
        functions("_minimum_sources")["_minimum_sources"]([], [], str(tools))


def header(cpu, minimum):
    return SimpleNamespace(
        header=SimpleNamespace(cputype=cpu),
        commands=[(SimpleNamespace(cmd=0x32),
                   SimpleNamespace(minos=minimum, platform=1), None)],
    )


@pytest.mark.parametrize("cpu", [0x01000007, 0x0100000C], ids=["intel-only", "arm-only"])
def test_universal2_requires_both_architecture_slices(monkeypatch, cpu):
    fake_macholib(monkeypatch, lambda path: SimpleNamespace(headers=[header(cpu, 0x000C0000)]))
    with pytest.raises(SystemExit):
        functions("_macho_minos")["_macho_minos"]("one-slice.dylib", "universal2")


def test_universal2_floor_includes_the_higher_slice_patch(monkeypatch):
    headers = [header(0x01000007, 0x000C0301), header(0x0100000C, 0x000D0102)]
    fake_macholib(monkeypatch, lambda path: SimpleNamespace(headers=headers))
    assert functions("_macho_minos")["_macho_minos"]("both.dylib", "universal2") == (13, 1, 2)


def test_target_slice_without_a_minimum_is_not_hidden_by_a_valid_slice(monkeypatch):
    headers = [header(0x01000007, 0x000C0000),
               SimpleNamespace(header=SimpleNamespace(cputype=0x0100000C), commands=[])]
    fake_macholib(monkeypatch, lambda path: SimpleNamespace(headers=headers))
    with pytest.raises(SystemExit):
        functions("_macho_minos")["_macho_minos"]("partly-uninspectable.dylib", "universal2")
