"""Save a transcript as a shareable interactive web page (one ``.html`` file).

Used by the transcript viewer (its in-memory segments, unsaved edits
included) and by the Last result card (the transcript JSON on disk). The
question window says what the page contains before anything is written, and
offers the footer link as a tick box. The page itself is built by
:mod:`core.writers.html_transcript`.
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from app.dpi import px
from app.theme import tokens
from app.widgets.platform import open_async
from core.writers import html_transcript

BUTTON_TEXT = "Save shareable page"

ACTION_SAVE = "save"
ACTION_SAVE_OPEN = "open"


def load_transcript(json_path: str) -> list[dict[str, Any]]:
    """The segment dicts of a transcript JSON; ValueError when it is not one."""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError("This file is not a transcript JSON (its root is not a list).")
    segments = [item for item in payload if isinstance(item, dict)]
    if payload and not segments:
        raise ValueError("This JSON list holds no transcript segments.")
    return segments


def load_chapters(json_path: str) -> list[dict[str, Any]]:
    """The ``<name>.chapters.json`` sidecar next to *json_path*; [] when absent or unreadable."""
    path = os.path.splitext(json_path)[0] + ".chapters.json"
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def privacy_note(media_path: str | None) -> str:
    """What the page holds and how its audio works, in plain words."""
    note = (
        "Saves one .html file that opens in any web browser, with no install and no "
        "internet connection. The page contains the full transcript text, the speaker "
        "names and the chapter titles, so share it only with people who may read them."
    )
    if media_path:
        note += (
            f"\n\nThe audio is not copied into the page: it plays "
            f"“{os.path.basename(media_path)}” from where that file is now, and "
            "it records the way there (the folder names between the page and the media). "
            "Keep the page and the media file together (for example in one folder) when "
            "you move or send them."
        )
    else:
        note += "\n\nNo media file was found for this transcript, so the page has no player."
    return note


def ask_options(master: "tk.Misc", *, media_path: str | None) -> tuple[str, bool] | None:
    """Modal question: ``(action, footer)`` or None when cancelled."""
    dialog = tk.Toplevel(master)
    dialog.title(BUTTON_TEXT)
    dialog.transient(master)  # type: ignore[arg-type]
    dialog.resizable(False, False)
    result: dict[str, Any] = {"action": None}
    footer = tk.BooleanVar(master=dialog, value=True)

    def pick(action: str | None) -> None:
        result["action"] = action
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(
        body, text="Save the transcript as a web page you can share",
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        body, text=privacy_note(media_path), foreground=tokens.themed(tokens.TEXT_MUTED),
        wraplength=px(460), justify="left",
    ).pack(anchor="w", pady=(6, 10))
    ttk.Checkbutton(
        body, text=f"Add a “{html_transcript.FOOTER_TEXT}” link at the bottom",
        variable=footer,
    ).pack(anchor="w")
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(12, 0))
    ttk.Button(actions, text="Cancel", command=lambda: pick(None)).pack(side="right")
    ttk.Button(
        actions, text="Save and open in browser", style="Accent.TButton",
        command=lambda: pick(ACTION_SAVE_OPEN),
    ).pack(side="right", padx=(0, 8))
    ttk.Button(actions, text="Save…", command=lambda: pick(ACTION_SAVE)).pack(
        side="right", padx=(0, 8)
    )
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(None))
    dialog.update_idletasks()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # headless test runs cannot always grab
    master.wait_window(dialog)
    if result["action"] is None:
        return None
    return result["action"], bool(footer.get())


def open_in_browser(path: str, master: "tk.Misc") -> None:
    """Open the saved page with the system's default handler for .html files.

    Does not make the window wait for the opener; a failure is shown when it comes.
    """
    def done(error: BaseException | None) -> None:
        if error is not None:
            messagebox.showerror(BUTTON_TEXT, f"The page was saved to\n{path}\n"
                                 f"but could not be opened:\n{error}",
                                 parent=master)  # type: ignore[arg-type]

    open_async(path, master, done)


def save_shareable_page(
    master: "tk.Misc",
    *,
    segments: list[dict[str, Any]],
    media_path: str | None,
    json_path: str,
    chapters: list[dict[str, Any]] | None = None,
    language: str | None = None,
) -> str | None:
    """Ask, pick the file name, write the page; the saved path or None."""
    media = media_path if media_path and os.path.isfile(media_path) else None
    if not any(isinstance(s, dict) and str(s.get("text") or "").strip() for s in segments):
        messagebox.showinfo(BUTTON_TEXT, "This transcript has no text to put on a page.",
                            parent=master)  # type: ignore[arg-type]
        return None
    answer = ask_options(master, media_path=media)
    if answer is None:
        return None
    action, footer = answer
    folder = os.path.dirname(os.path.abspath(json_path))
    stem = os.path.splitext(os.path.basename(json_path))[0]
    path = filedialog.asksaveasfilename(
        parent=master,  # type: ignore[arg-type]
        title=BUTTON_TEXT,
        initialdir=folder,
        initialfile=stem + ".html",
        defaultextension=".html",
        filetypes=[("Web page", "*.html"), ("All files", "*.*")],
    )
    if not path:
        return None
    # "All files" lets any name through: never replace the transcript or the media.
    sources = {os.path.normcase(os.path.abspath(p)) for p in (json_path, media) if p}
    if os.path.normcase(os.path.abspath(path)) in sources:
        messagebox.showerror(BUTTON_TEXT, "Choose another file name: this one is the "
                             "transcript or media file itself.",
                             parent=master)  # type: ignore[arg-type]
        return None
    try:
        html_transcript.write_page(
            segments, media or "", out_path=path, chapters=chapters, language=language,
            footer=footer, title=stem,
        )
    except OSError as e:
        messagebox.showerror(BUTTON_TEXT, f"Could not save the page:\n{e}",
                             parent=master)  # type: ignore[arg-type]
        return None
    # Only a web page is handed to the system opener: "All files" lets the user type
    # any name, and opening a .bat or .hta would run it.
    if action == ACTION_SAVE_OPEN and path.lower().endswith((".html", ".htm")):
        open_in_browser(path, master)
    return path
