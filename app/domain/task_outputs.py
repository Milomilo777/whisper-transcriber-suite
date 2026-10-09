"""Find the files a finished transcription task really wrote.

``task.output_paths`` is the worker's own list of written files. A re-run
writes ``name (1).srt`` and an output template can move or rename the
outputs, so actions on a finished task (burn-in, export, viewer, "Open
folder") read that list; recomputing ``<source>.<ext>`` is only the
fallback for tasks without one (older history rows).
"""
from __future__ import annotations

import os
from typing import Any


def task_output_with_ext(task: Any, ext: str) -> str | None:
    """The first existing output of *task* ending in *ext* (e.g. ``".srt"``)."""
    for p in getattr(task, "output_paths", None) or ():
        if isinstance(p, str) and p.lower().endswith(ext) and os.path.isfile(p):
            return p
    return None


# Extra ``.json`` files the worker writes NEXT to the transcript. The
# auto-chapters ``<name>.chapters.json`` is listed in ``output_paths`` like
# any output, but it is a list of chapter dicts, not transcript segments.
_SIDECAR_JSON_SUFFIXES = (".chapters.json",)


def is_sidecar_json(path: str) -> bool:
    """True for a ``.json`` that is a sidecar of the transcript, not the transcript."""
    return os.path.basename(str(path)).lower().endswith(_SIDECAR_JSON_SUFFIXES)


def pick_transcript_json(
    paths: Any, source_path: str | None = None, *, must_exist: bool = False
) -> str | None:
    """The transcript ``.json`` among *paths*, never a sidecar; None if there is none.

    Prefers the exact ``<source stem>.json``; else the first non-sidecar
    ``.json`` (a re-run writes ``name (1).json``, a template renames it).
    With *must_exist* a path that is not a file on disk is skipped.
    """
    found = [
        p for p in (paths or ())
        if isinstance(p, str) and p.lower().endswith(".json")
        and (not must_exist or os.path.isfile(p))
    ]
    if source_path:
        want = os.path.splitext(os.path.basename(source_path))[0].lower() + ".json"
        for p in found:
            if os.path.basename(p).lower() == want:
                return p
    return next((p for p in found if not is_sidecar_json(p)), None)


def task_transcript_json(task: Any, *, must_exist: bool = False) -> str | None:
    """The transcript JSON this task wrote (see :func:`pick_transcript_json`)."""
    return pick_transcript_json(
        getattr(task, "output_paths", None),
        getattr(task, "file_path", None),
        must_exist=must_exist,
    )


def task_srt_output(task: Any) -> str | None:
    """The .srt this task really wrote, else ``<source>.srt``; None if neither exists."""
    found = task_output_with_ext(task, ".srt")
    if found is not None:
        return found
    guessed = os.path.splitext(task.file_path)[0] + ".srt"
    return guessed if os.path.isfile(guessed) else None


def task_output_folder(task: Any) -> str:
    """Folder of the task's first existing output, else the source's folder."""
    for p in getattr(task, "output_paths", None) or ():
        if isinstance(p, str) and os.path.isfile(p):
            return os.path.dirname(os.path.abspath(p))
    return os.path.dirname(task.file_path) or "."


def task_output_file(task: Any) -> str | None:
    """The task's first output file that exists, else None (a file Reveal in Finder can select)."""
    for p in getattr(task, "output_paths", None) or ():
        if isinstance(p, str) and os.path.isfile(p):
            return p
    return None
