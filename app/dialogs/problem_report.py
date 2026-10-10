"""Help → About → Report a problem: a short message sent without a GitHub account.

The text goes through :mod:`core.problem_report` to the usage-statistics server. The window says
what is sent (the person's words, the app version and the operating system) and what is not, shows
how many characters are left, and sends on a worker thread; Tk is only touched on the main thread.
"""
from __future__ import annotations

import queue
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Any

from app.dpi import place_over
from app.theme import tokens
from core import problem_report as pr
from core._threads import safe_thread

_POLL_MS = 100
_GRAB_POLL_MS = 50
_GRAB_TRIES = 40  # about two seconds


def open_problem_report(parent: tk.Misc, config: dict[str, Any], github_url: str) -> tk.Toplevel:
    dlg = tk.Toplevel(parent)
    dlg.title("Report a problem")
    dlg.transient(parent.winfo_toplevel())
    dlg.resizable(True, True)
    body = ttk.Frame(dlg, padding=(16, 14, 16, 8))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(2, weight=1)

    ttk.Label(body, text="What went wrong?", font=("TkDefaultFont", 11, "bold")).grid(
        row=0, column=0, sticky="w")
    ttk.Label(
        body, wraplength=460, justify="left",
        foreground=tokens.themed(tokens.TEXT_MUTED),
        text=("Describe what you did and what happened. Your message is sent to the project with "
              "the app version and your operating system only: no file names, no logs, no "
              "settings. There is no reply; for a conversation, use GitHub."),
    ).grid(row=1, column=0, sticky="w", pady=(4, 8))

    text = tk.Text(body, width=60, height=8, wrap="word", undo=True)
    text.grid(row=2, column=0, sticky="nsew")
    info = ttk.Frame(body)
    info.grid(row=3, column=0, sticky="ew", pady=(6, 0))
    info.columnconfigure(0, weight=1)
    ttk.Label(info, text="Sent with: " + pr.system_summary(),
              foreground=tokens.themed(tokens.TEXT_MUTED)).grid(row=0, column=0, sticky="w")
    count_var = tk.StringVar(master=dlg, value=f"0 / {pr.MAX_CHARS}")
    count = ttk.Label(info, textvariable=count_var, foreground=tokens.themed(tokens.TEXT_MUTED))
    count.grid(row=0, column=1, sticky="e", padx=(12, 0))
    status_var = tk.StringVar(master=dlg, value="")
    status = ttk.Label(body, textvariable=status_var, wraplength=460, justify="left")
    status.grid(row=4, column=0, sticky="w", pady=(6, 0))

    footer = ttk.Frame(dlg, padding=(16, 4, 16, 14))
    footer.pack(fill="x")
    gh = ttk.Label(footer, text="Have a GitHub account? Report it there",
                   foreground=tokens.themed(tokens.LINK), cursor="hand2")
    gh.pack(side="left")
    gh.bind("<Button-1>", lambda _e: webbrowser.open(github_url))
    send_btn = ttk.Button(footer, text="Send", style="Accent.TButton")
    send_btn.pack(side="right")
    ttk.Button(footer, text="Cancel", command=dlg.destroy).pack(side="right", padx=(0, 8))

    def _current() -> str:
        return text.get("1.0", "end-1c")

    def _update_count(_e: object = None) -> None:
        n = len(pr.clean_text(_current()))
        raw = len(" ".join(_current().split()))
        count_var.set(f"{n} / {pr.MAX_CHARS}" + ("  (the rest is cut)" if raw > pr.MAX_CHARS else ""))
        send_btn.state(["!disabled"] if n else ["disabled"])

    def _on_modified(_e: object = None) -> None:
        # <<Modified>> fires for every change (typing, paste, drag and drop, undo);
        # clearing the flag re-arms it for the next change.
        text.edit_modified(False)
        _update_count()

    text.bind("<<Modified>>", _on_modified, add="+")
    _update_count()

    results: "queue.Queue[str | None]" = queue.Queue()

    def _worker(message: str) -> None:
        try:
            pr.send(config, message)
            results.put(None)
        except pr.ProblemReportError as e:
            results.put(str(e))
        except Exception as e:  # noqa: BLE001 - any failure is shown, never raised into Tk
            results.put(f"Could not send the report: {e}")

    def _poll() -> None:
        try:
            outcome = results.get_nowait()
        except queue.Empty:
            if dlg.winfo_exists():
                dlg.after(_POLL_MS, _poll)
            return
        if not dlg.winfo_exists():
            return
        if outcome is None:
            status_var.set("Thank you. Your report was sent.")
            status.configure(foreground=tokens.themed(tokens.SUCCESS_TEXT))
            send_btn.configure(text="Close", command=dlg.destroy)
            send_btn.state(["!disabled"])
            text.configure(state="disabled")
        else:
            status_var.set(outcome)
            status.configure(foreground=tokens.themed(tokens.DANGER_TEXT))
            text.configure(state="normal")
            send_btn.state(["!disabled"])

    def _send() -> None:
        message = _current()
        try:
            pr.build_payload(message)  # empty text: say so before any thread starts
        except pr.ProblemReportError as e:
            status_var.set(str(e))
            status.configure(foreground=tokens.themed(tokens.DANGER_TEXT))
            return
        send_btn.state(["disabled"])
        text.configure(state="disabled")  # no edits (and no re-enabled Send) while sending
        status_var.set("Sending…")
        status.configure(foreground=tokens.themed(tokens.TEXT_MUTED))
        safe_thread(_worker, args=(message,), name="problem-report")
        dlg.after(_POLL_MS, _poll)

    send_btn.configure(command=_send)
    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    place_over(dlg, parent)
    _take_grab(parent, dlg)
    text.focus_set()
    return dlg


def _take_grab(parent: tk.Misc, dlg: tk.Toplevel) -> None:
    """Move a modal grab from ``parent`` (the About window) to ``dlg`` and give it back on close.

    About holds a local grab. A child window opened under it gets no mouse clicks on macOS
    (Send and Cancel did nothing on 10.15), so the grab moves to this window while it is open.
    """
    owner = parent.winfo_toplevel()
    try:
        had_grab = owner.grab_current() is owner
    except tk.TclError:
        had_grab = False
    if had_grab:
        owner.grab_release()

    def _grab_when_viewable(tries: int = 0) -> None:
        # Never block on wait_visibility(): a window that never maps (main window
        # minimised, no visible desktop) would freeze the app. Poll briefly instead.
        try:
            if not dlg.winfo_exists():
                return
            if dlg.winfo_viewable():
                dlg.grab_set()
            elif tries < _GRAB_TRIES:
                dlg.after(_GRAB_POLL_MS, lambda: _grab_when_viewable(tries + 1))
        except tk.TclError:
            pass  # the window still works without a grab

    _grab_when_viewable()

    def _give_back(event: "tk.Event[tk.Misc]") -> None:
        if event.widget is not dlg or not had_grab:
            return
        try:
            if owner.winfo_exists():
                owner.grab_set()
        except tk.TclError:
            pass

    dlg.bind("<Destroy>", _give_back, add="+")
