"""Interface-language text for what ``core.model_manager`` returns in English."""
from __future__ import annotations

import re

from app.i18n import _

_SIZE_RE = re.compile(r"about (\d+(?:\.\d+)?) (MB|GB)")


def localize_size_text(text: str) -> str:
    """Translate the "about 500 MB" / "about 1.5 GB" text of ``approx_download_size_text``.

    The core module has no translation, so the interface calls this on what it returns.
    Any other text (including "") is returned unchanged.
    """
    match = _SIZE_RE.fullmatch(text)
    if match is None:
        return text
    if match.group(2) == "MB":
        return _("about {size} MB", size=match.group(1))
    return _("about {size} GB", size=match.group(1))
