"""Burn an SRT into a video via ffmpeg.

``burn(video_path, srt_path, out_path)`` uses ffmpeg's ``subtitles``
filter, which renders the SRT as a vector overlay on top of the video
stream. It blocks until ffmpeg ends; on large videos that takes a while,
so callers run it on a background thread. Optional hooks report a real
percent (ffmpeg ``-progress pipe:1`` against the probed duration), let the
caller cancel, and hand over the ffmpeg process so an existing cancel path
can tree-kill it.

Video is encoded with ffmpeg's defaults (H.264) and the audio stream is
copied when the output container accepts the source codec, falling back to
an AAC re-encode when it does not (e.g. an Opus track from a downloaded
``.webm``/``.mkv``). Adjust by passing ``extra_args``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, NamedTuple

from ._proc import kill_process_tree, new_session_kwargs
from .paths import bundled_binary

logger = logging.getLogger(__name__)

# ffmpeg's muxers reject an audio codec the target CONTAINER cannot carry
# (the common real case: an Opus/Vorbis track copied out of a downloaded
# .webm/.mkv into the .mp4 the Save dialog suggests). ffmpeg reports it as
# one of these two phrases; matching them lets burn() retry once with AAC
# instead of failing outright, without retrying on unrelated errors.
_CONTAINER_AUDIO_HINTS = (
    "not currently supported in container",
    "could not find tag for codec",
)


def _stderr_tail(exc: subprocess.CalledProcessError) -> str:
    return (exc.stderr or b"").decode("utf-8", "replace")[-1000:]


def _container_rejected_audio(stderr_text: str) -> bool:
    """True when ffmpeg's stderr is the container/codec-incompatibility error."""
    s = (stderr_text or "").lower()
    return any(hint in s for hint in _CONTAINER_AUDIO_HINTS)


# Audio codecs an MP4 carries that common players (phones, TVs, QuickTime)
# play; anything else is re-encoded to AAC.
_MP4_PLAYABLE_AUDIO = frozenset({"aac", "mp3", "ac3", "eac3", "alac"})


def _extra_args_set_audio_codec(extra_args: list[str] | None) -> bool:
    """True when the caller already chose an audio codec via extra_args."""
    if not extra_args:
        return False
    prefixes = ("-c:a", "-codec:a", "-acodec")
    return any(arg.startswith(prefixes) for arg in extra_args)


_RLM = chr(0x200F)  # RIGHT-TO-LEFT MARK

# Strong right-to-left letters: Hebrew, Arabic (+ Supplement / Extended-A),
# Syriac, Thaana, NKo and the Arabic/Hebrew presentation forms.
_RTL_RANGES = (
    (0x0590, 0x08FF),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFF),
)
# Letters of the Arabic script only (the font choice below is per script).
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
_HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
_KANA_RANGES = ((0x3040, 0x30FF), (0x31F0, 0x31FF))

# Windows font per script for the burned subtitles. libass falls back to
# Arial, which on Windows 10 draws a missing-glyph box inside common Persian
# words and mixes glyph weights in Chinese; Tahoma and Microsoft YaHei ship
# with every Windows install and render both cleanly. Other systems keep
# libass's own font fallback (fontconfig / CoreText).
_WINDOWS_SCRIPT_FONTS = {
    "arabic": "Tahoma",
    "han": "Microsoft YaHei",
}


def _in_ranges(ch: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def _has_rtl(line: str) -> bool:
    return any(_in_ranges(ch, _RTL_RANGES) for ch in line)


def wrap_rtl_lines(text: str) -> str:
    """Wrap every line holding right-to-left letters in U+200F marks.

    libass lays out each subtitle line with a left-to-right base direction,
    so a Persian/Arabic line's final "." "!" or "»" (neutral characters)
    is drawn at the wrong end. A RIGHT-TO-LEFT MARK at both ends gives the
    line an RTL context. The marks are invisible: removing every U+200F
    gives back the input, and wrapping twice changes nothing. SRT index and
    timing lines hold no RTL letters, so they pass through untouched.
    """
    out: list[str] = []
    for line in text.split("\n"):
        # Keep a CR of a CRLF file outside the marks.
        body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        if _has_rtl(body):
            if not body.startswith(_RLM):
                body = _RLM + body
            if not body.endswith(_RLM):
                body = body + _RLM
        out.append(body + cr)
    return "\n".join(out)


def _dominant_script(text: str) -> str:
    """``"arabic"``, ``"han"`` or ``""`` for the script most letters use."""
    arabic = han = kana = 0
    for ch in text:
        if _in_ranges(ch, _ARABIC_RANGES):
            arabic += 1
        elif _in_ranges(ch, _HAN_RANGES):
            han += 1
        elif _in_ranges(ch, _KANA_RANGES):
            kana += 1
    # Japanese mixes Han with kana; it rendered well with the default font,
    # and a Chinese font would draw its Han in Chinese glyph shapes.
    if kana:
        return ""
    if arabic and arabic >= han:
        return "arabic"
    if han:
        return "han"
    return ""


def subtitle_font_for(text: str, *, platform: str | None = None) -> str:
    """The font name to force for *text*, or ``""`` to keep libass's choice."""
    if (platform or os.name) != "nt":
        return ""
    return _WINDOWS_SCRIPT_FONTS.get(_dominant_script(text), "")


class BurnCancelled(RuntimeError):
    """The caller cancelled the burn; ffmpeg was stopped and nothing written."""


# A 1080p re-encode measured 2.2x real time on an 8-thread PC; slower CPUs
# need more, so the limit grows with the video and never drops below 1 h.
_MIN_TIMEOUT_S = 3600.0
_TIMEOUT_PER_MEDIA_SECOND = 3.0


def burn_timeout(duration_s: float) -> float:
    """The ffmpeg time limit for a video of *duration_s* seconds."""
    return max(_MIN_TIMEOUT_S, _TIMEOUT_PER_MEDIA_SECOND * max(0.0, duration_s))


class MediaInfo(NamedTuple):
    """What ffprobe reported: ``has_video`` is None when the probe failed."""

    duration: float
    has_video: bool | None
    audio_codec: str


def probe_media(path: str) -> MediaInfo:
    """Duration, video presence and first audio codec of *path* (one ffprobe)."""
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "timeout": 60,
    }
    kwargs.update(new_session_kwargs())
    try:
        r = subprocess.run(
            [bundled_binary("ffprobe"), "-v", "error",
             "-show_entries", "format=duration:stream=codec_type,codec_name",
             "-of", "json", path],
            **kwargs,
        )
        if r.returncode != 0:
            raise ValueError(f"ffprobe exit {r.returncode}")
        data = json.loads((r.stdout or b"").decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        logger.warning("Subtitle burn: could not probe %s (%s)", path, e)
        return MediaInfo(0.0, None, "")
    streams = data.get("streams") or []
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    audio = next(
        (str(st.get("codec_name") or "") for st in streams if st.get("codec_type") == "audio"),
        "",
    )
    return MediaInfo(
        duration if duration > 0 else 0.0,
        any(st.get("codec_type") == "video" for st in streams),
        audio,
    )


def probe_duration(path: str) -> float:
    """The media duration in seconds from ffprobe, or 0.0 when unknown."""
    return probe_media(path).duration


def free_output_path(path: str) -> str:
    """*path* when nothing is there, else the first free ``name (N).ext``.

    An earlier result of the same video is never replaced silently.
    """
    if not os.path.lexists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.lexists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def reserve_output_path(path: str) -> str:
    """Like ``free_output_path`` but creates the file empty (exclusive create),
    so two jobs started at once never pick the same name. ``burn()`` then
    replaces this placeholder; ``release_reserved_path`` removes it when no
    video was made."""
    stem, ext = os.path.splitext(path)
    candidate, n = path, 2
    while True:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            candidate = f"{stem} ({n}){ext}"
            n += 1
            continue
        os.close(fd)
        return candidate


def release_reserved_path(path: str) -> None:
    """Remove a placeholder from ``reserve_output_path`` if it is still empty."""
    try:
        if os.path.isfile(path) and os.path.getsize(path) == 0:
            os.unlink(path)
    except OSError:
        logger.warning("Could not remove the empty placeholder %s", path)


def parse_progress_seconds(line: str) -> float | None:
    """Seconds encoded so far from one ffmpeg ``-progress`` line, else None.

    ``out_time_us`` and (despite its name) ``out_time_ms`` both count
    MICROseconds; ``N/A`` appears before the first frame.
    """
    key, sep, value = line.strip().partition("=")
    if not sep or key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(0, int(value)) / 1_000_000
    except ValueError:
        return None


def _run_ffmpeg(
    cmd: list[str],
    *,
    timeout: float,
    duration_s: float = 0.0,
    progress_cb: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[Any], None] | None = None,
    **popen_kwargs: Any,
) -> None:
    """Run ffmpeg like ``subprocess.run(check=True)``, with progress and cancel.

    stdout carries the ``-progress`` lines; stderr is drained on its own
    thread (an unread pipe stalls a long encode) and its tail goes into the
    ``CalledProcessError`` on failure. A cancel or the time limit tree-kills
    ffmpeg; a cancel raises ``BurnCancelled``.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, **popen_kwargs,
    )
    if on_process is not None:
        on_process(proc)
    stderr_tail = bytearray()

    err_stream = proc.stderr
    out_stream = proc.stdout
    assert err_stream is not None and out_stream is not None

    def _drain_stderr() -> None:
        while True:
            chunk = err_stream.read(4096)
            if not chunk:
                return
            stderr_tail.extend(chunk)
            del stderr_tail[:-8192]

    def _read_progress() -> None:
        last = -1.0
        for raw in out_stream:
            line = raw.decode("ascii", "replace")
            if progress_cb is None:
                continue
            # "progress=end" also ends a FAILED run, so 100 is only reported
            # after a zero exit (below).
            secs = parse_progress_seconds(line)
            if secs is None or duration_s <= 0:
                continue
            pct = min(99.0, 100.0 * secs / duration_s)
            if pct > last:
                last = pct
                progress_cb(pct)

    readers = [
        threading.Thread(target=_drain_stderr, name="burn-stderr", daemon=True),
        threading.Thread(target=_read_progress, name="burn-progress", daemon=True),
    ]
    for t in readers:
        t.start()
    deadline = time.monotonic() + timeout
    cancelled = timed_out = False
    while proc.poll() is None:
        if cancel_check is not None and cancel_check():
            cancelled = True
        elif time.monotonic() >= deadline:
            timed_out = True
        if cancelled or timed_out:
            kill_process_tree(proc, force=True)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            break
        time.sleep(0.1)
    for t in readers:
        t.join(timeout=10)
    # An outside kill (the queue's own Cancel) ends ffmpeg before this loop
    # sees the flag, so ask once more.
    if cancelled or (cancel_check is not None and cancel_check()):
        raise BurnCancelled("Subtitle burn cancelled")
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, b"", bytes(stderr_tail)
        )
    if progress_cb is not None:
        progress_cb(100.0)


def _same_path(a: str, b: str) -> bool:
    """True when *a* and *b* name the same file (works when *b* is not there yet)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


_WJ = chr(0x2060)  # WORD JOINER: invisible, breaks a libass "\N"-style code
_BACKSLASH = chr(92)
_SRT_TIMING_ARROW = "-->"


def escape_cue_text(line: str) -> str:
    """Make one SRT cue line render as written, not as libass/ffmpeg markup.

    ffmpeg turns SRT into ASS, so ``{...}`` is an override block (``{\\an8}``
    moved a cue to the top, ``{x}`` vanished), ``\\N`` / ``\\n`` / ``\\h``
    are a line break or a space, and ``<i>``/``<b>``/``<font>`` are HTML-like
    tags. Braces get a backslash escape; a backslash and a ``<`` before a
    letter or ``/`` get an invisible WORD JOINER after them. Undo: drop
    ``\\`` before ``{``/``}`` first, then every U+2060.
    """
    out: list[str] = []
    for i, ch in enumerate(line):
        if ch in "{}":
            out.append(_BACKSLASH + ch)
        elif ch == _BACKSLASH:
            out.append(ch + _WJ)
        elif ch == "<" and (line[i + 1:i + 2].isalpha() or line[i + 1:i + 2] == "/"):
            out.append(ch + _WJ)
        else:
            out.append(ch)
    return "".join(out)


def escape_srt_markup(text: str) -> str:
    """``escape_cue_text`` on every cue line; index and timing lines unchanged."""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if _SRT_TIMING_ARROW in line or line.strip().isdigit():
            continue
        lines[n] = escape_cue_text(line)
    return "\n".join(lines)


def _prepare_srt(srt_path: str, safe_srt_file: str) -> str:
    """Copy the SRT for ffmpeg with markup escaped and RTL lines wrapped;
    return its forced font.

    A file that is not UTF-8 is copied byte for byte (ffmpeg reads it as
    before) with no wrap and no forced font.
    """
    try:
        with open(srt_path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except UnicodeDecodeError:
        logger.warning(
            "Subtitle burn: %s is not UTF-8; burning it without the RTL/font fix",
            srt_path,
        )
        shutil.copyfile(srt_path, safe_srt_file)
        return ""
    with open(safe_srt_file, "w", encoding="utf-8", newline="") as f:
        f.write(wrap_rtl_lines(escape_srt_markup(text)))
    return subtitle_font_for(text)


def burn(
    video_path: str,
    srt_path: str,
    out_path: str,
    *,
    extra_args: list[str] | None = None,
    timeout: float | None = None,
    progress_cb: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[Any], None] | None = None,
) -> None:
    """Write ``out_path`` with the SRT subtitles burned into the video.

    ``timeout`` defaults to ``burn_timeout`` of the probed duration.
    ``progress_cb(percent)`` runs on a reader thread, rising to 100.
    ``cancel_check()`` is polled about ten times a second; True stops
    ffmpeg. ``on_process(popen)`` receives each ffmpeg process as it starts.

    Raises:
        FileNotFoundError if the video or srt is missing.
        ValueError        if ``out_path`` is the video or the srt itself.
        BurnCancelled     if ``cancel_check`` asked to stop.
        RuntimeError      if ffmpeg returns non-zero or runs out of time.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if not os.path.isfile(srt_path):
        raise FileNotFoundError(f"srt not found: {srt_path}")
    # The final os.replace would put the encode over the source (the
    # original video was lost this way when the Save dialog's name was
    # changed to the source's own name).
    for src in (video_path, srt_path):
        if _same_path(src, out_path):
            raise ValueError(
                f"The output file must differ from the source: {out_path}"
            )
    video_path = os.path.abspath(video_path)
    info = probe_media(video_path)
    if info.has_video is False:
        raise ValueError(
            "This file has no video picture to burn the subtitles into: "
            f"{video_path}"
        )
    duration_s = info.duration
    if timeout is None:
        timeout = burn_timeout(duration_s)

    ffmpeg = bundled_binary("ffmpeg")
    # ffmpeg's `subtitles=` value is parsed as a libavfilter *filter graph*,
    # where ' , ; [ ] : \ are metacharacters. The SRT path is derived from
    # the media filename, and for a downloaded video that name comes
    # straight from the (attacker-influenced) yt-dlp title — which keeps
    # ' [ ] , by default. Interpolating such a name into the graph string
    # both breaks burning for legitimately-punctuated titles AND is a
    # filter-injection vector. Rather than juggle ffmpeg's brittle
    # multi-level escaping, copy the SRT into a temp dir as "subs.srt" and
    # run ffmpeg IN that dir, so the graph only ever holds the bare
    # relative name (the temp dir's own path can hold a drive colon, an
    # apostrophe or brackets of the user name).
    tmp_dir = tempfile.mkdtemp(prefix="burnsubs_")
    safe_srt_file = os.path.join(tmp_dir, "subs.srt")
    # Encode into a temp sibling of out_path instead of writing the final
    # path directly: ffmpeg `-y` truncates its output the moment it starts,
    # so a mid-way failure (bad source, disk full, the 1 h timeout) used to
    # leave a corrupt partial file under the user's chosen name — and could
    # destroy an existing file the user picked by mistake. The temp lives
    # in the same directory (same filesystem) so os.replace below is atomic.
    out_dir = os.path.dirname(os.path.abspath(out_path))
    tmp_out = ""
    try:
        font = _prepare_srt(srt_path, safe_srt_file)
        subtitle_filter = "subtitles=subs.srt"
        if font:
            subtitle_filter += f":force_style='FontName={font}'"
        fd, tmp_out = tempfile.mkstemp(
            prefix=".burn-",
            suffix=os.path.splitext(out_path)[1],
            dir=out_dir,
        )
        os.close(fd)
        is_mp4 = os.path.splitext(out_path)[1].lower() in (".mp4", ".m4v", ".mov")

        def _cmd(audio_codec: str) -> list[str]:
            # -c:a first so caller-supplied extra_args keep their original
            # ability to override it (ffmpeg lets later options win).
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-vf", subtitle_filter,
                "-c:a", audio_codec,
                # 8-bit 4:2:0 H.264 plays everywhere (a 10-bit or 4:4:4
                # source otherwise gives a profile phones and TVs refuse).
                "-pix_fmt", "yuv420p",
                "-progress", "pipe:1",
                "-nostats",
            ]
            if is_mp4:
                cmd += ["-movflags", "+faststart"]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(tmp_out)
            return cmd

        best = [-1.0]

        def _rising(pct: float) -> None:
            # The AAC retry is a second ffmpeg run starting at 0 again.
            if progress_cb is not None and pct > best[0]:
                best[0] = pct
                progress_cb(pct)

        kwargs: dict[str, Any] = {
            "cwd": tmp_dir,
            "duration_s": duration_s,
            "progress_cb": _rising if progress_cb is not None else None,
            "cancel_check": cancel_check,
            "on_process": on_process,
        }
        # CREATE_NO_WINDOW on Windows; start_new_session=True on POSIX so
        # kill_process_tree can killpg this ffmpeg's OWN group if needed.
        kwargs.update(new_session_kwargs())

        # Try the audio stream-copy first (lossless + fast); if the output
        # container rejects the source codec, retry ONCE with AAC. Skipped
        # when the caller set its own audio codec, which we must not override.
        codecs = ["copy"]
        if not _extra_args_set_audio_codec(extra_args):
            if is_mp4 and info.audio_codec and info.audio_codec not in _MP4_PLAYABLE_AUDIO:
                # ffmpeg accepts Opus/Vorbis/FLAC/PCM in MP4, but most
                # players do not play them there.
                codecs = ["aac"]
            else:
                codecs.append("aac")
        for codec in codecs:
            if cancel_check is not None and cancel_check():
                raise BurnCancelled("Subtitle burn cancelled")
            try:
                _run_ffmpeg(_cmd(codec), timeout=timeout, **kwargs)
                break
            except subprocess.CalledProcessError as e:
                msg = _stderr_tail(e)
                if codec == codecs[-1] or not _container_rejected_audio(msg):
                    raise RuntimeError(
                        f"ffmpeg failed to burn subtitles: {msg}"
                    ) from e
                logger.warning(
                    "Subtitle burn: output container rejected the copied "
                    "audio (%s); retrying with AAC",
                    msg.splitlines()[-1] if msg else "unknown ffmpeg error",
                )
                continue
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"ffmpeg timed out burning subtitles after {timeout}s"
                ) from e
        os.replace(tmp_out, out_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_out:
            try:
                os.unlink(tmp_out)
            except OSError:
                pass
