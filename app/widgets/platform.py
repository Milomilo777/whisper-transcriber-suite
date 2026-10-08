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


def open_folder(folder: str, parent: "tk.Misc | None" = None) -> None:
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
            import subprocess
            subprocess.run(["open", folder], check=False)
        else:
            import subprocess
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
