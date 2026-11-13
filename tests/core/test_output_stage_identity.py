"""A pre-existing staging alias must not truncate an unrelated original."""
import os
from pathlib import Path
import threading

import pytest
from core import transcriber as tr


@pytest.mark.parametrize("format", ["srt", "pdf"])
def test_preexisting_staging_alias_preserves_original(tmp_path, monkeypatch, format):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")
    monkeypatch.setattr(tr, "supported_formats", lambda: {"srt", "pdf"})
    monkeypatch.setattr(tr, "is_binary", lambda fmt: fmt == "pdf")
    monkeypatch.setattr(tr, "get_writer", lambda fmt: lambda *args: "new transcript\n")
    monkeypatch.setattr(tr, "get_binary_writer", lambda fmt: lambda *args: b"new binary transcript\n")
    original = tmp_path / "earlier-transcript.txt"
    original.write_bytes(b"irreplaceable earlier transcript\n")
    target = tmp_path / ("talk." + format)
    staging = Path(f"{target}.{os.getpid()}-{threading.get_ident()}.part")
    os.link(original, staging)
    before = original.read_bytes()

    written = tr._write_outputs(str(tmp_path / "talk"), [], "talk.wav", [format])

    assert original.read_bytes() == before, "an unowned staging alias truncated the original"
    assert staging.read_bytes() == before, "the pre-existing staging name was consumed"
    assert written == [str(target)] and target.read_bytes().startswith(b"new ")


def test_writer_failure_keeps_unowned_staging_file(tmp_path, monkeypatch):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")
    target = tmp_path / "talk.srt"
    staging = Path(f"{target}.{os.getpid()}-{threading.get_ident()}.part")
    staging.write_bytes(b"earlier partial result must survive\n")

    def fail(*args):
        raise OSError("writer unavailable")

    monkeypatch.setattr(tr, "get_writer", lambda fmt: fail)
    with pytest.raises(RuntimeError):
        tr._write_outputs(str(tmp_path / "talk"), [], "talk.wav", ["srt"])
    assert staging.read_bytes() == b"earlier partial result must survive\n"


def test_flush_failure_keeps_original_staging_alias(tmp_path, monkeypatch):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")
    original = tmp_path / "earlier-transcript.txt"
    original.write_bytes(b"irreplaceable original\n")
    target = tmp_path / "talk.srt"
    staging = Path(f"{target}.{os.getpid()}-{threading.get_ident()}.part")
    os.link(original, staging)
    monkeypatch.setattr(tr, "get_writer", lambda fmt: lambda *args: "new transcript\n")

    def fail(stream):
        raise OSError("flush unavailable")

    monkeypatch.setattr(tr._checkpoint, "_flush_to_disk", fail)
    with pytest.raises(RuntimeError):
        tr._write_outputs(str(tmp_path / "talk"), [], "talk.wav", ["srt"])
    assert original.read_bytes() == b"irreplaceable original\n"
    assert staging.read_bytes() == b"irreplaceable original\n"


def test_chapter_staging_alias_preserves_original(tmp_path):
    original = tmp_path / "earlier.txt"
    original.write_bytes(b"irreplaceable chapter source\n")
    target = tmp_path / "talk.chapters.json"
    staging = Path(f"{target}.{os.getpid()}-{threading.get_ident()}.part")
    os.link(original, staging)
    assert tr._write_chapter_sidecar(str(target), [{"start": 0.0, "title": "Intro"}]) == str(target)
    assert original.read_bytes() == b"irreplaceable chapter source\n"
    assert staging.read_bytes() == b"irreplaceable chapter source\n"


def test_partial_staging_alias_preserves_original(tmp_path, monkeypatch):
    from types import SimpleNamespace
    original = tmp_path / "earlier.txt"
    original.write_bytes(b"irreplaceable partial source\n")
    target = tmp_path / "talk.partial.srt"
    staging = Path(f"{target}.{os.getpid()}.part")
    os.link(original, staging)
    monkeypatch.setattr(tr, "get_writer", lambda fmt: lambda *args: "new partial transcript\n")
    task = SimpleNamespace(file_path=str(tmp_path / "talk.wav"), _audio_end=1.0)
    tr._save_partial_subtitles(task, [{"start": 0., "end": 1., "text": "new partial"}], None)
    assert original.read_bytes() == b"irreplaceable partial source\n"
    assert staging.read_bytes() == b"irreplaceable partial source\n"
    assert target.read_bytes() == b"new partial transcript\n"


def test_chapter_serialization_error_keeps_unowned_stage(tmp_path):
    target = tmp_path / "talk.chapters.json"
    staging = Path(f"{target}.{os.getpid()}-{threading.get_ident()}.part")
    staging.write_bytes(b"earlier partial chapter data\n")
    assert tr._write_chapter_sidecar(str(target), [{"start": object()}]) is None
    assert staging.read_bytes() == b"earlier partial chapter data\n"


def test_partial_writer_error_keeps_unowned_stage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    target = tmp_path / "talk.partial.srt"
    staging = Path(f"{target}.{os.getpid()}.part")
    staging.write_bytes(b"earlier partial subtitle data\n")

    def fail(*args):
        raise OSError("writer unavailable")

    monkeypatch.setattr(tr, "get_writer", lambda fmt: fail)
    tr._save_partial_subtitles(SimpleNamespace(file_path=str(tmp_path / "talk.wav")), [], None)
    assert staging.read_bytes() == b"earlier partial subtitle data\n"


def test_chapter_serialization_has_bounded_allocation(tmp_path):
    import tracemalloc
    assert tr._write_chapter_sidecar(str(tmp_path / "warm.json"), [{"start": 0.}])
    title = "x" * 65536
    chapters = [{"start": float(index), "title": title} for index in range(256)]
    target = tmp_path / "large.chapters.json"
    tracemalloc.start()
    try:
        written = tr._write_chapter_sidecar(str(target), chapters)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert written == str(target) and target.stat().st_size > 16 * 1024 * 1024
    assert peak < 4 * 1024 * 1024, "chapter serialization materialized the whole document"
