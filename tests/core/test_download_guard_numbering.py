"""core.download_guard, round 2: format-id streams only, and the first free numbered name (ADR 0019)."""
from __future__ import annotations

import os

from core import download_guard as g

AUDIO = ["yt-dlp", "-o", os.path.join("D:/dl", "%(title)s.%(ext)s"), "-f", "ba", "-x",
         "--audio-format", "mp3", "--", "https://x.test/v"]


def _item(tmp_path, stem="T"):
    return g.PlannedItem(str(tmp_path / f"{stem}.webm"), str(tmp_path / f"{stem}.mp3"))


def test_subtitle_files_are_not_taken_for_format_streams(tmp_path):
    # The subtitle phase of the same job writes these before the media phase.
    for name in ("T.fa.vtt", "T.fr.srt", "T.fi.srt", "T.fil.srt", "T.film.mp4", "T.en-US.vtt"):
        (tmp_path / name).write_bytes(b"x")
    assert g.find_clash([_item(tmp_path)], []) is None


def test_real_format_stream_ids_still_count(tmp_path):
    for name in ("T.f137.mp4", "T.f251-drc.webm.part", "T.fhls-720.mp4.ytdl", "T.fdash-v1.mp4",
                 "T.fhttp-1080p.mp4"):
        (tmp_path / name).write_bytes(b"x")
        clash = g.find_clash([_item(tmp_path)], [])
        assert clash is not None and os.path.basename(clash) == name
        (tmp_path / name).unlink()


def test_numbered_item_gets_the_number_before_the_extension():
    item = g.PlannedItem("/d/T.webm", "/d/T.mp3")
    numbered = g.numbered(item, 2)
    assert numbered == g.PlannedItem("/d/T (2).webm", "/d/T (2).mp3")


def test_numbered_command_changes_only_the_output_template():
    command = g.numbered_command(AUDIO, 3)
    assert command[command.index("-o") + 1].endswith("%(title)s (3).%(ext)s")
    assert [a for a in command if a != command[command.index("-o") + 1]] == \
        [a for a in AUDIO if a != AUDIO[AUDIO.index("-o") + 1]]


def test_choose_number_is_the_first_free_one_across_final_partial_and_sidecars(tmp_path):
    (tmp_path / "T.mp3").write_bytes(b"x")                   # the taken plain name
    (tmp_path / "T (1).webm.part").write_bytes(b"x")          # a partial of number 1
    (tmp_path / "T (2).fr.srt").write_bytes(b"x")             # a sidecar of number 2
    assert g.choose_number([_item(tmp_path)], set(), set()) == 3


def test_choose_number_resumes_the_stem_the_job_owns(tmp_path):
    (tmp_path / "T (1).webm.part").write_bytes(b"x")
    owned = {g.stem_key(g.numbered(_item(tmp_path), 1))}
    assert g.choose_number([_item(tmp_path)], owned, set()) == 1


def test_choose_number_skips_names_other_running_jobs_hold(tmp_path):
    claimed = {g.stem_key(g.numbered(_item(tmp_path), 1))}
    assert g.choose_number([_item(tmp_path)], set(), claimed) == 2


def test_find_clash_skips_items_whose_stem_the_job_owns(tmp_path):
    (tmp_path / "T.webm.part").write_bytes(b"x")
    item = _item(tmp_path)
    assert g.find_clash([item], []) is not None
    assert g.find_clash([item], [], {g.stem_key(item)}) is None
