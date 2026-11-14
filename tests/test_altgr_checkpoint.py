"""Interrupted native evidence writes must retain the last complete checkpoint."""
import ast
import importlib.util
import io
import json
from pathlib import Path

import pytest


HELPERS = Path(__file__).resolve().parents[1] / "tools" / "qa"


class InterruptedWrite(BaseException):
    """Model termination during a write without terminating the pytest process."""


def writer_module():
    spec = importlib.util.spec_from_file_location("receipt_io", HELPERS / "receipt_io.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def actual_saver(source, output, data):
    # Execute the actual small closure with inert data, never the Win32 runner.
    tree = ast.parse((HELPERS / source).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "save")
    namespace = {"json": json, "identity_path": output, "identity": data,
                 "output": output, "data": data}
    if (HELPERS / "receipt_io.py").exists():
        namespace["write_json_checkpoint"] = writer_module().write_json_checkpoint
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HELPERS / source), "exec"), namespace)
    return namespace["save"]


def interrupt_writes(monkeypatch):
    real_open = io.open

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, text):
            self.stream.write(text[:max(1, len(text) // 2)])
            self.stream.flush()
            raise InterruptedWrite()

        def __getattr__(self, name):
            return getattr(self.stream, name)

    def opened(file, mode="r", *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        return PartialWriter(stream) if "w" in mode else stream

    monkeypatch.setattr(io, "open", opened)


@pytest.mark.parametrize("source", ["hosted_altgr_loader.py", "test_altgr_acceptance.py"])
def test_actual_saver_keeps_last_checkpoint_when_write_is_interrupted(tmp_path, monkeypatch, source):
    output = tmp_path / "receipt.json"
    previous = b'{"status":"STARTED","observations":[{"vk":65}]}'
    output.write_bytes(previous)
    save = actual_saver(source, output, {"status": "PASS", "observations": [{"vk": 67}]})
    with monkeypatch.context() as patch:
        interrupt_writes(patch)
        with pytest.raises(InterruptedWrite):
            save()
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("source", ["hosted_altgr_loader.py", "test_altgr_acceptance.py"])
def test_actual_saver_publishes_complete_utf8_json(tmp_path, source):
    output = tmp_path / "receipt.json"
    data = {"status": "STARTED", "observations": [{"text": "\u263a\u202f\U0001f642"}]}
    actual_saver(source, output, data)()
    assert json.loads(output.read_text(encoding="utf-8")) == data
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("stage", ["flush", "replace"])
def test_failed_publication_keeps_previous_checkpoint(tmp_path, monkeypatch, stage):
    module = writer_module()
    output = tmp_path / "receipt.json"
    output.write_bytes(b'{"status":"STARTED"}')
    def fail(*args, **kwargs):
        raise OSError("Injected publication failure")
    monkeypatch.setattr(module.os, "fsync" if stage == "flush" else "replace", fail)
    with pytest.raises(OSError, match="Injected publication failure"):
        module.write_json_checkpoint(output, {"status": "PASS"})
    assert output.read_bytes() == b'{"status":"STARTED"}'
    assert list(tmp_path.iterdir()) == [output]


def test_serialization_failure_never_opens_the_previous_checkpoint(tmp_path):
    output = tmp_path / "receipt.json"
    output.write_bytes(b'{"status":"STARTED"}')
    with pytest.raises(TypeError):
        writer_module().write_json_checkpoint(output, {"invalid": object()})
    assert output.read_bytes() == b'{"status":"STARTED"}'
    assert list(tmp_path.iterdir()) == [output]
