"""Tests for core.burn_subs — ffmpeg subtitle burning.

Covers audit findings [7]/[14]/P2-17: the SRT path is fed into ffmpeg's
libavfilter ``subtitles=`` filter graph, where ' , ; [ ] are
metacharacters. A downloaded video's title (hence its sidecar .srt name)
is attacker-influenced and yt-dlp keeps those chars, so the old direct
interpolation broke burning for legitimately-punctuated titles and was a
filter-injection vector. The fix burns from a temp copy with a graph-safe
ASCII basename, so the dangerous characters never reach the graph string.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core import burn_subs


def _make_files(tmp_path, srt_name="subs.srt"):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftyp")  # not a real mp4; existence is all burn() checks
    srt = tmp_path / srt_name
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    out = tmp_path / "out.mp4"
    return str(video), str(srt), str(out)


def test_burn_raises_when_video_missing(tmp_path):
    _v, srt, out = _make_files(tmp_path)
    with pytest.raises(FileNotFoundError):
        burn_subs.burn(str(tmp_path / "nope.mp4"), srt, out)


def test_burn_raises_when_srt_missing(tmp_path):
    video, _s, out = _make_files(tmp_path)
    with pytest.raises(FileNotFoundError):
        burn_subs.burn(video, str(tmp_path / "nope.srt"), out)


def _capture_cmd(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)
    return captured


def _vf_value(cmd):
    i = cmd.index("-vf")
    return cmd[i + 1]


def test_burn_uses_graph_safe_temp_srt_name(tmp_path, monkeypatch):
    """An SRT whose stem contains the filtergraph metacharacters ' [ ] , ;
    must NOT appear verbatim in the -vf value — it is burned from a temp
    copy named subs.srt instead."""
    captured = _capture_cmd(monkeypatch)
    video, srt, out = _make_files(tmp_path, srt_name="it's, [live]; clip.srt")

    burn_subs.burn(video, srt, out)

    vf = _vf_value(captured["cmd"])
    assert vf.startswith("subtitles=")
    body = vf[len("subtitles="):]
    # The temp copy is always named subs.srt.
    assert body.endswith("subs.srt")
    # None of the dangerous metacharacters from the original name leaked in.
    for ch in ("'", "[", "]", ",", ";"):
        assert ch not in body, f"{ch!r} leaked into the filter graph: {body!r}"
    # The original malicious basename is gone.
    assert "live" not in body


def test_burn_video_path_passed_unescaped_as_input(tmp_path, monkeypatch):
    """The video path is a separate -i argv element (not in the graph), so
    it needs no filtergraph escaping and must reach ffmpeg verbatim."""
    captured = _capture_cmd(monkeypatch)
    weird = tmp_path / "my [weird], video.mp4"
    weird.write_bytes(b"\x00")
    srt = tmp_path / "subs.srt"
    srt.write_text("x", encoding="utf-8")
    out = tmp_path / "out.mp4"

    burn_subs.burn(str(weird), str(srt), str(out))

    cmd = captured["cmd"]
    assert cmd[cmd.index("-i") + 1] == str(weird)
    # The burn target is a temp sibling in the SAME directory; the user's
    # chosen path is only produced by the atomic os.replace on success.
    assert cmd[-1] != str(out)
    assert os.path.dirname(cmd[-1]) == os.path.dirname(str(out))
    assert cmd[-1].endswith(".mp4")
    assert os.path.isfile(out)


def test_burn_temp_dir_cleaned_up(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    video, srt, out = _make_files(tmp_path)

    burn_subs.burn(video, srt, out)

    body = _vf_value(captured["cmd"])[len("subtitles="):]
    # Recover the temp dir from the -vf path and confirm it was removed.
    # (Undo the Windows colon-escaping + forward-slashing for the check.)
    raw = body.replace("\\\\:", ":").replace("/", os.sep)
    assert raw.endswith("subs.srt")
    tmp_dir = os.path.dirname(raw)
    assert not os.path.exists(tmp_dir), "temp dir should be cleaned up after burn"


def test_burn_temp_dir_cleaned_up_on_ffmpeg_failure(tmp_path, monkeypatch):
    """Even when ffmpeg fails, the temp copy must not leak."""
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        i = cmd.index("-vf")
        body = cmd[i + 1][len("subtitles="):]
        seen["dir"] = os.path.dirname(body.replace("\\\\:", ":").replace("/", os.sep))
        raise subprocess.CalledProcessError(1, cmd, b"", b"boom")

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)
    video, srt, out = _make_files(tmp_path)

    with pytest.raises(RuntimeError, match="ffmpeg failed to burn subtitles"):
        burn_subs.burn(video, srt, out)
    assert not os.path.exists(seen["dir"])


# --- atomic output + audio-codec fallback ----------------------------------

_CONTAINER_ERR = (
    b"[mp4 @ 0x1] Could not find tag for codec opus in stream #1, "
    b"codec not currently supported in container\n"
)


def _last_audio_codec(cmd):
    """Value of the LAST -c:a (ffmpeg lets later options win)."""
    idx = max(i for i, arg in enumerate(cmd) if arg == "-c:a")
    return cmd[idx + 1]


def _no_temp_outputs(out_path):
    return [
        p.name for p in Path(out_path).parent.iterdir()
        if p.name.startswith(".burn-")
    ]


def test_burn_failure_does_not_clobber_existing_output(tmp_path, monkeypatch):
    """A failed burn must leave an existing file at out_path untouched and
    must not leave a partial encode behind under either name. Pre-fix,
    ffmpeg wrote straight to out_path, so a mid-way failure both destroyed
    whatever was there and left a corrupt .mp4 under the final name.
    """
    video, srt, out = _make_files(tmp_path)
    Path(out).write_bytes(b"ORIGINAL-CONTENT")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise subprocess.CalledProcessError(1, cmd, b"", b"[error] conversion failed")

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg failed to burn subtitles"):
        burn_subs.burn(video, srt, out)

    assert Path(out).read_bytes() == b"ORIGINAL-CONTENT"
    assert _no_temp_outputs(out) == []
    # A generic ffmpeg failure must not trigger the AAC retry pass.
    assert len(calls) == 1


def test_burn_retries_with_aac_when_container_rejects_audio(tmp_path, monkeypatch):
    """An Opus/Vorbis source copied into an .mp4 makes ffmpeg fail with the
    container/codec error; burn() must retry once with AAC and succeed."""
    video, srt, out = _make_files(tmp_path)
    codecs: list[str] = []

    def fake_run(cmd, **kwargs):
        codecs.append(_last_audio_codec(cmd))
        if len(codecs) == 1:
            raise subprocess.CalledProcessError(1, cmd, b"", _CONTAINER_ERR)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)

    burn_subs.burn(video, srt, out)

    assert codecs == ["copy", "aac"]
    assert os.path.isfile(out)
    assert _no_temp_outputs(out) == []


def test_burn_container_failure_with_caller_codec_is_not_retried(
    tmp_path, monkeypatch
):
    """When extra_args already choose an audio codec, burn() must respect it
    and report the failure instead of overriding it with AAC."""
    video, srt, out = _make_files(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise subprocess.CalledProcessError(1, cmd, b"", _CONTAINER_ERR)

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg failed to burn subtitles"):
        burn_subs.burn(video, srt, out, extra_args=["-c:a", "mp3"])

    assert len(calls) == 1
    # The caller's codec comes from extra_args, which must still win over
    # burn()'s own -c:a (later options override earlier ones in ffmpeg).
    assert "mp3" in calls[0]
    assert _no_temp_outputs(out) == []


def test_burn_aac_retry_failure_is_reported(tmp_path, monkeypatch):
    """If the AAC retry also fails, the RuntimeError must surface (and no
    partial output may replace the user's path)."""
    video, srt, out = _make_files(tmp_path)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, b"", _CONTAINER_ERR)

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg failed to burn subtitles"):
        burn_subs.burn(video, srt, out)

    assert not os.path.exists(out)
    assert _no_temp_outputs(out) == []
