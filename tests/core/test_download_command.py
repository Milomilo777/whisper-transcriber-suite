"""Tests for the pure builders + parsers in ``app.services.download_service``."""
from __future__ import annotations

import json

import pytest

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import (
    _cookies_from_browser_args,
    _download_sections_arg,
    _fmt_timecode,
    _parse_timecode,
    _time_range_badge,
    build_download_command,
    build_subtitle_command,
    parse_destination_line,
    parse_progress_line,
    select_saved_path,
)


def _task(folder: str = "/tmp/out", url: str = "https://www.youtube.com/watch?v=abc",
          mode: str = "Audio and video", output: str = "mp4",
          audio_kind: str = "best_audio", audio_id: str = "140",
          video_kind: str = "best_video", video_id: str = "137",
          section_start: float | None = None,
          section_end: float | None = None) -> VideoDownloadTask:
    # Build a REAL VideoDownloadTask (not a SimpleNamespace) so the call into
    # build_download_command / build_subtitle_command — whose ``task`` param is
    # typed VideoDownloadTask — is type-clean for pyright.
    return VideoDownloadTask(
        url=url,
        folder=folder,
        format_label="x",
        format_info={
            "mode": mode,
            "output": output,
            "audio": {"kind": audio_kind, "format_id": audio_id},
            "video": {"kind": video_kind, "format_id": video_id},
        },
        section_start=section_start,
        section_end=section_end,
    )


def test_build_subtitle_command_passes_lang_and_output():
    task = _task()
    cmd = build_subtitle_command(task, "en", yt_dlp_path="ytdlp.exe", bin_path="C:/bin")
    assert cmd[0] == "ytdlp.exe"
    assert "--ffmpeg-location" in cmd and cmd[cmd.index("--ffmpeg-location") + 1] == "C:/bin"
    assert "--write-auto-subs" in cmd and "--write-subs" in cmd
    assert "--sub-langs" in cmd and cmd[cmd.index("--sub-langs") + 1] == "en"
    assert "--no-playlist" in cmd
    assert cmd[-1] == task.url


def test_build_subtitle_command_normalizes_lang_list():
    task = _task()
    cmd = build_subtitle_command(task, " en , ja ", yt_dlp_path="ytdlp.exe", bin_path="C:/bin")
    assert cmd[cmd.index("--sub-langs") + 1] == "en,ja"


def test_build_subtitle_command_escapes_regex_metachars():
    """A detected-language code from video metadata must reach yt-dlp as a
    literal, not as a regex: --sub-langs ".*" used to fetch every translated
    caption track (see docs/auto-subtitles-feature.md)."""
    task = _task()
    cmd = build_subtitle_command(task, ".*", yt_dlp_path="ytdlp.exe", bin_path="C:/bin")
    value = cmd[cmd.index("--sub-langs") + 1]
    assert value != ".*"
    assert value == r"\.\*"


def test_build_download_command_audio_only_uses_x_flag():
    task = _task(mode="Audio", output="mp3", audio_kind="best_audio")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "-x" in cmd
    assert "--audio-format" in cmd and cmd[cmd.index("--audio-format") + 1] == "mp3"
    assert "--merge-output-format" not in cmd


def test_build_download_command_audio_only_specific_format_id():
    task = _task(mode="Audio", output="m4a", audio_kind="specific", audio_id="251")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f_idx = cmd.index("-f")
    assert cmd[f_idx + 1] == "251"


def test_build_download_command_video_uses_merge_output_format():
    task = _task(mode="Audio and video", output="mp4")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "--merge-output-format" in cmd
    assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"
    f = cmd[cmd.index("-f") + 1]
    assert "+" in f


def test_build_download_command_video_picks_mp4_friendly_selectors_for_mp4_output():
    task = _task(output="mp4")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f = cmd[cmd.index("-f") + 1]
    assert "ext=mp4" in f


def test_build_download_command_video_uses_neutral_selectors_for_webm():
    task = _task(output="webm")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f = cmd[cmd.index("-f") + 1]
    assert "ext=mp4" not in f


def test_build_download_command_groups_video_audio_selectors_mp4():
    """Regression for the missing-audio bug. The merge selector MUST wrap
    each stream group in parentheses; without them yt-dlp parses '/' at
    a higher level than '+', picks the first video-only candidate, and
    the merged file ends up silent."""
    task = _task(output="mp4")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f = cmd[cmd.index("-f") + 1]
    assert f == (
        "(bv*[ext=mp4]/bestvideo[ext=mp4]/bv*/bestvideo)"
        "+(ba[ext=m4a]/bestaudio[ext=m4a]/ba/bestaudio)/best"
    )


def test_build_download_command_groups_video_audio_selectors_webm():
    task = _task(output="webm")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f = cmd[cmd.index("-f") + 1]
    assert f == "(bv*/bestvideo)+(ba/bestaudio)/best"


def test_build_download_command_groups_specific_format_ids():
    """Explicit per-stream format ids must still be grouped so the
    trailing '/best' fallback can't silently drop the audio stream."""
    task = _task(output="mp4", audio_kind="specific", audio_id="251",
                 video_kind="specific", video_id="137")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    f = cmd[cmd.index("-f") + 1]
    assert f == "(137)+(251)/best"


# --- browser-cookie support (yt-dlp --cookies-from-browser) -----------------


def test_cookies_from_browser_args_valid_browser():
    assert _cookies_from_browser_args("chrome") == ["--cookies-from-browser", "chrome"]
    assert _cookies_from_browser_args("edge") == ["--cookies-from-browser", "edge"]


def test_cookies_from_browser_args_empty_or_invalid_is_dropped():
    assert _cookies_from_browser_args("") == []
    assert _cookies_from_browser_args(None) == []
    assert _cookies_from_browser_args("   ") == []
    assert _cookies_from_browser_args("(off)") == []
    assert _cookies_from_browser_args("netscape") == []   # not a real browser


def test_cookies_from_browser_args_accepts_profile_and_keyring_syntax():
    assert _cookies_from_browser_args("chrome:Default") == [
        "--cookies-from-browser", "chrome:Default"
    ]
    assert _cookies_from_browser_args("firefox+gnomekeyring") == [
        "--cookies-from-browser", "firefox+gnomekeyring"
    ]


def test_build_download_command_emits_cookies_flag():
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin",
                                 cookies_from_browser="edge")
    assert "--cookies-from-browser" in cmd
    assert cmd[cmd.index("--cookies-from-browser") + 1] == "edge"


def test_build_download_command_omits_cookies_when_unset():
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "--cookies-from-browser" not in cmd


def test_build_subtitle_command_emits_cookies_flag():
    task = _task()
    cmd = build_subtitle_command(task, "en", yt_dlp_path="ytdlp", bin_path="bin",
                                 cookies_from_browser="chrome")
    assert cmd[cmd.index("--cookies-from-browser") + 1] == "chrome"


def test_build_download_command_supports_progress_template():
    task = _task()
    cmd = build_download_command(
        task, yt_dlp_path="ytdlp", bin_path="bin", progress_template="%(progress)j"
    )
    assert "--progress-template" in cmd
    assert cmd[cmd.index("--progress-template") + 1] == "%(progress)j"


def test_build_download_command_supports_sponsorblock_categories():
    task = _task()
    cmd = build_download_command(
        task,
        yt_dlp_path="ytdlp",
        bin_path="bin",
        sponsorblock_categories=["sponsor", "intro", "outro"],
    )
    assert "--sponsorblock-remove" in cmd
    assert cmd[cmd.index("--sponsorblock-remove") + 1] == "sponsor,intro,outro"


def test_build_download_command_no_sponsorblock_when_categories_empty():
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin", sponsorblock_categories=[])
    assert "--sponsorblock-remove" not in cmd


def test_build_download_command_url_is_last():
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert cmd[-1] == task.url


# --- R2: -c/--continue so a resumed "pause" continues the .part -------------


def test_build_download_command_includes_continue_flag():
    # R2 stop-and-continue "pause" resumes the existing .part fragment; the
    # command must pass -c/--continue so yt-dlp doesn't restart from zero.
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "-c" in cmd or "--continue" in cmd


def test_build_download_command_continue_flag_present_audio_mode():
    task = _task(mode="Audio", output="mp3", audio_kind="best_audio")
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "-c" in cmd or "--continue" in cmd


# --- parse_progress_line ----------------------------------------------------


def test_parse_progress_line_legacy_percent():
    parsed = parse_progress_line("[download]   42.7% of 100MiB at 1MiB/s ETA 00:34")
    assert parsed and parsed["percent"] == pytest.approx(42.7)


def test_parse_progress_line_json_percent_derived():
    payload = {"downloaded_bytes": 5000, "total_bytes": 10000, "speed": 1234}
    parsed = parse_progress_line(json.dumps(payload))
    assert parsed and parsed["percent"] == pytest.approx(50.0)
    assert parsed["downloaded_bytes"] == 5000


def test_parse_progress_line_json_uses_total_bytes_estimate_when_no_total():
    payload = {"downloaded_bytes": 250, "total_bytes_estimate": 1000}
    parsed = parse_progress_line(json.dumps(payload))
    assert parsed and parsed["percent"] == pytest.approx(25.0)


def test_parse_progress_line_returns_none_for_unknown():
    assert parse_progress_line("just a log line") is None
    assert parse_progress_line("") is None
    assert parse_progress_line("{not json}") is None


def test_parse_progress_line_caps_at_100():
    parsed = parse_progress_line(json.dumps({"downloaded_bytes": 999, "total_bytes": 100}))
    assert parsed and parsed["percent"] == 100.0


# --- parse_destination_line ------------------------------------------------


def test_parse_destination_line_picks_fragment_path():
    line = "[download] Destination: C:/out/My Video.mp4"
    assert parse_destination_line(line) == ("C:/out/My Video.mp4", False)


def test_parse_destination_line_handles_merger_quoted_no_colon():
    # Real yt-dlp shape: the merge target is QUOTED and has NO colon. The
    # old regex expected `Merging formats into:` and silently missed this,
    # so the deleted audio fragment won — the v1.2.0 auto-transcribe bug.
    line = '[Merger] Merging formats into "/tmp/out.mp4"'
    assert parse_destination_line(line) == ("/tmp/out.mp4", True)


def test_parse_destination_line_handles_extract_audio():
    line = "[ExtractAudio] Destination: /tmp/song.mp3"
    assert parse_destination_line(line) == ("/tmp/song.mp3", True)


def test_parse_destination_line_handles_already_downloaded():
    line = "[download] /tmp/out.mp4 has already been downloaded"
    assert parse_destination_line(line) == ("/tmp/out.mp4", True)


def test_parse_destination_line_returns_none_for_other_lines():
    assert parse_destination_line("[download] 42% of 10MB") is None
    assert parse_destination_line("") is None


# --- select_saved_path: the on-disk file wins over deleted fragments -------


def test_select_saved_path_merge_beats_deleted_fragments():
    lines = [
        "[download] Destination: C:/out/clip.f137.mp4",
        "[download] Destination: C:/out/clip.f140.m4a",
        '[Merger] Merging formats into "C:/out/clip.mp4"',
        "Deleting original file C:/out/clip.f137.mp4 (pass -k to keep)",
        "Deleting original file C:/out/clip.f140.m4a (pass -k to keep)",
    ]
    assert select_saved_path(lines) == "C:/out/clip.mp4"


def test_select_saved_path_single_file_no_merge():
    assert select_saved_path(["[download] Destination: C:/out/clip.mp4"]) == "C:/out/clip.mp4"


def test_select_saved_path_extract_audio_wins():
    lines = [
        "[download] Destination: C:/out/clip.webm",
        "[ExtractAudio] Destination: C:/out/clip.mp3",
    ]
    assert select_saved_path(lines) == "C:/out/clip.mp3"


def test_select_saved_path_already_downloaded():
    lines = ["[download] C:/out/clip.mp4 has already been downloaded"]
    assert select_saved_path(lines) == "C:/out/clip.mp4"


def test_select_saved_path_final_locks_out_trailing_fragment():
    # Defensive: even if a fragment line trails the merge, the final wins.
    lines = [
        '[Merger] Merging formats into "C:/out/clip.mp4"',
        "[download] Destination: C:/out/clip.f140.m4a",
    ]
    assert select_saved_path(lines) == "C:/out/clip.mp4"


def test_select_saved_path_real_world_reel_regression():
    # Exact transcript shape that shipped broken in v1.2.0: saved_path
    # resolved to the deleted .m4a fragment, so auto-transcribe hit
    # "No such file or directory". The merge target must win.
    base = "C:/Users/Owner/Desktop/My Reel"
    lines = [
        f"[download] Destination: {base}.f1632576788007822v.mp4",
        f"[download] Destination: {base}.f1462030628999880a.m4a",
        f'[Merger] Merging formats into "{base}.mp4"',
        f"Deleting original file {base}.f1632576788007822v.mp4 (pass -k to keep)",
        f"Deleting original file {base}.f1462030628999880a.m4a (pass -k to keep)",
    ]
    assert select_saved_path(lines) == f"{base}.mp4"


# --- security: end-of-options "--" separator before the URL ---------------


def test_download_command_separates_url_with_double_dash():
    # A pasted "URL" starting with '-' must reach yt-dlp AFTER a "--" so it
    # can't be parsed as a flag (e.g. --exec → arbitrary command execution).
    cmd = build_download_command(_task(url="-evil"), yt_dlp_path="ytdlp", bin_path="bin")
    assert cmd[-1] == "-evil"
    assert cmd[-2] == "--"


def test_subtitle_command_separates_url_with_double_dash():
    cmd = build_subtitle_command(
        _task(url="-evil"), "en", yt_dlp_path="ytdlp", bin_path="bin"
    )
    assert cmd[-1] == "-evil"
    assert cmd[-2] == "--"


def test_download_sections_drops_nonsensical_end_le_start():
    # end <= start (fat-fingered, or end slider dragged below start) would
    # make yt-dlp's "*start-end" download nothing — degrade to open-ended.
    assert _download_sections_arg(90.0, 30.0) == "*0:01:30-"
    assert _download_sections_arg(60.0, 60.0) == "*0:01:00-"
    # A valid range is untouched.
    assert _download_sections_arg(30.0, 90.0) == "*0:00:30-0:01:30"


# --- timecode helpers (v1.0.3 --download-sections) -------------------------


def test_parse_timecode_accepts_h_mm_ss():
    assert _parse_timecode("1:23:45") == pytest.approx(5025.0)
    assert _parse_timecode("0:00:51") == pytest.approx(51.0)


def test_parse_timecode_accepts_mm_ss():
    assert _parse_timecode("5:30") == pytest.approx(330.0)
    assert _parse_timecode("0:51") == pytest.approx(51.0)


def test_parse_timecode_accepts_bare_seconds():
    assert _parse_timecode("90") == pytest.approx(90.0)
    assert _parse_timecode("7.25") == pytest.approx(7.25)


def test_parse_timecode_returns_none_for_blank_or_garbage():
    assert _parse_timecode(None) is None
    assert _parse_timecode("") is None
    assert _parse_timecode("   ") is None
    assert _parse_timecode("not a number") is None
    assert _parse_timecode("1:2:3:4") is None  # too many colons


def test_parse_timecode_rejects_negative_and_overflow():
    assert _parse_timecode("-5") is None
    assert _parse_timecode("-1:00") is None
    # 25 hours == 90000s, above the 86400 sanity cap.
    assert _parse_timecode("90000") is None


def test_parse_timecode_rejects_nonfinite():
    # float("nan") parses successfully yet compares false to every bound,
    # so it used to slip through and crash int(nan) in the queue badge /
    # --download-sections builder. "inf" fails the 24h cap either way.
    assert _parse_timecode("nan") is None
    assert _parse_timecode("NaN") is None
    assert _parse_timecode("1:nan") is None
    assert _parse_timecode("inf") is None
    assert _parse_timecode("1e400") is None


def test_parse_timecode_rejects_minute_or_second_overflow_when_colon_form():
    # When the user gave MM:SS, a sub-position of 60 is a typo.
    assert _parse_timecode("5:99") is None
    assert _parse_timecode("1:99:00") is None
    # But a bare seconds value can exceed 60 — "90s" is fine.
    assert _parse_timecode("99") == pytest.approx(99.0)


def test_fmt_timecode_produces_h_mm_ss():
    assert _fmt_timecode(51.0) == "0:00:51"
    assert _fmt_timecode(85.0) == "0:01:25"
    assert _fmt_timecode(3661.0) == "1:01:01"


def test_fmt_timecode_preserves_fraction_when_present():
    out = _fmt_timecode(85.5)
    assert out.startswith("0:01:25")
    assert "5" in out  # ".5" appended


def test_fmt_timecode_carries_subsecond_rounding():
    # Regression: 90.999 used to format as "0:01:301" because the
    # fraction rounded to "1.00" while the integer seconds stayed 90.
    assert _fmt_timecode(90.999) == "0:01:31"
    assert _fmt_timecode(59.999) == "0:01:00"
    assert _fmt_timecode(3599.999) == "1:00:00"
    # A genuine sub-second value still round-trips without a carry.
    assert _fmt_timecode(90.99).startswith("0:01:30")


def test_download_sections_arg_both_bounds():
    assert _download_sections_arg(51.0, 85.0) == "*0:00:51-0:01:25"


def test_download_sections_arg_open_left():
    assert _download_sections_arg(None, 85.0) == "*-0:01:25"


def test_download_sections_arg_open_right():
    assert _download_sections_arg(51.0, None) == "*0:00:51-"


def test_download_sections_arg_no_bounds_returns_none():
    assert _download_sections_arg(None, None) is None


def test_time_range_badge_short_form():
    assert _time_range_badge(51.0, 85.0) == "0:51 -> 1:25"
    assert _time_range_badge(None, 85.0) == "start -> 1:25"
    assert _time_range_badge(51.0, None) == "0:51 -> end"
    assert _time_range_badge(None, None) is None


# --- build_download_command + --download-sections wiring -------------------


def test_build_download_command_omits_sections_by_default():
    task = _task()
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "--download-sections" not in cmd


def test_build_download_command_emits_sections_for_sample_slice():
    """Spec sample: start=0:00:51 end=0:01:25 -> *0:00:51-0:01:25."""
    task = _task(section_start=51.0, section_end=85.0)
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "--download-sections" in cmd
    idx = cmd.index("--download-sections")
    assert cmd[idx + 1] == "*0:00:51-0:01:25"
    # Sections flag must come before the URL (yt-dlp accepts either
    # order but we keep the URL last by convention).
    assert cmd[-1] == task.url


def test_build_download_command_sections_open_left():
    task = _task(section_start=None, section_end=85.0)
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert cmd[cmd.index("--download-sections") + 1] == "*-0:01:25"


def test_build_download_command_sections_open_right():
    task = _task(section_start=51.0, section_end=None)
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert cmd[cmd.index("--download-sections") + 1] == "*0:00:51-"


def test_build_download_command_sections_audio_only_mode():
    task = _task(mode="Audio", output="mp3", audio_kind="best_audio",
                 section_start=10.0, section_end=20.0)
    cmd = build_download_command(task, yt_dlp_path="ytdlp", bin_path="bin")
    assert "-x" in cmd
    assert cmd[cmd.index("--download-sections") + 1] == "*0:00:10-0:00:20"


# --- VideoDownloadTask.time_range_label ------------------------------------


def test_time_range_label_on_real_task_class():
    from app.domain.tasks import VideoDownloadTask

    t = VideoDownloadTask(
        url="https://example.com/v", folder="/tmp", format_label="x",
        format_info={"mode": "Audio and video", "output": "mp4",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
        section_start=51.0, section_end=85.0,
    )
    assert t.time_range_label() == "0:51 -> 1:25"
    assert t.section_start == 51.0
    assert t.section_end == 85.0


def test_time_range_label_none_when_no_bounds_set():
    from app.domain.tasks import VideoDownloadTask

    t = VideoDownloadTask(
        url="https://example.com/v", folder="/tmp", format_label="x",
        format_info={"mode": "Audio and video", "output": "mp4",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
    )
    assert t.time_range_label() is None
    assert t.section_start is None
    assert t.section_end is None


def test_time_range_label_open_bounds():
    from app.domain.tasks import VideoDownloadTask

    fmt = {"mode": "Audio", "output": "mp3",
           "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"}}
    left_open = VideoDownloadTask(
        url="x", folder="/tmp", format_label="x", format_info=fmt,
        section_end=85.0,
    )
    assert left_open.time_range_label() == "start -> 1:25"
    right_open = VideoDownloadTask(
        url="x", folder="/tmp", format_label="x", format_info=fmt,
        section_start=51.0,
    )
    assert right_open.time_range_label() == "0:51 -> end"


# --- R2: VideoDownloadTask.paused default ----------------------------------


def test_video_download_task_paused_defaults_false():
    # R2 added a ``paused`` flag distinct from ``cancelled`` so the teardown
    # path can tell which terminal status a stopped download lands on.
    from app.domain.tasks import VideoDownloadTask

    t = VideoDownloadTask(
        url="https://example.com/v", folder="/tmp", format_label="x",
        format_info={"mode": "Audio", "output": "mp3",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}},
    )
    assert t.paused is False
    assert t.cancelled is False
