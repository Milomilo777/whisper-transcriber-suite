"""Tests for the speaker count UI on the Transcribe tab."""
import tkinter as tk
import threading
import time
import pytest
from unittest.mock import patch

pytest.importorskip("tkinter")

from app.app import App
from core.config import DEFAULT_CONFIG


def _wait_for_available(app):
    deadline = time.monotonic() + 5
    while app.diarization_check.instate(["disabled"]) and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    assert app.diarization_check.instate(["!disabled"])


@pytest.fixture
def startup_config(tmp_path, monkeypatch):
    cfg = dict(DEFAULT_CONFIG, diarization_enabled=True, diarization_num_speakers=3)
    monkeypatch.setattr("core.config.user_config_dir", lambda: tmp_path / "c")
    monkeypatch.setattr("core.config.user_data_dir", lambda: tmp_path / "d")
    monkeypatch.setattr("core.config.user_cache_dir", lambda: tmp_path / "k")
    monkeypatch.setattr("core.stats.post_stats_async", lambda *a, **kw: False)
    monkeypatch.setattr("app.app.load_config", lambda: cfg)
    monkeypatch.setattr("app.app.save_config", lambda *a, **kw: None)
    return cfg


def test_startup_returns_during_diarization_probe(startup_config, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    threads = []

    def available():
        threads.append(threading.current_thread())
        entered.set()
        if threading.current_thread() is not threading.main_thread():
            release.wait(10)
        return True

    monkeypatch.setattr("core.diarization.is_available", available)
    app = App()
    try:
        try:
            assert entered.wait(5)
            assert threads[0] is not threading.current_thread()
            assert app.diarization_check.instate(["disabled"])
            assert not app.diarization_speakers_combo.winfo_manager()
            app._save_transcribe_prefs()
            assert startup_config["diarization_enabled"] is True
        finally:
            release.set()
        _wait_for_available(app)
        assert app.diarization_check.instate(["!disabled", "selected"])
        assert app.diarization_speakers_combo.winfo_manager()
    finally:
        app.destroy()


def test_startup_finishes_if_diarization_thread_cannot_start(startup_config, monkeypatch):
    start = threading.Thread.start

    def refuse_diarization(thread):
        if thread.name == "diarization-availability":
            raise RuntimeError("could not start thread")
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", refuse_diarization)
    app = App()
    try:
        assert app.diarization_check.instate(["disabled", "!selected"])
        assert app.diarization_check.cget("text") == "Identify speakers (unavailable)"
    finally:
        app.destroy()


@pytest.fixture
def app(tmp_path):
    # Probe for a display first: App() itself would fail less clearly without one.
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")

    # Isolated config
    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False):

        cfg = dict(DEFAULT_CONFIG)
        cfg["diarization_enabled"] = True
        cfg["diarization_num_speakers"] = 3

        with patch("app.app.load_config", return_value=cfg), \
             patch("app.app.save_config"):

            with patch("core.diarization.is_available", return_value=True):
                app_inst = App()
                try:
                    _wait_for_available(app_inst)
                    yield app_inst
                finally:
                    try:
                        app_inst.destroy()
                    except tk.TclError:
                        pass


def test_speaker_count_initial_value(app):
    """The initial value is mapped correctly from config (-1 -> Auto, 3 -> 3)."""
    assert app.diarization_speakers_var.get() == "3"

    app.app_config["diarization_num_speakers"] = -1
    app.destroy()

    # Restart app with -1
    cfg = dict(DEFAULT_CONFIG)
    cfg["diarization_enabled"] = True
    cfg["diarization_num_speakers"] = -1
    with patch("app.app.load_config", return_value=cfg), \
         patch("core.diarization.is_available", return_value=True):
        app_inst = App()
        try:
            assert app_inst.diarization_speakers_var.get() == "Auto"
        finally:
            try:
                app_inst.destroy()
            except tk.TclError:
                pass


def test_speaker_count_disabled_when_diarization_off(app):
    """The combobox is disabled when speaker detection is turned off."""
    assert "disabled" not in app.diarization_speakers_combo.state()

    app.diarization_check.invoke()
    app.update_idletasks()

    assert "disabled" in app.diarization_speakers_combo.state()

    # Toggle it back
    app.diarization_check.invoke()
    app.update_idletasks()

    assert "disabled" not in app.diarization_speakers_combo.state()


def test_speaker_count_save_transcribe_prefs(app, caplog):
    """Saving preferences maps the combobox value back to config."""
    # Test valid number
    app.diarization_speakers_var.set("5")
    app.diarization_speakers_combo.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert app.app_config["diarization_num_speakers"] == 5

    # Test "Auto"
    app.diarization_speakers_var.set("Auto")
    app.diarization_speakers_combo.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert app.app_config["diarization_num_speakers"] == -1

    # Test invalid string fallback
    app.diarization_speakers_var.set("two")
    app.diarization_speakers_combo.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert app.app_config["diarization_num_speakers"] == -1
    assert "Invalid diarization_num_speakers" in caplog.text


def test_transcriber_receives_speaker_count(app):
    """The task settings passed to the transcriber carry the chosen number."""
    from core import task_settings

    app.diarization_speakers_var.set("4")
    app._save_transcribe_prefs()

    class DummyTask:
        pass

    task = DummyTask()
    snap = task_settings.stamp(task, app.app_config)

    assert snap is not None
    assert snap["diarization_num_speakers"] == 4
    assert task.task_settings["diarization_num_speakers"] == 4


@pytest.mark.parametrize("invalid_val", [0, 1, 11, 100, -5, "abc", None, True, [], {}, 2.0, 3.5, "3"])
def test_speaker_count_initial_value_outside_list(tmp_path, caplog, invalid_val):
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")

    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False):

        cfg = dict(DEFAULT_CONFIG)
        cfg["diarization_enabled"] = True
        cfg["diarization_num_speakers"] = invalid_val

        with patch("app.app.load_config", return_value=cfg), \
             patch("app.app.save_config"), \
             patch("core.diarization.is_available", return_value=True):

            app_inst = App()
            try:
                assert app_inst.diarization_speakers_var.get() == "Auto"
                assert "Invalid speaker count" in caplog.text
            finally:
                app_inst.destroy()


def test_speaker_count_layout_fits(app):
    app.geometry(f"{app.minsize()[0]}x{app.minsize()[1]}")
    # The speaker options sit behind "More options", closed on a new install.
    assert not app.diarization_speakers_combo.winfo_ismapped()
    app.transcribe_more_options.set_open(True)
    app.update_idletasks()
    app.update()

    widgets_to_check = [
        app.diarization_speakers_label,
        app.diarization_speakers_combo,
        app.diarization_help_icon
    ]

    checked = 0
    for w in widgets_to_check:
        assert w.winfo_ismapped()
        assert w.winfo_width() > 1
        assert w.winfo_rootx() + w.winfo_width() <= app.winfo_rootx() + app.winfo_width()
        checked += 1

    assert checked == 3


def test_speaker_count_is_hidden_while_detection_is_off(app):
    """Greyed out, the count still looked like a setting that applies (review 2026-10-21):
    it is hidden while detection is off and comes back in front of "Time range"."""
    row = app.diarization_speakers_combo.master
    assert app.diarization_speakers_combo.winfo_manager()

    app.diarization_check.invoke()  # off
    app.update_idletasks()
    assert not app.diarization_speakers_label.winfo_manager()
    assert not app.diarization_speakers_combo.winfo_manager()

    app.diarization_check.invoke()  # on again
    app.update_idletasks()
    order = row.pack_slaves()
    assert order.index(app.diarization_speakers_label) < order.index(app.diarization_speakers_combo) \
        < order.index(app.transcribe_time_range_label)
