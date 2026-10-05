"""Quick start: three choices on the first launch of a new install.

The user picks the main spoken language, "Fast" or "Best quality", and the folder for
downloads. The model comes from the per-language table (``core.language_defaults``);
each choice shows its download size and a rough time per minute of audio on this
computer (``core.hardware.estimate_seconds_per_audio_minute``). The hardware check can
take a few seconds (it loads the CUDA libraries), so it runs on a daemon thread and a
main-thread ``after`` poll picks the result up, as in ``model_advisor``.

The window never touches the network: the model still downloads on the first
transcription, after Finish. Skip keeps today's behaviour (the model-folder picker
follows); Skip, Finish and closing the window all mean the window never shows again.
``should_show`` is false for an existing install (see ``core.config.load_config``) and
when ``quick_start_enabled`` is off.
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from core import hardware as _hw
from core import hub as _hub
from core.language_defaults import recommended_model

logger = logging.getLogger(__name__)

AUTO_LANGUAGE_LABEL = "Several languages / not sure"
MODES = (("fast", "Fast"), ("best", "Best quality"))

Probe = Callable[[], tuple[_hw.CudaStatus, int]]


def whisper_language_code(codes: str) -> str:
    """Whisper code for a ``SUBTITLE_LANGUAGES`` code list: ``"zh-Hans,zh-CN"`` -> ``"zh"``."""
    first = codes.split(",")[0].strip()
    return first.split("-")[0].lower()


def language_options() -> list[tuple[str, str]]:
    """``[(label, whisper code), ...]``; the first entry ("" = auto-detect) is the default."""
    from app.domain.languages import SUBTITLE_LANGUAGES

    options = [(AUTO_LANGUAGE_LABEL, "")]
    options += [(name, whisper_language_code(codes)) for name, codes in SUBTITLE_LANGUAGES if codes]
    return options


def should_show(config: dict[str, Any]) -> bool:
    """True for a new install: a config without ``quick_start_done`` counts as done."""
    return bool(config.get("quick_start_enabled", True)) and not bool(
        config.get("quick_start_done", True)
    )


def default_output_folder(config: dict[str, Any]) -> str:
    """The saved download folder, else the user's Downloads folder, else home."""
    current = str(config.get("download_folder") or "").strip()
    if current:
        return current
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


def short_model_name(config: dict[str, Any], slug: str) -> str:
    """"Small" from the catalog label "Small — fast, moderate accuracy, ..."."""
    from core.model_manager import catalog_entry_info

    label = str((catalog_entry_info(config, slug) or {}).get("label") or slug)
    return label.split(" — ")[0].strip() or slug


def format_per_minute(seconds: float) -> str:
    """Decode time for one minute of audio, rounded the way a person would say it."""
    if seconds < 10:
        return "under 10 seconds"
    nearest_five = int(round(seconds / 5.0)) * 5
    if nearest_five < 60:
        return f"about {nearest_five} seconds"
    minutes, rest = divmod(int(round(seconds / 15.0)) * 15, 60)
    return f"about {minutes} min" if rest == 0 else f"about {minutes} min {rest} s"


@dataclass(frozen=True)
class QuickStartChoice:
    language: str  # Whisper code; "" = several languages / not sure
    mode: str  # "fast" or "best"
    output_folder: str

    @property
    def model_slug(self) -> str:
        return recommended_model(self.language, self.mode)


def apply_choice(config: dict[str, Any], choice: QuickStartChoice | None) -> None:
    """Write the outcome into ``config``; the caller saves it.

    ``None`` (Skip) only marks the window as done. Finish sets the model the same way
    the Transcribe tab's picker does, the download folder, and the default model
    folder when none is set (so a second first-run window does not follow).
    """
    config["quick_start_done"] = True
    if choice is None:
        return
    from core.model_manager import catalog_resolve_entry

    entry = catalog_resolve_entry(config, choice.model_slug)
    if entry is None:
        logger.warning("Quick start: %r is not in the model catalog", choice.model_slug)
    else:
        config["whisper_model"] = choice.model_slug
        config["model"] = entry
        config["model_path"] = ""
    config["download_folder"] = choice.output_folder
    if not _hub.is_hub_configured(config):
        config["hub_folder"] = _hub.normalise_hub_path(str(_hub.default_hub_folder()))


def _probe_hardware() -> tuple[_hw.CudaStatus, int]:
    return _hw.cuda_status(), _hw.physical_cpu_cores()


class QuickStartDialog(tk.Toplevel):
    """Modal window; ``on_done`` gets a :class:`QuickStartChoice`, or ``None`` on Skip."""

    def __init__(
        self,
        master: "tk.Misc",
        config: dict[str, Any],
        *,
        on_done: Callable[[QuickStartChoice | None], None],
        probe: Probe | None = None,
        on_try_sample: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._on_try_sample = on_try_sample
        try:
            self._open_window(master, config, on_done, probe)
        except Exception:
            # Never leave an empty window (holding the grab) behind: the caller
            # falls back to the old first-run path.
            try:
                self.grab_release()
                self.destroy()
            except tk.TclError:
                pass
            raise

    def _open_window(
        self,
        master: "tk.Misc",
        config: dict[str, Any],
        on_done: Callable[[QuickStartChoice | None], None],
        probe: Probe | None,
    ) -> None:
        self.title("Quick start")
        self.transient(master)  # type: ignore[arg-type]
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.skip)
        self._config = config
        self._on_done = on_done
        self._closed = False
        self._hardware: tuple[_hw.CudaStatus, int] | None = None
        self._result: dict[str, Any] = {}

        self._languages = language_options()
        self.language_var = tk.StringVar(master=self, value=self._languages[0][0])
        self.mode_var = tk.StringVar(master=self, value="fast")
        self.folder_var = tk.StringVar(master=self, value=default_output_folder(config))
        self.mode_detail_vars = {m: tk.StringVar(master=self) for m, _ in MODES}
        self.hardware_var = tk.StringVar(master=self, value="Checking this computer…")
        self._build()
        self._refresh_details()

        self.update_idletasks()
        try:
            self.grab_set()
        except tk.TclError:
            pass  # headless test runs cannot always grab
        self._center_on(master)

        self._thread = threading.Thread(
            target=self._check, args=(probe or _probe_hardware,), daemon=True,
        )
        self._thread.start()
        self._poll_id: str | None = self.after(100, self._poll)

    # ---------- layout -----------------------------------------------------

    def _build(self) -> None:
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, text="Welcome! Three quick choices", font=("TkDefaultFont", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body, text="You can change each of them later.", foreground="#666",
        ).pack(anchor="w", pady=(0, 12))

        ttk.Label(body, text="1. Main language you will transcribe").pack(anchor="w")
        self.language_combo = ttk.Combobox(
            body, textvariable=self.language_var, state="readonly", width=34,
            values=[label for label, _code in self._languages],
        )
        self.language_combo.pack(anchor="w", pady=(4, 12))
        self.language_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_details())

        ttk.Label(body, text="2. Speed or quality").pack(anchor="w")
        for mode, title in MODES:
            ttk.Radiobutton(
                body, text=title, value=mode, variable=self.mode_var,
            ).pack(anchor="w", pady=(4, 0))
            ttk.Label(
                body, textvariable=self.mode_detail_vars[mode], foreground="#666",
            ).pack(anchor="w", padx=(24, 0))
        ttk.Label(
            body, textvariable=self.hardware_var, foreground="#666",
            wraplength=500, justify="left",
        ).pack(anchor="w", pady=(6, 12))

        ttk.Label(body, text="3. Save downloaded videos and audio in").pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(4, 12))
        ttk.Entry(row, textvariable=self.folder_var, width=52).pack(
            side="left", fill="x", expand=True,
        )
        ttk.Button(row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))

        hub = str(self._config.get("hub_folder") or "").strip() or str(_hub.default_hub_folder())
        ttk.Label(
            body,
            text=(
                "Transcripts are saved next to the file they come from. The model "
                "downloads the first time you transcribe and is kept in "
                f"{hub} (Advanced settings > Model folder can move it)."
            ),
            foreground="#666", wraplength=500, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        actions = ttk.Frame(body)
        actions.pack(fill="x")
        ttk.Button(
            actions, text="Finish", command=self.finish, style="Accent.TButton",
        ).pack(side="right")
        if self._on_try_sample is not None:
            ttk.Button(
                actions, text="Finish and try it now", command=self.finish_and_try_sample,
            ).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="Skip", command=self.skip).pack(side="right", padx=(0, 8))

    def _center_on(self, master: "tk.Misc") -> None:
        try:
            master.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            if master.winfo_viewable():
                x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
                y = master.winfo_rooty() + max(0, (master.winfo_height() - h) // 2)
            else:
                x = max(0, (self.winfo_screenwidth() - w) // 2)
                y = max(0, (self.winfo_screenheight() - h) // 2)
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    # ---------- state ------------------------------------------------------

    def language_code(self) -> str:
        label = self.language_var.get()
        return next((code for name, code in self._languages if name == label), "")

    def choice(self) -> QuickStartChoice:
        return QuickStartChoice(
            language=self.language_code(),
            mode=self.mode_var.get(),
            output_folder=self.folder_var.get().strip(),
        )

    def _refresh_details(self) -> None:
        from core.model_manager import approx_download_size_text

        language = self.language_code()
        for mode, _title in MODES:
            slug = recommended_model(language, mode)
            parts = [short_model_name(self._config, slug)]
            size = approx_download_size_text(self._config, slug)
            if size:
                parts.append(f"{size} download")
            if self._hardware is not None:
                status, cores = self._hardware
                seconds = _hw.estimate_seconds_per_audio_minute(slug, status, physical_cores=cores)
                if seconds is not None:
                    parts.append(f"{format_per_minute(seconds)} per minute of audio")
            self.mode_detail_vars[mode].set(" · ".join(parts))

    def _hardware_text(self, status: _hw.CudaStatus, cores: int) -> str:
        where = f"{cores}-core processor" if cores else "processor"
        if status.usable:
            gpu = status.gpu_name or "your NVIDIA GPU"
            memory = f" ({status.memory_mb / 1024:.0f} GB)" if status.memory_mb else ""
            return (
                f"Times are rough estimates for {gpu}{memory}, from faster-whisper's "
                "published GPU benchmark; a model too large for its memory runs on the "
                f"{where} and shows that slower time."
            )
        if status.gpu_present:
            return (
                f"{status.gpu_name or 'Your NVIDIA GPU'} cannot be used yet, so the times are "
                f"for this computer's {where} (Advanced settings > Re-detect hardware "
                "explains why)."
            )
        return (
            f"Times are rough estimates for this computer's {where}, measured on a "
            "4-core desktop processor; a newer processor is faster, an older laptop slower."
        )

    # ---------- background check ------------------------------------------

    def _check(self, probe: Probe) -> None:
        try:
            self._result["done"] = probe()
        except Exception as e:  # noqa: BLE001
            logger.exception("Quick start hardware check failed")
            self._result["error"] = e

    def _poll(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        if "error" in self._result:
            self.hardware_var.set("Could not check this computer, so no time estimate is shown.")
            return
        if "done" not in self._result:
            self._poll_id = self.after(100, self._poll)
            return
        status, cores = self._result["done"]
        self._hardware = (status, cores)
        self.hardware_var.set(self._hardware_text(status, cores))
        self._refresh_details()

    # ---------- actions ----------------------------------------------------

    def _browse(self) -> None:
        initial = self.folder_var.get().strip()
        folder = filedialog.askdirectory(
            parent=self, title="Folder for downloaded videos and audio",
            initialdir=initial if os.path.isdir(initial) else None, mustexist=False,
        )
        if folder:
            self.folder_var.set(os.path.normpath(folder))

    def finish_and_try_sample(self) -> None:
        """Finish, then transcribe the bundled sample clip with the chosen model."""
        self.finish(try_sample=True)

    def finish(self, try_sample: bool = False) -> None:
        choice = self.choice()
        if not choice.output_folder:
            messagebox.showwarning(
                "Pick a folder", "Choose a folder for downloaded videos and audio.", parent=self,
            )
            return
        try:
            # "~\Videos" or a relative name typed by hand must not land in the
            # app's working folder.
            folder = os.path.abspath(os.path.expanduser(choice.output_folder))
            os.makedirs(folder, exist_ok=True)
            choice = QuickStartChoice(choice.language, choice.mode, folder)
        except (OSError, ValueError) as e:  # ValueError: e.g. a NUL character
            messagebox.showwarning(
                "Folder unavailable",
                f"Cannot create or use this folder:\n{choice.output_folder}\n\n{e}",
                parent=self,
            )
            return
        self._close(choice)
        if try_sample and self._on_try_sample is not None:
            self._on_try_sample()

    def skip(self) -> None:
        self._close(None)

    def _close(self, choice: QuickStartChoice | None) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self._on_done(choice)
        finally:
            try:
                self.destroy()
            except tk.TclError:
                pass
