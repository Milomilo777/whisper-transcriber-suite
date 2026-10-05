"""The "Try it now" sample clip in the quick start window and the app (see
docs/SAMPLE_CLIP.md); the clip itself and the packaging lists are in tests/core."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.dialogs import quick_start as qs
from core import hardware as hw
from core.task import TranscriptionTask

_CPU = hw.CudaStatus(usable=False, gpu_present=False)


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _open(root, tmp_path, **kwargs):
    results: list = []
    dialog = qs.QuickStartDialog(
        root, {"download_folder": str(tmp_path)}, on_done=results.append,
        probe=lambda: (_CPU, 4), **kwargs,
    )
    deadline = time.monotonic() + 60
    while dialog._hardware is None:
        assert time.monotonic() < deadline
        root.update()
        time.sleep(0.02)
    return dialog, results


def _button_texts(widget):
    for child in widget.winfo_children():
        if "text" in child.keys():
            yield str(child.cget("text"))
        yield from _button_texts(child)


# ------------------------------------------------------------ quick start window

def test_the_button_is_offered_only_when_the_app_can_run_the_clip(tk_root, tmp_path):
    without, _ = _open(tk_root, tmp_path)
    assert "Finish and try it now" not in set(_button_texts(without))
    without.skip()
    with_clip, _ = _open(tk_root, tmp_path, on_try_sample=MagicMock())
    assert "Finish and try it now" in set(_button_texts(with_clip))
    with_clip.skip()


def test_finish_and_try_saves_the_choice_first_then_runs_the_clip(tk_root, tmp_path):
    order: list = []
    results: list = []

    def done(choice):
        order.append("choice")
        results.append(choice)

    dialog = qs.QuickStartDialog(
        tk_root, {"download_folder": str(tmp_path)}, on_done=done,
        probe=lambda: (_CPU, 4), on_try_sample=lambda: order.append("sample"),
    )
    dialog.finish_and_try_sample()
    assert order == ["choice", "sample"]
    assert results[0] is not None and results[0].output_folder == str(tmp_path)


def test_finish_without_a_folder_does_not_run_the_clip(tk_root, monkeypatch):
    monkeypatch.setattr(qs.messagebox, "showwarning", MagicMock())
    sample = MagicMock()
    dialog = qs.QuickStartDialog(
        tk_root, {"download_folder": ""}, on_done=MagicMock(), probe=lambda: (_CPU, 4),
        on_try_sample=sample,
    )
    dialog.folder_var.set("")
    dialog.finish_and_try_sample()
    sample.assert_not_called()
    assert dialog.winfo_exists()
    dialog.skip()


def test_skip_and_plain_finish_never_run_the_clip(tk_root, tmp_path):
    sample = MagicMock()
    dialog, _ = _open(tk_root, tmp_path, on_try_sample=sample)
    dialog.finish()
    dialog2, _ = _open(tk_root, tmp_path, on_try_sample=sample)
    dialog2.skip()
    sample.assert_not_called()


# ------------------------------------------------------------ app methods

def _fake_app(**extra):
    return SimpleNamespace(
        log=MagicMock(), queue=[], pb={}, nb=MagicMock(), t2=object(), refresh=MagicMock(),
        _ensure_transcribe_ready=MagicMock(return_value=True), **extra,
    )


def test_try_sample_queues_the_working_copy_in_english_and_opens_it_when_done(
    monkeypatch, tmp_path,
):
    import app.app as app_mod
    from core import sample_clip

    clip = tmp_path / "sample_clip.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(sample_clip, "prepare_working_copy", lambda: str(clip))
    fake = _fake_app()
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    (task,) = fake.queue
    assert task.file_path == str(clip) and task.language == "en"
    assert task.open_when_done is True
    assert task.clip_start is None and task.clip_end is None
    fake.refresh.assert_called_once()


def test_a_second_click_while_the_clip_is_queued_adds_nothing(monkeypatch, tmp_path):
    import app.app as app_mod
    from core import sample_clip

    monkeypatch.setattr(sample_clip, "prepare_working_copy", lambda: str(tmp_path / "c.mp3"))
    fake = _fake_app()
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    assert len(fake.queue) == 1
    fake.queue[0].status = "finished"
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    assert len(fake.queue) == 2  # a finished run does not block a new one


def test_try_sample_stops_when_the_model_gate_says_no(monkeypatch, tmp_path):
    import app.app as app_mod
    from core import sample_clip

    monkeypatch.setattr(sample_clip, "prepare_working_copy", lambda: str(tmp_path / "c.mp3"))
    fake = _fake_app()
    fake._ensure_transcribe_ready.return_value = False
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    assert fake.queue == []


def test_try_sample_reports_a_missing_clip_and_a_copy_failure(monkeypatch):
    import app.app as app_mod
    from core import sample_clip

    fake = _fake_app()
    monkeypatch.setattr(sample_clip, "prepare_working_copy", lambda: None)
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    assert fake.queue == [] and "missing" in fake.log.call_args[0][0]
    fake._ensure_transcribe_ready.assert_not_called()

    def boom():
        raise PermissionError("denied")

    shown = MagicMock()
    monkeypatch.setattr(app_mod, "show_error", shown)
    monkeypatch.setattr(sample_clip, "prepare_working_copy", boom)
    app_mod.App.try_sample_clip(fake)  # type: ignore[arg-type]
    shown.assert_called_once()
    assert fake.queue == []


def test_the_result_opens_in_the_viewer_else_as_a_file(tmp_path):
    import app.app as app_mod

    js = tmp_path / "sample_clip.json"
    srt = tmp_path / "sample_clip.srt"
    js.write_text("[]", encoding="utf-8")
    srt.write_text("1", encoding="utf-8")
    task = TranscriptionTask(str(tmp_path / "sample_clip.mp3"))
    task.output_paths = [str(srt), str(js)]
    fake = SimpleNamespace(
        _task_json_output=app_mod.App._task_json_output, open_transcript_viewer_for=MagicMock(),
        _open_file=MagicMock(), log=MagicMock(),
    )
    app_mod.App.open_sample_result(fake, task)  # type: ignore[arg-type]
    fake.open_transcript_viewer_for.assert_called_once_with(task.file_path, str(js))
    fake._open_file.assert_not_called()

    os.remove(js)
    app_mod.App.open_sample_result(fake, task)  # type: ignore[arg-type]
    fake._open_file.assert_called_once_with(str(srt))

    os.remove(srt)
    fake.log.reset_mock()
    app_mod.App.open_sample_result(fake, task)  # type: ignore[arg-type]
    assert "no transcript file" in fake.log.call_args[0][0]


def test_a_finished_sample_task_triggers_the_viewer_and_a_normal_one_does_not():
    from app.services.transcription_service import TranscriptionService

    results = []
    for flag in (True, False):
        task = TranscriptionTask("a.mp3")
        task.open_when_done = flag
        app = MagicMock()
        app.app_config = {}
        app.history = None
        app.queue = []
        service = TranscriptionService(app)
        service._derive_transcript_stats = lambda _t: (0, 0.0)  # type: ignore[method-assign]
        service._post_usage_stats = MagicMock()  # type: ignore[method-assign]
        worker = {"task": task}
        service.finish_task(worker)
        results.append(app.open_sample_result.call_count)
    assert results == [1, 0]
