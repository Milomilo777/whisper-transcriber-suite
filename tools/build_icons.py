"""Rasterise the Lucide SVG sources into the PNG icon set under ``assets/icons``.

Dev-time only: the app never imports this and PyMuPDF is NOT a runtime dependency
(``pip install pymupdf`` on the machine that regenerates the set).  Re-run after adding an
SVG to ``tools/icons/lucide`` or changing ``SCALES`` / ``LOGICAL_SIZES`` in ``app/theme/icons.py``:

    python tools/build_icons.py

Every PNG is black with an alpha channel; the app tints it to a theme colour at run time
(``app.theme.icons.load_icon``), so one set serves light and dark.
"""
# Adapted from Lucide (https://github.com/lucide-icons/lucide) — SVG artwork rasterised here (ISC licence).
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.theme.icons import LOGICAL_SIZES, SCALES, icon_file_name  # noqa: E402

SVG_DIR = REPO / "tools" / "icons" / "lucide"
OUT_DIR = REPO / "assets" / "icons"
SVG_VIEWBOX = 24  # Lucide icons are drawn on a 24 x 24 grid


def main() -> int:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF, dev-time only

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for svg in sorted(SVG_DIR.glob("*.svg")):
        source = svg.read_text(encoding="utf-8").replace("currentColor", "#000000")
        doc = fitz.open(stream=source.encode("utf-8"), filetype="svg")
        page = doc[0]
        for size in LOGICAL_SIZES:
            for scale in SCALES:
                pixels = round(size * scale)
                zoom = pixels / SVG_VIEWBOX
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
                pix.save(str(OUT_DIR / icon_file_name(svg.stem, size, scale)))
                count += 1
        doc.close()
    print(f"wrote {count} PNG files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
