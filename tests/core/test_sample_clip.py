"""The bundled "Try it now" sample clip: the file, its working copy, and that every
packaging list ships it (see docs/SAMPLE_CLIP.md)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import sample_clip

_REPO = Path(__file__).resolve().parents[2]
_CLIP = _REPO / "assets" / sample_clip.SAMPLE_CLIP_NAME
_SPECS = (
    "whisper_project_onefile.spec",
    "whisper_project_onedir.spec",
    "platform/macos/pyinstaller/whisper_project_mac.spec",
)
_INSTALLERS = ("installer_embed.iss", "installer.iss")


def _read(rel: str) -> str:
    path = _REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not present in this checkout")
    return path.read_text(encoding="utf-8", errors="replace")


# ------------------------------------------------------------ the file

def test_the_clip_is_small_and_is_an_mp3():
    data = _CLIP.read_bytes()
    assert 20_000 < len(data) < 500_000
    # Either an ID3 tag or an MPEG audio frame sync starts a valid MP3 file.
    assert data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


def test_the_licence_and_credit_sit_in_docs():
    text = _read("docs/SAMPLE_CLIP.md")
    for needle in ("CC0", "Availle", "commons.wikimedia.org", "archive.org", "LibriVox"):
        assert needle in text


# ------------------------------------------------------------ lookup and copy

@pytest.fixture
def samples(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_clip, "samples_dir", lambda: tmp_path / "samples")
    return tmp_path / "samples"


def test_the_source_tree_clip_is_found():
    assert Path(sample_clip.bundled_clip_path() or "") == _CLIP


def test_the_working_copy_is_made_once_and_reused(samples):
    first = sample_clip.prepare_working_copy()
    assert first == str(samples / sample_clip.SAMPLE_CLIP_NAME)
    assert first is not None
    assert Path(first).read_bytes() == _CLIP.read_bytes()
    (samples / "sample_clip.json").write_text("[]", encoding="utf-8")  # a transcript beside it
    assert sample_clip.prepare_working_copy() == first
    assert (samples / "sample_clip.json").is_file()


def test_a_damaged_working_copy_is_replaced(samples):
    samples.mkdir()
    (samples / sample_clip.SAMPLE_CLIP_NAME).write_bytes(b"truncated")
    path = sample_clip.prepare_working_copy()
    assert Path(path or "").read_bytes() == _CLIP.read_bytes()


def test_a_missing_clip_gives_none_not_a_crash(samples, monkeypatch):
    monkeypatch.setattr(sample_clip, "bundled_clip_path", lambda: None)
    assert sample_clip.prepare_working_copy() is None
    assert not samples.exists()


def test_a_frozen_build_finds_the_clip_next_to_the_exe(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / sample_clip.SAMPLE_CLIP_NAME).write_bytes(b"x")
    monkeypatch.setattr(sample_clip.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sample_clip.sys, "executable", str(tmp_path / "App.exe"))
    assert sample_clip.bundled_clip_path() == str(tmp_path / "assets" / sample_clip.SAMPLE_CLIP_NAME)


# ------------------------------------------------------------ every list ships it

@pytest.mark.parametrize("spec", _SPECS)
def test_each_pyinstaller_spec_ships_the_clip_and_its_module(spec):
    text = _read(spec)
    # The whole assets folder is a data entry, which carries the clip.
    assert "'assets'), 'assets')" in text or "('assets', 'assets')" in text
    assert "'core.sample_clip'" in text


@pytest.mark.parametrize("script", _INSTALLERS)
def test_each_installer_names_the_clip(script):
    text = _read(script)
    assert 'Source: "assets\\' + sample_clip.SAMPLE_CLIP_NAME + '"' in text
