"""Dialogs for local media audio."""
from __future__ import annotations

import tkinter as tk
from os.path import basename
from tkinter import ttk

from app.dpi import place_over, px
from app.i18n import _, ngettext
from core.media_audio import AudioTrack, default_audio_track, probe_audio_tracks
from core.task import TranscriptionTask


def choose_queued_audio(master: tk.Tk, task: TranscriptionTask) -> bool:
    tracks = probe_audio_tracks(task.file_path)
    if len(tracks) < 2:
        return True
    task.audio_track = choose_audio_track(master, basename(task.file_path), tracks)
    return task.audio_track is not None


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
