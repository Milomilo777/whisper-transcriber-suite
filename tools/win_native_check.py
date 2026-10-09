"""Manual check of the Windows title bar / border theme (card C2.75): one small Tk window.

Opens ONE window drawn with the app's theme code (sv_ttk + ``app.theme.win_chrome``), switches it
light -> dark -> light, opens a dialog after each switch, and prints what Windows answered for
every DWM attribute. It never writes the Windows theme setting, the display scale or any other
desktop-wide value, and it does not start the app.

Run from the repo root:
    python tools/win_native_check.py                  # 4 s per step (time for a screenshot)
    python tools/win_native_check.py --hold 8
    python tools/win_native_check.py --watch 60       # then print live changes of the Windows
                                                      # app theme for 60 s (flip it in Settings)
    python tools/win_native_check.py --hidden --hold 0   # self-test, nothing shown
    python tools/win_native_check.py --kill-switch    # same run with the kill switch on: no DWM
                                                      # call must be printed

Output lines: ``step``, ``attr`` (attribute number, HRESULT, 0 = accepted), ``readback`` (the dark
flag as DWM reports it, 1 = dark) and ``watch`` (system theme changes).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.theme import system_appearance, theme_colours, win_chrome  # noqa: E402

ATTR_NAMES = {
    win_chrome.DWMWA_USE_IMMERSIVE_DARK_MODE: "dark mode (20)",
    win_chrome.DWMWA_USE_IMMERSIVE_DARK_MODE_OLD: "dark mode, old number (19)",
    win_chrome.DWMWA_CAPTION_COLOR: "caption colour (35)",
    win_chrome.DWMWA_BORDER_COLOR: "border colour (34)",
    win_chrome.DWMWA_TEXT_COLOR: "text colour (36)",
}


def _pump(root: tk.Misc, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


def _report(root: tk.Misc, label: str, windows: dict[str, tk.Misc]) -> None:
    print(f"step: {label}", flush=True)
    for name, win in windows.items():
        try:
            results = win_chrome.apply(win, label)   # re-applies; same call the app makes
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: apply raised {exc!r}", flush=True)
            continue
        if not results:
            print(f"  {name}: no DWM call made (not Windows, kill switch, or no handle)", flush=True)
            continue
        for attr, hresult in results.items():
            print(f"  {name}: attr {ATTR_NAMES.get(attr, attr)} hresult={hresult & 0xFFFFFFFF:#010x}",
                  flush=True)
        try:
            hwnd = win_chrome.window_handle(win)
            code, value = win_chrome._native().get_attribute(hwnd, win_chrome.DWMWA_USE_IMMERSIVE_DARK_MODE)
            print(f"  {name}: readback dark flag={value} (hresult={code & 0xFFFFFFFF:#010x})", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: readback failed {exc!r}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hold", type=float, default=4.0, help="seconds to show each step")
    parser.add_argument("--watch", type=float, default=0.0, help="then watch the Windows app theme for N seconds")
    parser.add_argument("--hidden", action="store_true",
                        help="keep the windows withdrawn (a self-test with nothing on the desktop)")
    parser.add_argument("--kill-switch", action="store_true", help="run with the kill switch on")
    args = parser.parse_args()

    if args.kill_switch:
        os.environ[win_chrome.ENV_KILL_SWITCH] = "1"
    print(f"platform={sys.platform} build={win_chrome.windows_build()} "
          f"enabled={win_chrome.enabled()}", flush=True)
    backend = system_appearance.get_backend()
    print(f"system app theme: dark={backend.is_dark()} (backend {type(backend).__name__})", flush=True)

    root = tk.Tk()
    root.title("win_native_check")
    root.geometry("420x160+200+200")
    if args.hidden:
        root.withdraw()
    try:
        import sv_ttk
    except ImportError:
        print("sv_ttk missing: install requirements.txt", flush=True)
        return 2
    dialogs: list[tk.Toplevel] = []
    try:
        sv_ttk.set_theme("light")
        theme_colours.apply(root, "light")
        win_chrome.install(root, "light")
        ttk.Label(root, text="Title bar check: look at the frame, not the body.").pack(padx=16, pady=24)
        windows: dict[str, tk.Misc] = {"main": root}
        _pump(root, 0.3)
        _report(root, "light", windows)
        _pump(root, args.hold)

        for theme in ("dark", "light"):
            sv_ttk.set_theme(theme)
            theme_colours.apply(root, theme)
            n = win_chrome.apply_all(root, theme)
            print(f"step: switched to {theme}; apply_all themed {n} window(s)", flush=True)
            dlg = tk.Toplevel(root)       # a dialog created AFTER the switch
            dlg.title(f"dialog opened in {theme}")
            dlg.geometry("320x100+700+260")
            if args.hidden:
                dlg.withdraw()
            ttk.Label(dlg, text=f"Opened after the switch to {theme}").pack(padx=12, pady=24)
            dialogs.append(dlg)
            windows = {"main": root, f"dialog-{theme}": dlg}
            _pump(root, 0.3)
            _report(root, theme, windows)
            _pump(root, args.hold)

        if args.watch > 0:
            changes: list[str] = []
            watcher = system_appearance.SystemThemeWatcher(
                root, lambda: changes.append("changed"))
            watcher.start()
            print(f"watch: change the Windows app theme now ({args.watch:.0f} s)", flush=True)
            end = time.monotonic() + args.watch
            seen = 0
            while time.monotonic() < end:
                root.update()
                time.sleep(0.05)
                if len(changes) > seen:
                    seen = len(changes)
                    dark = backend.is_dark()
                    print(f"watch: Windows app theme changed -> dark={dark} "
                          f"(resolve_theme says {system_appearance.resolve_theme('system')})", flush=True)
            watcher.stop()
            print(f"watch: done, {seen} change(s) seen", flush=True)
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
