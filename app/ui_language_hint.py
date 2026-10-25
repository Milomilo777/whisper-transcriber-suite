"""First-run suggestion of an interface language (Windows only), decided from three hints.

The app shows English when Windows displays English or a language that has no catalog. A person
whose regional FORMAT (dates, numbers) and installed KEYBOARD point to a language the app speaks
probably prefers it, so the first run offers it once. All of these must hold:

  * no explicit ``ui_language`` is saved yet and the question was never answered,
  * the Windows display language itself is English (an unsupported display language that makes
    the app fall back to English does not count) and the app runs in English,
  * the regional format locale maps to a supported non-English language ``L``,
  * an installed keyboard layout is a layout of ``L``.

Anything missing or in conflict means no suggestion. The home region (GeoID) is never used and
nothing is looked up online. Every Win32 call is wrapped: a failure is "no hint" (debug log).
The decision (:func:`suggestion`) takes its inputs as arguments so every branch is testable.
"""
from __future__ import annotations

import locale
import logging
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

from app import i18n

logger = logging.getLogger(__name__)

#: Config key: True once the person answered (or dismissed) the question; never asked again.
HINT_KEY = "ui_language_hint_done"
_LOCALE_NAME_MAX = 85  # LOCALE_NAME_MAX_LENGTH


def read_format_locale(windll: Any = None) -> str | None:
    """The regional format locale name ("fa-IR") from GetUserDefaultLocaleName, or None."""
    try:
        if windll is None:
            import ctypes
            windll = getattr(ctypes, "windll")
        import ctypes
        buf = ctypes.create_unicode_buffer(_LOCALE_NAME_MAX)
        count = int(windll.kernel32.GetUserDefaultLocaleName(buf, _LOCALE_NAME_MAX))
        name = buf.value.strip() if count > 0 else ""
        return name or None
    except Exception:  # noqa: BLE001 - a hint is a nicety; any failure is "no hint"
        logger.debug("Could not read the regional format locale", exc_info=True)
        return None


def read_display_language(windll: Any = None) -> str | None:
    """The Windows display language as a tag ("en-US") from GetUserDefaultUILanguage, or None."""
    try:
        if windll is None:
            import ctypes
            windll = getattr(ctypes, "windll")
        langid = int(windll.kernel32.GetUserDefaultUILanguage())
        name = locale.windows_locale.get(langid) if langid else None
        return name.replace("_", "-") if name else None
    except Exception:  # noqa: BLE001
        logger.debug("Could not read the Windows display language", exc_info=True)
        return None


def read_keyboard_langids(windll: Any = None) -> list[int]:
    """Language IDs (LANGID, low word of each HKL) of the installed keyboard layouts, or []."""
    try:
        import ctypes
        if windll is None:
            windll = getattr(ctypes, "windll")
        user32 = windll.user32
        count = int(user32.GetKeyboardLayoutList(0, None))
        if count <= 0:
            return []
        handles = (ctypes.c_void_p * count)()
        got = int(user32.GetKeyboardLayoutList(count, handles))
        return [int(handles[i] or 0) & 0xFFFF for i in range(max(0, min(got, count)))]
    except Exception:  # noqa: BLE001
        logger.debug("Could not read the installed keyboard layouts", exc_info=True)
        return []


def _language_of_langid(langid: int) -> str | None:
    """The base language ("fa") of a Windows LANGID; any sublanguage of the same primary ID counts."""
    name = locale.windows_locale.get(langid)
    if name is None:
        primary = langid & 0x3FF
        for known, text in locale.windows_locale.items():
            if known & 0x3FF == primary:
                name = text
                break
    return name.split("_")[0].lower() if name else None


def keyboard_matches(code: str, langids: list[int]) -> bool:
    """True when one of the layouts (LANGIDs) is a layout of language ``code`` ("pt-BR" -> "pt")."""
    wanted = code.split("-")[0].lower()
    return any(_language_of_langid(i) == wanted for i in langids)


def suggestion(
    config: Mapping[str, Any],
    *,
    running_language: str,
    display_language: str | None,
    format_locale: str | None,
    keyboard_langids: list[int],
    available: Mapping[str, str],
) -> str | None:
    """The language code to suggest, or None. Pure: the caller passes what the machine reports."""
    if config.get(HINT_KEY):
        return None
    saved = config.get("ui_language", "auto")
    if str(saved if saved is not None else "").strip().lower() not in ("", "auto"):
        return None
    if running_language != i18n.SOURCE_LANGUAGE:
        return None
    # The display language itself must be English: the app also shows English for a display
    # language it has no catalog for, and that person did not choose English. Unknown = no hint.
    if not display_language or display_language.split("-")[0].lower() != "en":
        return None
    if not format_locale or not keyboard_langids:
        return None
    code = i18n.resolve_language("auto", os_language=format_locale, available=available)
    if code == i18n.SOURCE_LANGUAGE or code not in i18n.LANGUAGES_BY_CODE or code not in available:
        return None
    if not keyboard_matches(code, keyboard_langids):
        return None
    return code


def suggestion_for_this_machine(
    config: Mapping[str, Any],
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    read_display: Callable[[], str | None] = read_display_language,
    read_locale: Callable[[], str | None] = read_format_locale,
    read_keyboards: Callable[[], list[int]] = read_keyboard_langids,
) -> str | None:
    """:func:`suggestion` with the real readers; None off Windows or while WTS_UI_LANGUAGE is set."""
    try:
        if (platform or sys.platform) != "win32":
            return None
        if (os.environ if environ is None else environ).get(i18n.ENV_LANGUAGE, "").strip():
            return None
        return suggestion(
            config,
            running_language=i18n.current_language(),
            display_language=read_display(),
            format_locale=read_locale(),
            keyboard_langids=read_keyboards(),
            available=i18n.catalog_statuses(),
        )
    except Exception:  # noqa: BLE001
        logger.debug("Could not decide on an interface-language suggestion", exc_info=True)
        return None
