#!/usr/bin/env python3
"""Probe which native macOS hooks the bundled Tk/Python really supports.

Run it on a Mac with the Python and Tk the app is built with, from a Terminal
or a desktop session (Aqua needs a window server)::

    python tools/mac_native_probe.py [--hold SECONDS] [--flip-appearance]

It prints the Tk patch level, then one line per hook::

    PASS|FAIL|INFO <hook>: <detail>

and exits 0 when every hook the app uses passes (``USED_BY_APP``; 2 when this is
not Aqua). The macOS
native-integration code (``app/mac_native.py``) is built only on hooks this
probe proves. Standard library plus tkinter only; the native menu bar is read
back through the Objective-C runtime with ``ctypes`` so no check relies on a
person looking at the screen.

Hooks (Tk 8.6 "macOS specific" documentation, ``menu`` and ``wm`` manual pages;
the ``::tk::mac::*`` commands are the ones in the Tk source ``tkMacOSXHLEvents.c``
and ``tkMacOSXMenu.c``):

* ``tk::mac::ShowPreferences`` - the app menu's Preferences item.
* ``tkAboutDialog`` / ``tk::mac::standardAboutPanel`` - the About item.
* ``tk::mac::OpenDocument`` - Finder "Open With", drops on the Dock icon.
* ``tk::mac::ReopenApplication`` - a click on the Dock icon.
* ``tk::mac::ShowHelp`` - the "<App> Help" item Tk adds to a ``.help`` menu.
* special menus ``.window``, ``.help`` and ``.apple`` on the menu bar.
* a Dock menu (the application delegate's ``applicationDockMenu:``).
* ``wm attributes -modified`` and ``-titlepath``.
* system appearance (card C2.73): ``tk::unsupported::MacWindowStyle isdark``, the
  ``<<LightAqua>>`` / ``<<DarkAqua>>`` virtual events (``<<TkSystemAppearanceChanged>>`` is
  bound too and reported, not assumed), and the system font names Tk reports. The events can only
  be proved by flipping the real Light/Dark setting, which changes the person's desktop, so that
  part runs only with ``--flip-appearance``; it restores the original setting in a ``finally``
  step and prints both values.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from typing import Any, Callable, Sequence

_results: list[tuple[str, str, str]] = []

# The hooks app/mac_native.py relies on. The others (apple_menu, dock_menu) are
# reported honestly but the app does not use them, so they do not fail the run.
USED_BY_APP = (
    "special_menus", "show_preferences", "show_preferences_createcommand", "about",
    "show_help", "open_document", "reopen_application", "window_menu", "help_menu",
    "window_attributes", "appearance_isdark", "appearance_events", "system_font_name",
)


def _report(status: str, hook: str, detail: str) -> None:
    _results.append((status, hook, detail))
    print(f"{status} {hook}: {detail}", flush=True)


# ---------------------------------------------------------------- Objective-C

class _ObjC:
    """The few Objective-C calls the probe needs (fixed arguments only)."""

    def __init__(self) -> None:
        path = ctypes.util.find_library("objc")
        if not path:
            raise OSError("libobjc not found")
        self._lib = ctypes.PyDLL(path)
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        self._lib.objc_getClass.restype = ctypes.c_void_p
        self._lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self._lib.sel_registerName.restype = ctypes.c_void_p
        self._lib.sel_registerName.argtypes = [ctypes.c_char_p]

    def cls(self, name: str) -> int:
        return self._lib.objc_getClass(name.encode()) or 0

    def msg(self, obj: int, sel: str, *args: Any, restype: Any = ctypes.c_void_p,
            argtypes: tuple[Any, ...] = ()) -> Any:
        # PYFUNCTYPE keeps the GIL: a menu action runs Tcl and so Python callbacks
        # on this same thread before objc_msgSend returns.
        fn = ctypes.PYFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(
            ("objc_msgSend", self._lib))
        return fn(obj, self._lib.sel_registerName(sel.encode()), *args)

    def string(self, nsstring: int) -> str:
        if not nsstring:
            return ""
        raw = self.msg(nsstring, "UTF8String", restype=ctypes.c_char_p)
        return raw.decode("utf-8", "replace") if raw else ""

    def count(self, obj: int) -> int:
        return int(self.msg(obj, "count", restype=ctypes.c_long)) if obj else 0

    def items(self, menu: int) -> list[tuple[int, str, bool]]:
        """``(item, title, enabled)`` for every entry of an NSMenu."""
        out: list[tuple[int, str, bool]] = []
        if not menu:
            return out
        for i in range(int(self.msg(menu, "numberOfItems", restype=ctypes.c_long))):
            item = self.msg(menu, "itemAtIndex:", i, argtypes=(ctypes.c_long,))
            title = self.string(self.msg(item, "title"))
            if int(self.msg(item, "isSeparatorItem", restype=ctypes.c_byte)):
                title = "-"
            enabled = bool(self.msg(item, "isEnabled", restype=ctypes.c_byte))
            out.append((item, title, enabled))
        return out

    def app(self) -> int:
        return self.msg(self.cls("NSApplication"), "sharedApplication")


def _pump(root: tk.Tk, seconds: float, until: Callable[[], bool] | None = None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        if until is not None and until():
            return
        time.sleep(0.03)


def _find(items: list[tuple[int, str, bool]], *prefixes: str) -> tuple[int, str, bool] | None:
    for entry in items:
        low = entry[1].lower().replace(chr(0x2026), "...")
        if any(low.startswith(p.lower()) for p in prefixes):
            return entry
    return None


# --------------------------------------------------------------------- probes

def _main_menu_titles(oc: _ObjC) -> list[tuple[int, str, bool]]:
    return oc.items(oc.msg(oc.app(), "mainMenu"))


def _submenu(oc: _ObjC, title: str) -> list[tuple[int, str, bool]]:
    for item, name, _enabled in _main_menu_titles(oc):
        if name == title:
            return oc.items(oc.msg(item, "submenu"))
    return []


def build_probe_menubar(root: tk.Tk) -> bool:
    """The menu bar, attached before the window is first shown (as the app does:
    Tk fills the special menus when its window first becomes active)."""
    menubar = tk.Menu(root)
    root.configure(menu=menubar)
    file_menu = tk.Menu(menubar, tearoff=0)
    file_menu.add_command(label="Probe item")
    menubar.add_cascade(label="File", menu=file_menu)
    try:
        apple = tk.Menu(menubar, name="apple", tearoff=0)
        apple.add_command(label="Probe about")
        menubar.add_cascade(menu=apple)
        window = tk.Menu(menubar, name="window", tearoff=0)
        menubar.add_cascade(label="Window", menu=window)
        help_menu = tk.Menu(menubar, name="help", tearoff=0)
        help_menu.add_command(label="Probe help item")
        menubar.add_cascade(label="Help", menu=help_menu)
    except tk.TclError as exc:
        _report("FAIL", "special_menus", f"creating .apple/.window/.help raised {exc}")
        return False
    return True


def probe_menus_and_app_menu(root: tk.Tk, oc: _ObjC, events: dict[str, list[Any]]) -> None:
    """Special menus (.window, .help, .apple) read back from NSApp."""
    top = _main_menu_titles(oc)
    _report("INFO", "main_menu", " | ".join(repr(t) for _i, t, _e in top))

    # .apple: documented as entries of the app menu. The app does not use it.
    app_items = oc.items(oc.msg(top[0][0], "submenu")) if top else []
    _report("INFO", "app_menu", " | ".join(t for _i, t, _e in app_items))
    merged = _find(app_items, "Probe about") is not None
    _report("PASS" if merged else "FAIL", "apple_menu",
            "entries of the .apple menu appear in the app menu" if merged else
            "entries of the .apple menu are NOT merged into the app menu "
            "(they show as an extra top-level menu with an empty title)")

    # .window: Minimize / Zoom / Bring All to Front come from macOS itself.
    wtitles = [t for _i, t, _e in _submenu(oc, "Window")]
    _report("INFO", "window_menu_items", " | ".join(wtitles) or "(none)")
    missing = [n for n in ("Minimize", "Zoom", "Bring All to Front")
               if not any(t.startswith(n) for t in wtitles)]
    _report("PASS" if wtitles and not missing else "FAIL", "window_menu",
            "Window menu has Minimize, Zoom, Bring All to Front and lists the windows"
            if wtitles and not missing else f"missing {missing or 'the Window menu'}")

    # .help: Tk adds "<App> Help" and macOS adds its search field to the menu
    # titled exactly "Help" (a title with a trailing dot symbol loses the search field).
    htitles = [t for _i, t, _e in _submenu(oc, "Help")]
    _report("INFO", "help_menu_items", " | ".join(htitles) or "(none)")
    ok = any(t.endswith("Help") for t in htitles) and "Probe help item" in htitles
    _report("PASS" if ok else "FAIL", "help_menu",
            "special .help menu: Tk added its '<App> Help' item next to the app's items"
            if ok else "the .help menu was not recognised as the Help menu")


def _tcl_events(root: tk.Tk) -> list[str]:
    return list(root.tk.splitlist(root.tk.eval("set ::probe_events")))


def probe_preferences(root: tk.Tk, oc: _ObjC, events: dict[str, list[Any]]) -> None:
    # A plain Tcl proc: the menu action runs it synchronously inside the ctypes
    # call, where a Python callback would find no interpreter state. The app
    # registers a Python command with createcommand, which Tk runs from the
    # event loop exactly like this proc.
    root.tk.eval("proc ::tk::mac::ShowPreferences {} {lappend ::probe_events prefs}")
    root.update()
    app = oc.app()
    top = oc.items(oc.msg(app, "mainMenu"))
    app_menu = oc.msg(top[0][0], "submenu") if top else 0
    items = oc.items(app_menu)
    pref = _find(items, "Preferences", "Settings")
    if not pref:
        _report("FAIL", "show_preferences", "no Preferences/Settings item in the app menu")
        return
    if not pref[2]:
        _report("FAIL", "show_preferences", f"item '{pref[1]}' exists but is disabled")
        return
    index = [i for i, entry in enumerate(items) if entry[0] == pref[0]][0]
    oc.msg(app_menu, "performActionForItemAtIndex:", index, argtypes=(ctypes.c_long,))
    _pump(root, 3.0, lambda: "prefs" in _tcl_events(root))
    ok = "prefs" in _tcl_events(root)
    _report("PASS" if ok else "FAIL", "show_preferences",
            f"app menu item '{pref[1]}' enabled and ran tk::mac::ShowPreferences"
            if ok else f"item '{pref[1]}' ran nothing")
    key = oc.string(oc.msg(pref[0], "keyEquivalent"))
    _report("INFO", "show_preferences_key", f"key equivalent '{key}'")
    root.createcommand("::tk::mac::ShowPreferences", lambda: events["prefs"].append(1))
    kind = "python command" if not root.tk.call("info", "procs", "::tk::mac::ShowPreferences") else "proc"
    _report("PASS" if kind == "python command" else "FAIL", "show_preferences_createcommand",
            f"createcommand replaced the proc ({kind})")


def probe_about(root: tk.Tk, oc: _ObjC, events: dict[str, list[Any]]) -> None:
    root.tk.eval("proc tkAboutDialog {} {lappend ::probe_events about}")
    root.update()
    app = oc.app()
    top = oc.items(oc.msg(app, "mainMenu"))
    app_menu = oc.msg(top[0][0], "submenu") if top else 0
    items = oc.items(app_menu)
    about = _find(items, "About")
    if not about:
        _report("FAIL", "about", "no About item in the app menu")
        return
    index = [i for i, entry in enumerate(items) if entry[0] == about[0]][0]
    oc.msg(app_menu, "performActionForItemAtIndex:", index, argtypes=(ctypes.c_long,))
    _pump(root, 3.0, lambda: "about" in _tcl_events(root))
    ok = "about" in _tcl_events(root)
    _report("PASS" if ok else "FAIL", "about",
            f"app menu item '{about[1]}' ran the tkAboutDialog command"
            if ok else f"item '{about[1]}' did not run tkAboutDialog")
    has_panel = int(root.tk.call("info", "commands", "::tk::mac::standardAboutPanel") != "")
    _report("PASS" if has_panel else "FAIL", "standard_about_panel",
            "::tk::mac::standardAboutPanel exists" if has_panel else "command missing")


def probe_show_help(root: tk.Tk, oc: _ObjC) -> None:
    root.tk.eval("proc ::tk::mac::ShowHelp {} {lappend ::probe_events help}")
    root.update()
    help_entry = [e for e in _main_menu_titles(oc) if e[1] == "Help"]
    if not help_entry:
        _report("FAIL", "show_help", "no Help menu")
        return
    menu = oc.msg(help_entry[0][0], "submenu")
    items = oc.items(menu)
    entry = next(((i, e) for i, e in enumerate(items) if e[1].endswith("Help")), None)
    if entry is None:
        _report("FAIL", "show_help", "no '<App> Help' item in the Help menu")
        return
    oc.msg(menu, "performActionForItemAtIndex:", entry[0], argtypes=(ctypes.c_long,))
    _pump(root, 3.0, lambda: "help" in _tcl_events(root))
    ok = "help" in _tcl_events(root)
    _report("PASS" if ok else "FAIL", "show_help",
            f"'{entry[1][1]}' ran tk::mac::ShowHelp" if ok else f"'{entry[1][1]}' ran nothing")


def _bundle_path(oc: _ObjC) -> str:
    bundle = oc.msg(oc.cls("NSBundle"), "mainBundle")
    return oc.string(oc.msg(bundle, "bundlePath"))


def probe_open_document(root: tk.Tk, oc: _ObjC, events: dict[str, list[Any]]) -> None:
    root.createcommand("::tk::mac::OpenDocument", lambda *paths: events["open"].extend(paths))
    root.update()
    bundle = _bundle_path(oc)
    _report("INFO", "bundle", bundle or "(none)")
    if not bundle.endswith(".app"):
        _report("FAIL", "open_document", f"process is not an app bundle ({bundle!r}); cannot receive Apple events")
        return
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "probe.py")  # .py: Python.app declares it as a document type
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("# probe\n")
        subprocess.run(["open", "-a", bundle, target], check=False, timeout=20)
        _pump(root, 6.0, lambda: bool(events["open"]))
        got = [os.path.realpath(p) for p in events["open"]]
        ok = os.path.realpath(target) in got
        _report("PASS" if ok else "FAIL", "open_document",
                "tk::mac::OpenDocument received the file opened with `open -a`"
                if ok else f"no file received (events={events['open']!r})")


def probe_reopen(root: tk.Tk, oc: _ObjC, events: dict[str, list[Any]]) -> None:
    root.createcommand("::tk::mac::ReopenApplication", lambda: events["reopen"].append(1))
    root.update()
    bundle = _bundle_path(oc)
    if not bundle.endswith(".app"):
        _report("FAIL", "reopen_application", "process is not an app bundle")
        return
    root.iconify()
    _pump(root, 1.0)
    subprocess.run(["open", "-a", bundle], check=False, timeout=20)  # what a Dock click sends
    _pump(root, 6.0, lambda: bool(events["reopen"]))
    ok = bool(events["reopen"])
    root.deiconify()
    root.update()
    _report("PASS" if ok else "FAIL", "reopen_application",
            "tk::mac::ReopenApplication ran while the window was minimised"
            if ok else "no reopen event while the window was minimised")


def _responds(oc: _ObjC, obj: int, selector: str) -> bool:
    return bool(int(oc.msg(obj, "respondsToSelector:", oc._lib.sel_registerName(selector.encode()),
                           restype=ctypes.c_byte, argtypes=(ctypes.c_void_p,))))


def probe_dock_menu(root: tk.Tk, oc: _ObjC) -> None:
    app = oc.app()
    # Controls: the same query must say yes for a selector Tk implements and no
    # for one that does not exist, or a "no" for the Dock menu proves nothing.
    positive = _responds(oc, app, "applicationShouldHandleReopen:hasVisibleWindows:")
    negative = not _responds(oc, app, "probeNoSuchSelector:")
    if not (positive and negative):
        _report("FAIL", "dock_menu", f"selector query is unreliable (positive={positive}, negative={negative})")
        return
    delegate = oc.msg(app, "delegate")
    targets = [o for o in (app, delegate) if o]
    if any(_responds(oc, o, "applicationDockMenu:") for o in targets):
        _report("PASS", "dock_menu", "Tk's application object answers applicationDockMenu:")
        return
    _report("FAIL", "dock_menu",
            "Tk's application object (TKApplication) has no applicationDockMenu: and Tk has no "
            "Tcl command for Dock menu entries (controls ok): the app cannot add Dock menu items")


def probe_window_attributes(root: tk.Tk, oc: _ObjC) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "probe.txt")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("probe\n")
        try:
            root.wm_attributes("-modified", True)
            root.wm_attributes("-titlepath", target)
            root.update()
            got_mod = bool(int(root.wm_attributes("-modified")))
            got_path = str(root.wm_attributes("-titlepath"))
        except tk.TclError as exc:
            _report("FAIL", "window_attributes", f"wm attributes raised {exc}")
            return
        windows = oc.msg(oc.app(), "windows")
        native_edited = native_path = None
        for i in range(oc.count(windows)):
            win = oc.msg(windows, "objectAtIndex:", i, argtypes=(ctypes.c_long,))
            if oc.string(oc.msg(win, "representedFilename")) == os.path.realpath(target) or \
                    oc.string(oc.msg(win, "representedFilename")) == target:
                native_path = True
                native_edited = bool(oc.msg(win, "isDocumentEdited", restype=ctypes.c_byte))
        ok = got_mod and os.path.realpath(got_path) == os.path.realpath(target)
        native = f", native proxy icon={'yes' if native_path else 'no'}, edited dot={native_edited}"
        _report("PASS" if ok and native_path and native_edited else "FAIL", "window_attributes",
                f"-modified={got_mod}, -titlepath={got_path!r}{native}")
        root.wm_attributes("-modified", False)
        root.wm_attributes("-titlepath", "")


# ------------------------------------------------------------------ appearance

APPEARANCE_EVENTS = ("<<LightAqua>>", "<<DarkAqua>>", "<<TkSystemAppearanceChanged>>")
_DARK_MODE_GET = 'tell application "System Events" to tell appearance preferences to get dark mode'
_DARK_MODE_SET = 'tell application "System Events" to tell appearance preferences to set dark mode to {}'
SYSTEM_FONT_CANDIDATES = (".AppleSystemUIFont", "SF Pro", "SF Pro Text", "Helvetica Neue",
                          "Segoe UI Variable Text")
TK_FONT_NAMES = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont", "TkFixedFont")
# One character per script the app draws in its own font on Windows (script_fonts.py).
SCRIPT_SAMPLES = (
    ("persian", chr(0x645)), ("arabic", chr(0x639)), ("hebrew", chr(0x5D0)),
    ("han", chr(0x6F22)), ("hiragana", chr(0x3042)), ("hangul", chr(0xD55C)),
    ("thai", chr(0xE01)), ("devanagari", chr(0x915)), ("sinhala", chr(0xD9A)),
    ("myanmar", chr(0x1000)),
)


def _osascript(script: str) -> str:
    run = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if run.returncode != 0:
        raise OSError(f"osascript failed: {run.stderr.strip()}")
    return run.stdout.strip()


def system_dark_mode() -> bool | None:
    """The real Light/Dark setting as System Events reports it (None: unreadable)."""
    try:
        return {"true": True, "false": False}.get(_osascript(_DARK_MODE_GET))
    except (OSError, subprocess.SubprocessError):
        return None


def set_system_dark_mode(dark: bool) -> None:
    _osascript(_DARK_MODE_SET.format("true" if dark else "false"))


def tk_isdark(root: tk.Tk) -> bool:
    """Tk's own answer for the main window (``MacWindowStyle isdark``)."""
    return bool(int(str(root.tk.call("tk::unsupported::MacWindowStyle", "isdark", "."))))


def effective_appearance_name(oc: _ObjC) -> str:
    """``[NSApp effectiveAppearance].name``: the independent oracle for the check above."""
    appearance = oc.msg(oc.app(), "effectiveAppearance")
    return oc.string(oc.msg(appearance, "name")) if appearance else ""


def probe_appearance_static(root: tk.Tk, oc: _ObjC) -> None:
    _report("INFO", "tk_patchlevel", str(root.tk.call("info", "patchlevel")))
    try:
        dark = tk_isdark(root)
    except (tk.TclError, ValueError) as exc:
        _report("FAIL", "appearance_isdark", f"tk::unsupported::MacWindowStyle isdark raised {exc}")
        return
    name = effective_appearance_name(oc)
    native_dark = "dark" in name.lower()
    _report("PASS" if dark == native_dark else "FAIL", "appearance_isdark",
            f"isdark={int(dark)}; NSApp effectiveAppearance={name!r} "
            f"({'agrees' if dark == native_dark else 'DISAGREES'})")
    system = system_dark_mode()
    _report("INFO", "appearance_system_setting", f"System Events dark mode={system}")


def probe_appearance_events(root: tk.Tk, oc: _ObjC, flip: bool) -> None:
    """Flip the real Light/Dark setting both ways and record which virtual events Tk sends."""
    seen: list[tuple[str, bool]] = []
    for sequence in APPEARANCE_EVENTS:
        root.bind(sequence, lambda _e, s=sequence: seen.append((s, tk_isdark(root))), add="+")
    if not flip:
        _report("INFO", "appearance_events",
                "not run: needs --flip-appearance (it changes the Mac's Light/Dark setting)")
        return
    original = system_dark_mode()
    if original is None:
        _report("FAIL", "appearance_events", "cannot read the Light/Dark setting (System Events)")
        return
    _report("INFO", "appearance_original", f"dark mode={original}")
    outcomes: list[str] = []
    ok = True
    try:
        for target in (not original, original):
            seen.clear()
            set_system_dark_mode(target)
            wanted = "<<DarkAqua>>" if target else "<<LightAqua>>"
            _pump(root, 8.0, lambda: any(s == wanted for s, _d in seen))
            _pump(root, 0.5)
            fired = [s for s, _d in seen]
            dark_at_event = [d for s, d in seen if s == wanted]
            good = wanted in fired and all(d == target for d in dark_at_event)
            ok = ok and good
            outcomes.append(f"set dark={target}: events={fired or 'none'}, "
                            f"isdark at event={dark_at_event or 'n/a'}, isdark now={int(tk_isdark(root))}")
    finally:
        try:
            if system_dark_mode() != original:
                set_system_dark_mode(original)
        except (OSError, subprocess.SubprocessError) as exc:
            _report("FAIL", "appearance_restore",
                    f"COULD NOT restore dark mode={original}: {exc}")
        final = system_dark_mode()
        _report("PASS" if final == original else "FAIL", "appearance_restore",
                f"original dark mode={original}, final dark mode={final}")
    _report("PASS" if ok else "FAIL", "appearance_events", "; ".join(outcomes))


def _actual(root: tk.Tk, spec: str, *options: str) -> str:
    return " ".join(str(x) for x in root.tk.splitlist(
        root.tk.call("font", "actual", spec, "-displayof", ".", *options)))


def probe_system_fonts(root: tk.Tk) -> None:
    families = {str(f) for f in root.tk.splitlist(root.tk.call("font", "families"))}
    _report("INFO", "font_families_count", str(len(families)))
    for candidate in SYSTEM_FONT_CANDIDATES:
        listed = candidate in families
        try:
            actual = _actual(root, f"{{{candidate}}} 13", "-family")
        except tk.TclError as exc:
            actual = f"raised {exc}"
        _report("INFO", "font_candidate",
                f"{candidate!r}: in `font families`={listed}; a font asked for it draws as {actual!r}")
    for name in TK_FONT_NAMES:
        _report("INFO", "font_named", f"{name}: {_actual(root, name)}")
    default_family = _actual(root, "TkDefaultFont", "-family")
    system_family = _actual(root, "{.AppleSystemUIFont} 13", "-family")
    _report("PASS" if system_family == ".AppleSystemUIFont" else "FAIL", "system_font_name",
            f"a font asked for '.AppleSystemUIFont' really is {system_family!r}; "
            f"TkDefaultFont is {default_family!r}")
    for script, char in SCRIPT_SAMPLES:
        try:
            ui = _actual(root, "{.AppleSystemUIFont} 13", "-family", "--", char)
            default = _actual(root, "TkDefaultFont", "-family", "--", char)
        except tk.TclError as exc:
            ui = default = f"raised {exc}"
        _report("INFO", "font_script", f"{script} U+{ord(char):04X}: system font -> {ui!r}; "
                                       f"TkDefaultFont -> {default!r}")


# ----------------------------------------------------------------------- main

def run_steps(steps: Sequence[tuple[str, Callable[[], None]]]) -> list[str]:
    """Run every step; one that raises is reported as a FAIL under its own name.

    Returns the names of the steps that raised: a broken check is never a pass.
    """
    crashed: list[str] = []
    for name, step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - reported, and the run fails below
            crashed.append(name)
            _report("FAIL", name, f"check raised {type(exc).__name__}: {exc}")
    return crashed


def exit_code(results: Sequence[tuple[str, str, str]], crashed: Sequence[str]) -> int:
    """1 when a step raised or a hook the app uses failed, else 0."""
    failed = {hook for status, hook, _detail in results if status == "FAIL"}
    return 1 if crashed or failed & set(USED_BY_APP) else 0


def main(argv: list[str]) -> int:
    hold = 0.0
    flip = "--flip-appearance" in argv
    if "--hold" in argv:
        hold = float(argv[argv.index("--hold") + 1])
    root = tk.Tk()
    try:
        root.title("Mac native probe")
        root.geometry("360x120+80+80")
        tk.Label(root, text="Mac native probe running").pack(padx=20, pady=30)
        system = root.tk.call("tk", "windowingsystem")
        print(f"python {sys.version.split()[0]}  platform {sys.platform}")
        print(f"Tk patchlevel {root.tk.call('info', 'patchlevel')}  windowingsystem {system}")
        if system != "aqua":
            print("SKIP: not Aqua; nothing to probe")
            return 2
        events: dict[str, list[Any]] = {k: [] for k in
                                        ("prefs", "about", "open", "reopen", "apple_item", "help_item")}
        crashed: list[str] = []
        try:
            menus_ok = build_probe_menubar(root)
            root.update()
            oc = _ObjC()
            root.tk.eval("set ::probe_events {}")
            # A background launch is not the active app, and Tk installs the app menu,
            # Help menu and Apple-menu entries when its window becomes active.
            oc.msg(oc.app(), "activateIgnoringOtherApps:", 1, argtypes=(ctypes.c_byte,))
            root.lift()
            _pump(root, 1.0)
        except Exception as exc:  # noqa: BLE001 - nothing can be probed without these
            _report("FAIL", "setup", f"setup raised {type(exc).__name__}: {exc}")
            print("SUMMARY: setup failed; hooks the app uses failing: all")
            return 1
        steps: list[tuple[str, Callable[[], None]]] = [
            ("menus", lambda: probe_menus_and_app_menu(root, oc, events) if menus_ok else None),
            ("show_preferences", lambda: probe_preferences(root, oc, events)),
            ("about", lambda: probe_about(root, oc, events)),
            ("show_help", lambda: probe_show_help(root, oc)),
            ("open_document", lambda: probe_open_document(root, oc, events)),
            ("reopen_application", lambda: probe_reopen(root, oc, events)),
            ("dock_menu", lambda: probe_dock_menu(root, oc)),
            ("window_attributes", lambda: probe_window_attributes(root, oc)),
            ("appearance_isdark", lambda: probe_appearance_static(root, oc)),
            ("appearance_events", lambda: probe_appearance_events(root, oc, flip)),
            ("system_fonts", lambda: probe_system_fonts(root)),
        ]
        crashed = run_steps(steps)
        if hold:
            _pump(root, hold)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    fails = [h for s, h, _d in _results if s == "FAIL"]
    needed = [h for h in fails if h in USED_BY_APP]
    print(f"SUMMARY: {sum(1 for s, _h, _d in _results if s == 'PASS')} pass, {len(fails)} fail"
          + (f" ({', '.join(fails)})" if fails else "")
          + f"; hooks the app uses failing: {', '.join(needed) or 'none'}"
          + (f"; steps that raised: {', '.join(crashed)}" if crashed else ""))
    return exit_code(_results, crashed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
