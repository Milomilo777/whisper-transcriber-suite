"""Language names written in their own language and script.

Kept in an i18n module because it is translated text: every other module stays English-only.
Keys are the language codes of the video site's browse pages (``ch``/``gb`` for traditional and
simplified Chinese, ``jp``, ``kr``, ``vn``).
"""

NATIVE_NAMES: dict[str, str] = {
    "en": "English",
    "ar": "العربية",
    "bg": "Български",
    "ch": "中文（繁體）",
    "gb": "中文（简体）",
    "cs": "Čeština",
    "de": "Deutsch",
    "es": "Español",
    "fa": "فارسی",
    "fr": "Français",
    "hi": "हिन्दी",
    "hu": "Magyar",
    "id": "Bahasa Indonesia",
    "it": "Italiano",
    "jp": "日本語",
    "kr": "한국어",
    "ms": "Bahasa Melayu",
    "mn": "Монгол",
    "pl": "Polski",
    "pt": "Português",
    "pa": "ਪੰਜਾਬੀ",
    "ro": "Română",
    "ru": "Русский",
    "tl": "Tagalog",
    "te": "తెలుగు",
    "th": "ไทย",
    "uk": "Українська",
    "vn": "Tiếng Việt",
}
