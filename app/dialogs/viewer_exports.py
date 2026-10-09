"""Keep the exports next to a transcript JSON in step with it (no Tk in here).

The transcript viewer's Save rewrites the JSON first, then rebuilds every text and Word
export that still holds the transcript it was made from, with the writers the transcription
used. Building a Word file of a long transcript takes tens of seconds, so the viewer runs
:func:`scan_exports` (at open) and :func:`update_exports` (after each Save) in worker threads;
both only touch files and plain data, never a widget.

A file is rewritten only when it equals a rebuild of the transcript as it was last saved
(``scan_exports`` proves that), has not changed since, is not a link and does not change while
it is being rebuilt. Everything else is named in the :class:`ExportReport`, never skipped
quietly, and is left exactly as it is.
"""
from __future__ import annotations

import glob
import io
import json
import logging
import os
import re
import sys
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit
from urllib.request import url2pathname
from xml.sax.saxutils import unescape as xml_unescape

logger = logging.getLogger(__name__)

# Exports next to the JSON that Save keeps in step with it: (writer key, file
# suffix). Both "txt" and "express_scribe" write a plain ".txt" (the second also
# as "name.express_scribe.txt"), so a ".txt" is tried against each writer.
SIBLING_FILES: tuple[tuple[str, str], ...] = (
    ("srt", ".srt"), ("vtt", ".vtt"), ("ass", ".ass"),
    ("txt", ".txt"), ("express_scribe", ".txt"), ("express_scribe", ".express_scribe.txt"),
    ("md", ".md"), ("tsv", ".tsv"), ("lrc", ".lrc"), ("otr", ".otr"),
    ("elan", ".eaf"), ("inqscribe", ".inqscr"), ("docx", ".docx"),
)
# Writers whose output names the media file; the rest ignore audio_path.
WRITERS_USING_AUDIO_PATH = frozenset({"md", "lrc", "otr", "elan", "docx"})
# Exports that exist but cannot be checked against the transcript or rebuilt
# faithfully here (a PDF embeds fonts, dates and ids; the SMTV team document needs
# the language and work title): Save names them.
UNREBUILDABLE_SUFFIXES = (".pdf",)
# The one Word part that holds a save time: everything else must match to count as "ours".
_DOCX_VOLATILE_PART = "docProps/core.xml"
# The slow writer: rebuilt after the quick ones, so the subtitle files are ready first.
_SLOW_FORMATS = frozenset({"docx"})


_SWITCH_LOCK = threading.Lock()
_SWITCH_USERS = 0
_SWITCH_SAVED = 0.005
# How often Python lets another thread run while a worker builds an export. The default
# (5 ms) makes the Tk thread wait that long for EVERY Tk call it makes while a CPU-bound
# worker is running, which turned a 1.5 s list fill into 18 s; a Word build of 20,000
# segments is mostly Python code, so the interpreter must hand the lock over often.
_RESPONSIVE_INTERVAL = 0.0005


@contextmanager
def responsive_threads() -> Iterator[None]:
    """While a worker builds exports, keep the interpreter's thread switches frequent."""
    global _SWITCH_USERS, _SWITCH_SAVED
    with _SWITCH_LOCK:
        if _SWITCH_USERS == 0:
            _SWITCH_SAVED = sys.getswitchinterval()
            sys.setswitchinterval(min(_SWITCH_SAVED, _RESPONSIVE_INTERVAL))
        _SWITCH_USERS += 1
    try:
        yield
    finally:
        with _SWITCH_LOCK:
            _SWITCH_USERS -= 1
            if _SWITCH_USERS == 0:
                sys.setswitchinterval(_SWITCH_SAVED)


def file_stamp(path: str) -> tuple[int, int] | None:
    """``(mtime_ns, size)`` of ``path``, or None when it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def link_reason(path: str) -> str | None:
    """Why ``path`` must not be replaced (a symlink, or a file with other hard links)."""
    try:
        if os.path.islink(path):
            return "symbolic link"
        if os.lstat(path).st_nlink > 1:
            return "hard link"
    except OSError:
        return None
    return None


def read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fb:
            return fb.read()
    except OSError:
        return None


def render_bytes(fmt: str, segments: list[dict[str, Any]], audio_path: str) -> bytes:
    """The export ``fmt`` as the transcription's own writer produces it."""
    from core.writers import get_binary_writer, get_writer, is_binary

    if is_binary(fmt):
        return get_binary_writer(fmt)(segments, audio_path)
    return get_writer(fmt)(segments, audio_path).encode("utf-8")


def signature(fmt: str, raw: bytes) -> object | None:
    """What makes two copies of an export "the same transcript"; None when unreadable.

    Text: the content with a BOM dropped and CRLF read as LF. Word: every part of the zip
    except the core properties (they carry the save time, so the bytes differ on every
    build): a change to the styles, headers or anything else made elsewhere counts too.
    """
    try:
        if fmt == "docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                return {n: z.read(n) for n in z.namelist() if n != _DOCX_VOLATILE_PART}
        return raw.decode("utf-8-sig").replace("\r\n", "\n")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, OSError):
        return None


def title_in_export(fmt: str, raw: bytes) -> str | None:
    """The media name an export was headed with, when the media file is gone.

    Markdown and Word start with the media's file name, LRC carries its stem in
    ``[ti:...]``, OTR its name and ELAN its path; Save must keep that rather than
    reword it to "Transcript" or drop it.
    """
    try:
        if fmt == "md":
            first = raw.decode("utf-8-sig").split("\n", 1)[0].rstrip("\r")
            return first[2:] if first.startswith("# ") and len(first) > 2 else None
        if fmt == "docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                xml = z.read("word/document.xml").decode("utf-8")
            found = re.search(r"<w:t(?:\s[^>]*)?>([^<]+)</w:t>", xml)
            return xml_unescape(found.group(1)) if found else None
        if fmt == "lrc":
            first = raw.decode("utf-8-sig").split("\n", 1)[0].rstrip("\r")
            found = re.fullmatch(r"\[ti:(.+)\]", first)
            # The writer keeps the file name without its extension: give it one to drop.
            return f"{found.group(1)}.media" if found else None
        if fmt == "otr":
            media = json.loads(raw.decode("utf-8-sig")).get("media")
            return media if isinstance(media, str) and media else None
        if fmt == "elan":
            found = re.search(r'MEDIA_URL="([^"]+)"', raw.decode("utf-8"))
            if found is None:
                return None
            # The writer saved Path.resolve().as_uri(): undo the file:// URI.
            return url2pathname(urlsplit(xml_unescape(found.group(1))).path)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, AttributeError):
        return None
    return None


def audio_path_candidates(fmt: str, raw: bytes, media_path: str | None) -> list[str]:
    """The ``audio_path`` values to try when rebuilding ``fmt``, best guess first."""
    if fmt not in WRITERS_USING_AUDIO_PATH:
        return [""]
    # The file says what it was made with; rebuilding once with that is enough (a Word
    # build of a long transcript takes seconds). Without a readable title: the media file
    # next to the JSON, then none.
    title = title_in_export(fmt, raw)
    if title is not None:
        return [title]
    return [media_path, ""] if media_path else [""]


def sibling_files(json_path: str) -> list[tuple[str, list[str]]]:
    """Existing exports next to the JSON as (path, writer keys that can make it)."""
    base = os.path.splitext(json_path)[0]
    by_path: dict[str, list[str]] = {}
    for fmt, suffix in SIBLING_FILES:
        path = f"{base}{suffix}"
        if os.path.isfile(path):
            by_path.setdefault(path, []).append(fmt)
    return list(by_path.items())


def unrebuildable_files(json_path: str) -> list[str]:
    """Exports next to the JSON that Save cannot rebuild: PDF and the SMTV team document."""
    base = os.path.splitext(json_path)[0]
    found = [f"{base}{s}" for s in UNREBUILDABLE_SUFFIXES if os.path.isfile(f"{base}{s}")]
    # "<name> -Transcription in <language> – Translation in English.docx": it needs the
    # language and the work title, which the transcript JSON does not hold.
    found.extend(sorted(glob.glob(glob.escape(base) + " -Transcription in*.docx")))
    return found


def other_files(json_path: str) -> list[str]:
    """Files made FROM this transcript on request, which Save does not rebuild.

    The bilingual subtitles (the viewer's AI panel) and the auto-chapters sidecar hold
    translations and chapter titles, not the segments, so they stay as they are.
    """
    base = os.path.splitext(json_path)[0]
    found = sorted(glob.glob(glob.escape(base) + ".bilingual.*.srt"))
    chapters = f"{base}.chapters.json"
    if os.path.isfile(chapters):
        found.append(chapters)
    return found


def exports_exist(json_path: str) -> bool:
    return bool(sibling_files(json_path) or unrebuildable_files(json_path) or other_files(json_path))


class ChangedWhileBuilding(Exception):
    """The target changed (or became a link) between the check and the replace."""


def write_atomically(
    path: str, data: bytes, expect_stamp: tuple[int, int] | None = None
) -> None:
    """Write ``data`` to a temp sibling of ``path``, then move it into place.

    With ``expect_stamp`` the target is checked once more right before the move and left
    alone (``ChangedWhileBuilding``) when someone changed it while ``data`` was being built.
    """
    part = f"{path}.{os.getpid()}.part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        if expect_stamp is not None and (
            file_stamp(path) != expect_stamp or link_reason(path) is not None
        ):
            raise ChangedWhileBuilding(path)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            try:
                os.unlink(part)
            except OSError:
                pass


class _CannotCheck(Exception):
    """A writer failed while rebuilding a file to compare it."""


def _matching_audio_path(
    fmt: str, raw: bytes, segments: list[dict[str, Any]], media_path: str | None,
) -> str | None:
    """The ``audio_path`` with which writer ``fmt`` rebuilds ``raw`` exactly, else None."""
    wanted = signature(fmt, raw)
    if wanted is None:
        return None
    for audio_path in audio_path_candidates(fmt, raw, media_path):
        try:
            rendered = render_bytes(fmt, segments, audio_path)
        except Exception as e:  # noqa: BLE001 - a writer bug must not block the viewer
            logger.warning("Could not render %s: %s", fmt, e, exc_info=True)
            raise _CannotCheck(fmt) from e
        if signature(fmt, rendered) == wanted:
            return audio_path
    return None


@dataclass
class ScanResult:
    """Per export path: the stamp it matched with and how to rebuild it."""

    synced: dict[str, tuple[int, int] | None] = field(default_factory=dict)
    plan: dict[str, tuple[str, str]] = field(default_factory=dict)  # path -> (writer, audio_path)
    unchecked: set[str] = field(default_factory=set)  # unreadable, or its writer failed


def _is_slow(formats: list[str]) -> bool:
    return all(fmt in _SLOW_FORMATS for fmt in formats)


def scan_exports(
    json_path: str,
    segments: list[dict[str, Any]],
    media_path: str | None,
    result: ScanResult | None = None,
    slow: bool | None = None,
) -> ScanResult:
    """Which exports next to the JSON equal a rebuild of ``segments`` (the saved transcript).

    ``slow`` picks the files: False the quick ones, True the Word file(s), None all. Results
    are added to ``result`` when given, so a quick pass can be shown before the slow one.
    """
    result = ScanResult() if result is None else result
    for path, formats in sibling_files(json_path):
        if slow is not None and _is_slow(formats) != slow:
            continue
        stamp = file_stamp(path)
        raw = read_bytes(path)
        if stamp is None or raw is None:
            result.unchecked.add(path)
            continue
        errored = False
        for fmt in formats:
            try:
                audio_path = _matching_audio_path(fmt, raw, segments, media_path)
            except _CannotCheck:
                errored = True
                continue
            if audio_path is not None:
                result.synced[path] = stamp
                result.plan[path] = (fmt, audio_path)
                break
        else:
            if errored:
                result.unchecked.add(path)
    return result


@dataclass
class ExportReport:
    """What Save did to each export; every file next to the JSON is in exactly one list."""

    updated: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)  # does not match the last saved version
    unchecked: list[str] = field(default_factory=list)  # could not be read or compared
    linked: list[str] = field(default_factory=list)  # a symlink / hard link: not replaced
    raced: list[str] = field(default_factory=list)  # changed while being rebuilt
    failed: list[str] = field(default_factory=list)  # the writer or the disk failed
    unrebuildable: list[str] = field(default_factory=list)  # PDF, SMTV document
    other: list[str] = field(default_factory=list)  # bilingual subtitles, chapters

    def old_text_files(self) -> list[str]:
        """Every export that still holds the old text."""
        return (self.stale + self.unchecked + self.linked + self.raced + self.failed
                + self.unrebuildable)


def update_exports(
    json_path: str,
    segments: list[dict[str, Any]],
    scan: ScanResult,
    fast_done: Callable[[], None] | None = None,
    wait_slow_scan: Callable[[], None] | None = None,
) -> ExportReport:
    """Rebuild the matching exports from ``segments`` (the transcript just saved).

    The quick formats go first; ``fast_done`` is called when only the slow Word file is left,
    and ``wait_slow_scan`` (if given) is called before that file is judged, because its check
    against the opened transcript may still be running. ``scan.synced`` gets the new stamp of
    each file written, so the next Save matches it.
    """
    report = ExportReport()
    files = sibling_files(json_path)
    for slow in (False, True):
        if slow and wait_slow_scan is not None:
            if fast_done is not None:
                fast_done()
                fast_done = None
            wait_slow_scan()
        for path, formats in files:
            if _is_slow(formats) == slow:
                _update_one(path, scan, segments, report)
    if fast_done is not None:
        fast_done()
    report.unrebuildable = unrebuildable_files(json_path)
    report.other = other_files(json_path)
    return report


def _update_one(
    path: str, scan: ScanResult, segments: list[dict[str, Any]], report: ExportReport,
) -> None:
    stamp = file_stamp(path)
    if stamp is None:
        return  # gone since the scan: nothing to update
    plan = scan.plan.get(path)
    if plan is None:
        (report.unchecked if path in scan.unchecked else report.stale).append(path)
        return
    if scan.synced.get(path) != stamp:
        report.stale.append(path)
        return
    if link_reason(path) is not None:
        report.linked.append(path)
        return
    fmt, audio_path = plan
    try:
        write_atomically(path, render_bytes(fmt, segments, audio_path), expect_stamp=stamp)
    except ChangedWhileBuilding:
        report.raced.append(path)
        return
    except Exception:  # noqa: BLE001 - one broken writer must not stop the others
        logger.warning("Could not update %s", path, exc_info=True)
        report.failed.append(path)
        return
    scan.synced[path] = file_stamp(path)
    report.updated.append(path)


def segments_from_json(text: str) -> list[dict[str, Any]]:
    """The segment dicts of a transcript JSON text, as the viewer loads them."""
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("a transcript JSON is a list of segments")
    return [item for item in payload if isinstance(item, dict)]


def _names(paths: list[str]) -> str:
    return ", ".join(os.path.basename(p) for p in paths)


def report_notices(report: ExportReport, json_path: str) -> list[tuple[str, str]]:
    """The notices Save shows after the exports were handled: (text, kind)."""
    out: list[tuple[str, str]] = []
    if report.updated:
        out.append((f"Updated {_names(report.updated)} next to {os.path.basename(json_path)}.",
                    "success"))
    warn: list[str] = []
    if report.failed:
        warn.append(f"Could not update {_names(report.failed)}; it still holds the OLD text "
                    "(the details are in app.log).")
    if report.raced:
        warn.append(f"Not updated: {_names(report.raced)} changed while Save was rebuilding "
                    "it, so it was left as it is and still holds the old text; save again to retry.")
    if report.linked:
        warn.append(f"Not updated: {_names(report.linked)} is a link to another file, which "
                    "Save never replaces; it still holds the old text.")
    if report.unchecked:
        warn.append(f"Not updated: {_names(report.unchecked)} could not be read or checked "
                    "when the transcript was opened, so it still holds the old text.")
    if report.stale:
        warn.append(f"Not updated: {_names(report.stale)} does not match this transcript's "
                    "last saved version (it was changed elsewhere or comes from another run), "
                    "so it was left as it is and still holds the old text.")
    if report.unrebuildable:
        warn.append(f"Cannot rebuild {_names(report.unrebuildable)} here (PDF and the team "
                    "document); it still holds the old text. Export it again if you need it.")
    if warn:
        out.append((" ".join(warn), "warning"))
    if report.other:
        out.append((f"Not rebuilt by Save: {_names(report.other)} (made from the transcript "
                    "on request; make it again to match the new text).", "info"))
    return out
