"""core.download_guard: the pure rules of which files a desktop download may touch (ADR 0019)."""
from __future__ import annotations

import os

import pytest

from core import download_guard as g

AUDIO = ["yt-dlp", "-o", "D:/dl/%(title)s.%(ext)s", "--no-playlist", "-f", "ba/bestaudio",
         "-x", "--audio-format", "mp3", "--", "https://x.test/v"]
VIDEO = ["yt-dlp", "--newline", "--progress-template", "%(progress)j", "-o", "D:/dl/%(title)s.%(ext)s",
         "-f", "(bv*)+(ba)/best", "--merge-output-format", "mp4", "--", "https://x.test/v"]


def test_audio_format_only_when_extracting_audio():
    assert g.command_audio_format(AUDIO) == "mp3"
    assert g.command_audio_format(VIDEO) is None
    assert g.command_audio_format(["yt-dlp", "--audio-format", "mp3", "--", "u"]) is None


def test_plan_command_prints_the_file_name_and_downloads_nothing():
    plan = g.plan_command(VIDEO)
    assert plan[plan.index("--print") + 1] == g.PLAN_PREFIX + "%(filename)s"
    assert "--progress-template" not in plan and "%(progress)j" not in plan
    assert plan[-2:] == ["--", "https://x.test/v"]          # the URL stays after the separator
    assert plan.index("--print") < plan.index("--")


def test_keep_source_only_for_audio_and_before_the_separator():
    kept = g.with_keep_source(AUDIO)
    assert kept.index("-k") < kept.index("--")
    assert g.with_keep_source(kept) == kept                   # idempotent
    assert g.with_keep_source(VIDEO) == VIDEO


def test_parse_plan_audio_item_has_source_and_final():
    out = f"noise\n{g.PLAN_PREFIX}D:\\dl\\Title A.webm\n"
    (item,) = g.parse_plan(out, AUDIO)
    assert item.source == "D:\\dl\\Title A.webm"
    assert item.final == os.path.join("D:\\dl", "Title A.mp3") or item.final.endswith("Title A.mp3")


def test_parse_plan_aac_and_vorbis_use_the_container_yt_dlp_writes():
    aac = [*AUDIO[:-3], "aac", "--", "u"]
    assert g.parse_plan(f"{g.PLAN_PREFIX}/d/T.webm", aac)[0].final.endswith("T.m4a")
    vorbis = [*AUDIO[:-3], "vorbis", "--", "u"]
    assert g.parse_plan(f"{g.PLAN_PREFIX}/d/T.webm", vorbis)[0].final.endswith("T.ogg")


def test_parse_plan_video_item_is_one_file_and_playlist_has_many():
    out = f"{g.PLAN_PREFIX}/d/A.mp4\n{g.PLAN_PREFIX}/d/B.mp4\n"
    items = g.parse_plan(out, VIDEO)
    assert [i.final for i in items] == ["/d/A.mp4", "/d/B.mp4"]
    assert all(i.source == i.final for i in items)


def test_parse_plan_ignores_lines_without_the_marker():
    assert g.parse_plan("[youtube] x: Downloading\nWARNING: y\n", VIDEO) == []


def _item(tmp_path, name="T", src_ext="webm", final_ext="mp3"):
    return g.PlannedItem(str(tmp_path / f"{name}.{src_ext}"), str(tmp_path / f"{name}.{final_ext}"))


def test_find_clash_free_folder_is_none(tmp_path):
    assert g.find_clash([_item(tmp_path)], []) is None


@pytest.mark.parametrize("leftover", [
    "T.mp3", "T.webm", "T.webm.part", "T.webm.ytdl", "T.webm.part-Frag3", "T.mp3.part",
    "T.f137.mp4", "T.f137.mp4.part", "T.fhls-720.mp4.ytdl",
])
def test_find_clash_names_every_file_the_job_would_use_or_resume(tmp_path, leftover):
    (tmp_path / leftover).write_bytes(b"x")
    clash = g.find_clash([_item(tmp_path)], [])
    assert clash is not None and os.path.basename(clash) == leftover


def test_find_clash_ignores_unrelated_names(tmp_path):
    for name in ("Tx.mp3", "T2.webm", "T.other.mp4.bak", "other.txt", "t.mp3.bak"):
        (tmp_path / name).write_bytes(b"x")
    assert g.find_clash([_item(tmp_path)], []) is None


def test_find_clash_skips_files_the_job_created_earlier(tmp_path):
    (tmp_path / "T.webm").write_bytes(b"x")
    (tmp_path / "T.webm.part").write_bytes(b"x")
    own = [str(tmp_path / "T.webm")]
    assert g.find_clash([_item(tmp_path)], own) is None
    (tmp_path / "T.mp3").write_bytes(b"x")                   # not announced by the job
    assert g.find_clash([_item(tmp_path)], own) is not None


def test_is_own_covers_the_file_and_its_unfinished_pieces():
    own = ["/d/T.webm"]
    assert g.is_own("/d/T.webm", own)
    assert g.is_own("/d/T.webm.part", own)
    assert g.is_own("/d/T.webm.part-Frag2", own)
    assert g.is_own("/d/T.webm.ytdl", own)
    assert not g.is_own("/d/T.webm.bak", own)
    assert not g.is_own("/d/T2.webm", own)


def test_has_partial_sees_unfinished_pieces_only(tmp_path):
    stem = g.norm(str(tmp_path / "Title"))
    assert not g.has_partial(stem)
    for name in ("Title.mp4", "Title.fr.srt", "Title (1).mp4.part", "Title2.mp4.part"):
        (tmp_path / name).write_bytes(b"x")                   # finished file, sidecar, other names
    assert not g.has_partial(stem)
    (tmp_path / "Title.f137.mp4").write_bytes(b"x")           # one stream of an unfinished merge
    assert g.has_partial(stem)
    (tmp_path / "Title.f137.mp4").unlink()
    (tmp_path / "Title.mp4.part").write_bytes(b"x")
    assert g.has_partial(stem)
    assert not g.has_partial(g.norm(str(tmp_path / "gone" / "Title")))   # missing folder


def test_is_own_matches_the_unfinished_pieces_exactly():
    own = ["/d/T.webm"]
    assert g.is_own("/d/T.webm.part", own) and g.is_own("/d/T.webm.part-Frag12", own)
    assert not g.is_own("/d/T.webm.partial", own)         # a user's file that only starts like a piece
    assert not g.is_own("/d/T.webm.ytdl.bak", own)
    assert not g.is_own("/d/T.webm.part-Fragment", own)


def test_is_own_takes_yt_dlps_mixed_case_fragment_name_where_paths_keep_their_case(monkeypatch):
    # macOS and Linux do not fold case in norm(); yt-dlp writes "<file>.part-Frag3" (downloader/fragment.py).
    monkeypatch.setattr(g, "norm", lambda p: p)
    own = ["/d/T.webm"]
    assert g.is_own("/d/T.webm.part-Frag3", own)
    assert g.is_own("/d/T.webm.part", own) and g.is_own("/d/T.webm.ytdl", own)
    assert not g.is_own("/d/T.webm.partial", own)
