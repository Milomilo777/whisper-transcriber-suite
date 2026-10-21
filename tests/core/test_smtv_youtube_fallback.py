"""A failed download from the video site's own server falls back to the same video on YouTube.

The site's server stays first (its page text is saved beside the file, some episodes have an
audio-only file, and the original quality is there); when it fails and the page names a
YouTube copy, the same task downloads that copy with yt-dlp, in the same mode, and still
saves the page text. No Tk, no network: the stream and the yt-dlp run are stubbed.
"""
from __future__ import annotations

import queue
import types

from app.services.download_service import DownloadService
from core.integrations import smtv as smtv_mod

PAGE = "https://suprememastertv.com/en1/v/123.html"


def _episode(youtube_id: str | None = "AbCdEf01234", text: str = "The page text.") -> smtv_mod.SmtvEpisode:
    return smtv_mod.SmtvEpisode(vid="123", title="Some Episode", page_url=PAGE, lang_prefix="en",
                                transcript_text=text, youtube_id=youtube_id)


def _task(tmp_path, mode: str = "Audio", episode=None) -> types.SimpleNamespace:
    chosen = {"kind": "smtv", "mode": "audio" if mode == "Audio" else "video-best",
              "url": "https://cdn.example/x.mp3"}
    return types.SimpleNamespace(
        folder=str(tmp_path), url=PAGE, cancelled=False, paused=False, _run_generation=1,
        format_info={"mode": mode, "audio": chosen if mode == "Audio" else None,
                     "video": None if mode == "Audio" else chosen, "output": "mp4",
                     "episode": episode if episode is not None else _episode()},
    )


def _svc(tmp_path, *, rc: int = 0, fail_official: bool = True):
    events: queue.Queue = queue.Queue()
    app = types.SimpleNamespace(download_events=events, app_config={},
                                yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "")
    svc = DownloadService(app)  # type: ignore[arg-type]
    commands: list[list[str]] = []
    saved = tmp_path / "Some Episode.mp3"

    def official(task, *, run_generation=None):
        if fail_official:
            raise RuntimeError("SMTV CDN download truncated: received 10 of 99 bytes")
        events.put(("done_full", task, {"status": "finished", "saved_path": "cdn"}))

    def media(task, command):
        commands.append(command)
        if rc == 0:
            saved.write_bytes(b"audio")
            return 0, "", "", str(saved), True
        return rc, "ERROR: [youtube] AbCdEf01234: Video unavailable", "", None, False

    svc._run_smtv_task = official  # type: ignore[method-assign]
    svc._run_media_process = media  # type: ignore[method-assign]
    svc.maybe_update_yt_dlp = lambda task: None  # type: ignore[method-assign]
    return svc, events, commands, saved


def _drain(events: queue.Queue) -> list[tuple]:
    out = []
    while not events.empty():
        out.append(events.get_nowait())
    return out


def test_the_watch_url_comes_from_a_valid_id_only() -> None:
    assert smtv_mod.youtube_watch_url(_episode()) == "https://www.youtube.com/watch?v=AbCdEf01234"
    assert smtv_mod.youtube_watch_url(_episode(None)) is None
    assert smtv_mod.youtube_watch_url(_episode("--exec rm")) is None  # never a flag or junk
    assert smtv_mod.youtube_watch_url(None) is None


def test_a_failed_site_download_takes_the_youtube_copy(tmp_path) -> None:
    svc, events, commands, saved = _svc(tmp_path)
    task = _task(tmp_path, mode="Audio")
    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]
    (command,) = commands
    assert command[-1] == "https://www.youtube.com/watch?v=AbCdEf01234" and command[-2] == "--"
    assert "-x" in command  # audio mode stays audio
    got = _drain(events)
    assert got[-1][0] == "done_full" and got[-1][2]["saved_path"] == str(saved)
    assert any(kind == "log" and "YouTube" in str(msg) for kind, _t, msg in got)
    assert (tmp_path / "Some Episode.txt").read_text(encoding="utf-8") == "The page text.\n"


def test_video_mode_stays_video(tmp_path) -> None:
    svc, _events, commands, _saved = _svc(tmp_path)
    svc._run_smtv_with_fallback(_task(tmp_path, mode="Audio and video"), 1, object())  # type: ignore[arg-type]
    assert "-x" not in commands[0] and "--merge-output-format" in commands[0]


def test_no_youtube_copy_posts_one_error(tmp_path) -> None:
    svc, events, commands, _saved = _svc(tmp_path)
    task = _task(tmp_path, episode=_episode(None))
    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]
    got = _drain(events)
    assert commands == [] and [g[0] for g in got] == ["error"] and "truncated" in got[0][2]


def test_both_failing_says_so(tmp_path) -> None:
    svc, events, _commands, _saved = _svc(tmp_path, rc=1)
    svc._run_smtv_with_fallback(_task(tmp_path), 1, object())  # type: ignore[arg-type]
    errors = [g for g in _drain(events) if g[0] == "error"]
    assert len(errors) == 1 and "truncated" in errors[0][2] and "YouTube" in errors[0][2]


def test_a_cancelled_task_does_not_fall_back(tmp_path) -> None:
    svc, events, commands, _saved = _svc(tmp_path)
    task = _task(tmp_path)
    task.cancelled = True
    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]
    assert commands == []


def test_a_working_site_download_never_touches_youtube(tmp_path) -> None:
    svc, events, commands, _saved = _svc(tmp_path, fail_official=False)
    svc._run_smtv_with_fallback(_task(tmp_path), 1, object())  # type: ignore[arg-type]
    assert commands == [] and _drain(events)[-1][0] == "done_full"
