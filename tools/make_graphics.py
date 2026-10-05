#!/usr/bin/env python3
"""Regenerate the repository's presentation graphics into docs/img/.

Everything is drawn from scratch with Pillow, so the banner, the social preview
card and the explainer diagrams stay editable text rather than binary blobs
nobody can touch after a rename or a palette change.

    python tools/make_graphics.py             # rebuild the generated assets
    python tools/make_graphics.py --frames    # also trim docs/img/raw-*.png

The screenshots are real captures of the running app; --frames only trims the
invisible Windows resize border off them and rounds the corners.

Palette is taken from the app icon (assets/whisper.png): teal #207a80 on white.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "img")
ICON = os.path.join(ROOT, "assets", "whisper.png")

BG = (15, 20, 25)
PANEL = (23, 30, 37)
PANEL_HI = (31, 40, 49)
LINE = (52, 66, 76)
TEXT = (233, 240, 243)
MUTED = (140, 156, 165)
BRAND = (32, 122, 128)        # #207a80 - the icon's teal
ACCENT = (61, 209, 202)       # brighter teal for highlights on dark
WARM = (240, 178, 92)         # single warm accent, used sparingly

FONTS = {
    "bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "reg": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"],
}
_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu",
              "/Library/Fonts", "/System/Library/Fonts"]


def font(kind: str, size: int):
    for name in FONTS[kind]:
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def text_w(d: ImageDraw.ImageDraw, s: str, f) -> int:
    return int(d.textbbox((0, 0), s, font=f)[2])


def tracked(d, xy, s, f, fill, spacing=0):
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textbbox((0, 0), ch, font=f)[2] + spacing
    return x


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1],
                                           radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def backdrop(w: int, h: int) -> Image.Image:
    """Dark card with a teal glow - legible on both GitHub themes."""
    img = Image.new("RGB", (w, h), BG)
    glow = Image.new("RGB", (w, h), BG)
    g = ImageDraw.Draw(glow)
    g.ellipse([w * 0.52, -h * 0.5, w * 1.2, h * 0.9], fill=(18, 62, 66))
    g.ellipse([-w * 0.18, h * 0.5, w * 0.30, h * 1.6], fill=(16, 44, 52))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(95)), 0.92)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 4):
        d.line([(0, y), (w, y)], fill=(int(BG[0] * 1.14), int(BG[1] * 1.14), int(BG[2] * 1.14)))
    return img


def chip(d, x, y, label, f, fg=MUTED, bg=PANEL_HI, border=LINE, pad=11, hgt=27):
    w = text_w(d, label, f) + pad * 2
    d.rounded_rectangle([x, y, x + w, y + hgt], radius=hgt // 2, fill=bg, outline=border)
    d.text((x + pad, y + (hgt - f.size) // 2 - 1), label, font=f, fill=fg)
    return x + w + 8


def app_icon(size: int) -> Image.Image | None:
    if not os.path.exists(ICON):
        return None
    return Image.open(ICON).convert("RGBA").resize((size, size), LANCZOS)


# --------------------------------------------------------------------------- #
#  The core motif: a waveform that becomes timed caption lines
# --------------------------------------------------------------------------- #
def _bar_height(i: int) -> float:
    """Deterministic pseudo-waveform in 0..1 - no RNG, so builds reproduce."""
    v = (math.sin(i * 0.63) * 0.5 + 0.5) * (math.sin(i * 0.21 + 1.1) * 0.35 + 0.65)
    return 0.14 + 0.86 * abs(v)


def draw_waveform(d, x, y, w, h, bars=46, color=ACCENT, dim=0.0):
    step = w / bars
    bw = max(2, int(step * 0.45))
    for i in range(bars):
        bh = max(3, int(_bar_height(i) * h))
        cx = int(x + i * step)
        cy = int(y + h / 2)
        c = color
        if dim:
            c = tuple(int(v * (1 - dim) + BG[j] * dim) for j, v in enumerate(color))
        d.rounded_rectangle([cx, cy - bh // 2, cx + bw, cy + bh // 2],
                            radius=bw // 2, fill=c)


CAPTIONS = [
    ("00:00:01,120", (0.92, 0.55)),
    ("00:00:04,880", (0.78, 0.86)),
    ("00:00:09,300", (0.86, 0.42)),
]


def draw_captions(d, x, y, w, line_h=13, block_gap=26, stamp_font=None, limit=None):
    """Caption blocks: a timestamp plus two grey 'text' bars each."""
    cy = y
    for stamp, widths in CAPTIONS[:limit]:
        if stamp_font is not None:
            d.text((x, cy), stamp, font=stamp_font, fill=ACCENT)
            cy += stamp_font.size + 9
        for frac in widths:
            d.rounded_rectangle([x, cy, x + int(w * frac), cy + line_h],
                                radius=line_h // 2, fill=(58, 72, 82))
            cy += line_h + 6
        cy += block_gap
    return cy - block_gap


def arrow(d, x, y, length, color=(96, 116, 126), width=2):
    d.line([(x, y), (x + length - 11, y)], fill=color, width=width)
    d.polygon([(x + length - 11, y - 6), (x + length - 11, y + 6), (x + length, y)], fill=color)


# --------------------------------------------------------------------------- #
#  1. Banner
# --------------------------------------------------------------------------- #
def build_hero(path: str, w=1280, h=460):
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)

    x = 76
    ic = app_icon(64)
    if ic:
        img.paste(ic, (x, 92), ic)
    tx = x + (84 if ic else 0)
    tracked(d, (tx, 104), "WHISPER", font("bold", 44), TEXT, spacing=2)
    tracked(d, (tx, 148), "PROJECT", font("bold", 44), ACCENT, spacing=2)

    d.text((x, 216), "Transcribe audio and video", font=font("reg", 26), fill=TEXT)
    d.text((x, 250), "on your own machine.", font=font("reg", 26), fill=TEXT)
    d.text((x, 292), "No cloud. No account. No upload.", font=font("semi", 26), fill=ACCENT)

    f = font("reg", 15)
    cx = x
    for c in ("Windows", "Drag & drop", "SRT · VTT · DOCX · PDF", "Speaker labels"):
        cx = chip(d, cx, 346, c, f)

    # Right: waveform -> captions.
    px, py, pw, ph = 700, 118, 500, 230
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=14, fill=PANEL, outline=LINE)
    draw_waveform(d, px + 30, py + 46, 178, 92)
    d.text((px + 30, py + 156), "audio in", font=font("mono", 13), fill=(104, 122, 132))
    arrow(d, px + 224, py + 92, 44)
    end = draw_captions(d, px + 292, py + 40, 172, stamp_font=font("mono", 12), limit=2)
    d.text((px + 292, end + 14), "timed transcript out", font=font("mono", 13),
           fill=(104, 122, 132))

    img.save(path)
    print("wrote", path)


# --------------------------------------------------------------------------- #
#  2. Social preview card (GitHub renders shares at 1280x640)
# --------------------------------------------------------------------------- #
def build_social(path: str, w=1280, h=640):
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)

    x = 92
    ic = app_icon(76)
    if ic:
        img.paste(ic, (x, 150), ic)
    tracked(d, (x + (98 if ic else 0), 158), "WHISPER", font("bold", 52), TEXT, spacing=2)
    tracked(d, (x + (98 if ic else 0), 210), "PROJECT", font("bold", 52), ACCENT, spacing=2)

    d.text((x, 292), "Offline speech-to-text", font=font("reg", 30), fill=TEXT)
    d.text((x, 330), "for Windows.", font=font("semi", 30), fill=ACCENT)

    f = font("reg", 18)
    for i, line in enumerate(("Drag a file in - get SRT, VTT, DOCX, PDF and more",
                              "Runs on your machine; nothing is uploaded",
                              "Speaker labels, word timestamps, batch queue")):
        d.ellipse([x + 2, 400 + i * 36, x + 11, 409 + i * 36], fill=BRAND)
        d.text((x + 26, 392 + i * 36), line, font=f, fill=MUTED)

    d.text((x, 528), "faster-whisper  ·  Python  ·  BSD-3", font=font("mono", 17),
           fill=(100, 118, 128))

    px, py, pw, ph = 742, 196, 446, 250
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=14, fill=PANEL, outline=LINE)
    draw_waveform(d, px + 28, py + 52, 152, 104)
    d.text((px + 28, py + 176), "audio in", font=font("mono", 13), fill=(104, 122, 132))
    arrow(d, px + 196, py + 104, 42)
    end = draw_captions(d, px + 258, py + 52, 156, stamp_font=font("mono", 12), limit=2)
    d.text((px + 258, end + 14), "timed transcript out", font=font("mono", 13),
           fill=(104, 122, 132))

    img.save(path)
    print("wrote", path)


# --------------------------------------------------------------------------- #
#  3. How it works
# --------------------------------------------------------------------------- #
def build_flow(path: str, w=1360, h=520):
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)
    d.text((56, 40), "How it works", font=font("bold", 30), fill=TEXT)
    d.text((56, 82), "The model runs in a worker process on your machine. "
                     "Nothing leaves it.", font=font("reg", 18), fill=MUTED)

    lock = "offline by default"
    fl = font("mono", 15)
    lw = text_w(d, lock, fl) + 24
    d.rounded_rectangle([w - 56 - lw, 78, w - 56, 108], radius=15,
                        fill=(20, 52, 54), outline=(38, 92, 96))
    d.text((w - 56 - lw + 12, 85), lock, font=fl, fill=ACCENT)

    boxes = [
        ("Drop a file", "audio or video\nor a yt-dlp URL"),
        ("Tk GUI", "queues the job,\nshows progress"),
        ("Worker process", "holds the model\nin memory"),
        ("faster-whisper", "transcribe, then\ndiarise if asked"),
        ("Your folder", "srt vtt txt json\ndocx pdf lrc md"),
    ]
    bw, bh, gap, y0 = 216, 122, 34, 168
    fx = 56
    for i, (title, sub) in enumerate(boxes):
        x = fx + i * (bw + gap)
        last = i == len(boxes) - 1
        d.rounded_rectangle([x, y0, x + bw, y0 + bh], radius=12,
                            fill=PANEL_HI if last else PANEL, outline=LINE)
        d.rectangle([x, y0 + 12, x + 3, y0 + 42], fill=ACCENT if last else BRAND)
        d.text((x + 18, y0 + 18), title, font=font("semi", 19), fill=TEXT)
        d.multiline_text((x + 18, y0 + 52), sub, font=font("mono", 14), fill=MUTED, spacing=5)
        if not last:
            arrow(d, x + bw + 8, y0 + bh // 2, gap - 16)

    # The IPC detail, drawn as a caption under the two middle boxes.
    a = fx + (bw + gap) * 1 + bw // 2
    b = fx + (bw + gap) * 2 + bw // 2
    d.line([(a, y0 + bh + 18), (a, y0 + bh + 34), (b, y0 + bh + 34), (b, y0 + bh + 18)],
           fill=(72, 90, 100), width=2)
    cap = "newline-delimited JSON over stdin/stdout  ·  UUID token + 5 s heartbeat"
    fc = font("mono", 14)
    d.text(((a + b) // 2 - text_w(d, cap, fc) // 2, y0 + bh + 44), cap, font=fc,
           fill=(104, 122, 132))

    # Bottom strip: what comes out.
    sy = 400
    d.text((56, sy), "Every run writes the formats you ticked, next to your input file:",
           font=font("reg", 17), fill=MUTED)
    fx2 = 56
    ff = font("mono", 15)
    for ext in ("srt", "vtt", "tsv", "txt", "json", "lrc", "md", "docx", "pdf"):
        fx2 = chip(d, fx2, sy + 34, ext, ff, fg=TEXT, bg=(24, 48, 50), border=(38, 84, 88))
    img.save(path)
    print("wrote", path)


# --------------------------------------------------------------------------- #
#  4. Feature grid
# --------------------------------------------------------------------------- #
def build_features(path: str, w=1280, h=470):
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)
    d.text((56, 40), "Five tabs, one window", font=font("bold", 30), fill=TEXT)
    d.text((56, 82), "Everything below runs locally unless you deliberately "
                     "switch on a cloud backend.", font=font("reg", 18), fill=MUTED)

    cards = [
        ("Transcribe", "Drag files in. Language auto-detect,\nspeaker labels, word timestamps,\ntime-range clipping."),
        ("Transcription Queue", "Batch jobs with live progress.\nPause, resume, cancel, re-run\nor remove any row."),
        ("Download Videos", "Any yt-dlp site. Pick a format,\nclip a range, grab subtitles,\nauto-transcribe when done."),
        ("Web / LAN access", "One button turns the machine\ninto a transcription page for\nphones and PCs on your network."),
        ("Convert transcript", "Re-emit any existing transcript\ninto oTranscribe, ELAN,\nInqScribe or Express Scribe."),
    ]
    cw, ch, gx, gy = 380, 148, 26, 20
    x0, y0 = 56, 140
    for i, (title, body) in enumerate(cards):
        cx = x0 + (i % 3) * (cw + gx)
        cy = y0 + (i // 3) * (ch + gy)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=12, fill=PANEL, outline=LINE)
        d.rectangle([cx, cy + 14, cx + 3, cy + 40], fill=BRAND)
        d.text((cx + 18, cy + 16), title, font=font("semi", 19), fill=TEXT)
        d.multiline_text((cx + 18, cy + 52), body, font=font("reg", 15), fill=MUTED, spacing=6)
    img.save(path)
    print("wrote", path)


# --------------------------------------------------------------------------- #
#  5. Trim the real screenshots
# --------------------------------------------------------------------------- #
def trim_screenshot(src: str, dst: str, border: int = 7):
    """GetWindowRect includes an invisible resize border on Windows 10/11; drop
    it so the shot carries no slice of whatever was behind the window."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    img = rounded(img.crop((border, 0, w - border, h - border)), 8)
    img.save(dst)
    print("wrote", dst, img.size)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", action="store_true",
                    help="also trim the docs/img/raw-*.png captures")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    build_hero(os.path.join(OUT, "hero.png"))
    build_social(os.path.join(OUT, "social-preview.png"))
    build_flow(os.path.join(OUT, "how-it-works.png"))
    build_features(os.path.join(OUT, "features.png"))
    if a.frames:
        for name in sorted(os.listdir(OUT)):
            if name.startswith("raw-") and name.endswith(".png"):
                trim_screenshot(os.path.join(OUT, name),
                                os.path.join(OUT, name[len("raw-"):]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
