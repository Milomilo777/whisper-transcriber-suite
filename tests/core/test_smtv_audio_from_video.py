"""Audio-only SMTV downloads when the page has no mp3 yet.

The site adds an episode's mp3 weeks after its video: none of the six newest pages listed one
on 2026-10-25 (a May 2026 page did). The audio format combo stayed empty and Download said "Wait for formats to
load, then select an audio format." forever. An audio-only download now fetches a video
(720p first: ~125 kb/s AAC) and ffmpeg takes the sound out into the chosen output format.

Hermetic: SimpleNamespace apps, no Tk root, no network. The end-to-end test runs the
bundled (or PATH) ffmpeg on a generated one-second clip and skips when there is none.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import types

import pytest

from app.services import download_service as ds
from app.services.download_service import DownloadService
from app.services.format_service import FormatService
from core import burn_subs
from core.integrations import smtv as smtv_mod

PAGE = "https://suprememastertv.com/en1/v/123.html"


def _file(quality: str, name: str) -> smtv_mod.SmtvFile:
    return smtv_mod.SmtvFile(quality, f"2021/0520/{name}", f"https://cdn.example/dl?file=2021/0520/{name}")


def _episode(*qualities: str) -> smtv_mod.SmtvEpisode:
    names = {
        "audio": "Show-p1.mp3", "1080p": "Show-p1-1080p.mp4", "720pHQ": "Show-p1-6m.mp4",
        "720p": "Show-p1-2m.mp4", "396p": "Show-p1-700k.mp4", "max": "Show-p1-max.mp4",
    }
    return smtv_mod.SmtvEpisode(
        vid="123", title="Show", page_url=PAGE, lang_prefix="en",
        files=[_file(q, names[q]) for q in qualities], transcript_text="",
    )


# ------------------------------------------------------------ source choice


@pytest.mark.parametrize(
    ("qualities", "expected"),
    [
        (("1080p", "720pHQ", "720p", "396p", "audio"), "audio"),  # the page's own mp3 wins
        (("1080p", "720pHQ", "720p", "396p"), "720p"),  # the live pages of 2026-10-25
        (("1080p", "720pHQ", "396p"), "720pHQ"),
        (("396p", "max"), "396p"),  # never a possibly-4K original just for the sound
        (("max",), "max"),
    ],
)
def test_audio_choice_prefers_mp3_then_720p(qualities, expected):
    choice = smtv_mod.audio_choice(_episode(*qualities))
    assert choice is not None and choice.quality == expected


def test_audio_choice_none_without_media():
    assert smtv_mod.audio_choice(_episode()) is None
    with pytest.raises(smtv_mod.SmtvError):
        smtv_mod.best_url_for_mode(_episode(), smtv_mod.AUDIO_FROM_VIDEO)


def test_best_url_for_audio_from_video_is_the_720p_file():
    url = smtv_mod.best_url_for_mode(_episode("1080p", "720p", "396p"), smtv_mod.AUDIO_FROM_VIDEO)
    assert url.endswith("Show-p1-2m.mp4")


@pytest.mark.parametrize(
    ("video", "stem"),
    [
        ("Show-p1-2m.mp4", "Show-p1"),
        ("Show-p1-700k.mp4", "Show-p1"),
        ("Show-p1-1080p.mp4", "Show-p1"),
        ("Show-p1-max.mp4", "Show-p1"),
        ("Show-p1.mp4", "Show-p1"),
        ("2m.mp4", "2m"),
    ],
)
def test_audio_stem_drops_the_quality_tag(video, stem):
    assert ds._smtv_audio_stem(video) == stem


def test_audio_output_falls_back_to_mp3():
    assert ds._smtv_audio_output("M4A")[0] == ".m4a"
    assert ds._smtv_audio_output("")[0] == ".mp3"
    assert ds._smtv_audio_output("mkv")[0] == ".mp3"


# ------------------------------------------------------------ format combo


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _format_app() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        set_download_duration=lambda _s: None,
        update_download_mode=lambda: None,
        update_caption_shortcut_state=lambda: None,
        audio_format_combo={}, video_format_combo={},
        audio_format_var=_Var(), video_format_var=_Var(), format_status_var=_Var(),
    )


def test_page_without_mp3_fills_the_audio_combo():
    app = _format_app()
    FormatService(app)._apply_smtv_formats(_episode("1080p", "720pHQ", "720p", "396p"))  # type: ignore[arg-type]
    assert app.audio_format_combo["values"] == ["Audio (taken from the video)"]
    assert app.audio_format_var.get() == "Audio (taken from the video)"
    entry = app.audio_format_map["Audio (taken from the video)"]
    assert entry["kind"] == "smtv" and entry["mode"] == smtv_mod.AUDIO_FROM_VIDEO
    assert entry["quality"] == "720p" and entry["url"].endswith("Show-p1-2m.mp4")


def test_page_with_mp3_keeps_the_direct_file():
    app = _format_app()
    FormatService(app)._apply_smtv_formats(_episode("720p", "audio"))  # type: ignore[arg-type]
    assert list(app.audio_format_map) == ["MP3 (audio only)"]
    assert app.audio_format_map["MP3 (audio only)"]["mode"] == "audio"


# ------------------------------------------------------------ download run


@pytest.fixture(autouse=True)
def _ffmpeg_present(monkeypatch):
    """The fake-extraction tests must not depend on an ffmpeg on the test machine."""
    monkeypatch.setattr(ds, "_smtv_ffmpeg_available", lambda: True)


def _task(tmp_path, output: str = "mp3") -> types.SimpleNamespace:
    episode = _episode("1080p", "720p", "396p")
    source = smtv_mod.audio_choice(episode)
    assert source is not None
    return types.SimpleNamespace(
        folder=str(tmp_path), url=PAGE, cancelled=False,
        format_info={
            "mode": "Audio",
            "audio": {"kind": "smtv", "mode": smtv_mod.AUDIO_FROM_VIDEO,
                      "quality": source.quality, "url": source.download_url},
            "video": None, "output": output, "episode": episode,
        },
    )


def _service(stream) -> tuple[DownloadService, queue.Queue]:
    events: queue.Queue = queue.Queue()
    svc = DownloadService(types.SimpleNamespace(download_events=events))  # type: ignore[arg-type]
    svc._stream_smtv_file = types.MethodType(stream, svc)  # type: ignore[assignment]
    return svc, events


def _terminal(events: queue.Queue) -> list:
    out = []
    while not events.empty():
        ev = events.get_nowait()
        if isinstance(ev, ds._RunEvent):
            out.append(ev)
    return out


def _fake_stream(self, task, url, dest_path, **_kw):  # noqa: ANN001
    with open(dest_path, "wb") as f:
        f.write(b"video bytes")


def test_run_streams_the_video_then_saves_only_the_audio(tmp_path, monkeypatch):
    seen: dict = {}

    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        seen.update(source=source, dest=dest, args=codec_args)
        with open(dest, "wb") as f:
            f.write(b"audio bytes")

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(_fake_stream)
    svc._run_smtv_task(_task(tmp_path, "m4a"))  # type: ignore[arg-type]

    assert os.path.basename(seen["source"]) == "Show-p1-2m.mp4.part"
    assert seen["args"][:3] == ["-c:a", "copy", "-f"]
    assert sorted(os.listdir(tmp_path)) == ["Show-p1.m4a"]
    done = _terminal(events)
    assert [e[0] for e in done] == ["done_full"]
    assert done[0][2]["saved_path"] == os.path.join(str(tmp_path), "Show-p1.m4a")


def test_failed_extraction_cleans_up_and_raises(tmp_path, monkeypatch):
    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        with open(dest, "wb") as f:
            f.write(b"half")
        raise RuntimeError("could not take the audio out of the video: boom")

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(_fake_stream)
    with pytest.raises(RuntimeError, match="audio out of the video"):
        svc._run_smtv_task(_task(tmp_path))  # type: ignore[arg-type]
    assert os.listdir(tmp_path) == []
    assert _terminal(events) == []  # the caller (YouTube fallback) reports it


def test_cancel_during_extraction_reports_cancelled(tmp_path, monkeypatch):
    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        raise burn_subs.BurnCancelled("stop")

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(_fake_stream)
    svc._run_smtv_task(_task(tmp_path))  # type: ignore[arg-type]
    assert os.listdir(tmp_path) == []
    assert [(e[0], e[2]) for e in _terminal(events)] == [("done", "cancelled")]


def _ffmpeg() -> str | None:
    from core.paths import bundled_binary

    exe = bundled_binary("ffmpeg")
    return exe if os.path.isfile(exe) else shutil.which(exe)


@pytest.mark.parametrize("output", ["mp3", "m4a", "aac", "opus", "flac", "wav"])
def test_real_ffmpeg_takes_the_audio_out(tmp_path, output):
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(clip)],
        check=True, capture_output=True, **ds.new_session_kwargs(),
    )

    def stream_clip(self, task, url, dest_path, **_kw):  # noqa: ANN001
        shutil.copyfile(clip, dest_path)

    out = tmp_path / "out"
    out.mkdir()
    svc, events = _service(stream_clip)
    svc._run_smtv_task(_task(out, output))  # type: ignore[arg-type]

    files = os.listdir(out)
    assert files == [f"Show-p1.{output}"]
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(out / files[0])],
        capture_output=True, text=True, **ds.new_session_kwargs(),
    )
    assert "Audio:" in probe.stderr and "Video:" not in probe.stderr
    assert [e[0] for e in _terminal(events)] == ["done_full"]


# ------------------------------------------------------------ series parts


def test_sibling_parts_without_mp3_take_audio_from_video(monkeypatch):
    sib = smtv_mod.SmtvSibling(url="https://suprememastertv.com/en1/v/124.html",
                               title="Show part 2", part=2, total=2)
    parent = _episode("720p")
    parent = smtv_mod.SmtvEpisode(**{**parent.__dict__, "siblings": [sib]})
    monkeypatch.setattr(smtv_mod, "fetch_episode", lambda url, timeout=30.0: _episode("1080p", "720p"))

    svc = DownloadService(types.SimpleNamespace(download_events=queue.Queue()))  # type: ignore[arg-type]
    tasks = svc._build_smtv_sibling_tasks(
        parent, mode="Audio", video_label="", folder="x", format_label="SMTV audio", output="mp3",
    )
    assert len(tasks) == 1
    audio = tasks[0].format_info["audio"]
    assert audio["mode"] == smtv_mod.AUDIO_FROM_VIDEO and audio["quality"] == "720p"


def test_missing_ffmpeg_fails_before_the_video_download(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "_smtv_ffmpeg_available", lambda: False)
    streamed: list = []
    svc, _events = _service(lambda self, task, url, dest, **kw: streamed.append(dest))
    with pytest.raises(RuntimeError, match="ffmpeg is needed"):
        svc._run_smtv_task(_task(tmp_path))  # type: ignore[arg-type]
    assert streamed == [] and os.listdir(tmp_path) == []


def test_copy_falls_back_to_aac_encode_for_a_non_aac_source(tmp_path):
    """m4a copies the sound; an mp3 sound inside the video cannot be copied into m4a."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "mpeg4", "-c:a", "libmp3lame", "-shortest", str(clip)],
        check=True, capture_output=True, **ds.new_session_kwargs(),
    )
    dest = tmp_path / "out.m4a.part"
    svc, _events = _service(_fake_stream)
    task = _task(tmp_path, "m4a")
    svc._extract_smtv_audio(task, str(clip), str(dest), ds._smtv_audio_output("m4a")[1], lambda: False)  # type: ignore[arg-type]
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-f", "mp4", "-i", str(dest)],
        capture_output=True, text=True, **ds.new_session_kwargs(),
    )
    assert "Audio: aac" in probe.stderr


# ------------------------------------------------------------ races (second-model review)


def test_each_run_owns_its_part_files(tmp_path, monkeypatch):
    seen: dict = {}

    def stream(self, task, url, dest_path, **_kw):  # noqa: ANN001
        seen["video"] = os.path.basename(dest_path)
        _fake_stream(self, task, url, dest_path)

    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        seen["audio"] = os.path.basename(dest)
        with open(dest, "wb") as f:
            f.write(b"audio")

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(stream)
    task = _task(tmp_path)
    task._run_generation = 3
    svc._run_smtv_task(task, run_generation=3)  # type: ignore[arg-type]
    assert seen == {"video": "Show-p1-2m.mp4.r3.part", "audio": "Show-p1.mp3.r3.part"}
    assert os.listdir(tmp_path) == ["Show-p1.mp3"]
    assert [e[0] for e in _terminal(events)] == ["done_full"]


def test_superseded_extraction_cleans_its_own_parts_and_reports_nothing(tmp_path, monkeypatch):
    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        with open(dest, "wb") as f:
            f.write(b"half")
        task._run_generation = 2  # a retry took the task over while ffmpeg ran
        assert superseded()
        raise burn_subs.BurnCancelled("stop")

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(_fake_stream)
    task = _task(tmp_path)
    task._run_generation = 1
    svc._run_smtv_task(task, run_generation=1)  # type: ignore[arg-type]
    assert os.listdir(tmp_path) == []
    assert _terminal(events) == []  # the fresh run owns all reporting


def test_cancel_after_extraction_publishes_nothing(tmp_path, monkeypatch):
    def fake_extract(self, task, source, dest, codec_args, superseded):  # noqa: ANN001
        with open(dest, "wb") as f:
            f.write(b"audio")
        task.cancelled = True  # after ffmpeg's last stop check

    monkeypatch.setattr(DownloadService, "_extract_smtv_audio", fake_extract)
    svc, events = _service(_fake_stream)
    svc._run_smtv_task(_task(tmp_path))  # type: ignore[arg-type]
    assert os.listdir(tmp_path) == []
    assert [(e[0], e[2]) for e in _terminal(events)] == [("done", "cancelled")]


def test_no_ffmpeg_starts_for_a_cancelled_run(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda *a, **k: calls.append(a))
    svc, _events = _service(_fake_stream)
    task = _task(tmp_path)
    task.cancelled = True
    with pytest.raises(burn_subs.BurnCancelled):
        svc._extract_smtv_audio(task, "in.mp4", "out.part", ["-f", "mp3"], lambda: False)  # type: ignore[arg-type]
    assert calls == []
