"""Probe container audio tracks and prepare audio on the source timeline."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from .paths import bundled_binary


@dataclass(frozen=True)
class AudioTrack:
    ordinal: int
    language: str
    title: str
    channels: int
    default: bool


def audio_ordinal(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _probe(source: str, timeout: float) -> dict:
    result = subprocess.run(
        [bundled_binary("ffprobe"), "-v", "error", "-protocol_whitelist", "file",
         "-select_streams", "a",
         "-show_entries", "format=duration:stream=channels,duration:stream_tags=language,title:stream_disposition=default",
         "-of", "json", "-i", os.path.abspath(source)],
        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return json.loads(result.stdout)


def probe_audio_tracks(source: str, *, timeout: float = 5) -> list[AudioTrack]:
    if not os.path.isfile(source):
        return []
    try:
        streams = _probe(source, timeout).get("streams", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []  # The normal decoder reports unreadable inputs.
    return [
        AudioTrack(
            ordinal, str(stream.get("tags", {}).get("language") or ""),
            str(stream.get("tags", {}).get("title") or ""),
            stream.get("channels") or 0, stream.get("disposition", {}).get("default") == 1,
        )
        for ordinal, stream in enumerate(streams)
    ]


def default_audio_track(tracks: list[AudioTrack]) -> int:
    return next((track.ordinal for track in tracks if track.default), tracks[0].ordinal)


class AudioPreparationError(RuntimeError):
    """The chosen stream could not be turned into a usable audio file."""


class AudioPreparationCancelled(Exception):
    pass


def _decode(
    source: str, target: Path, ordinal: int | None, limit: int,
    cancelled: Callable[[], bool], *, repair: bool = False,
) -> tuple[int, str]:
    flags = ["-fflags", "+discardcorrupt", "-err_detect", "ignore_err"] if repair else ["-xerror"]
    mapping = f"0:a:{ordinal}" if ordinal is not None else "0:a:0"
    with tempfile.TemporaryFile() as diagnostics, subprocess.Popen(
        [bundled_binary("ffmpeg"), "-nostdin", "-v", "error", "-y",
         "-protocol_whitelist", "file", *flags, "-i", os.path.abspath(source),
         "-map", mapping, "-af", "aresample=16000:async=1:first_pts=0",
         "-ac", "1", "-c:a", "pcm_s16le", "-fs", str(limit), str(target)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=diagnostics,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        try:
            while True:
                if cancelled():
                    raise AudioPreparationCancelled
                try:
                    process.wait(timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        diagnostics.seek(0)
        return process.returncode, diagnostics.read(2048).decode("utf-8", errors="replace")


def _new_copy(folder: Path) -> tuple[Path, int]:
    folder.mkdir(parents=True, exist_ok=True)
    reserve = 64 * 1024**2
    limit = min(4 * 1024**3 - reserve, shutil.disk_usage(folder).free - reserve)
    if limit < 1024**2:
        raise OSError("Not enough free space for temporary audio.")
    descriptor, name = tempfile.mkstemp(prefix="audio-copy-", suffix=".wav", dir=folder)
    os.close(descriptor)
    return Path(name), limit


def prepare_audio_track(
    source: str, ordinal: int, folder: Path, cancelled: Callable[[], bool],
) -> Path:
    target, limit = _new_copy(folder)
    try:
        code, detail = _decode(source, target, ordinal, limit, cancelled)
        size = target.stat().st_size
        if size >= limit - 65536:
            raise OSError("Not enough free space for the selected audio track.")
        if code or size <= 128:
            raise AudioPreparationError(detail.strip() or "The selected audio track could not be decoded.")
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise
