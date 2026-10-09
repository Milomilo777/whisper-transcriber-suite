"""Cross-platform UI helpers."""
from __future__ import annotations

import errno
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from app.widgets.error_dialog import show_error


class NoDefaultAppError(OSError):
    """The system has no app set to open this kind of file."""


# Windows ERROR_NO_ASSOCIATION, raised by os.startfile for such a file.
_WINERROR_NO_ASSOCIATION = 1155
# macOS `open` and xdg-open return as soon as the app has been asked to start.
# One that is still running after this long is a handler that waits for the app
# to quit, so the file was handed over.
_OPENER_WAIT_S = 5.0
# Plain-text formats the Mac text editor can show when no app is set for them.
_TEXT_EXTENSIONS = frozenset(
    {".srt", ".vtt", ".ass", ".ssa", ".lrc", ".txt", ".json", ".csv", ".tsv", ".md"}
)


def _run_opener(cmd: list[str], path: str) -> None:
    """Run ``open`` / ``xdg-open`` and check how it ended.

    Raises ``FileNotFoundError`` / ``PermissionError`` for those causes and
    :class:`NoDefaultAppError` for any other failure of a file that exists.
    """
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        code = proc.wait(timeout=_OPENER_WAIT_S)
    except subprocess.TimeoutExpired:
        return
    if code == 0:
        return
    if not os.path.exists(path):
        raise FileNotFoundError(errno.ENOENT, "No such file", path)
    if cmd[0] == "xdg-open" and code == 5:  # xdg-open: no permission
        raise PermissionError(errno.EACCES, "Permission denied", path)
    raise NoDefaultAppError(
        f"No app is set to open this kind of file ({cmd[0]} exited with code {code})."
    )


def open_with_default_app(path: str) -> None:
    """Open the file *path* with the system's default app (Windows, macOS,
    Linux). Raises :class:`NoDefaultAppError` when no app is set for the file
    type, and another ``OSError`` when it cannot be opened."""
    if sys.platform == "win32":
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as e:
            if getattr(e, "winerror", None) == _WINERROR_NO_ASSOCIATION:
                raise NoDefaultAppError(
                    "No app is set to open this kind of file."
                ) from e
            raise
    elif sys.platform == "darwin":
        _run_opener(["open", path], path)
    else:
        _run_opener(["xdg-open", path], path)


def _file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return f"{ext} files" if ext else "this kind of file"


def open_file(
    path: str,
    parent: "tk.Misc | None" = None,
    error_text: str = "Could not open that file with your system's default app.",
) -> bool:
    """Open ``path`` with the default app and always tell the person how it went.

    True when an app took the file. When no app is set for the file type, the
    file is shown in its folder (a text file opens in the Mac text editor) and a
    short notice says so; any other failure shows an error with ``error_text``.
    Returns False in both of those cases; never fails silently.
    """
    try:
        open_with_default_app(path)
        return True
    except NoDefaultAppError:
        pass
    except OSError as e:
        _show_open_error(parent, error_text, str(e))
        return False
    if is_darwin() and os.path.splitext(path)[1].lower() in _TEXT_EXTENSIONS:
        try:
            _run_opener(["open", "-t", path], path)
            return True
        except OSError:
            pass  # not even the text editor: show it in its folder below
    open_folder(os.path.dirname(path) or ".", parent=parent, select=path)
    message = f"No app is set to open {_file_kind(path)}; the file is shown in its folder."
    if parent is not None:
        from app.widgets.notice import notify

        notify(parent, message, "warning")
    else:
        messagebox.showinfo("No app to open the file", message)
    return False


def _show_open_error(parent: "tk.Misc | None", text: str, detail: str) -> None:
    if isinstance(parent, (tk.Tk, tk.Toplevel)):
        show_error(parent, "Open failed", text, detail=detail)
    else:
        kwargs = {"parent": parent} if parent is not None else {}
        messagebox.showerror(
            "Open failed", f"{text}\n{detail}", **kwargs  # type: ignore[arg-type]
        )


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
