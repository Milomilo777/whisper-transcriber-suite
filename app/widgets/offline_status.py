"""Work offline, made visible: the status line under the tabs and the Network log.

While Work offline is on (``core.offline``), a one-line bar at the bottom of the
window says what the switch has done in this window's process and whether the
app has any connection to another computer open right now. Its three states:

* clean: a fresh look at the app's open TCP connections found none to another
  computer;
* cannot check: there was no fresh look, or it failed (never shown as clean);
* warning: a connection to another computer is open (shown, never hidden).

**Network log** opens a window with the recent refused actions, automatic
requests that were not sent and connections allowed because they stay on this
computer, the open connections, a **Verify offline now** button and the limits
of what is checked. The text is copyable and holds host and feature names only.

The text builders are pure functions, tested without a window.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from app.theme import tokens
from core import offline

#: How often the open connections are listed while the bar is shown.
POLL_MS = 10_000
#: A look older than this no longer counts as "clean".
FRESH_SECONDS = 30.0

LIMITS = (
    "What this shows, and what it does not:",
    "- The counts and events come from this window's process. Transcription "
    "workers refuse in their own process; yt-dlp and ffmpeg are not started "
    "by the actions that would go online; Demucs only gets offline proxy and "
    "Hugging Face settings. Their refusals are not counted here.",
    "- The open-connection check lists the TCP connections of this app and of "
    "the processes it started that are still running under it, about every "
    "10 seconds. UDP sockets are not listed (Windows does not report where a "
    "UDP socket is connected). A connection that opens and closes between two "
    "checks can be missed. Another computer means any address that is not "
    "loopback, including this computer's own network address.",
    "- Refused here: outgoing TCP connections, host-name lookups and UDP sends "
    "to another computer (also through asyncio). Not covered: a UDP socket "
    "connected to another computer and then used with send(), and native code "
    "that does not use Python's socket module.",
    "- Bytes are not measured. To watch all traffic yourself, see "
    "docs/WORK_OFFLINE.md (Resource Monitor, Get-NetTCPConnection, Wireshark).",
)


def _clock(when: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(when))


def _counts_text(act: offline.Activity) -> str:
    refused = act.counts.get(offline.REFUSED, 0)
    skipped = act.counts.get(offline.SKIPPED, 0)
    return (
        f"{refused} refused, {skipped} automatic "
        f"request{'' if skipped == 1 else 's'} not sent since {_clock(act.since)[:5]}"
    )


def bar_state(check: offline.ConnectionCheck | None, now: float) -> str:
    """``"warning"``, ``"clean"`` or ``"unknown"`` for the last look at the connections."""
    if check is not None and check.ok and check.outside:
        return "warning"
    if check is None or not check.ok or now - check.when > FRESH_SECONDS:
        return "unknown"
    return "clean"


def _connection_text(conn: offline.OpenConnection) -> str:
    direction = "incoming" if conn.incoming else "outgoing"
    return f"{conn.process} (pid {conn.pid}) {conn.protocol} {direction} {conn.remote}"


def bar_text(check: offline.ConnectionCheck | None, act: offline.Activity, now: float) -> str:
    """The one line shown under the tabs."""
    state = bar_state(check, now)
    if state == "warning" and check is not None:
        n = len(check.outside)
        first = _connection_text(check.outside[0])
        return (
            f"Work offline: WARNING, this app has {n} open connection{'' if n == 1 else 's'} "
            f"to another computer ({first}). See the Network log."
        )
    if state == "clean" and check is not None:
        return (
            f"Work offline: this app has no open TCP connection to another computer "
            f"(checked {_clock(check.when)}) · {_counts_text(act)}"
        )
    reason = "not checked yet"
    if check is not None and not check.ok:
        reason = f"could not check: {check.error}"
    elif check is not None:
        reason = f"last check {_clock(check.when)} is too old"
    return f"Work offline: this app's open connections unknown ({reason}) · {_counts_text(act)}"


_KIND_WORDS = {
    offline.REFUSED: "refused",
    offline.SKIPPED: "not sent",
    offline.LOCAL: "allowed (this computer)",
    offline.TEST: "refused (test)",
}


def log_text(
    act: offline.Activity,
    check: offline.ConnectionCheck | None,
    probes: Sequence[offline.ProbeResult] = (),
    probes_when: float | None = None,
) -> str:
    """The Network log as plain, copyable text."""
    lines = [
        f"Work offline: Network log of this window since {_clock(act.since)}",
        f"Refused: {act.counts.get(offline.REFUSED, 0)}    "
        f"Automatic requests not sent: {act.counts.get(offline.SKIPPED, 0)}    "
        f"Connections allowed on this computer: {act.counts.get(offline.LOCAL, 0)}    "
        f"Verify offline now refusals (not in the counts): {act.counts.get(offline.TEST, 0)}",
        "",
    ]
    if check is None:
        lines.append("Open connections to other computers: not checked yet")
    elif not check.ok:
        lines.append(f"Open connections to other computers: could not check ({check.error})")
    else:
        lines.append(
            f"Open TCP connections to other computers (checked {_clock(check.when)}, "
            f"{check.processes} process{'' if check.processes == 1 else 'es'} of this app):"
        )
        if check.outside:
            lines.extend(f"  WARNING  {_connection_text(c)}" for c in check.outside)
        else:
            lines.append("  none")
    if probes:
        when = f" ({_clock(probes_when)})" if probes_when is not None else ""
        lines += ["", f"Verify offline now{when}:"]
        lines.extend(
            f"  {'OK' if p.refused else 'FAILED'}  {p.what}: {p.detail}" for p in probes
        )
    lines += ["", f"Events (oldest first, {len(act.events)} shown; the log keeps the last "
              f"{offline._LOG_SIZE} refused or not sent and the last {offline._LOG_SIZE} "
              "allowed; the counts above are not capped):"]
    if not act.events:
        lines.append("  none yet")
    for ev in act.events:
        target = f" -> {ev.host}" if ev.host else ""
        lines.append(f"  {_clock(ev.when)}  {_KIND_WORDS.get(ev.kind, ev.kind)}  {ev.feature}{target}")
    lines += ["", *LIMITS]
    return "\n".join(lines)


class NetworkLogWindow(tk.Toplevel):
    """The Network log: read-only text, Verify offline now, Refresh, Copy."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        get_check: Callable[[], offline.ConnectionCheck | None],
        post_to_main: Callable[[Callable[[], None]], None],
    ) -> None:
        super().__init__(master)
        self.title("Network log (Work offline)")
        self._get_check = get_check
        self._post = post_to_main
        self._probes: list[offline.ProbeResult] = []
        self._probes_when: float | None = None
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        self.verify_button = ttk.Button(
            buttons, text="Verify offline now", command=self.verify,
        )
        self.verify_button.pack(side="left")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Copy all", command=self.copy_all).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.text = tk.Text(body, wrap="word", width=96, height=26)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.refresh()

    def content(self) -> str:
        return log_text(offline.activity(), self._get_check(), self._probes, self._probes_when)

    def refresh(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.content())
        self.text.configure(state="disabled")

    def copy_all(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.content())

    def verify(self) -> None:
        """Run :func:`core.offline.self_test` off the Tk thread, then show the result."""
        self.verify_button.configure(state="disabled")

        def work() -> None:
            try:
                probes = offline.self_test()
            except RuntimeError as e:
                probes = [offline.ProbeResult("Verify offline now", False, str(e))]
            self._post(lambda: self._show_probes(probes))

        threading.Thread(target=work, name="offline-verify", daemon=True).start()

    def _show_probes(self, probes: list[offline.ProbeResult]) -> None:
        if not self.winfo_exists():
            return
        self._probes = probes
        self._probes_when = time.time()
        self.verify_button.configure(state="normal")
        self.refresh()


class OfflineStatusBar(ttk.Frame):
    """The line at the bottom of the window while Work offline is on."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        post_to_main: Callable[[Callable[[], None]], None],
        poll: Callable[[], offline.ConnectionCheck] = offline.poll_connections,
    ) -> None:
        super().__init__(master, padding=(10, 0, 10, 4))
        self._post = post_to_main
        self._poll = poll
        self._after_id: str | None = None
        self._closed = False
        self.check: offline.ConnectionCheck | None = None
        self._log_window: NetworkLogWindow | None = None
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.text_var = tk.StringVar(master=self, value="")
        self.label = ttk.Label(row, textvariable=self.text_var, anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Network log", command=self.open_log).pack(side="right")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event: tk.Event) -> None:
        # A tick left pending would call a deleted command ('invalid command name').
        if event.widget is self:
            self._closed = True
            self._cancel_tick()

    def _cancel_tick(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    @property
    def visible(self) -> bool:
        return bool(self.winfo_manager())

    def show(self, *, before: tk.Misc) -> None:
        if not self.visible:
            self.pack(side="bottom", fill="x", before=before)
        self.tick()

    def hide(self) -> None:
        self._cancel_tick()
        if self.visible:
            self.pack_forget()

    def tick(self) -> None:
        """Look at the open connections now and every :data:`POLL_MS` while shown."""
        if self._closed:
            return
        self._cancel_tick()
        try:
            self.check = self._poll()
        except Exception as e:  # noqa: BLE001 - shown as "unknown", never as clean
            self.check = offline.ConnectionCheck(time.time(), False, error=f"{type(e).__name__}: {e}")
        finally:
            self._after_id = self.after(POLL_MS, self.tick)
        self.render()

    def render(self) -> None:
        now = time.time()
        self.text_var.set(bar_text(self.check, offline.activity(), now))
        warning = bar_state(self.check, now) == "warning"
        self.label.configure(foreground=tokens.themed(tokens.DANGER_TEXT) if warning else "")

    def open_log(self) -> None:
        win = self._log_window
        if win is not None and win.winfo_exists():
            win.lift()
            win.refresh()
            return
        self._log_window = NetworkLogWindow(
            self.winfo_toplevel(), get_check=lambda: self.check, post_to_main=self._post,
        )
