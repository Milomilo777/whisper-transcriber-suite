"""Recovered downloads must match canonically equivalent Unicode titles."""
import unicodedata
from types import SimpleNamespace

import pytest

from app.services.download_service import DownloadService, _name_key


@pytest.mark.parametrize("title", ["Caf\u00e9", "\uac00\ub098", "\u0386\u03bb\u03c6\u03b1"])
def test_recovery_matches_decomposed_filename(tmp_path, title):
    decomposed = unicodedata.normalize("NFD", title)
    saved = tmp_path / (decomposed + ".mp4")
    saved.write_bytes(b"video")
    task = SimpleNamespace(folder=str(tmp_path), title=title, start_time=0)
    service = DownloadService(SimpleNamespace())
    assert service._find_recovered_path(task, None) == (str(saved), False)
    assert _name_key(title) == _name_key(decomposed)


def test_symbol_only_title_does_not_take_foreign_file(tmp_path):
    foreign = tmp_path / "\U0001f3b5.mp4"
    foreign.write_bytes(b"other video")
    task = SimpleNamespace(folder=str(tmp_path), title="\U0001f3b6", start_time=0)
    service = DownloadService(SimpleNamespace())
    assert service._find_recovered_path(task, None) == (None, True)


def test_quote_replacement_and_non_latin_letters_still_match():
    assert _name_key("O\ufffdNeill") == _name_key("O\u2019Neill") == "oneill"
    assert _name_key("\u0635\u062f\u0627 \u06f1") == "\u0635\u062f\u0627\u06f1"


def test_short_title_with_replaced_symbol_still_matches(tmp_path):
    saved = tmp_path / "A_.mp4"
    saved.write_bytes(b"video")
    task = SimpleNamespace(folder=str(tmp_path), title="A\u2605", start_time=0)
    service = DownloadService(SimpleNamespace())
    assert service._find_recovered_path(task, None) == (str(saved), False)
