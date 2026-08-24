"""Language tables shared across the UI and download services."""
from __future__ import annotations

# Display name → comma-separated yt-dlp subtitle language codes.
# Order: Automatic, English, then alphabetical by display name. Multi-variant
# entries collapse the codes YouTube actually uses (e.g. zh-Hans + zh-CN).
SUBTITLE_LANGUAGES: list[tuple[str, str]] = [
    ("Automatic", ""),
    ("English", "en"),
    ("Afrikaans", "af"),
    ("Albanian", "sq"),
    ("Amharic", "am"),
    ("Arabic", "ar"),
    ("Armenian", "hy"),
    ("Azerbaijani", "az"),
    ("Basque", "eu"),
    ("Belarusian", "be"),
    ("Bengali", "bn"),
    ("Bosnian", "bs"),
    ("Bulgarian", "bg"),
    ("Catalan", "ca"),
    ("Cebuano", "ceb"),
    ("Chinese (Simplified)", "zh-Hans,zh-CN"),
    ("Chinese (Traditional)", "zh-Hant,zh-TW"),
    ("Corsican", "co"),
    ("Croatian", "hr"),
    ("Czech", "cs"),
    ("Danish", "da"),
    ("Dutch", "nl"),
    ("Esperanto", "eo"),
    ("Estonian", "et"),
    ("Finnish", "fi"),
    ("French", "fr"),
    ("Frisian", "fy"),
    ("Galician", "gl"),
    ("Georgian", "ka"),
    ("German", "de"),
    ("Greek", "el"),
    ("Gujarati", "gu"),
    ("Haitian Creole", "ht"),
    ("Hausa", "ha"),
    ("Hawaiian", "haw"),
    ("Hebrew", "iw"),
    ("Hindi", "hi"),
    ("Hmong", "hmn"),
    ("Hungarian", "hu"),
    ("Icelandic", "is"),
    ("Igbo", "ig"),
    ("Indonesian", "id"),
    ("Irish", "ga"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Javanese", "jv"),
    ("Kannada", "kn"),
    ("Kazakh", "kk"),
    ("Khmer", "km"),
    ("Korean", "ko"),
    ("Kurdish", "ku"),
    ("Kyrgyz", "ky"),
    ("Lao", "lo"),
    ("Latin", "la"),
    ("Latvian", "lv"),
    ("Lithuanian", "lt"),
    ("Luxembourgish", "lb"),
    ("Macedonian", "mk"),
    ("Malagasy", "mg"),
    ("Malay", "ms"),
    ("Malayalam", "ml"),
    ("Maltese", "mt"),
    ("Maori", "mi"),
    ("Marathi", "mr"),
    ("Mongolian", "mn"),
    ("Myanmar (Burmese)", "my"),
    ("Nepali", "ne"),
    ("Norwegian", "no"),
    ("Nyanja (Chichewa)", "ny"),
    ("Pashto", "ps"),
    ("Persian", "fa"),
    ("Polish", "pl"),
    ("Portuguese (Portugal, Brazil)", "pt"),
    ("Punjabi", "pa"),
    ("Romanian", "ro"),
    ("Russian", "ru"),
    ("Samoan", "sm"),
    ("Scots Gaelic", "gd"),
    ("Serbian", "sr"),
    ("Sesotho", "st"),
    ("Shona", "sn"),
    ("Sindhi", "sd"),
    ("Sinhala (Sinhalese)", "si"),
    ("Slovak", "sk"),
    ("Slovenian", "sl"),
    ("Somali", "so"),
    ("Spanish", "es"),
    ("Sundanese", "su"),
    ("Swahili", "sw"),
    ("Swedish", "sv"),
    ("Tagalog (Filipino)", "tl"),
    ("Tajik", "tg"),
    ("Tamil", "ta"),
    ("Telugu", "te"),
    ("Thai", "th"),
    ("Turkish", "tr"),
    ("Ukrainian", "uk"),
    ("Urdu", "ur"),
    ("Uzbek", "uz"),
    ("Vietnamese", "vi"),
    ("Welsh", "cy"),
    ("Xhosa", "xh"),
    ("Yiddish", "yi"),
    ("Yoruba", "yo"),
    ("Zulu", "zu"),
]


def subtitle_lang_args(lang: str) -> str:
    """Convert a comma-separated lang spec to the form yt-dlp's ``--sub-langs`` accepts.

    Trims whitespace and drops empty entries. Returns the empty string if
    nothing is left.
    """
    codes = [c.strip() for c in (lang or "").split(",") if c.strip()]
    return ",".join(codes)


def resolve_caption_kind(
    caption_langs: dict[str, str], lang_codes_csv: str, fallback_lang: str = "",
) -> str:
    """"manual", "auto", or "" for whichever candidate code first matches.

    *caption_langs* maps a caption language code to ``"manual"`` or
    ``"auto"`` (see ``app.services.format_service.caption_lang_map``).
    *lang_codes_csv* is a ``SUBTITLE_LANGUAGES``-style comma list (one
    entry can cover several codes, e.g. ``"zh-Hans,zh-CN"``); an empty
    string means "Automatic", so *fallback_lang* -- the format lookup's
    best-effort detected language -- is tried instead. This mirrors how
    the existing subtitle-download feature resolves "Automatic"
    (``DownloadService.resolve_subtitle_lang``: ``task.subtitle_lang or
    task.detected_language``), so the "use captions instead" shortcut
    always agrees with what the checkbox+combo would have fetched.
    """
    if not caption_langs:
        return ""
    candidates = [c.strip() for c in (lang_codes_csv or "").split(",") if c.strip()]
    if not candidates and fallback_lang:
        candidates = [fallback_lang.strip()]
    for code in candidates:
        kind = caption_langs.get(code, "")
        if kind:
            return kind
    return ""
