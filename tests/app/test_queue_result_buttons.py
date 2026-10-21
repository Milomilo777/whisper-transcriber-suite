"""The Queue offers a finished job's result as buttons: "View transcript", "Open output folder".

Before, a finished row opened its result only by right-click or double-click, and the
double-click opened the SOURCE folder even when the transcript was written elsewhere
(screenshot review, 2026-10-21). Windowless: fakes stand in for Tk.
"""
from __future__ import annotations

import types

from app.app import App
from app.widgets.tabs import queue_result_task


def _task(status: str, tmp_path=None, out_dir=None, json: bool = False) -> types.SimpleNamespace:
    outputs = []
    if out_dir is not None:
        out_dir.mkdir(exist_ok=True)
        out = out_dir / "talk.srt"
        out.write_text("1\n", encoding="utf-8")
        outputs.append(str(out))
        if json:
            transcript = out_dir / "talk.json"
            transcript.write_text("{}", encoding="utf-8")
            outputs.append(str(transcript))
    src = str(tmp_path / "talk.mp3") if tmp_path is not None else "talk.mp3"
    return types.SimpleNamespace(
        status=status, file_path=src, output_paths=outputs, language="", detected_language="en",
    )


class _Button:
    def __init__(self) -> None:
        self.enabled: bool | None = None
        self.text = "Open output folder"

    def cget(self, _key: str) -> str:
        return self.text

    def configure(self, text: str) -> None:
        self.text = text


def _fake_app(selected: list) -> types.SimpleNamespace:
    calls: list = []
    fake = types.SimpleNamespace(
        queue_action_buttons={"remove": _Button()}, queue_result_buttons={"view": _Button(), "folder": _Button()},
        _selected_tasks=lambda: selected, _task_has_checkpoint=lambda _t: False,
        _sync_queue_failure_line=lambda: None, calls=calls,
        _open_folder=lambda folder, select=None: calls.append(("folder", folder, select)),
        _task_json_output=lambda t: "talk.json",
        open_transcript_viewer_for=lambda *a: calls.append(("view",) + a),
    )
    for name in ("_update_queue_action_bar", "_action_bar_view_transcript", "_action_bar_open_folder",
                 "_open_task_output_folder"):
        setattr(fake, name, getattr(App, name).__get__(fake))
    return fake


def test_only_one_finished_row_has_a_result() -> None:
    done = _task("finished")
    assert queue_result_task([done]) is done
    assert queue_result_task([]) is None
    assert queue_result_task([_task("error")]) is None
    assert queue_result_task([_task("running")]) is None
    assert queue_result_task([done, _task("finished")]) is None


def test_the_buttons_follow_the_selection(monkeypatch, tmp_path) -> None:
    import app.app as app_mod

    monkeypatch.setattr(app_mod, "_set_enabled", lambda btn, on: setattr(btn, "enabled", on))
    fake = _fake_app([_task("finished", tmp_path, out_dir=tmp_path / "out", json=True)])
    fake._update_queue_action_bar()
    assert [b.enabled for b in fake.queue_result_buttons.values()] == [True, True]
    fake._selected_tasks = lambda: [_task("cancelled")]
    fake._update_queue_action_bar()
    assert [b.enabled for b in fake.queue_result_buttons.values()] == [False, False]


def test_view_transcript_opens_the_viewer() -> None:
    fake = _fake_app([_task("finished")])
    fake._action_bar_view_transcript()
    assert fake.calls == [("view", "talk.mp3", "talk.json", "en")]


def test_open_folder_opens_where_the_transcript_is(tmp_path) -> None:
    task = _task("finished", tmp_path, out_dir=tmp_path / "outputs")
    fake = _fake_app([task])
    fake._action_bar_open_folder()
    assert fake.calls == [("folder", str(tmp_path / "outputs"), str(tmp_path / "outputs" / "talk.srt"))]


def test_double_click_opens_the_output_folder_too(tmp_path) -> None:
    task = _task("finished", tmp_path, out_dir=tmp_path / "outputs")
    fake = _fake_app([])
    fake.tree = types.SimpleNamespace(identify_row=lambda _y: "I0")
    fake.row_map = {"I0": task}
    App.queue_row_double_click(fake, types.SimpleNamespace(y=5))  # type: ignore[arg-type]
    assert fake.calls == [("folder", str(tmp_path / "outputs"), str(tmp_path / "outputs" / "talk.srt"))]


def test_nothing_happens_without_a_finished_row() -> None:
    fake = _fake_app([_task("error")])
    fake._action_bar_view_transcript()
    fake._action_bar_open_folder()
    assert fake.calls == []


def test_view_needs_a_transcript_json(monkeypatch, tmp_path) -> None:
    """Without one the viewer asks the user to pick a .json by hand (review, 2026-10-21)."""
    import app.app as app_mod

    monkeypatch.setattr(app_mod, "_set_enabled", lambda btn, on: setattr(btn, "enabled", on))
    fake = _fake_app([_task("finished", tmp_path, out_dir=tmp_path / "out")])  # .srt only
    fake._update_queue_action_bar()
    assert fake.queue_result_buttons["view"].enabled is False
    assert fake.queue_result_buttons["folder"].enabled is True
