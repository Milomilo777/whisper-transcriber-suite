"""Manual integration actions preserve originals and honor Keep existing."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from app.services import integrations_service as service
from core import _checkpoint, convert


@pytest.fixture
def integration(tmp_path, monkeypatch):
    source = tmp_path / "talk (1).srt"
    source.write_text("1\n00:00:00,000 --> 00:00:02,000\nCOMPLETE SPOKEN WORDS\n\n", encoding="utf-8")
    logs, status, errors = [], [], []
    app = SimpleNamespace(log=logs.append, status_var=SimpleNamespace(set=status.append))
    task = SimpleNamespace(file_path=str(tmp_path / "talk.mp4"), output_paths=[str(source)])
    monkeypatch.setattr(service, "show_error", lambda *args, **kwargs: errors.append(kwargs))
    monkeypatch.setattr(service.messagebox, "showwarning", lambda *args, **kwargs: pytest.fail("unexpected warning"))
    return service.IntegrationsService(app), task, source, logs, status, errors


def test_manual_export_keeps_a_file_created_during_rendering(integration, monkeypatch):
    api, task, source, logs, status, errors = integration
    target = source.with_suffix(".otr")
    render = service.srt_to_otr

    def other_editor_saves(*args):
        target.write_bytes(b"other editor's completed changes")
        return render(*args)

    monkeypatch.setattr(service, "srt_to_otr", other_editor_saves)
    api.export_task_to_otr(task)
    assert target.read_bytes() == b"other editor's completed changes"
    output = source.with_name(source.stem + " (1).otr")
    assert "COMPLETE SPOKEN WORDS" in json.loads(output.read_text())["text"]
    assert logs[-1] == f"Saved {output}" and output.name in status[-1]
    assert not errors


def test_keep_existing_also_preserves_a_late_numbered_file(integration, monkeypatch):
    api, task, source, logs, status, errors = integration
    target = source.with_suffix(".otr")
    target.write_bytes(b"first edited transcript")
    numbered = source.with_name(source.stem + " (1).otr")
    render = service.srt_to_otr
    monkeypatch.setattr(service.messagebox, "askyesnocancel", lambda *args, **kwargs: False)

    def other_editor_saves(*args):
        numbered.write_bytes(b"second edited transcript")
        return render(*args)

    monkeypatch.setattr(service, "srt_to_otr", other_editor_saves)
    api.export_task_to_otr(task)
    assert target.read_bytes() == b"first edited transcript"
    assert numbered.read_bytes() == b"second edited transcript"
    output = source.with_name(source.stem + " (2).otr")
    assert "COMPLETE SPOKEN WORDS" in json.loads(output.read_text())["text"]
    assert logs[-1] == f"Saved {output}" and output.name in status[-1] and not errors


@pytest.mark.parametrize("alias", [False, True])
def test_import_cannot_replace_its_original_otr_file(integration, monkeypatch, alias):
    api, task, source, logs, status, errors = integration
    original_path = source.with_suffix(".otr")
    original = service.srt_to_otr(str(source), "talk.mp4").encode("utf-8")
    original_path.write_bytes(original)
    selected = original_path.with_name("selected.srt") if alias else original_path
    if alias:
        os.link(original_path, selected)
    monkeypatch.setattr(service.filedialog, "askopenfilename", lambda **kwargs: str(original_path))
    monkeypatch.setattr(service.filedialog, "asksaveasfilename", lambda **kwargs: str(selected))
    api.import_otr_to_srt()
    assert original_path.read_bytes() == original
    assert selected.read_bytes() == original
    output = selected.with_suffix(".converted.srt")
    assert "COMPLETE SPOKEN WORDS" in output.read_text(encoding="utf-8")
    assert logs[-1] == f"Wrote {output}" and output.name in status[-1] and not errors


def test_atomic_integration_save_does_not_take_another_staging_file(tmp_path):
    target = tmp_path / "edited.otr"
    target.write_bytes(b"previous explicit target")
    foreign = Path(f"{target}.{os.getpid()}.part")
    foreign.write_bytes(b"another operation's recovery text")
    service._write_text_atomic(str(target), "complete replacement")
    assert foreign.read_bytes() == b"another operation's recovery text"
    assert target.read_bytes() == b"complete replacement"


def test_long_valid_selected_name_does_not_need_a_longer_staging_name(tmp_path):
    if os.name == "nt":
        tmp_path = Path(chr(92) * 2 + "?" + chr(92) + str(tmp_path.resolve()))
    target = tmp_path / ("x" * 245 + ".otr")
    target.write_bytes(b"previous explicit target")
    service._write_text_atomic(str(target), "complete replacement")
    assert target.read_bytes() == b"complete replacement"


def test_parallel_explicit_saves_keep_their_own_complete_staging(tmp_path, monkeypatch):
    target = tmp_path / "edited.otr"
    first_ready = threading.Event()
    second_ready = threading.Event()
    first_published = threading.Event()
    flush = _checkpoint._flush_to_disk

    def flush_together(stream):
        flush(stream)
        if threading.current_thread().name.endswith("_0"):
            first_ready.set()
            assert second_ready.wait(10)
        else:
            second_ready.set()
            assert first_published.wait(10)

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", flush_together)
    def save(text, first=False):
        try:
            service._write_text_atomic(str(target), text)
            return target.read_text(encoding="utf-8")
        finally:
            if first:
                first_published.set()

    # Both writes are staged together; publish in a known order to verify the
    # actual payload of EACH success without Windows rename-sharing noise.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="otr-save") as pool:
        first = pool.submit(save, "first complete save", True)
        assert first_ready.wait(10)
        second = pool.submit(save, "second complete save")
        assert first.result(timeout=15) == "first complete save"
        assert second.result(timeout=15) == "second complete save"
    assert not list(tmp_path.glob("*.part"))


def test_import_source_fallback_keeps_previous_converted_edits(integration, monkeypatch):
    api, task, source, logs, status, errors = integration
    original_path = source.with_suffix(".otr")
    original = service.srt_to_otr(str(source), "talk.mp4").encode("utf-8")
    original_path.write_bytes(original)
    previous = original_path.with_suffix(".converted.srt")
    previous.write_bytes(b"previous edited SRT conversion")
    monkeypatch.setattr(service.filedialog, "askopenfilename", lambda **kwargs: str(original_path))
    monkeypatch.setattr(service.filedialog, "asksaveasfilename", lambda **kwargs: str(original_path))
    api.import_otr_to_srt()
    output = previous.with_name(previous.stem + " (1).srt")
    assert original_path.read_bytes() == original
    assert previous.read_bytes() == b"previous edited SRT conversion"
    assert "COMPLETE SPOKEN WORDS" in output.read_text(encoding="utf-8")
    assert logs[-1] == f"Wrote {output}" and output.name in status[-1] and not errors


def test_failed_new_export_keeps_edits_and_never_reports_saved(integration, monkeypatch):
    api, task, source, logs, status, errors = integration
    previous = source.with_suffix(".otr")
    previous.write_bytes(b"previous edited OTR")
    monkeypatch.setattr(service.messagebox, "askyesnocancel", lambda *args, **kwargs: False)

    def fail_publish(staged, target):
        assert Path(staged).stat().st_size > 0
        raise PermissionError("synthetic export publication failure")

    monkeypatch.setattr(convert, "_install_new_output", fail_publish)
    api.export_task_to_otr(task)
    assert previous.read_bytes() == b"previous edited OTR"
    assert len(errors) == 1 and not logs and not status
    assert not list(source.parent.glob("*.part"))


def test_failed_explicit_import_keeps_previous_srt_and_original_otr(integration, monkeypatch):
    api, task, source, logs, status, errors = integration
    original_path = source.with_suffix(".otr")
    original = service.srt_to_otr(str(source), "talk.mp4").encode("utf-8")
    original_path.write_bytes(original)
    previous = source.read_bytes()
    monkeypatch.setattr(service.filedialog, "askopenfilename", lambda **kwargs: str(original_path))
    monkeypatch.setattr(service.filedialog, "asksaveasfilename", lambda **kwargs: str(source))

    def fail_flush(stream):
        stream.flush()
        assert Path(stream.name).stat().st_size > 0
        raise OSError("synthetic import write failure")

    monkeypatch.setattr(_checkpoint, "_flush_to_disk", fail_flush)
    api.import_otr_to_srt()
    assert source.read_bytes() == previous and original_path.read_bytes() == original
    assert len(errors) == 1 and not logs and not status
    assert not list(source.parent.glob("*.part"))
