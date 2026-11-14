"""A friendly error dialog: a plain-language sentence up front, with the
raw exception text (if any) tucked behind a collapsible "Details"
disclosure. The detail is still there — copyable, for a bug report — it
just isn't the first (and only) thing a non-technical user has to read,
unlike a bare ``messagebox.showerror(title, str(e))``.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from app.dpi import px
from app.i18n import _, plain
from app.theme import tokens

_PREVIOUS_GRAB_ATTR = "_wts_error_previous_grab"
logger = logging.getLogger(__name__)


def _unpost_combobox_grab(parent: tk.Misc) -> None:
    """Finish a known ttk popdown's saved-grab restoration before replacing it."""
    try:
        holder = str(parent.tk.call("grab", "current", str(parent)))
        if not holder or parent.tk.call("winfo", "class", holder) != "ComboboxPopdown":
            return
        combo_path = str(parent.tk.call("winfo", "parent", holder))
        if (holder != combo_path + ".popdown"
                or parent.tk.call("winfo", "class", combo_path) != "TCombobox"):
            return
        combo = parent.nametowidget(combo_path)
        if not isinstance(combo, ttk.Combobox) or str(combo) != combo_path:
            return
    except (tk.TclError, KeyError):
        # Unknown raw grabs are neither repaired nor restored by this helper.
        return
    try:
        parent.tk.call("ttk::combobox::Unpost", combo_path)
        # Unmap may be delivered later. Consume its saved grab now;
        # ttk::RestoreGrab removes the slot, so a later call is inert.
        parent.tk.call("ttk::releaseGrab", holder)
    except tk.TclError:
        logger.exception("Closing the combobox popdown before an error dialog failed")


def show_error(
    parent: "tk.Misc", title: str, message: str, detail: str | None = None,
) -> None:
    parent = parent.winfo_toplevel()
    # A popdown's later Unmap handler would otherwise restore its old grab
    # over this error. Unpost only a validated, Python-owned ttk Combobox.
    _unpost_combobox_grab(parent)
    try:
        parent_viewable = bool(parent.winfo_viewable())
    except tk.TclError:
        parent_viewable = False
    top = tk.Toplevel(parent)
    top.title(title)
    if parent_viewable:
        top.transient(parent)
    top.resizable(False, False)

    # Tk keeps a single grab per display and does not stack them: the
    # grab_set() below silently replaces whoever holds it. Destroying this
    # dialog does NOT hand the grab back, so an error shown while a modal
    # dialog is open (Advanced settings, the hardware wizard, ...) would
    # leave that dialog non-modal once dismissed. Remember the current
    # grab holder -- which is NOT always ``parent`` (background paths pass
    # the App root even while a dialog is up) -- and restore it on close.
    previous_grab: tk.Misc | None = None
    try:
        previous_grab = parent.grab_current()
    except (tk.TclError, KeyError):
        # Tcl-created windows (for example a Combobox popdown) have no
        # Python wrapper, so grab_current's widget lookup raises KeyError.
        previous_grab = None
    if not isinstance(previous_grab, (tk.Tk, tk.Toplevel)):
        # Only a window can meaningfully be modal; a popup menu's internal
        # grab (or anything else) must not be re-grabbed later.
        previous_grab = None

    setattr(top, _PREVIOUS_GRAB_ATTR, previous_grab)
    restored = False
    parent_map_id: str | None = None

    def _unbind_parent_map() -> None:
        nonlocal parent_map_id
        identifier, parent_map_id = parent_map_id, None
        if identifier is not None:
            try:
                # Older Tkinter clears the entire sequence even with a funcid.
                # Remove only our generated command line and its registration.
                script = str(parent.tk.call("bind", str(parent), "<Map>"))
                prefix = f'if {{"[{identifier} '
                kept = "".join(line for line in script.splitlines(keepends=True)
                               if not line.startswith(prefix))
                parent.tk.call("bind", str(parent), "<Map>", kept)
                parent.deletecommand(identifier)
            except tk.TclError:
                pass  # Parent teardown already removes its bindings.

    def _restore_grab(event: "tk.Event[tk.Misc] | None" = None) -> None:
        nonlocal restored
        if (event is not None and event.widget is not top) or restored:
            return
        _unbind_parent_map()
        restored = True
        owner = previous_grab
        try:
            # An older error can close before the one above it. Follow its
            # saved predecessor instead of losing the original modal host.
            while owner is not None and not owner.winfo_exists():
                owner = getattr(owner, _PREVIOUS_GRAB_ATTR, None)
            if owner is not None:
                current = owner.grab_current()
                # As in widgets/grab.py, Destroy may precede grab release.
                if current is None or current is top:
                    owner.grab_set()
        except (tk.TclError, KeyError):
            # Teardown or an unwrapped newer holder: never steal its grab.
            pass

    def _close() -> None:
        try:
            top.destroy()
        except tk.TclError:
            pass
        _restore_grab()

    top.protocol("WM_DELETE_WINDOW", _close)
    top.bind("<Destroy>", _restore_grab, add="+")

    body = ttk.Frame(top, padding=16)
    body.pack(fill="both", expand=True)

    msg_row = ttk.Frame(body)
    msg_row.pack(fill="x")
    # A messagebox.showerror shows the platform's error icon; keep that
    # at-a-glance "something went wrong" cue here too. A coloured glyph
    # instead of an image keeps this working on every platform/theme.
    icon = ttk.Label(msg_row, text="⚠", foreground=tokens.themed(tokens.DANGER_ICON))
    try:
        icon_font = tkfont.nametofont("TkDefaultFont").copy()
        icon_font.configure(size=16)
        icon.configure(font=icon_font)
        # A tkinter Font deletes its Tcl font when the Python object is
        # garbage-collected; park a reference on the widget to keep it
        # alive as long as the label is.
        setattr(icon, "_font_ref", icon_font)
    except tk.TclError:
        pass
    icon.pack(side="left", anchor="n", padx=(0, 10))
    ttk.Label(msg_row, text=message, wraplength=px(380), justify="left").pack(
        side="left", anchor="w"
    )

    if detail:
        toggle_row = ttk.Frame(body)
        toggle_row.pack(fill="x", pady=(10, 0))

        # A scrollbar in case ``detail`` is ever longer than the 5 visible
        # lines (today every call site passes only str(e) — normally a
        # short one-liner — but nothing here should silently hide part of
        # the text if that ever changes).
        detail_box = ttk.Frame(body)
        text_box = tk.Text(detail_box, height=5, width=54, wrap="word")
        detail_scroll = ttk.Scrollbar(detail_box, orient="vertical", command=text_box.yview)
        text_box.configure(yscrollcommand=detail_scroll.set)
        text_box.insert("1.0", detail)
        text_box.configure(state="disabled")
        text_box.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        state = {"shown": False}

        def _copy_detail() -> None:
            try:
                top.clipboard_clear()
                top.clipboard_append(plain(detail or ""))
            except tk.TclError:
                pass

        def _toggle() -> None:
            if state["shown"]:
                detail_box.pack_forget()
                toggle_btn.configure(text=_("Show details ▸"))
            else:
                detail_box.pack(fill="both", expand=True, pady=(6, 0))
                toggle_btn.configure(text=_("Hide details ▾"))
            state["shown"] = not state["shown"]

        toggle_btn = ttk.Button(toggle_row, text=_("Show details ▸"), command=_toggle)
        toggle_btn.pack(side="left")
        copy_btn = ttk.Button(toggle_row, text=_("Copy details"), command=_copy_detail)
        copy_btn.pack(side="left", padx=(8, 0))
        # Invoke the focused detail action before the toplevel's default
        # Return binding can dismiss the dialog (or a class binding repeats it).
        for button in (toggle_btn, copy_btn):
            for sequence in ("<Return>", "<KP_Enter>"):
                button.bind(sequence, lambda _e, btn=button: (btn.invoke(), "break")[1])

    ok_btn = ttk.Button(body, text=_("OK"), command=_close)
    ok_btn.pack(anchor="e", pady=(14, 0))

    # Same keyboard contract as a native messagebox: Enter/Esc dismiss,
    # and focus starts on OK so a plain Enter works immediately.
    top.bind("<Return>", lambda _e: _close())
    top.bind("<Escape>", lambda _e: _close())

    def _position_error() -> None:
        try:
            if parent_viewable:
                x = parent.winfo_rootx() + (parent.winfo_width() - top.winfo_width()) // 2
                y = parent.winfo_rooty() + (parent.winfo_height() - top.winfo_height()) // 2
                # Preserve a visible owner's secondary-monitor coordinates.
                screen_w = parent.winfo_screenwidth()
                screen_h = parent.winfo_screenheight()
                if 0 <= parent.winfo_rootx() < screen_w and 0 <= parent.winfo_rooty() < screen_h:
                    x = max(x, 0)
                    y = max(y, 0)
            else:
                # Hidden/iconic coordinates may be minimized far off-screen.
                x = max((top.winfo_screenwidth() - top.winfo_width()) // 2, 0)
                y = max((top.winfo_screenheight() - top.winfo_height()) // 2, 0)
            # A literal "+" keeps negative positions absolute, not edge offsets.
            top.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _parent_mapped(event: tk.Event[tk.Misc]) -> None:
        nonlocal parent_viewable
        if event.widget is not parent or parent_map_id is None:
            return
        try:
            if not parent.winfo_viewable() or not top.winfo_exists():
                return
            parent_viewable = True
            _unbind_parent_map()
            top.transient(parent)
            _position_error()
            try:
                current = top.grab_current()
            except KeyError:
                return  # Never lift or focus over an unwrapped newer holder.
            if current is None or current is top:
                top.lift()
                ok_btn.focus_set()
        except tk.TclError:
            logger.exception("Restoring an error dialog after its owner mapped failed")

    if not parent_viewable:
        parent_map_id = parent.bind("<Map>", _parent_mapped, add="+")
    top.update_idletasks()
    _position_error()
    try:
        top.grab_set()
    except tk.TclError:
        pass
    ok_btn.focus_set()
    try:
        top.bell()
    except tk.TclError:
        pass
