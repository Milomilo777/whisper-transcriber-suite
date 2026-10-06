"""The dialogs behind the "Open in Subtitle Edit" button, with every system call mocked."""
from __future__ import annotations

import types
from typing import Any

import pytest

from app.widgets import subtitle_edit as ui
from core import subtitle_edit as se


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    log: dict[str, list[Any]] = {"ask": [], "warn": [], "web": [], "open": [], "error": []}
    monkeypatch.setattr(
        ui.messagebox, "askyesno", lambda *a, **k: log["ask"].append(a) or log.get("yes", True)
    )
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: log["warn"].append(a))
    monkeypatch.setattr(ui.messagebox, "showerror", lambda *a, **k: log["error"].append(a))
    monkeypatch.setattr(ui.webbrowser, "open", lambda url: log["web"].append(url))
    monkeypatch.setattr(
        se, "open_in_subtitle_edit", lambda exe, path: log["open"].append((exe, path))
    )
    return log


PARENT: Any = types.SimpleNamespace(winfo_toplevel=lambda: object())


def test_missing_program_offers_the_official_page_only_on_yes(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    monkeypatch.setattr(se, "find_subtitle_edit", lambda _p="": None)
    ui.open_in_subtitle_edit(PARENT, {}, "a.srt")
    assert len(calls["ask"]) == 1
    assert calls["web"] == [se.DOWNLOAD_URL]
    assert calls["open"] == []


def test_missing_program_and_a_no_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    monkeypatch.setattr(se, "find_subtitle_edit", lambda _p="": None)
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: False)
    ui.open_in_subtitle_edit(PARENT, {}, "a.srt")
    assert calls["web"] == []
    assert calls["open"] == []


def test_found_program_opens_the_subtitle_without_any_dialog(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        se, "find_subtitle_edit", lambda p="": seen.append(p) or "C:\\SE\\SubtitleEdit.exe"
    )
    ui.open_in_subtitle_edit(PARENT, {se.CONFIG_KEY: "D:\\SE\\SubtitleEdit.exe"}, "a.srt")
    assert seen == ["D:\\SE\\SubtitleEdit.exe"]
    assert calls["open"] == [("C:\\SE\\SubtitleEdit.exe", "a.srt")]
    assert calls["ask"] == [] and calls["warn"] == [] and calls["web"] == []


def test_no_subtitle_file_warns_instead_of_starting_the_program(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    monkeypatch.setattr(se, "find_subtitle_edit", lambda _p="": "C:\\SE\\SubtitleEdit.exe")
    ui.open_in_subtitle_edit(PARENT, {}, None)
    assert len(calls["warn"]) == 1
    assert calls["open"] == []


def test_a_subtitle_deleted_after_the_click_is_reported(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    monkeypatch.setattr(se, "find_subtitle_edit", lambda _p="": "C:\\SE\\SubtitleEdit.exe")

    def gone(_exe: str, _path: str) -> None:
        raise FileNotFoundError("a.srt")

    monkeypatch.setattr(se, "open_in_subtitle_edit", gone)
    ui.open_in_subtitle_edit(PARENT, {}, "a.srt")
    assert len(calls["warn"]) == 1


def test_a_program_that_cannot_start_shows_an_error(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]],
) -> None:
    monkeypatch.setattr(se, "find_subtitle_edit", lambda _p="": "C:\\SE\\SubtitleEdit.exe")

    def broken(_exe: str, _path: str) -> None:
        raise PermissionError("blocked")

    monkeypatch.setattr(se, "open_in_subtitle_edit", broken)
    ui.open_in_subtitle_edit(PARENT, {}, "a.srt")
    assert len(calls["error"]) == 1


def test_the_button_text_and_help_name_the_program() -> None:
    assert "Subtitle Edit" in ui.BUTTON_TEXT
    assert "Subtitle Edit" in ui.HELP_TEXT


def test_the_save_in_advanced_writes_the_path() -> None:
    from tests.core.test_advanced_simplified import _base_cfg, _fake_app, _fake_dialog, _V
    from app.dialogs import advanced as adv

    cfg = _base_cfg()
    orig = adv.save_config
    adv.save_config = lambda _c: None  # type: ignore[assignment]
    try:
        adv.AdvancedDialog._save_and_close(  # type: ignore[arg-type]
            _fake_dialog(_fake_app(cfg), _subtitle_edit_path=_V('  D:\\SE\\SubtitleEdit.exe '))
        )
    finally:
        adv.save_config = orig
    assert cfg[se.CONFIG_KEY] == "D:\\SE\\SubtitleEdit.exe"


def _walk(widget: Any):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _viewer_with_srt(tmp_path, make_srt: bool):
    import json

    tk = pytest.importorskip("tkinter")
    from app.dialogs.transcript_viewer import TranscriptViewer

    jp = tmp_path / "talk نمونه.json"
    jp.write_text(json.dumps([{"start": 0.0, "end": 1.0, "text": "Hi"}]), encoding="utf-8")
    if make_srt:
        (tmp_path / "talk نمونه.srt").write_text("1\n", encoding="utf-8")
    root = tk.Tk()
    root.withdraw()
    return root, TranscriptViewer(root, str(jp))


def test_viewer_button_opens_the_srt_next_to_the_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.dialogs import transcript_viewer as tv

    monkeypatch.setattr(se, "is_supported", lambda platform=None: True)
    root, viewer = _viewer_with_srt(tmp_path, make_srt=True)
    got: list[Any] = []
    monkeypatch.setattr(tv.subtitle_edit_ui, "open_in_subtitle_edit",
                        lambda parent, cfg, path: got.append(path))
    try:
        viewer.withdraw()
        viewer._open_in_subtitle_edit()
        assert got == [str(tmp_path / "talk نمونه.srt")]
    finally:
        viewer._on_close()
        root.destroy()


def test_viewer_button_passes_none_when_no_subtitle_was_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.dialogs import transcript_viewer as tv

    root, viewer = _viewer_with_srt(tmp_path, make_srt=False)
    got: list[Any] = []
    monkeypatch.setattr(tv.subtitle_edit_ui, "open_in_subtitle_edit",
                        lambda parent, cfg, path: got.append(path))
    try:
        viewer.withdraw()
        viewer._open_in_subtitle_edit()
        assert got == [None]
    finally:
        viewer._on_close()
        root.destroy()


@pytest.mark.parametrize(("supported", "expected"), [(True, 1), (False, 0)])
def test_viewer_shows_the_button_only_where_supported(
    monkeypatch: pytest.MonkeyPatch, tmp_path, supported: bool, expected: int,
) -> None:
    monkeypatch.setattr(se, "is_supported", lambda platform=None: supported)
    root, viewer = _viewer_with_srt(tmp_path, make_srt=True)
    try:
        viewer.withdraw()
        labels = [
            w.cget("text") for w in _walk(viewer)
            if w.winfo_class() == "TButton"
        ]
        assert labels.count(ui.BUTTON_TEXT) == expected
    finally:
        viewer._on_close()
        root.destroy()
