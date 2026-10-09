"""Info.plist ``CFBundleDocumentTypes`` of the macOS app (standard library only).

The spec loads this file by path (it cannot import the repository's packages),
and ``tests/test_mac_document_types.py`` imports it the same way.

The app declares itself a *Viewer* with ``LSHandlerRank`` *Alternate* for audio
and video, so Finder lists it under "Open With" and a drop on the Dock icon is
accepted, while it never becomes the default app for any file type.
Finder-opened files reach the app as Apple events handled by
``::tk::mac::OpenDocument`` (``app/mac_native.py``); PyInstaller's
``argv_emulation`` is not used because it conflicts with Tk.
"""
from __future__ import annotations

from typing import Iterable

# Extensions left out of the Finder declaration: ".ts" is TypeScript on a
# developer's Mac far more often than an MPEG transport stream.
EXCLUDED_EXTENSIONS = frozenset({"ts"})

# System types that already cover most audio and video (mp3, wav, m4a, aiff,
# mp4, mov, m4v, ...). The extension entry below adds what they do not name.
_SYSTEM_TYPES = (
    ("Audio file", "public.audio"),
    ("Video file", "public.movie"),
)


def document_types(media_extensions: Iterable[str]) -> list[dict[str, object]]:
    """The ``CFBundleDocumentTypes`` list for ``media_extensions`` (``".mp4"`` form)."""
    common = {"CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate"}
    entries: list[dict[str, object]] = [
        {"CFBundleTypeName": name, "LSItemContentTypes": [uti], **common}
        for name, uti in _SYSTEM_TYPES
    ]
    extensions = sorted(
        {e.lstrip(".").lower() for e in media_extensions} - EXCLUDED_EXTENSIONS
    )
    entries.append(
        {"CFBundleTypeName": "Audio or video file", "CFBundleTypeExtensions": extensions, **common}
    )
    return entries
