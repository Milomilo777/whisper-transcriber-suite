"""Dialogs for local media audio."""
from __future__ import annotations

import logging
import time
import tkinter as tk
from os.path import basename
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from tkinter import ttk
from typing import Any

from app.dpi import place_over, px
from app.i18n import _, ngettext
from app.widgets.notice import notify
from core.media_audio import (
    AudioPreparationCancelled, AudioTrack, RepairedAudio, RepairSpaceError,
    default_audio_track, probe_audio_tracks, repair_audio,
)
from core.task import TranscriptionTask

logger = logging.getLogger(__name__)


def play_transcript_audio(viewer: Any) -> None:
    """Select a requested VLC stream while playback is paused at the start."""
    player = viewer.vlc_player
    ordinal = getattr(viewer, "_playback_audio_track", None)
    if ordinal is None:
        player.play()
        return
    if getattr(viewer, "_audio_track_pending", False):
        return
    if player.get_state() == viewer.vlc_mod.State.Paused:
        player.set_pause(0)
        return
    if player.is_playing():
        return
    viewer._audio_track_pending = True
    deadline = time.monotonic() + 2
    requested = None
    player.play()

    def select() -> None:
        nonlocal requested
        if viewer._closing or viewer.vlc_player is not player:
            return
        if player.get_state() == viewer.vlc_mod.State.Paused:
            ids = [track_id for track_id, _name in player.audio_get_track_description() or () if track_id >= 0]
            if ordinal < len(ids):
                target = ids[ordinal]
                if player.audio_get_track() == target:
                    viewer._audio_track_pending = False
                    player.set_pause(0)
                    return
                if requested != target and player.audio_set_track(target) == 0:
                    requested = target
        if time.monotonic() < deadline:
            viewer.after(25, select)
        else:
            viewer._audio_track_pending = False
            viewer._disable_embedded_playback()
            notify(viewer, _("Embedded playback not available."), "warning")

    select()


def _discard_copy(copy: RepairedAudio) -> None:
    try:
        copy.path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not discard repaired audio", exc_info=True)


def choose_queued_audio(master: tk.Tk, task: TranscriptionTask) -> bool:
    if isinstance(master, tk.Tk):
        tracks = _probe_without_blocking_tk(master, task.file_path)
    else:
        tracks = probe_audio_tracks(task.file_path)
    if tracks is None:
        return False
    if len(tracks) < 2:
        return True
    task.audio_track = choose_audio_track(master, basename(task.file_path), tracks)
    return task.audio_track is not None


def _probe_without_blocking_tk(master: tk.Tk, source: str) -> list[AudioTrack] | None:
    if getattr(master, "_audio_probe_busy", False):
        return None
    lifetime = tk.Toplevel(master)
    lifetime.withdraw()
    result: SimpleQueue[list[AudioTrack]] = SimpleQueue()
    tracks: list[AudioTrack] | None = None

    def work() -> None:
        try:
            result.put(probe_audio_tracks(source))
        except Exception:
            result.put([])

    def poll() -> None:
        nonlocal tracks
        try:
            tracks = result.get_nowait()
        except Empty:
            lifetime.after(30, poll)
        else:
            lifetime.destroy()

    setattr(master, "_audio_probe_busy", True)
    try:
        Thread(target=work, daemon=True, name="audio-track-probe").start()
        lifetime.after(0, poll)
        master.wait_window(lifetime)
        return tracks
    except tk.TclError:
        return None
    finally:
        setattr(master, "_audio_probe_busy", False)


def choose_audio_track(master: tk.Tk, name: str, tracks: list[AudioTrack]) -> int | None:
    dialog = tk.Toplevel(master)
    dialog.title(_("Choose audio track"))
    dialog.transient(master)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=px(16))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=name, wraplength=px(440)).pack(anchor="w")
    labels = []
    for track in tracks:
        parts = [_("Track {number}", number=track.ordinal + 1)]
        if track.language:
            parts.append(track.language)
        if track.title:
            parts.append(" ".join(track.title.split())[:72])
        if track.channels:
            parts.append(ngettext("{n} channel", "{n} channels", track.channels))
        if track.default:
            parts.append(_("Default"))
        labels.append(" · ".join(parts))
    choice = ttk.Combobox(body, state="readonly", values=labels, width=52)
    choice.current(default_audio_track(tracks))
    choice.pack(fill="x", pady=(px(8), px(12)))
    selected = None

    def accept() -> None:
        nonlocal selected
        selected = tracks[choice.current()].ordinal
        dialog.destroy()

    ttk.Button(body, text=_("Cancel"), command=dialog.destroy).pack(side="left")
    ttk.Button(body, text=_("Add to queue"), command=accept).pack(side="right")
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.bind("<Return>", lambda _event: accept())
    place_over(dialog, master)
    dialog.wait_visibility()
    dialog.grab_set()
    choice.focus_set()
    master.wait_window(dialog)
    return selected


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def offer_repaired_audio(
    master: tk.Tk, task: TranscriptionTask, folder: Path,
) -> RepairedAudio | None:
    dialog = tk.Toplevel(master)
    dialog.title(_("Repair audio"))
    dialog.transient(master)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=px(16))
    body.pack(fill="both", expand=True)
    status = tk.StringVar(master=dialog, value=_("Making an audio copy…"))
    ttk.Label(body, textvariable=status, wraplength=px(420)).pack(fill="x", pady=(0, px(12)))
    actions = ttk.Frame(body)
    actions.pack(fill="x")
    cancelled = Event()
    handoff = Lock()
    result: SimpleQueue[RepairedAudio | Exception | None] = SimpleQueue()
    copy: RepairedAudio | None = None
    accepted = False
    busy = True

    def cancel() -> None:
        if busy:
            cancelled.set()
            status.set(_("Cancelling…"))
            dismiss.state(["disabled"])
        else:
            dialog.destroy()

    def retry() -> None:
        nonlocal accepted
        accepted = True
        dialog.destroy()

    dismiss = ttk.Button(actions, text=_("Cancel"), command=cancel)
    dismiss.pack(side="left")
    dialog.protocol("WM_DELETE_WINDOW", cancel)
    dialog.bind("<Escape>", lambda _event: cancel())

    def work() -> None:
        try:
            finished = repair_audio(task.file_path, task.audio_track, folder, cancelled.is_set)
        except Exception as error:
            result.put(error)
            return
        with handoff:
            if cancelled.is_set() and finished is not None:
                _discard_copy(finished)
                finished = None
            result.put(finished)

    def poll() -> None:
        nonlocal busy, copy
        try:
            finished = result.get_nowait()
        except Empty:
            dialog.after(80, poll)
            return
        busy = False
        if isinstance(finished, RepairedAudio):
            copy = finished
        if cancelled.is_set() or isinstance(finished, AudioPreparationCancelled):
            dialog.destroy()
            return
        dismiss.configure(text=_("Close"))
        if isinstance(finished, RepairSpaceError):
            status.set(_("There is not enough disk space for a repaired audio copy."))
        elif isinstance(finished, OSError):
            status.set(_("Could not make an audio copy."))
        elif copy is None:
            status.set(_("No audio could be recovered."))
        else:
            length = _duration(copy.recovered)
            if copy.expected:
                status.set(_("About {recovered} of {expected} is playable. Damaged sections may be silent.",
                             recovered=length, expected=_duration(copy.expected)))
            else:
                status.set(_("About {recovered} is playable. Original duration unknown.", recovered=length))
            ttk.Button(actions, text=_("Try again"), command=retry).pack(side="right")

    place_over(dialog, master)
    dialog.wait_visibility()
    dialog.grab_set()
    thread = Thread(target=work, name="repair-audio", daemon=True)
    thread.start()
    dialog.after(80, poll)
    master.wait_window(dialog)
    with handoff:
        cancelled.set()
        if busy:
            try:
                remaining = result.get_nowait()
            except Empty:
                pass
            else:
                if isinstance(remaining, RepairedAudio):
                    copy = remaining
    if busy:
        thread.join(timeout=4)
    if copy is not None and not accepted:
        _discard_copy(copy)
    return copy if accepted else None
