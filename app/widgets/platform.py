"""Cross-platform UI helpers."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from app.widgets.error_dialog import show_error


def open_with_default_app(path: str) -> None:
    """Open the file *path* with the system's default app (Windows, macOS,
    Linux) without waiting for it. Raises ``OSError`` when it cannot start."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], stdin=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL)


def is_darwin() -> bool:
    """True on macOS (the platform the Finder wording and ``open -R`` are for)."""
    return sys.platform == "darwin"


def reveal_label(default: str) -> str:
    """Wording of an action that shows one file in the file manager.

    macOS says "Reveal in Finder"; ``default`` is returned unchanged elsewhere.
    Use it only where a file is selected (see :func:`open_folder`'s ``select``).
    """
    return "Reveal in Finder" if is_darwin() else default


def folder_label(default: str, what: str = "Folder") -> str:
    """Wording of an action that only opens a folder: "Open <what> in Finder" on macOS."""
    return f"Open {what} in Finder" if is_darwin() else default


def folder_action_label(default: str, what: str, target: "str | None") -> str:
    """:func:`reveal_label` when ``target`` (a file to select) exists, else :func:`folder_label`."""
    return reveal_label(default) if target else folder_label(default, what)


def open_folder(
    folder: str,
    parent: "tk.Misc | None" = None,
    select: "str | None" = None,
) -> None:
    """Show ``folder`` in the file manager.

    ``select``: a file to highlight. Only macOS uses it (``open -R`` reveals the
    file inside its folder, like Finder's own Reveal in Finder; when that fails
    the folder is opened instead); Windows and Linux open the folder exactly as
    before.
    """
    if (
        is_darwin() and select and os.path.isfile(select)
        and folder and os.path.isdir(folder)
    ):
        try:
            if subprocess.run(
                ["open", "-R", select], stdin=subprocess.DEVNULL, check=False
            ).returncode == 0:
                return
        except OSError:
            pass
        # `open -R` failed: open the folder the usual way below.
    if not folder or not os.path.isdir(folder):
        kwargs = {"parent": parent} if parent is not None else {}
        messagebox.showwarning(
            "Folder missing",
            f"Could not open: {folder or '(empty)'}",
            **kwargs,  # type: ignore[arg-type]
        )
        return
    try:
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], stdin=subprocess.DEVNULL, check=False)
        else:
            subprocess.run(["xdg-open", folder], stdin=subprocess.DEVNULL, check=False)
    except Exception as e:  # noqa: BLE001
        # show_error needs a real Tk/Toplevel to attach to and to read
        # geometry from; open_folder's own signature allows a looser
        # tk.Misc (or no parent at all) for callers that don't have one,
        # so fall back to the plain messagebox in that rarer case.
        if isinstance(parent, (tk.Tk, tk.Toplevel)):
            show_error(
                parent, "Open folder failed",
                "Could not open that folder.", detail=str(e),
            )
        else:
            kwargs = {"parent": parent} if parent is not None else {}
            messagebox.showerror(
                "Open folder failed", str(e), **kwargs  # type: ignore[arg-type]
            )
