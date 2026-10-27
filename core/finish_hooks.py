"""What the desktop app does AFTER a transcription finished and its files are saved.

Two optional hand-offs, both off until the user sets them in Advanced:

* **Obsidian note** (``obsidian_vault_dir``): the transcript is copied as a Markdown
  note (YAML front matter, then the existing Markdown writer's timestamped lines)
  into a vault folder. A note is never overwritten: a taken name gets a number.
* **Finish webhook** (``finish_webhook_url``): a small JSON POST (no transcript text
  unless ``finish_webhook_include_text``) with an optional secret header.

Everything here runs after the output files, the history row and the result card
exist ("save first, report second"), on a daemon thread, and never raises: a failed
hand-off is logged and the job stays finished. Work offline blocks the webhook
(the note is a local file, so it is not blocked).

The server has its own completion webhook (``core.server.jobs``) for its API jobs;
this one is for jobs started in the desktop window. It shares the secret rules
(``core.config.webhook_secret_valid``) and the header name, but allows a
``localhost`` receiver, which the server's SSRF guard refuses by design.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from core import offline
from core.config import webhook_secret_valid
from core.writers import md as md_writer
from core.writers.base import fmt_srt_time

logger = logging.getLogger(__name__)

#: Same header name as the server's webhook (a test pins them together).
WEBHOOK_HEADER = "X-Whisper-Webhook-Secret"
WEBHOOK_TIMEOUT_S = 10.0
WEBHOOK_RETRY_DELAY_S = 2.0
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_STEM = 100
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_ILLEGAL = set('<>:"/\\|?*')


@dataclass
class FinishedJob:
    """The facts about one finished transcription that the hand-offs need."""

    job_id: str
    title: str
    source: str
    status: str
    language: str = ""
    model: str = ""
    duration: float = 0.0
    output_paths: list[str] = field(default_factory=list)
    finished_at: float = 0.0


# --- file names --------------------------------------------------------------

def safe_note_stem(title: str) -> str:
    """A file name stem that is legal on Windows, macOS and Linux.

    Drops ``<>:"/\\|?*`` and control characters, trims trailing dots and spaces,
    prefixes ``_`` to a Windows device name (``CON``, ``COM1.txt`` ...), limits
    the length, and falls back to ``Transcript``.
    """
    out: list[str] = []
    for ch in str(title or ""):
        if ch in _ILLEGAL:
            continue
        if ch in "\t\r\n":
            out.append(" ")
        elif ord(ch) < 32 or ord(ch) == 127:
            continue
        else:
            out.append(ch)
    stem = "".join(out).strip(" .")
    stem = stem[:_MAX_STEM].strip(" .")
    if not stem:
        return "Transcript"
    if stem.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        stem = "_" + stem
    return stem


def unique_note_path(folder: str, stem: str) -> str:
    """``<folder>/<stem>.md``, else ``<stem> (1).md``, ``(2)`` ... the first free name."""
    path = os.path.join(folder, f"{stem}.md")
    n = 0
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{stem} ({n}).md")
    return path


# --- the Obsidian note -------------------------------------------------------

def _one_line(value: Any) -> str:
    """Text for a YAML double-quoted scalar: no line breaks, JSON-escaped quotes."""
    text = "".join(
        " " if (ord(c) < 32 or c in "\x7f  \x85") else c
        for c in str(value or "")
    )
    return json.dumps(text, ensure_ascii=False)


def _is_web(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def build_note(segments: list[dict], job: FinishedJob) -> str:
    """The note text: YAML front matter, then the Markdown writer's output."""
    source = job.source if _is_web(job.source) else os.path.basename(job.source)
    when = datetime.fromtimestamp(job.finished_at or time.time())
    front = [
        "---",
        f"title: {_one_line(job.title)}",
        f"source: {_one_line(source)}",
        f"date: {when.strftime('%Y-%m-%d')}",
        f"language: {_one_line(job.language)}",
        f"model: {_one_line(job.model)}",
        f"duration: {fmt_srt_time(job.duration).split(',')[0]}",
        "tags: [transcript]",
        "---",
        "",
    ]
    body = md_writer.write(segments, audio_path=safe_note_stem(job.title))
    if _is_web(job.source):
        head, _sep, rest = body.partition("\n\n")
        body = f"{head}\n\n[{job.source}]({job.source})\n\n{rest}"
    return "\n".join(front) + body


def write_obsidian_note(
    vault_dir: str, job: FinishedJob, segments: list[dict],
) -> str | None:
    """Write the note into an EXISTING vault folder; the path, or None.

    The folder is never created (a typo must not make a stray folder), and a
    file that exists is never touched: the note is created exclusively and a
    taken name moves on to ``Title (1).md``.
    """
    if not vault_dir or not os.path.isdir(vault_dir):
        logger.warning("Obsidian note not written: the vault folder does not exist")
        return None
    text = build_note(segments, job)
    stem = safe_note_stem(job.title)
    path = unique_note_path(vault_dir, stem)
    for _attempt in range(1000):
        try:
            handle = open(path, "x", encoding="utf-8", newline="\n")
        except FileExistsError:  # created between the check and the open
            path = unique_note_path(vault_dir, stem)
            continue
        try:
            with handle:
                handle.write(text)
        except BaseException:
            try:
                os.unlink(path)  # only the file this call just created
            except OSError:
                pass
            raise
        return path
    return None


# --- the webhook -------------------------------------------------------------

def webhook_url_allowed(url: str) -> bool:
    """https to any host, or http only to this computer."""
    try:
        parts = urlsplit((url or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and host in _LOCAL_HOSTS


def _origin(url: str) -> str:
    """Scheme and host only: a webhook URL often carries a secret in its path."""
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.hostname or '?'}"
    except ValueError:
        return "?"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        return None


def _default_opener(request: urllib.request.Request, timeout: float) -> None:
    handlers: list[Any] = [_NoRedirect()]
    host = (urlsplit(request.full_url).hostname or "").lower()
    if host in _LOCAL_HOSTS:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as resp:
        resp.read(_MAX_RESPONSE_BYTES)


def _transcript_text(segments: list[dict]) -> str:
    return "\n".join(
        str(s.get("text", "")).strip() for s in segments if str(s.get("text", "")).strip()
    )


def webhook_payload(
    job: FinishedJob, *, include_text: bool, segments: list[dict],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "job.finished",
        "delivery_id": uuid.uuid4().hex,
        "job_id": job.job_id,
        "title": job.title,
        "status": job.status,
        "language": job.language,
        "duration_seconds": job.duration,
        "outputs": list(job.output_paths),
        "finished_at": job.finished_at,
    }
    if include_text:
        payload["transcript"] = _transcript_text(segments)
    return payload


def send_webhook(
    url: str,
    job: FinishedJob,
    *,
    secret: str,
    include_text: bool,
    segments: list[dict],
    timeout: float = WEBHOOK_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] | None = None,
) -> bool:
    """POST the payload; one retry after a short pause. True when delivered.

    Never raises. Refused (False, nothing sent): Work offline, a URL that is not
    https or this computer, a secret that cannot be an HTTP header value.
    """
    url = (url or "").strip()
    if offline.is_offline():
        offline.skipped("the finish webhook")
        logger.info("finish webhook not sent (Work offline is on)")
        return False
    if not webhook_url_allowed(url):
        logger.warning("finish webhook refused: %s is not https or this computer",
                       _origin(url))
        return False
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "WhisperTranscriberSuite",
    }
    if secret:
        if not webhook_secret_valid(secret):
            logger.warning("finish webhook not sent: the secret cannot be used "
                           "as an HTTP header value")
            return False
        headers[WEBHOOK_HEADER] = secret
    send = opener or _default_opener
    body = json.dumps(
        webhook_payload(job, include_text=include_text, segments=segments)
    ).encode("utf-8")
    for attempt in (1, 2):
        try:
            request = urllib.request.Request(url, data=body, method="POST",
                                             headers=headers)
            send(request, timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - a hand-off never breaks the job
            logger.warning("finish webhook to %s failed (try %d of 2): %s",
                           _origin(url), attempt, type(exc).__name__)
            if attempt == 1:
                sleep(WEBHOOK_RETRY_DELAY_S)
    return False


# --- entry points ------------------------------------------------------------

def load_segments(output_paths: list[str]) -> list[dict]:
    """The segments of the written transcript: the JSON, else any readable format."""
    from core import convert

    paths = [p for p in output_paths if isinstance(p, str) and os.path.isfile(p)]

    def _rank(p: str) -> int:
        low = p.lower()
        if low.endswith(".chapters.json"):
            return 9
        return 0 if low.endswith(".json") else 1

    for path in sorted(paths, key=_rank):
        if _rank(path) == 9:
            continue
        try:
            segments = convert.parse_to_segments(path)
        except Exception:  # noqa: BLE001 - try the next written format
            continue
        if segments:
            return [s for s in segments if isinstance(s, dict)]
    return []


def deliver(config: Mapping[str, Any], job: FinishedJob) -> None:
    """Run the configured hand-offs for a FINISHED job. Never raises."""
    try:
        if job.status != "finished":
            return
        vault = str(config.get("obsidian_vault_dir") or "").strip()
        url = str(config.get("finish_webhook_url") or "").strip()
        if not vault and not url:
            return
        include_text = bool(config.get("finish_webhook_include_text"))
        segments: list[dict] = []
        if vault or (url and include_text):
            try:
                segments = load_segments(job.output_paths)
            except Exception:  # noqa: BLE001
                logger.exception("finish hand-offs: could not read the transcript")
        if vault:
            try:
                if segments:
                    path = write_obsidian_note(vault, job, segments)
                    if path:
                        logger.info("Obsidian note written: %s", path)
                else:
                    logger.info("Obsidian note skipped: the transcript has no text")
            except Exception:  # noqa: BLE001
                logger.exception("Obsidian note failed")
        if url:
            try:
                send_webhook(
                    url, job,
                    secret=str(config.get("finish_webhook_secret") or ""),
                    include_text=include_text, segments=segments,
                )
            except Exception:  # noqa: BLE001
                logger.exception("finish webhook to %s failed", _origin(url))
    except Exception:  # noqa: BLE001 - the job is already saved and reported
        logger.exception("finish hand-offs failed")


def deliver_async(config: Mapping[str, Any], job: FinishedJob) -> threading.Thread | None:
    """:func:`deliver` on a daemon thread (a slow receiver never holds the UI)."""
    snapshot = dict(config)
    thread = threading.Thread(
        target=deliver, args=(snapshot, job), name="finish-hooks", daemon=True)
    try:
        thread.start()
    except Exception:  # noqa: BLE001 - out of OS threads: lose the hand-off, keep the job
        logger.exception("could not start the finish-hooks thread")
        return None
    return thread
