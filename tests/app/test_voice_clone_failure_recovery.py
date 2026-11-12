"""Native Tk controls recover from deferred worker errors and cancellation."""
import threading
import pytest

from app import i18n
from app.services import voice_clone_service
from app.widgets import voice_clone_tab as tab
from tests.app.test_voice_clone_tab import (
    _build, _clone_mode, _state, _tick, _write_wav, fakes, no_dialogs, root,
)


@pytest.mark.parametrize("phase", ["start", "generate", "cancel"])
def test_repeated_worker_failure_preserves_output_and_allows_retry(
    root, fakes, no_dialogs, monkeypatch, tmp_path, phase,
):
    previous_language = i18n.current_language()
    i18n.set_language("en")
    callback_errors = []
    monkeypatch.setattr(root, "report_callback_exception", lambda *error: callback_errors.append(error))
    original_worker = voice_clone_service.VoiceCloneWorker
    failure = [True]
    starts = []

    class Worker(original_worker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.stopped = threading.Event()

        def start(self):
            starts.append(self)
            if failure[0] and phase == "start":
                raise OSError("aoti_torch_library_def DLL initialization failed")
            super().start()

        def generate(self, *args, **kwargs):
            if failure[0] and phase == "generate":
                self.running = False
                raise OSError("aoti_torch_library_def DLL initialization failed")
            if failure[0] and phase == "cancel":
                tab._cancel_generate(app)
                self.stopped.wait(1)
                raise RuntimeError("worker cancelled")
            return super().generate(*args, **kwargs)

        def stop(self):
            super().stop()
            self.stopped.set()

        def wait_for_exit(self, timeout=15):
            return not self.running

    monkeypatch.setattr(voice_clone_service, "VoiceCloneWorker", Worker)
    try:
        app = _build(root, fakes)
        _clone_mode(app, ["synthetic-reference.wav"])
        _tick(app)
        previous = tmp_path / "previous.wav"
        _write_wav(str(previous), 2)
        previous_bytes = previous.read_bytes()
        app.vc_last_output = str(previous)
        app.vc_play_btn.configure(state="normal")
        app.vc_save_btn.configure(state="normal")
        callbacks = []
        app.post_to_main = callbacks.append

        def drain():
            for _ in range(16):
                if not callbacks:
                    break
                callbacks.pop(0)()
            assert not callbacks
            root.update()
            assert not callback_errors

        for attempt in range(2):
            app.vc_generate_btn.invoke()
            assert app.vc_busy and _state(app) == "disabled"
            drain()
            if phase == "cancel":
                assert no_dialogs == [] and app.vc_worker.stopped.is_set()
                assert app.vc_status_var.get().startswith("Cancelled")
            else:
                assert len(no_dialogs) == attempt + 1
                assert "aoti_torch_library_def" in str(no_dialogs[-1])
            assert app.vc_busy is False and app.vc_cancel_event is None
            assert _state(app) == "normal"
            assert str(app.vc_cancel_btn.cget("state")) == "disabled"
            assert str(app.vc_load_btn.cget("state")) == "normal"
            assert app.vc_last_output == str(previous)
            assert previous.read_bytes() == previous_bytes

        failure[0] = False
        app.vc_generate_btn.invoke()
        drain()
        assert len(starts) == 3 and len(fakes["generate"]) == 1
        assert len(no_dialogs) == (0 if phase == "cancel" else 2)
        assert app.vc_status_var.get().startswith("Done")
        assert app.vc_busy is False and _state(app) == "normal"
        assert previous.read_bytes() == previous_bytes
    finally:
        i18n.set_language(previous_language)
