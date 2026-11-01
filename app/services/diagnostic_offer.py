"""The quiet offer to send technical details of a failure nobody has classified yet.

A failed transcription already sends one anonymous row of closed codes (``core.failure_clue``). When the failure has
no known cause, the worker also attaches a filtered record (``core.diagnostic``). This service keeps that record in a
local file, and, only while the person's statistics switch is on, shows a quiet bar offering to send it. Nothing is
sent before they press Send, and they can read the exact text first.

Rules (each one is a test in ``tests/app/test_diagnostic_offer.py``):

* only failures without a known cause are offered;
* at most one offer per session and one per 24 hours, and never while a job is running;
* the same failure (same fingerprint) is never offered twice in a session; several different ones share one bar;
* never while Work offline is on, when statistics are off, or after "Don't ask again";
* the local file is written even when nothing is offered, so a person can attach it to a GitHub issue.
"""
from __future__ import annotations

import logging
import queue
import time
from typing import Any, Callable

from app.i18n import _
from core import diagnostic, offline
from core import problem_report as pr
from core._threads import safe_thread

logger = logging.getLogger(__name__)

OFFER_COOLDOWN_SECONDS = 24 * 3600
MAX_LINES_PER_OFFER = 3
_RETRY_MS = 5000


class DiagnosticOffer:
    def __init__(self, app: Any, *, clock: Callable[[], float] = time.time) -> None:
        self.app = app
        self._clock = clock
        self._seen: set[str] = set()
        self._pending: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._offered_this_session = False
        self._scheduled = False
        self._bar: Any = None

    # -- intake ---------------------------------------------------------------------------------------------
    def note(self, task: Any) -> None:
        """Called once for each task that ended in an error."""
        record = getattr(task, "failure_diag", None)
        if not record:
            return
        clue = getattr(task, "failure_clue", None) or {}
        if clue.get("observed_code", "none") != "none":
            return  # a known cause: the anonymous row already says everything useful
        line = diagnostic.compose(
            record, site=str(clue.get("failure_site", "")), device=str(clue.get("device", "")),
            duration=diagnostic.duration_bucket(getattr(task, "audio_duration", 0.0)),
        )
        diagnostic.remember(line)
        fingerprint = diagnostic.fingerprint(record)
        self._counts[fingerprint] = self._counts.get(fingerprint, 0) + 1
        if fingerprint in self._seen or fingerprint in self._pending or not self._allowed():
            return
        if len(self._pending) < MAX_LINES_PER_OFFER:
            self._pending[fingerprint] = line
        self._schedule()

    def _allowed(self) -> bool:
        cfg = self.app.app_config
        if self._offered_this_session or not cfg.get("telemetry_opt_in", True):
            return False
        if not cfg.get("diagnostic_offer", True) or offline.is_offline(cfg):
            return False
        if self._clock() - float(cfg.get("diagnostic_offer_last", 0.0) or 0.0) < OFFER_COOLDOWN_SECONDS:
            return False
        return bool(str(cfg.get("stats_url") or "").strip())

    # -- showing --------------------------------------------------------------------------------------------
    def _schedule(self) -> None:
        if not self._scheduled:
            self._scheduled = True
            self.app.after(_RETRY_MS, self._tick)

    def _tick(self) -> None:
        self._scheduled = False
        if not self._pending or getattr(self.app, "_closing", False):
            return
        if not self._allowed():
            self._pending.clear()  # switched off (or offline) while waiting: nothing stays queued
            return
        if self.app._jobs_active():
            self._schedule()  # busy: look again later
            return
        self._show()

    def _show(self) -> None:
        from app.widgets.update_bar import DiagnosticBar
        bar = self._bar
        if bar is None:
            bar = DiagnosticBar(self.app, commands={
                "details": self.show_details, "send": self.send, "not_now": self.not_now, "never": self.never,
            })
            self._bar = bar
        self._offered_this_session = True
        self._seen.update(self._pending)
        cfg = self.app.app_config
        cfg["diagnostic_offer_last"] = self._clock()
        self._save()
        bar.show(
            _("Something did not work as expected. May we send a few technical details about this problem so it "
              "can be fixed in a later version? You can see exactly what would be sent."),
            before=self.app.nb,
        )

    def lines(self) -> list[str]:
        return list(self._pending.values())

    # -- the person's choices -------------------------------------------------------------------------------
    def show_details(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        top = tk.Toplevel(self.app)
        top.title(_("Technical details"))
        top.transient(self.app)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, wraplength=520, justify="left",
                  text=_("This is everything that would be sent, together with the app version and your "
                         "operating system. It has no file names, folders, links or personal text.")).pack(anchor="w")
        box = tk.Text(frame, width=70, height=min(10, 3 + 3 * len(self._pending)), wrap="word")
        box.insert("1.0", "\n\n".join(self.lines()))
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, pady=(8, 8))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Button(row, text=_("Close"), command=top.destroy).pack(side="right")
        ttk.Button(row, text=_("Send"), command=lambda: (self.send(), top.destroy())).pack(side="right", padx=(0, 8))

    def send(self) -> None:
        lines = self.lines()
        self._pending.clear()
        self._close_bar()
        if not lines:
            return
        config = dict(self.app.app_config)

        results: "queue.Queue[bool]" = queue.Queue()

        def _work() -> None:
            sent = 0
            for line in lines:  # one failed line must not hide that the others went out
                try:
                    pr.send(config, "[auto] " + line)
                    sent += 1
                except pr.ProblemReportError as e:
                    logger.info("diagnostic details not sent: %s", e)
                except Exception:  # noqa: BLE001 - never raised into Tk
                    logger.debug("diagnostic details not sent", exc_info=True)
            results.put(sent == len(lines))

        def _poll() -> None:
            # Tk is only touched from its own thread: the worker thread just fills the queue.
            try:
                ok = results.get_nowait()
            except queue.Empty:
                if not getattr(self.app, "_closing", False):
                    self.app.after(300, _poll)
                return
            self._after_send(ok)

        safe_thread(_work, name="diagnostic-send")
        self.app.after(300, _poll)

    def _after_send(self, ok: bool) -> None:
        from app.widgets.notice import notify
        try:
            notify(self.app, _("Thank you. The details were sent.") if ok
                   else _("The details could not be sent. Nothing was lost."))
        except Exception:  # noqa: BLE001
            logger.debug("notice failed", exc_info=True)

    def not_now(self) -> None:
        self._pending.clear()
        self._close_bar()

    def never(self) -> None:
        self.app.app_config["diagnostic_offer"] = False
        self._save()
        self.not_now()

    def _close_bar(self) -> None:
        if self._bar is not None:
            self._bar.hide()

    def _save(self) -> None:
        try:
            from core.config import save_config
            save_config(self.app.app_config)
        except Exception:  # noqa: BLE001
            logger.debug("Could not save the diagnostic offer state", exc_info=True)
