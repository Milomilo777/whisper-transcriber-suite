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
        RuntimeError      if ffmpeg returns non-zero.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if not os.path.isfile(srt_path):
        raise FileNotFoundError(f"srt not found: {srt_path}")

    ffmpeg = bundled_binary("ffmpeg")
    # ffmpeg's `subtitles=` value is parsed as a libavfilter *filter graph*,
    # where ' , ; [ ] are metacharacters. The SRT path is derived from the
    # media filename, and for a downloaded video that name comes straight
    # from the (attacker-influenced) yt-dlp title — which keeps ' [ ] , by
    # default. Interpolating such a name into the graph string both breaks
    # burning for legitimately-punctuated titles AND is a filter-injection
    # vector. Rather than juggle ffmpeg's brittle multi-level escaping, copy
    # the SRT to a temp file with a graph-safe ASCII basename and burn from
    # there. The only remaining special char is the Windows drive-letter
    # colon (the temp DIRECTORY can't contain ' , ; [ ] — those are illegal
    # in Windows usernames, and POSIX temp dirs don't use them); escape it
    # the same proven way, but only on Windows so a legal POSIX colon in the
    # temp path isn't mangled.
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
        shutil.copyfile(srt_path, safe_srt_file)
        filter_path = safe_srt_file.replace("\\", "/")
        if os.name == "nt":
            filter_path = filter_path.replace(":", "\\\\:")
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
                "-vf", f"subtitles={filter_path}",
                "-c:a", audio_codec,
            ]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(tmp_out)
            return cmd

        kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
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
