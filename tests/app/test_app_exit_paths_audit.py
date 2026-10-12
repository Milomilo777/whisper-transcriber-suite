"""Exit paths of App.on_exit: re-entry, a failing teardown step, and each kind of running job."""
import tkinter as tk
from unittest.mock import Mock

from app.app import App


def _bare_app():
    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    return root

def test_second_close_while_closing():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # Track calls
    call_count = 0
    def fake_shutdown_server():
        nonlocal call_count
        call_count += 1
        # simulate second click while closing
        if call_count == 1:
            app_obj.on_exit()

    app_obj._shutdown_server_on_exit = fake_shutdown_server

    app_obj.on_exit()

    # If it is not protected against re-entry, call_count will be 2 (or it might recurse infinitely).
    assert call_count == 1, "App.on_exit should not be re-entrant during teardown"

def test_exception_in_one_step_does_not_skip_others():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    app_obj.transcription_service.stop_all = Mock()

    # Make the LAN server shutdown throw an unhandled exception
    def failing_step():
        raise RuntimeError("Oops")

    app_obj._shutdown_server_on_exit = failing_step

    app_obj.on_exit()

    # The next step should still have run!
    app_obj.transcription_service.stop_all.assert_called_once()


def test_close_during_download():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []

    # Mock download task
    task = Mock()
    task.status = "downloading"
    task.process = Mock()
    app_obj.download_queue = [task]

    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # Mock messagebox to return True (yes, exit)
    import tkinter.messagebox
    original_askyesno = tkinter.messagebox.askyesno
    tkinter.messagebox.askyesno = lambda *args, **kwargs: True
    try:
        app_obj.on_exit()
        # Verify kill process tree was called
        task.process.poll.assert_called()
    finally:
        tkinter.messagebox.askyesno = original_askyesno


def test_close_during_transcription():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}

    # Mock transcription task
    task = Mock()
    task.status = "transcribing"
    app_obj.queue = [task]
    app_obj.download_queue = []

    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    import tkinter.messagebox
    original_askyesno = tkinter.messagebox.askyesno
    tkinter.messagebox.askyesno = lambda *args, **kwargs: True
    try:
        app_obj.on_exit()
        app_obj.transcription_service.stop_all.assert_called_once_with(cancel_running=True)
        app_obj.transcription_service.settle_done_on_exit.assert_called_once()
    finally:
        tkinter.messagebox.askyesno = original_askyesno


def test_close_with_unsaved_viewers():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []

    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # Mock confirm_unsaved_viewers_before_exit to return False (cancel exit)
    import app.app as app_module
    original_confirm = app_module.confirm_unsaved_viewers_before_exit
    app_module.confirm_unsaved_viewers_before_exit = lambda *args, **kwargs: False

    try:
        app_obj.on_exit()

        # We should NOT have flipped _closing since we bailed
        assert not app_obj._closing
        # stop_all should NOT have been called
        app_obj.transcription_service.stop_all.assert_not_called()
    finally:
        app_module.confirm_unsaved_viewers_before_exit = original_confirm
        # The cancelled exit leaves the window open. Destroy it here: a live root
        # stays tkinter's default root, so later tests' ttk.Style() and sv_ttk
        # calls would act on this window instead of their own.
        app_obj.destroy()


def test_close_with_model_download():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # We must ensure `_stop_installs_on_exit` is called, which we wrapped in a try/except earlier.
    # The module is `core.optional_deps`.
    import core.optional_deps
    original_req = core.optional_deps.request_stop_installs
    core.optional_deps.request_stop_installs = Mock()

    try:
        app_obj.on_exit()
        core.optional_deps.request_stop_installs.assert_called_once()
    finally:
        core.optional_deps.request_stop_installs = original_req

def test_close_with_live_recording():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # The Live recording stop logic happens in stop_live_session
    import app.app as app_module
    original_stop_live = getattr(app_module, "stop_live_session", None)
    mock_stop_live = Mock()
    app_module.stop_live_session = mock_stop_live

    try:
        app_obj.on_exit()
        mock_stop_live.assert_called_once_with(app_obj)
    finally:
        if original_stop_live:
            app_module.stop_live_session = original_stop_live
        else:
            del app_module.stop_live_session

def test_close_with_voice_clone_job():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    app_obj._server_handle = None
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    # Voice clone logic happens in stop_voice_clone_worker
    import app.app as app_module
    original_stop_vc = getattr(app_module, "stop_voice_clone_worker", None)
    mock_stop_vc = Mock()
    app_module.stop_voice_clone_worker = mock_stop_vc

    try:
        app_obj.on_exit()
        mock_stop_vc.assert_called_once_with(app_obj)
    finally:
        if original_stop_vc:
            app_module.stop_voice_clone_worker = original_stop_vc
        else:
            del app_module.stop_voice_clone_worker


def test_close_with_api_server_running():
    app_obj = _bare_app()
    app_obj._exit_prompt_open = False
    app_obj._exit_from_tray = False
    app_obj.app_config = {}
    app_obj.queue = []
    app_obj.download_queue = []
    app_obj.tray = None
    app_obj._closing = False
    app_obj._folder_watcher = None
    handle = Mock()
    app_obj._server_handle = handle
    app_obj.transcription_service = Mock()
    app_obj.history = Mock()

    app_obj.on_exit()
    handle.stop.assert_called_once_with(timeout=3.0)
