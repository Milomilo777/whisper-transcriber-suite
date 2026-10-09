"""core.paths.same_file / path_key: one file, however the platform spells its name.

Windows and macOS (APFS, the default) volumes ignore case, so ``T.JSON`` and ``t.json`` are
one file. ``os.path.normcase`` only folds case on Windows, so these tests make it behave as on
POSIX to show the helpers do not depend on it.
"""
from __future__ import annotations

import posixpath

import pytest

from core import paths


@pytest.fixture
def posix_normcase(monkeypatch):
    """normcase as on macOS/Linux: the identity."""
    monkeypatch.setattr(paths.os.path, "normcase", posixpath.normcase)


def _case_insensitive(tmp_path) -> bool:
    probe = tmp_path / "CaseProbe.txt"
    probe.write_text("x", encoding="utf-8")
    return (tmp_path / "caseprobe.txt").exists()


def test_same_file_sees_a_case_variant_of_an_existing_file(tmp_path, posix_normcase):
    if not _case_insensitive(tmp_path):
        pytest.skip("case-sensitive volume: a case variant is another file")
    target = tmp_path / "t.json"
    target.write_text("[]", encoding="utf-8")
    assert paths.same_file(str(target), str(target).upper())


def test_same_file_keeps_different_files_apart(tmp_path, posix_normcase):
    one = tmp_path / "a.json"
    two = tmp_path / "b.json"
    one.write_text("1", encoding="utf-8")
    two.write_text("2", encoding="utf-8")
    assert not paths.same_file(str(one), str(two))
    assert not paths.same_file(str(one), str(tmp_path / "missing.json"))


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_path_key_folds_case_where_volumes_ignore_it(monkeypatch, posix_normcase, platform):
    monkeypatch.setattr(paths.sys, "platform", platform)
    assert paths.path_key("/Media/Talk.JSON") == paths.path_key("/media/talk.json")


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_path_key_does_not_merge_names_the_volume_keeps_apart(monkeypatch, posix_normcase,
                                                            platform):
    """Full case folding maps the German sharp s to "ss"; NTFS and APFS do not, so two
    different files must not share a key (the wrong viewer window, a refused share name)."""
    monkeypatch.setattr(paths.sys, "platform", platform)
    sharp = "/media/Stra" + chr(0xDF) + "e.json"
    assert paths.path_key(sharp) != paths.path_key("/media/Strasse.json")


def test_path_key_stays_case_sensitive_on_linux(monkeypatch, posix_normcase):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths.path_key("/Media/Talk.JSON") != paths.path_key("/media/talk.json")


def test_same_file_falls_back_to_the_key_for_a_name_not_on_disk(tmp_path, monkeypatch,
                                                              posix_normcase):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert paths.same_file(str(tmp_path / "New.HTML"), str(tmp_path / "new.html"))


def test_burn_output_keys_ignore_case_on_macos(monkeypatch, posix_normcase):
    from core import burn_subs

    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert burn_subs._output_key("/Out/Movie.MP4") == burn_subs._output_key("/out/movie.mp4")


def test_viewer_keys_keep_a_sharp_s_name_apart_from_its_ss_spelling(monkeypatch, posix_normcase):
    from app.dialogs import transcript_viewer as tv

    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert tv._viewer_key("/m/Stra" + chr(0xDF) + "e.json") != tv._viewer_key("/m/Strasse.json")


def test_one_transcript_viewer_key_per_file_on_macos(monkeypatch, posix_normcase):
    from app.dialogs import transcript_viewer as tv

    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert tv._viewer_key("/Media/Talk.json") == tv._viewer_key("/media/TALK.json")
