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
