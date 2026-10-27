"""Starting the web / LAN server must not download the Whisper model without asking.

The desktop path asks "Whisper model required" and downloads through the dialog (which checks the
free disk space first). The server start used to download the default model silently on its thread.
"""
from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from app import app as app_module


def _fake(*, present: bool, answer: bool = True, download_ok: bool = True, running: bool = False,
          model_ready: bool = False) -> Any:
    fake = types.SimpleNamespace(
        _server_busy=False, model_setup_running=running, log=MagicMock(), model_ready=model_ready,
        _save_server_prefs=MagicMock(), _server_is_running=lambda: False,
        _start_server_async=MagicMock(), _model_bytes_present=lambda: present,
        ask=MagicMock(return_value=answer), downloads=MagicMock(return_value=download_ok),
    )
    fake._server_model_agreed = lambda: app_module.App._server_model_agreed(fake)
    fake._ask_model_download = fake.ask
    # as in App: ensure_model_with_modal is a no-op once any model is loaded, download_model_now is not
    fake.ensure_model_with_modal = lambda **_k: True if fake.model_ready else fake.downloads()
    fake.download_model_now = fake.downloads
    return fake


def test_a_loaded_other_model_does_not_skip_the_download_dialog() -> None:
    # model_ready says SOME model was loaded; the configured one is still missing, so the server
    # start thread would download it silently unless the dialog runs here
    fake = _fake(present=False, model_ready=True)
    app_module.App.toggle_server(fake)
    fake.ask.assert_called_once()
    fake.downloads.assert_called_once()
    fake._start_server_async.assert_called_once()


def test_start_with_the_model_on_disk_asks_nothing() -> None:
    fake = _fake(present=True)
    app_module.App.toggle_server(fake)
    fake.ask.assert_not_called()
    fake._start_server_async.assert_called_once()


def test_start_without_the_model_asks_then_downloads_then_starts() -> None:
    fake = _fake(present=False)
    app_module.App.toggle_server(fake)
    fake.ask.assert_called_once()
    fake.downloads.assert_called_once()
    fake._start_server_async.assert_called_once()


@pytest.mark.parametrize("answer, download_ok", [(False, True), (True, False)])
def test_start_is_cancelled_when_declined_or_the_download_fails(answer: bool, download_ok: bool) -> None:
    fake = _fake(present=False, answer=answer, download_ok=download_ok)
    app_module.App.toggle_server(fake)
    fake._start_server_async.assert_not_called()
    assert fake.log.called


def test_start_waits_while_another_model_download_runs() -> None:
    fake = _fake(present=False, running=True)
    app_module.App.toggle_server(fake)
    fake.ask.assert_not_called()
    fake._start_server_async.assert_not_called()
