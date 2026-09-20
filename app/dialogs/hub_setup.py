"""First-run Model Hub Folder picker.

Pops on the very first launch (and any launch where ``hub_folder``
is unset in the config) so the user can decide where Whisper model
files should live.

UX:

  +-----------------------------------------------------------+
  |  Choose Model Hub Folder                                   |
  +-----------------------------------------------------------+
  |  Whisper Transcriber Suite stores its speech-recognition   |
  |  models in a "model hub" folder. The default is a private  |
  |  per-user cache folder that is always writable.            |
  |                                                            |
  |  Hub folder:                                               |
  |  [ %LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\models ] [Browse…]|
  |                                                            |
  |  ☐ Use a different folder I'll pick                        |
  |                                                            |
  |          [ Use default ]   [ OK ]   [ Skip for now ]       |
  +-----------------------------------------------------------+

* "OK" persists whatever's in the entry box and closes.
* "Use default" resets the entry to ``core.hub.default_hub_folder()``
  and then closes (same effect as OK with the default value).
* "Skip for now" (formerly labeled "Cancel", which read as "abort" —
  it does not) closes without saving — the next launch will fire the
  dialog again, but the model loader uses the default value for
  this session so the user can still transcribe.

The dialog is purely Tk; it doesn't touch the filesystem until
the user clicks OK (which writes ``hub_folder`` to config). The
folder is created lazily by the model-download flow when needed.
"""
from __future__ import annotations

import logging
import os
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from core import hub as _hub
from core.config import save_config

logger = logging.getLogger(__name__)


class HubSetupDialog(tk.Toplevel):
    """Modal dialog that asks the user to pick / confirm the hub folder.

    Parameters
    ----------
    master:
        Parent Tk widget. The dialog is created as a Toplevel and
        ``transient + grab_set`` to act modally.
    config:
        Mutable config dict. ``hub_folder`` is written on OK / "Use
        default"; left untouched on Cancel.
    save:
        Save callback — defaults to ``core.config.save_config`` so
        the user's pick is persisted to disk. Tests inject a noop
        to avoid touching ``%APPDATA%``.
    on_done:
        Called after the user closes the dialog. Receives the
        resolved hub_folder string. Used by ``App.__init__`` to
        kick off the model load once the path is known.
    """

    def __init__(
        self,
        master: "tk.Tk | tk.Toplevel",
        config: dict,
        *,
        save: Callable[[dict], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Choose Model Hub Folder")
        self.transient(master)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._config = config
        self._save = save if save is not None else save_config
        self._on_done = on_done
        self._chosen_path: Optional[str] = None
        self._saved: bool = False

        # Initial value: any existing hub_folder (in case the dialog
        # was opened explicitly by a user re-picking), else the
        # platform-default per-user cache hub.
        initial = (config.get("hub_folder") or "").strip()
        if not initial:
            initial = str(_hub.default_hub_folder())
        self._path_var = tk.StringVar(value=initial)

        self._build()

        # Centre on parent + grab focus once the layout is laid out.
        self.update_idletasks()
        try:
            self.grab_set()
        except tk.TclError:
            # Headless test environments sometimes can't grab.
            pass
        self._center_on(master)

    # ---------- UI -----------------------------------------------------

    def _build(self) -> None:
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="Choose where Whisper Transcriber Suite should store its model files.",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            body,
            text=(
                "These files are large (1–3 GB each). The default is a\n"
                "private per-user cache folder that is always writable.\n"
                "Pick a different folder (e.g. an external drive) if you\n"
                "want to keep the models somewhere with more space."
            ),
            foreground="#666",
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(body)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="Hub folder:").pack(side="left")
        self._entry = ttk.Entry(row, textvariable=self._path_var, width=58)
        self._entry.pack(side="left", padx=(8, 4), fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse).pack(side="left")

        # Help line — show resolved default + remind user they can
        # change this later from the Advanced dialog.
        default_path = str(_hub.default_hub_folder())
        ttk.Label(
            body,
            text=f"Default if you accept: {default_path}",
            foreground="#666",
        ).pack(anchor="w", pady=(0, 10))

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(4, 0))
        # "Cancel" read as "abort" to at least one reviewer, when the real
        # behavior is "don't decide now" -- it still lets the app proceed
        # with the default for this session (see _on_cancel's docstring)
        # and asks again next launch, so a clearer label matches that.
        ttk.Button(actions, text="Skip for now", command=self._on_cancel).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(
            actions, text="OK", command=self._on_ok, style="Accent.TButton",
        ).pack(side="right")
        ttk.Button(
            actions, text="Use default", command=self._on_use_default,
        ).pack(side="right", padx=(0, 8))

    def _center_on(self, master: "tk.Misc") -> None:
        try:
            master.update_idletasks()
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width() or 800
            mh = master.winfo_height() or 600
            w = self.winfo_width() or 540
            h = self.winfo_height() or 220
            x = mx + max(0, (mw - w) // 2)
            y = my + max(0, (mh - h) // 2)
            self.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass

    # ---------- actions ------------------------------------------------

    def _browse(self) -> None:
        initial = (self._path_var.get() or "").strip()
        if initial and not os.path.isdir(initial):
            # filedialog can't open a non-existent path — fall back
            # to its parent or the user home.
            parent = os.path.dirname(initial)
            initial = parent if parent and os.path.isdir(parent) else ""
        folder = filedialog.askdirectory(
            parent=self,
            title="Pick the model hub folder",
            initialdir=initial or None,
            mustexist=False,
        )
        if folder:
            self._path_var.set(_hub.normalise_hub_path(folder))

    def _on_use_default(self) -> None:
        self._path_var.set(str(_hub.default_hub_folder()))
        self._on_ok()

    def _probe_writable(self, path: str) -> bool:
        """Confirm we can create + write inside ``path``.

        Creates the directory if needed and writes/deletes a temp file.
        On failure, warns the user and returns False so the caller keeps
        the dialog open. This catches the Program Files trap (a standard
        user picking a non-writable location) BEFORE the model download
        fails 3 GB in.
        """
        probe: Optional[str] = None
        try:
            os.makedirs(path, exist_ok=True)
            fd, probe = tempfile.mkstemp(prefix=".whisper-write-test-", dir=path)
            os.close(fd)
            os.unlink(probe)
            probe = None
            return True
        except OSError as e:
            logger.warning("Hub folder %r is not writable: %s", path, e)
            if probe is not None:
                # Either the close or the unlink above failed after
                # mkstemp succeeded — best-effort remove the probe so a
                # failed check doesn't litter the user's hub folder.
                try:
                    os.unlink(probe)
                except OSError:
                    pass
            messagebox.showwarning(
                "Folder not writable",
                (
                    f"Whisper cannot write to:\n\n{path}\n\n"
                    "Please pick a folder under your user profile (for "
                    "example on your main drive or an external drive)."
                ),
                parent=self,
            )
            return False

    def _on_ok(self) -> None:
        path = _hub.normalise_hub_path(self._path_var.get())
        if not self._probe_writable(path):
            # Keep the dialog open so the user can pick somewhere else.
            return
        self._chosen_path = path
        self._config["hub_folder"] = path

        # Also update the model folder -- for whichever model is actually
        # configured (this dialog also reopens mid-flow to retry a
        # non-writable folder for a download already in progress, e.g. a
        # user-picked "medium" model; hardcoding large-v3 here used to
        # silently redirect model_path at the wrong model's cache folder).
        model = self._config.get("model")
        model_name = model.get("name") if isinstance(model, dict) else ""
        if not isinstance(model_name, str) or not model_name.strip():
            model_name = "faster-whisper-large-v3"
        self._config["model_path"] = str(_hub.model_folder_for(path, model_name))

        try:
            self._save(self._config)
            self._saved = True
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist hub_folder: %s", e)
        self._close(path)

    def _on_cancel(self) -> None:
        # Cancel doesn't persist — but the caller still gets the
        # default so the model load can proceed for the session.
        path = str(_hub.default_hub_folder())
        self._chosen_path = path
        self._close(path)

    def _close(self, path: str) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        if self._on_done is not None:
            try:
                self._on_done(path)
            except Exception as e:  # noqa: BLE001
                logger.warning("hub_setup on_done callback raised: %s", e)
        try:
            self.destroy()
        except tk.TclError:
            pass

    # ---------- test introspection ------------------------------------

    @property
    def chosen_path(self) -> Optional[str]:
        return self._chosen_path

    @property
    def saved(self) -> bool:
        return self._saved


def ensure_hub_configured(
    master: "tk.Tk | tk.Toplevel",
    config: dict,
    *,
    save: Callable[[dict], None] | None = None,
    on_done: Callable[[str], None] | None = None,
) -> str:
    """High-level entry point: show the dialog if + only if needed.

    Returns the path the rest of the app should use as the hub
    folder for this session. When the user has already picked a
    folder (or the migration filled it in from a legacy
    ``model_path``), this is a no-op that simply returns the
    stored value.

    The dialog is shown asynchronously — the caller's startup
    continues immediately with the default path, and ``on_done``
    fires later when the user has decided. This matches the
    existing model-load standby pattern where the model worker
    starts in the background while the UI is still painting.
    """
    if _hub.is_hub_configured(config):
        return (config.get("hub_folder") or "").strip()
    HubSetupDialog(master, config, save=save, on_done=on_done)
    # Until the user picks, use the default so any code path that
    # consults hub_folder during startup gets a sensible value.
    return str(_hub.default_hub_folder())
