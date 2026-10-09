"""TranscriptViewer — modal Toplevel that shows a saved JSON transcript.

  - Left side: scrollable segment list. Each row carries the
    timestamp, optional speaker label, and the segment text.
  - Right side: a media player (when python-vlc + libvlc are
    available on the system), or a fallback "Open in system
    player" button when VLC isn't installed.
  - Single-click on a segment → seek the media to that segment's
    start time (when VLC is up).
  - Search box at the top filters the segment list.
  - Ctrl+F opens the Find-and-replace dialog operating on segment
    text in memory; "Save Changes" writes back via the JSON writer.
  - Right-click on a speaker cell → "Rename speaker..." rewrites
    every segment with the same speaker label.
  - Right-click on a segment → "Edit timestamp..." hand-edits that
    segment's start/end time (HH:MM:SS.mmm). Only that one segment
    changes — nothing downstream re-flows. A segment that now overlaps
    the previous one, or is under 1s long, gets a light-orange row
    background as a warning (purely visual; never blocks saving).
  - Word-confidence colour coding when a segment carries ``words``
    with probabilities.
  - Filler-word remove tool (one-click button) strips ``uh``, ``um``,
    ``er``, … from every segment text.
  - Karaoke-style word highlight follows the VLC playhead through
    the active segment's ``words`` list.

The viewer reads the ``.json`` output that core/writers/json_writer
produces. The matching media file is found next to the JSON by
checking the configured ``output_formats`` of the run — falls back
to any common audio/video extension that lives next to the JSON.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Collection, Optional

from app.dialogs import share_page, viewer_exports
from app import mac_native, shortcuts
from app.dpi import px, scaled_size
from app.theme import script_fonts, tokens
from app.widgets.error_dialog import show_error
from app.widgets import subtitle_edit as subtitle_edit_ui
from app.widgets.notice import Kind, notify
from app.widgets.platform import is_darwin, open_folder, reveal_label
from app.widgets.tooltip import help_icon
from core import subtitle_edit
from core.media_types import MEDIA_EXTENSIONS
from core.search import find_folded_span, folded_contains, replace_folded
from core.writers.base import words_match_text


logger = logging.getLogger(__name__)


_MEDIA_EXTENSIONS = MEDIA_EXTENSIONS

# " (1)" that a re-run adds to every output name (core.transcriber._indexed_path).
_RERUN_INDEX_RE = re.compile(r" \(\d+\)$")

# Words the one-click cleanup removes, per transcript language. A filler in
# one language is a real word in another (English "er" is German "he",
# Dutch "there", Danish "is"), so a language without a list gets no
# cleanup at all. Conservative: no "like" / "you know", which often carry
# meaning, and no "mhm" / "mm-hmm", which mean "yes".
_FILLERS_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    "en": ("uh", "um", "uhm", "umm", "er", "erm", "eh", "ah", "mm", "mmm", "hm", "hmm"),
    "de": ("äh", "ähm", "öh", "öhm", "hm", "hmm"),
    "nl": ("eh", "ehm", "uh", "uhm", "hm", "hmm"),
    "fr": ("euh", "heu", "hum", "hm", "hmm"),
    "es": ("eh", "ehm", "em", "mmm", "hmm"),
    "it": ("eh", "ehm", "uhm", "mmm", "hmm"),
    "pt": ("hum", "hmm", "ahn", "hã"),
    "sv": ("eh", "öh", "öhm", "hmm"),
    "da": ("øh", "øhm", "æh", "hmm"),
    "no": ("eh", "øh", "øhm", "hmm"),
    "pl": ("yyy", "eee", "hmm"),
}
_FILLERS_BY_LANGUAGE["nb"] = _FILLERS_BY_LANGUAGE["nn"] = _FILLERS_BY_LANGUAGE["no"]
_FILLER_WORDS = _FILLERS_BY_LANGUAGE["en"]

# Language names some callers carry instead of the ISO code.
_LANGUAGE_NAMES = {
    "english": "en", "german": "de", "dutch": "nl", "french": "fr", "spanish": "es",
    "italian": "it", "portuguese": "pt", "swedish": "sv", "danish": "da",
    "norwegian": "no", "polish": "pl",
}


def _language_code(language: str | None) -> str:
    """``"en"`` from ``"en"``, ``"en-US"``, ``"en_GB"`` or ``"English"``; "" when unknown."""
    if not isinstance(language, str):
        return ""
    value = language.strip().lower().replace("_", "-")
    if not value or value == "auto":
        return ""
    return _LANGUAGE_NAMES.get(value, value.split("-")[0])


def _filler_words_for(language: str | None) -> tuple[str, ...]:
    """The filler list for ``language``; empty when unknown or not covered."""
    return _FILLERS_BY_LANGUAGE.get(_language_code(language), ())


def _seg_text(seg: dict[str, Any], key: str = "text") -> str:
    """``seg[key]`` as a string for display and editing.

    Transcript JSON can be hand-edited: a number there becomes its digits, and
    anything else that is not a string (a list, a dict, ``null``) reads as "".
    """
    value = seg.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _seg_words(seg: dict[str, Any]) -> list[Any]:
    """``seg["words"]`` when it is a list, else an empty list."""
    words = seg.get("words")
    return words if isinstance(words, list) else []


# One viewer per transcript file, keyed by _viewer_key(json_path): two
# viewers on one JSON would each save their own copy, the last one winning.
_OPEN_VIEWERS: dict[str, "TranscriptViewer"] = {}
# Viewers whose export rebuild is (or was) running, kept even after the window is closed:
# the app's exit waits for them (finish_exports_before_exit).
_EXPORTING: list["TranscriptViewer"] = []


def _viewer_key(json_path: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(json_path))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(json_path))


_file_stamp = viewer_exports.file_stamp


def _render_sibling(fmt: str, segments: list[dict[str, Any]]) -> str:
    from core.writers import get_writer

    return get_writer(fmt)(segments, "")


def _write_text_atomically(path: str, text: str) -> None:
    """Write ``text`` to a temp sibling of ``path``, then move it into place."""
    viewer_exports.write_atomically(path, text.encode("utf-8"))


def _find_media_next_to(json_path: str) -> str | None:
    """Find a media file that pairs with the JSON next to it.

    Tries ``<json stem>.<ext>`` first, then the stem without a re-run's
    `` (N)`` index and a translate run's ``.en-translated`` suffix, so
    ``talk (1).json`` and ``talk.en-translated.json`` still find
    ``talk.mp4``. Extensions match case-insensitively (``clip.MP4``).
    Callers that know the real source pass it to the viewer instead.
    """
    from core.translate_task import TRANSLATED_SUFFIX

    folder = os.path.dirname(json_path) or "."
    stem = os.path.splitext(os.path.basename(json_path))[0]
    stems = [stem]
    stripped = _RERUN_INDEX_RE.sub("", stem)
    if stripped.endswith(TRANSLATED_SUFFIX):
        stripped = _RERUN_INDEX_RE.sub("", stripped[: -len(TRANSLATED_SUFFIX)])
    if stripped and stripped != stem:
        stems.append(stripped)
    try:
        names = {n.casefold(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for candidate_stem in stems:
        for ext in _MEDIA_EXTENSIONS:
            real = names.get((candidate_stem + ext).casefold())
            if real is not None and os.path.isfile(os.path.join(folder, real)):
                return os.path.join(folder, real)
    return None


def _fmt_hms(seconds: float) -> str:
    """``HH:MM:SS`` short-form."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# Resolution of the transport-bar seek slider. The slider runs 0..N and
# we map that to libvlc's 0.0..1.0 fractional position. A higher number
# = finer scrubbing granularity.
_SEEK_SLIDER_MAX = 1000


def _fmt_mmss(ms: float) -> str:
    """``MM:SS`` (or ``H:MM:SS`` past an hour) from a millisecond count.

    Used by the transport-bar time readout. libvlc returns ``-1`` for an
    unknown time/length (no media loaded yet, or a stream with no
    duration), so anything <= 0 collapses to ``00:00`` rather than a
    bogus negative clock.
    """
    total_s = int(ms // 1000) if ms and ms > 0 else 0
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _slider_to_fraction(value: float) -> float:
    """Map a transport-slider value (0.._SEEK_SLIDER_MAX) → 0.0..1.0.

    Clamped so a stray out-of-range value from the Tk scale can never
    drive libvlc ``set_position`` outside its valid domain.
    """
    frac = value / float(_SEEK_SLIDER_MAX)
    if frac < 0.0:
        return 0.0
    if frac > 1.0:
        return 1.0
    return frac


def _fraction_to_slider(fraction: float) -> float:
    """Map a libvlc position (0.0..1.0) → transport-slider value.

    Inverse of :func:`_slider_to_fraction`; clamped to the slider's
    range so a transient out-of-bounds ``get_position`` (libvlc returns
    values slightly past 1.0 near end-of-media) can't overshoot the
    widget.
    """
    if fraction < 0.0:
        fraction = 0.0
    elif fraction > 1.0:
        fraction = 1.0
    return fraction * _SEEK_SLIDER_MAX


def _clamp_time_ms(current_ms: float, delta_ms: float, total_ms: float) -> int:
    """Skip-button arithmetic: ``current + delta`` clamped to the media.

    Never returns < 0. When ``total_ms`` is known (> 0) the result is
    also capped just below the end (``total - 1``) so a forward skip
    past the end doesn't drive libvlc to a position it rejects; when the
    length is unknown (libvlc ``-1``/``0``) only the lower bound applies.
    """
    target = int(current_ms) + int(delta_ms)
    if target < 0:
        target = 0
    if total_ms and total_ms > 0 and target > total_ms - 1:
        target = int(total_ms) - 1
        if target < 0:
            target = 0
    return target


def _filler_regex(words: tuple[str, ...] = _FILLER_WORDS) -> re.Pattern[str]:
    """One regex for every filler in ``words`` plus the spaces before it.

    Whole words only, case-insensitive: a hyphen or apostrophe counts as
    part of the word, so "Mm-hmm" and "uh-huh" stay whole, and so does a
    dot or "@" inside a name ("user@um.com", "um.mp3"). Punctuation after
    the filler is NOT matched: "Hello um, world" keeps its comma
    ("Hello, world"); ``_strip_fillers`` tidies doubled punctuation.
    """
    alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(
        rf"(?i)\s*(?<![\w'’@./\\-])(?:{alternatives})(?![\w'’@/\\-]|\.\w)"
    )


def _seg_float(seg: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Read ``seg[key]`` as a float, coercing defensively to ``default``.

    Transcript JSON is user-supplied (or hand-edited), so a segment's
    ``start`` / ``end`` may carry a non-numeric value — a European
    decimal string like ``"1,5"``, a stray ``"abc"``, or ``None``. A
    bare ``float(seg.get(...))`` on those raises ``ValueError`` /
    ``TypeError`` and crashes the viewer at construction, bypassing the
    friendly "pick the .json" guard in :meth:`_load_segments`. Coercing
    to ``default`` (0.0) keeps the row visible with a sane timestamp
    instead of taking down the whole window.

    ``NaN`` / ``Infinity`` are also rejected: ``float("nan")`` and
    ``float("inf")`` parse cleanly, so they used to pass straight
    through and then blow up one step later in :func:`_fmt_hms`
    (``int(nan)`` → ``ValueError``, ``int(inf)`` → ``OverflowError``)
    — the exact construction crash this helper exists to prevent.
    Python's ``json`` parses the bare ``NaN`` / ``Infinity`` literals
    some tools emit, so this is real input, not just a hand-edit.
    """
    try:
        value = float(seg.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def _fmt_hms_ms(seconds: float) -> str:
    """``HH:MM:SS.mmm`` — millisecond-precision timestamp for the
    "Edit timestamp" dialog. Separate from :func:`_fmt_hms` (which the
    segment-list Time column uses) because the list only needs
    whole-second granularity, but hand-editing a segment's start/end
    needs sub-second precision to be useful."""
    seconds = max(0.0, float(seconds))
    total_ms = round(seconds * 1000)
    h, rem_ms = divmod(total_ms, 3_600_000)
    m, rem_ms = divmod(rem_ms, 60_000)
    s, ms = divmod(rem_ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _parse_hms_ms(text: str) -> float | None:
    """Parse ``HH:MM:SS.mmm``, ``MM:SS.mmm``, or bare seconds into a
    float second count. Returns ``None`` on anything unparseable (a
    typo, empty field, negative or non-finite value) so the caller can
    show a friendly inline error instead of crashing on a hand-typed
    value. ``float("inf")`` / ``float("1e400")`` parse successfully but
    are rejected here — stored as a segment timestamp they would later
    crash :func:`_fmt_hms` (``int(inf)`` → ``OverflowError``)."""
    text = (text or "").strip()
    if not text:
        return None
    if ":" not in text:
        try:
            value = float(text)
        except ValueError:
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return value
    raw_parts = text.split(":")
    if len(raw_parts) not in (2, 3):
        return None
    try:
        parts = [float(p) for p in raw_parts]
    except ValueError:
        return None
    if any(p < 0 for p in parts):
        return None
    if len(parts) == 2:
        h = 0.0
        m, s = parts
    else:
        h, m, s = parts
    total = h * 3600 + m * 60 + s
    if not math.isfinite(total):
        return None
    return total


def _segment_has_timing_issue(segments: list[dict[str, Any]], idx: int) -> bool:
    """True when segment ``idx`` overlaps the previous segment's end,
    or its own duration is under 1 second.

    Purely a visual cue (light-orange row background) so a manual
    timestamp edit that produces something odd is easy to spot — it
    never blocks saving. Mirrors the same two conditions the reference
    app (faster-whisper-GUI) flags after an in-place timestamp edit.
    """
    if idx < 0 or idx >= len(segments):
        return False
    seg = segments[idx]
    start = _seg_float(seg, "start")
    end = _seg_float(seg, "end", start)
    if end - start < 1.0:
        return True
    if idx > 0:
        prev = segments[idx - 1]
        prev_end = _seg_float(prev, "end", _seg_float(prev, "start"))
        if start < prev_end:
            return True
    return False


def _segment_min_probability(seg: dict[str, Any]) -> float | None:
    """Min word-confidence in a segment, or None when not available.

    A segment's ``words`` is normally a list of dicts, but a hand-edited
    / unrelated JSON may carry a list of NON-dict elements (e.g.
    ``words: [1, 2]`` or ``["a"]``). Calling ``.get(...)`` on a non-dict
    raises ``AttributeError`` — which the ``(TypeError, ValueError)``
    handler does NOT catch — crashing the viewer at construction and
    bypassing the friendly "pick the .json" guard in
    :meth:`_load_segments`. Skip non-dict entries defensively, mirroring
    the :func:`_seg_float` coercion style.
    """
    words = _seg_words(seg)
    probs: list[float] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        try:
            probs.append(float(w.get("probability", 0.0)))
        except (TypeError, ValueError):
            continue
    if not probs:
        return None
    return min(probs)


def _os_open(path: str) -> None:
    """Open a file or folder with the OS default handler (cross-platform)."""
    if sys.platform == "darwin":
        subprocess.run(["open", path], stdin=subprocess.DEVNULL, check=False)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path], stdin=subprocess.DEVNULL, check=False)


def _dir_has_vlc_lib(d: str) -> bool:
    """True if dir ``d`` contains the platform's libvlc shared library."""
    if not d or not os.path.isdir(d):
        return False
    if os.name == "nt":
        return os.path.isfile(os.path.join(d, "libvlc.dll"))
    try:
        for entry in os.listdir(d):
            # libvlc.dylib (mac) / libvlc.so, libvlc.so.5 (linux)
            if entry.startswith("libvlc.") and (".so" in entry or entry.endswith(".dylib")):
                return True
    except OSError:
        return False
    return False


def _locate_vlc_dir() -> str | None:
    """Best-effort path to the dir holding the libvlc shared library.

    python-vlc ctypes-loads libvlc at *import* time; if VLC is installed in
    a standard location that the loader doesn't search, the import fails
    even though VLC is present (the user's "VLC says not installed"
    report). Returning its dir lets _try_load_vlc point python-vlc at it.
    Covers Windows (registry + Program Files), macOS (VLC.app), and Linux
    (the usual library dirs).
    """
    candidates: list[str] = []
    if os.name == "nt":
        try:
            import winreg  # type: ignore[import-not-found]

            for flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VideoLAN\VLC",
                        0, winreg.KEY_READ | flag,
                    ) as key:
                        install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                        if install_dir:
                            candidates.append(str(install_dir))
                except OSError:
                    pass
        except ImportError:
            pass
        for env_var in ("PROGRAMW6432", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env_var)
            if base:
                candidates.append(os.path.join(base, "VideoLAN", "VLC"))
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/VLC.app/Contents/MacOS/lib",
            os.path.expanduser("~/Applications/VLC.app/Contents/MacOS/lib"),
        ]
    else:  # linux / other unix — usual shared-library dirs
        candidates += [
            "/usr/lib", "/usr/lib64", "/usr/local/lib",
            "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu",
            "/snap/vlc/current/usr/lib",
        ]
    for d in candidates:
        if _dir_has_vlc_lib(d):
            return d
    return None


def _vlc_lib_file(d: str) -> str | None:
    """Absolute path to the libvlc shared library inside dir ``d``."""
    if os.name == "nt":
        p = os.path.join(d, "libvlc.dll")
        return p if os.path.isfile(p) else None
    try:
        for entry in sorted(os.listdir(d)):
            if entry.startswith("libvlc.") and (".so" in entry or entry.endswith(".dylib")):
                return os.path.join(d, entry)
    except OSError:
        return None
    return None


def _vlc_plugins_dir(d: str) -> str | None:
    """Best-effort VLC plugins dir. Layouts: <vlc>/plugins (Windows),
    <...>/MacOS/plugins (sibling of the lib dir on macOS), and
    <libdir>/vlc/plugins (Linux)."""
    for cand in (
        os.path.join(d, "plugins"),
        os.path.join(os.path.dirname(d), "plugins"),
        os.path.join(d, "vlc", "plugins"),
    ):
        if os.path.isdir(cand):
            return cand
    return None


def _vlc_missing_hint(platform: str) -> str:
    """User-facing text for "libvlc could not be loaded".

    Only Windows has the 32-bit/64-bit VLC mix-up (the app is 64-bit there);
    macOS and Linux get platform-neutral wording.
    """
    if platform == "win32":
        return (
            "VLC media player isn't installed (or is the 32-bit build — "
            "this app is 64-bit and needs the 64-bit VLC). Install the "
            "64-bit VLC to enable embedded playback. The viewer still "
            "works in read-only mode."
        )
    return (
        "VLC media player isn't installed (or doesn't match this "
        "computer's architecture). Install VLC to enable embedded "
        "playback. The viewer still works in read-only mode."
    )


def _vlc_start_failed_hint(platform: str) -> str:
    """User-facing text for "libvlc loaded but vlc.Instance() failed"."""
    if platform == "win32":
        return (
            "VLC loaded but could not start (its plugins may be missing or "
            "the architecture doesn't match — this app is 64-bit). "
            "Reinstall the 64-bit VLC to enable embedded playback. The "
            "viewer still works in read-only mode."
        )
    return (
        "VLC loaded but could not start (its plugins may be missing or "
        "the architecture doesn't match). Reinstall VLC to enable "
        "embedded playback. The viewer still works in read-only mode."
    )


def _try_load_vlc() -> tuple[Any, str]:
    """Return ``(vlc_module_or_None, error_message)``.

    Two ways for VLC to be unavailable: the python-vlc Python
    binding isn't installed, or it is but libvlc.dll can't be
    found on the system. python-vlc raises FileNotFoundError (a
    subclass of OSError) at import time when libvlc.dll is
    missing on Windows — catch both.
    """
    # Point python-vlc at a standard VLC install before importing, so an
    # installed-but-not-on-PATH VLC is still found.
    vlc_dir = _locate_vlc_dir()
    if vlc_dir:
        lib_file = _vlc_lib_file(vlc_dir)
        if lib_file:
            os.environ.setdefault("PYTHON_VLC_LIB_PATH", lib_file)
        plugins = _vlc_plugins_dir(vlc_dir)
        if plugins:
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", plugins)
        if os.name == "nt":
            try:
                os.add_dll_directory(vlc_dir)  # type: ignore[attr-defined]
            except (OSError, AttributeError):
                pass
    try:
        import vlc  # type: ignore[import-not-found]
    except ImportError as e:
        return None, f"python-vlc binding not installed: {e}"
    except OSError:
        # libvlc.dll not loadable — either VLC isn't installed, or it's the
        # wrong architecture (this app is 64-bit, so it needs 64-bit VLC).
        return None, _vlc_missing_hint(sys.platform)
    try:
        inst = vlc.Instance()
        if inst is None:
            raise RuntimeError("vlc.Instance() returned None")
        # Release the probe instance immediately. Leaking it (and then
        # creating a SECOND instance in _init_vlc_player) keeps two native
        # libvlc instances alive at once, which worsens the native
        # instability around the HWND bind on Windows.
        try:
            inst.release()
        except Exception:  # noqa: BLE001
            pass
        return vlc, ""
    except Exception:  # noqa: BLE001
        return None, _vlc_start_failed_hint(sys.platform)


def _set_segment_text(seg: dict[str, Any], text: str) -> None:
    """Replace a segment's text and drop a word list it no longer matches.

    The per-word list (karaoke timing, confidence colours) describes the
    words as transcribed. After an edit it would spell the old wording, and
    word-level exports would bring the corrected-away words back, so it is
    removed unless it still spells the new text.
    """
    seg["text"] = text
    if "words" in seg and not words_match_text(seg):
        del seg["words"]


def _strip_fillers(text: str, pattern: re.Pattern[str]) -> str:
    """Return ``text`` with filler words removed and the punctuation around
    them tidied: "Hello, um, world" -> "Hello, world", "Hello um. Bye" ->
    "Hello. Bye", "Um, so" -> "so". Text without a filler comes back
    unchanged apart from surrounding whitespace."""
    cleaned = pattern.sub("", text)
    if cleaned == text:
        return text.strip()
    # Brackets or quotes that held only the filler: "(um)", '"um,"'.
    cleaned = re.sub(r"\(\s*[,;:]?\s*\)|\[\s*[,;:]?\s*\]", "", cleaned)
    cleaned = re.sub(r"(^|\s)[\"“]\s*[,;:]?\s*[\"”](?=[\s,.!?]|$)", r"\1", cleaned)
    # A comma left next to another mark: "Hello,, world", "Hello,.", "Bye., so"
    cleaned = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", cleaned)
    cleaned = re.sub(r"[,;:]\s*([.!?…])", r"\1", cleaned)
    cleaned = re.sub(r"([.!?…])\s*[,;:]", r"\1", cleaned)
    # A dash pair that framed the filler: "so - um - then" -> "so - then".
    cleaned = re.sub(r"([-–—])(?:\s+[-–—])+(?=\s)", r"\1", cleaned)
    # A quote or bracket that opened on the filler: '"Um, hello"' -> '"hello"'.
    cleaned = re.sub(r"(^|\s)([\"“«(\[])\s*[,;:]\s*", r"\1\2", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # A sentence that started with the filler: "Um, so" -> ", so" -> "so".
    cleaned = re.sub(r"^[,;:.!?\s]+", "", cleaned)
    return cleaned


class TranscriptViewer(tk.Toplevel):
    """Modal viewer for a saved transcript JSON.

    Build it via :func:`open_viewer` from anywhere in the app.
    """

    # The transcript's language, when known (set in __init__; the class default keeps
    # partly built viewers working, as some tests make them).
    language: str | None = None
    # Transient like a dialog, but usable beside the main window: the macOS file
    # queue and the About/Settings items do not treat it as a modal (app/mac_native.py).
    _non_modal = True
    # (mtime_ns, size) of the JSON when it was loaded or last saved here.
    _disk_stamp: tuple[int, int] | None = None
    _registry_key: str | None = None
    # Defaults for a viewer built without __init__ (tests drive _load_segments that way).
    media_path: str | None = None
    _scan_generation: int = 0

    @property
    def _dirty(self) -> bool:
        """True while the list holds edits that are not saved to the JSON."""
        return bool(self.__dict__.get("_dirty_flag", False))

    @_dirty.setter
    def _dirty(self, value: bool) -> None:
        self.__dict__["_dirty_flag"] = bool(value)
        # macOS: the dot in the close button; a no-op on Windows and Linux.
        mac_native.set_modified(self, bool(value))

    def __init__(
        self,
        master: "tk.Tk | tk.Toplevel",
        json_path: str,
        media_path: str | None = None,
        initial_seek_seconds: float | None = None,
        language: str | None = None,
    ) -> None:
        super().__init__(master)
        self.title(f"Transcript — {os.path.basename(json_path)}")
        width, height = scaled_size(self, 1180, 720)
        self.geometry(f"{width}x{height}")
        # No resizable()/minsize() existed before — Tk's default is
        # resizable in both directions, so nothing stopped a user from
        # shrinking below the width the toolbar (media label + search +
        # Find&Replace + Remove fillers + Save + Open JSON folder, now
        # plus 2 hover icons) actually needs. Floor it at the window's
        # own launch size, which was already fixed regardless of screen
        # size, so this doesn't change anything about small-screen fit.
        self.minsize(width, height)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.json_path = json_path
        # macOS: the transcript file as the window's proxy icon in the title bar.
        mac_native.set_title_path(self, json_path)
        # Export next to the JSON -> its stamp, for the ones that still
        # match the JSON (see _scan_siblings); Save rewrites only those.
        self._synced_siblings: dict[str, tuple[int, int] | None] = {}
        # The same files -> (writer key, audio_path) that rebuilds each one exactly.
        self._sibling_plan: dict[str, tuple[str, str]] = {}
        # Exports that could not be read or rebuilt for the comparison.
        self._sibling_unchecked: set[str] = set()
        # The scan and the rebuilds run in worker threads (a Word build of a long
        # transcript takes tens of seconds); the events and the lock are how they hand
        # over. Nothing in a worker touches a widget.
        self._scan_fast_done = threading.Event()  # the quick exports are checked
        self._scan_fast_done.set()
        self._scan_done = threading.Event()  # ... and the Word file too
        self._scan_done.set()
        self._scan_generation = 0
        self._scan_start: Any = None  # starts the scan thread; None once started
        self._export_lock = threading.Lock()
        self._export_pending: str | None = None  # the JSON text of the newest Save
        self._export_running = False
        self._export_idle = threading.Event()
        self._export_idle.set()
        self._export_fast_done = threading.Event()
        self._export_fast_done.set()
        self._export_reports: list[viewer_exports.ExportReport] = []
        self._export_remaining: set[str] = set()  # files of the running job not yet dealt with
        self._export_poll_id: str | None = None
        self.media_path = media_path or _find_media_next_to(json_path)
        # The transcript's language when the opener knows it (a queue task); the JSON itself has
        # none. Picks the regional font for Han text without kana (app.theme.script_fonts);
        # None (file picker, search results) leaves Han to Tk's default fallback font.
        self.language = language or None

        self.segments: list[dict[str, Any]] = []
        self.filtered_indices: list[int] = []
        self._dirty = False
        self._active_segment_idx: int | None = None
        self._active_word_idx: int | None = None
        # Set on _on_close so any pending after() tick or watcher
        # callback short-circuits before touching destroyed widgets.
        self._closing = False
        # Track find/replace dialog so we can destroy it before the
        # parent viewer closes (otherwise it becomes a zombie that
        # crashes on the next button click).
        self._find_dialog: "FindReplaceDialog | None" = None

        self.vlc_mod, self.vlc_unavailable_reason = _try_load_vlc()
        self.vlc_instance: Any = None
        self.vlc_player: Any = None
        self.vlc_seek_after: str | None = None
        # True while the user is dragging the transport seek slider. The
        # position loop checks this and skips updating the slider so its
        # thumb doesn't snap back to the playhead mid-drag (see
        # _update_position / _on_seek_*).
        self._seeking = False

        # AI panel state (see _build_ai_panel). The runner is built lazily
        # on first use and cached for the rest of this viewer's lifetime —
        # a local LLMRunner pays a multi-second model-load cost, so
        # rebuilding it per click would make Summarise-then-Ask-then-
        # Translate needlessly slow.
        self._llm_runner: Any = None
        self._llm_runner_cache_key: tuple[Any, ...] | None = None
        self._ai_busy = False
        self._bilingual_cancel: threading.Event | None = None

        self._build_widgets()
        self._load_segments()
        self._populate_listbox()
        self._load_chapters()
        if self.vlc_mod is not None and self.media_path:
            self._init_vlc_player()
        if initial_seek_seconds is not None:
            self._seek_to(initial_seek_seconds)
            self._select_segment_near(initial_seek_seconds)

        # Find-and-replace shortcut.
        shortcuts.bind_shortcut(self, "f", self._open_find_replace)
        shortcuts.bind_shortcut(self, "s", self._save_changes)

        # Transport keyboard niceties — bound to THIS Toplevel only (not
        # bind_all) so they don't leak into the main app window. Left /
        # Right scrub ∓5s; Space toggles play/pause. All call guarded
        # player methods, so they're harmless when there's no embedded
        # player.
        self.bind("<Left>", self._on_key_skip_back)
        self.bind("<Right>", self._on_key_skip_fwd)
        self.bind("<space>", self._on_key_toggle_play)

        # Registered last: a window that failed half-way is never the one
        # open_viewer brings forward.
        self._registry_key = _viewer_key(json_path)
        _OPEN_VIEWERS[self._registry_key] = self

    # -- widgets ---------------------------------------------------------

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        # Two bars, so every button keeps its full label at 100-150 % scaling (one bar cut
        # "Open in Subtitle Edit" to "Oper" at 100 %). Top: the media file and the file
        # actions; the right-hand buttons are packed first, so a long file name is what gives
        # way. Second: search and the edit tools.
        topbar = ttk.Frame(outer)
        topbar.pack(fill="x", pady=(0, 4))
        ttk.Button(
            topbar, text=reveal_label("Open JSON folder"), command=self._open_json_folder,
        ).pack(
            side="right"
        )
        ttk.Button(topbar, text=share_page.BUTTON_TEXT, command=self._save_shareable_page).pack(
            side="right", padx=(0, 4)
        )
        if subtitle_edit.is_supported():
            ttk.Button(
                topbar, text=subtitle_edit_ui.BUTTON_TEXT,
                command=self._open_in_subtitle_edit,
            ).pack(side="right", padx=(0, 4))
            help_icon(topbar, subtitle_edit_ui.HELP_TEXT).pack(side="right", padx=(0, 4))
        media_label = (
            f"Media: {os.path.basename(self.media_path)}"
            if self.media_path
            else "Media: (none found next to JSON)"
        )
        ttk.Label(topbar, text=media_label, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
            side="left"
        )

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 6))
        help_icon(
            toolbar,
            "Segment list colours: green/amber/red text is the model's "
            "confidence (high/medium/low). A red row background "
            "means the hallucination detector flagged that segment as "
            "suspect. An orange row background means its timing "
            "overlaps the previous segment or is under 1s (usually "
            "after a manual 'Edit timestamp...' edit). A yellow "
            "highlight marks the segment now playing.",
        ).pack(side="right")
        ttk.Label(toolbar, text="Search:").pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refilter())
        ttk.Entry(toolbar, textvariable=self.search_var, width=24).pack(side="left")
        ttk.Button(toolbar, text="Clear", command=lambda: self.search_var.set("")).pack(
            side="left", padx=(4, 0)
        )

        # Edit tools group
        ttk.Separator(toolbar, orient="vertical").pack(side="left", padx=8, fill="y")
        ttk.Button(toolbar, text=f"Find & Replace  ({shortcuts.accel_text('f')})",
                   command=self._open_find_replace).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Remove fillers",
                   command=self._remove_fillers).pack(side="left", padx=(0, 4))
        help_icon(
            toolbar,
            "Deletes standalone filler words of the transcript's language "
            "(English um, uh, er; German äh, ähm; French euh; …) from every "
            "segment's text. Only whole filler words are removed and the "
            "punctuation stays. Languages without a list are left alone. "
            "Review the segment list before saving (there is no undo).",
        ).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text=f"Save changes  ({shortcuts.accel_text('s')})",
                   command=self._save_changes).pack(side="left", padx=(0, 4))

        # Body: left = segment list, right = media controls
        body = ttk.PanedWindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        body.add(left, weight=3)

        cols = ("time", "speaker", "text")
        self.tree = ttk.Treeview(left, columns=cols, show="headings")
        self.tree.heading("time", text="Time")
        self.tree.heading("speaker", text="Speaker")
        self.tree.heading("text", text="Segment")
        self.tree.column("time", width=px(80), anchor="w")
        self.tree.column("speaker", width=px(110), anchor="w")
        self.tree.column("text", width=px(620))
        # Confidence colour tags. The cell text becomes the colour;
        # background stays unchanged so the row's highlight tag
        # (for karaoke) layers cleanly on top.
        self.tree.tag_configure("conf_high", foreground=tokens.themed(tokens.SUCCESS_STRONG))     # green
        self.tree.tag_configure("conf_med", foreground=tokens.themed(tokens.WARNING_STRONG))      # amber
        self.tree.tag_configure("conf_low", foreground=tokens.themed(tokens.DANGER_STRONG))      # red
        self.tree.tag_configure("active", background=tokens.themed(tokens.ROW_ACTIVE))        # karaoke
        # v0.8 — segments the hallucination detector flagged as suspect.
        # Light-red background so the row stands out at a glance; the
        # confidence foreground colour layers on top normally.
        self.tree.tag_configure("suspect", background=tokens.themed(tokens.ROW_SUSPECT))
        # Light-orange background for a segment that overlaps the
        # previous one or is under 1s long — set after a manual
        # "Edit timestamp..." edit produces something odd. "suspect"
        # (hallucination) takes visual priority when both apply, since
        # tags earlier in the applied tuple win ties in ttk.Treeview.
        self.tree.tag_configure("ts_warn", background=tokens.themed(tokens.ROW_WARN))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_segment_select)
        self.tree.bind("<Double-Button-1>", self._on_segment_double_click)
        # Right-click menu — currently only the speaker rename entry,
        # extensible later. Track which item was clicked so the menu
        # acts on the right row even when no row is selected.
        self.tree.bind("<Button-3>", self._on_segment_right_click)
        if sys.platform == "darwin":
            # macOS Tk generates Button-2 for a right-click (Button-3 is
            # the rarely-used third button there).
            self.tree.bind("<Button-2>", self._on_segment_right_click)

        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(right, weight=2)

        self._right_notebook = ttk.Notebook(right)
        self._right_notebook.pack(fill="both", expand=True)
        media_tab = ttk.Frame(self._right_notebook, padding=(4, 6, 0, 0))
        chapters_tab = ttk.Frame(self._right_notebook, padding=(4, 6, 0, 0))
        ai_tab = ttk.Frame(self._right_notebook, padding=(4, 6, 0, 0))
        self._right_notebook.add(media_tab, text="Media")
        self._right_notebook.add(chapters_tab, text="Chapters")
        self._right_notebook.add(ai_tab, text="AI Tools")
        self._build_media_panel(media_tab)
        self._build_chapters_panel(chapters_tab)
        self._build_ai_panel(ai_tab)

    def _build_media_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Media", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        # The video frame — VLC will render into this widget id when
        # available. Always pack it so the layout doesn't shift when
        # VLC is missing; just keep it blank.
        self.video_canvas = tk.Frame(parent, bg="black", height=300)
        self.video_canvas.pack(fill="both", expand=True, pady=(4, 6))

        controls = ttk.Frame(parent)
        controls.pack(fill="x")
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play)
        self.play_btn.pack(side="left")
        ttk.Button(controls, text="⏮ Restart", command=self._restart).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="Open in system player",
                   command=self._open_in_system_player).pack(side="right")

        # -- transport bar: draggable seek slider + skip + readout ------
        # A horizontal scale the user drags to scrub. The position loop
        # writes the playhead into it, EXCEPT while the user is dragging
        # (self._seeking) so the thumb doesn't fight the drag. On release
        # we jump the player to the slider's fraction.
        self._transport = ttk.Frame(parent)
        self._transport.pack(fill="x", pady=(8, 0))

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_scale = ttk.Scale(
            self._transport,
            from_=0.0,
            to=float(_SEEK_SLIDER_MAX),
            orient="horizontal",
            variable=self.seek_var,
            command=self._on_seek_drag,
        )
        self.seek_scale.pack(fill="x")
        # Drag lifecycle: press → suppress auto-update; release → commit
        # the seek to the player and resume auto-update.
        self.seek_scale.bind("<ButtonPress-1>", self._on_seek_press)
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)

        skips = ttk.Frame(self._transport)
        skips.pack(fill="x", pady=(4, 0))
        self._skip_btns: list[ttk.Button] = []
        for label, delta in (
            ("⏪ -10s", -10000),
            ("◀ -5s", -5000),
            ("+5s ▶", 5000),
            ("+10s ⏩", 10000),
        ):
            b = ttk.Button(
                skips, text=label, width=8,
                command=lambda d=delta: self._skip(d),
            )
            b.pack(side="left", padx=(0, 4))
            self._skip_btns.append(b)

        # MM:SS / MM:SS readout. Kept in its own var (separate from the
        # legacy HH:MM:SS position_var used elsewhere) so the transport
        # bar shows the compact clock the spec asks for.
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(skips, textvariable=self.time_var).pack(side="right")

        # Retained for backwards compatibility — some callers/tests refer
        # to position_var. The loop keeps it updated alongside time_var.
        self.position_var = tk.StringVar(value="00:00:00 / 00:00:00")

        # Karaoke word panel — shows the active segment's words with
        # the current one highlighted. When the segment has no word
        # timestamps, falls back to the segment text.
        self._words_lbl = ttk.Label(
            parent, text="", justify="left", wraplength=px(380), padding=(2, 4),
        )
        self._words_lbl.pack(anchor="w", fill="x", pady=(8, 0))

        if self.vlc_mod is None:
            note = ttk.Label(
                parent,
                text=self.vlc_unavailable_reason
                or "Embedded playback not available.",
                foreground=tokens.themed(tokens.DANGER_TEXT),
                wraplength=px(360),
                justify="left",
            )
            note.pack(anchor="w", pady=(8, 0))
        if self.vlc_mod is None or not self.media_path:
            # No embedded player, or no media file was found next to the
            # JSON → the transport bar can't control anything, so grey it
            # out instead of presenting controls that silently do nothing.
            # "Open in system player" stays enabled (it has its own
            # "no media found" message).
            self.play_btn.state(["disabled"])
            self._set_transport_enabled(False)

    def _set_transport_enabled(self, enabled: bool) -> None:
        """Enable/disable every transport-bar control as a group.

        Used both when VLC is absent at build time and when the deferred
        HWND bind fails at runtime (_disable_embedded_playback). All
        lookups are guarded so this is safe even before the widgets
        exist or after they're destroyed.
        """
        state = ["!disabled"] if enabled else ["disabled"]
        for attr in ("seek_scale",):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.state(state)
                except Exception:  # noqa: BLE001
                    pass
        for b in getattr(self, "_skip_btns", []):
            try:
                b.state(state)
            except Exception:  # noqa: BLE001
                pass

    # -- chapters ----------------------------------------------------------

    def _chapters_path(self) -> str:
        base, _ = os.path.splitext(self.json_path)
        return base + ".chapters.json"

    def _load_chapters(self) -> None:
        """Read the ``<name>.chapters.json`` sidecar core.chapters writes,
        if present. Missing/corrupt/empty is a normal state — not every
        job has 'Generate auto-chapter markers' on — the tab shows a
        hint instead of a list in that case."""
        self.chapters: list[dict[str, Any]] = []
        path = self._chapters_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.chapters = [c for c in data if isinstance(c, dict)]
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                self.chapters = []
        self._populate_chapters_list()

    def _build_chapters_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Chapters", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        self._chapters_empty_label = ttk.Label(
            parent,
            text="No chapters detected for this transcript.\n\n"
                 "Turn on 'Generate auto-chapter markers' in Advanced "
                 "Settings' AI Layer section before transcribing to get "
                 "chapters here.",
            foreground=tokens.themed(tokens.TEXT_MUTED), wraplength=px(360), justify="left",
        )
        cols = ("time", "title")
        self._chapters_tree = ttk.Treeview(
            parent, columns=cols, show="headings", height=16,
        )
        self._chapters_tree.heading("time", text="Start")
        self._chapters_tree.heading("title", text="Title")
        self._chapters_tree.column("time", width=px(70), anchor="w")
        self._chapters_tree.column("title", width=px(280))
        self._chapters_tree.bind("<<TreeviewSelect>>", self._on_chapter_select)
        self._chapters_tree.bind("<Double-Button-1>", self._on_chapter_double_click)
        # Packed/unpacked by _populate_chapters_list depending on whether
        # this transcript has any chapters to show.

    def _populate_chapters_list(self) -> None:
        self._chapters_tree.delete(*self._chapters_tree.get_children())
        if not self.chapters:
            self._chapters_tree.pack_forget()
            self._chapters_empty_label.pack(anchor="w", pady=(8, 0))
            return
        self._chapters_empty_label.pack_forget()
        self._chapters_tree.pack(fill="both", expand=True)
        for i, ch in enumerate(self.chapters):
            title = str(ch.get("title") or f"Chapter {i + 1}")
            start = _seg_float(ch, "start")
            self._chapters_tree.insert(
                "", "end", iid=str(i), values=(_fmt_hms(start), title),
                tags=script_fonts.tree_row_tags(self._chapters_tree, title, language=self.language),
            )

    def _on_chapter_select(self, _event: tk.Event) -> None:
        item = self._chapters_tree.focus()
        if not item:
            return
        try:
            idx = int(item)
        except ValueError:
            return
        if 0 <= idx < len(self.chapters):
            start = _seg_float(self.chapters[idx], "start")
            self._seek_to(start)
            self._select_segment_near(start)

    def _on_chapter_double_click(self, event: tk.Event) -> None:
        self._on_chapter_select(event)
        if self.vlc_player is not None and not self.vlc_player.is_playing():
            self.vlc_player.play()
            self.play_btn.configure(text="⏸ Pause")

    def _select_segment_near(self, seconds: float) -> None:
        """Select + scroll the segment list to the segment whose start is
        closest to (without going past) ``seconds``. Used by chapter
        jumps, the initial-seek constructor arg, and (via open_viewer)
        the search dialog's 'Open at result' action. A no-op if the
        target segment is currently filtered out of the tree by an
        active search query."""
        if not self.segments:
            return
        from bisect import bisect_right
        starts = [_seg_float(s, "start") for s in self.segments]
        i = max(0, bisect_right(starts, seconds) - 1)
        item = str(i)
        try:
            if self.tree.exists(item):
                self.tree.selection_set(item)
                self.tree.focus(item)
                self.tree.see(item)
                self._set_active_segment(i)
        except Exception:  # noqa: BLE001
            pass

    # -- AI panel ------------------------------------------------------------

    def _full_transcript_text(self) -> str:
        return "\n".join(
            _seg_text(seg).strip()
            for seg in self.segments
            if _seg_text(seg).strip()
        )

    def _app_config(self) -> dict[str, Any]:
        cfg = getattr(self.master, "app_config", None)
        return cfg if isinstance(cfg, dict) else {}

    def _post_to_main(self, fn) -> None:
        """Thread-safe UI update — mirrors App.post_to_main (the master
        IS the App instance at every real call site: open_viewer is only
        ever invoked with the App as master). Falls back to
        self.after(0, fn) defensively if that's ever not true."""
        poster = getattr(self.master, "post_to_main", None)
        if callable(poster):
            poster(fn)
            return
        try:
            self.after(0, fn)
        except Exception:  # noqa: BLE001
            pass

    def _get_llm_runner(self) -> "tuple[Any, str]":
        """Return ``(runner, "")`` or ``(None, friendly_error)``.

        Cached on ``self._llm_runner`` after the first successful build
        (see the comment in __init__) — call this from a BACKGROUND
        thread only, never the Tk main thread: the local provider's
        first build can pay a multi-second model-load cost
        (LLMRunner.load()) that would otherwise freeze the UI.

        The cache is keyed on the provider-selecting config fields, not
        just "was a runner ever built": if the user edits Advanced
        Settings (switches local<->remote, or changes the remote URL/
        key/model) while this viewer stays open, the NEXT AI action
        rebuilds against the new settings instead of silently keeping
        the old provider for the rest of the viewer's lifetime.
        """
        cfg = self._app_config()
        cache_key = (
            bool(cfg.get("ai_enabled", False)),
            str(cfg.get("llm_provider") or "local").strip().lower(),
            str(cfg.get("ai_model_path") or ""),
            str(cfg.get("llm_remote_base_url") or ""),
            str(cfg.get("llm_remote_api_key") or ""),
            str(cfg.get("llm_remote_model") or ""),
        )
        if self._llm_runner is not None and self._llm_runner_cache_key == cache_key:
            return self._llm_runner, ""
        from core import llm as _llm
        if not cfg.get("ai_enabled", False):
            return None, (
                "AI Layer is off — turn it on in Advanced Settings' AI "
                "Layer section."
            )
        runner = _llm.build_runner_from_config(cfg)
        if runner is None:
            if str(cfg.get("llm_provider") or "local").strip().lower() == "remote":
                return None, (
                    "Remote LLM isn't configured — set Base URL + Model "
                    "in Advanced Settings' AI Layer section."
                )
            return None, (
                "Local AI model isn't installed yet — use 'Install AI "
                "model…' in Advanced Settings' AI Layer section."
            )
        self._llm_runner = runner
        self._llm_runner_cache_key = cache_key
        return runner, ""

    def _build_ai_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="AI Tools", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        self._ai_status_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self._ai_status_var,
            foreground=tokens.themed(tokens.TEXT_MUTED), wraplength=px(380), justify="left",
        ).pack(anchor="w", pady=(2, 8))
        self._refresh_ai_status()

        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=(0, 4))
        self._ai_summarise_btn = ttk.Button(
            row1, text="Summarise", command=self._run_summarise,
        )
        self._ai_summarise_btn.pack(side="left")
        self._ai_actionitems_btn = ttk.Button(
            row1, text="Action items", command=self._run_action_items,
        )
        self._ai_actionitems_btn.pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="Ask:").pack(side="left")
        self._ai_question_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self._ai_question_var, width=24).pack(
            side="left", padx=(4, 4)
        )
        self._ai_ask_btn = ttk.Button(row2, text="Ask", command=self._run_ask)
        self._ai_ask_btn.pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)

        row3 = ttk.Frame(parent)
        row3.pack(fill="x", pady=(0, 4))
        ttk.Label(row3, text="Target language:").pack(side="left")
        self._ai_target_lang_var = tk.StringVar(value="English")
        ttk.Entry(row3, textvariable=self._ai_target_lang_var, width=14).pack(
            side="left", padx=(4, 4)
        )
        self._ai_translate_btn = ttk.Button(
            row3, text="Translate (preview)", command=self._run_translate_preview,
        )
        self._ai_translate_btn.pack(side="left")

        row4 = ttk.Frame(parent)
        row4.pack(fill="x", pady=(0, 4))
        self._ai_bilingual_btn = ttk.Button(
            row4, text="Save bilingual subtitle…",
            command=self._run_bilingual_translate,
        )
        self._ai_bilingual_btn.pack(side="left")
        help_icon(
            row4,
            "Translates every segment one at a time — needed to keep an "
            "exact line-for-line pairing with the original — and writes "
            "a new '.bilingual.<language>.srt' file with the original "
            "text and the translation under each cue. Can take a while "
            "on a long transcript with the local model.",
        ).pack(side="left", padx=(4, 0))
        self._ai_cancel_btn = ttk.Button(
            row4, text="Cancel", command=self._cancel_bilingual_translate,
        )
        # Not packed here — only shown while a bilingual translate runs.

        self._ai_progress_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._ai_progress_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
            anchor="w"
        )

        ttk.Label(parent, text="Result:").pack(anchor="w", pady=(8, 2))
        result_frame = ttk.Frame(parent)
        result_frame.pack(fill="both", expand=True)
        self._ai_result_text = tk.Text(
            result_frame, wrap="word", height=12, state="disabled",
        )
        script_fonts.use_text_font(self._ai_result_text)
        ai_vsb = ttk.Scrollbar(
            result_frame, orient="vertical", command=self._ai_result_text.yview,
        )
        self._ai_result_text.configure(yscrollcommand=ai_vsb.set)
        self._ai_result_text.pack(side="left", fill="both", expand=True)
        ai_vsb.pack(side="left", fill="y")
        ttk.Button(parent, text="Copy result", command=self._copy_ai_result).pack(
            anchor="w", pady=(4, 0)
        )

    def _refresh_ai_status(self) -> None:
        cfg = self._app_config()
        if not cfg.get("ai_enabled", False):
            self._ai_status_var.set(
                "AI Layer is off. Turn it on in Advanced Settings to use "
                "these tools."
            )
            return
        provider = str(cfg.get("llm_provider") or "local").strip().lower()
        if provider == "remote":
            model = (cfg.get("llm_remote_model") or "").strip() or "(no model set)"
            self._ai_status_var.set(f"Provider: remote — {model}")
        else:
            self._ai_status_var.set("Provider: local (Qwen2.5-1.5B)")

    def _set_ai_buttons_busy(self, busy: bool) -> None:
        self._ai_busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        for b in (
            self._ai_summarise_btn, self._ai_actionitems_btn, self._ai_ask_btn,
            self._ai_translate_btn, self._ai_bilingual_btn,
        ):
            try:
                b.state(state)
            except Exception:  # noqa: BLE001
                pass

    def _set_ai_result(self, text: str, language: str | None = None) -> None:
        """Show ``text`` in the result box; ``language`` is the result's, when known."""
        try:
            self._ai_result_text.configure(state="normal")
            self._ai_result_text.delete("1.0", "end")
            self._ai_result_text.insert("1.0", text)
            script_fonts.tag_script_lines(self._ai_result_text, language=language)
            self._ai_result_text.configure(state="disabled")
        except Exception:  # noqa: BLE001
            pass

    def _copy_ai_result(self) -> None:
        try:
            text = self._ai_result_text.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return
        self._copy_to_clipboard(text)

    def _run_ai_task(self, label: str, work, language: str | None = None) -> None:
        """Shared driver for the 3 simple (non-bilingual) AI actions.

        ``work(runner) -> str`` runs on a background thread — including
        the runner build/load itself, so a first-use local-model load
        never blocks the Tk main thread. Its return value (or a
        friendly error) lands in the result box back on the Tk thread,
        tagged for ``language`` (the result's language, when known).
        Guarded by self._ai_busy against double-clicks.
        """
        if self._ai_busy:
            return
        cfg = self._app_config()
        if not cfg.get("ai_enabled", False):
            notify(
                self,
                "AI Layer is off — turn it on in Advanced Settings' AI "
                "Layer section.",
                "warning",
            )
            return
        if not self.segments:
            notify(self, "This transcript has no segments to work with.", "warning")
            return
        self._set_ai_buttons_busy(True)
        self._set_ai_result(f"{label}…")

        def _worker() -> None:
            try:
                runner, err = self._get_llm_runner()
                if runner is None:
                    self._post_to_main(lambda: self._finish_ai_task(err))
                    return
                result = work(runner)
            except Exception as e:  # noqa: BLE001
                result = f"{label} failed: {e}"
            self._post_to_main(lambda: self._finish_ai_task(result, language))

        from core._threads import safe_thread
        safe_thread(_worker, name=f"ai-{label.lower().replace(' ', '-')}")

    def _finish_ai_task(self, result: str, language: str | None = None) -> None:
        if self._closing:
            return
        self._set_ai_buttons_busy(False)
        self._set_ai_result(result, language)

    def _run_summarise(self) -> None:
        text = self._full_transcript_text()
        self._run_ai_task("Summarise", lambda runner: runner.summarise(text), self.language)

    def _run_action_items(self) -> None:
        text = self._full_transcript_text()

        def work(runner: Any) -> str:
            items = runner.action_items(text)
            return "\n".join(f"- {i}" for i in items) if items else (
                "(no action items detected)"
            )

        self._run_ai_task("Action items", work, self.language)

    def _run_ask(self) -> None:
        question = (self._ai_question_var.get() or "").strip()
        if not question:
            notify(self, "Type a question first.", "warning")
            return
        text = self._full_transcript_text()
        self._run_ai_task("Ask", lambda runner: runner.ask(text, question), self.language)

    def _run_translate_preview(self) -> None:
        lang = (self._ai_target_lang_var.get() or "English").strip() or "English"
        text = self._full_transcript_text()
        # The target is a free-text name ("Japanese"), not a code: the result's Han text picks
        # its font from kana alone, never from the transcript's language.
        self._run_ai_task(
            "Translate", lambda runner: runner.translate(text, target_language=lang),
        )

    def _run_bilingual_translate(self) -> None:
        if self._ai_busy:
            return
        if not self.segments:
            notify(self, "This transcript has no segments to translate.", "warning")
            return
        cfg = self._app_config()
        if not cfg.get("ai_enabled", False):
            notify(
                self,
                "AI Layer is off — turn it on in Advanced Settings' AI "
                "Layer section.",
                "warning",
            )
            return
        lang = (self._ai_target_lang_var.get() or "English").strip() or "English"
        if not messagebox.askyesno(
            "Bilingual subtitle",
            f"Translate all {len(self.segments)} segment(s) to {lang}, one "
            "at a time? This can take a while, especially with the local "
            "model.",
            parent=self,
        ):
            return
        segments_snap = [dict(s) for s in self.segments]
        self._bilingual_cancel = threading.Event()
        self._set_ai_buttons_busy(True)
        self._ai_cancel_btn.pack(side="left", padx=(6, 0))
        self._ai_progress_var.set("Loading AI model…")

        def _progress(done: int, total: int) -> None:
            self._post_to_main(
                lambda: self._ai_progress_var.set(f"Translating {done}/{total}…")
            )

        def _worker() -> None:
            try:
                runner, err = self._get_llm_runner()
                if runner is None:
                    self._post_to_main(
                        lambda: self._finish_bilingual_translate(
                            segments_snap, None, lang, err
                        )
                    )
                    return
                from core import llm as _llm
                translations = _llm.translate_segments(
                    runner, segments_snap, target_language=lang,
                    progress_cb=_progress, cancel_event=self._bilingual_cancel,
                )
                error = None
            except Exception as e:  # noqa: BLE001
                translations = None
                error = str(e)
            self._post_to_main(
                lambda: self._finish_bilingual_translate(
                    segments_snap, translations, lang, error
                )
            )

        from core._threads import safe_thread
        safe_thread(_worker, name="ai-bilingual-translate")

    def _cancel_bilingual_translate(self) -> None:
        if self._bilingual_cancel is not None:
            self._bilingual_cancel.set()
            self._ai_progress_var.set("Cancelling…")

    def _finish_bilingual_translate(
        self, segments: "list[dict[str, Any]]",
        translations: "list[str] | None", lang: str, error: str | None,
    ) -> None:
        if self._closing:
            return
        self._set_ai_buttons_busy(False)
        try:
            self._ai_cancel_btn.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        cancelled = self._bilingual_cancel is not None and self._bilingual_cancel.is_set()
        self._bilingual_cancel = None
        self._ai_progress_var.set("")
        if translations is None:
            if error:
                messagebox.showinfo("Bilingual subtitle", error, parent=self)
            return
        if cancelled:
            messagebox.showinfo(
                "Bilingual subtitle", "Cancelled — no file was written.", parent=self,
            )
            return
        from core.writers import bilingual_srt as _bsrt
        try:
            body = _bsrt.write(segments, translations, self.media_path or "")
        except ValueError as e:
            show_error(
                self, "Save failed", "Could not build the bilingual subtitle.",
                detail=str(e),
            )
            return
        base, _ = os.path.splitext(self.json_path)
        lang_slug = re.sub(r"[^A-Za-z0-9]+", "-", lang).strip("-").lower() or "translated"
        out_path = f"{base}.bilingual.{lang_slug}.srt"
        part = out_path + ".part"
        try:
            with open(part, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            os.replace(part, out_path)
        except Exception as e:  # noqa: BLE001
            try:
                os.unlink(part)
            except OSError:
                pass
            show_error(
                self, "Save failed", "Could not write the bilingual subtitle file.",
                detail=str(e),
            )
            return
        translated_count = sum(1 for t in translations if t)
        # Segments that had text but came back empty (the provider kept
        # refusing after its retries) are gaps, not empty cues.
        missing = sum(
            1 for seg, t in zip(segments, translations)
            if (seg.get("text") or "").strip() and not t)
        summary = (
            f"Wrote {translated_count}/{len(translations)} translated "
            f"segment(s) → {os.path.basename(out_path)}")
        # A long background job ends here and the user may be in another window, so
        # the result stays a dialog (a notice would be gone before it is seen).
        if missing:
            messagebox.showwarning(
                "Bilingual subtitle saved with gaps",
                f"{summary}\n\n{missing} segment(s) could not be translated "
                "(the AI provider kept refusing or timed out) and are left "
                "empty in the file. Run it again to fill them.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Bilingual subtitle saved", summary, parent=self,
        )

    # -- loading ---------------------------------------------------------

    def _load_segments(self) -> None:
        try:
            self._disk_stamp = _file_stamp(self.json_path)
            # utf-8-sig: a transcript re-saved by an editor that adds a BOM
            # still loads.
            with open(self.json_path, "r", encoding="utf-8-sig") as f:
                opened_text = f.read()
            payload = json.loads(opened_text)
            if not isinstance(payload, list):
                # A transcript JSON is always a list of segment dicts. A dict
                # root almost always means the user picked the wrong file
                # (e.g. a credentials/config JSON), so say so plainly.
                raise ValueError(
                    "This looks like a credentials/config file, not a "
                    "transcript JSON — pick the .json next to your "
                    "audio/video."
                )
            # The root is a list, but it may be a list of NON-dict elements
            # (e.g. ``[1, 2, 3]`` or ``["a", "b"]`` from an unrelated JSON
            # array). Downstream code calls ``.get(...)`` on each segment, so
            # keep only the dict entries. If nothing qualifies, the file isn't
            # a transcript at all — surface the same "pick the .json" guidance
            # instead of crashing with an AttributeError in _populate_listbox.
            segments = [item for item in payload if isinstance(item, dict)]
            if payload and not segments:
                raise ValueError(
                    "This JSON is a list, but none of its entries look like "
                    "transcript segments — pick the .json next to your "
                    "audio/video."
                )
            self.segments = segments
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Failed to load transcript",
                f"Could not read {self.json_path}:\n{e}",
                parent=self,
            )
            self.segments = []
            return
        self._scan_siblings(opened_text)

    def _scan_siblings(self, opened_text: str) -> None:
        """Note, in a worker thread, the exports next to the JSON that it still produces.

        Save rewrites only these. A file that differs from the JSON was
        edited elsewhere (for example in Subtitle Edit or Word), and
        overwriting it would throw that work away. The scan works from the JSON text
        as it was read, so the edits made meanwhile cannot leak into it, and the window
        never waits for a long Word build.
        """
        self._scan_generation += 1
        generation = self._scan_generation
        media_path = self.media_path
        json_path = self.json_path
        if not viewer_exports.exports_exist(json_path):
            # Nothing to check. (getattr: a bare viewer built without __init__, as some
            # tests do for _load_segments, has no events; a real one always has them.)
            for name in ("_scan_fast_done", "_scan_done"):
                event = getattr(self, name, None)
                if event is not None:
                    event.set()
            self._scan_start = None
            return
        self._scan_fast_done.clear()
        self._scan_done.clear()

        def work() -> None:
            result = viewer_exports.ScanResult(
                self._synced_siblings, self._sibling_plan, self._sibling_unchecked
            )
            try:
                with viewer_exports.responsive_threads():
                    segments = viewer_exports.segments_from_json(opened_text)
                    # The quick files first: Subtitle Edit and a fast Save need only those.
                    viewer_exports.scan_exports(
                        json_path, segments, media_path, result, slow=False)
                    if generation == self._scan_generation:
                        self._scan_fast_done.set()
                    viewer_exports.scan_exports(
                        json_path, segments, media_path, result, slow=True)
            except Exception:  # noqa: BLE001 - a scan bug must not end in a lost Save
                logger.warning("Could not check the exports of %s", json_path, exc_info=True)
            finally:
                if generation == self._scan_generation:
                    self._scan_fast_done.set()
                    self._scan_done.set()

        # Started once the window is built (a busy thread slows every Tk call the window
        # makes while it fills its list); anything that needs the result starts it at once.
        self._scan_start = lambda: threading.Thread(
            target=work, name="viewer-export-scan", daemon=True).start()
        try:
            self.after(100, self._start_scan)
        except tk.TclError:
            self._start_scan()

    def _start_scan(self) -> None:
        start, self._scan_start = self._scan_start, None
        if start is not None:
            start()

    def _populate_listbox(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []
        query = (self.search_var.get() if hasattr(self, "search_var") else "").strip()
        active_idx = self._active_segment_idx
        for idx, seg in enumerate(self.segments):
            text = _seg_text(seg).strip()
            speaker = _seg_text(seg, "speaker").strip()
            # Folded like the global search: a half-space, Arabic kaf/yeh,
            # vowel marks, digit styles and case do not hide a match.
            if query and not (folded_contains(text, query) or folded_contains(speaker, query)):
                continue
            self.filtered_indices.append(idx)
            # Confidence colour, suspect / timing backgrounds and the script
            # font (see _tags_for). Re-layer the karaoke 'active' tag on top
            # when this row is the currently-playing segment.
            base_tags = self._tags_for(idx)
            if active_idx is not None and idx == active_idx:
                tags = ("active",) + base_tags
            else:
                tags = base_tags
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(_fmt_hms(_seg_float(seg, "start")), speaker, text),
                tags=tags,
            )

    def _refilter(self) -> None:
        self._populate_listbox()

    # -- callbacks -------------------------------------------------------

    def _on_segment_select(self, _event: tk.Event) -> None:
        item = self.tree.focus()
        if not item:
            return
        try:
            idx = int(item)
        except ValueError:
            return
        seg = self.segments[idx]
        self._seek_to(_seg_float(seg, "start"))
        self._set_active_segment(idx)

    def _on_segment_double_click(self, _event: tk.Event) -> None:
        # Same as single-select but also start playback if paused.
        self._on_segment_select(_event)
        if self.vlc_player is not None and not self.vlc_player.is_playing():
            self.vlc_player.play()
            self.play_btn.configure(text="⏸ Pause")

    def _on_segment_right_click(self, event: tk.Event) -> None:
        """Pop the segment context menu.

        Currently exposes:
          - Rename speaker (when the row carries one)
          - Copy text
        """
        item = self.tree.identify_row(event.y)
        if not item:
            return
        try:
            idx = int(item)
        except ValueError:
            return
        # Select the row so subsequent edit ops act on it.
        self.tree.selection_set(item)
        seg = self.segments[idx]
        speaker = _seg_text(seg, "speaker").strip()
        menu = tk.Menu(self, tearoff=0)
        if speaker:
            menu.add_command(
                label=f"Rename '{speaker}' (everywhere)...",
                command=lambda s=speaker: self._rename_speaker(s),
            )
        menu.add_command(
            label="Edit timestamp...",
            command=lambda i=idx: self._open_edit_timestamp(i),
        )
        menu.add_command(
            label="Copy text", command=lambda: self._copy_to_clipboard(
                _seg_text(seg).strip()
            )
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            # tk_popup grabs the pointer for the duration of the popup; a
            # release is supposed to happen automatically on dismiss, but a
            # missed one is a known Tk fragility (stuck grabs / unresponsive
            # UI afterward). grab_release() is a safe no-op if there is
            # nothing left to release.
            menu.grab_release()
            # A fresh Menu is built per right-click; Tk keeps every child
            # widget alive until destroyed, so without this each right-click
            # leaked one more dead Menu for the viewer's lifetime.
            menu.destroy()

    def _open_json_folder(self) -> None:
        folder = os.path.dirname(self.json_path) or "."
        try:
            if is_darwin():
                # Reveal in Finder: the JSON is selected inside its folder.
                open_folder(folder, parent=self, select=self.json_path)
            else:
                _os_open(folder)
        except Exception as e:  # noqa: BLE001
            show_error(
                self, "Open failed",
                "Could not open the transcript's folder.", detail=str(e),
            )

    def _save_shareable_page(self) -> None:
        """Export what the list shows now (unsaved edits included) as a web page."""
        share_page.save_shareable_page(
            self,
            segments=self.segments,
            media_path=self.media_path,
            json_path=self.json_path,
            chapters=getattr(self, "chapters", None),
            language=_language_code(self.language) or None,
        )

    def _open_in_subtitle_edit(self) -> None:
        """Open the subtitle file next to this JSON in Subtitle Edit.

        Subtitle Edit reads the file on disk, so unsaved edits are offered a
        save first (Save also rewrites the subtitle files). A transcript with
        no subtitle file yet gets an SRT written from the saved JSON.
        """
        if self._dirty:
            answer = messagebox.askyesnocancel(
                "Unsaved edits",
                "Subtitle Edit opens the saved subtitle file. Save your edits "
                "first so it shows them?\n\nYes: save, then open.\n"
                "No: open the last saved version.",
                parent=self,
            )
            if answer is None:
                return
            if answer:
                self._save_changes()
                if self._dirty:
                    return
                # Subtitle Edit reads the subtitle file: let the quick rebuild finish
                # (a long Word build is not waited for).
                self._wait_for_subtitle_files()
        subtitle_path = subtitle_edit.pick_subtitle_file(
            p for p in subtitle_edit.sibling_subtitle_candidates(self.json_path)
            if os.path.isfile(p)
        )
        config = self._app_config()
        if subtitle_path is None and subtitle_edit.find_subtitle_edit(
            str(config.get(subtitle_edit.CONFIG_KEY) or "")
        ) is not None:
            subtitle_path = self._export_srt_for_subtitle_edit()
        subtitle_edit_ui.open_in_subtitle_edit(self, config, subtitle_path)

    def _segments_on_disk(self) -> list[dict[str, Any]] | None:
        """The segments as saved in the JSON (the viewer's may hold unsaved edits)."""
        if not self._dirty:
            return self.segments
        try:
            with open(self.json_path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(payload, list):
            return None
        return [item for item in payload if isinstance(item, dict)]

    def _export_srt_for_subtitle_edit(self) -> str | None:
        """Write ``<json name>.srt`` from the saved transcript; its path, or None."""
        segments = self._segments_on_disk()
        if segments is None:
            return None
        path = os.path.splitext(self.json_path)[0] + ".srt"
        try:
            _write_text_atomically(path, _render_sibling("srt", segments))
        except Exception as e:  # noqa: BLE001
            show_error(
                self, "Export failed",
                "Could not write a subtitle file for Subtitle Edit.", detail=str(e),
            )
            return None
        # It matches the saved JSON, so the next Save keeps it in step.
        self._wait_for_subtitle_files()  # the open-time scan must not overwrite this entry
        self._synced_siblings[path] = _file_stamp(path)
        self._sibling_plan[path] = ("srt", "")
        self._sibling_unchecked.discard(path)
        notify(self, f"Wrote {os.path.basename(path)} for Subtitle Edit.", "info")
        return path

    def _open_in_system_player(self) -> None:
        if not self.media_path:
            notify(self, "No media file was found alongside the transcript JSON.", "warning")
            return
        try:
            _os_open(self.media_path)
        except Exception as e:  # noqa: BLE001
            show_error(
                self, "Open failed",
                "Could not open the media file in your system player.",
                detail=str(e),
            )

    # -- edit operations -------------------------------------------------

    def _open_find_replace(self) -> None:
        if self._find_dialog is not None:
            try:
                if self._find_dialog.winfo_exists():
                    self._find_dialog.show()
                    return
            except Exception:  # noqa: BLE001
                pass
        self._find_dialog = FindReplaceDialog(self)
        self._find_dialog.show()

    def _rename_speaker(self, current: str) -> None:
        new = simpledialog.askstring(
            "Rename speaker",
            f"Rename every '{current}' to:",
            parent=self,
            initialvalue=current,
        )
        # Guard against the user pressing OK with empty / whitespace-
        # only input — that would erase every matching speaker label.
        if new is None:
            return
        new_clean = new.strip()
        if not new_clean or new_clean == current:
            return
        renamed = 0
        for seg in self.segments:
            if _seg_text(seg, "speaker").strip() == current:
                seg["speaker"] = new_clean
                renamed += 1
        if renamed:
            self._dirty = True
            self._populate_listbox()
            notify(
                self,
                f"Renamed {renamed} segment(s). Use Save changes ({shortcuts.accel_text('s')}) to write.",
                "success",
            )

    def _open_edit_timestamp(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.segments):
            return
        EditTimestampDialog(self, idx)

    def _remove_fillers(self) -> None:
        words = _filler_words_for(self.language)
        if not words:
            notify(
                self,
                "Remove fillers needs the transcript's language, and it is unknown here."
                if not _language_code(self.language) else
                f"There is no filler list for the language '{self.language}', "
                "so nothing was removed.",
                "warning",
            )
            return
        if not messagebox.askyesno(
            "Remove fillers",
            f"Remove these filler words from every segment?\n\n{', '.join(words)}",
            parent=self,
        ):
            return
        pattern = _filler_regex(words)
        changed = 0
        for seg in self.segments:
            original = _seg_text(seg)
            cleaned = _strip_fillers(original, pattern)
            if cleaned != original.strip():
                _set_segment_text(seg, cleaned)
                changed += 1
        if changed:
            self._dirty = True
            self._populate_listbox()
        notify(
            self,
            f"Fillers removed: updated {changed} segment(s). Use Save changes ({shortcuts.accel_text('s')}) to write.",
            "success" if changed else "info",
        )

    def _save_changes(self) -> None:
        if not self._dirty:
            return
        if self._disk_stamp is not None and _file_stamp(self.json_path) != self._disk_stamp:
            if not messagebox.askyesno(
                "Transcript changed on disk",
                f"{os.path.basename(self.json_path)} was changed or removed by "
                "something else after it was opened here.\n\n"
                "Overwrite it with the version in this window?",
                parent=self,
            ):
                return
        try:
            from core.writers import json_writer as _jw  # type: ignore[import-not-found]
            payload_s = _jw.write(self.segments, audio_path=self.media_path or "")
        except Exception:  # noqa: BLE001
            # Fall back to a stdlib json.dumps if the project import
            # ever fails in a stripped-down environment.
            payload_s = json.dumps(self.segments, indent=2, ensure_ascii=False) + "\n"
        part = self.json_path + ".part"
        try:
            with open(part, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload_s)
            os.replace(part, self.json_path)
        except Exception as e:  # noqa: BLE001
            try:
                os.unlink(part)
            except OSError:
                pass
            show_error(
                self, "Save failed",
                "Could not write your changes to the transcript file.",
                detail=str(e),
            )
            return
        self._dirty = False
        self._disk_stamp = _file_stamp(self.json_path)
        notify(
            self,
            f"Saved {len(self.segments)} segment(s) → {os.path.basename(self.json_path)}",
            "success",
        )
        # The JSON is on disk: only now the other exports follow, off the UI thread.
        self._queue_exports(payload_s)

    def _queue_exports(self, saved_json_text: str) -> None:
        """Rebuild the exports next to the JSON from the text just saved, in a worker.

        A newer Save replaces one still waiting (only the last text matters); the worker
        reports when it is done (``_poll_exports``) and the window shows a busy cursor.
        """
        if not viewer_exports.exports_exist(self.json_path):
            return
        self._start_scan()
        names = [p for p, _f in viewer_exports.sibling_files(self.json_path)]
        with self._export_lock:
            # Registered and listed before the thread exists: an exit that gives up early
            # can still name every file that was waiting.
            if self not in _EXPORTING:
                _EXPORTING.append(self)
            self._export_remaining.update(names)
            self._export_pending = saved_json_text
            self._export_fast_done.clear()
            start = not self._export_running
            if start:
                self._export_running = True
                self._export_idle.clear()
        if start:
            threading.Thread(target=self._export_worker, name="viewer-export-update").start()
        self._set_busy(True)
        self._schedule_export_poll()

    def _export_worker(self) -> None:
        """Worker thread: rebuild for each queued Save in turn (no widget access here)."""
        finished = False
        try:
            finished = self._export_loop()
        finally:
            if not finished:
                # The loop died (a bug inside its own error handling): never leave the
                # exit waiting for a worker that is gone.
                logger.error("The export worker of %s stopped unexpectedly", self.json_path)
                with self._export_lock:
                    self._export_running = False
                    self._export_pending = None
                    self._export_fast_done.set()
                    self._export_idle.set()
                    if self in _EXPORTING:
                        _EXPORTING.remove(self)

    def _export_loop(self) -> bool:
        while True:
            with self._export_lock:
                text = self._export_pending
                self._export_pending = None
                if text is None:
                    self._export_running = False
                    self._export_fast_done.set()
                    self._export_idle.set()
                    self._export_remaining.clear()
                    if self in _EXPORTING:
                        _EXPORTING.remove(self)  # nothing left to wait for at exit
                    return True
            try:
                self._scan_fast_done.wait()
                segments = viewer_exports.segments_from_json(text)
                scan = viewer_exports.ScanResult(
                    self._synced_siblings, self._sibling_plan, self._sibling_unchecked
                )
                with viewer_exports.responsive_threads():
                    report = viewer_exports.update_exports(
                        self.json_path, segments, scan, self._mark_export_fast_done,
                        self._wait_for_scan, self._export_remaining.discard,
                    )
            except Exception:  # noqa: BLE001 - never leave a Save without a report
                logger.exception("Updating the exports of %s failed", self.json_path)
                report = viewer_exports.ExportReport(
                    failed=[p for p, _f in viewer_exports.sibling_files(self.json_path)]
                )
            with self._export_lock:
                self._export_reports.append(report)

    def _mark_export_fast_done(self) -> None:
        """The running job's quick files are written: say so unless a newer Save is waiting
        (its files are the ones the waiters need)."""
        with self._export_lock:
            if self._export_pending is None:
                self._export_fast_done.set()

    def _schedule_export_poll(self) -> None:
        if self._export_poll_id is not None or self._closing:
            return
        try:
            self._export_poll_id = self.after(150, self._poll_exports)
        except tk.TclError:
            self._export_poll_id = None

    def _poll_exports(self) -> None:
        self._export_poll_id = None
        if self._closing:
            return
        # Idle is read BEFORE the reports are taken: a worker that finishes in between
        # leaves a report this round did not deliver, and the next round must run for it.
        idle = self._export_idle.is_set()
        self._deliver_export_reports()
        if idle:
            self._set_busy(False)
        else:
            self._schedule_export_poll()

    def _deliver_export_reports(self) -> None:
        with self._export_lock:
            reports, self._export_reports = self._export_reports, []
        for report in reports:
            for text, kind in viewer_exports.report_notices(report, self.json_path):
                notify(self, text, kind)  # type: ignore[arg-type]

    def _set_busy(self, busy: bool) -> None:
        try:
            self.configure(cursor="watch" if busy else "")
        except tk.TclError:
            pass

    def _finish_exports(self, timeout: float | None = None) -> None:
        """Wait for the exports of the last Save and show their notices (tests, Subtitle Edit)."""
        self._start_scan()
        self._scan_done.wait(timeout)
        self._export_idle.wait(timeout)
        self._deliver_export_reports()
        self._set_busy(False)

    def _wait_for_scan(self) -> None:
        self._scan_done.wait()

    def _wait_for_subtitle_files(self, timeout: float = 60.0) -> None:
        """Wait until the quick exports (subtitles included) of the last Save are written."""
        self._start_scan()
        self._scan_fast_done.wait(timeout)
        self._export_fast_done.wait(timeout)

    def _copy_to_clipboard(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:  # noqa: BLE001
            pass

    # -- VLC + karaoke ---------------------------------------------------

    def _init_vlc_player(self) -> None:
        try:
            self.vlc_instance = self.vlc_mod.Instance("--no-xlib", "--quiet")
            self.vlc_player = self.vlc_instance.media_player_new()
            media = self.vlc_instance.media_new(self.media_path)
            self.vlc_player.set_media(media)
            # CRITICAL: do NOT bind the native window handle here. This runs
            # during __init__, before the Toplevel has been realized/mapped,
            # so video_canvas.winfo_id() is either 0 or a not-yet-valid HWND.
            # Calling libvlc set_hwnd() on an unrealized window triggers a
            # native Windows access-violation that bypasses Python try/except
            # and kills the whole process ("View transcript closes the app").
            # Defer the bind until the window is actually mapped.
            self.after(0, self._bind_vlc_window)
        except Exception as e:  # noqa: BLE001
            logger.warning("VLC init failed: %s", e)
            # Same degraded state as a failed HWND bind: no player, and
            # the play/transport controls greyed out so they don't sit
            # enabled while silently doing nothing.
            self._disable_embedded_playback()

    def _bind_vlc_window(self) -> None:
        """Bind libvlc to the video canvas — only once it is realized.

        Must run AFTER the Toplevel is mapped: set_hwnd/set_xwindow/
        set_nsobject on an unmapped window or a zero window id is a native
        crash on Windows. We force a layout pass, then verify the canvas is
        mapped and has a non-zero id; if not, we degrade to the "Open in
        system player" button rather than risk the access-violation, and we
        do NOT start the position loop (no embedded surface to track).
        """
        if self._closing or self.vlc_player is None:
            return
        try:
            # Force the geometry manager to realize + map the canvas so its
            # native handle is valid before we hand it to libvlc.
            self.update_idletasks()
            mapped = bool(self.video_canvas.winfo_ismapped())
            handle = int(self.video_canvas.winfo_id())
        except Exception as e:  # noqa: BLE001
            logger.warning("VLC window not ready: %s", e)
            self._disable_embedded_playback()
            return
        if not mapped or handle == 0:
            # Not realized yet / no valid surface — fall back to the system
            # player button instead of calling set_hwnd on a dead handle.
            logger.info(
                "VLC video surface not mapped (mapped=%s, id=%s); using "
                "system player fallback.", mapped, handle,
            )
            self._disable_embedded_playback()
            return
        try:
            # The libvlc call differs per platform: HWND on Windows, an
            # NSObject (NSView) on macOS, an X11 window id on Linux.
            if sys.platform == "darwin":
                self.vlc_player.set_nsobject(handle)
            elif os.name == "nt":
                self.vlc_player.set_hwnd(handle)
            else:
                self.vlc_player.set_xwindow(handle)
        except Exception as e:  # noqa: BLE001
            logger.warning("VLC set window handle failed: %s", e)
            self._disable_embedded_playback()
            return
        # Start the position-update loop ONLY after a successful bind.
        self.after(250, self._update_position)

    def _disable_embedded_playback(self) -> None:
        """Tear down embedded playback so only the system-player path stays.

        Called when the video surface can't be bound safely. Releases the
        player and disables the Play button; "Open in system player" still
        works, so the viewer keeps degrading gracefully.
        """
        try:
            if self.vlc_player is not None:
                self.vlc_player.stop()
        except Exception:  # noqa: BLE001
            pass
        self.vlc_player = None
        try:
            self.play_btn.state(["disabled"])
        except Exception:  # noqa: BLE001
            pass
        # Nothing left to scrub — grey out the seek slider + skip buttons.
        self._set_transport_enabled(False)

    def _toggle_play(self) -> None:
        if self.vlc_player is None:
            return
        if self.vlc_player.is_playing():
            self.vlc_player.pause()
            self.play_btn.configure(text="▶ Play")
        else:
            self.vlc_player.play()
            self.play_btn.configure(text="⏸ Pause")

    def _restart(self) -> None:
        if self.vlc_player is None:
            return
        self.vlc_player.set_time(0)
        if not self.vlc_player.is_playing():
            self.vlc_player.play()
            self.play_btn.configure(text="⏸ Pause")

    def _seek_to(self, seconds: float) -> None:
        if self.vlc_player is None:
            return
        try:
            self.vlc_player.set_time(int(seconds * 1000))
        except Exception:  # noqa: BLE001
            pass

    # -- transport bar: skip + drag-to-seek ------------------------------

    def _skip(self, delta_ms: int) -> None:
        """Jump the playhead by ``delta_ms`` (negative = back), clamped.

        Wired to the ⏪/⏩ buttons and the Left/Right keys. Fully guarded:
        a None / not-yet-bound / VLC-absent player is a silent no-op so
        no exception escapes into the Tk event loop.
        """
        if self.vlc_player is None:
            return
        try:
            cur_ms = self.vlc_player.get_time() or 0
            total_ms = self.vlc_player.get_length() or 0
            target = _clamp_time_ms(cur_ms, delta_ms, total_ms)
            self.vlc_player.set_time(target)
        except Exception:  # noqa: BLE001
            pass

    def _typing_in_entry(self) -> bool:
        """True when keyboard focus is inside a text-entry widget.

        The transport hotkeys are bound on the Toplevel, so they'd
        otherwise hijack Space / arrow keys while the user types in the
        Search box or the Find-and-replace fields. Skip the hotkey then
        and let the keystroke reach the entry normally.
        """
        try:
            focused = self.focus_get()
        except Exception:  # noqa: BLE001
            return False
        if focused is None:
            return False
        return isinstance(focused, (tk.Entry, ttk.Entry))

    def _focus_on_tree(self) -> bool:
        """True when the segment Treeview holds keyboard focus.

        Left/Right normally drive the tree's own column scroll and Up/Down
        its row navigation; we don't want the video-skip hotkey to fight
        that, so the arrow hotkeys defer to the tree when it's focused.
        """
        try:
            return self.focus_get() is self.tree
        except Exception:  # noqa: BLE001
            return False

    def _on_key_skip_back(self, _event: tk.Event) -> str | None:
        # Defer to a focused entry/tree so we don't hijack their arrows.
        if self._typing_in_entry() or self._focus_on_tree():
            return None
        self._skip(-5000)
        return "break"

    def _on_key_skip_fwd(self, _event: tk.Event) -> str | None:
        if self._typing_in_entry() or self._focus_on_tree():
            return None
        self._skip(5000)
        return "break"

    def _on_key_toggle_play(self, _event: tk.Event) -> str | None:
        # Space in an entry types a space; elsewhere (including the tree,
        # where Space has no useful default) it toggles play/pause.
        if self._typing_in_entry():
            return None
        self._toggle_play()
        return "break"

    def _on_seek_press(self, _event: tk.Event) -> None:
        """User grabbed the slider — suppress the auto-update so the
        position loop stops writing the playhead into the thumb and
        fighting the drag."""
        self._seeking = True

    def _on_seek_drag(self, _value: str) -> None:
        """Fires continuously while the slider moves (ttk.Scale command).

        We don't seek the player on every motion event (that would
        stutter the decoder); we only keep the MM:SS readout live so the
        user sees where they're scrubbing to. The actual seek happens on
        button release. Only acts while a drag is in progress.
        """
        if not self._seeking or self.vlc_player is None:
            return
        try:
            total_ms = self.vlc_player.get_length() or 0
            if total_ms and total_ms > 0:
                frac = _slider_to_fraction(self.seek_var.get())
                preview_ms = frac * total_ms
                self.time_var.set(
                    f"{_fmt_mmss(preview_ms)} / {_fmt_mmss(total_ms)}"
                )
        except Exception:  # noqa: BLE001
            pass

    def _on_seek_release(self, _event: tk.Event) -> None:
        """User let go of the slider — commit the seek, then resume the
        auto-update. We prefer set_time(fraction*duration) when the
        length is known (frame-accurate); otherwise fall back to
        set_position(fraction) for streams with no duration."""
        if self.vlc_player is None:
            self._seeking = False
            return
        try:
            frac = _slider_to_fraction(self.seek_var.get())
            total_ms = self.vlc_player.get_length() or 0
            if total_ms and total_ms > 0:
                self.vlc_player.set_time(int(frac * total_ms))
            else:
                self.vlc_player.set_position(frac)
        except Exception:  # noqa: BLE001
            pass
        finally:
            # Always clear the flag so a failed seek doesn't freeze the
            # slider's auto-update forever.
            self._seeking = False

    def _update_position(self) -> None:
        # Guard against ticks that fire after the viewer's been
        # destroyed. _on_close sets _closing BEFORE destroy() so a
        # tick mid-flight short-circuits cleanly rather than calling
        # self.after() on a dead Tcl interpreter.
        if self._closing or self.vlc_player is None:
            return
        try:
            cur_ms = self.vlc_player.get_time() or 0
            total_ms = self.vlc_player.get_length() or 0
            self.position_var.set(
                f"{_fmt_hms(cur_ms / 1000.0)} / {_fmt_hms(total_ms / 1000.0)}"
            )
            # Transport bar: compact MM:SS readout + slider position.
            # Skip BOTH while the user is dragging the slider — updating
            # time_var would be harmless but updating the thumb would
            # yank it back to the playhead (the "snap-back" the spec
            # warns against). _on_seek_drag keeps the readout live during
            # the drag instead.
            if not self._seeking:
                self.time_var.set(
                    f"{_fmt_mmss(cur_ms)} / {_fmt_mmss(total_ms)}"
                )
                pos = self.vlc_player.get_position()
                if pos is not None and pos >= 0.0:
                    self.seek_var.set(_fraction_to_slider(float(pos)))
            self._update_karaoke(cur_ms / 1000.0)
        except Exception:  # noqa: BLE001
            pass
        # Re-arm only if we're still alive. Without this re-check a
        # close that lands between the try block and the after()
        # schedules a tick on a destroyed window.
        if self._closing:
            return
        try:
            self.vlc_seek_after = self.after(250, self._update_position)
        except tk.TclError:
            self.vlc_seek_after = None

    def _set_active_segment(self, idx: int | None) -> None:
        """Mark a segment as the active one (visually + for karaoke).

        ``idx=None`` clears the active highlight without selecting a
        new row — used when the playhead lands in a gap between
        segments.
        """
        if self._active_segment_idx == idx:
            return
        # Clear the previous row's active tag.
        if self._active_segment_idx is not None:
            try:
                prev = str(self._active_segment_idx)
                if self.tree.exists(prev):
                    self.tree.item(prev, tags=self._tags_for(self._active_segment_idx))
            except Exception:  # noqa: BLE001
                pass
        self._active_segment_idx = idx
        self._active_word_idx = None
        if idx is None:
            # Clear the karaoke word panel so a stale highlighted
            # word doesn't linger between segments.
            try:
                self._words_lbl.configure(text="")
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            cur = str(idx)
            if self.tree.exists(cur):
                # Layer "active" on top of the colour tag.
                tags = ("active",) + self._tags_for(idx)
                self.tree.item(cur, tags=tags)
                self.tree.see(cur)
        except Exception:  # noqa: BLE001
            pass
        # Reset the karaoke panel to the new segment's text (or empty
        # if no words list); the per-word highlight will fill in on
        # the next tick.
        try:
            seg = self.segments[idx] if 0 <= idx < len(self.segments) else None
            if seg is not None:
                self._words_lbl.configure(text=_seg_text(seg).strip())
        except Exception:  # noqa: BLE001
            pass

    def _tags_for(self, idx: int) -> tuple[str, ...]:
        if idx < 0 or idx >= len(self.segments):
            return ()
        seg = self.segments[idx]
        min_prob = _segment_min_probability(seg)
        conf: tuple[str, ...] = ()
        if min_prob is not None:
            if min_prob >= 0.85:
                conf = ("conf_high",)
            elif min_prob >= 0.6:
                conf = ("conf_med",)
            else:
                conf = ("conf_low",)
        warn: tuple[str, ...] = (
            ("ts_warn",) if _segment_has_timing_issue(self.segments, idx) else ()
        )
        # A font that draws the segment's script in full (tall marks,
        # conjuncts); only the font, so it never competes with the colours.
        font = script_fonts.tree_row_tags(
            self.tree, _seg_text(seg), language=self.language,
        )
        if seg.get("suspect"):
            return ("suspect",) + warn + conf + font
        return warn + conf + font

    def _update_karaoke(self, t_seconds: float) -> None:
        """Refresh the active segment + word highlight from the playhead.

        Uses ``bisect_left`` over the (sorted) segment-start list to
        find the candidate segment in O(log N) per tick — without
        this, the 250-ms tick costs O(N) which becomes noticeable on
        transcripts with thousands of segments.
        """
        from bisect import bisect_right

        if not self.segments:
            return
        starts = [_seg_float(s, "start") for s in self.segments]
        # Candidate: largest start <= t_seconds.
        i = bisect_right(starts, t_seconds) - 1
        active_idx: int | None = None
        if 0 <= i < len(self.segments):
            seg = self.segments[i]
            start = _seg_float(seg, "start")
            end = _seg_float(seg, "end", start)
            if start <= t_seconds <= end:
                active_idx = i
        if active_idx is None:
            # Playhead in a gap between segments — clear any lingering
            # highlight rather than leaving the previous segment lit.
            if self._active_segment_idx is not None:
                self._set_active_segment(None)
            return
        if active_idx != self._active_segment_idx:
            self._set_active_segment(active_idx)

        seg = self.segments[active_idx]
        words = _seg_words(seg)
        if not words:
            self._words_lbl.configure(text=_seg_text(seg).strip())
            return
        # Find the active word inside the segment. Non-dict entries are
        # skipped for the same reason as in _segment_min_probability: a
        # hand-edited words list (e.g. ``[1, 2]``) must not raise here —
        # a failure aborts the whole highlight update for that tick.
        active_w_idx: int | None = None
        for w_idx, w in enumerate(words):
            if not isinstance(w, dict):
                continue
            try:
                ws = float(w.get("start", 0.0))
                we = float(w.get("end", ws))
            except (TypeError, ValueError):
                continue
            if ws <= t_seconds <= we:
                active_w_idx = w_idx
                break
        if active_w_idx == self._active_word_idx:
            return
        self._active_word_idx = active_w_idx
        # Build the karaoke string. Active word wrapped in […].
        parts: list[str] = []
        for w_idx, w in enumerate(words):
            if not isinstance(w, dict):
                continue
            token = str(w.get("word", "") or "").strip()
            if not token:
                continue
            if w_idx == active_w_idx:
                parts.append(f"[{token}]")
            else:
                parts.append(token)
        self._words_lbl.configure(text=" ".join(parts))

    # -- cleanup ---------------------------------------------------------

    def _on_close(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                "Discard changes?",
                "There are unsaved transcript edits. Close anyway?",
                parent=self,
            ):
                return
        # Set the closing flag FIRST so any after()-loop tick in
        # flight (notably _update_position → _update_karaoke) sees
        # it and short-circuits before touching widgets.
        self._closing = True
        if self.vlc_seek_after is not None:
            try:
                self.after_cancel(self.vlc_seek_after)
            except Exception:  # noqa: BLE001
                pass
            self.vlc_seek_after = None
        # Destroy any open find/replace dialog so it doesn't become
        # a zombie referencing this viewer's destroyed widgets.
        if self._find_dialog is not None:
            try:
                self._find_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._find_dialog = None
        if self.vlc_player is not None:
            try:
                self.vlc_player.stop()
                self.vlc_player.release()
            except Exception:  # noqa: BLE001
                pass
        if self.vlc_instance is not None:
            try:
                self.vlc_instance.release()
            except Exception:  # noqa: BLE001
                pass
        self.destroy()

    def _bring_forward(self) -> None:
        """Show this viewer in front, so a question about it is seen.

        A viewer follows its parent window: while the app sits hidden in the tray, the
        viewer is hidden with it, so the parent is shown first.
        """
        try:
            parent = self.master
            if isinstance(parent, (tk.Tk, tk.Toplevel)) and parent.state() == "withdrawn":
                parent.deiconify()
            self.deiconify()
            self.lift()
            self.focus_force()
            # Map the window before a question is attached to it: macOS shows a
            # message box as a sheet on a mapped window, and Windows stacks the
            # box above it only once the window has its place.
            self.update_idletasks()
        except tk.TclError:
            logger.debug("Could not bring the viewer forward", exc_info=True)

    def _confirm_exit(self, show_folder: bool = False) -> bool:
        """Ask what to do with this viewer's unsaved edits as the app exits.

        True: go on exiting (saved, or discarded on purpose). False: stay open (the user
        cancelled, or the save did not happen: the edits are still here to retry).
        ``show_folder`` adds the folder, for two transcripts that share a file name.
        """
        self._bring_forward()
        where = f"Folder: {os.path.dirname(self.json_path)}\n" if show_folder else ""
        answer = messagebox.askyesnocancel(
            "Unsaved transcript edits",
            f"{os.path.basename(self.json_path)} has edits that were not saved.\n"
            f"{where}\n"
            "Yes: save them, then exit.\n"
            "No: exit and discard them.\n"
            "Cancel: stay in the app.",
            parent=self,
        )
        if answer is None:
            return False
        if not answer:
            return True
        try:
            self._save_changes()
        except Exception as e:  # noqa: BLE001 - a save that blew up must not end in a discard
            logger.exception("Saving %s on exit failed", self.json_path)
            if not self._dirty:
                # The JSON was written; only the work after it (the subtitle files next
                # to it, the "saved" notice) failed. Nothing is lost: say so and go on.
                self._notice_quietly(
                    "Saved, but the subtitle files next to it could not be updated; "
                    "the details are in app.log.",
                    "warning",
                )
                return True
            show_error(
                self, "Save failed",
                "Could not write your changes to the transcript file, so the app was not closed.",
                detail=str(e),
            )
            return False
        # Still dirty: the write failed (its error is on screen) or the user declined to
        # overwrite a file changed on disk. Either way nothing was saved: do not exit.
        if self._dirty:
            self._notice_quietly("Not saved, so the app stays open.", "warning")
            return False
        # The JSON is on disk. The quick exports (subtitle files) land before the app goes;
        # a long Word build is waited for, within a limit, by finish_exports_before_exit.
        self._wait_for_subtitle_files()
        return True

    def _notice_quietly(self, text: str, kind: Kind) -> None:
        """A notice that can never itself stop the exit."""
        try:
            notify(self, text, kind)
        except Exception:  # noqa: BLE001
            logger.warning("Could not show the notice: %s", text, exc_info=True)

    def destroy(self) -> None:
        # Also reached when the main window goes away with the viewer open.
        poll_id = getattr(self, "_export_poll_id", None)
        if poll_id is not None:
            try:
                self.after_cancel(poll_id)
            except Exception:  # noqa: BLE001
                pass
            self._export_poll_id = None
        key = self._registry_key
        if key is not None and _OPEN_VIEWERS.get(key) is self:
            del _OPEN_VIEWERS[key]
        super().destroy()


class EditTimestampDialog(tk.Toplevel):
    """Small modal to hand-edit one segment's start/end time.

    Opened from the segment right-click menu ("Edit timestamp...").
    Fields take ``HH:MM:SS.mmm``; bare seconds (``83.5``) also parse.
    Only this one segment changes — matching the reference app
    (faster-whisper-GUI)'s own per-row editable table, this does NOT
    shift any other segment's timestamps. A resulting overlap or
    sub-1s duration just gets a visual warning (see ``ts_warn`` tag),
    it never blocks saving.
    """

    def __init__(self, viewer: "TranscriptViewer", seg_idx: int) -> None:
        super().__init__(viewer)
        self.viewer = viewer
        self.seg_idx = seg_idx
        seg = viewer.segments[seg_idx]
        self.title("Edit timestamp")
        self.transient(viewer)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        start_default = _seg_float(seg, "start")
        end_default = _seg_float(seg, "end", start_default)
        self.start_var = tk.StringVar(value=_fmt_hms_ms(start_default))
        self.end_var = tk.StringVar(value=_fmt_hms_ms(end_default))

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Start (HH:MM:SS.mmm)").grid(
            row=0, column=0, sticky="w", pady=4
        )
        start_entry = ttk.Entry(body, textvariable=self.start_var, width=16)
        start_entry.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(body, text="End (HH:MM:SS.mmm)").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ttk.Entry(body, textvariable=self.end_var, width=16).grid(
            row=1, column=1, sticky="w", padx=(6, 0)
        )

        self.error_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.error_var, foreground=tokens.themed(tokens.DANGER_STRONG)).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        start_entry.focus_set()
        start_entry.selection_range(0, "end")

    def _save(self) -> None:
        start = _parse_hms_ms(self.start_var.get())
        end = _parse_hms_ms(self.end_var.get())
        if start is None or end is None:
            self.error_var.set(
                "Enter a valid time: HH:MM:SS.mmm, MM:SS.mmm, or plain seconds."
            )
            return
        if end <= start:
            self.error_var.set("End must be after start.")
            return
        seg = self.viewer.segments[self.seg_idx]
        seg["start"] = start
        seg["end"] = end
        self.viewer._dirty = True
        self.viewer._populate_listbox()
        self.destroy()


class FindReplaceDialog(tk.Toplevel):
    """Compact Ctrl+F dialog.

    Operates on the parent viewer's ``segments`` list in memory:
    ``Find next`` scrolls + selects the next matching row, ``Replace``
    overwrites the selected match, ``Replace all`` does the whole list
    in one shot. Save is a separate explicit step in the viewer.
    """

    def __init__(self, viewer: "TranscriptViewer") -> None:
        super().__init__(viewer)
        self.viewer = viewer
        self.title("Find and replace")
        self.transient(viewer)
        self.geometry("%dx%d" % scaled_size(self, 420, 180))
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.find_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.case_var = tk.BooleanVar(value=False)
        self.last_match_idx: int = -1
        # Start of the selected match inside that segment's text.
        self.last_match_pos: int = -1
        # A new search word forgets the old match, so Replace never acts on
        # a position found for the previous word.
        self.find_var.trace_add("write", lambda *_: self._forget_match())
        self.case_var.trace_add("write", lambda *_: self._forget_match())

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Find").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self.find_var, width=42).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        ttk.Label(body, text="Replace").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self.replace_var, width=42).grid(
            row=1, column=1, sticky="ew", padx=(6, 0)
        )
        ttk.Checkbutton(body, text="Match case", variable=self.case_var).grid(
            row=2, column=1, sticky="w", padx=(6, 0)
        )

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Find next", command=self.find_next).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Replace", command=self.replace_current).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Replace all", command=self.replace_all).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Close", command=self.destroy).pack(
            side="left", padx=4
        )

        body.columnconfigure(1, weight=1)

    def _forget_match(self) -> None:
        self.last_match_idx = -1
        self.last_match_pos = -1

    def show(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _needle(self) -> str:
        return self.find_var.get() or ""

    def _is_valid_needle(self, needle: str) -> bool:
        """Reject empty or whitespace-only needles — replacing every
        space in every segment with a user-supplied string is almost
        never intentional and breaks the transcript silently."""
        return bool(needle) and bool(needle.strip())

    def _match(self, haystack: str, needle: str) -> bool:
        return self._search(haystack, needle) is not None

    def _search(self, haystack: str, needle: str, start: int = 0) -> tuple[int, int] | None:
        """The ``(start, end)`` span of the next match in the ORIGINAL text.

        Matching folds Persian spelling like the global search (half-space,
        Arabic kaf/yeh, vowel marks, digit styles, case). "Match case" turns
        every fold off: a plain, exact substring search. Replace rewrites the
        returned span, so the text around it is never touched by the folding.
        """
        return find_folded_span(haystack, needle, start, exact=self.case_var.get())

    def find_next(self) -> bool:
        """Select the next match: later in the same segment first, then the
        following segments (wrapping round). Remembers the match's position
        so Replace changes exactly that occurrence."""
        needle = self._needle()
        if not self._is_valid_needle(needle):
            return False
        segments = self.viewer.segments
        n = len(segments)
        start_idx = 0
        if 0 <= self.last_match_idx < n:
            m = self._search(
                _seg_text(segments[self.last_match_idx]), needle, self.last_match_pos + 1
            )
            if m is not None:
                self.last_match_pos = m[0]
                self._reveal(self.last_match_idx)
                return True
            start_idx = self.last_match_idx + 1
        for offset in range(n):
            idx = (start_idx + offset) % n
            m = self._search(_seg_text(segments[idx]), needle)
            if m is not None:
                self.last_match_idx = idx
                self.last_match_pos = m[0]
                self._reveal(idx)
                return True
        messagebox.showinfo("No match", f"'{needle}' not found.", parent=self)
        return False

    def _reveal(self, idx: int) -> None:
        item = str(idx)
        try:
            if not self.viewer.tree.exists(item):
                # The search box hides this row: clear the filter so the
                # match can be shown.
                self.viewer.search_var.set("")
            self.viewer.tree.see(item)
            self.viewer.tree.selection_set(item)
            self.viewer.tree.focus(item)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _safe_replace(text: str, needle: str, replacement: str, case_sensitive: bool) -> str:
        """Replace ``needle`` with ``replacement`` literally.

        ``needle`` matches the way the global search does (half-space, Arabic
        kaf/yeh, vowel marks) unless ``case_sensitive`` ("Match case") asks for
        an exact match; only the matched spans of ``text`` change.

        The replacement is literal: backreferences in it (``\\1``,
        ``\\g<name>``, ``\\\\``) are kept as plain characters, never parsed
        as regex syntax (an earlier version read ``\\1`` as group 1 and
        either crashed or mangled the segment text).
        """
        return replace_folded(text, needle, replacement, exact=case_sensitive)[0]

    def replace_current(self) -> None:
        """Replace the selected occurrence only, then select the next one."""
        needle = self._needle()
        if not self._is_valid_needle(needle):
            return
        segments = self.viewer.segments
        if self.last_match_idx < 0 or self.last_match_idx >= len(segments):
            if not self.find_next():
                return
        seg = segments[self.last_match_idx]
        text = _seg_text(seg)
        pos = max(0, self.last_match_pos)
        m = self._search(text, needle, pos)
        if m is None or m[0] != pos:
            # The text changed since the match was found: find it again.
            self.find_next()
            return
        replacement = self.replace_var.get() or ""
        _set_segment_text(seg, text[: m[0]] + replacement + text[m[1]:])
        self.viewer._dirty = True
        self.viewer._populate_listbox()
        # Continue after the inserted text, so it is not matched again.
        self.last_match_pos = m[0] + len(replacement) - 1
        self.find_next()

    def replace_all(self) -> None:
        needle = self._needle()
        if not self._is_valid_needle(needle):
            return
        replacement = self.replace_var.get() or ""
        case_sensitive = self.case_var.get()
        count = 0
        for seg in self.viewer.segments:
            text = _seg_text(seg)
            new_text = self._safe_replace(text, needle, replacement, case_sensitive)
            if new_text != text:
                _set_segment_text(seg, new_text)
                count += 1
        if count:
            self.viewer._dirty = True
            self.viewer._populate_listbox()
        messagebox.showinfo(
            "Replace all",
            f"Replaced in {count} segment(s).",
            parent=self,
        )

    def destroy(self) -> None:  # type: ignore[override]
        # Clear the parent's reference so re-opening Ctrl+F builds a
        # fresh dialog instead of a stale one.
        try:
            if self.viewer._find_dialog is self:
                self.viewer._find_dialog = None
        except Exception:  # noqa: BLE001
            pass
        super().destroy()


def _dirty_viewers() -> list["TranscriptViewer"]:
    """The open viewers that hold unsaved edits, in the order they were opened."""
    found: list[TranscriptViewer] = []
    for viewer in list(_OPEN_VIEWERS.values()):
        try:
            if viewer._closing or not viewer.winfo_exists() or not viewer._dirty:
                continue
        except tk.TclError:
            continue  # the window is already gone
        found.append(viewer)
    return found


def dirty_viewers() -> list["TranscriptViewer"]:
    """The open viewers that hold unsaved edits (for the app's exit)."""
    return _dirty_viewers()


def confirm_unsaved_before_exit(skip: "Collection[TranscriptViewer]" = ()) -> bool:
    """Exit hook: Save / Discard / Cancel for every viewer with unsaved edits.

    False means the exit is cancelled (or a save failed) and the app stays as it is.
    One question per viewer, each in front and naming its file: a combined list could not
    say which transcript a Save or Discard applies to. Edits are never touched until the
    user answers, so Cancel at a later viewer leaves an earlier one saved or still dirty,
    as chosen. Nothing is asked when no viewer has unsaved edits. ``skip`` lists viewers
    already decided (discarded on purpose), which are not asked again.
    """
    dirty = [v for v in _dirty_viewers() if v not in skip]
    names = [os.path.normcase(os.path.basename(v.json_path)) for v in dirty]
    for viewer in dirty:
        show_folder = names.count(os.path.normcase(os.path.basename(viewer.json_path))) > 1
        try:
            if not viewer._confirm_exit(show_folder):
                return False
        except tk.TclError:
            # Closed while its question was open: its own close already asked about the
            # edits. Still open: the question failed, so the edits must not be dropped.
            logger.warning("Exit question for %s failed", viewer.json_path, exc_info=True)
            try:
                if viewer.winfo_exists():
                    return False
            except tk.TclError:
                pass
    return True


EXIT_EXPORT_WAIT_S = 30.0


def finish_exports_before_exit(
    timeout: float = EXIT_EXPORT_WAIT_S,
    on_wait: "Callable[[int], None] | None" = None,
    pump: "Callable[[], None] | None" = None,
) -> list[str]:
    """Exit hook: let the export rebuilds of every open viewer finish, within ``timeout``.

    The process ends with ``os._exit`` right after the app's teardown, which kills the
    worker threads, so a Word file still being rebuilt would keep its old text without a
    word (a viewer closed meanwhile counts too). The transcripts are already saved: this only
    waits (up to ``timeout`` seconds in all, never for ever), calling ``on_wait(viewers still working)`` and ``pump()`` (the
    window's event loop, so it does not look frozen) every 100 ms. Returns the exports
    that were NOT rebuilt when the time ran out (also logged), empty when all finished.
    """
    deadline = time.monotonic() + timeout
    viewers = [v for v in _EXPORTING if not v._export_idle.is_set()]
    while viewers:
        viewers = [v for v in viewers if not v._export_idle.is_set()]
        if not viewers or time.monotonic() >= deadline:
            break
        if on_wait is not None:
            on_wait(len(viewers))
        if pump is not None:
            try:
                pump()
            except tk.TclError:
                pump = None
        time.sleep(0.1)
    left: list[str] = []
    for viewer in viewers:
        left.extend(sorted(viewer._export_remaining))
    _EXPORTING[:] = [v for v in _EXPORTING if not v._export_idle.is_set()]
    if left:
        logger.warning(
            "Exiting before these exports were rebuilt (they keep the old text): %s",
            ", ".join(left),
        )
    return left


def open_viewer(
    master: "tk.Tk | tk.Toplevel",
    json_path: Optional[str] = None,
    initial_seek_seconds: float | None = None,
    language: str | None = None,
    media_path: str | None = None,
) -> "TranscriptViewer | None":
    """Open the viewer, or bring forward the one already showing this JSON.

    If ``json_path`` is None, prompt the user to pick one.
    ``initial_seek_seconds``, when given, seeks the media and selects
    the nearest segment on open — used by the search dialog's "Open at
    result" action. ``language`` is the transcript's language when the
    caller knows it (``TranscriptViewer.language``). ``media_path`` is the
    task's real source; when it is missing on disk the viewer looks for
    media next to the JSON instead. Returns the viewer, or None when
    nothing was opened.
    """
    if media_path and not os.path.isfile(media_path):
        media_path = None
    if json_path is None:
        chosen = filedialog.askopenfilename(
            title="Open transcript JSON",
            filetypes=[("Transcript JSON", "*.json"), ("All files", "*.*")],
            parent=master,
        )
        if not chosen:
            return None
        json_path = chosen
    if not os.path.isfile(json_path):
        messagebox.showerror(
            "Transcript missing",
            f"That JSON file does not exist:\n{json_path}",
            parent=master,
        )
        return None
    key = _viewer_key(json_path)
    existing = _OPEN_VIEWERS.get(key)
    if existing is not None:
        try:
            alive = bool(existing.winfo_exists())
        except tk.TclError:
            alive = False
        if alive:
            if language and not existing.language:
                existing.language = language
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            if initial_seek_seconds is not None:
                existing._seek_to(initial_seek_seconds)
                existing._select_segment_near(initial_seek_seconds)
            return existing
        _OPEN_VIEWERS.pop(key, None)
    return TranscriptViewer(
        master, json_path, media_path=media_path,
        initial_seek_seconds=initial_seek_seconds, language=language,
    )
