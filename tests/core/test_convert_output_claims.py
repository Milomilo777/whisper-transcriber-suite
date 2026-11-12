"""Automatically chosen conversion paths never overwrite another completed output."""
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from core import convert


@pytest.fixture
def sources(tmp_path):
    first = tmp_path / "captions.srt"
    second = tmp_path / "captions.vtt"
    first.write_text("1\n00:00:00,000 --> 00:00:01,000\nFIRST INPUT\n\n", encoding="utf-8")
    second.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nSECOND INPUT\n\n", encoding="utf-8")
    return first, second, tmp_path / "captions.txt"


def test_parallel_default_outputs_are_separate_complete_files(sources, monkeypatch):
    first, second, _target = sources
    barrier = threading.Barrier(2)
    get_writer = convert._writers.get_writer

    def delayed_writer(fmt):
        writer = get_writer(fmt)

        def render(*args, **kwargs):
            body = writer(*args, **kwargs)
            barrier.wait(timeout=10)
            return body

        return render

    monkeypatch.setattr(convert._writers, "get_writer", delayed_writer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda source: Path(convert.convert_file(str(source), "txt")), (first, second)))
    assert outputs[0] != outputs[1]
    assert outputs[0].read_text(encoding="utf-8") == "FIRST INPUT\n"
    assert outputs[1].read_text(encoding="utf-8") == "SECOND INPUT\n"


def test_output_created_during_rendering_is_preserved(sources, monkeypatch):
    first, _second, target = sources
    get_writer = convert._writers.get_writer

    def writer_with_external_save(fmt):
        writer = get_writer(fmt)

        def render(*args, **kwargs):
            target.write_bytes(b"another completed edited transcript")
            return writer(*args, **kwargs)

        return render

    monkeypatch.setattr(convert._writers, "get_writer", writer_with_external_save)
    output = Path(convert.convert_file(str(first), "txt"))
    assert target.read_bytes() == b"another completed edited transcript"
    assert output != target and output.read_text(encoding="utf-8") == "FIRST INPUT\n"


def test_automatic_same_input_fallback_keeps_existing_converted_file(sources):
    first, _second, _target = sources
    previous = first.with_name("captions.converted.srt")
    previous.write_bytes(b"previous manually edited conversion")
    source = first.read_bytes()
    output = Path(convert.convert_file(str(first), "srt", out_path=str(first)))
    assert previous.read_bytes() == b"previous manually edited conversion"
    assert output != previous and "FIRST INPUT" in output.read_text(encoding="utf-8")
    assert first.read_bytes() == source


def test_explicit_selected_target_still_allows_replacement(sources):
    first, _second, target = sources
    target.write_bytes(b"selected previous output")
    assert convert.convert_file(str(first), "txt", out_path=str(target)) == str(target)
    assert target.read_text(encoding="utf-8") == "FIRST INPUT\n"


def test_explicit_overwrite_flag_retains_default_name(sources):
    first, _second, target = sources
    target.write_bytes(b"previous output")
    assert convert.convert_file(str(first), "txt", overwrite=True) == str(target)
    assert target.read_text(encoding="utf-8") == "FIRST INPUT\n"


_CHILD = """
import json, sys, time
from pathlib import Path
from core import offline
offline._override = True
from core import convert
source, ready, go = map(Path, sys.argv[1:])
original = convert._writers.get_writer
def get_writer(fmt):
    writer = original(fmt)
    def render(*args, **kwargs):
        body = writer(*args, **kwargs)
        ready.touch()
        deadline = time.monotonic() + 10
        while not go.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('conversion barrier timed out')
            time.sleep(.01)
        return body
    return render
convert._writers.get_writer = get_writer
print(json.dumps(convert.convert_file(str(source), 'txt')))
"""


def test_separate_processes_claim_separate_output_names(sources, tmp_path):
    first, second, _target = sources
    ready = [tmp_path / "ready-first", tmp_path / "ready-second"]
    go = tmp_path / "start"
    processes = [subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(source), str(marker), str(go)],
        cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        env={**os.environ, "WTS_PROFILE_DIR": str(tmp_path / ("profile-" + marker.name))},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) for source, marker in zip((first, second), ready)]
    try:
        deadline = time.monotonic() + 15
        while not all(marker.exists() for marker in ready):
            assert all(process.poll() is None for process in processes), "conversion child exited before barrier"
            assert time.monotonic() < deadline, "conversion children never reached barrier"
            time.sleep(.01)
        go.touch()
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            outputs.append(Path(json.loads(stdout)))
        assert outputs[0] != outputs[1]
        assert outputs[0].read_text(encoding="utf-8") == "FIRST INPUT\n"
        assert outputs[1].read_text(encoding="utf-8") == "SECOND INPUT\n"
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)


@pytest.mark.parametrize("contents", [b"", b"another completed transcript"])
def test_late_saved_file_is_kept_and_conversion_uses_another_name(sources, monkeypatch, contents):
    from core import _checkpoint

    first, _second, target = sources
    flush = _checkpoint._flush_to_disk
    changed = []

    def save_during_publication(stream):
        flush(stream)
        if not changed:
            owner_file = target.with_name("owner-edit.tmp")
            owner_file.write_bytes(contents)
            os.replace(owner_file, target)
            changed.append(True)

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", save_during_publication)
    output = Path(convert.convert_file(str(first), "txt"))
    assert target.read_bytes() == contents
    assert output != target and output.read_text(encoding="utf-8") == "FIRST INPUT\n"
    assert not list(target.parent.glob("*.part"))


def test_file_written_during_staging_is_not_overwritten(sources, monkeypatch):
    from core import _checkpoint

    first, _second, target = sources
    flush = _checkpoint._flush_to_disk
    changed = []

    def save_during_publication(stream):
        flush(stream)
        if not changed:
            target.write_bytes(b"owner edited this output path")
            changed.append(True)

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", save_during_publication)
    output = Path(convert.convert_file(str(first), "txt"))
    assert target.read_bytes() == b"owner edited this output path"
    assert output != target and output.read_text(encoding="utf-8") == "FIRST INPUT\n"


def test_failed_publication_preserves_input_and_removes_owned_staging(sources, monkeypatch):
    first, _second, target = sources
    original = first.read_bytes()

    def fail_replace(*args):
        raise PermissionError("synthetic publication failure")

    monkeypatch.setattr(convert, "_install_new_output", fail_replace)
    with pytest.raises(PermissionError, match="synthetic publication failure"):
        convert.convert_file(str(first), "txt")
    assert first.read_bytes() == original and not target.exists()
    assert not list(target.parent.glob("*.part"))


def test_render_failure_does_not_reserve_an_output(sources, monkeypatch):
    first, _second, target = sources

    def fail_render(*args):
        raise RuntimeError("synthetic render failure")

    monkeypatch.setattr(convert._writers, "get_writer", lambda fmt: fail_render)
    with pytest.raises(RuntimeError, match="synthetic render failure"):
        convert.convert_file(str(first), "txt")
    assert not target.exists() and not list(target.parent.glob("*.part"))


def test_binary_document_publication_uses_the_same_name_protection(sources, monkeypatch):
    from core.writers import smtv_docx_writer

    first, _second, _target = sources
    target = Path(convert._default_out_path(str(first), "smtv_docx"))
    payload = (Path(smtv_docx_writer.__file__).parent / "templates" / "smtv_template.docx").read_bytes()

    def render(*args, **kwargs):
        target.write_bytes(b"previous edited document")
        return payload

    monkeypatch.setattr(smtv_docx_writer, "write_bytes", render)
    output = Path(convert.convert_file(str(first), "smtv_docx"))
    assert target.read_bytes() == b"previous edited document"
    assert output != target and output.read_bytes() == payload


def test_persistent_output_changes_end_without_overwriting_any_edit(sources, monkeypatch):
    first, _second, target = sources
    edited = []

    def finish_before_every_install(staged, destination):
        path = Path(destination)
        path.write_bytes(b"owner's completed edit")
        edited.append(path)
        raise FileExistsError(destination)

    monkeypatch.setattr(convert, "_install_new_output", finish_before_every_install)
    with pytest.raises(convert.ConvertError, match="kept changing"):
        convert.convert_file(str(first), "txt")
    assert edited and all(path.read_bytes() == b"owner's completed edit" for path in edited)
    assert not list(target.parent.glob("*.part"))


@pytest.mark.parametrize("links_available", [True, False])
def test_posix_publication_preserves_existing_files(sources, monkeypatch, links_available):
    first, _second, target = sources
    target.write_bytes(b"previous completed output")
    monkeypatch.setattr(convert, "_IS_WINDOWS", False)
    if not links_available:
        monkeypatch.setattr(os, "link", unsupported_links)
    output = Path(convert.convert_file(str(first), "txt"))
    assert target.read_bytes() == b"previous completed output"
    assert output != target and output.read_bytes() == b"FIRST INPUT\n"
    assert not list(target.parent.glob("*.part"))


def unsupported_links(*args, **kwargs):
    raise OSError(errno.EOPNOTSUPP, "synthetic unsupported hard links")


def test_fallback_copy_retries_when_an_explicit_conversion_replaces_it(sources, monkeypatch):
    first, second, target = sources
    monkeypatch.setattr(convert, "_IS_WINDOWS", False)
    monkeypatch.setattr(os, "link", unsupported_links)
    matches = convert._copied_output_matches
    changed = []

    def complete_before_verification(path, owned, expected):
        if not changed:
            changed.append(True)
            convert.convert_file(str(second), "txt", out_path=str(target))
        return matches(path, owned, expected)

    monkeypatch.setattr(convert, "_copied_output_matches", complete_before_verification)
    output = Path(convert.convert_file(str(first), "txt"))
    assert changed and target.read_bytes() == b"SECOND INPUT\n"
    assert output != target and output.read_bytes() == b"FIRST INPUT\n"


def test_fallback_sync_failure_never_deletes_a_completed_explicit_output(sources, monkeypatch):
    from core import _checkpoint

    first, second, target = sources
    monkeypatch.setattr(convert, "_IS_WINDOWS", False)
    monkeypatch.setattr(os, "link", unsupported_links)
    original = first.read_bytes()

    def fail_sync(stream):
        # Close the public output so Windows also permits the explicit replace.
        stream.close()
        convert.convert_file(str(second), "txt", out_path=str(target))
        raise OSError("synthetic fallback sync failure")

    monkeypatch.setattr(_checkpoint, "_strict_sync", fail_sync)
    with pytest.raises(OSError, match="synthetic fallback sync failure"):
        convert.convert_file(str(first), "txt")
    assert target.read_bytes() == b"SECOND INPUT\n"
    assert first.read_bytes() == original
    assert not list(target.parent.glob("*.part"))


def test_fallback_sync_failure_retains_only_a_new_file_for_inspection(sources, monkeypatch):
    from core import _checkpoint

    first, _second, target = sources
    previous = target.with_name("captions (1).txt")
    previous.write_bytes(b"previous completed output")
    monkeypatch.setattr(convert, "_IS_WINDOWS", False)
    monkeypatch.setattr(os, "link", unsupported_links)

    def fail_sync(stream):
        raise OSError("synthetic fallback sync failure")

    monkeypatch.setattr(_checkpoint, "_strict_sync", fail_sync)
    with pytest.raises(OSError, match="synthetic fallback sync failure"):
        convert.convert_file(str(first), "txt")
    assert previous.read_bytes() == b"previous completed output"
    assert target.read_bytes() == b"FIRST INPUT\n"
    assert not list(target.parent.glob("*.part"))


def install_hooks(monkeypatch, callback):
    for name in ("replace", "rename", "link"):
        original = getattr(os, name)

        def hook(source, destination, *args, _original=original, **kwargs):
            callback(source, destination)
            return _original(source, destination, *args, **kwargs)

        monkeypatch.setattr(os, name, hook)


def test_automatic_commit_cannot_overwrite_a_completed_explicit_conversion(sources, monkeypatch):
    first, second, target = sources
    injected = []

    def finish_other_conversion(source, destination):
        if Path(destination) == target and not injected:
            injected.append(True)
            convert.convert_file(str(second), "txt", out_path=str(target))
            assert target.read_text(encoding="utf-8") == "SECOND INPUT\n"

    install_hooks(monkeypatch, finish_other_conversion)
    output = Path(convert.convert_file(str(first), "txt"))
    assert injected and target.read_text(encoding="utf-8") == "SECOND INPUT\n"
    assert output != target and output.read_text(encoding="utf-8") == "FIRST INPUT\n"


def test_failed_automatic_commit_never_unlinks_a_completed_explicit_conversion(sources, monkeypatch):
    first, second, target = sources
    failed = []
    injected = []
    unlink = os.unlink

    def fail_first_install(source, destination):
        if Path(destination) == target and not failed:
            failed.append(True)
            raise PermissionError("synthetic automatic publication failure")

    def cleanup_interleaving(path, *args, **kwargs):
        candidate = Path(path)
        if not injected and (candidate == target or (candidate.suffix == ".part" and not target.exists())):
            injected.append(True)
            convert.convert_file(str(second), "txt", out_path=str(target))
            assert target.read_text(encoding="utf-8") == "SECOND INPUT\n"
        return unlink(path, *args, **kwargs)

    install_hooks(monkeypatch, fail_first_install)
    monkeypatch.setattr(os, "unlink", cleanup_interleaving)
    with pytest.raises(PermissionError, match="synthetic automatic publication failure"):
        convert.convert_file(str(first), "txt")
    assert injected and target.read_text(encoding="utf-8") == "SECOND INPUT\n"
