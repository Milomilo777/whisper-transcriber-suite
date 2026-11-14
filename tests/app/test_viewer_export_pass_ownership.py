"""A previous export pass cannot consume the next saved revision's exit list."""
import json
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as tv, viewer_exports as ve


def segments(text):
    return [{"start": 0.0, "end": 1.0, "text": text}]


@pytest.mark.parametrize("pause_in_scan_wait", [False, True])
def test_queued_save_retains_every_unfinished_latest_export(tmp_path, monkeypatch, pause_in_scan_wait):
    path = str(tmp_path / "talk.json")
    old = segments("original")
    files = [str(tmp_path / ("talk." + fmt)) for fmt in ("srt", "vtt", "txt")]
    for filename, fmt in zip(files, ("srt", "vtt", "txt")):
        Path(filename).write_bytes(ve.render_bytes(fmt, old, ""))
    scan = ve.scan_exports(path, old, "")
    host = SimpleNamespace(
        json_path=path, _export_lock=threading.Lock(), _export_running=True,
        _export_pending=json.dumps(segments("edit A")), _export_remaining=set(files),
        _export_reports=[], _export_fast_done=threading.Event(),
        _export_idle=threading.Event(), _scan_fast_done=threading.Event(),
        _synced_siblings=scan.synced, _sibling_plan=scan.plan, _sibling_unchecked=scan.unchecked,
        _start_scan=lambda: None, _wait_for_scan=lambda: None,
        _set_busy=lambda *a: None, _schedule_export_poll=lambda: None,
    )
    host._scan_fast_done.set()
    host._mark_export_fast_done = MethodType(tv.TranscriptViewer._mark_export_fast_done, host)
    monkeypatch.setattr(tv, "_EXPORTING", [host])
    a_paused, release_a, b_paused, release_b = [threading.Event() for _ in range(4)]
    failures = []

    def wait_for_release(event, label):
        if not event.wait(5):
            error = AssertionError(f"Timed out waiting for {label}")
            failures.append(error)  # Export error handling must not hide a broken barrier.
            raise error

    if pause_in_scan_wait:
        def wait_in_scan():
            a_paused.set()
            wait_for_release(release_a, "scan release")
        host._scan_fast_done = SimpleNamespace(wait=wait_in_scan)
    render = ve.render_bytes
    original_remaining = host._export_remaining

    def barrier_render(fmt, segs, audio):
        text = segs[0]["text"]
        if not pause_in_scan_wait and text == "edit A" and fmt == "vtt":
            a_paused.set()
            wait_for_release(release_a, "A render release")
        if text == "edit B" and fmt == "srt":
            b_paused.set()
            wait_for_release(release_b, "B render release")
        return render(fmt, segs, audio)

    def run():
        try:
            tv.TranscriptViewer._export_loop(host)
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(ve, "render_bytes", barrier_render)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert a_paused.wait(5)
        payload = json.dumps(segments("edit B"))
        Path(path).write_text(payload, encoding="utf-8")
        tv.TranscriptViewer._queue_exports(host, payload)
        release_a.set()
        assert b_paused.wait(5)
        # All siblings still carry A while the authoritative JSON holds B.
        assert host._export_remaining == set(files)
        assert set(tv.finish_exports_before_exit(timeout=0)) == set(files)
        assert not host._export_fast_done.is_set()
    finally:
        release_a.set()
        release_b.set()
        worker.join(8)
    assert not worker.is_alive() and not failures
    assert not any(report.failed for report in host._export_reports)
    assert original_remaining == set()
    assert host._export_idle.is_set() and tv._EXPORTING == []
    assert all(b"edit B" in Path(filename).read_bytes() for filename in files)


def test_fast_done_already_waits_for_a_pending_save():
    host = SimpleNamespace(
        _export_lock=threading.Lock(), _export_pending="new revision",
        _export_fast_done=threading.Event(),
    )
    tv.TranscriptViewer._mark_export_fast_done(host)
    assert not host._export_fast_done.is_set()
    host._export_pending = None
    tv.TranscriptViewer._mark_export_fast_done(host)
    assert host._export_fast_done.is_set()
