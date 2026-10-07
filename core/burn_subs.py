"""Burn an SRT into a video via ffmpeg.

One pure function: ``burn(video_path, srt_path, out_path)``. Uses
ffmpeg's ``subtitles`` filter which renders the SRT as a vector
overlay on top of the video stream.

This is a one-shot synchronous call; on large videos it can take a
while. The caller (UI service) should run it in a background
thread and surface progress via the existing ``download_events``
or a similar queue.

Video is encoded with ffmpeg's defaults (H.264) and the audio stream is
copied when the output container accepts the source codec, falling back to
an AAC re-encode when it does not (e.g. an Opus track from a downloaded
``.webm``/``.mkv``). Adjust by passing ``extra_args``.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

from ._proc import new_session_kwargs
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


def _same_path(a: str, b: str) -> bool:
    """True when *a* and *b* name the same file (works when *b* is not there yet)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _prepare_srt(srt_path: str, safe_srt_file: str) -> str:
    """Copy the SRT for ffmpeg with RTL lines wrapped; return its forced font.

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
        f.write(wrap_rtl_lines(text))
    return subtitle_font_for(text)


def burn(
    video_path: str,
    srt_path: str,
    out_path: str,
    *,
    extra_args: list[str] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Write ``out_path`` with the SRT subtitles burned into the video.

    Raises:
        FileNotFoundError if the video or srt is missing.
        ValueError        if ``out_path`` is the video or the srt itself.
        RuntimeError      if ffmpeg returns non-zero.
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

        def _cmd(audio_codec: str) -> list[str]:
            # -c:a first so caller-supplied extra_args keep their original
            # ability to override it (ffmpeg lets later options win).
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-vf", subtitle_filter,
                "-c:a", audio_codec,
            ]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(tmp_out)
            return cmd

        kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": tmp_dir,
        }
        # CREATE_NO_WINDOW on Windows; start_new_session=True on POSIX so
        # kill_process_tree can killpg this ffmpeg's OWN group if needed.
        kwargs.update(new_session_kwargs())

        # Try the audio stream-copy first (lossless + fast); if the output
        # container rejects the source codec, retry ONCE with AAC. Skipped
        # when the caller set its own audio codec, which we must not override.
        codecs = ["copy"]
        if not _extra_args_set_audio_codec(extra_args):
            codecs.append("aac")
        for codec in codecs:
            try:
                subprocess.run(_cmd(codec), check=True, timeout=timeout, **kwargs)
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
