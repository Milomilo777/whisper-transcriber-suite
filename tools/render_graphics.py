"""Render the README / social graphics from tools/graphics/graphics.html.

Needs Google Chrome (headless). Writes:
    docs/img/hero.png            1280x460   README banner
    docs/img/features.png        1280x500   README "what's inside"
    docs/img/how-it-works.png    1360x520   README architecture strip
    docs/img/social-preview.png  1280x640   GitHub repo social preview (upload in
                                             Settings -> Social preview; keep < 1 MB)

    python tools/render_graphics.py [hero features flow social]

Replaces the Pillow-drawn banners from tools/make_graphics.py, which still
handles trimming the raw app screenshots.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools" / "graphics" / "graphics.html"
BOARDS = {
    "hero": ("hero.png", 1280, 460),
    "features": ("features.png", 1280, 500),
    "flow": ("how-it-works.png", 1360, 520),
    "social": ("social-preview.png", 1280, 640),
}
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium",
]


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c) or shutil.which(c):
            return c
    raise SystemExit("Google Chrome not found")


def render(name: str) -> None:
    out, w, h = BOARDS[name]
    dest = ROOT / "docs" / "img" / out
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([chrome(), "--headless=new", f"--user-data-dir={profile}", "--hide-scrollbars",
                        "--allow-file-access-from-files", "--force-device-scale-factor=1",
                        f"--window-size={w},{h}", "--virtual-time-budget=3000",
                        f"--screenshot={dest}", PAGE.as_uri() + f"?view={name}"],
                       check=True, capture_output=True)
    print(f"{dest.relative_to(ROOT)}  {dest.stat().st_size // 1024} KB")


def main() -> int:
    names = sys.argv[1:] or list(BOARDS)
    for n in names:
        render(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
