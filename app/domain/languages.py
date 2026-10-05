"""Language tables shared across the UI and download services."""
from __future__ import annotations

import re
from collections.abc import Iterable

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


# yt-dlp interprets every ``--sub-langs`` entry as a regular expression (its
# own docs example is ``--sub-langs "en.*,ja"``), which is why this app used
# to ship ``en.*`` and download seven translated caption files instead of one
# (see docs/auto-subtitles-feature.md). The table above only ever wants an
# EXACT code, so any regex metacharacter is escaped before the value reaches
# yt-dlp. This matters because the code can come from video metadata:
# ``app.services.format_service`` copies yt-dlp's ``language`` field straight
# out of the site's JSON, so a crafted/odd value like ``.*`` would match every
# caption track while a malformed one like ``en(`` is not a valid pattern at
# all. Hyphen is deliberately NOT escaped — it is a literal outside a
# character class, and every real code (``zh-Hans``, ``pt-BR``) must pass
# through unchanged.
_SUB_LANG_REGEX_METACHARS = re.compile(r"([.^$*+?{}\[\]\\|()])")


def subtitle_lang_args(lang: str) -> str:
    """Convert a comma-separated lang spec to the form yt-dlp's ``--sub-langs`` accepts.

    Trims whitespace, drops empty entries, and escapes regex metacharacters
    so yt-dlp matches each code literally instead of treating it as a
    pattern. Returns the empty string if nothing is left.
    """
    codes = [c.strip() for c in (lang or "").split(",") if c.strip()]
    return ",".join(_SUB_LANG_REGEX_METACHARS.sub(r"\\\1", c) for c in codes)


CAPTION_BAR_MAX_LANGUAGES = 6
_AUTO_ORIGINAL_SUFFIX = "-orig"


def caption_language_name(code: str) -> str:
    """Display name for a yt-dlp caption code: ``"es"`` -> ``"Spanish"``, else the code."""
    base = code[: -len(_AUTO_ORIGINAL_SUFFIX)] if code.endswith(_AUTO_ORIGINAL_SUFFIX) else code
    for name, codes in SUBTITLE_LANGUAGES:
        entries = [c.strip() for c in codes.split(",") if c.strip()]
        if base in entries:
            return name.split(" (")[0]
    head = base.split("-")[0]
    if head != base:
        for name, codes in SUBTITLE_LANGUAGES:
            if head in [c.strip() for c in codes.split(",")]:
                return name.split(" (")[0]
    return base


def real_caption_langs(caption_langs: dict[str, str]) -> dict[str, str]:
    """Drop YouTube's automatic translations when the real speech-recognition track exists.

    YouTube lists an automatic translation into every language beside the one real
    track (``xx-orig``, with ``xx`` itself as its alias). When that track is present
    only it and its alias are kept, so "available" never means "machine-translated".
    """
    originals = {c for c, kind in caption_langs.items() if kind == "auto" and c.endswith(_AUTO_ORIGINAL_SUFFIX)}
    if not originals:
        return caption_langs
    keep = originals | {c[: -len(_AUTO_ORIGINAL_SUFFIX)] for c in originals}
    return {c: kind for c, kind in caption_langs.items() if kind != "auto" or c in keep}


def caption_availability_text(
    caption_langs: dict[str, str], prefer: Iterable[str] = (),
) -> str:
    """One line naming the languages that already have subtitles, or ``""`` for none.

    *caption_langs* is the ``code -> "manual" / "auto"`` map of the format lookup.
    Subtitles made by the uploader come first, automatic ones after. YouTube lists
    an automatic translation into every language next to the one real speech
    recognition track (``xx-orig``); when such a track exists only it is shown, so
    the line never claims a hundred languages. At most ``CAPTION_BAR_MAX_LANGUAGES``
    are named, the rest are counted. Languages in *prefer* (the chosen subtitle
    language, the video's own) are named first, so a video with forty uploader
    subtitle tracks does not open with whichever sorts first.
    """
    if not caption_langs:
        return ""
    caption_langs = real_caption_langs(caption_langs)
    manual = [c for c, kind in caption_langs.items() if kind == "manual"]
    automatic = [c for c, kind in caption_langs.items() if kind == "auto"]
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for codes, label in ((manual, "made by the uploader"), (automatic, "automatic")):
        for code in codes:
            name = caption_language_name(code)
            if name not in seen:
                seen.add(name)
                entries.append((name, label))
    if not entries:
        return ""
    wanted = [caption_language_name(code) for code in prefer if code]
    entries.sort(key=lambda e: wanted.index(e[0]) if e[0] in wanted else len(wanted))
    shown = entries[:CAPTION_BAR_MAX_LANGUAGES]
    text = ", ".join(f"{name} ({label})" for name, label in shown)
    extra = len(entries) - len(shown)
    if extra > 0:
        text += f" and {extra} more"
    return f"Subtitles available: {text}"


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
    caption_langs = real_caption_langs(caption_langs)
    candidates = [c.strip() for c in (lang_codes_csv or "").split(",") if c.strip()]
    if not candidates and fallback_lang:
        candidates = [fallback_lang.strip()]
    for code in candidates:
        kind = caption_langs.get(code, "")
        if kind:
            return kind
    return ""
