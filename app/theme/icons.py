"""One icon family for the whole UI: Lucide, rasterised to PNG at dev time.

The PNGs under ``assets/icons`` are black with an alpha channel at two logical sizes and four
display scales (1x, 1.25x, 1.5x, 2x).  ``load_icon`` picks the file nearest the window's scale
and tints it to the requested colour, so one set serves the Light and Dark themes.  Regenerate
them with ``tools/build_icons.py``; the artwork and its licence live in ``tools/icons/lucide``.
"""
# Adapted from Lucide (https://github.com/lucide-icons/lucide) — icon artwork, ISC licence.
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from PIL import Image

from core.paths import resource_base

LOGICAL_SIZES = (16, 24)
SCALES = (1.0, 1.25, 1.5, 2.0)

# Every icon the UI may reference (one PNG family per name).
ICON_NAMES = (
    "chevron-right",
    "circle-check",
    "circle-question-mark",
    "circle-x",
    "clock",
    "copy",
    "download",
    "external-link",
    "file-text",
    "folder-open",
    "info",
    "languages",
    "link",
    "mic",
    "moon",
    "play",
    "plus",
    "refresh-cw",
    "search",
    "settings",
    "square",
    "sun",
    "trash",
    "triangle-alert",
    "upload",
    "x",
)


def scale_label(scale: float) -> str:
    """``1.0`` -> ``"1x"``, ``1.25`` -> ``"1.25x"`` (the file-name suffix)."""
    return f"{scale:g}x"


def icon_file_name(name: str, size: int, scale: float) -> str:
    return f"{name}-{size}@{scale_label(scale)}.png"


def icons_dir() -> str:
    """The shipped folder: ``assets/icons`` under the bundle (frozen) or the repo (source)."""
    return os.path.join(resource_base(), "assets", "icons")


def nearest_scale(scale: float) -> float:
    """The shipped scale closest to ``scale`` (rounded up on a tie, so icons stay sharp)."""
    return min(SCALES, key=lambda s: (abs(s - scale), -s))


def icon_path(name: str, size: int = 16, scale: float = 1.0) -> str:
    if name not in ICON_NAMES:
        raise KeyError(f"unknown icon {name!r}")
    if size not in LOGICAL_SIZES:
        raise ValueError(f"icon size must be one of {LOGICAL_SIZES}, got {size}")
    return os.path.join(icons_dir(), icon_file_name(name, size, nearest_scale(scale)))


def tint(image: Image.Image, color: str) -> Image.Image:
    """Paint every pixel ``color`` (``"#rrggbb"``) and keep the image's own alpha."""
    rgba = image.convert("RGBA")
    solid = Image.new("RGBA", rgba.size, color)
    solid.putalpha(rgba.getchannel("A"))
    return solid


@lru_cache(maxsize=256)
def _tinted(path: str, color: str) -> Image.Image:
    with Image.open(path) as src:
        return tint(src, color)


def load_icon(widget: Any, name: str, color: str, size: int = 16) -> Any:
    """A Tk ``PhotoImage`` of icon ``name`` in ``color``, sharp at this window's display scale.

    Keep a reference to the result (``label.image = photo``); Tk drops images that are not
    referenced from Python.
    """
    from PIL import ImageTk

    from app.dpi import scale_factor

    path = icon_path(name, size, scale_factor(widget))
    return ImageTk.PhotoImage(_tinted(path, color), master=widget)
