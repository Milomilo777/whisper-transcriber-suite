"""Run with a real desktop, bundled tools and a local faster-whisper tiny model."""
from __future__ import annotations

import json
import os
import subprocess
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import ttk
from types import SimpleNamespace

import pytest

from tests.smoke.conftest import DEFAULT_MODEL_PARENT
from tests.smoke.test_media_audio_tracks import executables


def test_closing_root_releases_pending_track_probe(monkeypatch):
    from app.dialogs import media_audio

    started = Event()
    release = Event()

    def slow_probe(source):
        started.set()
        release.wait(3)
        return []

    monkeypatch.setattr(media_audio, "probe_audio_tracks", slow_probe)
    root = tk.Tk()
    root.after(100, root.destroy)
    try:
        assert media_audio._probe_without_blocking_tk(root, "recording.mp4") is None
        assert started.is_set()
    finally:
        release.set()


@pytest.mark.parametrize("deny_cleanup", [False, True])
def test_closing_root_waits_for_repair_to_discard_copy(tmp_path, monkeypatch, deny_cleanup, caplog):
    from app.dialogs import media_audio
    from core.task import TranscriptionTask

    class UndeletableCopy(type(tmp_path)):
        def unlink(self, missing_ok=False):
            raise PermissionError("simulated file lock")

    target = tmp_path / "cancelled.wav"
    exited = Event()

    def slow_repair(source, ordinal, folder, cancelled):
        while not cancelled():
            time.sleep(0.02)
        target.write_bytes(b"temporary audio")
        exited.set()
        return media_audio.RepairedAudio(UndeletableCopy(target) if deny_cleanup else target, 1, 2)

    monkeypatch.setattr(media_audio, "repair_audio", slow_repair)
    root = tk.Tk()
    root.after(250, root.destroy)
    assert media_audio.offer_repaired_audio(root, TranscriptionTask("recording.mp4"), tmp_path) is None
    assert exited.is_set()
    assert target.exists() is deny_cleanup
    if deny_cleanup:
        assert "Could not discard repaired audio" in caplog.text


def _children(window):
    for child in window.winfo_children():
        yield child
        yield from _children(child)


def _button(window, text):
    return next(widget for widget in _children(window)
                if isinstance(widget, ttk.Button) and widget.cget("text") == text)


def _pump_until(app, check, seconds=75):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.update()
        if check():
            return
        time.sleep(0.04)
    pytest.fail("The desktop never reached the expected state.")


def test_native_playback_selects_nondefault_mp4_stream(tmp_path, executables):
    from app.dialogs.media_audio import play_transcript_audio
    from app.dialogs.transcript_viewer import _try_load_vlc

    vlc, reason = _try_load_vlc()
    if vlc is None:
        pytest.skip(reason)
    source = tmp_path / "preview.mp4"
    subprocess.run(
        [executables["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:d=3",
         "-f", "lavfi", "-i", "sine=440:sample_rate=16000:duration=3",
         "-map", "0:a", "-map", "1:a", "-c:a", "aac",
         "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=eng",
         "-disposition:a:0", "default", "-disposition:a:1", "0", str(source)],
        check=True,
    )
    # Isolate the test player from machine settings, output devices and stale caches.
    instance = vlc.Instance("vlc", "--ignore-config", "--no-plugins-cache",
                            "--aout=dummy", "--no-video", "--quiet")
    player = instance.media_player_new()
    media = instance.media_new_path(str(source))
    media.add_option(":start-paused")
    player.set_media(media)
    root = tk.Tk()
    root.withdraw()
    viewer = SimpleNamespace(vlc_player=player, vlc_mod=vlc, _closing=False,
                             _playback_audio_track=1, after=root.after)
    try:
        play_transcript_audio(viewer)
        _pump_until(root, lambda: not viewer._audio_track_pending, seconds=3)
        tracks = [track_id for track_id, _name in player.audio_get_track_description() if track_id >= 0]
        assert len(tracks) == 2
        assert player.audio_get_track() == tracks[1]
    finally:
        root.destroy()
        player.stop()
        player.release()
        media.release()
        instance.release()


def _when_dialog_is_open(app, title, action):
    deadline = time.monotonic() + 30

    def check():
        for child in app.winfo_children():
            if isinstance(child, tk.Toplevel) and child.title() == title:
                if action(child):
                    return
        if time.monotonic() < deadline:
            app.after(60, check)
        else:
            for child in app.winfo_children():
                if isinstance(child, tk.Toplevel) and child.title() == title:
                    child.destroy()

    app.after(60, check)


def test_desktop_transcribes_selected_and_repaired_audio(tmp_path, monkeypatch, executables):
    from app.app import App
    from core import _checkpoint, transcriber
    from core.config import load_config, save_config
    from core.model_manager import catalog_resolve_entry
    from core.task import task_repair_path

    model = Path(os.environ.get("WHISPER_SMOKE_MODEL", str(
        DEFAULT_MODEL_PARENT / "models--Systran--faster-whisper-tiny"
    )))
    if not (model / "model.bin").is_file():
        pytest.skip("A local faster-whisper tiny model is required.")
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("WTS_UI_LANGUAGE", "en")
    monkeypatch.setenv("PATH", str(Path(executables["ffmpeg"]).parent) + os.pathsep + os.environ.get("PATH", ""))
    entry = catalog_resolve_entry({}, "tiny")
    assert entry
    save_config({
        "quick_start_done": True, "work_offline": True, "telemetry_opt_in": False,
        "whisper_model": "tiny", "model": entry, "model_path": str(model),
        "hub_folder": str(model.parent), "device": "cpu", "compute_type": "int8",
        "output_formats": ["json", "srt"], "transcribe_backend": "faster_whisper",
    })

    source = tmp_path / "Two audio tracks.mp4"
    sample = Path(__file__).resolve().parents[2] / "assets" / "sample_clip.mp3"
    subprocess.run([executables["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000",
                    "-i", str(sample), "-map", "0:a", "-map", "1:a", "-shortest", "-c:a", "aac",
                    "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=eng",
                    "-movflags", "+faststart", str(source)], check=True)
    broken = tmp_path / "Truncated recording.mp4"
    data = source.read_bytes()
    broken.write_bytes(data[:len(data) * 3 // 4])

    app = App()
    try:
        def choose_track(dialog):
            selection = next(widget for widget in _children(dialog) if isinstance(widget, ttk.Combobox))
            selection.current(1)
            _button(dialog, "Add to queue").invoke()
            return True

        def submit(path):
            app.fv.set(str(path))
            _when_dialog_is_open(app, "Choose audio track", choose_track)
            app.add()
            task = app.queue[-1]
            _pump_until(app, lambda: task.status in ("finished", "error"))
            return task

        def verify_transcript(task, original, repaired=False):
            assert task.status == "finished", task.error_reason
            assert task.audio_track == 1
            transcript = next(Path(path) for path in task.output_paths if path.endswith(".json"))
            assert transcript.stem == original.stem
            cues = json.loads(transcript.read_text(encoding="utf-8"))
            assert any(cue["text"].strip() for cue in cues)
            assert all(cue["audio_track"] == 1 for cue in cues)
            assert bool(cues[0].get("audio_repaired")) is repaired

        selected = submit(source)
        verify_transcript(selected, source)
        monkeypatch.setattr(transcriber, "config", dict(load_config()))
        with transcriber._runtime_overrides_scope(selected):
            fingerprint = _checkpoint.config_fingerprint(transcriber.config)
        _checkpoint.write_checkpoint(
            str(source), backend="faster_whisper", model_name=entry["name"],
            language="en", language_probability=1, cfg_fingerprint=fingerprint,
            last_end_time=1, segments=[{"start": 0, "end": 1, "text": "Saved prefix."}],
            checkpoint_time=time.time(), audio_track=1,
        )
        app.resume_task(selected)
        resumed = app.queue[-1]
        assert resumed is not selected
        _pump_until(app, lambda: resumed.status in ("finished", "error"))
        assert resumed.status == "finished", resumed.error_reason
        resumed_json = next(Path(path) for path in resumed.output_paths if path.endswith(".json"))
        resumed_cues = json.loads(resumed_json.read_text(encoding="utf-8"))
        assert resumed_cues[0]["text"] == "Saved prefix."
        assert len(resumed_cues) > 1
        assert all(cue["audio_track"] == 1 for cue in resumed_cues)

        failed = submit(broken)
        assert failed.status == "error"
        assert failed.error_reason == "The audio could not be decoded."
        app.show_task_in_queue(failed)
        _pump_until(app, app.queue_repair_button.winfo_ismapped, seconds=5)

        def retry_when_ready(dialog):
            try:
                retry = _button(dialog, "Try again")
            except StopIteration:
                return False
            retry.invoke()
            return True

        _when_dialog_is_open(app, "Repair audio", retry_when_ready)
        app.queue_repair_button.invoke()
        retry = app.queue[-1]
        assert retry is not failed
        _pump_until(app, lambda: retry.status in ("finished", "error"))
        verify_transcript(retry, broken, repaired=True)
        copy_path = task_repair_path(retry)
        assert copy_path
        copy = Path(copy_path)
        assert copy.is_file()
        app.remove_task(retry)
        assert not copy.exists()
        assert broken.read_bytes() == data[:len(data) * 3 // 4]
    finally:
        app.transcription_service.stop_all()
        app.destroy()
