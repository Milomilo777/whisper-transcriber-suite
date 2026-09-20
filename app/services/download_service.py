"""yt-dlp download service.

Builds yt-dlp argv lists, runs them in a daemon thread, and posts events on
``app.download_events``. The Tk side drains the events on its main loop.

The two pure helpers, :func:`build_subtitle_command` and
:func:`build_download_command`, are exposed at module level for unit testing.
They take a task object and a "tools" descriptor and return a complete argv.
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
import urllib.error
import urllib.request

from core._proc import kill_process_tree, new_session_kwargs

logger = logging.getLogger(__name__)


def _reap_process(proc: "subprocess.Popen | None") -> None:
    """Close a download process's stdout pipe and reap it. Never raises.

    Safety net for _run_task: on the normal path the phase already
    wait()ed and nulled task.process, but if an exception is raised while
    iterating stdout the Popen would otherwise be dropped un-wait()ed —
    leaving a defunct child and an open OS pipe handle until GC. Here we
    close the pipe and, if the child (yt-dlp + its ffmpeg) is still alive,
    kill the whole tree before waiting.
    """
    if proc is None:
        return
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        if proc.poll() is None:
            kill_process_tree(proc, force=True)
        proc.wait(timeout=2)
    except Exception:  # noqa: BLE001
        pass
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from queue import Empty
from typing import TYPE_CHECKING, Any

from app.domain.languages import subtitle_lang_args
from core.config import save_config
from core.integrations import smtv as smtv_mod

if TYPE_CHECKING:
    from app.app import App
    from app.domain.tasks import VideoDownloadTask


def _dir_is_writable(path: str) -> bool:
    """Probe write access to ``path`` by actually writing a throwaway file.

    ``os.access(path, os.W_OK)`` is not reliable for this on Windows: the
    Microsoft CRT ``_waccess`` call it wraps only consults the legacy
    per-file read-only attribute, not the NTFS ACL that actually protects
    a Program Files install directory from a non-admin account -- it
    returns True even where a real write would raise PermissionError
    (confirmed against an explicit icacls /deny ACE). A real write/remove
    is the only check that matches what "yt-dlp --update" will actually
    hit.
    """
    probe = os.path.join(path, f".wp_write_probe_{os.getpid()}")
    try:
        with open(probe, "w"):
            pass
    except OSError:
        return False
    else:
        return True
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def _is_smtv_task(task: "VideoDownloadTask") -> bool:
    info = task.format_info or {}
    for key in ("audio", "video"):
        sub = info.get(key)
        if isinstance(sub, dict) and sub.get("kind") == "smtv":
            return True
    return False


def _smtv_basename_from_url(url: str) -> str | None:
    """Extract the filename the CDN encoded in ?file=… ."""
    import urllib.parse as _up
    parsed = _up.urlparse(url)
    files = _up.parse_qs(parsed.query).get("file") or []
    if not files:
        return None
    return os.path.basename(files[0])


def _quiet_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _content_length_or_none(resp: Any) -> int | None:
    raw = resp.headers.get("Content-Length") if resp.headers else None
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# --- timecode helpers (v1.0.3 — optional --download-sections slice) ------------

_MAX_TIMECODE_SECONDS = 86_400.0  # 24h sanity cap


def _parse_timecode(raw: str | None) -> float | None:
    """Parse a user-typed timecode into seconds.

    Accepted shapes (whitespace-tolerant):

      * ``H:MM:SS[.ms]`` — e.g. ``"1:23:45"``, ``"0:00:51"``
      * ``MM:SS[.ms]``   — e.g. ``"5:30"``, ``"1:25.5"``
      * ``SS[.ms]``      — e.g. ``"90"``, ``"7.25"``

    Returns ``None`` for ``None``, empty string, pure whitespace,
    negative values, values above the 24-hour sanity cap, or any
    string the parser can't make sense of (so the caller can treat
    "garbled input" the same as "left blank").
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) > 3:
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    # Reject sub-positions >= 60 in MM:SS / H:MM:SS shapes — that
    # would normally be a typo. SS-only is allowed to exceed 60
    # because the user might legitimately type "90" for 90 seconds.
    if len(nums) >= 2:
        if any(n >= 60 for n in nums[1:]):
            return None
    if len(parts) == 3:
        h, m, sec = nums
        total = h * 3600 + m * 60 + sec
    elif len(parts) == 2:
        m, sec = nums
        total = m * 60 + sec
    else:
        total = nums[0]
    if not math.isfinite(total):
        # float("nan") parses fine yet compares false to every bound, so
        # without this it slipped past both range checks: int(nan) then
        # raised ValueError out of the enqueue badge / --download-sections
        # builder when a user typed "nan" in a Start/End field. (An "inf"
        # input already fails the cap check; rejected here too.)
        return None
    if total < 0 or total > _MAX_TIMECODE_SECONDS:
        return None
    return total


def _fmt_timecode(seconds: float) -> str:
    """Format seconds back into yt-dlp's preferred ``H:MM:SS.SS``."""
    if seconds < 0:
        seconds = 0.0
    # Round to centiseconds FIRST so a value like 90.999 carries into the
    # integer part (-> 91) instead of leaving total=90 with frac="1.00",
    # which appended a bogus digit ("0:01:301"). After rounding, frac is
    # always < 1.00 so the suffix can never overflow the seconds field.
    seconds = round(seconds, 2)
    total = int(seconds)
    frac = round(seconds - total, 2)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    base = f"{hours}:{minutes:02d}:{secs:02d}"
    # Preserve sub-second precision only when the user supplied any —
    # avoids polluting argv with .00 for whole-second inputs.
    if frac > 0:
        # 2-decimal fractional, drop trailing zeros + dot.
        suffix = f"{frac:.2f}".lstrip("0").rstrip("0").rstrip(".")
        if suffix:
            base = f"{base}{suffix}"
    return base


def _download_sections_arg(
    start: float | None, end: float | None
) -> str | None:
    """Build the ``--download-sections`` value, or ``None`` if both bounds unset."""
    if start is None and end is None:
        return None
    # A nonsensical end <= start (fat-fingered, or end slider dragged below
    # start) would make yt-dlp's "*start-end" download nothing/error — drop
    # the end so it degrades to "from start to the end of the video".
    if start is not None and end is not None and end <= start:
        end = None
    start_str = _fmt_timecode(start) if start is not None else ""
    end_str = _fmt_timecode(end) if end is not None else ""
    return f"*{start_str}-{end_str}"


def _time_range_badge(
    start: float | None, end: float | None
) -> str | None:
    """Short ``MM:SS -> MM:SS`` badge for the Queue row title.

    Mirrors :meth:`VideoDownloadTask.time_range_label` but is exposed
    here so the enqueue path can decorate the title before any task
    instance exists.
    """
    if start is None and end is None:
        return None

    def _fmt(seconds: float | None, *, fallback: str) -> str:
        if seconds is None:
            return fallback
        total = int(seconds)
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    return f"{_fmt(start, fallback='start')} -> {_fmt(end, fallback='end')}"


# Module-level pure builders (tested in tests/test_download_command.py) ---------


_COOKIE_BROWSERS = frozenset({
    "brave", "chrome", "chromium", "edge", "firefox", "opera",
    "safari", "vivaldi", "whale",
})


def _cookies_from_browser_args(value: str | None) -> list[str]:
    """``--cookies-from-browser`` args for yt-dlp, or [] when unset.

    Lets the app download login-walled / age-gated content (Facebook,
    Instagram, TikTok stories; some YouTube Shorts) using the user's
    logged-in browser session. ``value`` accepts yt-dlp's
    ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]`` syntax; the leading
    browser token is validated against the supported set so a typo in a
    hand-edited config can't pass a bogus flag.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    browser = raw.split("+", 1)[0].split(":", 1)[0].strip().lower()
    if browser not in _COOKIE_BROWSERS:
        return []
    return ["--cookies-from-browser", raw]


# yt-dlp's own failure to read the local browser's cookie jar — e.g. "Could
# not copy Chrome cookie database" when the browser is still open and holds
# a lock on the file (see yt-dlp#7271) — is a LOCAL file-access problem, not
# the target site rejecting an unauthenticated request. Most URLs (a public
# post, a public video) do not actually need the cookies at all, so this
# case is worth a same-process retry without them rather than failing the
# whole download outright.
_COOKIE_EXTRACTION_ERROR_RE = re.compile(
    r"could not (?:copy|find|load|extract)\b.{0,40}\bcookie", re.IGNORECASE
)


def _is_cookie_extraction_error(text: str) -> bool:
    """True when yt-dlp failed to read the browser's cookie jar itself.

    Distinct from the target site genuinely requiring a logged-in session
    (that shows up as a normal auth/permission error from the site, not a
    local "could not copy/find the cookie database" failure).
    """
    return bool(_COOKIE_EXTRACTION_ERROR_RE.search(text or ""))


def build_subtitle_command(
    task: "VideoDownloadTask",
    lang: str,
    *,
    yt_dlp_path: str,
    bin_path: str,
    cookies_from_browser: str | None = None,
) -> list[str]:
    output = os.path.join(task.folder, "%(title)s.%(ext)s")
    sub_langs = subtitle_lang_args(lang)
    command = [yt_dlp_path]
    if bin_path:
        command += ["--ffmpeg-location", bin_path]
    command += ["--newline"]
    command.extend(_cookies_from_browser_args(cookies_from_browser))
    command.extend([
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        sub_langs,
        "--no-playlist",
        "-o",
        output,
        # End-of-options: a pasted "URL" starting with '-' must not be
        # parsed as a yt-dlp flag (e.g. --exec → arbitrary command).
        "--",
        task.url,
    ])
    return command


# Extensions yt-dlp writes for "Writing video subtitles to:" that
# core.convert.parse_to_segments can read (auto-subs are usually .vtt;
# --write-subs can also produce .srt for some sites).
_CONVERTIBLE_SUB_EXTS = (".vtt", ".srt")


def write_subtitle_extra_formats(
    sub_path: str, *, language: str = "", work_title: str = "",
) -> list[str]:
    """Convert a downloaded ``.vtt``/``.srt`` subtitle into extra formats.

    Writes, alongside *sub_path*:

      * an oTranscribe ``.otr`` (via :mod:`core.integrations.otranscribe`),
      * an Express Scribe ``.txt`` (via the ``express_scribe`` writer), and
      * an SMTV transcription ``.docx`` (via ``smtv_docx_writer``, when
        python-docx is available).

    Returns the list of extra paths actually written. Never raises: each
    format is best-effort and a failure (missing optional dependency,
    unparseable subtitle, disk error) is swallowed so the caller's
    subtitle-download flow is unaffected. Returns ``[]`` for an
    unparseable / unsupported *sub_path* (e.g. not ``.vtt``/``.srt``, or no
    cues).
    """
    if os.path.splitext(sub_path)[1].lower() not in _CONVERTIBLE_SUB_EXTS:
        return []

    from core import convert as _convert
    from core.integrations import otranscribe as _otr

    try:
        segments = _convert.parse_to_segments(sub_path)
    except _convert.ConvertError:
        return []
    if not segments:
        return []

    written: list[str] = []
    base = os.path.splitext(sub_path)[0]

    # Express Scribe .txt
    try:
        out = _convert.convert_file(sub_path, "express_scribe", f"{base}.txt")
        written.append(out)
    except (OSError, _convert.ConvertError) as e:
        logger.warning("Express Scribe export for %s failed: %s", sub_path, e)

    # oTranscribe .otr — otr_to_srt/whisper_json_to_otr need a file path, so
    # round-trip the parsed segments through a temp JSON via the existing
    # JSON writer rather than duplicating the .otr serialisation here.
    try:
        import tempfile

        from core.writers import json_writer as _json_writer

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(_json_writer.write(segments, sub_path))
            tmp_path = tmp.name
        try:
            otr_text = _otr.whisper_json_to_otr(
                tmp_path, media_filename=os.path.basename(sub_path)
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        otr_path = f"{base}.otr"
        with open(otr_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(otr_text)
        written.append(otr_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("oTranscribe export for %s failed: %s", sub_path, e)

    # SMTV transcription .docx (needs python-docx; skip cleanly if absent).
    try:
        from core.writers import smtv_docx_writer as _smtv_docx

        payload = _smtv_docx.write_bytes(
            segments, sub_path, language=language, work_title=work_title,
        )
        docx_path = f"{base}.smtv.docx"
        with open(docx_path, "wb") as f:
            f.write(payload)
        written.append(docx_path)
    except (RuntimeError, OSError) as e:
        logger.info("SMTV docx export for %s skipped: %s", sub_path, e)

    return written


def build_download_command(
    task: "VideoDownloadTask",
    *,
    yt_dlp_path: str,
    bin_path: str,
    sponsorblock_categories: list[str] | None = None,
    progress_template: str | None = None,
    cookies_from_browser: str | None = None,
) -> list[str]:
    output = os.path.join(task.folder, "%(title)s.%(ext)s")
    command = [yt_dlp_path]
    if bin_path:
        command += ["--ffmpeg-location", bin_path]
    # ``-c`` / ``--continue`` so a resumed download (R2 stop-and-continue
    # "pause") picks up the existing .part fragment instead of restarting
    # from zero. yt-dlp continues by default for plain downloads, but being
    # explicit also covers the modes where it would otherwise overwrite.
    command += ["--newline", "-c", "-o", output]
    command.extend(_cookies_from_browser_args(cookies_from_browser))
    if progress_template:
        command.extend(["--progress-template", progress_template])
    if sponsorblock_categories:
        command.extend(["--sponsorblock-remove", ",".join(sponsorblock_categories)])
    fmt = task.format_info
    output_format = fmt.get("output", "mp4")
    audio = fmt.get("audio") or {"kind": "best_audio"}
    video = fmt.get("video") or {"kind": "best_video"}

    if fmt.get("mode") == "Audio":
        audio_selector = "ba/bestaudio" if audio["kind"] == "best_audio" else audio["format_id"]
        command.extend(["-f", audio_selector, "-x", "--audio-format", output_format])
    else:
        
        if video["kind"] == "best_video":
            if output_format == "mp4":
                video_selector = "bv*[ext=mp4]/bestvideo[ext=mp4]/bv*/bestvideo"
            else:
                video_selector = "bv*/bestvideo"
        else:
            video_selector = video["format_id"]

        if audio["kind"] == "best_audio":
            if output_format == "mp4":
                audio_selector = "ba[ext=m4a]/bestaudio[ext=m4a]/ba/bestaudio"
            else:
                audio_selector = "ba/bestaudio"
        else:
            audio_selector = audio["format_id"]

        format_selector = f"({video_selector})+({audio_selector})/best"

        command.extend([
            "-f",
            format_selector,
            "--merge-output-format",
            output_format,
        ])


    # Optional --download-sections slice (v1.0.3). Only emitted when
    # the user supplied a start and/or end in the Download tab fields
    # and the task carries the parsed values. yt-dlp accepts the same
    # ``*start-end`` shape regardless of audio-only vs muxed mode.
    section_start = getattr(task, "section_start", None)
    section_end = getattr(task, "section_end", None)
    sections_arg = _download_sections_arg(section_start, section_end)
    if sections_arg is not None:
        command.extend(["--download-sections", sections_arg])

    # End-of-options separator: a URL starting with '-' must not be parsed
    # as a yt-dlp flag (e.g. --exec → arbitrary command execution).
    command.append("--")
    command.append(task.url)
    return command


_PERCENT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
# Plain per-stream download target. With adaptive (separate video+audio)
# formats these are intermediate fragments that yt-dlp DELETES the moment
# it merges them, so a fragment path must never win over a final one below.
_DEST_RE = re.compile(r"^\[download\] Destination:\s+(.+)$")
# Authoritative final on-disk file, emitted by post-processing. yt-dlp
# prints the merge target QUOTED and with NO colon
# (`Merging formats into "PATH"`); audio extraction uses `Destination: PATH`;
# a re-run that finds the file already present prints `PATH has already
# been downloaded`. These name the file that actually survives on disk.
_MERGE_RE = re.compile(r'^\[Merger\] Merging formats into "(.+)"$')
_EXTRACT_RE = re.compile(r"^\[ExtractAudio\] Destination:\s+(.+)$")
_ALREADY_RE = re.compile(r"^\[download\] (.+) has already been downloaded$")


def _utf8_subprocess_env() -> dict[str, str]:
    """Env that forces the yt-dlp child to emit UTF-8 on stdout.

    On Windows a child Python process defaults to the console/ANSI code
    page, so a non-ASCII filename character (e.g. the U+2019 apostrophe in
    a YouTube title) came back mojibake'd under our utf-8 decode. The
    parsed saved_path then didn't match the real on-disk file, so the size
    readout showed "(?)" and auto-transcribe hit "No such file".
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def parse_progress_line(line: str) -> dict[str, Any] | None:
    """Parse one stdout line from yt-dlp.

    Recognized shapes:
      * ``--progress-template "%(progress)j"`` JSON: returns the dict as-is plus
        a derived ``percent`` field when ``downloaded_bytes`` and
        ``total_bytes`` are both present.
      * Legacy ``[download] N.N%`` regex: returns ``{"percent": ...}``.
      * Anything else: returns ``None``.
    """
    line = (line or "").strip()
    if not line:
        return None
    if line.startswith("{") and line.endswith("}"):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        downloaded = payload.get("downloaded_bytes")
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
            payload["percent"] = min(100.0, (downloaded / total) * 100.0)
        return payload
    m = _PERCENT_RE.search(line)
    if m:
        return {"percent": float(m.group(1))}
    return None


def parse_destination_line(line: str) -> tuple[str, bool] | None:
    """Pick a saved-file path out of one yt-dlp output line.

    Returns ``(path, is_final)`` or ``None``. ``is_final`` is True for a
    post-processed / already-present file (a merge target, extracted audio,
    or "has already been downloaded"). Those name the file that survives on
    disk and must take priority over the per-stream ``[download]
    Destination:`` fragments, which yt-dlp deletes during a video+audio
    merge — transcribing a fragment path would hit a missing file.
    """
    if not line:
        return None
    s = line.strip()
    for pattern in (_MERGE_RE, _EXTRACT_RE, _ALREADY_RE):
        m = pattern.match(s)
        if m:
            return m.group(1).strip(), True
    m = _DEST_RE.match(s)
    if m:
        return m.group(1).strip(), False
    return None


def select_saved_path(lines: "Iterable[str]") -> str | None:
    """Choose the real saved file from a run of yt-dlp output lines.

    A final (post-processed) path wins and locks; the per-stream fragment
    paths only fill in until a final one arrives, and never overwrite it —
    so a download whose fragments were merged-then-deleted still resolves to
    the surviving merged file. Mirrors the accumulation in ``_media_phase``.
    """
    saved: str | None = None
    saved_is_final = False
    for line in lines:
        dest = parse_destination_line(line.rstrip())
        if dest is None:
            continue
        path, is_final = dest
        if is_final or not saved_is_final:
            saved = path
            saved_is_final = saved_is_final or is_final
    return saved


# Service class wired into the App ------------------------------------------------


class DownloadService:
    def __init__(self, app: "App") -> None:
        self.app = app

    # Helpers exposed to the App
    def resolve_subtitle_lang(self, task: "VideoDownloadTask") -> str:
        lang = task.subtitle_lang or task.detected_language or ""
        return lang.strip()

    def build_subtitle_command(self, task: "VideoDownloadTask", lang: str) -> list[str]:
        return build_subtitle_command(
            task, lang,
            yt_dlp_path=self.app.yt_dlp_path(),
            bin_path=self.app.bin_path(),
            cookies_from_browser=self.app.app_config.get("cookies_from_browser", ""),
        )

    def build_download_command(
        self, task: "VideoDownloadTask", *, force_no_cookies: bool = False
    ) -> list[str]:
        return build_download_command(
            task,
            yt_dlp_path=self.app.yt_dlp_path(),
            bin_path=self.app.bin_path(),
            sponsorblock_categories=list(self.app.app_config.get("sponsorblock_categories") or []),
            progress_template="%(progress)j",
            cookies_from_browser=(
                None if force_no_cookies else self.app.app_config.get("cookies_from_browser", "")
            ),
        )

    def maybe_update_yt_dlp(self, task: "VideoDownloadTask") -> None:
        cfg = self.app.app_config
        if not cfg.get("auto_update_yt_dlp", False):
            return
        # A frozen build's bundled yt-dlp lives inside the read-only app
        # bundle/install dir; "yt-dlp --update" can't write there and would
        # just fail silently every 24h (matches the core.tiling self-heal
        # guard for the same reason).
        if getattr(sys, "frozen", False):
            return
        last = cfg.get("last_yt_dlp_update_check") or ""
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if datetime.now(timezone.utc) - last_dt < timedelta(hours=24):
                    return
            except ValueError:
                pass
        yt_dlp_path = self.app.yt_dlp_path()
        # The Setup-Standard installer (embeddable Python, not frozen) puts
        # yt-dlp.exe under Program Files by default, which a non-admin
        # Windows account can't write to -- "yt-dlp --update" would fail
        # every 24h the same way. Skip whenever the resolved binary's own
        # directory isn't writable, regardless of why (Program Files,
        # frozen bundle, read-only mount, ...). A bare "yt-dlp" fallback
        # name (no bundled binary found; PATH lookup on Linux/Mac) has no
        # directory to check, so it falls through unchanged. Checked after
        # the 24h backoff above so the real probe write in _dir_is_writable
        # only runs once a day, not on every single download task.
        yt_dlp_dir = os.path.dirname(yt_dlp_path)
        if yt_dlp_dir and not _dir_is_writable(yt_dlp_dir):
            return
        try:
            update_cmd = [yt_dlp_path, "--update"]
            update = subprocess.run(
                update_cmd,
                cwd=os.path.dirname(os.path.abspath(self.app.entry_file)),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if update.stdout.strip():
                self.app.download_events.put(("log", task, update.stdout.strip()))
            if update.stderr.strip():
                self.app.download_events.put(("log", task, update.stderr.strip()))
            if update.returncode:
                self.app.download_events.put(
                    ("log", task, f"yt-dlp update returned code {update.returncode}; continuing")
                )
            # Only stamp the 24h backoff once the check actually ran to
            # completion (regardless of returncode) -- a timeout or other
            # failure below means we never really checked, so it must not
            # suppress a retry on the next download for a full day.
            cfg["last_yt_dlp_update_check"] = datetime.now(timezone.utc).isoformat()
            try:
                save_config(cfg)
            except Exception:
                logger.exception("Failed to persist yt-dlp auto-update preference")
        except subprocess.TimeoutExpired:
            self.app.download_events.put(("log", task, "yt-dlp update timed out; continuing"))
        except Exception as e:  # noqa: BLE001
            self.app.download_events.put(("log", task, f"yt-dlp update skipped: {e}"))

    def _warn_format_missing(self, kind: str) -> None:
        """Explain why a required audio/video format isn't selected.

        "Wait for formats to load" is only true while the lookup is still
        running (or hasn't been tried for this URL yet). Once the lookup
        has already run and failed -- an extractor rejecting the URL
        (Facebook/Instagram/X often need a logged-in session, or break
        outright when the site changes its page structure), a network
        error, a deleted/private video -- that message is a dead end: it
        tells the user to wait for something that will never finish, and
        the real reason (format_service already captured it) never
        reaches the download log the user is watching. Surface it in both
        places instead.
        """
        from tkinter import messagebox

        app = self.app
        reason = getattr(app, "format_lookup_error", "")
        if reason:
            message = (
                f"This URL's {kind} formats could not be loaded, so it "
                f"cannot be downloaded yet:\n\n{reason}"
            )
            app.log(f"Download blocked -- format lookup failed: {reason}")
        else:
            message = f"Wait for formats to load, then select an {kind} format."
        messagebox.showwarning(f"Missing {kind} format", message, parent=app)

    def enqueue_from_form(self) -> None:
        """Read the download tab form, validate, build a task, and enqueue."""
        from tkinter import messagebox
        from app.domain.languages import SUBTITLE_LANGUAGES
        from app.domain.tasks import VideoDownloadTask

        app = self.app
        url = app.download_url_var.get().strip()
        folder = app.download_folder_var.get().strip()
        mode = app.download_mode_var.get()
        audio_label = app.audio_format_var.get()
        video_label = app.video_format_var.get()
        output = app.output_format_var.get()
        if not url:
            messagebox.showwarning("Missing URL", "Enter a URL first.", parent=app)
            return
        if not folder:
            messagebox.showwarning("Missing folder", "Select a download folder first.", parent=app)
            return

        # Resolve the SMTV episode up front: an SMTV news/short clip ships
        # WITHOUT an mp3 (only video qualities), so audio_format_map is empty
        # for it. The audio-format gate below must not reject such a clip in
        # video mode (smtv-research.md R3) — so we need is_smtv before the
        # validation runs, not after it (as it used to be ordered).
        # Match the stashed episode against THIS url's page_url, not just
        # "is it some SMTV episode". The format lookup is debounced 800ms,
        # so a user who pastes SMTV url A, then replaces it with a DIFFERENT
        # SMTV url B and clicks Download before B's lookup fires, would
        # otherwise reuse episode A's CDN urls/transcript for B. A real
        # episode (fetch_episode) always carries its already-stripped
        # page_url, and url is stripped above, so reject the reuse only when
        # the episode HAS a page_url that disagrees — an episode with no
        # page_url (never produced in practice) keeps the old behaviour.
        raw_episode = getattr(app, "_smtv_episode", None)
        episode_page_url = (getattr(raw_episode, "page_url", "") or "").strip()
        smtv_episode: smtv_mod.SmtvEpisode | None = (
            raw_episode
            if isinstance(raw_episode, smtv_mod.SmtvEpisode)
               and smtv_mod.is_smtv_url(url)
               and (not episode_page_url or episode_page_url == url)
            else None
        )
        is_smtv = smtv_episode is not None

        # An audio format is only required when audio is actually downloaded:
        #   * "Audio" mode (audio-only output) always needs one;
        #   * a non-SMTV "Audio and video" download still merges a separate
        #     audio stream, so it needs one too.
        # An SMTV video download carries its audio inside the muxed video
        # file (there is no separate audio stream), and a news/short clip has
        # no mp3 variant at all, so an empty audio map must NOT block it.
        audio_required = mode == "Audio" or not is_smtv
        if audio_required and (not audio_label or audio_label not in app.audio_format_map):
            self._warn_format_missing("audio")
            return
        if mode == "Audio and video" and (not video_label or video_label not in app.video_format_map):
            self._warn_format_missing("video")
            return
        if not output:
            messagebox.showwarning("Missing output", "Select an output format.", parent=app)
            return

        # The saved folder can have gone stale (a USB/network drive that is
        # now unplugged, a read-only or no-longer-existing path). os.makedirs
        # and save_config can both raise OSError straight out of the Download
        # button callback; guard them so the non-technical operator gets an
        # actionable message instead of a console traceback / silent no-op.
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showwarning(
                "Folder unavailable",
                f"Cannot create or write the download folder:\n{folder}\n\n{e}",
                parent=app,
            )
            return
        app.app_config["download_folder"] = folder
        title = app.current_video_title or url
        subtitles_enabled = app.download_subtitles_var.get()
        sub_lang_name = app.subtitle_lang_var.get()
        sub_lang_code = next((code for name, code in SUBTITLE_LANGUAGES if name == sub_lang_name), "")
        app.app_config["download_subtitles_enabled"] = subtitles_enabled
        app.app_config["download_subtitle_lang"] = sub_lang_name
        try:
            save_config(app.app_config)
        except OSError:
            # The download itself can still proceed; only the preference
            # persistence failed. Log it (FB-01: never silent) and continue
            # rather than abort the enqueue the user explicitly asked for.
            logger.exception("Failed to persist download preferences")
        label_extra = f" + subs ({sub_lang_name})" if subtitles_enabled else ""
        format_label = f"{mode} -> {output}{label_extra}"
        format_info = {
            "mode": mode,
            # audio_label may be absent for an SMTV video-only clip; guard
            # the lookup so it never KeyErrors when audio isn't required.
            "audio": app.audio_format_map.get(audio_label),
            "video": app.video_format_map.get(video_label),
            "output": output,
        }

        # When the stashed episode was rejected (stale page_url != url, so
        # is_smtv is False) the format maps were NOT necessarily rebuilt yet —
        # the 800ms lookup for the new url may not have fired. The maps can
        # still hold the rejected episode's kind=='smtv' selector dicts (with
        # episode A's CDN url). Routing keys off _is_smtv_task, which trips on
        # ANY kind=='smtv' sub-dict, so leaving one in format_info would stream
        # the stale CDN file while writing this url's transcript. The 'episode'
        # key was already guarded above; scrub the audio/video selectors too so
        # no kind=='smtv' sub-dict survives into a non-SMTV task.
        if not is_smtv:
            for key in ("audio", "video"):
                sub = format_info.get(key)
                if isinstance(sub, dict) and sub.get("kind") == "smtv":
                    format_info[key] = None

        if smtv_episode is not None:
            format_info["episode"] = smtv_episode
            format_label = f"SMTV {audio_label if mode == 'Audio' else video_label}"

        # Optional time-range slice (v1.0.3). Read both Start/End
        # entry vars, parse with the strict timecode parser, and pin
        # the result onto the task. Either bound may stay None (open-
        # ended on that side). When the URL is SMTV the slice is
        # ignored at run-time (smtv path streams the full CDN file)
        # — the warning is logged by core.integrations.smtv when the
        # download begins so the user sees it in the same console.
        raw_start = ""
        raw_end = ""
        start_var = getattr(app, "download_start_time_var", None)
        end_var = getattr(app, "download_end_time_var", None)
        if start_var is not None:
            try:
                raw_start = start_var.get()
            except Exception:  # noqa: BLE001
                raw_start = ""
        if end_var is not None:
            try:
                raw_end = end_var.get()
            except Exception:  # noqa: BLE001
                raw_end = ""
        section_start = _parse_timecode(raw_start)
        section_end = _parse_timecode(raw_end)
        # The fields default to "0:00:00"; treat a zero (or blank) bound as
        # "unset" so the default = the full video. A real 0:00:00 start is
        # the beginning anyway (== open-left) and a 0:00:00 end is
        # nonsensical, so collapsing both to None loses nothing.
        if not section_start:
            section_start = None
        if not section_end:
            section_end = None
        # Drop any bound at/beyond the probed video length. A user can TYPE a
        # timecode past the end (the slider clamps, the entry field doesn't);
        # an end >= duration is just "to the end" so dropping it is exactly
        # equivalent, and a start >= duration is an empty slice that would
        # build a "*<dur>-" arg yt-dlp can't honour (it downloads nothing /
        # errors). Only act on a positive, known duration so a live/unknown
        # length (0) never touches a valid range. SMTV ignores the slice
        # entirely, so skip the guard there too.
        probed_duration = 0.0
        if not is_smtv:
            try:
                probed_duration = float(getattr(app, "_download_duration", 0.0) or 0.0)
            except (TypeError, ValueError):
                probed_duration = 0.0
        if probed_duration > 0:
            if section_start is not None and section_start >= probed_duration:
                section_start = None
            if section_end is not None and section_end >= probed_duration:
                section_end = None
        any_range = section_start is not None or section_end is not None

        # Decorate the visible title with the trim badge so the
        # Queue tab's File column shows the user what slice is
        # being downloaded — matches the spec's "trim 0:51 -> 1:25".
        decorated_title = title
        if any_range:
            badge = _time_range_badge(section_start, section_end)
            if badge:
                decorated_title = f"{title}  -  trim {badge}"

        if any_range and is_smtv:
            # The SMTV streamer doesn't honour --download-sections;
            # warn the user once via the existing log channel so
            # nobody silently gets a full clip when they asked for
            # a slice. The actual download is unchanged.
            smtv_mod.warn_time_range_unsupported(url)
            app.download_events.put(
                ("log", None,
                 "Time-range download is not supported for Supreme Master "
                 "TV URLs in this release; downloading the full clip.")
            )

        tasks_to_enqueue = [
            VideoDownloadTask(
                url, folder, format_label, format_info, decorated_title,
                subtitles_enabled=False if is_smtv else subtitles_enabled,
                subtitle_lang="" if is_smtv else sub_lang_code,
                detected_language=app.current_video_language,
                # SMTV ignores the slice at run-time but we still
                # store the values so .time_range_label() and any
                # later inspection see what the user asked for.
                section_start=section_start,
                section_end=section_end,
            )
        ]

        if (
            smtv_episode is not None
            and getattr(app, "smtv_download_all_parts_var", None) is not None
            and bool(app.smtv_download_all_parts_var.get())
            and smtv_episode.siblings
        ):
            tasks_to_enqueue.extend(
                self._build_smtv_sibling_tasks(
                    smtv_episode,
                    mode=mode,
                    video_label=video_label,
                    folder=folder,
                    format_label=format_label,
                    output=output,
                )
            )

        for t in tasks_to_enqueue:
            app.download_queue.append(t)
        app.refresh_download_queue()

        # Clear the time-range entries so the next URL the user
        # pastes doesn't accidentally inherit this job's slice. The
        # spec calls these per-job, not persistent. Done in a try/
        # except so a missing var (e.g. headless test harness) is
        # never fatal.
        if start_var is not None:
            try:
                start_var.set("")
            except Exception:  # noqa: BLE001
                pass
        if end_var is not None:
            try:
                end_var.set("")
            except Exception:  # noqa: BLE001
                pass

        self.process_queue()

    def enqueue_caption_only_from_form(self) -> None:
        """"Use captions instead" shortcut button on the Download tab.

        Fetches only the existing captions for the pasted URL and converts
        them to the transcript formats chosen in Advanced settings,
        skipping the media download and the transcription queue entirely.
        Only ever offered (see App.update_caption_shortcut_state) when the
        most recent format lookup actually found a caption track in the
        resolved language, so the "no captions found" branch below should
        be rare -- it's a defensive re-check, not the primary UX path.
        """
        from tkinter import messagebox

        from app.domain.languages import SUBTITLE_LANGUAGES, resolve_caption_kind
        from app.domain.tasks import VideoDownloadTask

        app = self.app
        url = app.download_url_var.get().strip()
        folder = app.download_folder_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Enter a URL first.", parent=app)
            return
        if not folder:
            messagebox.showwarning("Missing folder", "Select a download folder first.", parent=app)
            return
        if getattr(app, "_smtv_episode", None) is not None:
            # The shortcut button is hidden for SMTV URLs; this only
            # guards a stale click racing a URL change.
            return

        sub_lang_name = app.subtitle_lang_var.get()
        lang_code_csv = next(
            (code for name, code in SUBTITLE_LANGUAGES if name == sub_lang_name), ""
        )
        caption_langs = getattr(app, "current_video_caption_langs", None) or {}
        kind = resolve_caption_kind(
            caption_langs, lang_code_csv, fallback_lang=app.current_video_language
        )
        if not kind:
            messagebox.showwarning(
                "No captions found",
                "No existing captions were found for this video in the "
                "selected language.",
                parent=app,
            )
            return

        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showwarning(
                "Folder unavailable",
                f"Cannot create or write the download folder:\n{folder}\n\n{e}",
                parent=app,
            )
            return
        app.app_config["download_folder"] = folder
        try:
            save_config(app.app_config)
        except OSError:
            logger.exception("Failed to persist download folder preference")

        title = app.current_video_title or url
        display_lang = (
            sub_lang_name if sub_lang_name and sub_lang_name != "Automatic"
            else (app.current_video_language or "auto")
        )
        task = VideoDownloadTask(
            url, folder, f"Captions only ({display_lang})",
            {"mode": "Captions", "audio": None, "video": None, "output": ""},
            f"{title} (captions only)",
            subtitles_enabled=True,
            subtitle_lang=lang_code_csv,
            detected_language=app.current_video_language,
            caption_only=True,
            caption_kind=kind,
        )
        app.download_queue.append(task)
        app.refresh_download_queue()
        self.process_queue()

    # Driver
    def process_queue(self) -> None:
        app = self.app
        # Don't start a new download once shutdown has begun (Audit P2-5).
        if getattr(app, "_closing", False):
            return
        if app.download_current:
            return
        task = next((t for t in app.download_queue if t.status == "waiting"), None)
        if not task:
            return

        app.download_current = task
        task.status = "running"
        task.progress = 0
        import time as _t  # local to avoid shadow on type-checking

        task.start_time = _t.time()
        # Re-run path: clear a frozen end_time so the counter starts
        # incrementing again for the second attempt.
        task.end_time = None
        app.refresh_download_queue()

        from core._threads import safe_thread
        safe_thread(self._run_task, args=(task,), name="download-task")

    def _run_task(self, task: "VideoDownloadTask") -> None:
        app = self.app
        app.download_events.put(("subtitle_status", task, ""))
        # Per-run generation token. Pause tree-kills the process but the old
        # _run_task daemon keeps draining stdout, then runs its finally:
        # _reap_process(task.process). A resume re-uses the SAME task object
        # and spawns a NEW _run_task that assigns task.process = Popen(...).
        # If the old finally then reads task.process it would see (and
        # tree-kill) the freshly-respawned process — a silently dead resume.
        # Bump + capture a generation so the finally only reaps/nulls when
        # task.process still belongs to THIS run. (Mirrors the per-worker
        # token the transcription side already uses.)
        my_gen = getattr(task, "_run_generation", 0) + 1
        task._run_generation = my_gen  # type: ignore[attr-defined]

        # Phase 3a — record start in history.
        history = getattr(app, "history", None)
        if history is not None:
            try:
                task.history_id = history.insert_download(
                    url=task.url, title=task.title, folder=task.folder,
                    format_label=task.format_label,
                )
            except Exception:  # noqa: BLE001
                task.history_id = 0

        def _finalize_own_process() -> None:
            # Only this run's process may be reaped/nulled. A newer run
            # (resume) has bumped _run_generation; touching its task.process
            # here would kill the just-started download.
            if getattr(task, "_run_generation", my_gen) != my_gen:
                return
            _reap_process(task.process)
            task.process = None

        if getattr(task, "caption_only", False):
            try:
                self.maybe_update_yt_dlp(task)
                self._run_caption_only_task(task)
            except Exception as e:  # noqa: BLE001
                app.download_events.put(("error", task, str(e)))
            finally:
                _finalize_own_process()
            return

        if _is_smtv_task(task):
            try:
                self._run_smtv_task(task)
            except Exception as e:  # noqa: BLE001
                app.download_events.put(("error", task, str(e)))
            finally:
                _finalize_own_process()
            return

        try:
            self.maybe_update_yt_dlp(task)

            if task.subtitles_enabled and not task.cancelled:
                self._subtitle_phase(task)
                if task.cancelled:
                    return

            self._media_phase(task)
        except Exception as e:  # noqa: BLE001
            app.download_events.put(("error", task, str(e)))
        finally:
            _finalize_own_process()

    def _build_smtv_sibling_tasks(
        self,
        episode: smtv_mod.SmtvEpisode,
        *,
        mode: str,
        video_label: str,
        folder: str,
        format_label: str,
        output: str,
    ) -> list["VideoDownloadTask"]:
        """One VideoDownloadTask per sibling part.

        Each sibling page is fetched in this thread (cheap — one HTTP
        GET per part) so the per-task format_info carries the part-
        specific CDN URLs. The current episode is NOT included; the
        caller already enqueued it.
        """
        from app.domain.tasks import VideoDownloadTask

        # Detect chosen mode against the parent episode's format_info
        chosen_mode_video = None
        chosen_mode_audio = None
        if mode == "Audio":
            chosen_mode_audio = "audio"
        else:
            quality_lookup = {
                "HD 1080p": "video-1080",
                "HD 720p":  "video-720",
                "SD 396p":  "video-396",
            }
            chosen_mode_video = quality_lookup.get(video_label, "video-best")

        sibling_tasks: list["VideoDownloadTask"] = []
        for sib in episode.siblings:
            try:
                sib_episode = smtv_mod.fetch_episode(sib.url, timeout=30.0)
            except smtv_mod.SmtvError as e:
                self.app.download_events.put(
                    ("log", None, f"SMTV sibling fetch failed for {sib.url}: {e}")
                )
                continue

            try:
                if chosen_mode_audio:
                    sib_url = smtv_mod.best_url_for_mode(sib_episode, "audio")
                    sib_format = {
                        "mode": "Audio",
                        "audio": {
                            "kind": "smtv", "mode": "audio",
                            "quality": "audio", "url": sib_url,
                        },
                        "video": None,
                        "output": output,
                        "episode": sib_episode,
                    }
                else:
                    sib_url = smtv_mod.best_url_for_mode(sib_episode, chosen_mode_video or "video-best")
                    sib_format = {
                        "mode": "Audio and video",
                        "audio": None,
                        "video": {
                            "kind": "smtv", "mode": chosen_mode_video or "video-best",
                            "quality": chosen_mode_video or "video-best",
                            "url": sib_url,
                        },
                        "output": output,
                        "episode": sib_episode,
                    }
            except smtv_mod.SmtvError as e:
                self.app.download_events.put(
                    ("log", None, f"SMTV sibling mode unavailable for {sib.url}: {e}")
                )
                continue

            sibling_tasks.append(
                VideoDownloadTask(
                    sib.url,
                    folder,
                    f"{format_label} (part {sib.part})" if sib.part else format_label,
                    sib_format,
                    sib_episode.title,
                    subtitles_enabled=False,
                    subtitle_lang="",
                    detected_language=sib_episode.lang_prefix,
                )
            )

        return sibling_tasks

    def _run_smtv_task(self, task: "VideoDownloadTask") -> None:
        """Direct CDN download for an SMTV task, bypassing yt-dlp.

        The format_info dict (built by format_service._apply_smtv_formats
        and ratified by enqueue_from_form) holds the chosen mode and the
        CDN URL. We stream chunks, post progress events into the existing
        download_events queue, atomic-rename .part -> final, and (if the
        episode has an article-text transcript) write <base>.txt
        alongside. On completion we emit done_full so the
        auto-transcribe-after-download wiring works the same way as the
        YouTube flow.
        """
        app = self.app
        info = task.format_info or {}
        chosen = info.get("audio") if info.get("mode") == "Audio" else info.get("video")
        if not isinstance(chosen, dict) or chosen.get("kind") != "smtv":
            raise RuntimeError("SMTV task missing chosen format")
        cdn_url = chosen.get("url")
        if not isinstance(cdn_url, str) or not cdn_url:
            raise RuntimeError("SMTV task missing CDN url")

        # Try to recover the parsed episode (preferred path), else
        # re-fetch on the worker thread. fetch_episode raises on
        # failure, so `episode` is always a real SmtvEpisode after
        # this block.
        cached = info.get("episode")
        if isinstance(cached, smtv_mod.SmtvEpisode):
            episode: smtv_mod.SmtvEpisode = cached
        else:
            episode = smtv_mod.fetch_episode(task.url, timeout=30.0)

        raw_basename = _smtv_basename_from_url(cdn_url)
        if raw_basename:
            # The CDN basename comes from the page's ?file= value, which is
            # attacker-influenceable; an NTFS ADS colon ("a:b") or a Windows
            # reserved device stem (CON/PRN/NUL/COM1...) would otherwise reach
            # os.path.join and yield a zero-byte / redirected file or an
            # OSError on write. Run it through the same sanitiser smtv.py
            # already applies in filename_for()/transcript_filename(), and
            # fall back to a safe default if it sanitises down to nothing.
            basename = smtv_mod._sanitise_filename(raw_basename) or "smtv_episode"
        else:
            # filename_for() already sanitises its CDN/title-derived name.
            basename = smtv_mod.filename_for(
                episode, chosen.get("mode", "video-best")
            )
        target_path = os.path.join(task.folder, basename)
        part_path = target_path + ".part"

        app.download_events.put(
            ("log", task, f"--- SMTV download: {basename} ({cdn_url}) ---")
        )

        try:
            self._stream_smtv_file(task, cdn_url, part_path)
        except Exception:  # noqa: BLE001
            # Whatever went wrong, the partial file is useless to the
            # user — clean it up and re-raise so the caller posts the
            # error event.
            _quiet_unlink(part_path)
            raise

        if task.cancelled:
            _quiet_unlink(part_path)
            app.download_events.put(("done", task, "cancelled"))
            return

        try:
            os.replace(part_path, target_path)
        except OSError as e:
            raise RuntimeError(f"could not finalise download to {target_path}: {e}") from e

        transcript_text = (episode.transcript_text or "").strip()
        if transcript_text:
            transcript_basename = smtv_mod.transcript_filename(episode)
            mode = chosen.get("mode", "")
            if mode.startswith("video"):
                stem, _ = os.path.splitext(basename)
                transcript_basename = stem + ".txt"
            elif mode == "audio":
                stem, _ = os.path.splitext(basename)
                transcript_basename = stem + ".txt"
            transcript_path = os.path.join(task.folder, transcript_basename)
            try:
                with open(transcript_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(transcript_text + "\n")
                app.download_events.put(
                    ("log", task, f"--- SMTV transcript saved: {transcript_basename} ---")
                )
            except OSError as e:
                app.download_events.put(
                    ("log", task, f"transcript write failed for {transcript_basename}: {e}")
                )

        app.download_events.put(
            ("done_full", task, {"status": "finished", "saved_path": target_path})
        )

    def _stream_smtv_file(
        self, task: "VideoDownloadTask", url: str, dest_path: str
    ) -> None:
        """Chunked GET → write to dest_path with progress events.

        Posts ``progress`` events throttled to once per ~500 ms so we
        don't drown the Tk poll loop. Honours ``task.cancelled``.
        """
        app = self.app
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperTranscriberSuite"
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                total = _content_length_or_none(resp)
                downloaded = 0
                last_emit = 0.0
                with open(dest_path, "wb") as out:
                    while True:
                        if task.cancelled:
                            return
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if total and (now - last_emit) >= 0.5:
                            percent = (downloaded / total) * 100.0
                            app.download_events.put(("progress", task, percent))
                            last_emit = now
                if task.cancelled:
                    return
                # A clean EOF before Content-Length bytes have arrived
                # means the CDN dropped the connection mid-transfer — no
                # exception is raised in that case. Treat the partial file
                # as a failed download; otherwise _run_smtv_task renames
                # it to the final name and auto-transcribes a corrupt clip.
                if total is not None and downloaded < total:
                    raise RuntimeError(
                        f"SMTV CDN download truncated: received {downloaded} "
                        f"of {total} bytes"
                    )
                # When the CDN omits Content-Length (chunked transfer) total
                # is None and a connection dropped mid-stream looks like
                # success; and a "Content-Length: 0" error/edge body yields
                # total==0 (falsy), slipping past every `if total` gate and
                # the `0 < 0` truncation check. In both cases a zero-byte
                # file would be finalised as a valid download. Reject it.
                if downloaded == 0:
                    raise RuntimeError(
                        "SMTV CDN download empty: received 0 bytes"
                    )
                app.download_events.put(("progress", task, 100.0))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"SMTV CDN HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"SMTV CDN network error: {e.reason}") from e
        except TimeoutError as e:
            raise RuntimeError("SMTV CDN read timeout") from e

    def _subtitle_phase(self, task: "VideoDownloadTask") -> None:
        app = self.app
        sub_lang = self.resolve_subtitle_lang(task)
        if not sub_lang:
            app.download_events.put(("subtitle_status", task, "no language detected"))
            app.download_events.put(("log", task, "Skipping subtitles: original language could not be detected."))
            return

        app.download_events.put(("subtitle_status", task, f"fetching subtitles ({sub_lang})..."))
        app.download_events.put(("log", task, f"--- Subtitle phase: requesting {sub_lang} ---"))
        task.process = subprocess.Popen(
            self.build_subtitle_command(task, sub_lang),
            cwd=os.path.dirname(os.path.abspath(app.entry_file)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_subprocess_env(),
            # Isolate so a cancel/exit can kill yt-dlp AND its ffmpeg child.
            **new_session_kwargs(),
        )
        wrote_files: list[str] = []
        no_subs_warning = False
        for line in task.process.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if not line:
                continue
            app.download_events.put(("log", task, line))
            if "Writing video subtitles to:" in line:
                wrote_files.append(line.split("Writing video subtitles to:", 1)[1].strip())
            elif (
                "no subtitles for the requested languages" in line.lower()
                or "no automatic captions for the requested languages" in line.lower()
            ):
                no_subs_warning = True
        sub_rc = task.process.wait()
        task.process = None
        if task.cancelled:
            for partial in wrote_files:
                try:
                    if os.path.isfile(partial):
                        os.unlink(partial)
                        app.download_events.put(("log", task, f"Removed partial subtitle file: {partial}"))
                except OSError as e:
                    app.download_events.put(
                        ("log", task, f"Could not remove partial subtitle file {partial}: {e}")
                    )
            app.download_events.put(("subtitle_status", task, "cancelled"))
            app.download_events.put(("done", task, "cancelled"))
            return
        if wrote_files:
            app.download_events.put(
                (
                    "subtitle_status",
                    task,
                    f"✓ saved {len(wrote_files)} subtitle file{'s' if len(wrote_files) != 1 else ''}",
                )
            )
            app.download_events.put(("log", task, f"--- Subtitle phase: wrote {len(wrote_files)} file(s) ---"))
            # Also offer the downloaded auto-subtitle in SMTV / oTranscribe /
            # Express Scribe formats, written alongside the .vtt/.srt. Each
            # format is best-effort (write_subtitle_extra_formats never
            # raises); failures are logged but don't affect the subtitle
            # phase's own success status.
            for sub_file in wrote_files:
                try:
                    extras = write_subtitle_extra_formats(
                        sub_file,
                        language=sub_lang,
                        work_title=os.path.splitext(os.path.basename(sub_file))[0],
                    )
                except Exception as e:  # noqa: BLE001
                    app.download_events.put(
                        ("log", task, f"Extra subtitle formats for {sub_file} failed: {e}")
                    )
                    continue
                for extra in extras:
                    app.download_events.put(("log", task, f"Also wrote: {extra}"))
        elif no_subs_warning:
            app.download_events.put(("subtitle_status", task, "no captions available"))
            app.download_events.put(("log", task, "--- Subtitle phase: no captions available for the requested language ---"))
        elif sub_rc:
            app.download_events.put(("subtitle_status", task, f"failed (rc={sub_rc})"))
            app.download_events.put(
                ("log", task, f"--- Subtitle phase: yt-dlp exit code {sub_rc} (continuing with media) ---")
            )
        else:
            app.download_events.put(("subtitle_status", task, "completed (no files written)"))
            app.download_events.put(("log", task, "--- Subtitle phase: completed without writing files ---"))

    def _run_caption_only_task(self, task: "VideoDownloadTask") -> None:
        """"Use captions instead" shortcut: fetch only the existing captions
        and convert them to the transcript formats chosen in Advanced
        settings ('output_formats'). Never downloads media and never
        queues a transcription -- that's the whole point of the shortcut.

        Reuses the same yt-dlp ``--skip-download --write-subs
        --write-auto-subs`` invocation as :meth:`_subtitle_phase`, but
        (unlike that method, which is a bonus step before a media
        download) this is the task's entire run, so it posts its own
        terminal ``done``/``done_full``/``error`` event instead of falling
        through to a media phase.
        """
        app = self.app
        sub_lang = self.resolve_subtitle_lang(task)
        if not sub_lang:
            app.download_events.put(("subtitle_status", task, "no language detected"))
            app.download_events.put(
                ("error", task, "Could not resolve a caption language for this video.")
            )
            return

        app.download_events.put(("subtitle_status", task, f"fetching captions ({sub_lang})..."))
        app.download_events.put(("log", task, f"--- Caption-only phase: requesting {sub_lang} ---"))
        task.process = subprocess.Popen(
            self.build_subtitle_command(task, sub_lang),
            cwd=os.path.dirname(os.path.abspath(app.entry_file)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_subprocess_env(),
            **new_session_kwargs(),
        )
        wrote_files: list[str] = []
        no_subs_warning = False
        for line in task.process.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if not line:
                continue
            app.download_events.put(("log", task, line))
            if "Writing video subtitles to:" in line:
                wrote_files.append(line.split("Writing video subtitles to:", 1)[1].strip())
            elif (
                "no subtitles for the requested languages" in line.lower()
                or "no automatic captions for the requested languages" in line.lower()
            ):
                no_subs_warning = True
        sub_rc = task.process.wait()
        task.process = None

        if task.cancelled:
            for partial in wrote_files:
                try:
                    if os.path.isfile(partial):
                        os.unlink(partial)
                except OSError:
                    pass
            app.download_events.put(("subtitle_status", task, "cancelled"))
            app.download_events.put(("done", task, "cancelled"))
            return

        if not wrote_files:
            reason = (
                "no captions available" if no_subs_warning
                else f"failed (rc={sub_rc})" if sub_rc
                else "completed (no files written)"
            )
            app.download_events.put(("subtitle_status", task, reason))
            app.download_events.put(
                ("error", task, f"Could not fetch captions for this video: {reason}")
            )
            return

        caption_path = wrote_files[0]
        from core import convert as _convert

        try:
            segments = _convert.parse_to_segments(caption_path)
        except _convert.ConvertError as e:
            app.download_events.put(("subtitle_status", task, "conversion failed"))
            app.download_events.put(
                ("error", task, f"Captions were downloaded but could not be read: {e}")
            )
            return

        # Only auto-generated YouTube captions have the rolling-window
        # duplicate-text artifact; a manual/creator track must not be
        # touched (see core.convert.dedupe_rolling_captions).
        if getattr(task, "caption_kind", "") == "auto":
            segments = _convert.dedupe_rolling_captions(segments)

        wanted_formats = [f for f in (app.app_config.get("output_formats") or ["srt"]) if f]
        convertible = set(_convert.CONVERT_TARGETS)
        written: list[str] = []
        skipped: list[str] = []
        for fmt in wanted_formats:
            fmt_lower = fmt.lower()
            if fmt_lower not in convertible:
                # docx / pdf need extra context convert_file doesn't offer
                # (see its module docstring) -- not available from this
                # shortcut. Not a failure: every other requested format
                # still gets produced.
                skipped.append(fmt_lower)
                continue
            try:
                out_path = _convert.convert_file(caption_path, fmt_lower, segments=segments)
                written.append(out_path)
            except (OSError, _convert.ConvertError) as e:
                app.download_events.put(
                    ("log", task, f"Caption conversion to {fmt_lower} failed: {e}")
                )

        if skipped:
            app.download_events.put((
                "log", task,
                "Skipped for the caption-only shortcut (need a full "
                "transcription run to produce these): " + ", ".join(skipped),
            ))

        if not written:
            app.download_events.put(("subtitle_status", task, "conversion failed"))
            app.download_events.put((
                "error", task,
                "Captions were downloaded but none of the selected output "
                "formats could be produced from them.",
            ))
            return

        app.download_events.put((
            "subtitle_status", task,
            f"captions converted to {len(written)} format{'s' if len(written) != 1 else ''}",
        ))
        app.download_events.put((
            "log", task,
            "--- Caption-only phase: wrote "
            + ", ".join(os.path.basename(w) for w in written) + " ---",
        ))
        app.download_events.put(
            ("done_full", task, {"status": "finished", "saved_path": written[0]})
        )

    def _run_media_process(
        self, task: "VideoDownloadTask", command: list[str]
    ) -> tuple[int, str, str, str | None, bool]:
        """Run one yt-dlp media download to completion.

        Returns ``(return_code, last_error_line, last_line, saved_path,
        saved_is_final)``. Streams progress/log events exactly like before;
        pulled out of ``_media_phase`` so a cookie-extraction failure can
        retry the same download once, without cookies, using this same
        parsing logic.
        """
        app = self.app
        task.process = subprocess.Popen(
            command,
            cwd=os.path.dirname(os.path.abspath(app.entry_file)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_subprocess_env(),
            # Isolate so a cancel/exit can kill yt-dlp AND its ffmpeg merge
            # child (otherwise orphaned, holding the .part/output handle).
            **new_session_kwargs(),
        )

        saved_path: str | None = None
        saved_is_final = False
        last_error_line = ""
        last_line = ""
        for line in task.process.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            parsed = parse_progress_line(line)
            if parsed and "percent" in parsed:
                app.download_events.put(("progress", task, float(parsed["percent"])))
            elif line:
                last_line = line
                # Case-insensitive: yt-dlp emits both "ERROR:" and
                # lowercase "[error]"-style lines depending on the
                # extractor/postprocessor, and an uppercase-only match
                # silently missed the real reason on the latter.
                if "error" in line.lower():
                    last_error_line = line
                dest = parse_destination_line(line)
                if dest is not None:
                    path, is_final = dest
                    # A final (post-processed) path wins and locks; a plain
                    # per-stream fragment never overwrites a final one,
                    # because fragments are deleted during a merge.
                    if is_final or not saved_is_final:
                        saved_path = path
                        saved_is_final = saved_is_final or is_final
                app.download_events.put(("log", task, line))

        return_code = task.process.wait()
        return return_code, last_error_line, last_line, saved_path, saved_is_final

    def _media_phase(self, task: "VideoDownloadTask") -> None:
        app = self.app
        cookies_configured = bool(
            _cookies_from_browser_args(app.app_config.get("cookies_from_browser", ""))
        )

        return_code, last_error_line, last_line, saved_path, _ = (
            self._run_media_process(task, self.build_download_command(task))
        )

        # A cookie-jar read failure (browser still open, locked profile,
        # unsupported keyring, ...) is a LOCAL problem, not the site
        # rejecting the request — most URLs don't need the cookies at all,
        # so retry once without them before giving up. This keeps "Cookies
        # from browser" usable for the sites that actually need it while no
        # longer breaking every other download whenever the browser happens
        # to be open.
        retried_without_cookies = False
        if (
            return_code
            and not task.cancelled
            and not getattr(task, "paused", False)
            and cookies_configured
            and _is_cookie_extraction_error(last_error_line or last_line)
        ):
            retried_without_cookies = True
            app.download_events.put((
                "log", task,
                "--- Could not read cookies from your browser (close it fully "
                "if it's open) — retrying this download without cookies ---",
            ))
            return_code, last_error_line, last_line, saved_path, _ = (
                self._run_media_process(
                    task, self.build_download_command(task, force_no_cookies=True)
                )
            )

        if task.cancelled:
            app.download_events.put(("done", task, "cancelled"))
        elif getattr(task, "paused", False):
            # R2 stop-and-continue "pause": the process was tree-killed by
            # pause_download, so the wait() returns nonzero — but this is a
            # deliberate hold, not a failure. Land on "paused" and keep the
            # partial .part so a later resume continues via -c/--continue.
            app.download_events.put(("done", task, "paused"))
        elif return_code:
            # Surface the real reason (yt-dlp's ERROR line) rather than a
            # bare exit code, so a login-walled site (Facebook → enable
            # "Cookies from browser") or a site-specific failure
            # (Dailymotion HLS) is actually diagnosable from the queue.
            reason = last_error_line or last_line
            msg = f"Download failed (yt-dlp exit code {return_code})"
            if reason:
                msg = f"{msg}: {reason}"
            low = reason.lower()
            if retried_without_cookies:
                msg += (
                    "  — could not read cookies from your browser, and the "
                    "download failed again without them too: this video "
                    "most likely needs a logged-in session. Fully close the "
                    "browser configured under 'Cookies from browser' and "
                    "retry so yt-dlp can read its cookie jar, or the video "
                    "may simply be private."
                )
            # Specific phrases only — bare "age"/"account" matched unrelated
            # errors ("storage", "page", "message").
            elif any(k in low for k in (
                "login", "log in", "sign in", "sign-in", "cookies",
                "private video", "members-only", "age-restrict",
                "age restrict", "this video is private", "confirm your age",
            )):
                msg += (
                    "  — this site likely needs a logged-in session: turn on "
                    "'Cookies from browser' in Advanced settings and retry."
                )
            app.download_events.put(("error", task, msg))
        else:
            payload = {"status": "finished", "saved_path": saved_path}
            app.download_events.put(("done_full", task, payload))

    def poll(self) -> None:
        app = self.app
        # Stop pumping (and re-arming) once shutdown begins so no new
        # download work starts during teardown (Audit P2-5).
        if getattr(app, "_closing", False):
            return
        processed_any = False
        while True:
            try:
                kind, task, payload = app.download_events.get_nowait()
            except Empty:
                break
            processed_any = True

            try:
                self._dispatch_event(app, kind, task, payload)
            except Exception:  # noqa: BLE001
                # One malformed/unexpected event must never wedge the whole
                # download pump -- an uncaught exception here would skip the
                # app.after(300, self.poll) re-arm below and silently stop
                # ALL further download progress/done/error events.
                logger.exception("Download event handling failed for %r", kind)

        if processed_any:
            # Rebuild the Treeview ONCE per tick, after the whole batch is
            # drained -- not once per event. A single active download can
            # emit dozens of progress/log lines per tick; rebuilding the
            # full Treeview that many times in one frame was pure waste.
            # Guarded the same way as _dispatch_event above: a failure here
            # must not skip the re-arm below and wedge the pump.
            try:
                app.refresh_download_queue()
            except Exception:  # noqa: BLE001
                logger.exception("Download queue refresh failed")

        app.after(300, self.poll)

    def _dispatch_event(
        self, app: "App", kind: str, task: "VideoDownloadTask", payload: Any,
    ) -> None:
        """The per-event body of :meth:`poll`, split out so it can be
        wrapped in one try/except there without re-indenting every branch."""
        if kind == "progress":
            # Defensive coercion: a non-numeric / NaN / inf percent
            # (a malformed yt-dlp progress JSON, a future event source)
            # would make int(payload) raise ValueError/OverflowError,
            # which _dispatch_event's caller now catches -- but coerce
            # defensively anyway so a bad payload degrades to 0% instead
            # of being swallowed as a logged, silently-dropped event.
            try:
                pct = float(payload)
            except (TypeError, ValueError):
                pct = 0.0
            if pct != pct or pct in (float("inf"), float("-inf")):
                pct = 0.0
            task.progress = min(100, max(0, int(pct)))
        elif kind == "log":
            app.log(payload)
        elif kind == "subtitle_status":
            app.subtitle_status_var.set(payload)
        elif kind == "done":
            self._finish(task, payload, saved_path=None)
        elif kind == "done_full":
            self._finish(task, payload["status"], saved_path=payload.get("saved_path"))
        elif kind == "error":
            task.status = "error"
            import time as _time
            if getattr(task, "end_time", None) is None:
                try:
                    task.end_time = _time.time()
                except AttributeError:
                    pass
            app.log(payload)
            if app.download_current is task:
                app.download_current = None
            self.process_queue()
        else:
            logger.warning("Unrecognized download event kind: %r", kind)

    def _recover_saved_path(self, task: "VideoDownloadTask", parsed: str | None) -> str | None:
        """Find the file a finished download actually produced on disk.

        saved_path is parsed from yt-dlp stdout and can be wrong (a
        postprocessor rename, or a filename character that slips past the
        utf-8 fix). Downloads run one at a time, so the newest media file in
        the target folder touched since this task started is the real
        output. Returns None when nothing plausible is found.
        """
        folder = getattr(task, "folder", "") or (
            os.path.dirname(parsed) if parsed else ""
        )
        if not folder or not os.path.isdir(folder):
            return None
        media_exts = {
            ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv",
            ".m4a", ".mp3", ".opus", ".aac", ".flac", ".wav", ".ogg",
        }
        started = float(getattr(task, "start_time", None) or 0.0)
        best: tuple[float, str] | None = None
        try:
            names = os.listdir(folder)
        except OSError:
            return None
        for name in names:
            if os.path.splitext(name)[1].lower() not in media_exts:
                continue
            full = os.path.join(folder, name)
            try:
                if not os.path.isfile(full):
                    continue
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            if mtime + 5.0 < started:  # untouched since the download began
                continue
            if best is None or mtime > best[0]:
                best = (mtime, full)
        return best[1] if best else None

    def _finish(self, task: "VideoDownloadTask", status: str, saved_path: str | None) -> None:
        app = self.app
        # Stale-pause guard: a paused task that the user already resumed has
        # been re-dispatched (status running/waiting) and may even be the
        # current download again. The torn-down thread's late "paused" event
        # must not clobber that fresh run back to "paused".
        if status == "paused" and getattr(task, "status", "") in ("running", "waiting"):
            return
        task.status = status
        # Freeze the Elapsed column the moment the task is terminal,
        # regardless of which status it ended in (finished / error /
        # cancelled). Without this, app.fmt_time kept ticking.
        # Defensive getattr — the unit suite passes a SimpleNamespace
        # mock that doesn't carry end_time.
        if getattr(task, "end_time", None) is None:
            import time as _time
            try:
                task.end_time = _time.time()
            except AttributeError:
                pass
        if status == "finished":
            task.progress = 100
            # Self-healing: saved_path is parsed from yt-dlp stdout, which can
            # mismatch the real file (a postprocessor rename, or an exotic
            # filename character that still slips past the utf-8 fix). If the
            # parsed path isn't on disk, fall back to the newest media file the
            # download just produced so the size readout AND auto-transcribe
            # still find it.
            if not saved_path or not os.path.exists(saved_path):
                recovered = self._recover_saved_path(task, saved_path)
                if recovered:
                    if not saved_path or os.path.basename(recovered) != os.path.basename(saved_path):
                        app.log(f"(recovered downloaded file: {os.path.basename(recovered)})")
                    saved_path = recovered
            if saved_path:
                task.saved_path = saved_path
                # Friendly completion line — the user actually wants
                # to know "what file landed, where, how big". Ring
                # the bell so they notice even if they're in another
                # window or scrolling the console.
                try:
                    size = os.path.getsize(saved_path)
                    if size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    elif size < 1024 * 1024 * 1024:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    else:
                        size_str = f"{size / (1024 * 1024 * 1024):.2f} GB"
                except OSError:
                    size_str = "?"
                app.log(
                    f"✓ Downloaded: {os.path.basename(saved_path)} "
                    f"({size_str}) → {os.path.dirname(saved_path) or '.'}"
                )
                if getattr(app, "chime_on_complete_var", None) is not None:
                    try:
                        if app.chime_on_complete_var.get():
                            app.bell()
                    except Exception:  # noqa: BLE001
                        pass
            if (
                app.app_config.get("auto_transcribe_after_download")
                and saved_path
                and not getattr(task, "caption_only", False)
            ):
                try:
                    app.enqueue_transcription_from_download(
                        saved_path, task.detected_language, source_download=task
                    )
                    # Show the download row as "transcribing" so the user
                    # knows work continues after the download — the file is
                    # being transcribed, which can be slow. The app /
                    # finish_task flip it back to "finished" when done.
                    task.status = "transcribing"
                    app.log(f"-> Now transcribing: {os.path.basename(saved_path)}")
                except Exception as e:  # noqa: BLE001
                    app.log(f"Auto-transcribe wiring failed: {e}")
        # Phase 3a — finalise the history row.
        history = getattr(app, "history", None)
        if history is not None and getattr(task, "history_id", 0):
            try:
                history.finish_download(
                    task.history_id,
                    status=status,
                    output_paths=[saved_path] if saved_path else [],
                    detected_language=task.detected_language or "",
                )
            except Exception as e:  # noqa: BLE001
                app.log(f"history record update failed: {e}")
        if app.download_current is task:
            app.download_current = None
        self.process_queue()
