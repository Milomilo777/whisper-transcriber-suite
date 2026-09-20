"""System-tray controller backed by pystray + Pillow.

When ``config["minimise_to_tray"]`` is enabled, WM_DELETE_WINDOW
hides the main window instead of exiting; the tray icon's right-
click menu offers Show / Hide / Exit. The icon colour changes
to indicate idle vs. active work so the user can glance at the
notification area and see whether a long job is still running.

pystray + Pillow are listed in requirements.txt; if either fails
to import (e.g. headless CI machine without Pillow's pre-built
binary), the module silently degrades to a no-op controller so
the rest of the App keeps booting.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.app import App

logger = logging.getLogger(__name__)


def _try_load_pystray() -> tuple[Any, Any]:
    """Return (pystray_module, PIL_module). Either may be None."""
    try:
        import pystray  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return None, None
    try:
        from PIL import Image  # type: ignore[import-not-found] # noqa: F401
        import PIL  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return pystray, None
    return pystray, PIL


def is_available() -> bool:
    ps, pil = _try_load_pystray()
    return ps is not None and pil is not None


def availability_reason() -> str:
    ps, pil = _try_load_pystray()
    if ps is None:
        return "pystray Python package not installed"
    if pil is None:
        return "Pillow Python package not installed"
    return ""


def _build_icon_image(active: bool, size: int = 64) -> Any:
    """Render a flat-colour circle for the tray icon.

    Blue ring = idle; red dot in the middle = a job is running.
    Pillow only — no asset files to ship.
    """
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Outer ring
    draw.ellipse((4, 4, size - 4, size - 4), outline=(40, 90, 200), width=4)
    if active:
        # Filled red dot
        margin = size // 4
        draw.ellipse((margin, margin, size - margin, size - margin),
                     fill=(200, 40, 40))
    else:
        # Hollow blue circle
        margin = size // 3
        draw.ellipse((margin, margin, size - margin, size - margin),
                     outline=(40, 90, 200), width=3)
    return img


class TrayController:
    """Wraps a pystray ``Icon`` running on a daemon thread.

    The Tk main loop owns all widget calls; tray-thread events (menu
    clicks) are bounced back to the Tk thread via ``app.post_to_main``
    so we don't touch widgets from a foreign thread. ``after(0, ...)``
    used to work here on CPython 3.13 but raises ``RuntimeError`` on
    Python 3.14 — the queue hop is the portable fix.
    """

    def __init__(self, app: "App") -> None:
        self.app = app
        self._pystray, self._pil = _try_load_pystray()
        self._icon: Any = None
        self._thread: threading.Thread | None = None
        self._active = False
        # Set by stop() so the runner's finally can tell a deliberate
        # teardown (on_exit) from an unexpected tray crash. On a crash we
        # must un-strand a window that was minimised-to-tray; on a clean
        # stop the app is exiting anyway, so we leave the window alone.
        self._stopping = False
        # Set when start() could not build/spawn the icon. The App keeps
        # this controller (``self.tray``) after a failed start, and
        # minimise-to-tray only checks ``is_supported()`` -- so without
        # this flag a failed icon would still let the X button withdraw
        # the window with no tray icon to bring it back.
        self._start_failed = False

    def _libs_available(self) -> bool:
        # Platform + dependency support, IGNORING a previous failed start.
        # start() uses this (not is_supported()) so a transient failure
        # (notification area not ready at boot) stays retryable; a
        # successful retry clears _start_failed and reports supported again.
        if sys.platform == "darwin":
            return False
        return self._pystray is not None and self._pil is not None

    def is_supported(self) -> bool:
        # macOS: pystray's AppKit backend must run its event loop on the
        # MAIN thread, but Tk already owns it. Running the tray off-thread
        # (as start() does) silently no-ops there — worse, it would let
        # minimise-to-tray hide the window with no tray to restore it. So
        # the tray is disabled on macOS; the app lives in the Dock instead.
        if getattr(self, "_start_failed", False):
            # Platform/libs support the tray, but bringing THIS icon up
            # failed; a dead controller must not count as usable.
            return False
        return self._libs_available()

    # -- icon lifecycle --------------------------------------------------

    def start(self) -> None:
        if self._icon is not None:
            return
        if not self._libs_available():
            return
        try:
            menu = self._pystray.Menu(
                self._pystray.MenuItem("Show", lambda _i, _e: self._post(self._show_window),
                                       default=True),
                self._pystray.MenuItem("Hide", lambda _i, _e: self._post(self._hide_window)),
                self._pystray.Menu.SEPARATOR,
                self._pystray.MenuItem("Exit", lambda _i, _e: self._post(self._exit_app)),
            )
            self._icon = self._pystray.Icon(
                "WhisperTranscriberSuite",
                _build_icon_image(active=False),
                "Whisper Transcriber Suite",
                menu,
            )

            def _runner() -> None:
                try:
                    self._icon.run()
                except Exception as e:  # noqa: BLE001
                    logger.warning("Tray icon thread crashed: %s", e)
                finally:
                    # Mark the controller dead so later set_active /
                    # notify calls don't operate on a corpse. Bounce
                    # back to the Tk thread to null out app.tray (so the
                    # rest of the app stops dispatching to us) and, on an
                    # unexpected death, restore the window if it was
                    # minimised-to-tray.
                    self._icon = None
                    try:
                        self.app.post_to_main(self._on_runner_exit)
                    except Exception:  # noqa: BLE001
                        pass

            from core._threads import safe_thread
            self._thread = safe_thread(_runner, name="tray-loop")
            self._start_failed = False
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not start tray icon: %s", e)
            self._icon = None
            self._start_failed = True

    def _on_runner_exit(self) -> None:
        """Runs on the Tk main thread when the tray runner thread exits.

        Always nulls ``app.tray`` so nothing else dispatches to a dead
        controller. On an UNEXPECTED exit (not a deliberate ``stop()``),
        also restore a window that was minimised to the tray: the tray
        icon was the only way back, so leaving it withdrawn would strand
        the app as an invisible background process the user can only kill
        from Task Manager.
        """
        try:
            setattr(self.app, "tray", None)
        except Exception:  # noqa: BLE001
            pass
        if self._stopping:
            return
        # Un-strand a withdrawn (minimised-to-tray) window.
        try:
            state = self.app.state()
        except Exception:  # noqa: BLE001
            state = ""
        if state == "withdrawn":
            try:
                self.app.deiconify()
                self.app.lift()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        # Deliberate teardown: tell the runner's finally NOT to re-show
        # the window (the app is exiting).
        self._stopping = True
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
        # Wait briefly for the daemon thread to exit so any in-flight
        # menu-callback bounce to Tk completes BEFORE on_exit's
        # destroy(). Without this join, a tray click that landed
        # right as the user clicked exit could push its callback
        # into the main-thread queue on a destroyed Tcl interpreter.
        thread = self._thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=2.0)
            except Exception:  # noqa: BLE001
                pass
        self._icon = None
        self._thread = None

    # -- state updates ---------------------------------------------------

    def set_active(self, active: bool) -> None:
        """Flip the icon colour between idle (hollow blue) and active
        (red dot). Safe to call from the Tk thread."""
        if self._icon is None or active == self._active:
            return
        try:
            self._icon.icon = _build_icon_image(active=active)
            self._active = active
        except Exception:  # noqa: BLE001
            pass

    def notify(self, title: str, body: str) -> None:
        """Native toast via pystray. Silent fallback when unavailable."""
        if self._icon is None:
            return
        notify_fn = getattr(self._icon, "notify", None)
        if not callable(notify_fn):
            return
        try:
            notify_fn(body, title=title)
        except Exception as e:  # noqa: BLE001
            logger.info("Tray notify failed: %s", e)

    # -- menu actions (run on Tk thread) ---------------------------------

    def _post(self, fn: Any) -> None:
        # pystray fires menu callbacks from its own daemon thread;
        # post_to_main hops back to the Tk main thread via the App's
        # main-thread queue. Calling self.app.after(0, fn) here used
        # to silently no-op on older 3.x and now raises RuntimeError
        # on Python 3.14 — both modes meant every tray click did
        # nothing for the user.
        try:
            self.app.post_to_main(fn)
        except Exception:  # noqa: BLE001
            pass

    def _show_window(self) -> None:
        try:
            self.app.deiconify()
            self.app.lift()
            self.app.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _hide_window(self) -> None:
        try:
            self.app.withdraw()
        except Exception:  # noqa: BLE001
            pass

    def _exit_app(self) -> None:
        # Treat tray "Exit" as a true exit (skip the minimise-to-tray
        # redirect in on_exit).
        try:
            setattr(self.app, "_exit_from_tray", True)
            self.app.on_exit()
        except Exception:  # noqa: BLE001
            pass
