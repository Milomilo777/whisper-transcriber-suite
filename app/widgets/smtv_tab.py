"""The "Supreme Master TV" tab: an introduction to the channel plus a
browsable, searchable view of its video library.

Layout, top to bottom:

* a hero banner (gradient, channel name, tagline, live stats and links:
  watch live, about, schedule, website);
* a search bar (keyword, program, site language) and one-click program
  shortcuts;
* a scrolling list of video cards (thumbnail, title, program, date,
  length, views, summary) with Watch / Download / Transcribe actions,
  and "Load more" paging.

All network work (search pages, thumbnails) runs on background threads
and comes back through ``app.post_to_main``; Tk is only touched on the
main thread. Data comes from :mod:`core.integrations.smtv_browse`.
Download / Transcribe prefill the existing Download tab (which already
understands SMTV episode URLs) rather than duplicating that pipeline.
"""
from __future__ import annotations

import io
import logging
import math
import threading
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)

_HERO_H = 176
_THUMB_W, _THUMB_H = 192, 108
# Fixed hero palette (reads the same under sv_ttk light/dark).
_HERO_LEFT = (12, 25, 58)     # deep navy
_HERO_RIGHT = (8, 110, 130)   # teal
_HERO_TEXT = "#f8fafc"
_HERO_SUB = "#bae6fd"
_HERO_ACCENT = "#fde68a"      # warm gold
_SHORTCUTS = (
    "Featured Programs", "Noteworthy News", "Between Master and Disciples",
    "Words of Wisdom", "Vegan Cooking Show", "Animal World: Our Co-inhabitants",
    "Science and Spirituality",
)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    r, g, bl = (int(round(x + (y - x) * t)) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def format_views(n: int | None) -> str:
    if n is None:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M views"
    if n >= 10_000:
        return f"{n / 1000:.0f}K views"
    if n >= 1000:
        return f"{n / 1000:.1f}K views"
    return f"{n} views"


_RTL_LANGS = frozenset({"fa", "ar"})


def detail_line(item: Any) -> str:
    """Date · length · views -- digits and Latin only, so it never mixes
    directions with a right-to-left program name on the same label."""
    parts = [item.date, item.duration, format_views(item.views)]
    return "   ·   ".join(p for p in parts if p)


def shorten(text: str, limit: int = 260) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;: ") + "…"


# --------------------------------------------------------------------- build


# Adapted from SiriWave (https://github.com/kopiro/siriwave) — the "classic"
# curve set (attenuation, line width, opacity) and ClassicCurve's
# globalAttFn / xPos / yPos (MIT, Copyright (c) 2020 Flavio Maria De Stefano).
_HERO_CURVES = ((-2, 1, 0.1), (-6, 1, 0.2), (4, 1, 0.4), (2, 1, 0.6), (1, 1.5, 1.0))


def _hero_curve_points(attenuation: float, width: float, height_max: float,
                       amplitude: float, phase: float) -> list[float]:
    out: list[float] = []
    scale = 0.6 * height_max * amplitude / attenuation
    steps = 200
    for k in range(steps + 1):
        x = -2 + 4 * k / steps
        att = (4 / (4 + x ** 4)) ** 4
        out.append(width * ((x + 2) / 4))
        out.append(height_max + att * scale * math.sin(6 * x - phase))
    return out


def build_smtv_tab(app: Any, parent: Any) -> None:
    from core.integrations import smtv_browse as sb

    state = _TabState(app)
    app.smtv_state = state
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(3, weight=1)

    _build_hero(app, state, parent).grid(row=0, column=0, sticky="ew")

    # ── Search bar ─────────────────────────────────────────────────────
    bar = ttk.Frame(parent, padding=(15, 12, 15, 4))
    bar.grid(row=1, column=0, sticky="ew")
    bar.columnconfigure(1, weight=1)
    ttk.Label(bar, text="Search").grid(row=0, column=0, sticky="w")
    state.query_var = tk.StringVar()
    entry = ttk.Entry(bar, textvariable=state.query_var)
    entry.grid(row=0, column=1, sticky="ew", padx=(8, 12))
    entry.bind("<Return>", lambda _e: state.new_search())
    state.program_var = tk.StringVar(value=sb.PROGRAMS[0][0])
    ttk.Combobox(
        bar, textvariable=state.program_var, state="readonly", width=30,
        values=[label for label, _t, _c in sb.PROGRAMS],
    ).grid(row=0, column=2, padx=(0, 8))
    state.lang_var = tk.StringVar(value="English")
    lang_combo = ttk.Combobox(
        bar, textvariable=state.lang_var, state="readonly", width=20,
        values=[name for _c, name in sb.LANGUAGES],
    )
    lang_combo.grid(row=0, column=3, padx=(0, 8))
    for combo in bar.grid_slaves(row=0):
        if isinstance(combo, ttk.Combobox):
            combo.bind("<<ComboboxSelected>>", lambda _e: state.new_search())
    ttk.Button(
        bar, text="Search", style="Accent.TButton", command=state.new_search,
    ).grid(row=0, column=4)

    chips = ttk.Frame(parent, padding=(15, 2, 15, 6))
    chips.grid(row=2, column=0, sticky="ew")
    ttk.Label(chips, text="Explore:", foreground="#64748b").pack(side="left", padx=(0, 6))
    for label in _SHORTCUTS:
        ttk.Button(
            chips, text=label.split(":")[0], style="Toolbutton",
            command=lambda lb=label: state.show_program(lb),
        ).pack(side="left", padx=2)

    # ── Results ────────────────────────────────────────────────────────
    body = ttk.Frame(parent)
    body.grid(row=3, column=0, sticky="nsew", padx=(15, 0), pady=(0, 6))
    body.columnconfigure(0, weight=1)
    body.rowconfigure(1, weight=1)
    state.status_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=state.status_var, foreground="#64748b").grid(
        row=0, column=0, sticky="w", pady=(0, 4)
    )
    canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0)
    try:
        bg = str(ttk.Style().lookup("TFrame", "background") or "")
        if bg:
            canvas.configure(background=bg)
    except Exception:  # noqa: BLE001
        pass
    vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=1, column=0, sticky="nsew")
    vsb.grid(row=1, column=1, sticky="ns")
    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _on_canvas_resize(e: "tk.Event[tk.Canvas]") -> None:
        canvas.itemconfigure(window, width=e.width)
        state.set_wrap(e.width)

    canvas.bind("<Configure>", _on_canvas_resize)
    _bind_wheel(canvas, inner)
    state.canvas, state.inner = canvas, inner

    # First load waits until the tab is actually shown: no network traffic
    # at app start for anyone who never opens it, and by then the app's
    # post_to_main bridge (built after the tabs) exists.
    def _first_show(_e: Any = None) -> None:
        if state.page == 0 and not state.loading:
            state.new_search()

    parent.bind("<Map>", _first_show, add="+")


def _bind_wheel(canvas: tk.Canvas, inner: Any) -> None:
    """Mouse-wheel scrolls the list only while the pointer is over it."""
    def _wheel(e: "tk.Event[Any]") -> None:
        delta = e.delta if e.delta else (120 if getattr(e, "num", 0) == 4 else -120)
        canvas.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")

    def _enter(_e: Any) -> None:
        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel)
        canvas.bind_all("<Button-5>", _wheel)

    def _leave(_e: Any) -> None:
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.unbind_all(seq)

    for w in (canvas, inner):
        w.bind("<Enter>", _enter)
        w.bind("<Leave>", _leave)


def _build_hero(app: Any, state: "_TabState", parent: Any) -> tk.Canvas:
    from core.integrations import smtv_browse as sb

    hero = tk.Canvas(parent, height=_HERO_H, highlightthickness=0, borderwidth=0,
                     background=_mix(_HERO_LEFT, _HERO_LEFT, 0))
    links = (
        ("▶  Watch live", sb.LIVE_URL),
        ("About the channel", "about-us/"),
        ("TV schedule", "schedule/"),
        ("Website", ""),
    )
    buttons = []
    for i, (label, target) in enumerate(links):
        style = "Accent.TButton" if i == 0 else "TButton"
        btn = ttk.Button(hero, text=label, style=style,
                         command=lambda t=target: state.open_link(t))
        buttons.append(btn)

    def _draw(_e: Any = None) -> None:
        hero.delete("all")
        w = max(hero.winfo_width(), 400)
        steps = 64
        for k in range(steps):
            x0 = w * k / steps
            hero.create_rectangle(x0, 0, w * (k + 1) / steps + 1, _HERO_H,
                                  fill=_mix(_HERO_LEFT, _HERO_RIGHT, k / (steps - 1)),
                                  outline="")
        # Decorative sine waves on the right.
        wave_w = w * 0.45
        for att, width, opacity in _HERO_CURVES:
            pts = _hero_curve_points(att, wave_w, _HERO_H / 2, 0.85, math.pi / 3)
            pts = [p + (w - wave_w) if i % 2 == 0 else p for i, p in enumerate(pts)]
            hero.create_line(*pts, fill=_mix((253, 230, 138), _HERO_RIGHT, 1 - opacity * 0.7),
                             width=width, smooth=True)
        hero.create_text(24, 26, anchor="nw", text="SUPREME MASTER TELEVISION",
                         fill=_HERO_ACCENT, font=("Segoe UI", 10, "bold"))
        hero.create_text(24, 46, anchor="nw", text="Good news from around our beautiful planet",
                         fill=_HERO_TEXT, font=("Segoe UI Semibold", 20))
        hero.create_text(24, 86, anchor="nw", text=state.stats_text(),
                         fill=_HERO_SUB, font=("Segoe UI", 10))
        x = 24
        for btn in buttons:
            hero.create_window(x, 124, anchor="nw", window=btn)
            x += btn.winfo_reqwidth() + 8

    hero.bind("<Configure>", _draw)
    state.redraw_hero = _draw
    return hero


# --------------------------------------------------------------------- state


class _TabState:
    """Mutable state + actions for one SMTV tab instance."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.query_var: tk.StringVar
        self.program_var: tk.StringVar
        self.lang_var: tk.StringVar
        self.status_var: tk.StringVar
        self.canvas: tk.Canvas | None = None
        self.inner: Any = None
        self.redraw_hero: Any = None
        self.total: int | None = None
        self.page = 0
        self.has_more = False
        self.loading = False
        self._generation = 0
        self._cards: list[dict[str, Any]] = []
        self._images: dict[str, Any] = {}   # url -> PhotoImage (keeps refs alive)
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="smtv-thumb")
        self._more_btn: ttk.Button | None = None
        self._placeholder: tk.PhotoImage | None = None
        self._rtl = False
        self._wrap = 600

    # -- queries --------------------------------------------------------

    def _params(self) -> tuple[str, str, str, str]:
        from core.integrations import smtv_browse as sb

        lang = next((c for c, n in sb.LANGUAGES if n == self.lang_var.get()), "en")
        type_, cat = next(
            ((t, c) for label, t, c in sb.PROGRAMS if label == self.program_var.get()),
            ("all", ""),
        )
        return lang, self.query_var.get().strip(), type_, cat

    def lang_code(self) -> str:
        return self._params()[0]

    def stats_text(self) -> str:
        from core.integrations import smtv_browse as sb

        videos = f"{self.total:,} videos" if self.total and not self.query_var.get().strip() \
            and self.program_var.get() == sb.PROGRAMS[0][0] else "Thousands of videos"
        return (f"On air 24 hours a day, 7 days a week   ·   {len(sb.LANGUAGES)} "
                f"website languages   ·   {videos}   ·   news, wisdom, arts, animals & vegan living")

    def show_program(self, label: str) -> None:
        self.query_var.set("")
        self.program_var.set(label)
        self.new_search()

    def new_search(self) -> None:
        # Supersede any request still in flight: its result is dropped by
        # the generation check in _on_page, so it must not block this one.
        self._generation += 1
        self.loading = False
        self._rtl = self.lang_code() in _RTL_LANGS
        self.page = 0
        self.total = None
        self._clear_cards()
        if self.canvas is not None:
            self.canvas.yview_moveto(0)
        self.load_more()

    def load_more(self) -> None:
        if self.loading:
            return
        from core.integrations import smtv_browse as sb

        self.loading = True
        gen = self._generation
        page = self.page + 1
        lang, query, type_, cat = self._params()
        self._set_status("Loading…" if page == 1 else "Loading more…")
        if self._more_btn is not None:
            self._more_btn.configure(state="disabled", text="Loading…")

        def work() -> None:
            try:
                result = sb.search(lang, query, type_, cat, page)
                self.app.post_to_main(lambda: self._on_page(gen, result))
            except Exception as e:  # noqa: BLE001
                logger.warning("SMTV search failed: %s", e)
                msg = str(e)
                self.app.post_to_main(lambda: self._on_error(gen, msg))

        threading.Thread(target=work, name="smtv-search", daemon=True).start()

    def _on_page(self, gen: int, result: Any) -> None:
        if gen != self._generation:
            return  # a newer search replaced this one
        self.loading = False
        self.page = result.page
        self.total = result.total
        self.has_more = result.has_more and bool(result.items)
        self._remove_more_button()
        for item in result.items:
            self._add_card(item)
        shown = len(self._cards)
        if not shown:
            self._set_status("No videos found. Try another word, program or language.")
        elif self.total:
            self._set_status(f"Showing {shown:,} of {self.total:,} videos")
        else:
            self._set_status(f"Showing {shown:,} videos")
        if self.has_more:
            self._add_more_button()
        if self.redraw_hero is not None:
            try:
                self.redraw_hero()
            except Exception:  # noqa: BLE001
                pass

    def _on_error(self, gen: int, msg: str) -> None:
        if gen != self._generation:
            return
        self.loading = False
        self._set_status("Could not reach Supreme Master TV — check the internet "
                         "connection and press Search to try again.")
        self.app.log(f"Supreme Master TV: {msg}")
        if self._more_btn is not None:
            self._more_btn.configure(state="normal", text="Load more")

    # -- cards ------------------------------------------------------------

    def _clear_cards(self) -> None:
        for card in self._cards:
            try:
                card["frame"].destroy()
            except Exception:  # noqa: BLE001
                pass
        self._cards = []
        self._remove_more_button()

    def set_wrap(self, canvas_width: int) -> None:
        self._wrap = max(260, canvas_width - _THUMB_W - 60)
        for card in self._cards:
            for label in (card["title"], card["abstract"]):
                try:
                    label.configure(wraplength=self._wrap)
                except Exception:  # noqa: BLE001
                    pass

    def _add_card(self, item: Any) -> None:
        if self.inner is None:
            return
        frame = ttk.Frame(self.inner, padding=(0, 10, 12, 10))
        frame.pack(fill="x")
        frame.columnconfigure(1, weight=1)
        if self._placeholder is None:
            # A Label with no image sizes itself in text characters; a
            # blank image of the thumbnail size keeps every card aligned
            # while the real picture downloads.
            self._placeholder = tk.PhotoImage(width=_THUMB_W, height=_THUMB_H)
        thumb = tk.Label(frame, image=self._placeholder, background="#1e293b",
                         cursor="hand2", borderwidth=0)
        thumb.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 14))
        thumb.bind("<Button-1>", lambda _e, u=item.url: webbrowser.open(u))
        rtl = self._rtl
        side, anchor, justify = ("right", "e", "right") if rtl else ("left", "w", "left")
        title = ttk.Label(frame, text=item.title, font=("Segoe UI Semibold", 11),
                          wraplength=self._wrap, justify=justify, cursor="hand2")
        title.grid(row=0, column=1, sticky=anchor)
        title.bind("<Button-1>", lambda _e, u=item.url: webbrowser.open(u))
        meta = ttk.Frame(frame)
        meta.grid(row=1, column=1, sticky=anchor, pady=(2, 2))
        if item.program:
            ttk.Label(meta, text=item.program, foreground="#0891b2").pack(side=side)
            ttk.Label(meta, text="   ·   ", foreground="#94a3b8").pack(side=side)
        ttk.Label(meta, text=detail_line(item), foreground="#64748b").pack(side=side)
        abstract = ttk.Label(frame, text=shorten(item.abstract), wraplength=self._wrap,
                             justify=justify, foreground="#64748b")
        abstract.grid(row=2, column=1, sticky=anchor)
        actions = ttk.Frame(frame)
        actions.grid(row=3, column=1, sticky=anchor, pady=(6, 0))
        buttons = (
            ("▶  Watch", "Accent.TButton", lambda u=item.url: webbrowser.open(u)),
            ("⬇  Download", "TButton",
             lambda u=item.url: self.send_to_download(u, transcribe=False)),
            ("✎  Transcribe", "TButton",
             lambda u=item.url: self.send_to_download(u, transcribe=True)),
        )
        for text, style, cmd in buttons:
            ttk.Button(actions, text=text, style=style, command=cmd).pack(
                side=side, padx=(0, 6) if not rtl else (6, 0))
        ttk.Separator(self.inner, orient="horizontal").pack(fill="x", padx=(0, 12))
        card = {"frame": frame, "title": title, "abstract": abstract, "thumb": thumb}
        self._cards.append(card)
        if item.thumbnail:
            self._load_thumb(item.thumbnail, thumb)

    def _load_thumb(self, url: str, label: tk.Label) -> None:
        cached = self._images.get(url)
        if cached is not None:
            label.configure(image=cached)
            return

        def work() -> None:
            try:
                from core.integrations import smtv_browse as sb
                from PIL import Image

                raw = sb.fetch_bytes(url)
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                img = _cover(img, _THUMB_W, _THUMB_H)
            except Exception:  # noqa: BLE001
                logger.debug("Thumbnail failed: %s", url, exc_info=True)
                return
            self.app.post_to_main(lambda: self._show_thumb(url, img, label))

        self._pool.submit(work)

    def _show_thumb(self, url: str, img: Any, label: tk.Label) -> None:
        try:
            from PIL import ImageTk

            photo = ImageTk.PhotoImage(img)
            self._images[url] = photo
            if label.winfo_exists():
                label.configure(image=photo)
        except Exception:  # noqa: BLE001
            logger.debug("Could not show thumbnail", exc_info=True)

    def _add_more_button(self) -> None:
        if self.inner is None:
            return
        self._more_btn = ttk.Button(self.inner, text="Load more", command=self.load_more)
        self._more_btn.pack(pady=12)

    def _remove_more_button(self) -> None:
        if self._more_btn is not None:
            try:
                self._more_btn.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._more_btn = None

    # -- actions ----------------------------------------------------------

    def _set_status(self, text: str) -> None:
        try:
            self.status_var.set(text)
        except Exception:  # noqa: BLE001
            pass

    def open_link(self, target: str) -> None:
        from core.integrations import smtv_browse as sb

        url = target if target.startswith("http") else sb.page_url(self.lang_code(), target)
        webbrowser.open(url)

    def send_to_download(self, url: str, *, transcribe: bool) -> None:
        """Prefill the Download tab with ``url`` and switch to it.

        Transcribe also turns on "Transcribe after download" and, once the
        Download tab's own format lookup shows the episode HAS an audio
        track, switches to the smaller audio-only download. News clips and
        shorts ship video only, so for those the mode stays on video --
        forcing "Audio" there would make the Download button refuse.
        """
        app = self.app
        try:
            app.download_mode_var.set("Audio and video")
            try:
                app.update_download_mode()
            except Exception:  # noqa: BLE001
                logger.debug("update_download_mode failed", exc_info=True)
            # A card is one specific video; the Download tab's series
            # checkbox (default on for pasted links) stays visible there
            # for anyone who wants every part.
            parts_var = getattr(app, "smtv_download_all_parts_var", None)
            if parts_var is not None:
                parts_var.set(False)
            app.download_url_var.set(url)
            if transcribe:
                app.auto_transcribe_var.set(True)
                try:
                    app._save_auto_transcribe_pref()
                except Exception:  # noqa: BLE001
                    pass
            app.nb.select(app.t3)
        except Exception:  # noqa: BLE001
            logger.exception("Could not hand the video to the Download tab")
            return
        if transcribe:
            app.log("Supreme Master TV: transcription set up in the Download tab — "
                    "press Download to start.")
            self._prefer_audio_when_available(url, tries=40)
        else:
            app.log("Supreme Master TV: video added to the Download tab — press "
                    "Download to start.")

    def _prefer_audio_when_available(self, url: str, tries: int) -> None:
        app = self.app
        try:
            if app.download_url_var.get().strip() != url:
                return  # the user moved on to another link
            episode = getattr(app, "_smtv_episode", None)
            if episode is not None and getattr(episode, "page_url", "") == url:
                if getattr(app, "audio_format_map", None):
                    app.download_mode_var.set("Audio")
                    app.update_download_mode()
                return
        except Exception:  # noqa: BLE001
            logger.debug("Audio preference check failed", exc_info=True)
            return
        if tries > 0:
            try:
                app.after(500, lambda: self._prefer_audio_when_available(url, tries - 1))
            except Exception:  # noqa: BLE001
                pass


def _cover(img: Any, width: int, height: int) -> Any:
    """Scale ``img`` to fill width x height, centre-cropping the overflow."""
    from PIL import Image

    scale = max(width / img.width, height / img.height)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))
