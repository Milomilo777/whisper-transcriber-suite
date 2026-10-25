"""The interface-language button above the tabs, its chooser and the restart question.

One place for everything outside Advanced settings that deals with the language of the app: the
permanent button (globe, own name of the running language, a down arrow), the chooser it and
View > "Interface language..." open, saving the pick (config key ``ui_language``, the same value
the Advanced combobox stores) and offering the restart a change needs.

The language is read once at start-up, so a change shows after a restart. "Restart now" is
offered only where the app can start itself again (``core.process_exit``) and only while no
transcription or download job is active.
"""
from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from core import process_exit
from core.config import save_config

from app import i18n, rtl_layout
from app.dialogs import advanced
from app.dpi import place_over
from app.i18n import _
from app.theme import bidi_display, icons, tokens
from app.widgets.notice import notify
from app.widgets.tooltip import bind_tooltip

logger = logging.getLogger(__name__)

AUTO = advanced._UI_LANGUAGE_AUTO
_IDLE_STATUSES = ("finished", "cancelled", "error")
_CHECK = "✓"  # the mark in front of the language that runs now
_ARROW = "▾"  # the down arrow of the button


# --- names and entries -----------------------------------------------------------------------

def autonym(code: str) -> str:
    """A language's own name; the code itself for one the app does not list (pseudo-locale)."""
    known = i18n.LANGUAGES_BY_CODE.get(code)
    return known.endonym if known else code


def button_text() -> str:
    """The button label: the running language's own name and the arrow, left to right."""
    return bidi_display.ltr_base(f"{autonym(i18n.current_language())}  {_ARROW}")


def chooser_entries(setting: object) -> list[tuple[str, str]]:
    """(label, stored value) of the chooser lines: Automatic (naming what it gives), English
    right below it (always easy to find), then the other languages grouped by script."""
    choices = advanced._ui_language_choices(setting)
    auto = _("Automatic (system: {language})", language=autonym(i18n.setting_language(AUTO)))
    choices[0] = (bidi_display.ltr_base(auto), AUTO)
    english = next((c for c in choices if c[1] == i18n.SOURCE_LANGUAGE), None)
    if english is not None:
        choices.remove(english)
        choices.insert(1, english)
    return choices


# --- the button ------------------------------------------------------------------------------

def build_button(app: Any, parent: tk.Misc) -> ttk.Button:
    """The permanent button in the top-right corner of ``parent`` (the same place in every
    language, right to left too). Keyboard focusable; ``app.open_ui_language_chooser`` runs on click."""
    bar = ttk.Frame(parent)
    bar.pack(side="top", fill="x", padx=tokens.SPACE_SM, pady=(tokens.SPACE_XS, 0))
    rtl_layout.keep_ltr(bar)
    button = ttk.Button(bar, text=button_text(), compound="left", takefocus=True,
                        command=lambda: app.open_ui_language_chooser())
    button.pack(side="right")
    button.bar = bar  # type: ignore[attr-defined]
    _tint(button)
    button.bind("<<ThemeChanged>>", lambda _e: _tint(button), add="+")
    bind_tooltip(button, lambda: _("Interface language"))
    return button


def _tint(button: ttk.Button) -> None:
    try:
        photo = icons.load_icon(button, "globe", icons.text_colour(), 16)
    except Exception:  # noqa: BLE001 - a missing icon must not stop the window opening
        logger.warning("Could not load the language icon", exc_info=True)
        return
    button.configure(image=photo)
    button.image = photo  # type: ignore[attr-defined]


# --- the chooser -----------------------------------------------------------------------------

def open_chooser(app: Any) -> None:
    """Open the language chooser (one at a time); OK or a double click saves the pick."""
    shown = getattr(app, "_ui_language_chooser", None)
    try:
        if shown is not None and shown.winfo_exists():
            shown.lift()
            shown.focus_force()
            return
    except tk.TclError:
        pass
    setting = app.app_config.get("ui_language", AUTO)
    entries = chooser_entries(setting)
    current = advanced._ui_language_index(entries, setting) or 0

    dlg = tk.Toplevel(app)
    app._ui_language_chooser = dlg
    dlg.title(_("Interface language"))
    dlg.transient(app)
    dlg.resizable(False, True)
    body = ttk.Frame(dlg, padding=12)
    body.pack(fill="both", expand=True)
    lines = ttk.Frame(body)
    lines.pack(fill="both", expand=True)
    box = tk.Listbox(lines, exportselection=False, activestyle="dotbox", width=36,
                     height=min(len(entries), 14), selectmode="browse")
    scroll = ttk.Scrollbar(lines, orient="vertical", command=box.yview)
    box.configure(yscrollcommand=scroll.set)
    box.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    for index, (label, _value) in enumerate(entries):
        box.insert("end", f"{_CHECK}  {label}" if index == current else f"     {label}")
    box.selection_set(current)
    box.activate(current)
    box.see(current)
    if sys.platform.startswith("win"):
        _use_ui_font(box)

    def close() -> None:
        app._ui_language_chooser = None
        dlg.destroy()

    def accept(_event: object = None) -> str:
        picked = box.curselection()
        close()
        if picked and picked[0] != current:
            apply_choice(app, entries[picked[0]][1])
        return "break"

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text=_("OK"), command=accept).pack(side="right")
    ttk.Button(buttons, text=_("Cancel"), command=close).pack(side="right", padx=(0, 8))
    box.bind("<Double-Button-1>", accept)
    box.bind("<Return>", accept)
    dlg.bind("<Escape>", lambda _e: close())
    dlg.protocol("WM_DELETE_WINDOW", close)
    place_over(dlg, app)
    box.focus_set()
    dlg.grab_set()


def _use_ui_font(box: tk.Listbox) -> None:
    """Segoe UI draws every script of the names through font fallback at the right height."""
    from tkinter import font as tkfont

    from app.theme import script_fonts

    try:
        ui = tokens.FONT_FAMILIES_WINDOWS["ui"]
        if ui in script_fonts.installed_families(box):
            size = int(tkfont.nametofont("TkTextFont", root=box).cget("size"))
            box.configure(font=(ui, size))
    except (tk.TclError, ValueError, KeyError):
        logger.info("Could not set the font of the language list", exc_info=True)


# --- saving and restarting -------------------------------------------------------------------

def apply_choice(app: Any, value: str) -> bool:
    """Store ``value`` as ``ui_language`` and offer the restart. False when it could not be saved."""
    previous = app.app_config.get("ui_language", AUTO)
    app.app_config["ui_language"] = value
    try:
        save_config(app.app_config)
    except Exception as e:  # noqa: BLE001 - the pick must not be lost silently
        app.app_config["ui_language"] = previous
        logger.exception("Could not save the interface language")
        messagebox.showerror(_("Interface language"), str(e), parent=app)
        return False
    offer_restart(app, value)
    return True


def jobs_running(app: Any) -> bool:
    """True while a transcription or a download is not finished (waiting ones count)."""
    for queue_name in ("queue", "download_queue"):
        for task in getattr(app, queue_name, None) or []:
            if getattr(task, "status", "") not in _IDLE_STATUSES:
                return True
    return False


def restart_supported() -> bool:
    return process_exit.relaunch_command() is not None


def offer_restart(app: Any, value: str, notifier: Any = notify) -> None:
    """Tell the person when ``value`` applies: ask "Restart now" / "Later" where the app can
    restart itself, else the plain notice. Nothing when the running language already is ``value``."""
    if os.environ.get(i18n.ENV_LANGUAGE, "").strip():
        notifier(app, _(
            "The {variable} environment variable sets the interface language of this run. "
            "Your choice applies when the app starts without it.", variable=i18n.ENV_LANGUAGE))
        return
    if i18n.setting_language(value) == i18n.current_language():
        return
    text = _("The interface language changes the next time you start the app.")
    if not restart_supported():
        notifier(app, text)
        return
    busy = jobs_running(app)
    if ask_restart(app, text, busy):
        restart_now(app)


def ask_restart(app: Any, text: str, busy: bool) -> bool:
    """The "Restart now" / "Later" question; True for "Restart now". While a job runs there is
    only "Later" and a note."""
    answer = {"now": False}
    dlg = tk.Toplevel(app)
    dlg.title(_("Interface language"))
    dlg.transient(app)
    dlg.resizable(False, False)
    body = ttk.Frame(dlg, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=text, wraplength=360, justify="left").pack(anchor="w")
    if busy:
        ttk.Label(body, text=_("A task is still running, so restarting is not offered now."),
                  wraplength=360, justify="left",
                  foreground=tokens.themed(tokens.TEXT_MUTED)).pack(anchor="w", pady=(8, 0))
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(14, 0))

    def choose(now: bool) -> None:
        answer["now"] = now
        dlg.destroy()

    later = ttk.Button(row, text=_("Later"), command=lambda: choose(False))
    later.pack(side="right")
    if not busy:
        now_button = ttk.Button(row, text=_("Restart now"), command=lambda: choose(True))
        now_button.pack(side="right", padx=(0, 8))
        now_button.focus_set()
    else:
        later.focus_set()
    dlg.protocol("WM_DELETE_WINDOW", lambda: choose(False))
    dlg.bind("<Escape>", lambda _e: choose(False))
    place_over(dlg, app)
    dlg.grab_set()
    app.wait_window(dlg)
    return answer["now"]


def restart_now(app: Any) -> None:
    """Close the app through the normal exit (its own questions about unsaved work included)
    and start it again. If the exit is declined the restart is cancelled."""
    if not process_exit.request_relaunch():
        return
    try:
        app._force_exit()
    finally:
        if not getattr(app, "_closing", False):
            process_exit.cancel_relaunch()

