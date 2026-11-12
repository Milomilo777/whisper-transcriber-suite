"""Conversion publishes its own bytes without touching another writer's staging."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import _checkpoint, convert


def test_parallel_conversion_to_one_destination_keeps_each_payload(tmp_path, monkeypatch):
    target = tmp_path / "shared.txt"
    first_source = tmp_path / "first.srt"
    second_source = tmp_path / "second.srt"
    for source, text in ((first_source, "FIRST TRANSCRIPT"), (second_source, "SECOND TRANSCRIPT")):
        source.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n", encoding="utf-8")
    first_ready = threading.Event()
    second_ready = threading.Event()
    first_published = threading.Event()
    original_flush = _checkpoint._flush_to_disk

    def pause_after_flush(stream):
        original_flush(stream)
        if threading.current_thread().name.endswith("_0"):
            first_ready.set()
            assert second_ready.wait(10), "second conversion never reached its flush"
        else:
            second_ready.set()
            assert first_published.wait(10), "first conversion never completed"

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", pause_after_flush)

    def run(source, first=False):
        try:
            result = convert.convert_file(str(source), "txt", out_path=str(target))
            return Path(result).read_text(encoding="utf-8")
        except Exception as error:
            return error
        finally:
            if first:
                first_published.set()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="convert") as pool:
        first = pool.submit(run, first_source, True)
        assert first_ready.wait(10)
        second = pool.submit(run, second_source)
        first_result, second_result = first.result(timeout=15), second.result(timeout=15)
    assert first_result == "FIRST TRANSCRIPT\n"
    assert second_result == "SECOND TRANSCRIPT\n"
    assert not list(tmp_path.glob("*.part"))


def test_conversion_preserves_unowned_predictable_staging(tmp_path):
    target = tmp_path / "transcript.txt"
    foreign = Path(f"{target}.{os.getpid()}.part")
    foreign.write_bytes(b"other writer's recoverable transcript")
    convert._replace_atomically(str(target), b"new transcript")
    assert target.read_bytes() == b"new transcript"
    assert foreign.read_bytes() == b"other writer's recoverable transcript"


def test_conversion_accepts_long_valid_destination_basename(tmp_path):
    if os.name == "nt":
        tmp_path = Path("\\\\?\\" + str(tmp_path.resolve()))
    target = tmp_path / ("t" * 245 + ".txt")
    target.write_bytes(b"previous transcript")
    convert._replace_atomically(str(target), b"converted transcript")
    assert target.read_bytes() == b"converted transcript"


@pytest.mark.parametrize("operation", ["flush", "replace"])
def test_failed_publication_preserves_destination_and_owned_cleanup(tmp_path, monkeypatch, operation):
    target = tmp_path / "transcript.txt"
    target.write_bytes(b"previous transcript")
    sibling = tmp_path / "unrelated.part"
    sibling.write_bytes(b"recoverable sibling")

    def fail(*args):
        raise OSError("synthetic disk failure")

    if operation == "flush":
        monkeypatch.setattr(_checkpoint, "_flush_to_disk", fail)
    else:
        monkeypatch.setattr(convert.os, "replace", fail)
    with pytest.raises(OSError, match="synthetic disk failure"):
        convert._replace_atomically(str(target), b"incomplete replacement")
    assert target.read_bytes() == b"previous transcript"
    assert sibling.read_bytes() == b"recoverable sibling"
    assert list(tmp_path.glob("*.part")) == [sibling]


def test_exclusive_creation_collision_preserves_foreign_staging(tmp_path, monkeypatch):
    target = tmp_path / "transcript.txt"
    target.write_bytes(b"previous transcript")
    foreign = tmp_path / ".convert-fixed.part"
    foreign.write_bytes(b"other writer's recoverable transcript")
    monkeypatch.setattr(convert.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(FileExistsError):
        convert._replace_atomically(str(target), b"new transcript")
    assert target.read_bytes() == b"previous transcript"
    assert foreign.read_bytes() == b"other writer's recoverable transcript"


def test_default_output_staging_collision_preserves_foreign_file(tmp_path, monkeypatch):
    source = tmp_path / "input.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nwords\n\n", encoding="utf-8")
    foreign = tmp_path / ".convert-fixed.part"
    foreign.write_bytes(b"other writer's recoverable transcript")
    monkeypatch.setattr(convert.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(FileExistsError):
        convert.convert_file(str(source), "txt")
    assert not source.with_suffix(".txt").exists()
    assert foreign.read_bytes() == b"other writer's recoverable transcript"
