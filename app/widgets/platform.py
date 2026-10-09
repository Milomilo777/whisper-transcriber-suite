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
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_label(default: str, what: str = "") -> str:
    """The wording of an "open this folder" action: macOS says Reveal in Finder.

    ``default`` is returned unchanged everywhere else. ``what`` names the thing
    on macOS when "Reveal in Finder" alone would be unclear (a menu that is not
    about one selected item), for example ``"Log Folder"``.
    """
    if sys.platform != "darwin":
        return default
    return f"Reveal {what} in Finder" if what else "Reveal in Finder"


def open_folder(
    folder: str,
    parent: "tk.Misc | None" = None,
    select: "str | None" = None,
) -> None:
    """Show ``folder`` in the file manager.

    ``select``: a file to highlight. Only macOS uses it (``open -R`` reveals the
    file inside its folder, like Finder's own Reveal in Finder); Windows and
    Linux open the folder exactly as before.
    """
    if (
        sys.platform == "darwin" and select and os.path.isfile(select)
        and folder and os.path.isdir(folder)
    ):
        try:
            subprocess.run(["open", "-R", select], check=False)
            return
        except OSError:
            pass  # fall through to opening the folder the usual way
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
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
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
