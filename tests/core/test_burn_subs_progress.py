"""burn() v2: progress, cancel, time limit, output naming, text round trip.

Fake ffmpeg runs are a Python child that speaks ffmpeg's ``-progress``
protocol; one test runs the real bundled ffmpeg when it is present.
"""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import time

import pytest

from core import burn_subs
from core.writers import srt as srt_writer

_RLM = chr(0x200F)

# A stand-in for ffmpeg: writes part of the output, reports progress lines,
# floods stderr, then exits with the given code or hangs.
_FAKE = r"""
import sys, time
out, steps, code, hang, flood = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1", int(sys.argv[5])
open(out, "wb").write(b"partial")
sys.stderr.write("x" * flood + "\nLAST STDERR LINE\n")
sys.stderr.flush()
for i in range(1, steps + 1):
    print(f"out_time_us={i * 1000000}", flush=True)
    print("progress=continue", flush=True)
    time.sleep(0.02)
if hang:
    time.sleep(60)
print("progress=end", flush=True)
sys.exit(code)
"""


def _files(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    srt = tmp_path / "clip.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    return str(video), str(srt), str(tmp_path / "clip-subbed.mp4")


def _use_fake(monkeypatch, *, steps=5, code=0, hang=False, flood=0, duration=10.0):
    real = burn_subs._run_ffmpeg
    seen: dict = {"procs": []}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        seen["timeout"] = kw["timeout"]
        fake = [sys.executable, "-c", _FAKE, cmd[-1], str(steps), str(code),
                "1" if hang else "0", str(flood)]
        user_on_process = kw.get("on_process")

        def on_process(p):
            seen["procs"].append(p)
            if user_on_process:
                user_on_process(p)

        kw["on_process"] = on_process
        return real(fake, **kw)

    monkeypatch.setattr(burn_subs, "_run_ffmpeg", run)
    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(burn_subs, "probe_duration", lambda path: duration)
    return seen


def test_progress_is_a_rising_percent_that_ends_at_100(tmp_path, monkeypatch):
    seen = _use_fake(monkeypatch, steps=5, duration=10.0)
    video, srt, out = _files(tmp_path)
    got: list[float] = []

    burn_subs.burn(video, srt, out, progress_cb=got.append)

    assert got == sorted(got) and got[-1] == 100.0
    assert got[:5] == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert "-progress" in seen["cmd"] and "pipe:1" in seen["cmd"]
    assert os.path.isfile(out)


def test_cancel_stops_ffmpeg_and_leaves_no_output(tmp_path, monkeypatch):
    seen = _use_fake(monkeypatch, steps=3, hang=True)
    video, srt, out = _files(tmp_path)
    progress: list[float] = []

    start = time.monotonic()
    with pytest.raises(burn_subs.BurnCancelled):
        burn_subs.burn(
            video, srt, out,
            progress_cb=progress.append,
            cancel_check=lambda: bool(progress),
        )

    assert time.monotonic() - start < 30
    assert seen["procs"] and all(p.poll() is not None for p in seen["procs"])
    assert sorted(os.listdir(tmp_path)) == ["clip.mp4", "clip.srt"]


def test_cancel_before_start_runs_nothing(tmp_path, monkeypatch):
    seen = _use_fake(monkeypatch)
    video, srt, out = _files(tmp_path)
    with pytest.raises(burn_subs.BurnCancelled):
        burn_subs.burn(video, srt, out, cancel_check=lambda: True)
    assert seen["procs"] == []
    assert sorted(os.listdir(tmp_path)) == ["clip.mp4", "clip.srt"]


def test_time_limit_kills_ffmpeg(tmp_path, monkeypatch):
    seen = _use_fake(monkeypatch, hang=True)
    video, srt, out = _files(tmp_path)
    with pytest.raises(RuntimeError, match="timed out"):
        burn_subs.burn(video, srt, out, timeout=1.5)
    assert all(p.poll() is not None for p in seen["procs"])
    assert sorted(os.listdir(tmp_path)) == ["clip.mp4", "clip.srt"]


def test_big_stderr_does_not_stall_and_its_tail_is_reported(tmp_path, monkeypatch):
    _use_fake(monkeypatch, code=1, flood=300_000)
    video, srt, out = _files(tmp_path)
    with pytest.raises(RuntimeError, match="LAST STDERR LINE"):
        burn_subs.burn(video, srt, out, timeout=60)
    assert sorted(os.listdir(tmp_path)) == ["clip.mp4", "clip.srt"]


def test_default_time_limit_grows_with_the_video(tmp_path, monkeypatch):
    seen = _use_fake(monkeypatch, duration=7200.0)
    video, srt, out = _files(tmp_path)
    burn_subs.burn(video, srt, out)
    assert seen["timeout"] == 3 * 7200.0
    assert burn_subs.burn_timeout(10) == 3600.0
    assert burn_subs.burn_timeout(0) == 3600.0


@pytest.mark.parametrize(
    "line, secs",
    [
        ("out_time_us=2800000", 2.8),
        ("out_time_ms=2800000", 2.8),  # microseconds despite the name
        ("out_time_us=N/A", None),
        ("out_time=00:00:02.800000", None),
        ("progress=end", None),
        ("out_time_us=-5", 0.0),
    ],
)
def test_parse_progress_seconds(line, secs):
    assert burn_subs.parse_progress_seconds(line) == secs


def test_free_output_path(tmp_path):
    first = str(tmp_path / "a-subbed.mp4")
    assert burn_subs.free_output_path(first) == first
    open(first, "wb").close()
    assert burn_subs.free_output_path(first) == str(tmp_path / "a-subbed (2).mp4")
    open(str(tmp_path / "a-subbed (2).mp4"), "wb").close()
    assert burn_subs.free_output_path(first) == str(tmp_path / "a-subbed (3).mp4")


# -- real ffmpeg -----------------------------------------------------------------

def _real_ffmpeg() -> str | None:
    exe = burn_subs.bundled_binary("ffmpeg")
    return exe if os.path.isfile(exe) or shutil.which(exe) else None


@pytest.mark.skipif(_real_ffmpeg() is None, reason="ffmpeg not available")
def test_real_ffmpeg_burn_keeps_duration_and_video(tmp_path):
    ffmpeg = _real_ffmpeg()
    assert ffmpeg is not None
    video = tmp_path / "clip [1].mp4"
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-shortest", str(video)],
        check=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    srt = tmp_path / "clip [1].srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,500\n"
        + "سلام دنیا. {x} \\N 你好\n",
        encoding="utf-8",
    )
    out = str(tmp_path / "clip [1]-subbed.mp4")
    got: list[float] = []

    burn_subs.burn(str(video), str(srt), out, progress_cb=got.append)

    assert got and got[-1] == 100.0
    probe = subprocess.run(
        [burn_subs.bundled_binary("ffprobe"), "-v", "error", "-show_entries",
         "format=duration:stream=codec_type", "-of", "default=noprint_wrappers=1", out],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert "codec_type=video" in probe.stdout
    duration = float(re.search(r"duration=([\d.]+)", probe.stdout).group(1))  # type: ignore[union-attr]
    assert abs(duration - burn_subs.probe_duration(str(video))) <= 1.0
    assert sorted(os.listdir(tmp_path)) == sorted(
        ["clip [1].mp4", "clip [1].srt", "clip [1]-subbed.mp4"]
    )


# -- text round trip: what ffmpeg reads equals the transcript ---------------------

_ALPHABETS = [
    "abc xyz",
    "سلام من کتاب یک.",
    "مرحبا بكم، كيف الحال؟",
    "你好世界。我们",
    "\U0001F600\U0001F44D‍",
    "{}\\{\\}\\N\\h",
    "--> <i> & «» \"' ,;[]:",
    "‌ 12 3.5%",
]


def _random_text(rng: random.Random) -> str:
    pool = "".join(rng.sample(_ALPHABETS, k=rng.randint(1, 3)))
    return "".join(rng.choice(pool) for _ in range(rng.randint(1, 40)))


def _parse_back(text: str) -> list[str]:
    """Cue payloads of an SRT, one string per cue (no multi-line payloads)."""
    body = text.replace("\r\n", "\n").strip("\n")
    if not body:
        return []
    blocks = body.split("\n\n")
    out = []
    for b in blocks:
        lines = b.split("\n")
        assert lines[0].strip().isdigit() and "-->" in lines[1], b
        out.append("\n".join(lines[2:]))
    return out


def _burned_texts(tmp_path, segments, prepare=None) -> list[str]:
    srt = tmp_path / "in.srt"
    srt.write_text(srt_writer.write(segments), encoding="utf-8")
    safe = tmp_path / "subs.srt"
    (prepare or burn_subs._prepare_srt)(str(srt), str(safe))
    payloads = _parse_back(safe.read_text(encoding="utf-8"))
    texts = []
    for seg, payload in zip(
        [s for s in segments if " ".join(str(s["text"]).split())], payloads
    ):
        payload = payload.replace(_RLM, "")
        prefix = f"{seg['speaker']}: " if seg.get("speaker") else ""
        assert payload.startswith(prefix)
        texts.append(payload[len(prefix):].replace("→", "-->"))
    return texts


def _expected(segments) -> list[str]:
    return [t for t in (" ".join(str(s["text"]).split()) for s in segments) if t]


def _random_segments(rng: random.Random) -> list[dict]:
    segs = []
    t = 0.0
    for _ in range(rng.randint(1, 12)):
        seg = {"start": t, "end": t + rng.uniform(0.2, 3), "text": _random_text(rng)}
        if rng.random() < 0.3:
            seg["speaker"] = f"Speaker {rng.randint(1, 3)}"
        segs.append(seg)
        t = seg["end"]
    return segs


@pytest.mark.parametrize("seed", range(150))
def test_burned_text_equals_the_transcript(tmp_path, seed):
    """No loss, no reorder: the SRT ffmpeg reads holds the transcript text
    once the documented decorations are removed (RLM marks, the speaker
    prefix, the SRT arrow for a literal "-->")."""
    rng = random.Random(seed)
    segments = _random_segments(rng)
    assert _burned_texts(tmp_path, segments) == _expected(segments)


def test_round_trip_check_catches_a_broken_preparer(tmp_path):
    """Negative control: a preparer that drops one character must fail."""
    def broken(src, dst):
        text = open(src, encoding="utf-8").read()
        text = burn_subs.wrap_rtl_lines(text).replace("ل", "", 1)
        open(dst, "w", encoding="utf-8", newline="").write(text)
        return ""

    segments = [{"start": 0, "end": 1, "text": "سلام دنیا"}]
    assert _burned_texts(tmp_path, segments) == _expected(segments)
    assert _burned_texts(tmp_path, segments, prepare=broken) != _expected(segments)
