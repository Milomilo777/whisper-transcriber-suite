"""The first-run language suggestion window (see ``app.ui_language_hint`` for when it appears)."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any

from core.config import save_config

from app import i18n, ui_language_hint
from app.dialogs.ui_language import apply_choice, autonym
from app.dpi import place_over
from app.i18n import _
from app.theme import bidi_display

logger = logging.getLogger(__name__)

# How long to wait before asking again while the Quick Start or hub setup window is open.
RETRY_MS = 1000


def maybe_suggest(app: Any) -> None:
    """Windows, first run: offer the language the regional format and the keyboard point to
    (see ``app.ui_language_hint``). Never switches by itself; nothing happens without a clear hint."""
    if getattr(app, "_closing", False):
        return
    if (getattr(app, "_quick_start_open", False) or getattr(app, "_hub_setup_open", False)
            or getattr(app, "_model_question_open", False)):
        # Those windows hold the input grab, so this one's buttons would do nothing; ask again later.
        app.after(RETRY_MS, lambda: maybe_suggest(app))
        return
    code = ui_language_hint.suggestion_for_this_machine(app.app_config)
    if code:
        show_suggestion(app, code)


def _remember_answer(app: Any) -> None:
    app.app_config[ui_language_hint.HINT_KEY] = True
    try:
        save_config(app.app_config)
    except Exception:  # noqa: BLE001 - at worst the question comes once more
        logger.warning("Could not save that the language question was answered", exc_info=True)


def show_suggestion(app: Any, code: str) -> tk.Toplevel:
    """A small window that does not block the app: the question in the suggested language and in
    English, and "Use <language>" / "Keep English" / "Other...". Any answer, and closing the
    window, is remembered so the question is asked once."""
    name = autonym(code)
    dlg = tk.Toplevel(app)
    dlg.title(_("Interface language"))
    dlg.transient(app)
    dlg.resizable(False, False)
    body = ttk.Frame(dlg, padding=16)
    body.pack(fill="both", expand=True)
    in_english = _("Use {language} for this app?", language=name)
    in_language = i18n.text_in(code, "Use {language} for this app?", language=name)
    for text in dict.fromkeys((in_language, in_english)):  # one line when no translation exists yet
        ttk.Label(body, text=text, wraplength=380, justify="left").pack(anchor="w", pady=(0, 4))
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(12, 0))

    def answer(then: Any = None) -> None:
        _remember_answer(app)
        dlg.destroy()
        if then is not None:
            then()

    ttk.Button(row, text=_("Other…"), command=lambda: answer(lambda: app.open_ui_language_chooser())
               ).pack(side="right")
    ttk.Button(row, text=_("Keep English"), command=answer).pack(side="right", padx=(0, 8))
    use = ttk.Button(row, text=bidi_display.ltr_base(_("Use {language}", language=name)),
                     command=lambda: answer(lambda: apply_choice(app, code)))
    use.pack(side="right", padx=(0, 8))
    use.focus_set()
    dlg.protocol("WM_DELETE_WINDOW", answer)
    dlg.bind("<Escape>", lambda _e: answer())
    place_over(dlg, app)
    return dlg
