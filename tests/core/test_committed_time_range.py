"""Submission checks without constructing a window."""
from types import SimpleNamespace

import pytest

from app.app import App
from core.task import TranscriptionTask


class _Var:
    def __init__(self, text):
        self.text = text

    def get(self):
        return self.text


def _app(start, end):
    return SimpleNamespace(
        transcribe_start_time_var=_Var(start), transcribe_end_time_var=_Var(end),
        app_config={}, _selected_transcribe_language=lambda: None,
    )


@pytest.mark.parametrize("start,end", [("oops", ""), ("", "1:99"), ("5", "4"),
                                           ("2", "2"), ("nan", ""), ("", "-0")])
def test_invalid_committed_range_is_refused_without_losing_input(monkeypatch, start, end):
    notices = []
    monkeypatch.setattr("app.app.show_error", lambda *args, **kw: notices.append(args[2]))
    app = _app(start, end)
    task = TranscriptionTask("recording.wav")
    assert App._apply_task_options(app, task) is False
    assert notices and len(notices[0]) < 80
    assert app.transcribe_start_time_var.get() == start
    assert app.transcribe_end_time_var.get() == end
    assert task.clip_start is None and task.clip_end is None


# Both fields start at 0:00:00 in the tab: that default must stay "the whole file",
# and a start with the end left at its default must run to the end of the file.
@pytest.mark.parametrize("start,end,expected", [("0:00:00", "0:00:00", (None, None)),
    ("0", "10", (None, 10.0)), ("", "0", (None, None)), ("", "", (None, None)),
    ("5:00", "0:00:00", (300.0, None)),
    (" 0:00:00\r\n", " 1:30 ", (None, 90.0)), ("\u06f0", "\u06f1", (None, 1.0))])
def test_valid_committed_range_treats_zero_as_unset(start, end, expected):
    task = TranscriptionTask("recording.wav")
    assert App._apply_task_options(_app(start, end), task) is True
    assert (task.clip_start, task.clip_end) == expected


@pytest.mark.parametrize("bulk", [False, True])
def test_invalid_range_never_reaches_queue(monkeypatch, tmp_path, bulk):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"audio")
    notices = []
    monkeypatch.setattr("app.app.show_error", lambda *args, **kw: notices.append(args[2]))
    app = _app("1:99", "10")
    app.queue = []
    app.fv = _Var(str(path))
    app._confirm_english_only_model = lambda: True
    app._ensure_transcribe_ready = lambda: True
    app._apply_task_options = lambda task: App._apply_task_options(app, task)
    # Any later queue/UI action is a failure, including duplicate detection.
    app._same_job_active = lambda task: pytest.fail("invalid range passed validation")
    if bulk:
        assert App._bulk_enqueue(app, [str(path)]) == 0
    else:
        App.add(app)
    assert app.queue == [] and len(notices) == 1
    assert app.transcribe_start_time_var.get() == "1:99"
