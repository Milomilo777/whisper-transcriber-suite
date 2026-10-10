"""A book showcase panel for the Supreme Master TV tab.

One panel is built once and refilled with whichever book is chosen: the cover on a
white mat on the left; the eyebrow, title, subtitle, author, a short description, a
line of facts and the buttons that open the official pages on the right. The tab
puts it where the video list is and takes it away again on "Back to videos".

The cover is downloaded on a background thread (``submit``), decoded and fitted
there, and handed back through ``post_to_main``; Tk is only touched on the main
thread. While it loads, offline or after a failure the panel draws a neutral book
instead. All text and links come from :mod:`core.integrations.smtv_books`.
"""
from __future__ import annotations

import io
import logging
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Any, Callable

from app.dpi import scale_factor
from app.theme import system_fonts, tokens
from core import offline
from core.integrations import smtv_books
from core.integrations.smtv_books import Book

logger = logging.getLogger(__name__)

# Sizes at 96 dpi; scaled by the window's DPI factor when drawn.
_MAT_W, _MAT_H = 250, 310
_MAT_PAD = 16
_MAX_UPSCALE = 1.5       # a small official picture is never blown up further than this
_TEXT_MAX = 640          # longest comfortable line of body text
_NOT_BLANK = [0] * 11 + [255] * 245   # lookup table: a difference above 10 of 255 is content
_GUTTER = 32             # between the cover and the text


def _trim_margin(img: Any, keep: int) -> Any:
    """``img`` without its blank (near-white) border, leaving ``keep`` pixels around the content.

    The official pictures are shot on white with a wide empty margin; trimming it lets the
    cover fill the mat. A picture with no content at all is returned unchanged.
    """
    from PIL import Image, ImageChops

    diff = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255)))
    box = diff.convert("L").point(_NOT_BLANK).getbbox()
    if box is None:
        return img
    left, top, right, bottom = box
    return img.crop((max(0, left - keep), max(0, top - keep),
                     min(img.width, right + keep), min(img.height, bottom + keep)))


def _rounded(rgb: Any, radius: int) -> Any:
    """``rgb`` with rounded corners (transparent outside) and a hairline edge, anti-aliased."""
    from PIL import Image, ImageDraw

    w, h = rgb.size
    ss = 4
    box = (0, 0, w * ss - 1, h * ss - 1)
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius * ss, fill=255)
    ring = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(ring).rounded_rectangle(box, radius=radius * ss, outline=255, width=ss)
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)
    ring = ring.resize((w, h), Image.Resampling.LANCZOS)
    out = Image.composite(Image.new("RGB", (w, h), tokens.BOOK_COVER_EDGE), rgb, ring).convert("RGBA")
    out.putalpha(mask)
    return out


def _fit_on_mat(img: Any, width: int, height: int, pad: int) -> Any:
    """``img`` trimmed, scaled to fit inside the padded mat and centred on it (never cropped)."""
    from PIL import Image

    img = _trim_margin(img.convert("RGB"), keep=max(2, min(img.size) // 40))
    room_w, room_h = max(1, width - 2 * pad), max(1, height - 2 * pad)
    scale = min(room_w / img.width, room_h / img.height, _MAX_UPSCALE)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    mat = Image.new("RGB", (width, height), tokens.BOOK_COVER_MAT)
    mat.paste(img.resize(size, Image.Resampling.LANCZOS),
              ((width - size[0]) // 2, (height - size[1]) // 2))
    return _rounded(mat, round(pad * 0.75))


def _placeholder(width: int, height: int) -> Any:
    """A neutral closed book on the mat, drawn anti-aliased at four times the size."""
    from PIL import Image, ImageDraw

    ss = 4
    big = Image.new("RGB", (width * ss, height * ss), tokens.BOOK_COVER_MAT)
    draw = ImageDraw.Draw(big)
    bw, bh = int(width * 0.46) * ss, int(height * 0.50) * ss
    x0, y0 = (width * ss - bw) // 2, (height * ss - bh) // 2
    ink = tokens.BOOK_PLACEHOLDER
    draw.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=6 * ss, outline=ink, width=4 * ss)
    spine = x0 + bw // 5
    draw.line((spine, y0 + 4 * ss, spine, y0 + bh - 4 * ss), fill=ink, width=3 * ss)
    for i, frac in enumerate((0.34, 0.5, 0.66)):
        y = y0 + int(bh * frac)
        end = x0 + bw - 12 * ss - (bw // 5 if i == 2 else 0)
        draw.line((spine + 14 * ss, y, end, y), fill=ink, width=3 * ss)
    return _rounded(big.resize((width, height), Image.Resampling.LANCZOS), round(_MAT_PAD * 0.75))


class BookPanel(ttk.Frame):
    """The showcase of one book; ``show(book)`` refills it."""

    def __init__(self, master: tk.Misc, *, post_to_main: Callable[[Callable[[], None]], Any],
                 submit: Callable[[Callable[[], None]], Any],
                 on_close: Callable[[], None]) -> None:
        super().__init__(master)
        self._post = post_to_main
        self._submit = submit
        self._on_close = on_close
        self.book: Book | None = None
        self.cover_state = "placeholder"          # "placeholder" | "loading" | "cover"
        self.link_buttons: list[ttk.Button] = []
        self._photos: dict[str, Any] = {}         # book key -> PhotoImage (also keeps refs alive)
        self._placeholder_photo: Any = None
        self._inflight: set[str] = set()
        self._wraps: list[ttk.Label] = []
        k = scale_factor(self)
        self._mat = (round(_MAT_W * k), round(_MAT_H * k), round(_MAT_PAD * k))
        muted = tokens.themed(tokens.TEXT_MUTED)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.close_button = ttk.Button(self, text="←  Back to videos", command=self._close)
        self.close_button.grid(row=0, column=0, sticky="w", pady=(0, 14))

        # The showcase scrolls when the window is too short to hold it (scrollbar only then).
        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                 background=self._page_background())
        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        card = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window((0, 0), window=card, anchor="nw")
        card.columnconfigure(1, weight=1)
        self._card = card
        card.bind("<Configure>", self._on_card_resize, add="+")
        self._canvas.bind("<Configure>", self._on_canvas_resize, add="+")
        self._bind_wheel()

        side = ttk.Frame(card)
        side.grid(row=0, column=0, sticky="n")
        self._cover = tk.Label(side, borderwidth=0, highlightthickness=0,
                               background=self._page_background())
        self._cover.grid(row=0, column=0)
        self.note_var = tk.StringVar(value="")
        self._note = ttk.Label(side, textvariable=self.note_var, foreground=muted,
                               wraplength=self._mat[0], justify="center")
        self._note.grid(row=1, column=0, pady=(8, 0))

        text = ttk.Frame(card)
        text.grid(row=0, column=1, sticky="nw", padx=(round(_GUTTER * k), 0))
        text.columnconfigure(0, weight=1)
        self._text = text
        self._eyebrow = ttk.Label(text, text="FEATURED BOOK", foreground=tokens.PROGRAM_ACCENT,
                                  font=system_fonts.ui_font(self, "Segoe UI", 9, "bold"))
        self._eyebrow.grid(row=0, column=0, sticky="w")
        self._title = ttk.Label(text, justify="left",
                                font=system_fonts.ui_font(self, "Segoe UI Semibold", 22))
        self._title.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._subtitle = ttk.Label(text, justify="left", foreground=muted,
                                   font=system_fonts.ui_font(self, "Segoe UI", 13))
        self._subtitle.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self._author = ttk.Label(text, justify="left", foreground=tokens.PROGRAM_ACCENT,
                                 font=system_fonts.ui_font(self, "Segoe UI Semibold", 11))
        self._author.grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Separator(text, orient="horizontal").grid(row=4, column=0, sticky="ew", pady=14)
        self._summary = ttk.Label(text, justify="left", font=system_fonts.ui_font(self, "Segoe UI", 11))
        self._summary.grid(row=5, column=0, sticky="w")
        self._facts = ttk.Label(text, justify="left", foreground=muted,
                                font=system_fonts.ui_font(self, "Segoe UI", 10))
        self._facts.grid(row=6, column=0, sticky="w", pady=(12, 0))
        self._actions = ttk.Frame(text)
        self._actions.grid(row=7, column=0, sticky="w", pady=(20, 0))
        self._wraps = [self._title, self._subtitle, self._summary, self._facts]

        self.bind("<Configure>", self._on_resize, add="+")
        self.bind("<Escape>", lambda _e: self._close(), add="+")
        # The rounded cover corners and the scroll area take the theme's panel colour.
        self.bind("<<ThemeChanged>>", lambda _e: self.after_idle(self._refresh_background), add="+")

    # ---------------------------------------------------------------- show
    def show(self, book: Book) -> None:
        self.book = book
        self._refresh_background()
        self._title.configure(text=book.title)
        self._subtitle.configure(text=book.subtitle)
        if book.subtitle:
            self._subtitle.grid()
        else:
            self._subtitle.grid_remove()
        self._author.configure(text=f"by {book.author}")
        self._summary.configure(text=book.summary)
        self._facts.configure(text="   ·   ".join(book.facts))
        self._build_buttons(book)
        self._show_cover(book)
        self._on_resize()

    def _build_buttons(self, book: Book) -> None:
        for child in self._actions.winfo_children():
            child.destroy()
        self.link_buttons = []
        for i, link in enumerate(book.links):
            button = ttk.Button(self._actions, text=link.label,
                                style="Accent.TButton" if link.primary else "TButton",
                                command=lambda u=link.url: self._open(u))
            button.grid(row=0, column=i, padx=(0, 10))
            button.bind("<Escape>", lambda _e: self._close(), add="+")
            self.link_buttons.append(button)
        self.close_button.bind("<Escape>", lambda _e: self._close(), add="+")

    def _open(self, url: str) -> None:
        webbrowser.open(url)

    def _close(self) -> str:
        self._on_close()
        return "break"

    def _on_card_resize(self, _event: Any = None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._sync_scrollbar()

    def _on_canvas_resize(self, event: "tk.Event[tk.Canvas]") -> None:
        self._canvas.itemconfigure(self._window, width=event.width)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        """Show the scrollbar only while the content is taller than the visible area."""
        try:
            needed = self._card.winfo_reqheight() > self._canvas.winfo_height() > 1
            if needed and not self._vsb.winfo_manager():
                self._vsb.grid(row=1, column=1, sticky="ns")
            elif not needed and self._vsb.winfo_manager():
                self._vsb.grid_remove()
                self._canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _bind_wheel(self) -> None:
        """The mouse wheel scrolls the panel only while the pointer is over it."""
        canvas = self._canvas

        def wheel(e: "tk.Event[Any]") -> None:
            if not self._vsb.winfo_manager():
                return
            delta = e.delta if e.delta else (120 if getattr(e, "num", 0) == 4 else -120)
            canvas.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")

        def enter(_e: Any) -> None:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(seq, wheel)

        def leave(_e: Any) -> None:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(seq)

        for widget in (canvas, self._card):
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)

    def _on_resize(self, _event: Any = None) -> None:
        try:
            avail = self.winfo_width() - self._mat[0] - round(_GUTTER * scale_factor(self)) - 8
        except tk.TclError:
            return
        wrap = max(260, min(avail, round(_TEXT_MAX * scale_factor(self))))
        for label in self._wraps:
            label.configure(wraplength=wrap)

    # --------------------------------------------------------------- cover
    def _page_background(self) -> str:
        """The colour behind the rounded corners of the cover: the theme's panel colour."""
        try:
            return str(ttk.Style(self).lookup("TFrame", "background") or tokens.BOOK_COVER_MAT)
        except tk.TclError:
            return tokens.BOOK_COVER_MAT

    def _refresh_background(self) -> None:
        page = self._page_background()
        try:
            self._cover.configure(background=page)
            self._canvas.configure(background=page)
        except tk.TclError:
            pass

    def _set_image(self, photo: Any) -> None:
        self._cover.configure(image=photo)

    def _placeholder_image(self) -> Any:
        if self._placeholder_photo is None:
            from PIL import ImageTk

            w, h, _pad = self._mat
            self._placeholder_photo = ImageTk.PhotoImage(_placeholder(w, h), master=self)
        return self._placeholder_photo

    def _show_cover(self, book: Book) -> None:
        photo = self._photos.get(book.key)
        if photo is not None:
            self._set_image(photo)
            self.cover_state = "cover"
            self.note_var.set("")
            return
        self._set_image(self._placeholder_image())
        self.cover_state = "loading"
        self.note_var.set("Loading cover…")
        if book.key in self._inflight:
            return
        self._inflight.add(book.key)
        w, h, pad = self._mat

        def work() -> None:
            try:
                from PIL import Image

                raw = smtv_books.fetch_cover(book)
                fitted = _fit_on_mat(Image.open(io.BytesIO(raw)), w, h, pad)
                error = ""
            except offline.OfflineModeError:
                fitted, error = None, "Cover not available while Work offline is on."
            except Exception:  # noqa: BLE001 - any failure leaves the placeholder
                logger.debug("Book cover failed: %s", book.cover_url, exc_info=True)
                fitted, error = None, "Cover not available. Check the internet connection."
            self._post(lambda: self._cover_ready(book, fitted, error))

        try:
            self._submit(work)
        except RuntimeError:       # the tab's pool was shut down with the window
            self._inflight.discard(book.key)

    def _cover_ready(self, book: Book, image: Any, error: str) -> None:
        self._inflight.discard(book.key)
        try:
            if not self.winfo_exists():
                return
            if image is not None:
                from PIL import ImageTk

                self._photos[book.key] = ImageTk.PhotoImage(image, master=self)
            if self.book is not book:
                return          # another book was chosen meanwhile; its own result is kept
            if image is not None:
                self._set_image(self._photos[book.key])
                self.cover_state = "cover"
                self.note_var.set("")
            else:
                self.cover_state = "placeholder"
                self.note_var.set(error)
        except tk.TclError:
            logger.debug("Could not show the book cover", exc_info=True)
