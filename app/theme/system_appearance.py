"""The operating system's light/dark choice: read it, and hear when it changes.

``resolve_theme("system")`` answers "light" or "dark" from the OS; ``SystemThemeWatcher`` calls a
function on the Tk thread when the OS choice changes, so the "System" theme mode follows the OS
live. One back-end per OS sits behind a small interface (``Backend``): ``is_dark()`` and
``subscribe(callback, root)``. Windows (``WindowsBackend``) reads the per-user "Choose your
default app mode" value; macOS (``MacBackend``) asks Tk and listens for its appearance events.
Every other system keeps the earlier behaviour: the optional ``darkdetect`` package decides, and
nothing watches for changes.

Prior art, read before writing this:

* darkdetect (https://github.com/albertosottile/darkdetect): its Windows detection
  reads ``AppsUseLightTheme`` under ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\
  Personalize`` (0 = dark, 1 = light); this module reads the same value with ``winreg``. Its
  ``listener`` blocks a thread in ``RegNotifyChangeKeyValue`` and calls back from that thread.
  Not adopted: Tk is not safe to touch from another thread, and the app would then need a hand-off
  queue plus a stop event for a thread that exits with the process. A 2-second ``after`` check
  of one registry value is simpler and has no thread to leak.
* A ``WM_SETTINGCHANGE`` ("ImmersiveColorSet") hook would need to replace Tk's window procedure.
  Not adopted: that is fragile next to Tk and tkdnd, which already own it.
* macOS: Tk 8.6.16 answers ``tk::unsupported::MacWindowStyle isdark .`` and sends the
  ``<<LightAqua>>`` / ``<<DarkAqua>>`` virtual events to the main window when the user flips
  System Settings > Appearance (proved on macOS 13 by ``tools/mac_native_probe.py
  --flip-appearance``; ``<<TkSystemAppearanceChanged>>`` did NOT fire there and is not used). The
  events arrive on the Tk thread, so no timer and no listener thread are needed; darkdetect's
  ``theme()`` read stays only as the answer when Tk cannot be asked.

``darkdetect`` was never in the Windows bundles (it is an optional extra), so on Windows the old
code always answered "dark" for "System". The registry read has no dependency.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from collections.abc import Callable
from typing import Any, Protocol

from app import mac_native

logger = logging.getLogger(__name__)

# Same cadence as a person notices a theme flip: quick enough to feel live, one registry read.
POLL_MS = 2000

_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_APPS_USE_LIGHT = "AppsUseLightTheme"

# A change whose handler fails (a restyle error) is retried on the next ticks, this many times in
# all, then dropped until the value changes again: a bug must not become a restyle every 2 s.
MAX_CALLBACK_ATTEMPTS = 3

# What "System" resolves to when the OS cannot be asked: the long-standing answer, kept so a
# machine where detection is unavailable looks as it always did (and the reason is logged once).
UNKNOWN_FALLBACK = "dark"


class Backend(Protocol):
    """One operating system's way of reading and watching its light/dark choice."""

    #: True when ``subscribe`` really reports changes (False: the choice is read once).
    live: bool

    def is_dark(self) -> bool | None:
        """True = the OS asks for dark apps, False = light, None = cannot be told."""
        ...

    def subscribe(self, callback: Callable[[], None], root: tk.Misc) -> Callable[[], None]:
        """Call ``callback()`` on the Tk thread whenever ``is_dark()`` changes.

        Returns the function that cancels the subscription. A back-end that cannot watch returns
        a no-op canceller and never calls back.
        """
        ...


def _deliver(now: bool, state: dict[str, Any], callback: Callable[[], None]) -> None:
    """Tell ``callback`` that the choice became ``now``; remember it only once that worked."""
    if now != state["pending"]:
        state["pending"], state["attempts"] = now, 0
    state["attempts"] += 1
    try:
        callback()
    except Exception:  # noqa: BLE001 - a failing handler must not end the watch
        if state["attempts"] == 1:
            logger.exception("System theme change handler failed")
        else:
            logger.debug("System theme change handler failed again", exc_info=True)
        if state["attempts"] >= MAX_CALLBACK_ATTEMPTS:
            logger.warning("System theme change handler failed %d times: giving up on this change",
                           state["attempts"])
            state["last"] = now
        return
    state["last"] = now


# ----------------------------------------------------------------------------- Windows

class WindowsBackend:
    """Windows 10 1809+ and 11: the per-user "app mode" registry value, checked every 2 s."""

    live = True

    def __init__(self, poll_ms: int = POLL_MS) -> None:
        self._poll_ms = poll_ms

    def is_dark(self) -> bool | None:
        try:
            import winreg  # type: ignore[import-not-found,unused-ignore]
        except ImportError:
            return None
        # Adapted from darkdetect (https://github.com/albertosottile/darkdetect) — the registry key
        # and value (AppsUseLightTheme, 0 = dark) that Windows keeps for the app mode.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, _APPS_USE_LIGHT)
        except FileNotFoundError:
            # Windows before 1809 (or a stripped profile) has no dark app mode: apps are light.
            return False
        except OSError as exc:
            _warn_once("windows-read", "Could not read the Windows app theme: %s", exc)
            return None
        try:
            return int(value) == 0
        except (TypeError, ValueError):
            _warn_once("windows-value", "Unexpected Windows app theme value: %r", value)
            return None

    _deliver = staticmethod(_deliver)

    def subscribe(self, callback: Callable[[], None], root: tk.Misc) -> Callable[[], None]:
        state: dict[str, Any] = {"last": self.is_dark(), "after": None, "stopped": False,
                                 "pending": None, "attempts": 0}

        def tick() -> None:
            state["after"] = None
            if state["stopped"]:
                return
            try:
                now = self.is_dark()
                if now is not None and now != state["last"]:
                    self._deliver(now, state, callback)
            except Exception:  # noqa: BLE001 - nothing may end the watch
                logger.exception("System theme check failed")
            if state["stopped"]:
                return
            try:
                state["after"] = root.after(self._poll_ms, tick)
            except tk.TclError:
                state["stopped"] = True  # the window is gone

        def cancel() -> None:
            state["stopped"] = True
            handle = state["after"]
            state["after"] = None
            if handle is not None:
                try:
                    root.after_cancel(handle)
                except tk.TclError:
                    pass

        try:
            state["after"] = root.after(self._poll_ms, tick)
        except tk.TclError:
            state["stopped"] = True
        return cancel


# ----------------------------------------------------------------------------------- macOS

# The two virtual events Tk sends to the main window when the Light/Dark setting flips.
MAC_APPEARANCE_EVENTS = ("<<LightAqua>>", "<<DarkAqua>>")


class MacBackend:
    """macOS: Tk's own ``isdark`` answer, and the Light/Dark events Tk sends on a flip.

    Without a window to ask (or on a Tk that cannot tell) the answer is the earlier one: the
    optional ``darkdetect`` package, which is how a build without it kept "dark". ``root`` is the
    Tk root to ask; ``None`` means the process's default root (``is_dark`` before the app has one
    is the darkdetect answer).
    """

    live = True

    def __init__(self, root: tk.Misc | None = None, retry_ms: int = POLL_MS) -> None:
        self._root = root
        self._retry_ms = retry_ms

    def _ask_tk(self, root: tk.Misc) -> bool | None:
        if not mac_native.is_aqua(root):
            return None
        try:
            raw = str(root.tk.call("tk::unsupported::MacWindowStyle", "isdark", str(root))).lower()
        except tk.TclError as exc:
            _warn_once("mac-isdark", "Tk could not tell the macOS appearance: %s", exc)
            return None
        if raw in ("1", "true"):
            return True
        if raw in ("0", "false"):
            return False
        _warn_once("mac-isdark-value", "Unexpected macOS appearance value from Tk: %r", raw)
        return None

    def _answer(self, root: tk.Misc | None) -> bool | None:
        answer = self._ask_tk(root) if root is not None else None
        if answer is None:
            return DarkdetectBackend().is_dark()
        return answer

    def is_dark(self) -> bool | None:
        return self._answer(self._root or getattr(tk, "_default_root", None))

    def subscribe(self, callback: Callable[[], None], root: tk.Misc) -> Callable[[], None]:
        state: dict[str, Any] = {"last": self._answer(root), "after": None, "stopped": False,
                                 "pending": None, "attempts": 0}
        bound: dict[str, str] = {}

        def clear_timer() -> None:
            handle, state["after"] = state["after"], None
            if handle is not None:
                try:
                    root.after_cancel(handle)
                except tk.TclError:
                    pass

        def check(_event: object = None) -> None:
            clear_timer()
            if state["stopped"]:
                return
            now: bool | None = None
            try:
                now = self._answer(root)
                if now is not None and now != state["last"]:
                    _deliver(now, state, callback)
            except Exception:  # noqa: BLE001 - nothing may end the watch
                logger.exception("System theme check failed")
            if state["stopped"] or now is None or now == state["last"]:
                return
            # The handler failed and is not given up on yet: look again shortly.
            try:
                state["after"] = root.after(self._retry_ms, check)
            except tk.TclError:
                state["stopped"] = True  # the window is gone

        def cancel() -> None:
            state["stopped"] = True
            clear_timer()
            for sequence, funcid in list(bound.items()):
                try:
                    root.unbind(sequence, funcid)
                except tk.TclError:
                    pass
            bound.clear()

        for sequence in MAC_APPEARANCE_EVENTS:
            try:
                bound[sequence] = root.bind(sequence, check, add="+")
            except tk.TclError:
                state["stopped"] = True  # the window is gone
                break
        return cancel


# --------------------------------------------------------------- everything else (unchanged: Linux)

class DarkdetectBackend:
    """Linux (and macOS when Tk cannot answer): the optional ``darkdetect`` package, no watching.

    Same answers as the code it replaces: "Dark" is dark, anything else the package returns
    (including None) is light, and a missing or failing package is unknown (dark, logged once).
    """

    live = False

    def is_dark(self) -> bool | None:
        try:
            import darkdetect  # type: ignore[import-not-found,unused-ignore]
        except ImportError:
            _warn_once(
                "darkdetect-missing",
                "darkdetect is not installed: 'System' theme falls back to %s", UNKNOWN_FALLBACK,
            )
            return None
        try:
            answer = darkdetect.theme()
        except Exception as exc:  # noqa: BLE001 - detection must never stop the app
            _warn_once("darkdetect-failed", "darkdetect could not read the theme: %s", exc)
            return None
        # As before: no answer (None) counted as light.
        return str(answer or "").lower() == "dark"

    def subscribe(self, callback: Callable[[], None], root: tk.Misc) -> Callable[[], None]:
        return _no_op


def _no_op() -> None:
    return None


_warned: set[str] = set()


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(message, *args)


def get_backend(platform: str | None = None) -> Backend:
    """The back-end for ``platform`` (default: this system)."""
    chosen = platform or sys.platform
    if chosen == "win32":
        return WindowsBackend()
    if chosen == "darwin":
        return MacBackend()
    return DarkdetectBackend()


def resolve_theme(name: str, backend: Backend | None = None) -> str:
    """The theme to draw, ``"light"`` or ``"dark"``, for a saved choice.

    ``"light"`` / ``"dark"`` are themselves; ``"system"`` asks the OS; anything else is dark
    (as before). A system that cannot be asked gives ``UNKNOWN_FALLBACK`` and logs why, once.
    """
    if name in ("light", "dark"):
        return name
    if name != "system":
        return "dark"
    try:
        answer = (backend or get_backend()).is_dark()
    except Exception as exc:  # noqa: BLE001 - a back-end bug must not stop start-up
        _warn_once("backend-failed", "System theme detection failed: %s", exc)
        answer = None
    if answer is None:
        return UNKNOWN_FALLBACK
    return "dark" if answer else "light"


class SystemThemeWatcher:
    """Runs ``on_change`` when the OS light/dark choice changes; idle until ``start``."""

    def __init__(self, root: tk.Misc, on_change: Callable[[], None],
                 backend: Backend | None = None) -> None:
        self._root = root
        self._on_change = on_change
        self._backend = backend
        self._cancel: Callable[[], None] | None = None

    @property
    def running(self) -> bool:
        return self._cancel is not None

    def start(self) -> None:
        """Begin watching (once; a second call changes nothing)."""
        if self._cancel is not None:
            return
        backend = self._backend or get_backend()
        if not backend.live:
            return
        self._cancel = backend.subscribe(self._on_change, self._root)

    def stop(self) -> None:
        cancel, self._cancel = self._cancel, None
        if cancel is not None:
            cancel()
