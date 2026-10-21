"""Tab construction extracted from App.

Each ``build_*_tab`` function attaches widgets onto the App and returns
nothing. The App class stays slim while the widget code lives next to its
sibling components.
"""
from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Callable

from app.domain.cookies import cookie_browser_choices, cookie_browser_label
from app.domain.languages import SUBTITLE_LANGUAGES, caption_language_name, subtitle_language_label
from app.dpi import px
from app.i18n import N_, _, pgettext, translate
from app.theme import tokens
from app.widgets.tooltip import bind_tooltip, help_icon, section_labelframe

if TYPE_CHECKING:
    from app.app import App
    from app.domain.tasks import TranscriptionTask, VideoDownloadTask

logger = logging.getLogger(__name__)


# --- shared UX helpers -----------------------------------------------------


class _AutoScrollbar(ttk.Scrollbar):
    """A scrollbar that hides itself when the whole view already fits.

    Gives the queue lists a vertical scrollbar that appears only when the
    list grows past the visible area. Must be managed by grid — it
    grid_remove()s itself when not needed and grid()s back when it is.
    """

    def set(self, first: float | str, last: float | str) -> None:
        try:
            if float(first) <= 0.0 and float(last) >= 1.0:
                self.grid_remove()
            else:
                self.grid()
        except (ValueError, tk.TclError):
            pass
        super().set(first, last)


def translated_choice_var(
    master: tk.Misc, stored: tk.StringVar, labels: dict[str, str]
) -> tk.StringVar:
    """A variable for a combobox that shows translated labels while ``stored`` keeps the value.

    ``labels`` maps a stored (English) value to the text shown for it; values without an
    entry are shown as they are (language names, numbers). Code that reads or sets ``stored``
    keeps working with the English values, and choosing a label in the combobox writes its
    value to ``stored``. The two variables follow each other through write traces; the
    returned variable stays alive through the trace callback that ``stored`` holds.
    """
    values = {label: value for value, label in labels.items()}
    shown = tk.StringVar(master=master, value=labels.get(stored.get(), stored.get()))
    busy: list[bool] = []

    def _copy(source: tk.StringVar, target: tk.StringVar, table: dict[str, str]) -> None:
        if busy:
            return
        busy.append(True)
        try:
            text = source.get()
            new = table.get(text, text)
            if target.get() != new:
                target.set(new)
        finally:
            busy.clear()

    stored.trace_add("write", lambda *_args: _copy(stored, shown, labels))
    shown.trace_add("write", lambda *_args: _copy(shown, stored, values))
    return shown


# Widget classes that scroll themselves: the wheel over one of them must keep
# scrolling it, not the page around it.
_SELF_SCROLLING = frozenset({
    "Treeview", "Text", "Listbox", "Canvas", "TCombobox", "TSpinbox", "TScale",
})


def _redraw_embedded_window(canvas: tk.Canvas, window: int) -> None:
    """Make the canvas paint its embedded window again (macOS only needs this).

    After its tab was hidden and shown again, an aqua canvas draws blank until something
    moves its embedded window: a repeated ``itemconfigure``, a background re-set, ``update()``
    or re-gridding all leave it blank, but moving the item by one pixel and back repaints it
    (measured in the macOS 13 VM). Both moves happen before Tk draws, so nothing flickers.
    """
    try:
        x, y = canvas.coords(window)
        canvas.coords(window, x, y + 1)
        canvas.update_idletasks()
        canvas.coords(window, x, y)
    except tk.TclError:
        pass  # the page is being destroyed


def fit_or_scroll(page: tk.Misc) -> ttk.Frame:
    """Give ``page`` a vertical scroller that only appears when needed.

    Returns the frame to build the tab into. That frame always spans the
    page's full width and at least its full height, so lists that expand
    still fill a big window; only when the content is taller than the
    window does a scrollbar appear. On a 1366x768 laptop the Download tab's
    list and Pause/Cancel buttons, the end of the Live tab and the Web / LAN
    options were simply cut off with no way to reach them.
    """
    canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0)
    vsb = _AutoScrollbar(page, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    page.rowconfigure(0, weight=1)  # type: ignore[attr-defined]
    page.columnconfigure(0, weight=1)  # type: ignore[attr-defined]
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    last: dict[str, tuple[int, int, int]] = {}
    # Pending after()/after_idle() calls. Destroying the page deletes the Tcl commands they
    # point at, so a call left pending fails later with 'invalid command name'.
    timers: set[str] = set()
    closed: list[bool] = []

    def _after(ms: int | None, func: Callable[[], None]) -> None:
        if closed:
            return
        ident = ""

        def _fit_or_scroll_timer() -> None:
            timers.discard(ident)
            func()

        ident = canvas.after_idle(_fit_or_scroll_timer) if ms is None else canvas.after(ms, _fit_or_scroll_timer)
        timers.add(ident)

    def _cancel_timers(event: tk.Event) -> None:
        if event.widget is not canvas:
            return
        closed.append(True)
        for ident in list(timers):
            try:
                canvas.after_cancel(ident)
            except tk.TclError:
                pass
        timers.clear()

    def _layout() -> None:
        try:
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            req = inner.winfo_reqheight()
        except tk.TclError:
            return
        if cw <= 1:
            return
        key = (cw, ch, req)
        if last.get("k") == key:
            return
        last["k"] = key
        height = max(ch, req)
        canvas.itemconfigure(window, width=cw, height=height)
        canvas.configure(scrollregion=(0, 0, cw, height))

    def _poll() -> None:
        # Tk has no "requested size changed" event: rows that appear later
        # (the SMTV toggle, the caption shortcut, the YouTube helper) change
        # the content height without a <Configure>, so re-check cheaply.
        try:
            if not canvas.winfo_exists():
                return
        except tk.TclError:
            return
        _layout()
        _after(400, _poll)

    canvas.bind("<Configure>", lambda _e: _layout())
    canvas.bind("<Destroy>", _cancel_timers, add="+")
    _after(50, _poll)
    if sys.platform == "darwin":
        # The notebook maps this page again when its tab is selected (the canvas itself gets
        # no <Map>): repaint the embedded content once per switch, not on a timer, so an
        # idle window stays idle.
        page.bind(
            "<Map>",
            lambda _e: _after(None, lambda: _redraw_embedded_window(canvas, window)),
            add="+",
        )

    def _scrollable() -> bool:
        first, last_frac = canvas.yview()
        return not (first <= 0.0 and last_frac >= 1.0)

    canvas_path = str(canvas)

    def _on_wheel(event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Misc):
            return
        # Only for the pointer over THIS tab's content, only when it overflows,
        # and never over a widget that scrolls (or cycles values) itself.
        path = str(widget)
        inside = path == canvas_path or path.startswith(canvas_path + ".")
        if not inside or not _scrollable():
            return
        if widget is not canvas and widget.winfo_class() in _SELF_SCROLLING:
            return
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            divisor = 1 if sys.platform == "darwin" else 120
            step = int(-1 * (event.delta / divisor)) or (-1 if event.delta > 0 else 1)
        canvas.yview_scroll(step, "units")

    # Bound on the main window (every widget's event reaches it through its
    # bindtags), NOT bind_all: the Settings dialog unbind_all()s the wheel on
    # <Leave>, which would silently remove a global binding.
    root = page.winfo_toplevel()
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind(seq, _on_wheel, add="+")
    return inner


# Rows of the Last result file list shown before the list scrolls: a run with many
# output formats must not push the drop zone and the log off the window.
LAST_RESULT_MAX_ROWS = 4


def capped_rows(
    parent: ttk.Frame,
    count: int,
    fill_rows: "Callable[[ttk.Frame], None]",
    max_rows: int = LAST_RESULT_MAX_ROWS,
) -> None:
    """Fill ``parent`` with ``count`` equal rows, scrolling after ``max_rows`` of them.

    ``fill_rows(frame)`` packs the rows into ``frame``. Up to ``max_rows`` rows they go
    straight into ``parent`` (nothing changes); beyond that they sit in a scrolled area
    exactly ``max_rows`` rows high, so the block's height stays the same for 5 files or 500.
    The wheel over the list scrolls the list; Tab to a button inside scrolls it into view.
    """
    if count <= max_rows:
        fill_rows(parent)
        return
    canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
    vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="x", expand=True)
    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    fill_rows(inner)
    inner.update_idletasks()
    row_h = max(1, inner.winfo_reqheight() // count)
    canvas.configure(
        height=row_h * max_rows, yscrollincrement=row_h,
        scrollregion=(0, 0, 1, inner.winfo_reqheight()),
    )
    canvas.bind(
        "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width), add="+"
    )

    def _wheel(event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            divisor = 1 if sys.platform == "darwin" else 120
            step = int(-1 * (event.delta / divisor)) or (-1 if event.delta > 0 else 1)
        canvas.yview_scroll(step, "units")
        return "break"  # the page around the card must not scroll as well

    def _see(widget: tk.Misc) -> None:
        try:
            top = widget.winfo_rooty() - inner.winfo_rooty()
            bottom = top + widget.winfo_height()
            total = max(1, inner.winfo_height())
            shown = canvas.winfo_height()
            first = canvas.canvasy(0)
            if top < first:
                canvas.yview_moveto(top / total)
            elif bottom > first + shown:
                canvas.yview_moveto((bottom - shown) / total)
        except tk.TclError:
            pass

    def _wire(widget: tk.Misc) -> None:
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(seq, _wheel, add="+")
        widget.bind("<FocusIn>", lambda _e, w=widget: _see(w), add="+")
        for child in widget.winfo_children():
            _wire(child)

    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        canvas.bind(seq, _wheel, add="+")
    _wire(inner)


# Glanceable status icons for both Treeviews. Plain Unicode so they
# render without an embedded image set, and so they survive the
# packaging mode that ships no icon assets.
STATUS_ICON = {
    "waiting":      "⋯ ",
    "running":      "▶ ",
    "paused":       "⏸ ",
    "transcribing": "✍ ",
    "burning":      "♨ ",
    "finished":     "✓ ",
    "error":        "✗ ",
    "cancelled":    "⊘ ",
}


def _fmt_bytes(n: int) -> str:
    """Compact filesize formatter for the Last Result card."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _status_text(status: str) -> str:
    """The shown word for a task status; the status value itself stays English."""
    texts = {
        "waiting": pgettext("task status", "waiting"),
        "running": pgettext("task status", "running"),
        "paused": pgettext("task status", "paused"),
        "transcribing": pgettext("task status", "transcribing"),
        "burning": pgettext("task status", "burning"),
        "finished": pgettext("task status", "finished"),
        "error": pgettext("task status", "error"),
        "cancelled": pgettext("task status", "cancelled"),
    }
    return texts.get(status, status)


def status_label(status: str) -> str:
    """Friendly status text for the Treeview's status column."""
    return STATUS_ICON.get(status, "") + _status_text(status)


# Whisper codes the subtitle language list spells differently, and the Whisper languages it
# lacks: without them the Language cell showed a bare "he" or "yue".
_WHISPER_CODE_ALIASES = {"he": "iw", "jw": "jv", "nn": "no"}
_WHISPER_ONLY_NAMES = {
    "as": N_("Assamese"), "ba": N_("Bashkir"), "bo": N_("Tibetan"), "br": N_("Breton"),
    "fo": N_("Faroese"), "ln": N_("Lingala"), "oc": N_("Occitan"), "sa": N_("Sanskrit"),
    "tk": N_("Turkmen"), "tt": N_("Tatar"), "yue": N_("Cantonese"),
}


def queue_language_cell(code: str, probability: object = None) -> str:
    """The Queue's Language cell: the detected language by name, "Chinese" rather than
    "zh (88%)" (screenshot review, 2026-10-21); "(not sure)" when the detection was
    below even odds. 0 means no detection ran (some engines report it for a chosen
    language). An unknown code stays as it is. No Tk."""
    if not code:
        return ""
    if code in _WHISPER_ONLY_NAMES:
        name = translate(_WHISPER_ONLY_NAMES[code])
    else:
        # Whisper reports bare codes ("zh", "pt") where the list has "zh-Hans,zh-CN".
        bare = _WHISPER_CODE_ALIASES.get(code, code).lower()
        english = next(
            (name.split(" (")[0] for name, codes in SUBTITLE_LANGUAGES
             if codes and codes.split(",")[0].strip().split("-")[0].lower() == bare),
            "",
        )
        name = subtitle_language_label(english or caption_language_name(code))
    if isinstance(probability, (int, float)) and not isinstance(probability, bool) and 0 < probability < 0.5:
        return _("{language} (not sure)", language=name)
    return name


def queue_failure_line(selected: list[Any]) -> str:
    """The red line under the Queue's buttons: why the one selected failed job failed.

    Empty unless exactly one row is selected and it failed. A Treeview cell has no room
    for a reason, so the row says only "error" (click-through test, 2026-10-21). No Tk.
    """
    if len(selected) != 1 or getattr(selected[0], "status", "") != "error":
        return ""
    reason = str(getattr(selected[0], "error_reason", "") or "")
    return reason or _("This job failed and no reason was recorded; try Re-run.")


def queue_result_task(selected: list[Any]) -> Any | None:
    """The task whose result the Queue's "View transcript" / "Open output folder" buttons
    open: exactly one selected row that finished, else None. Before these buttons a
    finished row offered its result only by right-click or double-click (screenshot
    review, 2026-10-21). No Tk."""
    if len(selected) == 1 and getattr(selected[0], "status", "") == "finished":
        return selected[0]
    return None


_PROGRESS_SEGMENTS = 10


def progress_cell(percent: float | int) -> str:
    """Render progress as a text bar + number for a Treeview cell.

    A Treeview cell can't host a real ttk.Progressbar, so we draw a
    fixed-width block bar (█ filled / ░ empty) and append the exact
    percentage — a glanceable graphical trend *and* the number in one
    column.
    """
    try:
        pct = int(round(float(percent)))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(round(inf)) on a non-finite percent.
        pct = 0
    pct = max(0, min(100, pct))
    filled = (pct * _PROGRESS_SEGMENTS + 50) // 100
    bar = "█" * filled + "░" * (_PROGRESS_SEGMENTS - filled)
    return f"{bar} {pct:>3d}%"


def marquee_cell(frame: int, percent: float | int = 0) -> str:
    """An indeterminate "working" bar that STILL shows the percentage.

    A 3-cell shaded window slides across the track so the user sees that
    something is happening (e.g. while the model loads, before the first
    segment), while the real number is still appended — so the percentage
    is never hidden, just animated until determinate progress takes over.
    """
    track = ["░"] * _PROGRESS_SEGMENTS
    head = frame % _PROGRESS_SEGMENTS
    for i in range(3):
        track[(head + i) % _PROGRESS_SEGMENTS] = "▓"
    try:
        pct = max(0, min(100, int(round(float(percent)))))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(round(inf)) on a non-finite percent.
        pct = 0
    return "".join(track) + f" {pct:>3d}%"


def progress_column_width(measure: Callable[[str], int]) -> int:
    """Width of a Treeview progress column that shows every progress cell whole.

    ``measure`` = the row font's ``measure``. A fixed px(150) cut "100%" to "10(" on
    Windows 10, where the block glyphs come from a wider fallback font (screenshot
    review, 2026-10-21). No Tk.
    """
    # Every shape a cell takes: the shade glyphs of an empty or animated bar need not be as
    # wide as the full block in a fallback font.
    widest = max(measure(progress_cell(0)), measure(progress_cell(100)), measure(marquee_cell(0, 100)))
    return max(px(150), widest + px(20))


def fit_progress_column(tree: ttk.Treeview, column: str = "progress") -> None:
    """Size ``column`` to its widest cell in the tree's own row font, now and after
    every <<ThemeChanged>> (a theme switch or a script font changes that font)."""

    def _fit() -> None:
        try:
            style_name = str(tree.cget("style")) or "Treeview"
            font_name = str(ttk.Style(tree).lookup(style_name, "font")) or "TkDefaultFont"
            try:
                font = tkfont.nametofont(font_name, root=tree)
            except tk.TclError:
                font = tkfont.Font(root=tree, font=font_name)
            width = progress_column_width(font.measure)
            tree.column(column, width=width, minwidth=width, stretch=False)
        except tk.TclError:
            pass  # the tree was destroyed before an after_idle refit ran

    def _on_theme_changed(_event: tk.Event) -> None:
        tree.after_idle(_fit)

    _fit()
    tree.bind("<<ThemeChanged>>", _on_theme_changed, add="+")


# Transcription action keys surfaced by the per-row action bar AND the
# right-click context menu. Keep this list in sync with the buttons built
# in build_queue_tab so a status with no valid action disables them all.
QUEUE_ACTION_KEYS = ("pause", "resume", "cancel", "rerun", "remove")


def button_states_for_status(
    status: str, has_checkpoint: bool = False
) -> dict[str, bool]:
    """Which transcription actions are valid for a task in ``status``.

    The single source of truth shared by the Queue action bar and the
    right-click ``menu_row`` so the two can never drift. Returns a dict
    mapping each key in :data:`QUEUE_ACTION_KEYS` to whether that action
    should be ENABLED for a task in this state. Pure (no Tk), so it is
    unit-testable without a Tk root.

    Mirrors ``App.menu_row``:
      * waiting  -> Cancel, Remove
      * running  -> Pause, Cancel
      * paused   -> Resume, Cancel
      * terminal (finished / cancelled / error) -> Re-run, Remove
        (cancelled also offers Resume when a resumable checkpoint exists)

    ``has_checkpoint`` only matters for the ``cancelled`` state — it maps
    to the "Resume" entry ``menu_row`` adds above "Re-run".
    """
    states = {k: False for k in QUEUE_ACTION_KEYS}
    if status == "waiting":
        # Remove too: a job that has not started yet just leaves the list (it was greyed out
        # with no reason: code review, 2026-10-21). Dispatch runs on the Tk thread as well.
        states["cancel"] = True
        states["remove"] = True
    elif status == "running":
        states["pause"] = True
        states["cancel"] = True
    elif status == "paused":
        states["resume"] = True
        states["cancel"] = True
    elif status in ("finished", "cancelled", "error"):
        states["rerun"] = True
        states["remove"] = True
        if status == "cancelled" and has_checkpoint:
            states["resume"] = True
    return states


# Download action keys for the per-row Download action bar.
DOWNLOAD_ACTION_KEYS = ("pause", "resume", "cancel", "rerun", "remove", "open")


def download_button_states_for_status(
    status: str, *, is_smtv: bool = False, has_saved_file: bool = False
) -> dict[str, bool]:
    """Which download actions are valid for a task in ``status``.

    Single source of truth for the Download action bar (Phase 2). Pure (no
    Tk) so it is unit-testable without a Tk root. Mirrors download_menu_row:
      * waiting / running / transcribing / burning -> Cancel  (and Pause for a running
        non-SMTV download — yt-dlp can stop-and-continue; SMTV cannot)
      * running paused                   -> Resume, Cancel
      * terminal (finished/cancelled/error) -> Re-run, Remove (and Open when
        a saved file exists on disk)

    ``is_smtv`` disables Pause (SMTV CDN has no HTTP Range resume point).
    ``has_saved_file`` gates Open to a finished download with a real file.
    """
    states = {k: False for k in DOWNLOAD_ACTION_KEYS}
    if status in ("waiting", "running", "transcribing", "burning"):
        states["cancel"] = True
        if status == "running" and not is_smtv:
            states["pause"] = True
    elif status == "paused":
        states["resume"] = True
        states["cancel"] = True
    elif status in ("finished", "cancelled", "error"):
        states["rerun"] = True
        states["remove"] = True
        if status == "finished" and has_saved_file:
            states["open"] = True
    return states


EMPTY_STATE_LINK_HINT = N_("To use a link, paste it into the File or video link box below and click Transcribe.")
EMPTY_STATE_FORMATS = N_(
    "Works with MP3, WAV, M4A, FLAC, OGG, MP4, MKV, MOV, WebM and most other "
    "audio and video formats."
)


def once_per(seconds: float, action: Callable[[], object],
             clock: Callable[[], float] | None = None) -> Callable[..., None]:
    """An event handler that runs ``action`` at most once per ``seconds``: a held Enter
    (keyboard auto-repeat) or a double tap must not queue the same file twice (review,
    2026-10-21). No Tk."""
    import time

    now = clock or time.monotonic
    last = [float("-inf")]

    def handler(*_args: object) -> None:
        t = now()
        if t - last[0] < seconds:
            return
        last[0] = t
        action()

    return handler


def combo_width(values: list[str], floor: int = 44, cap: int = 72) -> int:
    """Width in characters for a read-only Combobox: its longest entry, kept within
    floor..cap. A Combobox's list is as wide as the box, so a fixed 44 cut entries such
    as "Google Cloud Speech-to-Text ... ⚠ unavailable" (click-through test, 2026-10-21);
    the cap keeps the row inside the 960-px minimum window. No Tk."""
    longest = max((len(str(v)) for v in values), default=0)
    return max(floor, min(cap, longest + 2))


def time_range_hint(start: str, end: str) -> tuple[str, bool]:
    """The note beside the Transcribe tab's time range and whether it is an error.

    "(whole recording)" while both sides are empty or zero; a red "not a valid time" line
    when a side holds text that is not a time ("5 min", "5;00"): App.add reads such text
    as unset, so the whole recording would be transcribed while the user meant a part
    (code review, 2026-10-21); else nothing. No Tk.
    """
    from app.services.download_service import _parse_timecode

    sides = [text for text in (start, end) if text.strip()]
    if any(_parse_timecode(text) is None for text in sides):
        return _("Not a time: use H:MM:SS"), True
    if not any(_parse_timecode(text) for text in sides):
        return _("(whole recording)"), False
    return "", False


READY_NAME_MAX = 48


def elide_middle(name: str, limit: int = READY_NAME_MAX) -> str:
    """``name`` cut in the middle to ``limit`` characters ("Interview with the … 1 of 3).mp4"),
    keeping its end (the extension). A long file name on the ready line pushed "Advanced
    settings..." and the processor note out of the window (click-through test, 2026-10-21).
    No Tk."""
    if len(name) <= limit:
        return name
    tail = max(8, limit // 3)
    return name[: limit - tail - 1] + "…" + name[-tail:]


def clock_length(seconds: float) -> str:
    """A recording length as a clock: ``0:07``, ``3:05``, ``1:46:12``. No Tk."""
    s = max(0, int(round(seconds)))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def file_ready_state(text: str, duration: float | None = None) -> tuple[str, str]:
    """What the File or video link box holds, for the line next to the Transcribe button.

    ``("empty" | "link" | "file" | "missing" | "not_media", line)``: an audio or video file
    that exists or a link makes the button the blue primary action; nothing, a path that is
    not a file, or a file that is not audio or video (a README picked by mistake) keeps it
    plain, so the user can see whether the app has something to transcribe. ``duration``
    (seconds, from ffprobe) adds the recording's length to a file's line, so the user knows
    which recording it is and roughly how long the job takes. No Tk.
    """
    import os

    from app.app import _clean_pasted_path
    from core.watcher import is_transcribable

    path = _clean_pasted_path(text or "")
    if not path:
        return "empty", ""
    if path.startswith(("http://", "https://")):
        return "link", _("Link: it downloads first, then transcribes.")
    if not os.path.isfile(path):
        return "missing", _("File not found: check the path, or click Browse.")
    if not is_transcribable(path):
        return "not_media", _("{name} is not an audio or video file.", name=elide_middle(os.path.basename(path)))
    try:
        size = _fmt_bytes(os.path.getsize(path))
    except OSError:
        size = "?"
    name = elide_middle(os.path.basename(path))
    if duration:
        return "file", _("Ready: {name} ({length}, {size})", name=name, length=clock_length(duration),
                         size=size)
    return "file", _("Ready: {name} ({size})", name=name, size=size)


def empty_state_headline(dnd_ready: bool, has_sample: bool) -> str:
    """The empty Transcribe tab's headline; it names only what this install can do.

    Drag-and-drop needs the optional tkinterdnd2 package and the sample clip needs
    its bundled file, so each phrase appears only when it works. Pure (no Tk).
    One whole sentence per case, so a translation can order it freely.
    """
    if dnd_ready:
        if has_sample:
            return _("Drop a file here, paste a link, or try the sample")
        return _("Drop a file here or paste a link")
    if has_sample:
        return _("Pick a file, paste a link, or try the sample")
    return _("Pick a file or paste a link")


def sync_transcribe_empty_state(app: "App") -> None:
    """Show the empty-state block while the queue is empty, hide it once a file is queued."""
    frame = getattr(app, "transcribe_empty_state", None)
    if frame is None:
        return
    headline = empty_state_headline(
        bool(getattr(app, "_dnd_ready", False)), bool(app.transcribe_has_sample)
    )
    # App.refresh() calls this every 500 ms. Writing the unchanged text still fires the
    # label's variable trace and redraws it, which kept an idle window busy on macOS (about
    # 38% of a core, measured). Write on change only.
    if app.transcribe_empty_headline_var.get() != headline:
        app.transcribe_empty_headline_var.set(headline)
    sample_row = getattr(app, "transcribe_sample_row", None)
    if app.queue:
        if frame.winfo_manager():
            frame.pack_forget()
        if sample_row is not None and sample_row.winfo_manager():
            sample_row.pack_forget()
    else:
        if not frame.winfo_manager():
            frame.pack(fill="x", before=app.transcribe_browse_row)
        if sample_row is not None and not sample_row.winfo_manager():
            sample_row.pack(pady=(10, 0), after=app.transcribe_browse_row)


def build_transcribe_tab(app: "App", parent: ttk.Frame) -> None:
    """Beginner-friendly Transcribe tab.

    Layout philosophy comes from researching MacWhisper / Aiko / Vibe /
    OpenWhispr / Buzz / WhisperUI in May 2026. The pattern
    every well-loved offline app converges on is:

      1. A *hero drop-zone* takes the visual centre of the tab — it's
         both the empty state and the primary affordance.
      2. *Three* visible controls beneath: language picker, two
         feature toggles (identify speakers + per-word timestamps).
      3. *One* prominent primary CTA — sv_ttk's ``Accent.TButton``
         style + ``ipady`` so it's ~2× the visual weight of Browse.
      4. *Everything else hidden* behind an "Advanced settings…"
         button: VAD knobs, device / compute backend, hotwords,
         output formats, watched folder, telemetry, etc. None of
         these strings (``VAD``, ``compute``, ``device``, ``hotwords``)
         appear on the main canvas — the research's #1 anti-pattern.

    Note for maintainers: every ``*_var`` that lived in the old layout
    is still created here so the config save path + the hermetic test
    suite don't need to know the UI was rebuilt. Vars without a
    matching widget are simply not packed.
    """
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS

    # ── all vars created up-front (some have no UI surface; they're
    #     still referenced by config save + test suite + Advanced
    #     dialog, so we initialise them either way) ───────────────────
    app.fv = tk.StringVar()
    app.vad_enabled_var = tk.BooleanVar(
        value=bool(app.app_config.get("vad_enabled", True))
    )
    app.word_timestamps_var = tk.BooleanVar(
        value=bool(app.app_config.get("word_timestamps", False))
    )
    app.translate_var = tk.BooleanVar(
        value=bool(app.app_config.get("translate_to_english", False))
    )
    try:
        from core import diarization as _diar  # type: ignore[import-not-found]
        _diar_available = _diar.is_available()
        _diar_reason = _diar.availability_reason() if not _diar_available else ""
    except Exception:  # noqa: BLE001
        _diar_available = False
        _diar_reason = _("sherpa-onnx not present")
    app.diarization_var = tk.BooleanVar(
        value=bool(_diar_available) and bool(app.app_config.get("diarization_enabled", False))
    )
    _speakers_val = app.app_config.get("diarization_num_speakers", -1)
    if type(_speakers_val) is not int or (_speakers_val not in range(2, 11) and _speakers_val != -1):
        logger.warning("Invalid speaker count %r; defaulting to Auto", _speakers_val)
        _speakers_val = -1
    app.diarization_speakers_var = tk.StringVar(
        value="Auto" if _speakers_val == -1 else str(_speakers_val)
    )
    # Always start at "Auto" — the language is deliberately NOT restored
    # from config (user request: every launch defaults to auto-detect).
    app.transcribe_lang_var = tk.StringVar(value="Auto")
    # Mixed-language audio (experimental): off on every launch, like the language.
    app.mixed_lang_var = tk.BooleanVar(value=False)
    app.transcribe_lang2_var = tk.StringVar(value="English")
    app.device_var = tk.StringVar(value=str(app.app_config.get("device", "auto")))
    app.compute_type_var = tk.StringVar(
        value=str(app.app_config.get("compute_type", "int8"))
    )
    app.hotwords_var = tk.StringVar(value=str(app.app_config.get("hotwords", "")))

    # ── Row 0: hero drop zone ─────────────────────────────────────────
    drop_zone = ttk.LabelFrame(parent, text="", padding=24)
    drop_zone.grid(
        row=0, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(15, 6),
    )
    # The empty-state block: tells a new user what to do. It is shown while the
    # queue is empty and hidden once a file is queued (sync_transcribe_empty_state,
    # called from App.refresh); Browse below stays for adding more files.
    from core.sample_clip import bundled_clip_path

    app.transcribe_has_sample = bool(bundled_clip_path())
    empty_state = ttk.Frame(drop_zone)
    app.transcribe_empty_state = empty_state
    app.transcribe_empty_headline_var = tk.StringVar(
        value=empty_state_headline(False, app.transcribe_has_sample)
    )
    ttk.Label(
        empty_state,
        textvariable=app.transcribe_empty_headline_var,
        font=("TkDefaultFont", 14, "bold"),
        anchor="center",
        justify="center",
    ).pack(fill="x")
    ttk.Label(
        empty_state,
        text=translate(EMPTY_STATE_LINK_HINT),
        foreground=tokens.themed(tokens.TEXT_MUTED),
        anchor="center",
        justify="center",
    ).pack(fill="x", pady=(2, 0))
    ttk.Label(
        empty_state,
        text=translate(EMPTY_STATE_FORMATS),
        foreground=tokens.themed(tokens.TEXT_MUTED),
        anchor="center",
        justify="center",
    ).pack(fill="x", pady=(2, 12))
    empty_state.pack(fill="x")
    browse_row = ttk.Frame(drop_zone)
    app.transcribe_browse_row = browse_row
    browse_row.pack()
    ttk.Button(browse_row, text=_("Browse files..."), command=app.browse).pack(side="left")
    help_icon(
        browse_row,
        _("Pick an audio or video file to transcribe locally (mp3, wav, mp4, "
          "mkv, and most other common formats). The file is processed on "
          "this machine and never leaves it unless you pick a cloud Engine "
          "below."),
    ).pack(side="left", padx=(6, 0))
    # The sample comes second: picking your own file is the main action (it sat above
    # Browse: screenshot review, 2026-10-21). Shown and hidden with the empty state.
    sample_row: ttk.Frame | None = None
    if app.transcribe_has_sample:
        sample_row = ttk.Frame(drop_zone)
        ttk.Button(sample_row, text=_("Try it now (sample clip)"), command=app.try_sample_clip).pack()
        sample_row.pack(pady=(10, 0))
    app.transcribe_sample_row = sample_row

    # ── Row 1: file path display (always visible — shows what's selected) ─
    file_row = ttk.Frame(parent)
    file_row.grid(
        row=1, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(2, 8),
    )
    # "Selected file" hid that a link works here too (screenshot review, 2026-10-21).
    ttk.Label(file_row, text=_("File or video link:")).pack(side="left")
    file_entry = ttk.Entry(file_row, textvariable=app.fv)
    file_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
    # Enter after pasting a path or link starts it, as the Transcribe button does (it did
    # nothing: code review, 2026-10-21).
    start_file = once_per(1.5, app.add)
    for key in ("<Return>", "<KP_Enter>"):
        file_entry.bind(key, start_file)

    # ── Row 2: engine + model pickers — let the user choose the
    #     transcription engine AND (for Faster-Whisper) which model size
    #     right here, without digging through the crowded Advanced dialog.
    #     Two stacked lines in one gridded frame (same split-line trick as
    #     quick_opts below) so neither line's help icons overflow the app's
    #     default 960px width. Short status lines show whether the chosen
    #     engine is ready / model already downloaded, and an engine that
    #     can't run until the user sets it up (missing key, missing package)
    #     is marked "⚠ unavailable" in the dropdown itself — ttk.Combobox
    #     can't grey one entry, so the marker + the status line + the hover
    #     help below carry the reason instead. ────────────────────────────
    from core.backends import availability as _eng
    from core.model_manager import DEFAULT_MODEL_SLUG, catalog_models

    engine_frame = ttk.Frame(parent)
    engine_frame.grid(
        row=2, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 8),
    )
    engine_row = ttk.Frame(engine_frame)
    engine_row.pack(fill="x")
    model_row = ttk.Frame(engine_frame)
    model_row.pack(fill="x", pady=(6, 0))

    ttk.Label(engine_row, text=_("Engine:")).pack(side="left")
    # Cheap readiness only (no heavy backend imports on the UI thread); a
    # deep probe of the current pick refines this shortly after startup.
    _engine_options = _eng.engine_options(app.app_config, deep=False)
    _current_engine_value = _eng.normalise_engine(
        app.app_config.get("transcribe_backend")
    )
    _current_engine_label = next(
        (
            opt.display_label
            for opt in _engine_options
            if opt.value == _current_engine_value
        ),
        _engine_options[0].display_label,
    )
    app.transcribe_engine_var = tk.StringVar(value=_current_engine_label)
    engine_combo = ttk.Combobox(
        engine_row,
        textvariable=app.transcribe_engine_var,
        values=[opt.display_label for opt in _engine_options],
        state="readonly",
        width=combo_width([opt.display_label for opt in _engine_options]),
    )
    engine_combo.pack(side="left", padx=(6, 8))
    app.transcribe_engine_combo = engine_combo
    if not any(opt.ready for opt in _engine_options):
        # No engine has any usable path — the documented fallback for a
        # combobox whose entries can't be disabled individually.
        engine_combo.configure(state="disabled")
    help_icon(
        engine_row,
        lambda: _(
            "Which transcription engine to use. Offline engines "
            "(Faster-Whisper, whisper.cpp, NVIDIA Parakeet) run entirely on "
            "this machine; the two cloud engines upload your audio to "
            "Google. Set up keys/models for each in Advanced settings.\n\n{summary}",
            summary=_eng.engine_status_summary(
                app.app_config,
                deep=False,
                statuses=getattr(app, "_engine_deep_statuses", None),
            ),
        ),
    ).pack(side="left", padx=(0, 8))
    engine_combo.bind("<<ComboboxSelected>>", lambda _e: app._on_engine_selected())
    app.engine_status_var = tk.StringVar(value="")
    app.engine_status_label = ttk.Label(
        engine_row, textvariable=app.engine_status_var, foreground=tokens.themed(tokens.TEXT_MUTED),
    )
    app.engine_status_label.pack(side="left")
    # Cheap readiness probe for the initial selection (no heavy import).
    app._refresh_engine_status()

    # Model picker — which Whisper model size the Faster-Whisper engine
    # above loads (tiny/base/.../large-v3/turbo/...). Same catalog + slug
    # as Advanced settings' "Whisper model" picker; either one can change
    # it and both stay in sync (see App._refresh_model_selector).
    ttk.Label(model_row, text=_("Model:")).pack(side="left")
    _model_labeled = catalog_models(app.app_config)
    app._transcribe_model_label_to_slug = {slug_lbl[1]: slug_lbl[0] for slug_lbl in _model_labeled}
    _model_slug_to_label = {slug: lbl for slug, lbl in _model_labeled}
    _current_model_slug = str(
        app.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG
    )
    app.transcribe_model_var = tk.StringVar(
        value=_model_slug_to_label.get(
            _current_model_slug, _model_labeled[0][1] if _model_labeled else ""
        )
    )
    model_combo = ttk.Combobox(
        model_row,
        textvariable=app.transcribe_model_var,
        values=[lbl for _slug, lbl in _model_labeled],
        state="readonly",
        width=combo_width([lbl for _slug, lbl in _model_labeled]),
    )
    model_combo.pack(side="left", padx=(6, 8))
    app.transcribe_model_combo = model_combo
    # Owner idea (2026-09-23): recommend a model for this computer's GPU /
    # CPU / memory instead of leaving the size choice to guesswork.
    app.transcribe_model_advisor_btn = ttk.Button(
        model_row, text=_("Best for this PC…"), command=app.open_model_advisor,
    )
    app.transcribe_model_advisor_btn.pack(side="left", padx=(0, 8))
    bind_tooltip(
        app.transcribe_model_advisor_btn,
        _("Checks this computer's NVIDIA GPU (and its memory) or CPU and RAM "
          "and suggests the fastest and the most accurate model that fit."),
    )
    # A disabled combobox still fires Enter/Leave, so this hover text is the
    # reason the picker is greyed out whenever the engine doesn't use it.
    bind_tooltip(model_combo, app._model_picker_disabled_reason)
    help_icon(
        model_row,
        _("Which Whisper model size the Faster-Whisper engine loads — bigger "
          "models are more accurate but slower and use more RAM/VRAM. Not "
          "used by the cloud engines or NVIDIA Parakeet, which have their "
          "own model. Same picker as 'Whisper model' in Advanced settings."),
    ).pack(side="left", padx=(0, 8))
    model_combo.bind("<<ComboboxSelected>>", lambda _e: app._on_model_selected())
    app.model_status_var = tk.StringVar(value="")
    app.model_status_label = ttk.Label(
        model_row, textvariable=app.model_status_var, foreground=tokens.themed(tokens.TEXT_MUTED),
    )
    app.model_status_label.pack(side="left")
    # Cheap on-disk existence check only (no heavy import) — safe to run
    # synchronously, unlike _refresh_engine_status's background probe.
    app._refresh_model_status()
    # Grey the picker out entirely while a non-Faster-Whisper engine is
    # picked (those engines use their own model).
    app._sync_model_picker_for_engine()

    # ── Row 3: quick options, split across two lines so a full row of
    #     help icons doesn't overflow the app's default 960px width
    #     (pack(side="left") never wraps — it silently clips instead).
    #     Line 1: language + the two feature toggles. Line 2: the
    #     optional time-slice, which reads better on its own line
    #     anyway (it's conceptually separate from the toggles above).
    quick_opts = ttk.Frame(parent)
    quick_opts.grid(
        row=3, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 8),
    )
    opts_line1 = ttk.Frame(quick_opts)
    opts_line1.pack(fill="x")
    opts_line2 = ttk.Frame(quick_opts)
    opts_line2.pack(fill="x", pady=(6, 0))

    ttk.Label(opts_line1, text=_("Language:")).pack(side="left")
    # transcribe_lang_var keeps the English "Auto" or language name (App compares it and
    # looks the code up by name); only the shown labels are translated.
    auto_label = pgettext("language choice", "Auto")
    lang_labels = {"Auto": auto_label}
    # Not the list's own "Automatic" row: it meant the same as "Auto", and the two stood one
    # above the other (click-through test, 2026-10-21).
    lang_labels.update((name, subtitle_language_label(name)) for name, code in _LANGS if code)
    lang_combo = ttk.Combobox(
        opts_line1,
        textvariable=translated_choice_var(opts_line1, app.transcribe_lang_var, lang_labels),
        values=list(lang_labels.values()),
        state="readonly",
        width=14,
    )
    lang_combo.pack(side="left", padx=(6, 4))
    help_icon(
        opts_line1,
        _("Spoken language in the file. Auto detects it from the first few "
          "seconds of audio; picking it explicitly is faster and can be more "
          "accurate for short or noisy clips."),
    ).pack(side="left", padx=(0, 20))
    lang_combo.bind("<<ComboboxSelected>>", lambda _e: app._save_transcribe_prefs())

    # A model trained for the picked language (core/language_models.py, ADR 0015): one line
    # with a "Use it" / "Switch back" button, packed right under line 1 only when there is
    # something to offer (App._refresh_language_model_hint).
    app.language_model_anchor = opts_line1
    app.language_model_row = ttk.Frame(quick_opts)
    app.language_model_hint_var = tk.StringVar(value="")
    ttk.Label(
        app.language_model_row, textvariable=app.language_model_hint_var,
        foreground=tokens.themed(tokens.TEXT_MUTED), wraplength=640, justify="left",
    ).pack(side="left", padx=(0, 8))
    app.language_model_button = ttk.Button(
        app.language_model_row, text=_("Use it"), command=app._on_language_model_button,
    )
    app.language_model_button.pack(side="left")
    app._refresh_language_model_hint()  # a language model may already be active from an earlier session

    # Feature toggles — friendly phrasing instead of "diarization" /
    # "Word timestamps". The research's vocabulary mapping: Aiko ships
    # "Produce timestamps" and "Skip silent parts"; speaker-detection
    # is universally framed as "Identify / detect speakers".
    # The reason can carry a long file path; it goes in the hover text so the
    # row doesn't run off the window (it did at the default size).
    diar_label = (
        _("Identify speakers")
        if _diar_available
        else _("Identify speakers (unavailable)")
    )
    def _on_diar_check_changed() -> None:
        app._save_transcribe_prefs()
        app._sync_diarization_speakers_option()

    app.diarization_check = ttk.Checkbutton(
        opts_line1,
        text=diar_label,
        variable=app.diarization_var,
        command=_on_diar_check_changed,
    )
    if not _diar_available:
        app.diarization_check.state(["disabled"])
        bind_tooltip(app.diarization_check, _("Unavailable: {reason}", reason=_diar_reason))
    app.diarization_check.pack(side="left", padx=(0, 4))

    app.diarization_help_icon = help_icon(
        opts_line1,
        _("Splits the transcript by who is speaking (SPEAKER_00, SPEAKER_01, "
          "...). Adds processing time and needs the optional sherpa-onnx "
          "component to be installed."),
    )
    app.diarization_help_icon.pack(side="left", padx=(0, 20))

    app.diarization_speakers_label = ttk.Label(opts_line2, text=_("Speakers:"))
    app.diarization_speakers_label.pack(side="left")
    # diarization_speakers_var keeps "Auto" or a number (App saves it as -1 or the count).
    speaker_values = [auto_label] + [str(i) for i in range(2, 11)]
    app.diarization_speakers_combo = ttk.Combobox(
        opts_line2,
        textvariable=translated_choice_var(
            opts_line2, app.diarization_speakers_var, {"Auto": auto_label}),
        values=speaker_values,
        state="readonly",
        width=5,
    )
    app.diarization_speakers_combo.pack(side="left", padx=(6, 2))
    app.diarization_speakers_combo.bind(
        "<<ComboboxSelected>>", lambda _e: app._save_transcribe_prefs()
    )
    bind_tooltip(
        app.diarization_speakers_combo,
        _("Force the detector to find exactly this many people, or leave on Auto.")
    )

    app._sync_diarization_speakers_option()

    ttk.Checkbutton(
        opts_line1,
        text=_("Per-word timestamps"),
        variable=app.word_timestamps_var,
        command=app._save_transcribe_prefs,
    ).pack(side="left")
    help_icon(
        opts_line1,
        _("Stores a start/end time for every individual word instead of only "
          "per sentence. Useful for karaoke-style captions or precise "
          "editing; makes the output file larger."),
    ).pack(side="left", padx=(4, 0))

    # Optional time-slice — transcribe only a portion of a long file
    # (e.g. 5 minutes out of a 10-hour recording). 0:00:00 on a side means
    # "unset"; leaving both at 0:00:00 transcribes the whole file.
    app.transcribe_time_range_label = ttk.Label(opts_line2, text=_("Time range:"))
    app.transcribe_time_range_label.pack(side="left")
    app.transcribe_start_time_var = tk.StringVar(value="0:00:00")
    ttk.Entry(opts_line2, textvariable=app.transcribe_start_time_var, width=9).pack(
        side="left", padx=(6, 2)
    )
    ttk.Label(opts_line2, text=pgettext("time range", "to")).pack(side="left")
    app.transcribe_end_time_var = tk.StringVar(value="0:00:00")
    ttk.Entry(opts_line2, textvariable=app.transcribe_end_time_var, width=9).pack(
        side="left", padx=(2, 0)
    )
    # "0:00:00 to 0:00:00" read as an empty range (screenshot review, 2026-10-21): say
    # what it means, and say so in red when a side is not a time at all.
    range_hint_var = tk.StringVar(master=opts_line2, value="")
    range_hint = ttk.Label(opts_line2, textvariable=range_hint_var, foreground=tokens.themed(tokens.TEXT_MUTED))
    range_hint.pack(side="left", padx=(6, 0))

    def _sync_range_hint(*_args: object) -> None:
        line, wrong = time_range_hint(app.transcribe_start_time_var.get(), app.transcribe_end_time_var.get())
        if range_hint_var.get() != line:
            range_hint_var.set(line)
        range_hint.configure(
            foreground=tokens.themed(tokens.DANGER_TEXT) if wrong else tokens.themed(tokens.TEXT_MUTED))

    app.transcribe_start_time_var.trace_add("write", _sync_range_hint)
    app.transcribe_end_time_var.trace_add("write", _sync_range_hint)
    _sync_range_hint()

    # Mixed-language audio (experimental): a recording that switches between two
    # languages. The Language picker above is the first, this one the second.
    opts_line3 = ttk.Frame(quick_opts)
    opts_line3.pack(fill="x", pady=(6, 0))
    mixed_check = ttk.Checkbutton(
        opts_line3, text=_("Mixed-language audio (experimental)"),
        variable=app.mixed_lang_var,
    )
    mixed_check.pack(side="left")
    app.transcribe_lang2_frame = ttk.Frame(opts_line3)
    ttk.Label(app.transcribe_lang2_frame, text=_("Second language:")).pack(side="left")
    # a real language only: no "Automatic" entry for the second one
    lang2_labels = {name: subtitle_language_label(name) for name, code in _LANGS if code}
    ttk.Combobox(
        app.transcribe_lang2_frame,
        textvariable=translated_choice_var(app.transcribe_lang2_frame, app.transcribe_lang2_var, lang2_labels),
        values=list(lang2_labels.values()),
        state="readonly",
        width=14,
    ).pack(side="left", padx=(6, 0))

    def _on_mixed_changed() -> None:
        if app.mixed_lang_var.get():
            app.transcribe_lang2_frame.pack(side="left", padx=(12, 0), after=mixed_check)
        else:
            app.transcribe_lang2_frame.pack_forget()

    mixed_check.configure(command=_on_mixed_changed)
    help_icon(
        opts_line3,
        _("For a recording that switches between two languages, such as a class or an interview. "
          "Pick the first language in Language above (not Auto) and the second one here: each "
          "stretch is then written in whichever of the two it sounds like, instead of translated "
          "into one of them. Works with the faster-whisper engine, not with English translation."),
    ).pack(side="left", padx=(6, 0))
    help_icon(
        opts_line2,
        _("Transcribe only this portion of the file (format H:MM:SS). Leave "
          "both at 0:00:00 to transcribe the whole file."),
    ).pack(side="left", padx=(4, 0))

    # Output in English: Whisper's own translate task (no AI model needed).
    # Greyed out, with the reason on hover, where it cannot work (other
    # engines, turbo, English-only models); see App._sync_translate_option.
    app.translate_check = ttk.Checkbutton(
        opts_line2,
        text=_("Output: English translation"),
        variable=app.translate_var,
        command=app._save_transcribe_prefs,
    )
    app.translate_check.pack(side="left", padx=(24, 0))
    bind_tooltip(
        app.translate_check,
        lambda: app._translate_unsupported_reason()
        or _(
            "Writes English text straight from the speech in one pass, using "
            "Whisper's own translate task (no extra AI model). Output files "
            "get an .en-translated name. Works with multilingual models only."
        ),
    )
    app._sync_translate_option()

    # ── Row 4: the big accent Transcribe CTA + tiny Advanced link ────
    cta_row = ttk.Frame(parent)
    cta_row.grid(
        row=4, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(4, 4),
    )
    transcribe_btn = ttk.Button(
        cta_row,
        text="▶    " + pgettext("button", "Transcribe"),
        command=app.add,
        style="Accent.TButton",
    )
    # ipady doubles the button height; ipadx widens it. Together they
    # give the primary CTA a clear ~2× visual weight over Browse,
    # matching the hero-CTA pattern across MacWhisper / OpenWhispr /
    # WhisperUI.
    transcribe_btn.pack(side="left", ipadx=24, ipady=8)

    # Ready line + button colour (click-through test, 2026-10-21): the button was blue before
    # any file was chosen, so nothing showed that a file was accepted. It is plain until the
    # File or video link box holds an existing file or a link, then blue, with the file's name and
    # size beside it (or why it cannot start). It stays clickable: with an empty box a click
    # opens Browse.
    app.transcribe_ready_var = tk.StringVar(master=parent, value="")
    ready_label = ttk.Label(cta_row, textvariable=app.transcribe_ready_var)
    ready_label.pack(side="left", padx=(12, 0))

    probing: set[str] = set()

    def _probe_length(path: str) -> None:
        """Find the file's length off the UI thread (ffprobe may take seconds), then redraw."""
        if path in probing:
            return
        probing.add(path)

        def _done() -> None:
            probing.discard(path)
            _sync_ready()

        def _work() -> None:
            from core.watcher import media_duration

            try:
                media_duration(path)
            finally:
                app.post_to_main(_done)

        threading.Thread(target=_work, name="ready-line-length", daemon=True).start()

    def _sync_ready(*_args: object) -> None:
        kind, line = file_ready_state(app.fv.get())
        if kind == "file":
            from app.app import _clean_pasted_path
            from core.watcher import UNKNOWN_DURATION, cached_media_duration

            path = _clean_pasted_path(app.fv.get())
            known = cached_media_duration(path)
            if known is UNKNOWN_DURATION:
                _probe_length(path)
            elif isinstance(known, float):
                line = file_ready_state(app.fv.get(), duration=known)[1]
        if app.transcribe_ready_var.get() != line:
            app.transcribe_ready_var.set(line)
        transcribe_btn.configure(style="Accent.TButton" if kind in ("file", "link") else "TButton")
        if kind in ("missing", "not_media"):
            colour = tokens.themed(tokens.DANGER_TEXT)
        elif kind == "file":
            colour = tokens.themed(tokens.SUCCESS_TEXT)
        else:
            colour = tokens.themed(tokens.TEXT_MUTED)
        ready_label.configure(foreground=colour)

    app.fv.trace_add("write", _sync_ready)
    _sync_ready()

    ttk.Button(
        cta_row, text=_("Advanced settings…"),
        command=app.open_advanced_dialog,
    ).pack(side="right")

    # R3: GPU/CPU device badge — primary placement, next to the CTA so users
    # see it where they start a job. Driven by app.device_badge_var (set in
    # TranscriptionService.update_model_state). Registers with the App so
    # apply_device_badge can recolour it + attach the hover tooltip.
    device_badge = ttk.Label(
        cta_row, textvariable=app.device_badge_var, anchor="center",
    )
    device_badge.pack(side="right", padx=(0, 16))
    app.register_device_badge_label(
        device_badge, tier_label=_("Open the Hardware wizard for accelerator details.")
    )

    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=1)
    parent.columnconfigure(2, weight=1)

    # ── Last Result card (hidden until first transcription completes) ─
    ttk.Separator(parent, orient="horizontal").grid(
        row=5, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(8, 6),
    )
    app.last_result_frame = section_labelframe(
        parent, _("Last result"),
        _("The output files from the most recently finished transcription, "
          "with quick Open/Reveal actions. Stays empty until a job "
          "completes; see the Transcription Queue tab for jobs in progress."),
        padding=10,
    )
    app.last_result_frame.grid(
        row=6, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 12),
    )
    # The card sizes to its content instead of greedily filling the whole
    # lower half of the tab (it previously expanded via rowconfigure
    # weight=1, which dominated the window).
    app.last_result_empty_var = tk.StringVar(
        value=_("No transcription finished yet. Drop a file above and click Transcribe.")
    )
    app.last_result_empty_label = ttk.Label(
        app.last_result_frame,
        textvariable=app.last_result_empty_var,
        foreground=tokens.themed(tokens.TEXT_MUTED),
    )
    app.last_result_empty_label.pack(anchor="w")
    app.last_result_body = ttk.Frame(app.last_result_frame)
    app.last_result_title_var = tk.StringVar(value="")
    app.last_result_files_frame = ttk.Frame(app.last_result_body)


def build_queue_tab(app: "App", parent: ttk.Frame) -> None:
    top_row = ttk.Frame(parent)
    top_row.pack(fill="x", padx=10, pady=6)
    help_icon(
        top_row,
        _("Every transcription job you start is tracked here. Use the "
          "buttons below the list (or right-click a row) to pause, resume, "
          "cancel, re-run, or remove it; double-click a finished row to "
          "open its output folder. Speed: 4.8x means 4.8 seconds of audio "
          "were transcribed per second of work; below 1x is slower than the "
          "recording plays. The time left is a rough estimate."),
    ).pack(side="left")
    # "Clear completed" also took failed and cancelled jobs off the list, and did not say
    # whether files go too (screenshot review, 2026-10-21).
    clear_btn = ttk.Button(top_row, text=_("Remove ended jobs"), command=app.clear_completed)
    clear_btn.pack(side="right")
    bind_tooltip(clear_btn, _("Takes every finished, failed or cancelled job off this list. "
                              "No file is deleted."))

    cols = ("file", "status", "progress", "speed", "language", "time")
    tree_frame = ttk.Frame(parent)
    tree_frame.pack(fill="both", expand=True, padx=10)
    tree_frame.rowconfigure(0, weight=1)
    tree_frame.columnconfigure(0, weight=1)
    app.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
    headings = {
        "file": pgettext("column", "File"),
        "status": pgettext("column", "Status"),
        "progress": pgettext("column", "Progress"),
        "speed": pgettext("column", "Speed and time left"),
        "language": pgettext("column", "Language"),
        "time": pgettext("column", "Elapsed"),
    }
    for c in cols:
        app.tree.heading(c, text=headings[c])
    app.tree.column("language", width=px(140))
    app.tree.column("progress", anchor="w")
    fit_progress_column(app.tree)
    app.tree.column("speed", width=px(190), anchor="w")
    app.tree.column("time", width=px(80), anchor="center")
    app.tree.column("status", width=px(120))
    _vsb = _AutoScrollbar(tree_frame, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=_vsb.set)
    app.tree.grid(row=0, column=0, sticky="nsew")
    _vsb.grid(row=0, column=1, sticky="ns")

    # Empty-state hint shown on top of the Treeview when there are no
    # rows yet. App.refresh hides it as soon as a task is enqueued.
    app.queue_empty_var = tk.StringVar(
        value=_("Queue is empty.  Go to the Transcribe tab and pick a file to add one.")
    )
    app.queue_empty_label = ttk.Label(
        parent, textvariable=app.queue_empty_var, foreground=tokens.themed(tokens.TEXT_MUTED), anchor="center"
    )
    app.queue_empty_label.pack(fill="x", pady=(2, 0))

    app.pb = ttk.Progressbar(parent, length=px(400))
    app.pb.pack(fill="x", padx=10, pady=10)

    status_line = ttk.Frame(parent)
    status_line.pack()
    ttk.Label(status_line, textvariable=app.status_var).pack(side="left")
    # R3: mirror the GPU/CPU device badge next to the queue status line.
    queue_device_badge = ttk.Label(
        status_line, textvariable=app.device_badge_var,
    )
    queue_device_badge.pack(side="left", padx=(12, 0))
    app.register_device_badge_label(queue_device_badge)
    app.tree.bind("<Button-3>", app.menu_row)
    if sys.platform == "darwin":
        # macOS Tk generates Button-2 for a right-click (Button-3 is
        # the rarely-used third button there).
        app.tree.bind("<Button-2>", app.menu_row)
    # Double-click on a finished row -> open the file's containing
    # folder. Discoverable shortcut for the right-click menu entry.
    app.tree.bind("<Double-Button-1>", app.queue_row_double_click)
    app.row_map = {}

    # R2 — always-visible per-task action bar. The right-click context
    # menu is not discoverable for a non-technical operator, so mirror its
    # actions as plain buttons that operate on the selected row(s). Enabled
    # state is recomputed from the selected task's status (the same logic
    # menu_row uses, via button_states_for_status) on every selection change
    # AND inside App.refresh (which rebuilds the tree each tick).
    action_bar = ttk.Frame(parent)
    action_bar.pack(fill="x", padx=10, pady=(0, 6))
    app.queue_action_buttons = {
        "pause": ttk.Button(
            action_bar, text=pgettext("button", "Pause"),
            command=lambda: app._action_bar_apply(app.pause, active_only=True),
        ),
        "resume": ttk.Button(
            action_bar, text=pgettext("button", "Resume"),
            command=app._action_bar_resume,
        ),
        "cancel": ttk.Button(
            action_bar, text=_("Cancel"),
            command=lambda: app._action_bar_apply(app.cancel, active_only=True),
        ),
        "rerun": ttk.Button(
            action_bar, text=_("Re-run"),
            command=lambda: app._action_bar_apply(app._rerun_task, active_only=False),
        ),
        "remove": ttk.Button(
            action_bar, text=_("Remove"),
            command=lambda: app._action_bar_apply(app.remove_task, active_only=False, also_waiting=True),
        ),
    }
    for key in ("pause", "resume", "cancel", "rerun", "remove"):
        app.queue_action_buttons[key].pack(side="left", padx=(0, 6))
        app.queue_action_buttons[key].state(["disabled"])
    # The finished job's result (queue_result_task), on the right of the same bar.
    app.queue_result_buttons = {
        "view": ttk.Button(action_bar, text=_("View transcript"), command=app._action_bar_view_transcript),
        "folder": ttk.Button(action_bar, text=_("Open output folder"), command=app._action_bar_open_folder),
    }
    for key in ("folder", "view"):  # side="right": the first one packed sits rightmost
        app.queue_result_buttons[key].pack(side="right", padx=(6, 0))
        app.queue_result_buttons[key].state(["disabled"])
    bind_tooltip(app.queue_result_buttons["view"],
                 _("Opens the selected finished job in the transcript viewer. It needs the Whisper JSON "
                   "output format, which is on by default."))
    # Why the selected failed job failed (queue_failure_line); packed by
    # App._update_queue_action_bar only while it has text.
    app.queue_failure_var = tk.StringVar(master=parent, value="")
    app.queue_failure_label = ttk.Label(
        parent, textvariable=app.queue_failure_var,
        foreground=tokens.themed(tokens.DANGER_TEXT), wraplength=px(760), justify="left",
    )
    # A single-click on a running/paused row's status or progress cell
    # toggles pause/resume — a discoverable shortcut on top of the menu.
    app.tree.bind("<Button-1>", app.queue_status_cell_click, add="+")
    app.tree.bind("<<TreeviewSelect>>", lambda _e: app._update_queue_action_bar())


def build_download_tab(app: "App", parent: ttk.Frame) -> None:
    top = ttk.Frame(parent, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text=pgettext("download form", "URL")).grid(row=0, column=0, sticky="w")
    app.download_url_var = tk.StringVar()
    app.download_url_var.trace_add("write", lambda *_args: app.format_service.schedule_lookup())
    url_cell = ttk.Frame(top)
    url_cell.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(6, 0))
    url_entry = ttk.Entry(url_cell, textvariable=app.download_url_var, width=80)
    url_entry.pack(fill="x")
    start_download = once_per(1.5, app.add_download)  # as the Download button
    for key in ("<Return>", "<KP_Enter>"):
        url_entry.bind(key, start_download)
    # Which subtitles the looked-up video already has; packed only when there
    # are some (App.update_caption_bar), so it takes no room otherwise.
    app.caption_bar_var = tk.StringVar(value="")
    app.caption_bar_label = ttk.Label(
        url_cell, textvariable=app.caption_bar_var,
        foreground=tokens.themed(tokens.SUCCESS_TEXT), wraplength=px(760), justify="left",
    )
    help_icon(
        top,
        _("Paste a link from YouTube or any other yt-dlp-supported site. "
          "Available formats and subtitles are looked up automatically as "
          "soon as you paste it."),
    ).grid(row=0, column=3, sticky="w", padx=(6, 0))

    # Browser cookies right under the URL: login-walled sites (Instagram,
    # Facebook, TikTok stories, age-gated YouTube) need them, and the option
    # used to exist only in Advanced settings. Same config key, so the two
    # controls stay in sync (App.sync_cookies_browser_from_config).
    ttk.Label(top, text=_("Log-in cookies")).grid(row=1, column=0, sticky="w", pady=(8, 0))
    cookies_row = ttk.Frame(top)
    cookies_row.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    current_cookies = str(app.app_config.get("cookies_from_browser") or "")
    app.download_cookies_var = tk.StringVar(value=cookie_browser_label(current_cookies))
    app.download_cookies_combo = ttk.Combobox(
        cookies_row,
        textvariable=app.download_cookies_var,
        state="readonly",
        values=cookie_browser_choices(current_cookies),
        width=14,
    )
    app.download_cookies_combo.pack(side="left")
    app.download_cookies_combo.bind(
        "<<ComboboxSelected>>", lambda _e: app._on_download_cookies_selected()
    )
    ttk.Label(
        cookies_row,
        text=_("use my browser's log-in — for Instagram, Facebook, TikTok stories, age-gated videos"),
        foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(side="left", padx=(10, 0))
    help_icon(
        top,
        _("Pick the browser you are logged in with. The download then uses "
          "that browser's log-in session, so videos that need an account "
          "(Instagram, Facebook, TikTok stories, age-restricted YouTube) work. "
          "The cookies are read on this computer only; nothing is uploaded. "
          "On Windows, close Chrome/Edge completely if it says it could not "
          "copy the cookie database. Same setting as Advanced › Downloads."),
    ).grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text=pgettext("download form", "Folder")).grid(row=2, column=0, sticky="w", pady=(8, 0))
    # No saved folder (a fresh install whose Quick start was skipped): the user's Downloads
    # folder, as the Quick start offers, instead of an empty box and a "Missing folder"
    # warning on the first Download (click-through test, 2026-10-21). Saved on the first use.
    from app.dialogs.quick_start import default_output_folder

    app.download_folder_var = tk.StringVar(value=default_output_folder(app.app_config))
    ttk.Entry(top, textvariable=app.download_folder_var, width=70).grid(
        row=2, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
    )
    ttk.Button(top, text=_("Browse"), command=app.browse_download_folder).grid(
        row=2, column=2, sticky="ew", padx=(6, 0), pady=(8, 0)
    )
    help_icon(
        top,
        _("Where the downloaded file is saved. Defaults to the folder "
          "you last used; Browse to change it."),
    ).grid(row=2, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text=pgettext("download form", "Mode")).grid(row=3, column=0, sticky="w", pady=(8, 0))
    # download_mode_var keeps the English mode (App, the download service and the
    # video-site tab compare and set it); the combobox shows the translated labels.
    app.download_mode_var = tk.StringVar(value="Audio and video")
    mode_labels = {
        "Audio and video": pgettext("download mode", "Audio and video"),
        "Audio": pgettext("download mode", "Audio"),
    }
    app.download_mode_combo = ttk.Combobox(
        top,
        textvariable=translated_choice_var(top, app.download_mode_var, mode_labels),
        state="readonly",
        values=tuple(mode_labels.values()),
        width=24,
    )
    app.download_mode_combo.grid(row=3, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
    app.download_mode_combo.bind("<<ComboboxSelected>>", lambda _e: app.update_download_mode())
    help_icon(
        top,
        _("'Audio and video' downloads a normal video file. 'Audio' "
          "extracts just the audio track — smaller and faster if you only "
          "need the sound or plan to transcribe it."),
    ).grid(row=3, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text=pgettext("download form", "Audio")).grid(row=4, column=0, sticky="w", pady=(8, 0))
    app.audio_format_var = tk.StringVar()
    app.audio_format_combo = ttk.Combobox(
        top, textvariable=app.audio_format_var, state="readonly", width=76
    )
    app.audio_format_combo.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        _("Audio-only quality/codec choice, filled in once the URL is "
          "looked up. Higher bitrate means a larger file and better "
          "quality."),
    ).grid(row=4, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text=pgettext("download form", "Video")).grid(row=5, column=0, sticky="w", pady=(8, 0))
    app.video_format_var = tk.StringVar()
    app.video_format_combo = ttk.Combobox(
        top, textvariable=app.video_format_var, state="readonly", width=76
    )
    app.video_format_combo.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        _("Video quality/resolution choice, filled in once the URL is "
          "looked up. Only used in 'Audio and video' mode."),
    ).grid(row=5, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text=pgettext("download form", "Output")).grid(row=6, column=0, sticky="w", pady=(8, 0))
    app.output_format_var = tk.StringVar(value="mp4")
    app.output_format_combo = ttk.Combobox(
        top, textvariable=app.output_format_var, state="readonly", width=20
    )
    app.output_format_combo.grid(row=6, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        _("Container format for the saved file (e.g. mp4). Changing it may "
          "re-encode the file instead of just repackaging it, which takes "
          "longer."),
    ).grid(row=6, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    # --- Optional time-range slice (v1.0.3) -------------------------------
    # Two short Entry widgets inside a LabelFrame, plus a tiny hint label
    # below. Pre-filled with "0:00:00" so the user edits a real value
    # instead of an empty box (per request). The download service treats a
    # zero/blank bound as "unset", so leaving both = the full video.
    app.download_start_time_var = tk.StringVar(value="0:00:00")
    app.download_end_time_var = tk.StringVar(value="0:00:00")
    trim_frame = section_labelframe(
        top, _("Time range (optional)"),
        _("Download (and optionally transcribe) only this portion of the "
          "video instead of the whole thing. Leave both at 0:00:00 for the "
          "full length."),
        padding=(8, 4),
    )
    trim_frame.grid(
        row=6, column=2, sticky="ew", padx=(12, 0), pady=(8, 0)
    )
    ttk.Label(trim_frame, text=pgettext("time range", "Start")).grid(row=0, column=0, sticky="w")
    start_entry = ttk.Entry(
        trim_frame, textvariable=app.download_start_time_var, width=12
    )
    start_entry.grid(row=0, column=1, sticky="w", padx=(4, 8))
    ttk.Label(trim_frame, text=pgettext("time range", "End")).grid(row=1, column=0, sticky="w", pady=(2, 0))
    end_entry = ttk.Entry(
        trim_frame, textvariable=app.download_end_time_var, width=12
    )
    end_entry.grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(2, 0))
    # Keep the position sliders in sync when Start/End is typed directly
    # instead of dragged -- see App._sync_download_scale_from_text for why
    # this matters (a stale slider position silently overwrites a typed
    # value the next time either knob moves).
    app.download_start_time_var.trace_add(
        "write", lambda *_a: app._sync_download_scale_from_text("start")
    )
    app.download_end_time_var.trace_add(
        "write", lambda *_a: app._sync_download_scale_from_text("end")
    )
    # Position sliders (0 .. video length) that fill the Start/End fields by
    # dragging. Disabled until a video is probed — the format probe calls
    # app.set_download_duration() with the real length (0 = live/unknown).
    trim_frame.columnconfigure(2, weight=1)
    app.download_start_scale = ttk.Scale(
        trim_frame, from_=0.0, to=1.0, orient="horizontal", length=px(180),
        command=lambda v: app._on_download_scale("start", v),
    )
    app.download_start_scale.state(["disabled"])
    app.download_start_scale.grid(row=0, column=2, sticky="ew", padx=(8, 0))
    app.download_end_scale = ttk.Scale(
        trim_frame, from_=0.0, to=1.0, orient="horizontal", length=px(180),
        command=lambda v: app._on_download_scale("end", v),
    )
    app.download_end_scale.state(["disabled"])
    app.download_end_scale.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(2, 0))
    ttk.Label(
        trim_frame,
        text=_("format H:MM:SS — e.g. 0:00:51 to 0:01:25; leave at 0:00:00 for full video"),
        foreground=tokens.themed(tokens.TEXT_MUTED),
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
    app.download_duration_var = tk.StringVar(value="")
    ttk.Label(trim_frame, textvariable=app.download_duration_var, foreground=tokens.themed(tokens.TEXT_MUTED)).grid(
        row=3, column=0, columnspan=3, sticky="w"
    )

    ttk.Label(top, text=pgettext("download form", "Subtitles")).grid(row=7, column=0, sticky="w", pady=(8, 0))
    sub_frame = ttk.Frame(top)
    sub_frame.grid(row=7, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    saved_sub_enabled = bool(app.app_config.get("download_subtitles_enabled", False))
    app.download_subtitles_var = tk.BooleanVar(value=saved_sub_enabled)
    ttk.Checkbutton(
        sub_frame,
        text=_("Download subtitles (auto + manual when present)"),
        variable=app.download_subtitles_var,
        command=app.update_subtitle_state,
    ).pack(side="left")
    saved_sub_lang = app.app_config.get("download_subtitle_lang") or SUBTITLE_LANGUAGES[0][0]
    if saved_sub_lang not in [name for name, _code in SUBTITLE_LANGUAGES]:
        saved_sub_lang = SUBTITLE_LANGUAGES[0][0]
    # subtitle_lang_var keeps the English name (saved as download_subtitle_lang, looked up
    # in SUBTITLE_LANGUAGES); the combobox shows the translated names.
    app.subtitle_lang_var = tk.StringVar(value=saved_sub_lang)
    sub_labels = {name: subtitle_language_label(name) for name, _code in SUBTITLE_LANGUAGES}
    app.subtitle_lang_combo = ttk.Combobox(
        sub_frame,
        textvariable=translated_choice_var(sub_frame, app.subtitle_lang_var, sub_labels),
        state="disabled",
        values=list(sub_labels.values()),
        width=24,
    )
    app.subtitle_lang_combo.pack(side="left", padx=(10, 0))
    app.subtitle_status_var = tk.StringVar(value="")
    ttk.Label(sub_frame, textvariable=app.subtitle_status_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
        side="left", padx=(10, 0)
    )
    help_icon(
        top,
        _("Downloads the video's existing subtitles/captions (auto-"
          "generated or manual) in the chosen language, instead of "
          "transcribing the audio yourself. Only available when the site "
          "provides them."),
    ).grid(row=7, column=3, sticky="w", padx=(6, 0), pady=(8, 0))
    app.subtitle_lang_combo.bind(
        "<<ComboboxSelected>>", lambda _e: app.update_caption_shortcut_state()
    )

    # "Use captions instead" shortcut — a distinct action from the
    # "Download subtitles" checkbox above (which fetches subtitles ALONGSIDE
    # the media). This one skips the media download and transcription
    # entirely. Hidden by default; App.update_caption_shortcut_state shows
    # it only once a format lookup finds a caption track in the resolved
    # language (see app/services/format_service.py::caption_lang_map).
    caption_shortcut_frame = ttk.Frame(top)
    caption_shortcut_frame.grid(
        row=8, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0)
    )
    app.caption_shortcut_status_var = tk.StringVar(value="")
    ttk.Label(
        caption_shortcut_frame,
        textvariable=app.caption_shortcut_status_var,
        foreground=tokens.themed(tokens.SUCCESS_TEXT), wraplength=px(460), justify="left",
    ).pack(side="left")
    app.caption_shortcut_button = ttk.Button(
        caption_shortcut_frame,
        text=_("Use captions instead"),
        command=app.download_service.enqueue_caption_only_from_form,
    )
    # Not packed here — update_caption_shortcut_state packs/unpacks it on
    # demand so it stays invisible for the common case (no captions, or
    # not in the requested language).

    app.auto_transcribe_var = tk.BooleanVar(
        value=bool(app.app_config.get("auto_transcribe_after_download", False))
    )
    # Both "after the download" choices share row 9.
    after_frame = ttk.Frame(top)
    after_frame.grid(row=9, column=1, columnspan=3, sticky="w", padx=(6, 0), pady=(4, 0))
    ttk.Checkbutton(
        after_frame,
        text=_("Transcribe after download"),
        variable=app.auto_transcribe_var,
        command=app._save_auto_transcribe_pref,
    ).pack(side="left")
    help_icon(
        after_frame,
        _("Automatically queues the downloaded file for transcription as "
          "soon as the download finishes, using the settings in the "
          "Transcribe tab."),
    ).pack(side="left", padx=(6, 0))

    # "Make subtitled video": per job, not saved (a re-encode can take as
    # long as the video), see app/services/subbed_video.py.
    app.make_subbed_video_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        after_frame,
        text=_("Make subtitled video"),
        variable=app.make_subbed_video_var,
    ).pack(side="left", padx=(18, 0))
    help_icon(
        after_frame,
        _("Downloads the video, transcribes it with the Transcribe tab's "
          "settings, then burns the subtitles into a new file named "
          "<title>-subbed.mp4 next to the download. The download and the "
          "transcript files are kept. Needs 'Audio and video'."),
    ).pack(side="left", padx=(6, 0))

    # SMTV "all parts" toggle. Built always, shown only when an SMTV
    # episode with >=1 sibling parts is detected. format_service sets
    # visibility via app._smtv_series_toggle().
    app.smtv_download_all_parts_var = tk.BooleanVar(value=True)
    smtv_frame = ttk.Frame(top)
    smtv_check = ttk.Checkbutton(
        smtv_frame,
        text="Download all parts of this series (SMTV)",
        variable=app.smtv_download_all_parts_var,
    )
    smtv_check.pack(side="left")
    help_icon(
        smtv_frame,
        "This episode has multiple parts on the source site. Checking "
        "this queues every part, not just the one you pasted.",
    ).pack(side="left", padx=(6, 0))

    def _toggle(*, visible: bool) -> None:
        if visible:
            smtv_frame.grid(row=10, column=1, columnspan=2, sticky="w",
                            padx=(6, 0), pady=(4, 0))
        else:
            smtv_frame.grid_remove()

    _toggle(visible=False)
    app._smtv_series_toggle = _toggle  # type: ignore[attr-defined]

    app.format_status_var = tk.StringVar(value=_("Enter a URL to load available formats"))
    app.format_lookup_error = ""
    status_frame = ttk.Frame(top)
    status_frame.grid(
        row=11, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(4, 0)
    )
    # wraplength: a yt-dlp error is often one very long line; unwrapped it
    # widened the whole form and squeezed out the helper button below.
    app.format_status_label = ttk.Label(
        status_frame, textvariable=app.format_status_var,
        wraplength=px(820), justify="left",
    )
    app.format_status_label.pack(side="left")
    # One-click install of Deno, the JavaScript runtime yt-dlp needs for
    # YouTube (core.js_runtime). Packed only while a YouTube link is loaded
    # and no Deno exists (App.update_js_runtime_prompt).
    app.js_runtime_button = ttk.Button(
        status_frame,
        text=_("Install YouTube helper"),
        command=app.install_js_runtime,
    )
    bind_tooltip(
        app.js_runtime_button,
        _("YouTube downloads need a small JavaScript engine (Deno, one-time "
          "download of about 40 MB from its official GitHub page, checked "
          "against its published checksum). Without it some or all YouTube "
          "formats are missing and downloads can fail."),
    )

    # Primary CTA for the Download tab — same Accent style + larger
    # ipadx/ipady as the Transcribe button on the other tab, so the
    # user has a single visual rule for "this is the main action".
    # Spans the full row (columnspan=3) and sits at the bottom of the
    # form so it's the natural last step after filling URL + format.
    download_btn = ttk.Button(
        top, text="⬇    " + pgettext("button", "Download"),
        command=app.add_download,
        style="Accent.TButton",
    )
    download_btn.grid(
        row=12, column=0, columnspan=3, sticky="e",
        padx=(0, 0), pady=(12, 0), ipadx=24, ipady=8,
    )

    top.columnconfigure(1, weight=1)

    bottom = ttk.Frame(parent, padding=(10, 0, 10, 10))
    bottom.pack(fill="both", expand=True)

    cols = ("name", "url", "format", "status", "progress", "time")
    bottom.rowconfigure(0, weight=1)
    bottom.columnconfigure(0, weight=1)
    app.download_tree = ttk.Treeview(bottom, columns=cols, show="headings", height=8)
    # Column ids stay English (App reads rows by id); the headings show the same words translated.
    download_headings = {
        "name": pgettext("download column", "name"),
        "url": pgettext("download column", "url"),
        "format": pgettext("download column", "format"),
        "status": pgettext("download column", "status"),
        "progress": pgettext("download column", "progress"),
        "time": pgettext("download column", "time"),
    }
    for c in cols:
        app.download_tree.heading(c, text=download_headings[c])
    app.download_tree.column("name", width=px(220))
    app.download_tree.column("url", width=px(420))
    app.download_tree.column("format", width=px(180))
    app.download_tree.column("status", width=px(100))
    app.download_tree.column("progress", anchor="w")
    fit_progress_column(app.download_tree)
    app.download_tree.column("time", width=px(80))
    _dvsb = _AutoScrollbar(bottom, orient="vertical", command=app.download_tree.yview)
    app.download_tree.configure(yscrollcommand=_dvsb.set)
    app.download_tree.grid(row=0, column=0, sticky="nsew")
    _dvsb.grid(row=0, column=1, sticky="ns")
    app.download_tree.bind("<Button-3>", app.download_menu_row)
    if sys.platform == "darwin":
        # See the Queue-tab tree binding above: macOS right-click is
        # Button-2, not Button-3.
        app.download_tree.bind("<Button-2>", app.download_menu_row)
    # See `app.row_map` above — annotation belongs on the class.
    app.download_row_map = {}

    # R2 — Download action bar mirroring the Queue tab. Pause is the
    # stop-and-continue semantics (tooltip below); SMTV downloads disable it.
    dl_action_bar = ttk.Frame(parent, padding=(10, 0, 10, 4))
    dl_action_bar.pack(fill="x")
    app.download_action_buttons = {
        "pause": ttk.Button(
            dl_action_bar, text=pgettext("button", "Pause"),
            command=lambda: app._download_action_apply(app.pause_download),
        ),
        "resume": ttk.Button(
            dl_action_bar, text=pgettext("button", "Resume"),
            command=lambda: app._download_action_apply(app.resume_download),
        ),
        "cancel": ttk.Button(
            dl_action_bar, text=_("Cancel"),
            command=lambda: app._download_action_apply(app.cancel_download),
        ),
        "rerun": ttk.Button(
            dl_action_bar, text=_("Re-run"),
            command=lambda: app._download_action_apply(app._rerun_download),
        ),
        "remove": ttk.Button(
            dl_action_bar, text=_("Remove"),
            command=lambda: app._download_action_apply(app.remove_download),
        ),
        "open": ttk.Button(
            dl_action_bar, text=pgettext("button", "Open"),
            command=app._download_action_open,
        ),
    }
    for key in ("pause", "resume", "cancel", "rerun", "remove", "open"):
        app.download_action_buttons[key].pack(side="left", padx=(0, 6))
        app.download_action_buttons[key].state(["disabled"])
    # Global list action (not tied to a selection), so it lives on the
    # right like the Queue tab's own "Remove ended jobs" -- mirrors that
    # button, which this tab was missing.
    dl_clear_btn = ttk.Button(
        dl_action_bar, text=_("Remove ended downloads"), command=app.clear_completed_downloads,
    )
    dl_clear_btn.pack(side="right")
    bind_tooltip(dl_clear_btn, _("Takes every finished, failed or cancelled download off this list. "
                                 "No file is deleted."))
    ttk.Label(
        dl_action_bar,
        text=_("(Pause stops the download but keeps the partial file; "
               "Resume continues it)"),
        foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(side="left", padx=(8, 0))
    app.download_tree.bind(
        "<<TreeviewSelect>>", lambda _e: app._update_download_action_bar()
    )

    app.update_download_mode()
    app.update_subtitle_state()
    app.after(200, app.format_service.poll)
    app.after(300, app.download_service.poll)


def build_server_tab(app: "App", parent: ttk.Frame) -> None:
    """Web / LAN access: a one-click toggle to let a browser transcribe.

    Turning this on starts a small web page (served by this app) so you —
    or other people on your network — can drop a file or paste a link in a
    browser and get subtitles back, without installing anything. One
    obvious Start/Stop button; everything else has a plain-language note.
    """
    cfg = app.app_config
    frame = ttk.Frame(parent, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame, text=_("Web / LAN access"), font=("TkDefaultFont", 13, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            _("Turn this on to open a simple web page that uses this app to "
              "transcribe. Open it in a browser on this computer, or share it "
              "with phones and other PCs on your network. It stays off until "
              "you start it, and there is nothing to install on the other "
              "devices.")
        ),
        wraplength=px(620), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", pady=(4, 12))

    # --- the one obvious control: Start / Stop -------------------------------
    toggle_row = ttk.Frame(frame)
    toggle_row.pack(fill="x", pady=(0, 6))
    app.server_toggle_btn = ttk.Button(
        toggle_row, text=_("Start web access"), command=app.toggle_server,
    )
    app.server_toggle_btn.pack(side="left")
    app.server_open_btn = ttk.Button(
        toggle_row, text=_("Open in browser"),
        command=app.open_server_in_browser, state="disabled",
    )
    app.server_open_btn.pack(side="left", padx=(8, 0))

    # Status line ("Off" / "Running...").
    app.server_status_var = tk.StringVar(value=pgettext("web access status", "Off"))
    ttk.Label(
        frame, textvariable=app.server_status_var,
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w", pady=(2, 0))

    # The reachable address(es) — shown so the user can type them on a
    # phone or another PC. Selectable so they can copy it.
    app.server_url_var = tk.StringVar(value="")
    url_label = ttk.Label(
        frame, textvariable=app.server_url_var, foreground=tokens.themed(tokens.LINK),
        justify="left",
    )
    url_label.pack(anchor="w", pady=(2, 12))
    app.server_url_label = url_label

    # Phone: a QR code of the network address, packed under the address only
    # while the server is shared on the network (App._show_phone_link).
    app.server_qr_frame = ttk.Frame(frame)
    app.server_qr_label = ttk.Label(app.server_qr_frame)
    app.server_qr_label.pack(side="left", anchor="n")
    qr_side = ttk.Frame(app.server_qr_frame)
    qr_side.pack(side="left", anchor="n", padx=(12, 0))
    ttk.Label(
        qr_side, text=_("Use it from your phone"), font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")
    app.server_qr_note_var = tk.StringVar(value="")
    ttk.Label(
        qr_side, textvariable=app.server_qr_note_var,
        wraplength=px(380), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", pady=(2, 0))
    ttk.Button(
        qr_side, text=_("Copy phone link"), command=app.copy_phone_link,
    ).pack(anchor="w", pady=(8, 0))

    # --- options -------------------------------------------------------------
    opts = section_labelframe(
        frame, _("Options"),
        _("Port, network sharing, and an optional access password for the "
          "web page this tab starts. Each field also has its own note "
          "below it."),
        padding=12,
    )
    opts.pack(fill="x", pady=(0, 8))

    # Port.
    port_row = ttk.Frame(opts)
    port_row.pack(fill="x", pady=(0, 8))
    ttk.Label(port_row, text=_("Port:")).pack(side="left")
    saved_port = cfg.get("server_port", 8765)
    try:
        saved_port = int(saved_port)
    except (TypeError, ValueError):
        saved_port = 8765
    if not 1 <= saved_port <= 65535:
        saved_port = 8765
    app.server_port_var = tk.IntVar(value=saved_port)
    ttk.Spinbox(
        port_row, from_=1, to=65535, width=8,
        textvariable=app.server_port_var,
        command=app._save_server_prefs,
    ).pack(side="left", padx=(8, 0))
    ttk.Label(
        port_row,
        text=_("(the number after the address; leave the default if unsure)"),
        foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(side="left", padx=(8, 0))

    # Share on local network.
    app.server_share_lan_var = tk.BooleanVar(
        value=bool(cfg.get("server_share_lan", False))
    )
    ttk.Checkbutton(
        opts, text=_("Share on local network (other devices can use it)"),
        variable=app.server_share_lan_var,
        command=app._save_server_prefs,
    ).pack(anchor="w")
    ttk.Label(
        opts,
        text=(
            _("Off: only this computer can use it (no firewall prompt).\n"
              "On: Windows may ask to allow it through the firewall — click "
              "Allow. Anyone on your network will be able to use it.")
        ),
        wraplength=px(560), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

    # Optional access password (the --token mechanism).
    pw_row = ttk.Frame(opts)
    pw_row.pack(fill="x")
    ttk.Label(pw_row, text=_("Access password (optional):")).pack(side="left")
    app.server_token_var = tk.StringVar(value=str(cfg.get("server_token", "")))
    pw_entry = ttk.Entry(
        pw_row, textvariable=app.server_token_var, width=24, show="•",
    )
    pw_entry.pack(side="left", padx=(8, 0))
    pw_entry.bind("<FocusOut>", lambda _e: app._save_server_prefs())
    ttk.Label(
        opts,
        text=(
            _("Leave blank for no password. If you set one, share it with the "
              "people you want to let in: they type it into the page's "
              "password box, or open the address with  ?token=YOURPASSWORD  "
              "added (letters and digits only; the page then removes it from "
              "the address bar).")
        ),
        wraplength=px(560), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", padx=(0, 0), pady=(4, 0))

    # HTTPS (self-signed certificate).
    app.server_https_enabled_var = tk.BooleanVar(
        value=bool(cfg.get("server_https_enabled", False))
    )
    ttk.Checkbutton(
        opts, text=_("Use HTTPS (self-signed certificate)"),
        variable=app.server_https_enabled_var,
        command=app._save_server_prefs,
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(
        opts,
        text=(
            _("Off by default. When on, the address starts with https:// and "
              "the browser will warn that the certificate is not trusted the "
              "first time — that is expected; accept it once.")
        ),
        wraplength=px(560), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

    # Completion webhook.
    hook_row = ttk.Frame(opts)
    hook_row.pack(fill="x")
    ttk.Label(hook_row, text=_("Webhook URL (optional):")).pack(side="left")
    app.server_webhook_url_var = tk.StringVar(
        value=str(cfg.get("server_webhook_url", ""))
    )
    hook_entry = ttk.Entry(
        hook_row, textvariable=app.server_webhook_url_var, width=32,
    )
    hook_entry.pack(side="left", padx=(8, 0))
    hook_entry.bind("<FocusOut>", lambda _e: app._save_server_prefs())
    ttk.Label(
        opts,
        text=(
            _("Leave blank for none. When set, the server POSTs a small JSON "
              "summary to this URL each time a job finishes (or fails). "
              "Loopback and private cloud-metadata addresses are refused.")
        ),
        wraplength=px(560), justify="left", foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", padx=(0, 0), pady=(4, 0))

    # --- safety note ---------------------------------------------------------
    ttk.Label(
        frame,
        text=(
            _("Use this only on a network you trust (your home or office "
              "Wi-Fi). It has no accounts, and unless you turn on HTTPS above "
              "it is not encrypted — anyone who can reach the address (and "
              "knows the password, if you set one) can use it. The first time "
              "you turn it on it may need to download the speech model; jobs "
              "will wait for that.")
        ),
        wraplength=px(620), justify="left", foreground=tokens.themed(tokens.WARNING_TEXT),
    ).pack(anchor="w", pady=(10, 0))
