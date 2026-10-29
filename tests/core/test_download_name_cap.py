"""The title part of every yt-dlp output template is capped (Errno 22 on a 330-character title).

A Facebook "title" is the view count, the reactions and the whole post text; the file name built
from it exceeded NTFS's 255 UTF-16 units per name, so yt-dlp failed with "[Errno 22] Invalid
argument" on the ``.f<id>v.mp4.part`` file and on the caption file. The templates now use yt-dlp's
own ``%(title).<N>B`` (UTF-8 bytes, an upper bound of the UTF-16 units) with N computed from the
folder length. No Tk, no network.
"""
from __future__ import annotations

import os
import re

import pytest

from app.domain.tasks import VideoDownloadTask
from app.services import download_service as ds
from core import download_guard

# The shape of the real title from the log: view count, middle dot, fullwidth bar, emoji, author.
LONG_TITLE = (
    "134K views \u00b7 6.2K reactions \uff5c How to create an ASCII block effect "
    + "with plain text characters and a little patience \U0001F600 " * 5
    + "\uff5c Tim Hosqo"
)
assert len(LONG_TITLE) > 300

# The longest things yt-dlp and the app put after the title.
SUFFIXES = (
    ".f3520236458150143v.mp4.part",
    ".f3520236458150143v.mp4.part-Frag99999",
    " (9999).f3520236458150143v.webm.part",
    ".zh-Hans-CN.vtt",
    " (9999).en_US.vtt",
    ".smtv.docx",
)
FOLDER = r"C:\Users\Owner\Desktop\New folder"


def _task(folder: str = FOLDER, **kw) -> VideoDownloadTask:
    return VideoDownloadTask(
        url="https://www.facebook.com/share/r/abc/",
        folder=folder,
        format_label="x",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio", "format_id": "140"},
            "video": {"kind": "best_video", "format_id": "137"},
        },
        **kw,
    )


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _expand(template: str, title: str, ext: str = "mp4") -> str:
    """What yt-dlp makes of ``%(title).<N>B`` / ``%(title)s`` (YoutubeDL.prepare_outtmpl): the title
    cut to N UTF-8 bytes, a partly cut character dropped."""
    def sub(m: re.Match) -> str:
        n = m.group(1)
        raw = title.encode("utf-8")
        return (raw[: int(n)] if n else raw).decode("utf-8", "ignore")

    out = re.sub(r"%\(title\)(?:\.(\d+)B|s)", sub, template)
    return out.replace("%(ext)s", ext)


def _check_fits(template: str, folder: str, windows_path_limit: int = 259) -> None:
    name = os.path.basename(template.replace("\\", "/"))
    for suffix in SUFFIXES:
        stem = _expand(name, LONG_TITLE)
        # drop the final ".mp4" of the expanded template, then add what yt-dlp appends
        stem = stem[: -len(".mp4")]
        full = stem + suffix
        assert _units(full) <= 255, (suffix, _units(full))
        assert _units(folder) + 1 + _units(full) <= windows_path_limit, (suffix, _units(folder) + 1 + _units(full))


def _o(command: list[str]) -> str:
    return command[command.index("-o") + 1]


def test_budget_shrinks_with_folder_length_and_keeps_a_minimum():
    short = ds.title_byte_budget(r"C:\dl", windows=True)
    deep = ds.title_byte_budget("C:\\" + "x" * 120, windows=True)
    absurd = ds.title_byte_budget("C:\\" + "x" * 400, windows=True)
    assert short > deep > absurd
    assert absurd == 40
    assert short <= 255 - 40
    assert ds.title_byte_budget("/home/me/dl", windows=False) > 150


def test_download_template_caps_the_title_and_the_real_title_fits():
    cmd = ds.build_download_command(_task(), yt_dlp_path="y", bin_path="")
    out = _o(cmd)
    assert re.search(r"%\(title\)\.\d+B\.%\(ext\)s$", out)
    _check_fits(out, FOLDER)


def test_section_clip_template_reserves_room_for_the_clip_tag():
    cmd = ds.build_download_command(_task(section_start=51.0, section_end=85.0), yt_dlp_path="y", bin_path="")
    out = _o(cmd)
    assert "(clip 0.00.51-0.01.25)" in out
    _check_fits(out, FOLDER)


def test_caption_template_caps_the_title_and_the_numbered_form_still_fits():
    plain = ds.build_subtitle_command(_task(), "en", yt_dlp_path="y", bin_path="")
    numbered = ds.build_subtitle_command(_task(), "en", yt_dlp_path="y", bin_path="", number=9999)
    for cmd in (plain, numbered):
        assert re.search(r"%\(title\)\.\d+B( \(\d+\))?\.%\(ext\)s$", _o(cmd))
        _check_fits(_o(cmd), FOLDER)


def test_numbering_keeps_the_cap_and_adds_the_number_after_it():
    cmd = ds.build_download_command(_task(), yt_dlp_path="y", bin_path="")
    n = download_guard.numbered_command(cmd, 12)
    assert re.search(r"%\(title\)\.\d+B \(12\)\.%\(ext\)s$", _o(n))
    _check_fits(_o(n), FOLDER)


def test_a_deep_folder_leaves_less_room_but_the_whole_path_still_fits():
    folder = "C:\\" + "d" * 100 + "\\" + "e" * 60
    cmd = ds.build_download_command(_task(folder), yt_dlp_path="y", bin_path="")
    _check_fits(_o(cmd), folder)


def test_short_titles_are_not_touched():
    out = _o(ds.build_download_command(_task(), yt_dlp_path="y", bin_path=""))
    assert _expand(os.path.basename(out.replace("\\", "/")), "Title A") == "Title A.mp4"


def test_the_recovery_match_uses_the_trimmed_title():
    # The file on disk carries the capped title; the task keeps the full one.
    budget = ds.title_byte_budget(FOLDER)
    trimmed = ds.trim_title(LONG_TITLE, budget)
    assert len(trimmed.encode("utf-8")) <= budget
    assert LONG_TITLE.startswith(trimmed) and trimmed != LONG_TITLE
    assert ds.name_key_of_title(LONG_TITLE, FOLDER) == ds._name_key(trimmed)


def test_a_long_title_downloads_under_a_capped_name_and_is_owned_by_the_job(tmp_path, monkeypatch):
    # The whole run against the yt-dlp stand-in: the plan pass, the claim, the download and the
    # saved path all use the capped name; a second run of the same link resumes under it.
    import urllib.parse

    from tests.core.test_downloads_keep_user_files import _run

    monkeypatch.setattr(ds, "yt_dlp_js_args", lambda *_a, **_k: [])
    monkeypatch.setattr(ds, "_claims_path", lambda: tmp_path / "claims.json")
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(tmp_path / "runs.log"))
    for var in ("FAKE_YTDLP_PLAN_FAIL", "FAKE_YTDLP_DIE_PART", "FAKE_YTDLP_SLOW"):
        monkeypatch.delenv(var, raising=False)
    import queue
    import types

    folder = tmp_path / "dl"
    folder.mkdir()
    app = types.SimpleNamespace(
        download_events=queue.Queue(), app_config={}, entry_file=str(tmp_path / "app.py"),
        yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "",
    )
    svc = ds.DownloadService(app)  # type: ignore[arg-type]
    url = "https://x.test/v/" + urllib.parse.quote(LONG_TITLE)
    info = {"mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"}}
    task = VideoDownloadTask(url=url, folder=str(folder), format_label="x", format_info=info)
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved
    name = os.path.basename(saved)
    assert saved == str(folder / name) and os.path.exists(saved)
    assert LONG_TITLE.startswith(os.path.splitext(name)[0]) and len(name) < len(LONG_TITLE)
    budget = ds.title_byte_budget(str(folder))
    assert len(os.path.splitext(name)[0].encode("utf-8")) <= budget
    # the same link again: its own finished file exists, so it is numbered after the CAPPED name
    again = VideoDownloadTask(url=url, folder=str(folder), format_label="x", format_info=info)
    rc2, _e2, _l2, saved2, _f2 = _run(svc, again)
    assert rc2 == 0 and saved2 == str(folder / (os.path.splitext(name)[0] + " (1).mp4"))


def test_the_cap_matches_what_the_installed_yt_dlp_really_writes():
    yt_dlp = pytest.importorskip("yt_dlp")
    ydl = yt_dlp.YoutubeDL({"quiet": True})
    cmd = ds.build_download_command(_task(), yt_dlp_path="y", bin_path="")
    out = ydl.prepare_filename({"id": "1", "title": LONG_TITLE, "ext": "mp4"}, outtmpl=_o(cmd))
    name = os.path.basename(out.replace("\\", "/"))
    for suffix in SUFFIXES:
        assert _units(os.path.splitext(name)[0] + suffix) <= 255
