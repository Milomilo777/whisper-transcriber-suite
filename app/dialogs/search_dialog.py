"""SearchDialog — full-text search across every saved transcript.

Wires up core.search (FTS5, with an optional semantic layer the search
module already knows how to fall back from — this dialog only ever
passes ``embedder=None``, keyword search, so it needs no extra
dependency) to a small results list. Selecting a result opens
app.dialogs.transcript_viewer.TranscriptViewer seeked to that segment.

Reindexing walks history.db and re-reads any transcript JSON that's
new or changed since the last index (core.search.index_file's
mtime+size check) — cheap and safe to re-run every time this dialog
opens.
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from app.dpi import place_over, px, scaled_size
from app.theme import script_fonts
from app.theme import tokens
from app.theme.bidi_display import ltr_base

logger = logging.getLogger(__name__)


def _fmt_hms(seconds: float) -> str:
    try:
        s = max(0, int(seconds))
    except (OverflowError, ValueError):
        # NaN / Infinity from a hand-edited transcript or an older index.
        s = 0
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class SearchDialog(tk.Toplevel):
    """Modal-ish (non-blocking) search window over every saved transcript."""

    # Transient, but usable beside the main window (app/mac_native.py).
    _non_modal = True

    def __init__(self, master: "tk.Tk | tk.Toplevel") -> None:
        super().__init__(master)
        self.title("Search transcripts")
        width, height = scaled_size(self, 820, 520)
        self.geometry(f"{width}x{height}")
        self.minsize(width, height)
        self.transient(master)
        place_over(self, master, width, height)

        # tkinter types self.master as the generic Misc, not Tk | Toplevel —
        # keep the correctly-typed constructor arg around for open_viewer().
        self._master_window: "tk.Tk | tk.Toplevel" = master
        self._hits: list[Any] = []  # core.search.SearchHit, kept parallel to the tree rows
        self._closing = False

        # Monotonic counter so an out-of-order background search
        # completion (query B's worker finishes before query A's) can't
        # overwrite a newer result with a stale one.
        self._search_seq = 0

        self._build_widgets()
        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._reindex()

    # -- widgets ---------------------------------------------------------

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        topbar = ttk.Frame(outer)
        topbar.pack(fill="x", pady=(0, 6))
        ttk.Label(topbar, text="Search:").pack(side="left")
        self.query_var = tk.StringVar()
        entry = ttk.Entry(topbar, textvariable=self.query_var, width=40)
        entry.pack(side="left", padx=(4, 4))
        entry.bind("<Return>", lambda _e: self._run_search())
        ttk.Button(topbar, text="Search", command=self._run_search).pack(side="left")
        self._reindex_btn = ttk.Button(
            topbar, text="Reindex now", command=self._reindex
        )
        self._reindex_btn.pack(side="left", padx=(12, 0))
        self.status_var = tk.StringVar(value="Indexing…")
        ttk.Label(topbar, textvariable=self.status_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
            side="right"
        )

        tree_frame = ttk.Frame(outer)
        tree_frame.pack(fill="both", expand=True, pady=(0, 6))
        cols = ("file", "time", "text")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        self.tree.heading("file", text="File")
        self.tree.heading("time", text="Time")
        self.tree.heading("text", text="Match")
        self.tree.column("file", width=px(220), anchor="w")
        self.tree.column("time", width=px(70), anchor="w")
        self.tree.column("text", width=px(460))
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-Button-1>", lambda _e: self._open_selected())

        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        ttk.Button(btns, text="Open at result", command=self._open_selected).pack(
            side="left"
        )
        ttk.Label(
            btns,
            text="Double-click a row, or select it and click Open, to jump "
                 "straight to that moment in the transcript viewer.",
            foreground=tokens.themed(tokens.TEXT_MUTED),
        ).pack(side="left", padx=(10, 0))

    # -- thread-safe UI updates -------------------------------------------

    def _post_to_main(self, fn) -> None:
        poster = getattr(self.master, "post_to_main", None)
        if callable(poster):
            poster(fn)
            return
        try:
            self.after(0, fn)
        except Exception:  # noqa: BLE001
            pass

    # -- indexing ----------------------------------------------------------

    def _reindex(self) -> None:
        # Single flight: a second pass while one runs would only repeat the work.
        if getattr(self, "_reindexing", False):
            return
        self._reindexing = True
        self._reindex_btn.state(["disabled"])
        self.status_var.set("Indexing…")

        def _worker() -> None:
            from core import search as _search
            try:
                count = _search.reindex_all_history()
                message = f"Indexed — {count} segment(s) up to date"
            except Exception as e:  # noqa: BLE001
                logger.warning("Transcript reindex failed: %s", e)
                message = f"Indexing failed: {e}"
            self._post_to_main(lambda: self._finish_reindex(message))

        from core._threads import safe_thread
        safe_thread(_worker, name="search-reindex")

    def _finish_reindex(self, message: str) -> None:
        if self._closing:
            return
        self._reindexing = False
        self._reindex_btn.state(["!disabled"])
        self.status_var.set(message)
        # Re-run whatever query is already typed so a reindex (the
        # "Reindex now" button, a fresh transcription that just finished,
        # or — since this dialog's own reindex is asynchronous — a query
        # the user typed and submitted WHILE the very first,
        # dialog-opening reindex was still in flight) is reflected
        # without the user re-typing it.
        if (self.query_var.get() or "").strip():
            self._run_search()

    # -- search --------------------------------------------------------------

    def _run_search(self) -> None:
        query = (self.query_var.get() or "").strip()
        self.tree.delete(*self.tree.get_children())
        self._hits = []
        if not query:
            return
        self.status_var.set("Searching…")
        self._search_seq += 1
        seq = self._search_seq

        def _worker() -> None:
            from core import search as _search
            try:
                hits = _search.search(query, limit=100)
                error = None
            except Exception as e:  # noqa: BLE001
                hits = []
                error = str(e)
            self._post_to_main(lambda: self._finish_search(hits, error, seq))

        from core._threads import safe_thread
        safe_thread(_worker, name="search-query")

    def _finish_search(self, hits: list[Any], error: str | None, seq: int) -> None:
        if self._closing:
            return
        if seq != self._search_seq:
            # A newer search has since been started (the user kept
            # typing/hit Search again); this worker's result is stale —
            # discard it rather than let a slow, older query overwrite
            # the row list a faster, newer query already populated.
            return
        if error:
            self.status_var.set(f"Search failed: {error}")
            return
        self._hits = hits
        for i, hit in enumerate(hits):
            name = os.path.basename(hit.json_path)
            self.tree.insert(
                "", "end", iid=str(i),
                values=(ltr_base(name), _fmt_hms(hit.start_seconds), hit.text),
                tags=script_fonts.tree_row_tags(self.tree, name, hit.text),
            )
        self.status_var.set(f"{len(hits)} result(s)")

    # -- opening a result ---------------------------------------------------

    def _open_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            return
        try:
            idx = int(item)
        except ValueError:
            return
        if idx < 0 or idx >= len(self._hits):
            return
        hit = self._hits[idx]
        if not os.path.isfile(hit.json_path):
            from tkinter import messagebox
            messagebox.showerror(
                "Transcript missing",
                f"That transcript's JSON file no longer exists:\n{hit.json_path}",
                parent=self,
            )
            return
        from app.dialogs.transcript_viewer import open_viewer
        open_viewer(
            self._master_window, hit.json_path,
            initial_seek_seconds=hit.start_seconds,
        )

    def _on_close(self) -> None:
        self._closing = True
        self.destroy()


def open_search_dialog(master: "tk.Tk | tk.Toplevel") -> None:
    SearchDialog(master)
