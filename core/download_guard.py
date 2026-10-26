"""Which files a desktop download may use, resume or delete (ADR 0019).

Pure rules, no Tk and no yt-dlp import. A download names its output by title only, so the file it
plans to write can already belong to the user or to another job. The download service asks yt-dlp
for the planned names first (``--print filename``), refuses when a planned path is taken, and tracks
what the job itself created; this module holds the command rewriting, the plan parsing and the
"is this file taken" checks, so they can be tested without a process.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Marks the lines of the plan pass in yt-dlp's output (it prints nothing else on stdout).
PLAN_PREFIX = "wts-plan:"

# ``--audio-format`` values whose file does not carry the format's own name.
_AUDIO_EXT = {"aac": "m4a", "alac": "m4a", "vorbis": "ogg"}

# Pieces an unfinished download leaves next to a file.
_PIECES = (".part", ".ytdl")


class DownloadRefused(Exception):
    """The download was not started (or was stopped before it wrote anything) because a file it
    would use belongs to someone else. ``str()`` is the text shown to the user."""


@dataclass(frozen=True)
class PlannedItem:
    """One item yt-dlp will download: the file it fetches and the file the job leaves behind
    (they differ when audio is extracted: ``Title.webm`` -> ``Title.mp3``)."""

    source: str
    final: str


def norm(path: str) -> str:
    """A comparison key for a path (absolute, case folded on Windows)."""
    return os.path.normcase(os.path.abspath(path))


def command_audio_format(command: Sequence[str]) -> str | None:
    """The ``--audio-format`` value when *command* extracts audio (``-x``), else None."""
    if "-x" not in command and "--extract-audio" not in command:
        return None
    for i, arg in enumerate(command):
        if arg == "--":
            break
        if arg == "--audio-format" and i + 1 < len(command):
            return command[i + 1]
    return None


def _split_separator(command: Sequence[str]) -> tuple[list[str], list[str]]:
    """Options and the part from ``--`` on (the end-of-options separator and the URL)."""
    cmd = list(command)
    if "--" in cmd:
        at = cmd.index("--")
        return cmd[:at], cmd[at:]
    return cmd, []


def plan_command(command: Sequence[str]) -> list[str]:
    """The same download as a plan pass: yt-dlp prints the planned file name of every item and
    downloads nothing (``--print`` implies a simulation)."""
    options, tail = _split_separator(command)
    kept: list[str] = []
    skip = False
    for arg in options:
        if skip:
            skip = False
            continue
        if arg == "--progress-template":
            skip = True
            continue
        if arg in ("-k", "--keep-video"):
            continue
        kept.append(arg)
    kept += ["--print", PLAN_PREFIX + "%(filename)s"]
    return kept + tail


def with_keep_source(command: Sequence[str]) -> list[str]:
    """Audio extraction keeps its source file (``-k``): yt-dlp then never deletes a file; the app
    removes the source itself, and only when the job created it."""
    options, tail = _split_separator(command)
    if command_audio_format(command) is None or "-k" in options or "--keep-video" in options:
        return list(command)
    return options + ["-k"] + tail


def parse_plan(output: str, command: Sequence[str]) -> list[PlannedItem]:
    """The planned items out of a plan pass's stdout (lines that carry the marker)."""
    audio = command_audio_format(command)
    items: list[PlannedItem] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith(PLAN_PREFIX):
            continue
        source = line[len(PLAN_PREFIX):].strip()
        if not source:
            continue
        final = source
        if audio:
            ext = _AUDIO_EXT.get(audio, audio)
            if audio != "best":
                final = os.path.splitext(source)[0] + "." + ext
        items.append(PlannedItem(source, final))
    return items


def is_own(path: str, own: Iterable[str]) -> bool:
    """True when *path* is a file the job created earlier (*own*) or an unfinished piece of one
    (``.part``, ``.part-Frag3``, ``.ytdl``)."""
    key = norm(path)
    for base in own:
        b = norm(base)
        if key == b:
            return True
        if key.startswith(b) and key[len(b):].startswith(_PIECES + (".part-frag",)):
            return True
    return False


def _paths_in_use(item: PlannedItem) -> list[str]:
    """Existing paths the job would write, convert, merge or resume for *item*."""
    found: set[str] = set()
    for base in {item.source, item.final}:
        found.add(base)
        found.update(base + piece for piece in _PIECES)
    folder = os.path.dirname(item.final) or "."
    stems = {os.path.splitext(os.path.basename(p))[0] for p in (item.source, item.final)}
    names_in = {os.path.basename(p) for p in (item.source, item.final)}
    streams = re.compile(
        r"^(?:%s)\.f[^.]+\.[^.]+(?:\.part|\.ytdl|\.part-Frag\d+)?$"
        % "|".join(re.escape(s) for s in stems)
    )
    frags = re.compile(r"^(?:%s)\.part-Frag\d+$" % "|".join(re.escape(n) for n in names_in))
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    found.update(os.path.join(folder, n) for n in names if streams.match(n) or frags.match(n))
    return sorted(p for p in found if os.path.lexists(p))


def find_clash(items: Iterable[PlannedItem], own: Iterable[str]) -> str | None:
    """The first existing file that a planned item would use and that the job did not create, or None."""
    own = list(own)
    for item in items:
        for path in _paths_in_use(item):
            if not is_own(path, own):
                return path
    return None
