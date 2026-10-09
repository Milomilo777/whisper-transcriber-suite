"""Windows taskbar button: progress bar, job-count badge and a flash when a job finishes.

What the user sees on the app's taskbar button (Windows 7 and later):

* a green progress bar while a job runs (a marquee while it has no percentage yet), a yellow one
  while the running jobs are paused, a red one after a job failed;
* a small red badge with the number of queued and running jobs (``9+`` above nine);
* a flash of the button (three blinks) when a job finishes while the window is not in front,
  tied to the existing "Chime on completion" setting (no second option). A user job flashes once,
  when its last stage is done: a failed or cancelled job does not flash, and the transcription
  step of a subtitled-video chain waits for the burn.

How it is done: ``ITaskbarList3`` through ``ctypes`` only (no new dependency). The COM object is
called through its vtable, so the slot numbers below are pinned by a test and were checked against
the Windows SDK header ``ShObjIdl_core.h`` (``ITaskbarList3`` derives from ``ITaskbarList2``, which
derives from ``ITaskbarList``, which derives from ``IUnknown``: 3 + 5 + 1 methods come first).

Guards (a wrong vtable call is an access violation that no ``try`` can catch, so there are several):

* kill switch: the config key ``native_taskbar`` set to false (``set_enabled``) or the environment
  variable ``WTS_NO_TASKBAR`` set to anything but ``0``/``false`` turns every call here off;
* start marker: a small file is written before the first COM call and removed after the first
  full round of calls succeeded. A crash in between leaves it behind, and while it exists for
  this app version the taskbar integration stays off (a warning is logged; delete the file
  or update the app to try again);
* COM runs only on the Tk thread, in a single-threaded apartment; any other thread is refused;
* the ``TaskbarButtonCreated`` message (sent again after Explorer restarts) re-creates the COM
  object and re-applies the state, through ``SetWindowSubclass`` (chains to the existing window
  procedure; Tk's own is never replaced);
* an HRESULT failure is retried, and five failures in a row switch the integration off for the
  session; every native failure is logged once and never reaches the user.

Nothing here runs off Windows, and importing this module is safe everywhere (``ctypes.wintypes``
and the DLLs are only touched when a Windows window asks for them).

Sources: Microsoft's ``ITaskbarList3`` documentation
(https://learn.microsoft.com/windows/win32/api/shobjidl_core/nn-shobjidl_core-itaskbarlist3),
"Taskbar Extensions" (the ``TaskbarButtonCreated`` message), ``FlashWindowEx``, and
``SetWindowSubclass`` (https://learn.microsoft.com/windows/win32/controls/subclassing-overview).
"""
from __future__ import annotations

import ctypes
import functools
import logging
import math
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from app.theme.win_chrome import _as_switch

logger = logging.getLogger(__name__)

ENV_KILL_SWITCH = "WTS_NO_TASKBAR"
MARKER_NAME = "taskbar_integration.marker"

# ------------------------------------------------------------------- COM identifiers
# Windows SDK ShObjIdl_core.h: DECLSPEC_UUID of the TaskbarList coclass and the two interfaces.
CLSID_TASKBAR_LIST = "56FDF344-FD6D-11d0-958A-006097C9A090"   # class TaskbarList
IID_ITASKBAR_LIST3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"   # ITaskbarList3

# Vtable slot of each method used, in header order: IUnknown (0-2), ITaskbarList (3-7:
# HrInit, AddTab, DeleteTab, ActivateTab, SetActiveAlt), ITaskbarList2 (8: MarkFullscreenWindow),
# ITaskbarList3 (9-20: SetProgressValue, SetProgressState, RegisterTab, UnregisterTab,
# SetTabOrder, SetTabActive, ThumbBarAddButtons, ThumbBarUpdateButtons, ThumbBarSetImageList,
# SetOverlayIcon, SetThumbnailTooltip, SetThumbnailClip).
ITASKBAR_LIST3_METHODS = (
    "QueryInterface", "AddRef", "Release",
    "HrInit", "AddTab", "DeleteTab", "ActivateTab", "SetActiveAlt",
    "MarkFullscreenWindow",
    "SetProgressValue", "SetProgressState", "RegisterTab", "UnregisterTab", "SetTabOrder",
    "SetTabActive", "ThumbBarAddButtons", "ThumbBarUpdateButtons", "ThumbBarSetImageList",
    "SetOverlayIcon", "SetThumbnailTooltip", "SetThumbnailClip",
)
SLOT_RELEASE = ITASKBAR_LIST3_METHODS.index("Release")
SLOT_HR_INIT = ITASKBAR_LIST3_METHODS.index("HrInit")
SLOT_SET_PROGRESS_VALUE = ITASKBAR_LIST3_METHODS.index("SetProgressValue")
SLOT_SET_PROGRESS_STATE = ITASKBAR_LIST3_METHODS.index("SetProgressState")
SLOT_SET_OVERLAY_ICON = ITASKBAR_LIST3_METHODS.index("SetOverlayIcon")

# TBPFLAG (ShObjIdl_core.h)
TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

# Win32 constants (WinUser.h, objbase.h, CommCtrl.h)
COINIT_APARTMENTTHREADED = 0x2
COINIT_DISABLE_OLE1DDE = 0x4
CLSCTX_INPROC_SERVER = 0x1
RPC_E_CHANGED_MODE = 0x80010106
FLASHW_TRAY = 0x2
GA_ROOTOWNER = 3
SM_CXSMICON = 49
WM_NCDESTROY = 0x0082
MSGFLT_ALLOW = 1
TASKBAR_BUTTON_CREATED = "TaskbarButtonCreated"   # registered window message name
_SUBCLASS_ID = 0x57545331   # arbitrary id of this subclass ("WTS1"); one per window

# ------------------------------------------------------------------------- behaviour
MIN_INTERVAL = 0.5          # seconds between two rounds of taskbar updates (<= 2 per second)
MAX_FAILURES = 5            # failed rounds in a row before the integration stops for the session
FLASH_COUNT = 3             # blinks of one flash (a single blink is easy to miss)
ERROR_MIN_SECONDS = 5.0     # a failure shows red for 5 s at least, then until the window is in front
BADGE_RED = (0xC4, 0x2B, 0x1C)

QUEUE_ACTIVE = ("waiting", "running", "paused")
# A download "transcribing" is its linked transcription task in the other queue: not counted twice.
DOWNLOAD_ACTIVE = ("waiting", "running", "paused", "burning")

# Process-wide state (reset by tests/conftest.py).
_config_enabled = True
_failed: set[str] = set()
_ctl: "_Controller | None" = None
# Set by shutdown() (App.destroy) and never cleared in production: the process ends with the
# window, so the integration is deliberately not restartable after a close.
_closed = False
_session_off = False


class ComError(RuntimeError):
    """A COM or Win32 call the integration depends on failed."""


# ---------------------------------------------------------------------- kill switch

def set_enabled(enabled: object) -> None:
    """The config switch (``native_taskbar``); the environment variable is read live."""
    global _config_enabled
    _config_enabled = _as_switch(enabled)


def env_disabled() -> bool:
    value = os.environ.get(ENV_KILL_SWITCH, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def _platform() -> str:
    return sys.platform


def enabled(platform: str | None = None) -> bool:
    """True when taskbar calls are allowed: Windows, config on, environment switch off."""
    if (platform or _platform()) != "win32":
        return False
    return _config_enabled and not env_disabled() and not _session_off


def _note_failure(key: str, message: str, *args: object) -> None:
    if key in _failed:
        return
    _failed.add(key)
    logger.info(message, *args)


# ------------------------------------------------------------------ start marker

def marker_path() -> Path:
    from core import config
    return config.user_data_dir() / MARKER_NAME


def _app_version() -> str:
    from core import __version__
    return str(__version__)


def marker_blocks(path: Path) -> bool:
    """True when a marker from a crashed start of THIS app version exists.

    A marker of another version is stale (the code may have changed): it is removed and the
    integration tries again. An unreadable marker counts as blocking.
    """
    try:
        if not path.exists():
            return False
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = None
        if text is not None and text != _app_version():
            logger.info("Removing a taskbar start marker left by version %s", text)
            path.unlink()
            return False
    except OSError as exc:
        logger.warning("Taskbar start marker cannot be checked (%s); integration stays off", exc)
        return True
    logger.warning(
        "The last start crashed while setting up the Windows taskbar integration; it stays off. "
        "Delete %s, or update the app, to try again.", path)
    return True


def _write_marker(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_app_version(), encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("Taskbar start marker cannot be written (%s); integration stays off", exc)
        return False


def _remove_marker(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Taskbar start marker cannot be removed (%s); the integration will stay "
                       "off at the next start until %s is deleted", exc, path)


# --------------------------------------------------------------------- the snapshot

@dataclass(frozen=True)
class Snapshot:
    """What the taskbar button should show: progress state, percent (0-100) and badge count."""
    state: int = TBPF_NOPROGRESS
    value: int = 0
    badge: int = 0

    @property
    def idle(self) -> bool:
        return self.state == TBPF_NOPROGRESS and self.badge == 0


def _percent(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number):
        return 0.0
    return min(100.0, max(0.0, number))


def _average(values: list[float]) -> int:
    return int(round(sum(values) / len(values))) if values else 0


def summarize(queue: Iterable[Any], downloads: Iterable[Any], *, error: bool = False,
              download_progress: Callable[[Any], object] | None = None) -> Snapshot:
    """The taskbar state for the two queues.

    ``error`` is the "a job failed" latch (the caller holds it). Priority: failed (red), running
    (green; a marquee while no percentage is known), paused (yellow), nothing (cleared).
    The badge counts jobs that are waiting, running or paused in both queues.
    """
    running: list[float] = []
    paused: list[float] = []
    badge = 0
    for task in queue:
        status = getattr(task, "status", "")
        if status == "running":
            running.append(_percent(getattr(task, "progress", 0)))
        elif status == "paused":
            paused.append(_percent(getattr(task, "progress", 0)))
        elif status != "waiting":
            continue
        badge += 1
    for item in downloads:
        status = getattr(item, "status", "")
        if status in ("running", "burning"):
            progress = download_progress(item) if download_progress else getattr(item, "progress", 0)
            running.append(_percent(progress))
        elif status == "paused":
            paused.append(_percent(getattr(item, "progress", 0)))
        elif status != "waiting":
            continue
        badge += 1
    if error:
        # A red bar needs a visible length: a failed job with nothing else running shows it full.
        return Snapshot(TBPF_ERROR, _average(running or paused) or 100, badge)
    if running:
        value = _average(running)
        return Snapshot(TBPF_NORMAL if value > 0 else TBPF_INDETERMINATE, value, badge)
    if paused:
        return Snapshot(TBPF_PAUSED, _average(paused), badge)
    return Snapshot(TBPF_NOPROGRESS, 0, badge)


def badge_label(count: int) -> str:
    return str(count) if count <= 9 else "9+"


# 3x5 pixel digits and a plus sign; drawn in whole-pixel steps so the badge stays sharp.
_GLYPHS = {
    "0": ("###", "# #", "# #", "# #", "###"),
    "1": (" # ", "## ", " # ", " # ", "###"),
    "2": ("###", "  #", "###", "#  ", "###"),
    "3": ("###", "  #", "###", "  #", "###"),
    "4": ("# #", "# #", "###", "  #", "  #"),
    "5": ("###", "#  ", "###", "  #", "###"),
    "6": ("###", "#  ", "###", "# #", "###"),
    "7": ("###", "  #", "  #", "  #", "  #"),
    "8": ("###", "# #", "###", "# #", "###"),
    "9": ("###", "# #", "###", "  #", "###"),
    "+": ("   ", " # ", "###", " # ", "   "),
}


def render_badge(label: str, size: int) -> bytes:
    """A ``size`` x ``size`` badge as top-down 32-bit BGRA bytes: red rounded square, white text.

    Pure Python, so no font or imaging library is needed and the result is the same everywhere.
    """
    if size < 8:
        raise ValueError("badge size too small")
    unknown = [c for c in label if c not in _GLYPHS]
    if unknown or not label:
        raise ValueError(f"cannot draw badge text {label!r}")
    scale = max(1, size // 8)
    text_w = len(label) * 3 * scale + (len(label) - 1) * scale
    if text_w > size - 2:
        raise ValueError(f"badge text {label!r} does not fit {size} pixels")
    left = (size - text_w) // 2
    top = (size - 5 * scale) // 2
    lit: set[tuple[int, int]] = set()
    for index, char in enumerate(label):
        x0 = left + index * 4 * scale
        for row, line in enumerate(_GLYPHS[char]):
            for col, mark in enumerate(line):
                if mark != "#":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        lit.add((x0 + col * scale + dx, top + row * scale + dy))
    corner = max(1, size // 6)
    red = bytes((BADGE_RED[2], BADGE_RED[1], BADGE_RED[0], 0xFF))   # BGRA
    white = b"\xff\xff\xff\xff"
    clear = b"\x00\x00\x00\x00"
    out = bytearray()
    for y in range(size):
        for x in range(size):
            if min(x, size - 1 - x) + min(y, size - 1 - y) < corner - 1:
                out += clear
            elif (x, y) in lit:
                out += white
            else:
                out += red
    return bytes(out)


# ---------------------------------------------------------------------- native layer

def _guid(text: str) -> Any:
    class _Guid(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    parts = uuid.UUID(text)
    return _Guid(parts.fields[0], parts.fields[1], parts.fields[2],
                 (ctypes.c_ubyte * 8)(*parts.bytes[8:]))


class _ComObject:
    """An ``ITaskbarList3`` interface pointer, called through its vtable.

    Every prototype is declared here with 64-bit-safe types: handles and the interface pointer
    are ``c_void_p`` (a Python int would be truncated to 32 bits by the default ``c_int``).
    """

    def __init__(self, pointer: int) -> None:
        """Take over one reference to ``pointer``; it is released again if wrapping fails."""
        if not pointer:
            raise ComError("null interface pointer")
        self._pointer = int(pointer)
        try:
            self._bind()
        except BaseException:
            self._release_raw()
            raise

    def _bind(self) -> None:
        functype = ctypes.WINFUNCTYPE  # type: ignore[attr-defined]
        void_p, hresult = ctypes.c_void_p, ctypes.c_long
        self._release = self._method(SLOT_RELEASE, functype(ctypes.c_ulong, void_p))
        self._hr_init = self._method(SLOT_HR_INIT, functype(hresult, void_p))
        self._set_value = self._method(
            SLOT_SET_PROGRESS_VALUE,
            functype(hresult, void_p, void_p, ctypes.c_ulonglong, ctypes.c_ulonglong))
        self._set_state = self._method(
            SLOT_SET_PROGRESS_STATE, functype(hresult, void_p, void_p, ctypes.c_int))
        self._set_overlay = self._method(
            SLOT_SET_OVERLAY_ICON, functype(hresult, void_p, void_p, void_p, ctypes.c_wchar_p))

    def _release_raw(self) -> None:
        """Release without relying on the other wrappers (they may be what failed)."""
        try:
            functype = ctypes.WINFUNCTYPE  # type: ignore[attr-defined]
            self._method(SLOT_RELEASE, functype(ctypes.c_ulong, ctypes.c_void_p))(self._pointer)
        except Exception as exc:  # noqa: BLE001 - nothing more can be done for this pointer
            _note_failure("release-raw", "Could not release a taskbar interface: %s", exc)

    def _method(self, slot: int, prototype: Any) -> Any:
        size = ctypes.sizeof(ctypes.c_void_p)
        table = ctypes.c_void_p.from_address(self._pointer).value
        if not table:
            raise ComError("interface has no method table")
        address = ctypes.c_void_p.from_address(table + slot * size).value
        if not address:
            raise ComError(f"method table slot {slot} is empty")
        return prototype(address)

    def hr_init(self) -> int:
        return int(self._hr_init(self._pointer))

    def set_progress_value(self, hwnd: int, completed: int, total: int) -> int:
        return int(self._set_value(self._pointer, hwnd, completed, total))

    def set_progress_state(self, hwnd: int, flag: int) -> int:
        return int(self._set_state(self._pointer, hwnd, flag))

    def set_overlay_icon(self, hwnd: int, icon: int | None, description: str) -> int:
        return int(self._set_overlay(self._pointer, hwnd, icon, description))

    def release(self) -> None:
        self._release(self._pointer)


class _Native:
    """The Win32 and COM functions used, loaded on first use (never at import)."""

    def __init__(self) -> None:
        from ctypes import wintypes
        windll = ctypes.WinDLL  # type: ignore[attr-defined]
        self._ole32 = windll("ole32", use_last_error=True)
        self._user32 = windll("user32", use_last_error=True)
        self._gdi32 = windll("gdi32", use_last_error=True)
        void_p = ctypes.c_void_p
        self._ole32.CoInitializeEx.argtypes = [void_p, wintypes.DWORD]
        self._ole32.CoInitializeEx.restype = ctypes.c_long
        self._ole32.CoUninitialize.argtypes = []
        self._ole32.CoUninitialize.restype = None
        self._ole32.CoCreateInstance.argtypes = [
            void_p, void_p, wintypes.DWORD, void_p, ctypes.POINTER(void_p)]
        self._ole32.CoCreateInstance.restype = ctypes.c_long
        u = self._user32
        u.GetParent.argtypes = [void_p]
        u.GetParent.restype = void_p
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = void_p
        u.GetAncestor.argtypes = [void_p, wintypes.UINT]
        u.GetAncestor.restype = void_p
        u.IsIconic.argtypes = [void_p]
        u.IsIconic.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [void_p]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        u.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
        u.RegisterWindowMessageW.restype = wintypes.UINT
        u.CreateIconIndirect.argtypes = [void_p]
        u.CreateIconIndirect.restype = void_p
        u.DestroyIcon.argtypes = [void_p]
        u.DestroyIcon.restype = wintypes.BOOL
        u.FlashWindowEx.argtypes = [void_p]
        u.FlashWindowEx.restype = wintypes.BOOL
        u.ChangeWindowMessageFilterEx.argtypes = [void_p, wintypes.UINT, wintypes.DWORD, void_p]
        u.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
        self._gdi32.CreateBitmap.argtypes = [
            ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, void_p]
        self._gdi32.CreateBitmap.restype = void_p
        self._gdi32.DeleteObject.argtypes = [void_p]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._com: _ComObject | None = None
        self._owns_com = False
        self._icons: dict[tuple[str, int], int] = {}
        self._subclassed: tuple[int, Any] | None = None

    # -- COM apartment and object
    def co_initialize(self) -> None:
        """Enter a single-threaded apartment on this (the Tk) thread, or raise.

        S_OK and S_FALSE (already in an STA, for example because drag and drop started OLE) both
        count one init that ``close`` balances. A thread already in a multi-threaded apartment
        (RPC_E_CHANGED_MODE) is refused: the taskbar object is apartment-threaded.
        """
        hr = self._ole32.CoInitializeEx(
            None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) & 0xFFFFFFFF
        if hr in (0, 1):
            self._owns_com = True
            return
        if hr == RPC_E_CHANGED_MODE:
            raise ComError("this thread already uses a multi-threaded COM apartment")
        raise ComError(f"CoInitializeEx failed ({hr:#x})")

    def create(self) -> None:
        """Create the TaskbarList object and call HrInit on it (the call the interface requires)."""
        self._drop_object()
        clsid, iid = _guid(CLSID_TASKBAR_LIST), _guid(IID_ITASKBAR_LIST3)
        pointer = ctypes.c_void_p()
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER, ctypes.byref(iid),
            ctypes.byref(pointer)) & 0xFFFFFFFF
        if hr != 0 or not pointer.value:
            raise ComError(f"CoCreateInstance(TaskbarList) failed ({hr:#x})")
        com = _ComObject(pointer.value)
        self._com = com
        hr = com.hr_init() & 0xFFFFFFFF
        if hr != 0:
            self._drop_object()
            raise ComError(f"ITaskbarList::HrInit failed ({hr:#x})")

    def _drop_object(self) -> None:
        com, self._com = self._com, None
        if com is not None:
            com.release()

    def _object(self) -> _ComObject:
        if self._com is None:
            raise ComError("taskbar object not created")
        return self._com

    # -- taskbar calls (HRESULT; 0 = success)
    def set_progress_state(self, hwnd: int, flag: int) -> int:
        return self._object().set_progress_state(hwnd, flag)

    def set_progress_value(self, hwnd: int, completed: int, total: int) -> int:
        return self._object().set_progress_value(hwnd, completed, total)

    def set_overlay(self, hwnd: int, label: str | None, description: str) -> int:
        """Show the badge for ``label`` (None clears it)."""
        icon = self._icon(label) if label else None
        return self._object().set_overlay_icon(hwnd, icon, description if label else "")

    # -- window helpers
    def top_window(self, widget_id: int) -> int:
        """The frame window Windows draws (and puts on the taskbar) for a Tk top-level."""
        return int(self._user32.GetParent(widget_id) or 0)

    def is_foreground(self, hwnd: int) -> bool:
        """True when the window (or a dialog it owns) is the active one, shown and not minimised.

        A hidden window can still be the "foreground window" of the process, so visibility is
        checked as well.
        """
        if self._user32.IsIconic(hwnd) or not self._user32.IsWindowVisible(hwnd):
            return False
        front = self._user32.GetForegroundWindow()
        if not front:
            return False
        owner = self._user32.GetAncestor(front, GA_ROOTOWNER)
        return hwnd in (int(front), int(owner or 0))

    def flash(self, hwnd: int, count: int) -> None:
        from ctypes import wintypes

        class _FlashInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", ctypes.c_void_p),
                        ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                        ("dwTimeout", wintypes.DWORD)]

        info = _FlashInfo(ctypes.sizeof(_FlashInfo), hwnd, FLASHW_TRAY, count, 0)
        self._user32.FlashWindowEx(ctypes.byref(info))

    def small_icon_size(self) -> int:
        size = int(self._user32.GetSystemMetrics(SM_CXSMICON))
        return min(64, max(16, size))

    # -- badge icons (kept per label and size, destroyed at close)
    def _icon(self, label: str) -> int:
        size = self.small_icon_size()
        key = (label, size)
        handle = self._icons.get(key)
        if handle:
            return handle
        handle = self._create_icon(render_badge(label, size), size)
        self._icons[key] = handle
        return handle

    def _create_icon(self, bgra: bytes, size: int) -> int:
        from ctypes import wintypes

        class _IconInfo(ctypes.Structure):
            _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                        ("yHotspot", wintypes.DWORD), ("hbmMask", ctypes.c_void_p),
                        ("hbmColor", ctypes.c_void_p)]

        color = self._gdi32.CreateBitmap(size, size, 1, 32, bgra)
        mask = self._gdi32.CreateBitmap(size, size, 1, 1, bytes(((size + 15) // 16 * 2) * size))
        try:
            if not color or not mask:
                raise ComError("CreateBitmap failed")
            info = _IconInfo(True, 0, 0, mask, color)
            handle = self._user32.CreateIconIndirect(ctypes.byref(info))
        finally:
            for bitmap in (color, mask):
                if bitmap:
                    self._gdi32.DeleteObject(bitmap)
        if not handle:
            raise ComError("CreateIconIndirect failed")
        return int(handle)

    # -- TaskbarButtonCreated
    def watch_button_created(self, hwnd: int, callback: Callable[[], None]) -> None:
        """Call ``callback()`` (on the Tk thread) whenever the taskbar button is (re)created."""
        from ctypes import wintypes
        windll = ctypes.WinDLL  # type: ignore[attr-defined]
        comctl = windll("comctl32", use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
            ctypes.c_ssize_t, ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
            ctypes.c_size_t, ctypes.c_size_t)
        comctl.SetWindowSubclass.argtypes = [
            ctypes.c_void_p, proc_type, ctypes.c_size_t, ctypes.c_size_t]
        comctl.SetWindowSubclass.restype = wintypes.BOOL
        comctl.RemoveWindowSubclass.argtypes = [ctypes.c_void_p, proc_type, ctypes.c_size_t]
        comctl.RemoveWindowSubclass.restype = wintypes.BOOL
        comctl.DefSubclassProc.argtypes = [
            ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        comctl.DefSubclassProc.restype = ctypes.c_ssize_t
        message = int(self._user32.RegisterWindowMessageW(TASKBAR_BUTTON_CREATED))
        if not message:
            raise ComError("RegisterWindowMessage(TaskbarButtonCreated) failed")
        # A process that runs as administrator only receives the message when it is allowed.
        self._user32.ChangeWindowMessageFilterEx(hwnd, message, MSGFLT_ALLOW, None)

        # The procedure sees the callback only through this cell, which close() empties: the
        # procedure itself must stay alive for good, the controller behind it must not.
        cell: list[Callable[[], None] | None] = [callback]

        def window_proc(h: int, msg: int, wparam: int, lparam: int, _id: int, _ref: int) -> int:
            try:
                if msg == message:
                    target = cell[0]
                    if target is not None:
                        target()
                elif msg == WM_NCDESTROY:
                    comctl.RemoveWindowSubclass(h, proc, _SUBCLASS_ID)
            except Exception:  # noqa: BLE001 - never raise into the window procedure
                logger.debug("Taskbar window hook failed", exc_info=True)
            return int(comctl.DefSubclassProc(h, msg, wparam, lparam))

        proc = proc_type(window_proc)
        if not comctl.SetWindowSubclass(hwnd, proc, _SUBCLASS_ID, 0):
            raise ComError("SetWindowSubclass failed")
        # Windows can still call the procedure until its window is gone, so it is never freed;
        # one entry per window (a new start of the same window replaces the removed one).
        _KEEP_ALIVE[hwnd] = proc

        def unhook() -> None:
            cell[0] = None
            comctl.RemoveWindowSubclass(hwnd, proc, _SUBCLASS_ID)

        self._subclassed = (hwnd, unhook)

    def close(self) -> None:
        """Release everything, each step on its own so one failure cannot skip the rest."""
        steps: list[Callable[[], object]] = []
        if self._subclassed is not None:
            steps.append(self._subclassed[1])
        steps.append(self._drop_object)
        for handle in self._icons.values():
            steps.append(functools.partial(self._user32.DestroyIcon, handle))
        if self._owns_com:
            steps.append(self._ole32.CoUninitialize)
        self._subclassed = None
        self._icons = {}
        self._owns_com = False
        for step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                _note_failure("close", "Taskbar clean-up step failed: %s", exc)


_KEEP_ALIVE: dict[int, Any] = {}


def _unavailable() -> Any:
    raise ComError("no native taskbar layer")


# What builds the native layer; tests replace it (conftest blocks the real one).
_native_factory: Callable[[], Any] = _Native


# ------------------------------------------------------------------------ controller

class _Controller:
    """The live taskbar integration of one Tk window."""

    def __init__(self, root: Any, native: Any, hwnd: int, marker: Path | None) -> None:
        self.root = root
        self.native = native
        self.hwnd = hwnd
        self.marker = marker          # start marker, still on disk until the first full apply
        self.applied: Snapshot | None = None
        self.last_round = float("-inf")
        self.failures = 0
        self.button_created = False
        self.error_since: float | None = None
        self.errors_seen: set[int] = set()
        self.active_ids: set[int] = set()        # queue tasks seen queued/running/paused
        self.chained_ids: set[int] = set()       # ... that belong to a subtitled-video row
        self.download_status: dict[int, str] = {}   # last status seen of each download row

    # TaskbarButtonCreated arrives on the Tk thread inside the window procedure: only note it.
    def on_button_created(self) -> None:
        self.button_created = True

    def clear_marker(self) -> None:
        marker, self.marker = self.marker, None
        if marker is not None:
            _remove_marker(marker)

    def recreate(self) -> bool:
        """After the taskbar button was (re)created: a fresh COM object, everything re-applied."""
        self.applied = None
        try:
            self.native.create()
        except Exception as exc:  # noqa: BLE001
            _note_failure("recreate", "Could not re-create the taskbar object: %s", exc)
            return False
        self.button_created = False
        self.failures = 0
        return True

    def apply(self, snap: Snapshot) -> bool:
        """Send what differs from ``self.applied``; True when every call succeeded."""
        old = self.applied
        native, hwnd = self.native, self.hwnd
        results: list[int] = []
        if old is None or old.state != snap.state:
            results.append(native.set_progress_state(hwnd, snap.state))
        if snap.state in (TBPF_NORMAL, TBPF_PAUSED, TBPF_ERROR) and (
                old is None or old.state != snap.state or old.value != snap.value):
            results.append(native.set_progress_value(hwnd, snap.value, 100))
        if old is None or old.badge != snap.badge:
            if snap.badge:
                text = f"{snap.badge} job" + ("" if snap.badge == 1 else "s")
                results.append(native.set_overlay(hwnd, badge_label(snap.badge), text))
            else:
                results.append(native.set_overlay(hwnd, None, ""))
        bad = [hr for hr in results if hr < 0]
        if bad:
            _note_failure("hresult", "Taskbar call refused (HRESULT %#x)", bad[0] & 0xFFFFFFFF)
            return False
        self.applied = snap
        return True


def _activate(root: Any) -> "_Controller | None":
    """Build the COM side for ``root`` behind the start marker; None when it cannot be done.

    The marker is written before the first COM call and handed to the controller, which removes
    it after the first real update went through.
    """
    global _session_off
    native: Any = None
    try:
        native = _native_factory()
        hwnd = native.top_window(int(root.winfo_id()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Windows taskbar integration is off for this session: %s", exc)
        _session_off = True
        return None
    if not hwnd:
        return None   # no frame window yet: try again at the next round
    try:
        path = marker_path()
    except Exception as exc:  # noqa: BLE001 - e.g. no usable profile folder
        logger.warning("Windows taskbar integration is off for this session: %s", exc)
        _session_off = True
        return None
    if marker_blocks(path) or not _write_marker(path):
        _session_off = True
        return None
    try:
        native.co_initialize()
        native.create()
        ctl = _Controller(root, native, hwnd, path)
        try:
            native.watch_button_created(hwnd, ctl.on_button_created)
        except Exception as exc:  # noqa: BLE001 - only the Explorer-restart recovery is lost
            _note_failure("watch", "Taskbar button hook not installed: %s", exc)
        # First use of the plain calls while the marker exists; the badge icon follows in the
        # first real update. The value goes first: SetProgressValue can switch a cleared button
        # to a (green, empty) bar, so the state call that clears it comes after.
        for hr in (native.set_progress_value(hwnd, 0, 100),
                   native.set_progress_state(hwnd, TBPF_NOPROGRESS),
                   native.set_overlay(hwnd, None, "")):
            if hr < 0:
                raise ComError(f"first taskbar call refused (HRESULT {hr & 0xFFFFFFFF:#x})")
    except Exception as exc:  # noqa: BLE001 - a failed set-up is handled, not a crash
        logger.warning("Windows taskbar integration is off for this session: %s", exc)
        _session_off = True
        native.close()
        _remove_marker(path)
        return None
    return ctl


def _is_withdrawn(root: Any) -> bool:
    try:
        return str(root.state()) == "withdrawn"
    except Exception:  # noqa: BLE001 - a destroyed window is not shown either
        return True


def _chime_on(root: Any) -> bool:
    """The existing "Chime on completion" setting: the one switch for every finish signal."""
    var = getattr(root, "chime_on_complete_var", None)
    if var is None:
        return False
    try:
        return bool(var.get())
    except Exception:  # noqa: BLE001
        return False


def _chained(task: Any) -> bool:
    """True for a transcription that is the middle stage of a "Make subtitled video" row."""
    return bool(getattr(getattr(task, "source_download", None), "make_subbed_video", False))


def _download_finished_for_user(item: Any, previous: str | None) -> bool:
    """A download row that just became "finished": did a user-visible job end well?

    The auto-transcribe hand-off sets the row to "finished" when the linked transcription ends
    however it ended (finished, failed, cancelled, model-load timeout), so ``transcribing`` ->
    ``finished`` says nothing: a successful transcription is reported by its own queue task.
    A subtitled-video row is done only after its burn.
    """
    if previous is None:
        return False
    if getattr(item, "make_subbed_video", False):
        return previous == "burning"
    return previous in ("waiting", "running", "paused")


def _track_jobs(ctl: _Controller, queue: list[Any], downloads: list[Any], now: float) -> bool:
    """Update the failure latch; True when a user job just finished well (one flash per round)."""
    finished = False
    alive: set[int] = set()
    for task in queue:
        key = id(task)
        alive.add(key)
        status = getattr(task, "status", "")
        if status in QUEUE_ACTIVE:
            ctl.active_ids.add(key)
            if _chained(task):
                ctl.chained_ids.add(key)
        elif status == "finished" and key in ctl.active_ids:
            ctl.active_ids.discard(key)
            # The transcription of a subtitled-video row is not the last stage.
            finished = finished or key not in ctl.chained_ids
        elif status in ("error", "cancelled"):
            ctl.active_ids.discard(key)
        if status == "error" and key not in ctl.errors_seen:
            ctl.errors_seen.add(key)
            ctl.error_since = now
    for item in downloads:
        key = id(item)
        alive.add(key)
        status = getattr(item, "status", "")
        previous = ctl.download_status.get(key)
        if status == "finished" and _download_finished_for_user(item, previous):
            finished = True
        ctl.download_status[key] = status
        if status == "error" and key not in ctl.errors_seen:
            ctl.errors_seen.add(key)
            ctl.error_since = now
    ctl.active_ids &= alive
    ctl.chained_ids &= alive
    ctl.errors_seen &= alive
    ctl.download_status = {k: v for k, v in ctl.download_status.items() if k in alive}
    return finished


def _clear_error_if_seen(ctl: _Controller, now: float) -> None:
    """The red bar goes when the failure is at least ``ERROR_MIN_SECONDS`` old and the window
    is in front now (so a user who was already looking still sees it for those seconds)."""
    if ctl.error_since is None or now - ctl.error_since < ERROR_MIN_SECONDS:
        return
    if ctl.native.is_foreground(ctl.hwnd):
        ctl.error_since = None


def _has_work(queue: list[Any], downloads: list[Any]) -> bool:
    """Something to show: a badge, a progress bar, or a failed job."""
    if summarize(queue, downloads) != Snapshot():
        return True
    return any(getattr(t, "status", "") == "error" for t in (*queue, *downloads))


def _failed_round(ctl: _Controller, reason: str) -> None:
    ctl.applied = None
    ctl.failures += 1
    if ctl.failures >= MAX_FAILURES:
        _give_up(f"{ctl.failures} rounds in a row failed ({reason})")


def sync(root: Any, *, now: float | None = None) -> None:
    """Bring the taskbar button in line with the queues of ``root``; call from the Tk thread.

    Cheap when called often: at most one round per ``MIN_INTERVAL`` does any work, and only a
    changed state reaches Windows. Never raises.
    """
    global _ctl
    if _closed:
        return
    # First, before anything is released or created: COM belongs to the Tk (main) thread.
    if threading.current_thread() is not threading.main_thread():
        _note_failure("thread", "Taskbar update refused: not on the main (Tk) thread")
        return
    if not enabled():
        _release()
        return
    now = time.monotonic() if now is None else now
    ctl = _ctl
    if ctl is not None and now - ctl.last_round < MIN_INTERVAL:
        return
    try:
        if _is_withdrawn(root):
            return
        if ctl is not None and ctl.root is not root:
            _release()
            ctl = None
        queue = list(getattr(root, "queue", ()) or ())
        downloads = list(getattr(root, "download_queue", ()) or ())
        if ctl is None:
            # Nothing to show yet: no COM, no marker, no cost for users who never queue a job.
            if not _has_work(queue, downloads):
                return
            ctl = _ctl = _activate(root)
            if ctl is None:
                return
        ctl.last_round = now
        finished = _track_jobs(ctl, queue, downloads, now)
        if ctl.button_created and not ctl.recreate():
            _failed_round(ctl, "re-creating the taskbar object")
            return
        _clear_error_if_seen(ctl, now)
        snap = summarize(queue, downloads, error=ctl.error_since is not None,
                         download_progress=getattr(root, "_download_row_progress", None))
        if finished and _chime_on(root) and not ctl.native.is_foreground(ctl.hwnd):
            ctl.native.flash(ctl.hwnd, FLASH_COUNT)
        if snap == ctl.applied:
            return
        try:
            ok = ctl.apply(snap)
        except Exception as exc:  # noqa: BLE001
            _note_failure("apply", "Taskbar update failed: %s", exc)
            ok = False
        # Reached only when the calls came back (a crash never returns): the set-up is proven.
        ctl.clear_marker()
        if ok:
            ctl.failures = 0
        else:
            _failed_round(ctl, "taskbar calls refused")
    except Exception as exc:  # noqa: BLE001 - the taskbar must never break the queue refresh
        _note_failure("sync", "Taskbar update failed: %s", exc)
        if _ctl is not None:
            _ctl.clear_marker()   # a Python error is not a crash; only a crash keeps the marker


def _give_up(reason: str) -> None:
    global _session_off
    logger.warning("Windows taskbar integration is off for this session: %s", reason)
    _session_off = True
    _release(clear=False)    # the taskbar is refusing calls: do not send it more


def _release(clear: bool = True) -> None:
    """Release the COM object, the window hook and the badge icons (idempotent).

    With ``clear`` the progress bar and the badge are taken off the button first (each call on
    its own, so a refusal skips nothing).
    """
    global _ctl
    ctl, _ctl = _ctl, None
    if ctl is None:
        return
    try:
        if clear and ctl.applied is not None:
            for call in (lambda: ctl.native.set_progress_state(ctl.hwnd, TBPF_NOPROGRESS),
                         lambda: ctl.native.set_overlay(ctl.hwnd, None, "")):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001
                    _note_failure("clear", "Could not clear the taskbar button: %s", exc)
        ctl.native.close()
    finally:
        ctl.clear_marker()


def shutdown() -> None:
    """Final clean-up before the window is destroyed; the integration cannot restart after it."""
    global _closed
    _closed = True
    try:
        _release()
    except Exception as exc:  # noqa: BLE001 - closing the window must always go on
        logger.warning("Taskbar clean-up failed: %s", exc)


def reset_for_tests() -> None:
    """Forget process-wide state (used by the autouse fixture in tests/conftest.py).

    Also blocks the real native layer: a test that wants it sets ``_native_factory`` itself.
    """
    global _config_enabled, _closed, _session_off, _native_factory
    try:
        _release(clear=False)
    except Exception:  # noqa: BLE001
        pass
    _config_enabled = True
    _closed = False
    _session_off = False
    _native_factory = _unavailable
    _failed.clear()
