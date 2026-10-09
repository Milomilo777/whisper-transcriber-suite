"""Hardware autodetect wizard (v0.8).

Modal Toplevel that surfaces every accelerator tier the host
supports (probed by :mod:`core.hardware`), highlights the one the
bundled faster_whisper backend can actually drive, lets the user
override the auto-pick, and persists the choice to
``hardware.json``. ``core.transcriber.detect_device`` reads that
file on the next model load.

Layout:

  +----------------------------------------------------------+
  |  Detected hardware:                                       |
  |  +------+---------------------------------+-------------+ |
  |  |  ✓   | NVIDIA CUDA (float16) — RTX… | recommended  | |
  |  |      | Snapdragon X NPU (QNN) — …    | install ext. | |
  |  |      | CPU int8 — Intel i7-…         | fallback     | |
  |  +------+---------------------------------+-------------+ |
  |  Selected tier: NVIDIA CUDA (float16)                     |
  |  (why an NVIDIA GPU cannot be used yet + how to fix it)   |
  |  [ Re-probe ] [ Copy diagnostics ]                        |
  |  [ Install GPU support ]  (only when that is the fix)     |
  |                                                           |
  |                    [ Cancel ] [ Save and use ]            |
  +----------------------------------------------------------+

There is no speed benchmark here: transcription runs in a worker
process, so the GUI process has no loaded model to time, and a timing
on a silent clip says nothing about the tier being saved.
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable, Optional

from app.dpi import px
from app.theme import tokens
from app.widgets.error_dialog import show_error
from core import hardware as _hw
from core import offline

if TYPE_CHECKING:
    from app.app import App


logger = logging.getLogger(__name__)


# Tree iid of the informational "NVIDIA CUDA — needs setup" row; not a tier.
_CUDA_INFO_ROW = "cuda_unusable"


class HardwareWizard(tk.Toplevel):
    """Modal wizard for picking the acceleration tier."""

    def __init__(self, master: "tk.Tk | tk.Toplevel", *, app: "App | None" = None) -> None:
        super().__init__(master)
        self.app = app
        self.title("Hardware autodetect")
        self.transient(master)
        # Tk keeps a single grab per display and does not stack them, so
        # our grab_set() silently replaces the master's (Advanced settings
        # launches this wizard and owns the grab at that point). Destroying
        # this window does not hand the grab back, which would leave the
        # master non-modal; remember it so _on_close can restore it.
        try:
            self._master_had_grab = master.grab_current() is master
        except tk.TclError:
            self._master_had_grab = False
        self.grab_set()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._tiers: list[_hw.Tier] = []
        self._cuda_status: _hw.CudaStatus | None = None
        self._busy: bool = False
        self._selected_idx: int = -1
        # True once the user clicked a tier; the pre-selected automatic pick
        # is not a choice (see _save_and_close).
        self._user_picked: bool = False
        # Generation token: each _reprobe bumps it; a result from a superseded
        # probe (stale token) is ignored.
        self._probe_seq: int = 0
        # Kept so tests / callers can join the in-flight probe before
        # asserting on the populated tree (the probe runs off-thread).
        self._probe_thread: threading.Thread | None = None
        # The worker thread stashes (seq, tiers) here under the lock; a
        # main-thread after()-poll picks it up. We deliberately do NOT call
        # self.after() from the worker thread — on Python 3.14 that raises
        # "main thread is not in main loop".
        self._probe_lock = threading.Lock()
        self._probe_result: (
            tuple[int, list[_hw.Tier], _hw.CudaStatus | None] | None
        ) = None
        # Re-entrancy guard: True while we programmatically set the tree
        # selection so _on_select ignores the event we caused (see
        # _select_index — otherwise it feedback-loops forever).
        self._selecting: bool = False

        self._build()
        self._reprobe()

    # ---------- UI -----------------------------------------------------

    def _build(self) -> None:
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="Detected hardware (best first):",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        cols = ("pick", "label", "note")
        self.tree = ttk.Treeview(
            body, columns=cols, show="headings", height=8,
        )
        self.tree.heading("pick", text="")
        self.tree.heading("label", text="Tier")
        self.tree.heading("note", text="Status")
        self.tree.column("pick", width=px(40), anchor="center")
        self.tree.column("label", width=px(480), anchor="w")
        self.tree.column("note", width=px(140), anchor="w")
        self.tree.tag_configure("supported", foreground=tokens.themed(tokens.SUCCESS_STRONG))
        self.tree.tag_configure("unsupported", foreground=tokens.themed(tokens.TEXT_MISSING))
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.status_var = tk.StringVar(value="Probing…")
        ttk.Label(body, textvariable=self.status_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
            anchor="w", pady=(6, 0)
        )

        # Why a detected NVIDIA GPU cannot be used yet, and what fixes it
        # (core.hardware.cuda_status). Before this line existed the wizard
        # just listed "CPU" with no explanation (GitHub issue #7).
        self.cuda_var = tk.StringVar(value="")
        ttk.Label(
            body, textvariable=self.cuda_var, foreground=tokens.themed(tokens.WARNING_TEXT),
            wraplength=px(640), justify="left",
        ).pack(anchor="w", pady=(4, 0))

        tools = ttk.Frame(body)
        tools.pack(fill="x", pady=(8, 4))
        self.reprobe_btn = ttk.Button(tools, text="Re-probe", command=self._reprobe)
        self.reprobe_btn.pack(side="left")
        self.diag_btn = ttk.Button(
            tools, text="Copy diagnostics", command=self._copy_diagnostics,
        )
        self.diag_btn.pack(side="left", padx=(8, 0))
        self.install_btn = ttk.Button(
            tools, text="Install GPU support…", command=self._install_gpu_support,
        )
        # Packed only when installing NVIDIA's cuBLAS is the fix
        # (see _update_cuda_line).

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Cancel", command=self._on_close).pack(
            side="right", padx=(8, 0)
        )
        self.save_btn = ttk.Button(
            actions, text="Save and use", command=self._save_and_close
        )
        self.save_btn.pack(side="right")

    # ---------- behaviour ----------------------------------------------

    def _reprobe(self) -> None:
        """Re-run the hardware probe OFF the Tk main thread.

        ``probe_tiers()`` does seconds-long first imports (ctranslate2 /
        onnxruntime / openvino / torch) and loads the CUDA runtime library
        (cuBLAS), which can BLOCK for many seconds on a broken CUDA stack.
        Running that inline froze the UI ("Not Responding"). Mirror the
        benchmark path: run on a daemon thread, then marshal the result back
        to the Tk thread via App.post_to_main (with the no-app self.after(0)
        fallback). A generation token guards against a stale probe landing
        after a newer one (or after the wizard is destroyed).
        """
        self._probe_seq += 1
        seq = self._probe_seq
        self.status_var.set("Probing…")
        self._set_buttons_enabled(False)
        with self._probe_lock:
            self._probe_result = None
        self._probe_thread = threading.Thread(
            target=self._reprobe_worker, args=(seq,), daemon=True,
        )
        self._probe_thread.start()
        # Drain the result on the Tk main thread. Scheduling the poll here
        # (we are on the main thread) is safe; scheduling self.after() from
        # the worker thread is NOT (RuntimeError on Python 3.14: "main thread
        # is not in main loop"). The worker only stashes the result.
        self._schedule_probe_poll()

    def _schedule_probe_poll(self) -> None:
        try:
            self.after(50, self._poll_probe_result)
        except Exception:  # noqa: BLE001
            logger.exception("Probe poll failed to schedule")

    def _poll_probe_result(self) -> None:
        """Main-thread poll: apply the worker's result once it lands."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        with self._probe_lock:
            pending = self._probe_result
            self._probe_result = None
        if pending is None:
            # Still probing — re-arm unless a newer probe superseded us.
            self._schedule_probe_poll()
            return
        seq, tiers, status = pending
        self._reprobe_done(seq, tiers, status)

    def _reprobe_worker(self, seq: int) -> None:
        """Daemon-thread body: run the blocking probe, stash the result.

        Must NOT touch Tk (no self.after / no widget calls) — the main-thread
        _poll_probe_result picks the stashed result up.
        """
        # One CUDA check, shared by the tier list and the "needs setup" line,
        # so the two can't disagree and the (slow) chain runs once.
        status: _hw.CudaStatus | None
        try:
            status = _hw.cuda_status()
        except Exception:  # noqa: BLE001
            logger.exception("CUDA status check failed")
            status = None
        try:
            tiers = _hw.probe_tiers(status)
        except Exception as e:  # noqa: BLE001
            logger.exception("Hardware probe failed: %s", e)
            try:
                tiers = _hw._probe_cpu()
            except Exception:  # noqa: BLE001
                tiers = []
        with self._probe_lock:
            self._probe_result = (seq, tiers, status)

    def _reprobe_done(
        self,
        seq: int,
        tiers: list[_hw.Tier],
        status: "_hw.CudaStatus | None" = None,
    ) -> None:
        """Main-thread continuation: refresh the tree + re-enable buttons.

        Ignores a stale result (an older probe finishing after a newer
        _reprobe) or a destroyed wizard.
        """
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if seq != self._probe_seq:
            return  # superseded by a newer probe
        self._tiers = tiers
        self._cuda_status = status
        self._user_picked = False  # the list was rebuilt: the old click no longer counts
        self._refresh_tree()
        self._update_cuda_line()
        self._set_buttons_enabled(True)
        if not self._tiers:
            self.status_var.set("No tier detected — falling back to CPU.")
            return
        recommended = _hw.first_supported_tier(self._tiers)
        # Pre-select the recommended tier so the user can just hit Save.
        # set_widget_selection=False: we are inside an after()-driven refresh
        # running under update()/mainloop(); a synchronous ttk selection_set
        # here wedges. The ✓ column + _selected_idx convey the pick.
        for idx, t in enumerate(self._tiers):
            if t.slug == recommended.slug:
                self._select_index(idx, set_widget_selection=False)
                break
        self.status_var.set(
            f"Recommended: {recommended.label}  "
            f"(device={recommended.device}, compute_type={recommended.compute_type})"
        )

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Toggle Re-probe / Save / Install while a probe is in flight."""
        flag = "!disabled" if enabled else "disabled"
        self._busy = not enabled
        for btn in (
            getattr(self, "reprobe_btn", None),
            getattr(self, "save_btn", None),
            getattr(self, "install_btn", None),
        ):
            if btn is None:
                continue
            try:
                btn.state([flag])
            except tk.TclError:
                pass
        if enabled:
            self._sync_save_button()

    def _sync_save_button(self) -> None:
        """Save is off for a tier whose backend is not bundled: such a choice
        is ignored by the device pick, so saving it would only mislead."""
        if self._busy:
            return
        idx = self._selected_idx
        usable = 0 <= idx < len(self._tiers) and self._tiers[idx].backend == "faster_whisper"
        try:
            self.save_btn.state(["!disabled" if usable else "disabled"])
        except tk.TclError:
            pass

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for idx, tier in enumerate(self._tiers):
            supported = tier.backend == "faster_whisper"
            note = "ready" if supported else "needs backend"
            tags = ("supported",) if supported else ("unsupported",)
            self.tree.insert(
                "", "end", iid=str(idx),
                values=("", tier.label, note), tags=tags,
            )
        status = self._cuda_status
        if status is not None and status.gpu_present and not status.usable:
            # List the GPU even though it cannot be picked yet, so "only CPU
            # detected" never looks like the GPU was not seen at all. The
            # non-numeric iid keeps it out of selection (_on_select).
            self.tree.insert(
                "", 0, iid=_CUDA_INFO_ROW,
                values=(
                    "",
                    f"NVIDIA CUDA — {status.gpu_name or 'NVIDIA GPU'}",
                    "needs setup",
                ),
                tags=("unsupported",),
            )

    def _update_cuda_line(self) -> None:
        """Explain an unusable NVIDIA GPU (or a first-run note) under the table."""
        status = self._cuda_status
        text = ""
        if status is not None and status.gpu_present:
            if status.usable:
                text = status.note
            else:
                name = status.gpu_name or "NVIDIA GPU"
                text = f"{name} cannot be used yet. {status.summary()}"
        self.cuda_var.set(text)
        try:
            if status is not None and status.can_install_runtime:
                if not self.install_btn.winfo_ismapped():
                    self.install_btn.pack(side="left", padx=(8, 0))
            elif self.install_btn.winfo_ismapped():
                self.install_btn.pack_forget()
        except tk.TclError:
            pass

    def _select_index(self, idx: int, *, set_widget_selection: bool = True) -> None:
        """Mark tier ``idx`` as chosen (logical state + the ✓ column).

        ``set_widget_selection`` also drives the Treeview's own selection +
        focus. Skip it (pass False) when called from inside an after()-driven
        refresh that itself runs under update()/mainloop(): calling ttk
        ``selection_set`` from within the event dispatch wedges the ttk
        ``_selection`` C call. The auto-pick after a re-probe therefore sets
        only the logical state + checkmark; a real user click goes through
        _on_select where the widget selection already happened.
        """
        if not (0 <= idx < len(self._tiers)):
            return
        self._selected_idx = idx
        # selection_set/focus below fire <<TreeviewSelect>>, which calls
        # _on_select, which calls back into _select_index. Without this guard
        # that is an infinite feedback loop once a Tk event pump is running.
        # Suppress our own programmatic selection event.
        self._selecting = True
        try:
            for child in self.tree.get_children():
                try:
                    self.tree.set(child, "pick", "")
                except tk.TclError:
                    continue
            try:
                self.tree.set(str(idx), "pick", "✓")
                if set_widget_selection:
                    self.tree.selection_set(str(idx))
                    self.tree.focus(str(idx))
            except tk.TclError:
                pass
        finally:
            self._selecting = False
        self._sync_save_button()

    def _on_select(self, _event: tk.Event) -> None:
        # Ignore the <<TreeviewSelect>> we triggered ourselves from
        # _select_index — otherwise the two re-enter each other forever.
        if getattr(self, "_selecting", False):
            return
        sel = self.tree.focus()
        if not sel:
            return
        try:
            idx = int(sel)
        except ValueError:
            # The informational "NVIDIA CUDA — needs setup" row.
            if sel == _CUDA_INFO_ROW and self._cuda_status is not None:
                self.status_var.set(self._cuda_status.summary())
            return
        self._user_picked = True
        self._select_index(idx)
        if 0 <= idx < len(self._tiers):
            t = self._tiers[idx]
            note = "" if t.backend == "faster_whisper" else " -- its backend is not bundled, so it cannot be saved"
            self.status_var.set(
                f"Selected: {t.label}  "
                f"(device={t.device}, compute_type={t.compute_type}){note}"
            )

    # ---------- diagnostics / GPU runtime install ----------------------

    def _run_in_background(
        self,
        fn: Callable[[], object],
        on_done: Callable[[object, BaseException | None], None],
    ) -> None:
        """Run ``fn`` off the Tk thread; call ``on_done(result, error)`` on it.

        Same stash-and-poll pattern as the probe: the worker never touches Tk
        (self.after from a non-main thread raises on Python 3.14).
        """
        box: dict[str, tuple[object, BaseException | None]] = {}

        def _work() -> None:
            try:
                box["done"] = (fn(), None)
            except Exception as e:  # noqa: BLE001
                box["done"] = (None, e)

        threading.Thread(target=_work, daemon=True).start()

        def _poll() -> None:
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            if "done" not in box:
                self.after(100, _poll)
                return
            result, error = box["done"]
            on_done(result, error)

        self.after(100, _poll)

    def _copy_diagnostics(self) -> None:
        """Copy a full GPU/CUDA report to the clipboard for a bug report."""
        self.diag_btn.state(["disabled"])
        self.status_var.set("Collecting GPU diagnostics…")

        def _done(report: object, error: object) -> None:
            try:
                self.diag_btn.state(["!disabled"])
            except tk.TclError:
                return
            text = str(report) if error is None else f"Diagnostics failed: {error}"
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
            except tk.TclError:
                pass
            if self.app is not None:
                self.app.log(text)
            self.status_var.set(
                "GPU diagnostics copied to the clipboard (also written to the "
                "log) — paste them into a GitHub issue."
            )

        self._run_in_background(_hw.diagnostics_report, _done)

    def _install_gpu_support(self) -> None:
        """pip-install NVIDIA cuBLAS (core.optional_deps 'cuda_runtime')."""
        status = self._cuda_status
        if status is None or not status.can_install_runtime or self._busy:
            return
        from core import optional_deps

        if offline.is_offline():
            self.status_var.set(offline.refused("installing GPU support"))
            return
        if not messagebox.askyesno(
            "Install GPU support",
            "Your NVIDIA GPU needs NVIDIA's cuBLAS library, which the graphics "
            "driver does not include.\n\n"
            "Download and install it now? It is a one-time download of about "
            "550 MB from NVIDIA (via PyPI) into:\n"
            f"{optional_deps.extras_dir()}",
            parent=self,
        ):
            return
        self._set_buttons_enabled(False)
        self.status_var.set("Installing GPU support (about 550 MB)… this can take a few minutes.")
        tail: list[str] = []
        app = self.app

        def _log(line: str) -> None:
            tail.append(line)
            del tail[:-15]
            if app is not None:
                log = app.log
                app.post_to_main(lambda: log(f"[GPU support] {line}"))

        # A present-but-unloadable copy must be reinstalled, not reported as
        # already installed by install()'s short-circuit.
        force = optional_deps.is_available("cuda_runtime")

        def _work() -> bool:
            return optional_deps.install("cuda_runtime", log_cb=_log, force=force)

        def _done(ok: object, error: object) -> None:
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            if ok is True and error is None:
                if app is not None:
                    app.log("GPU support installed; re-probing hardware.")
                self._reprobe()
                return
            self._set_buttons_enabled(True)
            if offline.is_offline():
                self.status_var.set(offline.message("installing GPU support"))
                return
            self.status_var.set("GPU support install failed — see the log.")
            show_error(
                self, "Install failed",
                "Could not install NVIDIA's cuBLAS library.",
                detail=str(error) if error is not None else "\n".join(tail),
            )

        self._run_in_background(_work, _done)

    # ---------- save / close -------------------------------------------

    def _save_and_close(self) -> None:
        if not (0 <= self._selected_idx < len(self._tiers)):
            messagebox.showinfo(
                "Pick a tier", "Select a tier in the table first.", parent=self
            )
            return
        tier = self._tiers[self._selected_idx]
        if tier.backend != "faster_whisper":
            messagebox.showinfo(
                "Cannot be used yet",
                f"{tier.label}\n\nThis needs a backend that is not bundled, so the "
                "app would ignore it. Pick a tier marked ready.",
                parent=self,
            )
            return
        status = self._cuda_status
        if (
            not self._user_picked
            and tier.device == "cpu"
            and status is not None
            and status.gpu_present
        ):
            # Nothing was chosen and the only reason for CPU is that the GPU is
            # unusable right now. Saving "cpu" would pin it for good, so a later
            # driver or runtime fix would never reach the automatic CUDA pick.
            if self.app is not None:
                self.app.log(
                    "Hardware: no tier chosen and the NVIDIA GPU is not usable yet; "
                    "nothing saved, the automatic pick stays in charge."
                )
            self._on_close()
            return
        try:
            path = _hw.save_hardware_choice(tier)
        except Exception as e:  # noqa: BLE001
            show_error(
                self, "Save failed",
                "Could not save your hardware preference.", detail=str(e),
            )
            return
        if self.app is not None:
            self.app.log(
                f"Hardware preference saved → {path}  "
                f"(device={tier.device}, compute_type={tier.compute_type})"
            )
            self._restart_idle_engine()
        self._on_close()

    def _restart_idle_engine(self) -> None:
        """Make a saved choice take effect on the next transcription.

        The transcription worker picks its device once, when it starts, so
        without a restart a new choice only applied after the app was
        restarted. Stops the workers (a fresh one starts on the next
        transcription) -- after asking, if one is busy.
        """
        svc = getattr(self.app, "transcription_service", None)
        if svc is None or self.app is None:
            return
        try:
            workers = svc.active_workers()
        except Exception:  # noqa: BLE001
            return
        if not workers:
            return
        # Same "a transcription is running -- stop it?" prompt as an engine
        # or model switch (App._confirm_backend_switch); no prompt when idle.
        confirm = getattr(self.app, "_confirm_backend_switch", None)
        if callable(confirm) and not confirm(
            self,
            title="Apply now?",
            action="Applying the new hardware setting now",
            question=(
                "Apply it now? Choose No to let it finish; the setting is "
                "then used after the app is restarted."
            ),
        ):
            return
        try:
            svc.stop_all()
            self.app.log("The new hardware setting is used from the next transcription.")
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Could not restart the transcription worker: {e}")

    def _on_close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        # Hand the master's modal grab back (see __init__), but only when
        # nothing newer holds it -- never steal a grab from another dialog.
        if self._master_had_grab:
            try:
                if self.master.winfo_exists() and self.master.grab_current() is None:
                    self.master.grab_set()
            except tk.TclError:
                pass
        self.destroy()


def open_hardware_wizard(
    master: "tk.Tk | tk.Toplevel",
    *,
    app: Optional["App"] = None,
) -> None:
    """Helper for callers that want to spawn the wizard programmatically."""
    HardwareWizard(master, app=app)
