"""One media-extension list: the viewer pairs what the watcher accepts."""
from __future__ import annotations

from core import watcher
from core.media_types import MEDIA_EXTENSIONS


def test_every_extension_the_watcher_accepts_is_in_the_shared_list():
    assert set(watcher._MEDIA_EXTENSIONS) <= set(MEDIA_EXTENSIONS)


def test_the_list_is_lowercase_dotted_and_free_of_duplicates():
    assert all(e.startswith(".") and e == e.lower() for e in MEDIA_EXTENSIONS)
    assert len(set(MEDIA_EXTENSIONS)) == len(MEDIA_EXTENSIONS)


def test_the_viewer_uses_the_shared_list():
    from app.dialogs import transcript_viewer as tv

    assert tv._MEDIA_EXTENSIONS is MEDIA_EXTENSIONS
