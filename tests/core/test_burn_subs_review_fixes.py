"""burn() review fixes: markup escape, no-picture refusal, codec choice,
progress across the AAC retry, reserved output names."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from core import burn_subs

BS = chr(92)
WJ = chr(0x2060)


def _files(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    srt = tmp_path / "clip.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    return str(video), str(srt), str(tmp_path / "clip-subbed.mp4")


def _probe(monkeypatch, *, has_video: bool | None = True, audio="aac", duration=10.0):
    monkeypatch.setattr(
        burn_subs, "probe_media",
        lambda path: burn_subs.MediaInfo(duration, has_video, audio),
    )
    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")


# -- markup escape ---------------------------------------------------------------

@pytest.mark.parametrize(
    "line, escaped",
    [
        ("plain", "plain"),
        ("{x}", BS + "{x" + BS + "}"),
        (BS + "N", BS + WJ + "N"),
        ("<i>a</i>", "<" + WJ + "i>a<" + WJ + "/i>"),
        ("a < b", "a < b"),
        ("1 <2", "1 <2"),
    ],
)
def test_escape_cue_text(line, escaped):
    assert burn_subs.escape_cue_text(line) == escaped


def test_escape_keeps_index_and_timing_lines():
    srt = "1\n00:00:00,000 --> 00:00:01,000\n{a}\n\n2\n00:00:01,000 --> 00:00:02,000\n42\n"
    out = burn_subs.escape_srt_markup(srt)
    assert out.split("\n")[:2] == ["1", "00:00:00,000 --> 00:00:01,000"]
    assert out.split("\n")[2] == BS + "{a" + BS + "}"
    assert "\n42\n" in out


# -- refusals and command shape -----------------------------------------------------

def test_no_video_stream_is_refused_before_ffmpeg(tmp_path, monkeypatch):
    _probe(monkeypatch, has_video=False)
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda *a, **k: pytest.fail("ffmpeg ran"))
    video, srt, out = _files(tmp_path)
    with pytest.raises(ValueError, match="no video picture"):
        burn_subs.burn(video, srt, out)
    assert not os.path.exists(out)


def test_unknown_probe_does_not_block(tmp_path, monkeypatch):
    _probe(monkeypatch, has_video=None, audio="")
    ran = []
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda cmd, **k: ran.append(cmd))
    video, srt, out = _files(tmp_path)
    burn_subs.burn(video, srt, out)
    assert ran


@pytest.mark.parametrize(
    "audio, first", [("opus", "aac"), ("vorbis", "aac"), ("flac", "aac"),
                     ("pcm_s16le", "aac"), ("aac", "copy"), ("mp3", "copy"), ("", "copy")],
)
def test_mp4_gets_a_playable_audio_codec(tmp_path, monkeypatch, audio, first):
    _probe(monkeypatch, audio=audio)
    cmds = []
    monkeypatch.setattr(burn_subs, "_run_ffmpeg", lambda cmd, **k: cmds.append(cmd))
    video, srt, out = _files(tmp_path)
    burn_subs.burn(video, srt, out)
    cmd = cmds[0]
    assert cmd[cmd.index("-c:a") + 1] == first
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"


def test_progress_never_drops_across_the_aac_retry(tmp_path, monkeypatch):
    _probe(monkeypatch, audio="")  # unknown codec: copy first, AAC on refusal
    calls = []

    def run(cmd, *, progress_cb, **k):
        calls.append(cmd)
        progress_cb(30.0)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(
                1, cmd, b"", b"codec not currently supported in container")
        progress_cb(10.0)
        progress_cb(60.0)
        progress_cb(100.0)

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", run)
    video, srt, out = _files(tmp_path)
    seen: list[float] = []
    burn_subs.burn(video, srt, out, progress_cb=seen.append)
    assert len(calls) == 2
    assert seen == [30.0, 60.0, 100.0]


# -- reserved names -----------------------------------------------------------------

def test_reserved_names_never_collide(tmp_path):
    base = str(tmp_path / "a-subbed.mp4")
    first = burn_subs.reserve_output_path(base)
    second = burn_subs.reserve_output_path(base)
    assert first == base and second == str(tmp_path / "a-subbed (2).mp4")
    assert os.path.getsize(first) == 0
    burn_subs.release_reserved_path(second)
    assert not os.path.exists(second)
    with open(first, "wb") as f:
        f.write(b"finished video")
    burn_subs.release_reserved_path(first)
    assert os.path.exists(first), "a real result is never removed"


# -- real ffmpeg: markup in the text is drawn as text ---------------------------------

def _real_ffmpeg() -> str | None:
    exe = burn_subs.bundled_binary("ffmpeg")
    return exe if os.path.isfile(exe) or shutil.which(exe) else None


def _frame_rows(ffmpeg, video, w, h):
    """Bright-pixel count per row of the frame at 1 s (gray, raw)."""
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", "1", "-i", video, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True, timeout=60, stdin=subprocess.DEVNULL,
    ).stdout
    assert len(raw) == w * h
    return [sum(1 for b in raw[r * w:(r + 1) * w] if b > 128) for r in range(h)]


@pytest.mark.skipif(_real_ffmpeg() is None, reason="ffmpeg not available")
def test_real_burn_draws_markup_as_text(tmp_path):
    ffmpeg = _real_ffmpeg()
    assert ffmpeg is not None
    w, h = 320, 240
    video = str(tmp_path / "black.mp4")
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"color=black:size={w}x{h}:rate=10",
         "-t", "2", video],
        check=True, timeout=120, stdin=subprocess.DEVNULL,
    )

    def burned(text: str, name: str) -> list[int]:
        srt = tmp_path / f"{name}.srt"
        srt.write_text(f"1\n00:00:00,000 --> 00:00:02,000\n{text}\n", encoding="utf-8")
        out = str(tmp_path / f"{name}-subbed.mp4")
        burn_subs.burn(video, str(srt), out)
        return _frame_rows(ffmpeg, out, w, h)

    tagged = burned("{" + BS + "an8}TOP", "tag")
    # Unescaped, {\an8} moved the cue to the top; escaped it stays at the
    # bottom and is drawn as text.
    assert sum(tagged[: h // 2]) == 0
    assert sum(tagged[h // 2:]) > 0
    with_braces = sum(burned("A {x} B", "braces"))
    without = sum(burned("A B", "plain"))
    assert with_braces > without, "the literal {x} must be drawn"
