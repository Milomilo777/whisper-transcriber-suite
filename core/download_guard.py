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
# yt-dlp names fragments "<file>.part-Frag<N>" (downloader/fragment.py); norm() keeps case off Windows.
_PIECE_SUFFIX = re.compile(r"\.(?:part(?:-frag\d+)?|ytdl)", re.IGNORECASE)


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
        if key.startswith(b) and _PIECE_SUFFIX.fullmatch(key[len(b):]):
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
    # ``Title.f137.mp4``, ``Title.fhls-720.mp4``: "f" plus a format id (digits, or hls-/dash-/http-
    # prefixed). Not ``Title.fa.vtt`` / ``Title.fr.srt``: those are subtitle files (language codes).
    streams = re.compile(
        r"^(?:%s)\.f(?:\d|hls-|dash-|http-)[^.]*\.[^.]+(?:\.part|\.ytdl|\.part-Frag\d+)?$"
        % "|".join(re.escape(s) for s in stems)
    )
    frags = re.compile(r"^(?:%s)\.part-Frag\d+$" % "|".join(re.escape(n) for n in names_in))
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    found.update(os.path.join(folder, n) for n in names if streams.match(n) or frags.match(n))
    return sorted(p for p in found if os.path.lexists(p))


def stem_key(item: PlannedItem) -> str:
    """Comparison key of the name (without extension) a planned item is written under."""
    return norm(os.path.splitext(item.final)[0])


def find_clash(
    items: Iterable[PlannedItem], own: Iterable[str], owned_stems: Iterable[str] = ()
) -> str | None:
    """The first existing file that a planned item would use and that the job did not create, or None.

    *owned_stems* are the names the job claimed in an earlier run (also in an earlier session of
    the app): everything planned under such a name is the job's to resume."""
    own = list(own)
    owned = set(owned_stems)
    for item in items:
        if stem_key(item) in owned:
            continue
        for path in _paths_in_use(item):
            if not is_own(path, own):
                return path
    return None


def _with_number(path: str, number: int) -> str:
    root, ext = os.path.splitext(path)
    return f"{root} ({number}){ext}"


def numbered(item: PlannedItem, number: int) -> PlannedItem:
    """The item under the next name, browser style: ``Title.mp4`` -> ``Title (1).mp4``."""
    return PlannedItem(_with_number(item.source, number), _with_number(item.final, number))


def numbered_command(command: Sequence[str], number: int) -> list[str]:
    """*command* with its output template changed to write ``... (<number>).<ext>``."""
    cmd = list(command)
    for i, arg in enumerate(cmd):
        if arg == "--":
            break
        if arg == "-o" and i + 1 < len(cmd):
            template = cmd[i + 1]
            suffix = ".%(ext)s"
            if template.endswith(suffix):
                cmd[i + 1] = template[: -len(suffix)] + f" ({number})" + suffix
            break
    return cmd


def _stem_in_use(item: PlannedItem) -> bool:
    """True when anything in the folder carries the item's name: the final file, a partial, a
    stream, a subtitle or any other sidecar (``Title (1).<anything>``)."""
    folder = os.path.dirname(item.final) or "."
    stem = os.path.basename(os.path.splitext(item.final)[0]).casefold()
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    return any(n.casefold() == stem or n.casefold().startswith(stem + ".") for n in names)


def choose_number(
    items: Sequence[PlannedItem], owned_stems: Iterable[str], claimed: Iterable[str],
    limit: int = 9999,
) -> int:
    """The first number whose names are free for every item: no file or sidecar of the new stem
    exists and no other running job holds it. A stem the job owns (an earlier run of the same
    download left its partial there) is taken as is, so the download resumes."""
    owned = set(owned_stems)
    held = set(claimed)
    for n in range(1, limit + 1):
        candidates = [numbered(i, n) for i in items]
        keys = [stem_key(c) for c in candidates]
        if any(k in held for k in keys):
            continue
        if all(k in owned for k in keys):
            return n
        if any(_stem_in_use(c) for c in candidates):
            continue
        return n
    raise DownloadRefused("No free file name was found in the download folder.")


_STREAM_SUFFIX = re.compile(r"\.f(?:\d|hls-|dash-|http-)[^.]*$")


def path_stem(path: str) -> str:
    """The name a file belongs to, as :func:`stem_key` writes it: ``Title.f137.mp4.part`` and
    ``Title.mp4`` are both ``Title``."""
    p = re.sub(r"\.(?:part-Frag\d+|part|ytdl)$", "", path)
    root = os.path.splitext(p)[0]
    root = re.sub(r"\.temp$", "", _STREAM_SUFFIX.sub("", root))
    return norm(root)


_PIECE_NAME = re.compile(r"\.(?:part(?:-Frag\d+)?|ytdl)$")


def has_partial(stem: str) -> bool:
    """True when an unfinished piece of the download written under *stem* (a :func:`stem_key`
    value) is in the folder: ``.part``, ``.ytdl``, ``.part-Frag3`` or one stream of a merge. The
    finished file does not count, and neither does a subtitle or another sidecar."""
    folder, _base = os.path.split(stem)
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return False
    for name in names:
        if path_stem(os.path.join(folder, name)) != stem:
            continue
        if _PIECE_NAME.search(name) or _STREAM_SUFFIX.search(os.path.splitext(name)[0]):
            return True
    return False
