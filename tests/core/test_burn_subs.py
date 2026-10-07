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
    # The temp copy is always the bare relative name subs.srt; ffmpeg runs
    # inside the temp dir, so no directory part reaches the graph.
    assert body == "subs.srt"
    assert os.path.isabs(captured["kwargs"]["cwd"])
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

    tmp_dir = captured["kwargs"]["cwd"]
    assert os.path.basename(tmp_dir).startswith("burnsubs_")
    assert not os.path.exists(tmp_dir), "temp dir should be cleaned up after burn"


def test_burn_temp_dir_cleaned_up_on_ffmpeg_failure(tmp_path, monkeypatch):
    """Even when ffmpeg fails, the temp copy must not leak."""
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["dir"] = kwargs["cwd"]
        assert os.path.isfile(os.path.join(kwargs["cwd"], "subs.srt"))
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


# --- same-file guard, graph-safe temp dir, RTL wrap + per-script font ------

RLM = chr(0x200F)


def test_burn_refuses_to_write_over_the_source_video(tmp_path, monkeypatch):
    """out_path == the source video used to replace the original with the
    encode (the final os.replace). It must fail before ffmpeg runs."""
    captured = _capture_cmd(monkeypatch)
    video, srt, _out = _make_files(tmp_path)
    before = Path(video).read_bytes()
    with pytest.raises(ValueError, match="must differ from the source"):
        burn_subs.burn(video, srt, video)
    with pytest.raises(ValueError, match="must differ from the source"):
        burn_subs.burn(video, srt, srt)
    assert "cmd" not in captured
    assert Path(video).read_bytes() == before


def test_burn_same_file_guard_handles_another_spelling(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    video, srt, _out = _make_files(tmp_path)
    other = os.path.join(str(tmp_path), ".", os.path.basename(video))
    with pytest.raises(ValueError):
        burn_subs.burn(video, srt, other)
    assert "cmd" not in captured


def test_burn_temp_dir_with_graph_metacharacters(tmp_path, monkeypatch):
    """A temp dir holding ' , ; [ ] (possible in a user-profile path) must not
    reach the filter graph: ffmpeg runs in it and gets only "subs.srt"."""
    captured = _capture_cmd(monkeypatch)
    weird = tmp_path / "it's, [odd]; tmp"
    weird.mkdir()

    def fake_mkdtemp(prefix=""):
        path = weird / (prefix + "x")
        path.mkdir()
        return str(path)

    monkeypatch.setattr(burn_subs.tempfile, "mkdtemp", fake_mkdtemp)
    video, srt, out = _make_files(tmp_path)
    burn_subs.burn(video, srt, out)
    vf = _vf_value(captured["cmd"])
    assert vf.split(":")[0] == "subtitles=subs.srt"
    assert captured["kwargs"]["cwd"] == str(weird / "burnsubs_x")
    # The video is passed absolute, since ffmpeg's cwd is the temp dir.
    assert os.path.isabs(captured["cmd"][captured["cmd"].index("-i") + 1])
    assert os.path.isabs(captured["cmd"][-1])


def _capture_with_srt(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        with open(os.path.join(kwargs["cwd"], "subs.srt"), "rb") as f:
            captured["srt"] = f.read()
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs.subprocess, "run", fake_run)
    return captured


def test_burn_wraps_persian_lines_and_forces_a_font_on_windows(tmp_path, monkeypatch):
    captured = _capture_with_srt(monkeypatch)
    monkeypatch.setattr(burn_subs.os, "name", "nt")
    video, _s, out = _make_files(tmp_path)
    srt = tmp_path / "fa.srt"
    srt.write_bytes(
        "1\r\n00:00:00,000 --> 00:00:02,000\r\nسلام دنیا!\r\n".encode("utf-8-sig")
    )
    burn_subs.burn(video, str(srt), out)
    text = captured["srt"].decode("utf-8")
    assert text == (
        "1\r\n00:00:00,000 --> 00:00:02,000\r\n" + RLM + "سلام دنیا!" + RLM + "\r\n"
    )
    assert _vf_value(captured["cmd"]) == "subtitles=subs.srt:force_style='FontName=Tahoma'"


def test_burn_latin_srt_is_copied_unchanged_without_a_font(tmp_path, monkeypatch):
    captured = _capture_with_srt(monkeypatch)
    monkeypatch.setattr(burn_subs.os, "name", "nt")
    video, srt, out = _make_files(tmp_path)
    burn_subs.burn(video, srt, out)
    assert captured["srt"] == Path(srt).read_bytes()
    assert _vf_value(captured["cmd"]) == "subtitles=subs.srt"


def test_burn_non_utf8_srt_is_copied_byte_for_byte(tmp_path, monkeypatch):
    captured = _capture_with_srt(monkeypatch)
    video, _s, out = _make_files(tmp_path)
    srt = tmp_path / "cp.srt"
    raw = "1\n00:00:00,000 --> 00:00:01,000\nسلام\n".encode("cp1256")
    srt.write_bytes(raw)
    burn_subs.burn(video, str(srt), out)
    assert captured["srt"] == raw
    assert _vf_value(captured["cmd"]) == "subtitles=subs.srt"


@pytest.mark.parametrize(
    "text, font",
    [
        ("سلام دنیا", "Tahoma"),            # Persian
        ("مرحبا بالعالم", "Tahoma"),        # Arabic
        ("你好，世界", "Microsoft YaHei"),   # Chinese
        ("こんにちは世界", ""),               # Japanese: kana present -> default
        ("नमस्ते दुनिया", ""),                # Hindi
        ("สวัสดีชาวโลก", ""),                # Thai
        ("Привет, мир", ""),                # Russian
        ("Hello world", ""),
        ("", ""),
    ],
)
def test_subtitle_font_for_each_script(text, font):
    assert burn_subs.subtitle_font_for(text, platform="nt") == font
    # Other systems keep libass's own fallback.
    assert burn_subs.subtitle_font_for(text, platform="posix") == ""


def test_wrap_rtl_lines_known_cases():
    w = burn_subs.wrap_rtl_lines
    assert w("سلام.") == RLM + "سلام." + RLM
    assert w("שלום!") == RLM + "שלום!" + RLM
    assert w("hello.") == "hello."
    assert w("1\n00:00:00,000 --> 00:00:01,000\nسلام\n") == (
        "1\n00:00:00,000 --> 00:00:01,000\n" + RLM + "سلام" + RLM + "\n"
    )
    assert w("a\r\nسلام\r\n") == "a\r\n" + RLM + "سلام" + RLM + "\r\n"


def test_wrap_rtl_lines_properties():
    """Randomised property check (standard library only): the wrap never
    changes the visible text, never adds or drops a line, keeps line
    endings, and is idempotent."""
    import random

    rng = random.Random(20261008)
    alphabet = list("ab .!?»«،؟:") + ["سل", "ام", "דנ", "你好", "\r", "\n", "\n", RLM, "1", ","]
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        out = burn_subs.wrap_rtl_lines(text)
        # Removing the marks gives back the input with its own marks removed.
        assert out.replace(RLM, "") == text.replace(RLM, "")
        assert out.count("\n") == text.count("\n")
        assert out.count("\r") == text.count("\r")
        assert burn_subs.wrap_rtl_lines(out) == out
        for line in out.split("\n"):
            body = line[:-1] if line.endswith("\r") else line
            if burn_subs._has_rtl(body):
                assert body.startswith(RLM) and body.endswith(RLM)
            else:
                assert RLM not in body or RLM in text
