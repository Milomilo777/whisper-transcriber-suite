"""The model download size ("about 500 MB") is shown in the interface language."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import i18n
from app.model_text import localize_size_text


@pytest.fixture(autouse=True)
def _catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    folder = tmp_path / "locales"
    folder.mkdir()
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    monkeypatch.setattr(i18n, "_WARNED", set())
    lang = i18n.LANGUAGES_BY_CODE["de"]
    doc = {"_meta": {"code": "de", "name": lang.endonym, "direction": "ltr", "status": "reviewed",
                     "plural": lang.plural},
           "messages": {"about {size} MB": "etwa {size} MB", "about {size} GB": "etwa {size} GB"}}
    (folder / "de.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    i18n.set_language("de")
    yield
    i18n.set_language("en")


@pytest.mark.parametrize("english, shown", [
    ("about 500 MB", "etwa 500 MB"),
    ("about 1.5 GB", "etwa 1.5 GB"),
    ("about 3 GB", "etwa 3 GB"),
    ("", ""),
    ("unknown", "unknown"),       # anything else passes through
])
def test_localize_size_text(english: str, shown: str) -> None:
    assert localize_size_text(english) == shown
