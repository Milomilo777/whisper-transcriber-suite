"""macOS microphone permission: read its state, decide when to explain it, open its settings page.

macOS (10.14+) asks once, the first time an app opens the microphone. A user who answers "Don't
Allow" (or an administrator profile that forbids it) leaves the app recording pure silence with no
error anywhere. This module is the logic behind the notice that prevents that silent failure; the
dialog is ``app/dialogs/mac_permission.py``, the call sites are in ``app/widgets/live_tab.py``.

No pyobjc: the state is read through the Objective-C runtime with ``ctypes`` (as ``mac_native``
does for the key window). Every function returns a safe answer (``UNKNOWN``, ``None``, ``False``)
off macOS and when the runtime cannot be reached, and takes the platform and the system calls as
parameters so tests run anywhere.

Screen Recording is deliberately absent: no feature of this app captures the screen (system-audio
capture is a Windows-only WASAPI loopback), so there is nothing to ask for.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import subprocess
import sys
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

AUTHORIZED = "authorized"
DENIED = "denied"
RESTRICTED = "restricted"
NOT_DETERMINED = "not_determined"
UNKNOWN = "unknown"

#: The two reasons to show the notice.
REASON_FIRST_USE = "first_use"  # macOS is about to ask; say what it will ask and what to answer
REASON_BLOCKED = "blocked"  # denied, restricted, or the device delivers only silence

MICROPHONE_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")

# AVAuthorizationStatus, from AVFoundation/AVCaptureDevice.h.
_AV_STATUS = {0: NOT_DETERMINED, 1: RESTRICTED, 2: DENIED, 3: AUTHORIZED}
_AV_MEDIA_TYPE_AUDIO = b"soun"  # AVMediaTypeAudio


def is_macos() -> bool:
    return sys.platform == "darwin"


def _darwin(platform: Optional[str]) -> bool:
    return is_macos() if platform is None else platform == "darwin"


def _query_av_status() -> Optional[int]:
    """``[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio]`` or None."""
    path = ctypes.util.find_library("objc")
    if not path:
        return None
    lib = ctypes.CDLL(path)
    ctypes.CDLL("/System/Library/Frameworks/Foundation.framework/Foundation")
    ctypes.CDLL("/System/Library/Frameworks/AVFoundation.framework/AVFoundation")
    lib.objc_getClass.restype = ctypes.c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]
    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    ns_string = lib.objc_getClass(b"NSString")
    capture_device = lib.objc_getClass(b"AVCaptureDevice")
    if not ns_string or not capture_device:
        return None
    make_string = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(("objc_msgSend", lib))
    status_for = ctypes.CFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", lib))
    media_type = make_string(
        ns_string, lib.sel_registerName(b"stringWithUTF8String:"), _AV_MEDIA_TYPE_AUDIO)
    if not media_type:
        return None
    return int(status_for(
        capture_device, lib.sel_registerName(b"authorizationStatusForMediaType:"), media_type))


def microphone_status(*, platform: Optional[str] = None,
                      query: Optional[Callable[[], Optional[int]]] = None) -> str:
    """One of ``AUTHORIZED``, ``DENIED``, ``RESTRICTED``, ``NOT_DETERMINED``, ``UNKNOWN``."""
    if not _darwin(platform):
        return UNKNOWN
    try:
        code = (query or _query_av_status)()
    except (OSError, AttributeError, ctypes.ArgumentError, ValueError):
        logger.debug("Could not read the microphone permission", exc_info=True)
        return UNKNOWN
    return _AV_STATUS.get(code, UNKNOWN) if code is not None else UNKNOWN


def notice_reason(status: str, *, seen: bool, silent: bool = False,
                  platform: Optional[str] = None) -> Optional[str]:
    """Why to show the microphone notice now, or None.

    ``seen``: the first-use notice was shown before. ``silent``: the open microphone has delivered
    only silence (muted, or macOS withholding the audio). Never on Windows or Linux.
    """
    if not _darwin(platform):
        return None
    if silent or status in (DENIED, RESTRICTED):
        return REASON_BLOCKED
    if status in (NOT_DETERMINED, UNKNOWN) and not seen:
        return REASON_FIRST_USE
    return None


def open_microphone_settings(*, platform: Optional[str] = None,
                             run: Optional[Callable[..., Any]] = None) -> bool:
    """Open System Settings at Privacy & Security > Microphone; True when ``open`` accepted it."""
    if not _darwin(platform):
        return False
    try:
        if run is not None:
            done = run(
                ["open", MICROPHONE_SETTINGS_URL], check=False, timeout=10,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            done = subprocess.run(
                ["open", MICROPHONE_SETTINGS_URL], check=False, timeout=10,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        logger.warning("Could not open the microphone settings page", exc_info=True)
        return False
    return getattr(done, "returncode", 1) == 0
