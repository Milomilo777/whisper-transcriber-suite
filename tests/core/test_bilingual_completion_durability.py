"""Completed translation survives UI delivery loss and output-folder failures."""
import hashlib
import json
from pathlib import Path
from types import MethodType, SimpleNamespace
import zipfile

import pytest

from app.dialogs import transcript_viewer as viewer
from core import config, convert, llm
from core import _threads


ORIGINAL = "ORIGINAL SYNTHETIC WORDS"
TRANSLATED = "COMPLETED SYNTHETIC TRANSLATION"


@pytest.fixture
def job(tmp_path, monkeypatch):
    segments = [{"start": 1.25, "end": 3.5, "text": ORIGINAL}]
    source = tmp_path / "talk.json"
    source.write_text(json.dumps(segments), encoding="utf-8")
    callbacks, shown, errors = [], [], []
    fake = SimpleNamespace(
        _closing=False, _ai_busy=False, segments=segments, json_path=str(source), media_path="",
        _app_config=lambda: {"ai_enabled": True}, _ai_target_lang_var=SimpleNamespace(get=lambda: "French"),
        _bilingual_cancel=None, _get_llm_runner=lambda: (object(), ""),
        _set_ai_buttons_busy=lambda busy: None,
        _ai_cancel_btn=SimpleNamespace(pack=lambda **kwargs: None, pack_forget=lambda: None),
        _ai_progress_var=SimpleNamespace(set=lambda value: None), _post_to_main=callbacks.append,
    )
    fake._finish_bilingual_translate = MethodType(viewer.TranscriptViewer._finish_bilingual_translate, fake)
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: True)
    for name in ("showinfo", "showwarning"):
        monkeypatch.setattr(viewer.messagebox, name, lambda title, message, **kwargs: shown.append(message))
    monkeypatch.setattr(viewer, "show_error", lambda *args, **kwargs: errors.append(kwargs))
    monkeypatch.setattr(llm, "translate_segments", lambda *args, **kwargs: [TRANSLATED])
    monkeypatch.setattr(_threads, "safe_thread", lambda function, **kwargs: function())
    return fake, source, callbacks, shown, errors


def run(fake):
    viewer.TranscriptViewer._run_bilingual_translate(fake)


def assert_output(source):
    output = source.with_suffix(".bilingual.french.srt")
    text = output.read_text(encoding="utf-8")
    assert ORIGINAL in text and TRANSLATED in text
    return output


def recovery_archives():
    return list((config.user_data_dir() / "translation-recovery").glob("bilingual-*.zip"))


def assert_recovery(source):
    archives = recovery_archives()
    assert archives, "completed translation must have a durable recovery archive"
    with zipfile.ZipFile(archives[-1]) as recovery:
        body = recovery.read("translation.srt")
        metadata = json.loads(recovery.read("metadata.json"))
    assert ORIGINAL.encode() in body and TRANSLATED.encode() in body
    assert metadata["source_json"] == str(source.resolve())
    assert metadata["language"] == "French"
    assert metadata["translation_sha256"] == hashlib.sha256(body).hexdigest()
    return archives[-1]


def test_worker_saves_completed_result_before_ui_callback(job):
    fake, source, callbacks, shown, errors = job
    run(fake)
    assert callbacks and not shown and not errors
    assert_output(source)
    assert_recovery(source)


def test_closed_viewer_does_not_discard_completed_translation(job, monkeypatch):
    fake, source, callbacks, shown, errors = job

    def close_during_generation(*args, **kwargs):
        fake._closing = True
        return [TRANSLATED]

    monkeypatch.setattr(llm, "translate_segments", close_during_generation)
    run(fake)
    for callback in callbacks:
        callback()
    assert_output(source)
    assert_recovery(source)
    assert not shown and not errors


def test_final_publication_failure_keeps_completed_translation_and_reports_path(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    previous = source.with_suffix(".bilingual.french.srt")
    previous.write_bytes(b"previous manually edited translation")
    install = convert._install_new_output

    def fail_publish(staged, target):
        if Path(target).suffix == ".srt":
            assert TRANSLATED.encode() in Path(staged).read_bytes()
            raise PermissionError("synthetic output publication denied")
        return install(staged, target)

    monkeypatch.setattr(convert, "_install_new_output", fail_publish)
    run(fake)
    archive = assert_recovery(source)
    assert previous.read_bytes() == b"previous manually edited translation"
    for callback in callbacks:
        callback()
    assert len(errors) == 1 and str(archive) in errors[0]["detail"]
    assert not shown


def test_recovery_folder_failure_does_not_prevent_valid_output_save(job, monkeypatch, tmp_path):
    fake, source, callbacks, shown, errors = job
    blocked = tmp_path / "not-a-directory"
    blocked.write_bytes(b"existing unrelated file")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    run(fake)
    output = assert_output(source)
    for callback in callbacks:
        callback()
    assert not errors and output.name in shown[-1]
    assert blocked.read_bytes() == b"existing unrelated file"


def test_explicit_cancel_before_completion_publishes_nothing(job, monkeypatch):
    fake, source, callbacks, shown, errors = job

    def cancel_before_completion(*args, **kwargs):
        kwargs["cancel_event"].set()
        return [TRANSLATED]

    monkeypatch.setattr(llm, "translate_segments", cancel_before_completion)
    run(fake)
    for callback in callbacks:
        callback()
    assert not source.with_suffix(".bilingual.french.srt").exists()
    assert not recovery_archives() and not errors


def test_late_cancel_cannot_relabel_saved_result_as_discarded(job):
    fake, source, callbacks, shown, errors = job
    run(fake)
    output = assert_output(source)
    fake._bilingual_cancel.set()
    for callback in callbacks:
        callback()
    assert not errors and output.name in shown[-1]
    assert_recovery(source)


def test_request_source_identity_is_captured_before_generation(job, monkeypatch, tmp_path):
    fake, source, callbacks, shown, errors = job
    other = tmp_path / "unrelated.json"

    def change_viewer_during_generation(*args, **kwargs):
        fake.json_path = str(other)
        return [TRANSLATED]

    monkeypatch.setattr(llm, "translate_segments", change_viewer_during_generation)
    run(fake)
    assert_output(source)
    assert_recovery(source)
    assert not other.with_suffix(".bilingual.french.srt").exists()


def test_ui_dispatch_exception_cannot_erase_saved_result(job):
    fake, source, callbacks, shown, errors = job

    def broken_dispatch(callback):
        raise RuntimeError("synthetic UI dispatch failure")

    fake._post_to_main = broken_dispatch
    with pytest.raises(RuntimeError, match="synthetic UI dispatch"):
        run(fake)
    assert_output(source)
    assert_recovery(source)


def test_progress_delivery_failure_cannot_abort_completed_translation(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    calls = []

    def progress_then_result(*args, **kwargs):
        kwargs["progress_cb"](1, 1)
        return [TRANSLATED]

    def unreliable_dispatch(callback):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("synthetic progress delivery failure")
        callbacks.append(callback)

    fake._post_to_main = unreliable_dispatch
    monkeypatch.setattr(llm, "translate_segments", progress_then_result)
    run(fake)
    assert_output(source)
    assert_recovery(source)


def test_both_save_failures_can_retry_without_another_provider_call(job, monkeypatch):
    from core.writers import bilingual_srt

    fake, source, callbacks, shown, errors = job
    calls = []

    def generate(*args, **kwargs):
        calls.append(True)
        return [TRANSLATED]

    monkeypatch.setattr(llm, "translate_segments", generate)
    with monkeypatch.context() as failure:
        failure.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("synthetic recovery failure")))
        failure.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("synthetic output failure")))
        run(fake)
        for callback in callbacks:
            callback()
    assert len(calls) == 1 and len(errors) == 1 and not shown
    assert fake._pending_bilingual_save.body and TRANSLATED in fake._pending_bilingual_save.body
    callbacks.clear()
    run(fake)
    for callback in callbacks:
        callback()
    assert len(calls) == 1 and fake._pending_bilingual_save is None
    assert_output(source)
    assert_recovery(source)


def test_recovery_removed_before_ui_callback_is_not_advertised_as_available(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    install = convert._install_new_output

    def fail_output(staged, target):
        if Path(target).suffix == ".srt":
            raise PermissionError("synthetic output failure")
        return install(staged, target)

    monkeypatch.setattr(convert, "_install_new_output", fail_output)
    run(fake)
    archive = assert_recovery(source)
    archive.unlink()
    for callback in callbacks:
        callback()
    assert len(errors) == 1 and "kept in memory" in errors[0]["detail"]
    assert "Recovery copy:" not in errors[0]["detail"]
    assert fake._pending_bilingual_save and not shown


@pytest.mark.parametrize("dispatch_raises", [False, True])
def test_both_storage_failures_retain_memory_before_failed_ui_dispatch(job, monkeypatch, dispatch_raises):
    from core.writers import bilingual_srt

    fake, source, callbacks, shown, errors = job

    def dispatch(callback):
        if dispatch_raises:
            raise RuntimeError("synthetic final dispatch failure")

    fake._post_to_main = dispatch
    monkeypatch.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("recovery blocked")))
    monkeypatch.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("output blocked")))
    if dispatch_raises:
        with pytest.raises(RuntimeError, match="synthetic final dispatch"):
            run(fake)
    else:
        run(fake)
    pending = getattr(fake, "_pending_bilingual_save", None)
    assert pending is not None and TRANSLATED in pending.body
    assert pending.saved_path is None and pending.recovery_path is None
    assert not callbacks and not shown and not errors


def test_unsaved_result_blocks_silent_close_and_can_retry_after_dispatch_loss(job, monkeypatch):
    from core.writers import bilingual_srt

    fake, source, callbacks, shown, errors = job
    destroyed = []
    fake._set_ai_buttons_busy = lambda busy: setattr(fake, "_ai_busy", busy)
    fake._dirty = False
    fake._vlc_bind_id = fake.vlc_seek_after = fake._find_dialog = None
    fake.vlc_player = fake.vlc_instance = None
    fake.destroy = lambda: destroyed.append(True)
    with monkeypatch.context() as failure:
        failure.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("recovery blocked")))
        failure.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("output blocked")))
        fake._post_to_main = lambda callback: None
        run(fake)
    assert fake._pending_bilingual_save is not None and fake._ai_busy
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: False)
    viewer.TranscriptViewer._on_close(fake)
    assert not destroyed and not fake._closing and not fake._ai_busy
    fake._post_to_main = callbacks.append
    run(fake)
    for callback in callbacks:
        callback()
    assert_output(source)


def install_unsaved_result(fake, callbacks, monkeypatch):
    from core.writers import bilingual_srt

    fake._set_ai_buttons_busy = lambda busy: setattr(fake, "_ai_busy", busy)
    fake._dirty = False
    fake._vlc_bind_id = fake.vlc_seek_after = fake._find_dialog = None
    fake.vlc_player = fake.vlc_instance = None
    fake.destroy = lambda: pytest.fail("declined close must not destroy viewer")
    with monkeypatch.context() as failure:
        failure.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("recovery blocked")))
        failure.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("output blocked")))
        run(fake)
        for callback in callbacks:
            callback()
    callbacks.clear()
    assert fake._pending_bilingual_save is not None and not fake._ai_busy


def test_declined_close_does_not_enable_another_retry_while_worker_is_active(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    install_unsaved_result(fake, callbacks, monkeypatch)
    deferred = []
    monkeypatch.setattr(_threads, "safe_thread", lambda function, **kwargs: deferred.append(function))
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: False)
    run(fake)
    assert len(deferred) == 1 and fake._ai_busy
    viewer.TranscriptViewer._on_close(fake)
    assert fake._ai_busy and not fake._closing
    run(fake)
    assert len(deferred) == 1
    deferred[0]()
    for callback in callbacks:
        callback()
    assert_output(source)


def test_stale_failed_completion_cannot_clear_new_retry_state(job, monkeypatch):
    from core.writers import bilingual_srt

    fake, source, callbacks, shown, errors = job
    install_unsaved_result(fake, callbacks, monkeypatch)
    deferred = []
    monkeypatch.setattr(_threads, "safe_thread", lambda function, **kwargs: deferred.append(function))
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: False)
    with monkeypatch.context() as failure:
        failure.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("recovery blocked")))
        failure.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("output blocked")))
        run(fake)
        deferred[0]()
    assert len(callbacks) == 1
    stale_completion = callbacks.pop()
    viewer.TranscriptViewer._on_close(fake)
    assert not fake._ai_busy and not fake._closing
    run(fake)
    assert len(deferred) == 2 and fake._ai_busy
    error_count = len(errors)
    stale_completion()
    assert fake._ai_busy and len(errors) == error_count
    deferred[1]()
    for callback in callbacks:
        callback()
    assert_output(source)


def test_unsaved_close_guard_does_not_unlock_another_ai_action(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    install_unsaved_result(fake, callbacks, monkeypatch)
    for name in ("_ai_summarise_btn", "_ai_actionitems_btn", "_ai_ask_btn", "_ai_translate_btn", "_ai_bilingual_btn"):
        setattr(fake, name, SimpleNamespace(state=lambda value: None))
    fake._set_ai_buttons_busy = MethodType(viewer.TranscriptViewer._set_ai_buttons_busy, fake)
    fake._set_ai_buttons_busy(True)  # another AI action now owns the busy controls
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: False)
    viewer.TranscriptViewer._on_close(fake)
    assert fake._ai_busy and not fake._closing


def test_retry_worker_start_failure_releases_busy_state_and_retains_result(job, monkeypatch):
    fake, source, callbacks, shown, errors = job
    install_unsaved_result(fake, callbacks, monkeypatch)
    pending = fake._pending_bilingual_save

    def fail_start(function, **kwargs):
        raise RuntimeError("synthetic worker start failure")

    with monkeypatch.context() as failure:
        failure.setattr(_threads, "safe_thread", fail_start)
        with pytest.raises(RuntimeError, match="synthetic worker start failure"):
            run(fake)
    assert not fake._ai_busy and not fake._bilingual_worker_state.is_set()
    assert fake._pending_bilingual_save is pending
    run(fake)
    for callback in callbacks:
        callback()
    assert_output(source)


def test_stale_bilingual_completion_cannot_unlock_a_new_different_ai_action(job, monkeypatch):
    from core.writers import bilingual_srt

    fake, source, callbacks, shown, errors = job
    install_unsaved_result(fake, callbacks, monkeypatch)
    for name in ("_ai_summarise_btn", "_ai_actionitems_btn", "_ai_ask_btn", "_ai_translate_btn", "_ai_bilingual_btn"):
        setattr(fake, name, SimpleNamespace(state=lambda value: None))
    fake._set_ai_buttons_busy = MethodType(viewer.TranscriptViewer._set_ai_buttons_busy, fake)
    deferred = []
    monkeypatch.setattr(_threads, "safe_thread", lambda function, **kwargs: deferred.append(function))
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *args, **kwargs: False)
    with monkeypatch.context() as failure:
        failure.setattr(bilingual_srt, "_save_recovery", lambda result: (_ for _ in ()).throw(OSError("recovery blocked")))
        failure.setattr(convert, "_publish_new_output", lambda *args: (_ for _ in ()).throw(OSError("output blocked")))
        run(fake)
        deferred[0]()
    stale = callbacks.pop()
    viewer.TranscriptViewer._on_close(fake)
    assert not fake._ai_busy
    fake._set_ai_buttons_busy(True)  # a different AI tool is now running
    before = len(errors)
    stale()
    assert fake._ai_busy and len(errors) == before
