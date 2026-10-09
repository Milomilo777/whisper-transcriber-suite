"""Transcript viewer exports: never block the window, never overwrite what is not ours.

Opening and saving used to rebuild the Word export on the Tk thread (35 s for 20,000 segments).
Now both run in worker threads; and a file is left alone (and named) when it is a link, was
changed while it was being rebuilt, differs from the saved transcript in any Word part, or
could not be read. Failure notices say the file still holds the OLD text.
"""
from __future__ import annotations

import io
import os
import shutil
import time
import zipfile
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402
from app.dialogs import viewer_exports as ve  # noqa: E402
import core.writers as writers  # noqa: E402

OLD, NEW = "Hello world", "Edited in the viewer"


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    got: list[tuple[str, str]] = []
    monkeypatch.setattr(tv, "notify", lambda _w, text, kind="info", **_k: got.append((text, kind)))
    return got


def _segments(count: int = 2) -> list[dict[str, Any]]:
    return [
        {"start": i * 1.5, "end": i * 1.5 + 1.25,
         "text": OLD if i == 0 else f"Segment number {i} of the talk"}
        for i in range(count)
    ]


def _make(tmp_path, formats: list[str], count: int = 2) -> str:
    from core.transcriber import _write_outputs as write_outputs

    written = write_outputs(str(tmp_path / "talk"), _segments(count), str(tmp_path / "talk.mp4"), formats)
    return next(p for p in written if p.endswith(".json"))


def _open(root, json_path: str, wait: bool = True) -> tv.TranscriptViewer:
    viewer = tv.TranscriptViewer(root, json_path)
    viewer.withdraw()
    if wait:
        viewer._finish_exports()
    return viewer


def _close(viewer: tv.TranscriptViewer) -> None:
    viewer._finish_exports()
    viewer._dirty = False
    viewer._on_close()


def _edit(viewer: tv.TranscriptViewer, text: str = NEW) -> None:
    tv._set_segment_text(viewer.segments[0], text)
    viewer._dirty = True


def _text(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _warnings(notices) -> str:
    return " ".join(t for t, kind in notices if kind == "warning")


# --- 1: the window never waits for a long Word build ------------------------------


def _slow_docx(monkeypatch, seconds: float) -> list[float]:
    real = writers.BINARY_WRITERS["docx"]
    started: list[float] = []

    def slow(segments, audio_path=""):
        started.append(time.monotonic())
        time.sleep(seconds)
        return real(segments, audio_path)

    monkeypatch.setitem(writers.BINARY_WRITERS, "docx", slow)
    return started


def test_opening_does_not_wait_for_the_word_build(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "docx", "json"], count=300)
    _slow_docx(monkeypatch, 3.0)
    t0 = time.monotonic()
    viewer = _open(root, json_path, wait=False)
    opened_in = time.monotonic() - t0
    try:
        assert opened_in < 1.5, f"open blocked for {opened_in:.1f} s"
        assert not viewer._scan_done.is_set()  # the Word check is still running
        viewer._finish_exports()
        assert len(viewer._synced_siblings) == 3  # and it ends with every file matched
    finally:
        _close(viewer)


def test_save_does_not_wait_for_the_word_build(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "docx", "json"], count=300)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 3.0)
    try:
        _edit(viewer)
        t0 = time.monotonic()
        viewer._save_changes()
        saved_in = time.monotonic() - t0
        assert saved_in < 1.5, f"Save blocked for {saved_in:.1f} s"
        assert NEW in _text(json_path)  # persist first: the JSON is already on disk
        assert not viewer._export_idle.is_set()  # the Word file is still being built
        assert "Saved 300 segment(s)" in notices[-1][0]
        viewer._wait_for_subtitle_files()  # quick files do not wait for the Word build
        assert NEW in _text(tmp_path / "talk.srt") and NEW in _text(tmp_path / "talk.txt")
        assert not viewer._export_idle.is_set()
        viewer._finish_exports()
        assert any(t.startswith("Updated") and "talk.docx" in t for t, _k in notices)
    finally:
        _close(viewer)


def test_the_window_keeps_running_while_the_exports_build(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["docx", "json"], count=50)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 1.5)
    try:
        _edit(viewer)
        viewer._save_changes()
        longest = 0.0
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            t0 = time.monotonic()
            root.update()
            longest = max(longest, time.monotonic() - t0)
            time.sleep(0.01)
        assert longest < 0.5 and not viewer._export_idle.is_set()
    finally:
        _close(viewer)


def test_two_quick_saves_end_with_the_last_text(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "docx", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 0.5)
    try:
        for text in ("first", "second", "third"):
            _edit(viewer, text)
            viewer._save_changes()
        viewer._finish_exports()
        assert "third" in _text(tmp_path / "talk.srt")
        body = zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")
        assert "third" in body and "second" not in body
        assert not list(tmp_path.glob("*.part"))
    finally:
        _close(viewer)


def test_real_writers_on_a_moderate_transcript_open_and_save_off_the_ui_thread(
    root, tmp_path, notices
) -> None:
    """The real Word writer (about a second for this size): the calls return before it ends."""
    json_path = _make(tmp_path, ["srt", "md", "docx", "json"], count=1500)
    t0 = time.monotonic()
    viewer = _open(root, json_path, wait=False)
    open_ui = time.monotonic() - t0
    try:
        assert not viewer._scan_done.is_set()
        viewer._finish_exports()
        _edit(viewer)
        t0 = time.monotonic()
        viewer._save_changes()
        save_ui = time.monotonic() - t0
        assert not viewer._export_idle.is_set()
        viewer._finish_exports()
        assert NEW in _text(tmp_path / "talk.md")
        assert NEW in zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")
        assert open_ui < 2.0 and save_ui < 1.0, (open_ui, save_ui)
    finally:
        _close(viewer)


def test_twenty_thousand_segments_check_and_rebuild_the_quick_files_in_bounded_time(tmp_path) -> None:
    """No Tk: the pure functions on a big transcript with the quick writers (no Word file)."""
    json_path = _make(tmp_path, ["srt", "vtt", "txt", "md", "tsv", "lrc", "json"], count=20000)
    segments = ve.segments_from_json(_text(json_path))
    assert len(segments) == 20000
    t0 = time.monotonic()
    scan = ve.scan_exports(json_path, segments, None)
    scan_s = time.monotonic() - t0
    assert len(scan.synced) == 6 and not scan.unchecked
    segments[0]["text"] = NEW
    t0 = time.monotonic()
    report = ve.update_exports(json_path, segments, scan)
    update_s = time.monotonic() - t0
    assert len(report.updated) == 6 and not report.old_text_files()
    assert scan_s < 20 and update_s < 20, (scan_s, update_s)


# --- 2: honest messages -----------------------------------------------------------


def test_a_failed_update_says_the_file_still_holds_the_old_text(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    viewer = _open(root, json_path)

    def boom(_segments, _audio_path=""):
        raise RuntimeError("locked")

    monkeypatch.setitem(writers.WRITERS, "txt", boom)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        warning = _warnings(notices)
        assert "talk.txt" in warning and "OLD text" in warning
        assert "changed outside" not in warning
    finally:
        _close(viewer)


def test_a_file_that_does_not_match_gets_a_neutral_message(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    (tmp_path / "talk.txt").write_text("something else entirely\n", encoding="utf-8")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        warning = _warnings(notices)
        assert "talk.txt" in warning and "does not match this transcript's last saved version" in warning
        assert "outside the viewer" not in warning
    finally:
        _close(viewer)


def test_a_file_unreadable_at_open_is_reported_as_unchecked(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    real = ve.read_bytes
    monkeypatch.setattr(ve, "read_bytes", lambda p: None if p.endswith("talk.txt") else real(p))
    viewer = _open(root, json_path)
    monkeypatch.setattr(ve, "read_bytes", real)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        warning = _warnings(notices)
        assert "talk.txt" in warning and "could not be read or checked" in warning
        assert "does not match" not in warning
        assert OLD in _text(tmp_path / "talk.txt") and NEW in _text(tmp_path / "talk.srt")
    finally:
        _close(viewer)


# --- 3: any Word part changed elsewhere counts -------------------------------------


def _rewrite_zip_part(path, name: str, patch) -> None:
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in items:
            out.writestr(info.filename, patch(data) if info.filename == name else data)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def test_a_word_file_with_changed_styles_is_left_alone(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["docx", "srt", "json"])
    docx = tmp_path / "talk.docx"
    _rewrite_zip_part(docx, "word/styles.xml", lambda d: d + b"<!-- house style -->")
    before = docx.read_bytes()
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        assert docx.read_bytes() == before
        assert "talk.docx" in _warnings(notices)
    finally:
        _close(viewer)


def test_a_word_file_differing_only_in_its_save_time_still_matches(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["docx", "json"])
    _rewrite_zip_part(tmp_path / "talk.docx", "docProps/core.xml", lambda d: d + b"<!-- saved later -->")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        body = zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")
        assert NEW in body and not _warnings(notices)
    finally:
        _close(viewer)


# --- 4: the file changes while it is being rebuilt ----------------------------------


def test_a_file_changed_during_the_rebuild_is_left_alone_and_named(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    viewer = _open(root, json_path)
    real = writers.WRITERS["txt"]
    txt = tmp_path / "talk.txt"

    def build_while_someone_edits(segments, audio_path=""):
        body = real(segments, audio_path)
        with open(txt, "a", encoding="utf-8") as f:  # an editor saves meanwhile
            f.write("added by hand\n")
        return body

    monkeypatch.setitem(writers.WRITERS, "txt", build_while_someone_edits)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        assert _text(txt).endswith("added by hand\n") and OLD in _text(txt)
        assert NEW in _text(tmp_path / "talk.srt")
        warning = _warnings(notices)
        assert "talk.txt" in warning and "changed while Save was rebuilding" in warning
        assert not list(tmp_path.glob("*.part"))
    finally:
        _close(viewer)


# --- 5: links are never replaced -----------------------------------------------------


def test_a_hard_linked_export_is_skipped_and_named(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    other = tmp_path / "elsewhere.txt"
    try:
        os.link(tmp_path / "talk.txt", other)
    except (OSError, NotImplementedError):  # pragma: no cover - no hard links here
        pytest.skip("hard links unavailable")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        assert OLD in _text(tmp_path / "talk.txt") and OLD in _text(other)
        assert "talk.txt" in _warnings(notices) and "link" in _warnings(notices)
        assert NEW in _text(tmp_path / "talk.srt")
    finally:
        _close(viewer)


def test_a_symlinked_export_is_skipped_and_its_target_untouched(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    target = tmp_path / "real_notes.txt"
    shutil.move(str(tmp_path / "talk.txt"), target)
    try:
        os.symlink(target, tmp_path / "talk.txt")
    except (OSError, NotImplementedError):  # pragma: no cover - needs a privilege on Windows
        pytest.skip("symlinks unavailable")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        assert os.path.islink(tmp_path / "talk.txt")  # still a link, not a regular file
        assert OLD in _text(target)
        assert "talk.txt" in _warnings(notices) and "link" in _warnings(notices)
    finally:
        _close(viewer)


# --- 6: files made from the transcript that Save does not rebuild are named -----------


def test_bilingual_and_chapter_files_are_named_not_touched(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["srt", "json"])
    bilingual = tmp_path / "talk.bilingual.fa.srt"
    chapters = tmp_path / "talk.chapters.json"
    bilingual.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\nسلام\n", encoding="utf-8")
    chapters.write_text("[]\n", encoding="utf-8")
    (tmp_path / "other.chapters.json").write_text("[]\n", encoding="utf-8")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        info = " ".join(t for t, kind in notices if kind == "info")
        assert "talk.bilingual.fa.srt" in info and "talk.chapters.json" in info
        assert "other.chapters.json" not in info
        assert "Hello" in _text(bilingual) and _text(chapters) == "[]\n"
    finally:
        _close(viewer)


def test_every_file_is_in_exactly_one_report_list(tmp_path) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    (tmp_path / "talk.pdf").write_bytes(b"%PDF")
    segments = ve.segments_from_json(_text(json_path))
    scan = ve.scan_exports(json_path, segments, None)
    (tmp_path / "talk.txt").write_text("changed\n", encoding="utf-8")
    report = ve.update_exports(json_path, segments, scan)
    names = sorted(os.path.basename(p) for p in report.updated + report.old_text_files())
    assert names == ["talk.pdf", "talk.srt", "talk.txt"]


def test_workers_keep_thread_switches_frequent_and_restore_the_setting() -> None:
    import sys

    before = sys.getswitchinterval()
    with ve.responsive_threads():
        inside = sys.getswitchinterval()
        with ve.responsive_threads():
            assert sys.getswitchinterval() == inside
        assert sys.getswitchinterval() == inside  # the inner exit must not restore early
    assert inside < before and sys.getswitchinterval() == before


def test_closing_while_the_exports_build_cancels_the_poll_and_loses_nothing(
    root, tmp_path, notices, monkeypatch
) -> None:
    json_path = _make(tmp_path, ["srt", "docx", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 0.5)
    _edit(viewer)
    viewer._save_changes()
    assert viewer._export_poll_id is not None
    viewer._dirty = False
    viewer._on_close()  # the window goes; the worker finishes the files on its own
    assert viewer._export_poll_id is None
    deadline = time.monotonic() + 20
    while not viewer._export_idle.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert NEW in _text(tmp_path / "talk.srt")
    assert NEW in zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")


# --- round 2: exit waits, quick-file waiters, poll race, logging, damaged zips -------------


def _slow_writer(monkeypatch, name: str, seconds: float) -> None:
    real = writers.WRITERS[name]

    def slow(segments, audio_path=""):
        time.sleep(seconds)
        return real(segments, audio_path)

    monkeypatch.setitem(writers.WRITERS, name, slow)


def test_exit_waits_for_a_running_word_rebuild(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _make(tmp_path, ["srt", "docx", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 1.0)
    _edit(viewer)
    viewer._save_changes()
    assert not viewer._export_idle.is_set()
    shown: list[int] = []
    left = tv.finish_exports_before_exit(timeout=15, on_wait=shown.append, pump=root.update)
    assert left == [] and viewer._export_idle.is_set() and shown  # it said why it waited
    body = zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")
    assert NEW in body
    _close(viewer)


def test_exit_wait_is_bounded_and_names_what_was_not_rebuilt(
    root, tmp_path, notices, monkeypatch, caplog
) -> None:
    json_path = _make(tmp_path, ["srt", "docx", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 2.5)
    _edit(viewer)
    viewer._save_changes()
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger=tv.logger.name):
        left = tv.finish_exports_before_exit(timeout=0.4)
    assert time.monotonic() - t0 < 1.5  # never for ever
    assert [os.path.basename(p) for p in left] == ["talk.docx"]  # srt was done, docx was not
    assert "talk.docx" in caplog.text
    _close(viewer)


def test_exit_also_waits_for_a_viewer_closed_during_the_rebuild(
    root, tmp_path, notices, monkeypatch
) -> None:
    json_path = _make(tmp_path, ["docx", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_docx(monkeypatch, 1.0)
    _edit(viewer)
    viewer._save_changes()
    viewer._dirty = False
    viewer._on_close()
    assert tv.finish_exports_before_exit(timeout=15) == []
    body = zipfile.ZipFile(tmp_path / "talk.docx").read("word/document.xml").decode("utf-8")
    assert NEW in body


def test_exit_with_nothing_running_returns_at_once(root, tmp_path, notices) -> None:
    json_path = _make(tmp_path, ["srt", "json"])
    viewer = _open(root, json_path)
    t0 = time.monotonic()
    assert tv.finish_exports_before_exit(timeout=30) == []
    assert time.monotonic() - t0 < 0.5
    _close(viewer)


def test_a_waiter_for_the_quick_files_is_not_released_by_an_older_save(
    root, tmp_path, notices, monkeypatch
) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"], count=20)
    viewer = _open(root, json_path)
    _slow_writer(monkeypatch, "txt", 0.6)
    try:
        _edit(viewer, "text from save A")
        viewer._save_changes()
        time.sleep(0.2)  # A's job is inside the slow txt writer
        _edit(viewer, "text from save B")
        viewer._save_changes()
        viewer._wait_for_subtitle_files()
        assert "text from save B" in _text(tmp_path / "talk.srt")
    finally:
        _close(viewer)


def test_poll_does_not_stop_while_a_report_arrives_during_delivery(
    root, tmp_path, notices
) -> None:
    json_path = _make(tmp_path, ["srt", "json"])
    viewer = _open(root, json_path)
    try:
        viewer._export_idle.clear()
        report = ve.ExportReport(updated=[str(tmp_path / "talk.srt")])

        def deliver_then_the_worker_finishes() -> None:
            # the worker ends its job right after this round took the reports
            viewer._export_reports.append(report)
            viewer._export_idle.set()

        viewer._deliver_export_reports = deliver_then_the_worker_finishes  # type: ignore[method-assign]
        viewer._poll_exports()
        assert viewer._export_poll_id is not None  # another round is due for that report
        viewer._export_poll_id = None
        del viewer._deliver_export_reports
        viewer._poll_exports()
        assert any(t.startswith("Updated") for t, _k in notices)
    finally:
        _close(viewer)


def test_lists_left_with_the_old_text_are_logged_by_the_worker(
    root, tmp_path, notices, caplog
) -> None:
    json_path = _make(tmp_path, ["srt", "txt", "json"])
    (tmp_path / "talk.txt").write_text("not ours\n", encoding="utf-8")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        with caplog.at_level("WARNING", logger=ve.logger.name):
            viewer._save_changes()
            viewer._finish_exports()
        assert "talk.txt" in caplog.text and "not matching" in caplog.text
    finally:
        _close(viewer)


def _break_deflate_stream(path, name: str) -> None:
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(name)
        offset = info.header_offset + 30 + len(info.filename.encode("utf-8")) + len(info.extra)
        size = info.compress_size
    raw = bytearray(open(path, "rb").read())
    raw[offset:offset + size] = b"\xff" * size
    with open(path, "wb") as f:
        f.write(bytes(raw))


def test_a_word_file_with_a_damaged_stream_is_reported_as_unreadable(
    root, tmp_path, notices
) -> None:
    json_path = _make(tmp_path, ["docx", "srt", "json"])
    docx = tmp_path / "talk.docx"
    _break_deflate_stream(docx, "word/document.xml")
    assert ve.signature("docx", docx.read_bytes()) is None  # no zlib.error escapes
    before = docx.read_bytes()
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        viewer._finish_exports()
        warning = _warnings(notices)
        assert "talk.docx" in warning and "could not be read or checked" in warning
        assert "does not match" not in warning
        assert docx.read_bytes() == before
    finally:
        _close(viewer)
