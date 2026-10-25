"""Crash salvage must find re-run output sets whose names are NFC or NFD Unicode.

Finished transcripts are irreplaceable: when a worker dies after writing ``name (1).srt``
and ``name (1).json``, the app records the run as finished only if it finds those files.
NTFS and ext4 keep NFC and NFD spellings apart, so the search must try both.
"""
from __future__ import annotations

import os
import time
import unicodedata
from types import SimpleNamespace

import pytest

from app.services.transcription_service import TranscriptionService

STEM = "cl" + "é" + "p à la française"  # accents that differ between NFC and NFD
NFC_STEM = unicodedata.normalize("NFC", STEM)
NFD_STEM = unicodedata.normalize("NFD", STEM)


def _service() -> TranscriptionService:
    return TranscriptionService(SimpleNamespace(app_config={"output_formats": ["srt", "json"]}))


def _require_distinct_spellings(folder) -> None:
    probe = folder / (NFD_STEM + ".probe")
    probe.write_text("x")
    if (folder / (NFC_STEM + ".probe")).exists():
        pytest.skip("this filesystem folds NFC and NFD names together")


def _write(folder, stem: str, suffix: str, text: str, mtime: float | None = None):
    path = folder / f"{stem}{suffix}"
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.mark.parametrize(
    "source_stem, output_stem",
    [(NFC_STEM, NFD_STEM), (NFD_STEM, NFC_STEM), (NFD_STEM, NFD_STEM)],
    ids=["nfc-source-nfd-outputs", "nfd-source-nfc-outputs", "nfd-everywhere"],
)
def test_rerun_set_is_found_whatever_the_unicode_form(tmp_path, source_stem, output_stem):
    _require_distinct_spellings(tmp_path)
    start = time.time() - 30.0
    (tmp_path / f"{source_stem}.mp4").touch()
    # The first run's files are kept and are older than this run: they must not count.
    _write(tmp_path, output_stem, ".srt", "old run", start - 600.0)
    _write(tmp_path, output_stem, ".json", "old run", start - 600.0)
    task = SimpleNamespace(file_path=str(tmp_path / f"{source_stem}.mp4"), start_time=start)
    assert _service()._are_outputs_complete(task) is False  # only the old run: nothing to salvage

    new_srt = _write(tmp_path, output_stem, " (1).srt", "this run")
    new_json = _write(tmp_path, output_stem, " (1).json", "{}")
    task = SimpleNamespace(file_path=str(tmp_path / f"{source_stem}.mp4"), start_time=start)
    assert _service()._are_outputs_complete(task) is True
    assert sorted(task.output_paths) == sorted([str(new_srt), str(new_json)])
    assert all(os.path.getsize(p) > 0 for p in task.output_paths)


def test_nfd_named_rerun_with_nonascii_folder(tmp_path):
    """Only the file name is re-spelled; the folder part must stay as the task gave it."""
    folder = tmp_path / NFC_STEM
    folder.mkdir()
    _require_distinct_spellings(folder)
    start = time.time() - 30.0
    nfd_name = unicodedata.normalize("NFD", "café")
    _write(folder, nfd_name, ".srt", "old run", start - 600.0)
    out = _write(folder, nfd_name, " (1).srt", "x")
    # source named like the outputs, but in the other spelling
    src = folder / (unicodedata.normalize("NFC", "café") + ".mp4")
    src.touch()
    task = SimpleNamespace(
        file_path=str(src), start_time=start, output_formats=["srt"],
    )
    assert _service()._are_outputs_complete(task) is True
    assert task.output_paths == [str(out)]


def test_other_unicode_form_directory_is_never_searched(tmp_path):
    """NFC and NFD folders are two folders: another folder's fresh files are not ours."""
    nfc_dir = tmp_path / NFC_STEM
    nfd_dir = tmp_path / NFD_STEM
    nfc_dir.mkdir()
    nfd_dir.mkdir()
    if nfc_dir.samefile(nfd_dir):
        pytest.skip("this filesystem folds NFC and NFD names together")
    start = time.time() - 30.0
    (nfc_dir / "clip.mp4").touch()
    _write(nfd_dir, "clip", ".srt", "someone else's")
    _write(nfd_dir, "clip", ".json", "{}")
    task = SimpleNamespace(file_path=str(nfc_dir / "clip.mp4"), start_time=start)
    assert _service()._are_outputs_complete(task) is False


def test_outputs_of_two_sources_are_never_mixed_into_one_set(tmp_path):
    """NFC '(1).srt' from one source and NFD '(1).json' from another is not a complete set."""
    _require_distinct_spellings(tmp_path)
    start = time.time() - 30.0
    (tmp_path / f"{NFC_STEM}.mp4").touch()
    _write(tmp_path, NFC_STEM, ".srt", "old", start - 600.0)
    _write(tmp_path, NFC_STEM, ".json", "{}", start - 600.0)
    _write(tmp_path, NFC_STEM, " (1).srt", "this run, srt only")
    _write(tmp_path, NFD_STEM, " (1).json", "{}")  # another source's file
    task = SimpleNamespace(file_path=str(tmp_path / f"{NFC_STEM}.mp4"), start_time=start)
    assert _service()._are_outputs_complete(task) is False


def test_two_spellings_with_files_are_ambiguous_and_not_salvaged(tmp_path):
    _require_distinct_spellings(tmp_path)
    start = time.time() - 30.0
    (tmp_path / f"{NFC_STEM}.mp4").touch()
    for stem in (NFC_STEM, NFD_STEM):
        _write(tmp_path, stem, ".srt", "fresh")
        _write(tmp_path, stem, ".json", "{}")
    task = SimpleNamespace(file_path=str(tmp_path / f"{NFC_STEM}.mp4"), start_time=start)
    assert _service()._are_outputs_complete(task) is False
