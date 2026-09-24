"""The "Best model for this computer" dialog: Whisper models for this hardware.

Opened from the Transcribe tab's "Best for this PC…" button. The hardware
check (``core.hardware.cuda_status`` + ``recommend_models``) can take a few
seconds on a first run (it loads the CUDA libraries), so it runs on a daemon
thread; the result is picked up by a main-thread ``after`` poll -- the worker
never touches Tk (``after`` from another thread raises on Python 3.14).
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from core import hardware as _hw

if TYPE_CHECKING:
    from app.app import App

logger = logging.getLogger(__name__)

_TITLES = {"fastest": "Fastest", "accurate": "Most accurate"}


class ModelAdvisorDialog(tk.Toplevel):
    """Shows one or two recommended models with a "Use this model" button."""

    def __init__(self, master: "tk.Misc", app: "App") -> None:
        super().__init__(master)
        self.app = app
        self.title("Best model for this computer")
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)
        self._result: dict[str, Any] = {}

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.summary_var = tk.StringVar(value="Checking this computer…")
        ttk.Label(
            body, textvariable=self.summary_var, wraplength=520, justify="left",
        ).pack(anchor="w", pady=(0, 10))
        self.picks_frame = ttk.Frame(body)
        self.picks_frame.pack(fill="x")
        ttk.Button(body, text="Close", command=self.destroy).pack(anchor="e", pady=(12, 0))

        self._thread = threading.Thread(target=self._check, daemon=True)
        self._thread.start()
        self.after(100, self._poll)

    # ---------- background check ----------------------------------------

    def _check(self) -> None:
        try:
            status = _hw.cuda_status()
            self._result["done"] = (
                status,
                _hw.recommend_models(status),
                _hw.system_ram_gb(),
                os.cpu_count() or 0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Model recommendation failed")
            self._result["error"] = e

    def _poll(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if "error" in self._result:
            self.summary_var.set(f"Could not check this computer: {self._result['error']}")
            return
        if "done" not in self._result:
            self.after(100, self._poll)
            return
        status, picks, ram_gb, cores = self._result["done"]
        self._show(status, picks, ram_gb, cores)

    # ---------- result ----------------------------------------------------

    def _show(
        self,
        status: _hw.CudaStatus,
        picks: list[_hw.ModelPick],
        ram_gb: float,
        cores: int,
    ) -> None:
        cpu = f"{cores} CPU cores" if cores else "the CPU"
        if ram_gb:
            cpu += f", {ram_gb:.0f} GB memory"
        if status.usable:
            mem = f", {status.memory_mb / 1024:.0f} GB" if status.memory_mb else ""
            summary = (
                f"{status.gpu_name or 'NVIDIA GPU'}{mem}: models run on the GPU."
            )
        elif status.gpu_present:
            summary = (
                f"{status.gpu_name or 'Your NVIDIA GPU'} cannot be used yet, so "
                f"these are for {cpu}. Advanced > Re-detect hardware explains "
                "why and can fix it; then open this window again."
            )
        else:
            summary = f"No usable NVIDIA GPU, so models run on {cpu}."
        self.summary_var.set(summary)

        from core.model_manager import (
            DEFAULT_MODEL_SLUG,
            approx_download_size_text,
            catalog_models,
            model_downloaded,
        )

        cfg = self.app.app_config
        labels = dict(catalog_models(cfg))
        current = str(cfg.get("whisper_model") or DEFAULT_MODEL_SLUG)
        for pick in picks:
            if pick.slug not in labels:
                continue  # not in this catalog (e.g. a trimmed online catalog)
            title = "Recommended" if len(picks) == 1 else _TITLES.get(pick.kind, pick.kind)
            card = ttk.LabelFrame(self.picks_frame, text=title, padding=10)
            card.pack(fill="x", pady=(0, 8))
            ttk.Label(
                card, text=labels[pick.slug], font=("TkDefaultFont", 10, "bold"),
            ).pack(anchor="w")
            ttk.Label(card, text=pick.reason, wraplength=500, justify="left").pack(
                anchor="w", pady=(2, 4),
            )
            if model_downloaded(cfg, pick.slug):
                note = "Already downloaded."
            else:
                size = approx_download_size_text(cfg, pick.slug)
                note = f"Downloads once on first use ({size})." if size else "Downloads once on first use."
            ttk.Label(card, text=note, foreground="#666").pack(anchor="w")
            btn = ttk.Button(
                card, text="Use this model",
                command=lambda slug=pick.slug: self._use(slug),
            )
            btn.pack(anchor="e", pady=(6, 0))
            if pick.slug == current:
                btn.configure(text="Current model")
                btn.state(["disabled"])

    def _use(self, slug: str) -> None:
        """Pick ``slug`` exactly as choosing it in the Transcribe tab does."""
        from core.model_manager import catalog_models

        label = dict(catalog_models(self.app.app_config)).get(slug)
        var = getattr(self.app, "transcribe_model_var", None)
        if not label or var is None:
            return
        var.set(label)
        self.app._on_model_selected()
        if str(self.app.app_config.get("whisper_model") or "") == slug:
            self.destroy()  # applied (a declined "stop the running job?" keeps it open)


def open_model_advisor(master: "tk.Misc", app: "App") -> ModelAdvisorDialog:
    return ModelAdvisorDialog(master, app)
