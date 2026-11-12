"""Automatic caption companion exports preserve previous edits and real files."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import zipfile

import pytest

from app.services.download_service import write_subtitle_extra_formats
from core import convert
from core.integrations import otranscribe


@pytest.fixture
def subtitle(tmp_path):
    source = tmp_path / "captions (1) \u0641\u0627\u0631\u0633\u06cc.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:03,000\nCOMPLETE SPOKEN WORDS\n\n", encoding="utf-8")
    return source


def assert_complete(paths, phrase="COMPLETE SPOKEN WORDS", extensions=None):
    wanted = extensions if extensions is not None else {".txt", ".otr", ".docx"}
    assert len(paths) == len(wanted)
    assert {Path(path).suffix for path in paths} == wanted
    for path in map(Path, paths):
        if path.suffix == ".txt":
            assert phrase in path.read_text(encoding="utf-8")
            assert b"\r" not in path.read_bytes()
        elif path.suffix == ".otr":
            assert phrase in json.loads(path.read_text(encoding="utf-8"))["text"]
        else:
            with zipfile.ZipFile(path) as document:
                assert phrase.encode() in document.read("word/document.xml")


@pytest.mark.parametrize("suffix", [".txt", ".otr", ".smtv.docx"])
def test_existing_companion_edits_are_preserved(subtitle, suffix):
    target = subtitle.with_suffix(suffix)
    previous = b"previous manually edited companion file"
    target.write_bytes(previous)
    original = subtitle.read_bytes()
    paths = write_subtitle_extra_formats(str(subtitle), language="en", work_title="Synthetic work")
    assert target.read_bytes() == previous
    assert str(target) not in paths
    assert_complete(paths)
    assert subtitle.read_bytes() == original


def test_repeated_exports_preserve_all_earlier_outputs(subtitle):
    first = write_subtitle_extra_formats(str(subtitle), language="en")
    saved = {path: Path(path).read_bytes() for path in first}
    second = write_subtitle_extra_formats(str(subtitle), language="en")
    assert set(first).isdisjoint(second)
    assert all(Path(path).read_bytes() == content for path, content in saved.items())
    assert_complete(first)
    assert_complete(second)


def test_parallel_companions_return_distinct_complete_outputs(subtitle, monkeypatch):
    second = subtitle.with_suffix(".vtt")
    second.write_text("WEBVTT\n\n00:01.000 --> 00:03.000\nOTHER SPOKEN WORDS\n\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    render = otranscribe.whisper_json_to_otr

    def render_together(*args, **kwargs):
        payload = render(*args, **kwargs)
        barrier.wait(timeout=10)
        return payload

    monkeypatch.setattr(otranscribe, "whisper_json_to_otr", render_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_job = pool.submit(write_subtitle_extra_formats, str(subtitle), language="en")
        second_job = pool.submit(write_subtitle_extra_formats, str(second), language="en")
        first_paths, second_paths = first_job.result(timeout=15), second_job.result(timeout=15)
    assert set(first_paths).isdisjoint(second_paths)
    assert_complete(first_paths)
    assert_complete(second_paths, "OTHER SPOKEN WORDS")


def test_file_saved_during_otr_rendering_is_preserved(subtitle, monkeypatch):
    target = subtitle.with_suffix(".otr")
    render = otranscribe.whisper_json_to_otr

    def render_with_other_save(*args, **kwargs):
        target.write_bytes(b"other application's completed edits")
        return render(*args, **kwargs)

    monkeypatch.setattr(otranscribe, "whisper_json_to_otr", render_with_other_save)
    paths = write_subtitle_extra_formats(str(subtitle), language="en")
    assert target.read_bytes() == b"other application's completed edits"
    assert_complete(paths)


@pytest.mark.parametrize("suffix", [".txt", ".otr", ".docx"])
@pytest.mark.parametrize("failure", [OSError, convert.ConvertError])
def test_failed_publication_keeps_edits_and_other_formats(subtitle, monkeypatch, suffix, failure):
    previous = {subtitle.with_suffix(ext): b"previous edited " + ext.encode()
                for ext in (".txt", ".otr", ".smtv.docx")}
    for path, payload in previous.items():
        path.write_bytes(payload)
    install = convert._install_new_output
    failed = []

    def fail_one_format(staged, target):
        if Path(target).suffix == suffix:
            assert Path(staged).stat().st_size > 0
            failed.append(True)
            raise failure("synthetic companion publication failure")
        return install(staged, target)

    monkeypatch.setattr(convert, "_install_new_output", fail_one_format)
    paths = write_subtitle_extra_formats(str(subtitle), language="en")
    assert failed and all(path.read_bytes() == payload for path, payload in previous.items())
    assert_complete(paths, extensions={".txt", ".otr", ".docx"} - {suffix})
    assert not list(subtitle.parent.glob("*.part"))


@pytest.mark.parametrize("suffix", [".txt", ".otr", ".smtv.docx"])
def test_companion_alias_cannot_overwrite_the_input_subtitle(subtitle, suffix):
    target = subtitle.with_suffix(suffix)
    os.link(subtitle, target)
    original = subtitle.read_bytes()
    paths = write_subtitle_extra_formats(str(subtitle), language="en")
    assert subtitle.read_bytes() == target.read_bytes() == original
    assert str(target) not in paths
    assert_complete(paths)


def test_missing_optional_word_writer_keeps_other_complete_companions(subtitle, monkeypatch):
    from core.writers import smtv_docx_writer

    previous = subtitle.with_suffix(".smtv.docx")
    previous.write_bytes(b"previous edited document")

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic optional Word dependency unavailable")

    monkeypatch.setattr(smtv_docx_writer, "write_bytes", unavailable)
    paths = write_subtitle_extra_formats(str(subtitle), language="en")
    assert previous.read_bytes() == b"previous edited document"
    assert_complete(paths, extensions={".txt", ".otr"})
