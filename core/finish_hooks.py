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
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

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
# A name is limited in BYTES (Linux allows 255 per name; " (999).md" is added after).
_MAX_STEM_BYTES = 200
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
# Windows also treats COM¹ COM² COM³ (and LPT) as devices.
_SUPERSCRIPT_DIGITS = str.maketrans("¹²³", "123")
# Query parameters that carry a signature, token or password: never copied into a note.
_SECRET_QUERY_NAMES = frozenset({
    "token", "access_token", "id_token", "refresh_token", "auth", "authorization",
    "signature", "sig", "key", "apikey", "api_key", "expires", "expire", "policy",
    "hmac", "secret", "password", "pass", "session", "sessionid", "jwt", "code",
    "se", "sp", "sv", "sr", "st", "skoid", "sktid", "sks", "skv", "spr",
})
_SECRET_QUERY_PREFIXES = ("x-amz-", "x-goog-")
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
    # Whole characters only, and bytes not characters: 100 Persian or Japanese
    # characters are ~300 bytes, over what Linux allows for one name.
    stem = stem.encode("utf-8", "ignore")[:_MAX_STEM_BYTES].decode("utf-8", "ignore")
    stem = stem.strip(" .")
    if not stem:
        return "Transcript"
    device = stem.split(".", 1)[0].rstrip(" ").translate(_SUPERSCRIPT_DIGITS).upper()
    if device in _WINDOWS_RESERVED:
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

# DEL, NEL, LINE SEPARATOR, PARAGRAPH SEPARATOR: line breaks YAML would honour.
_LINE_BREAKS = frozenset(chr(c) for c in (0x7F, 0x85, 0x2028, 0x2029))


def _one_line(value: Any) -> str:
    """Text for a YAML double-quoted scalar: no line breaks, JSON-escaped quotes."""
    text = "".join(
        " " if (ord(c) < 32 or c in _LINE_BREAKS) else c
        for c in str(value or "")
    )
    return json.dumps(text, ensure_ascii=False)


def _is_web(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def clean_source_url(url: str) -> str:
    """The link to show in a note: no password, no fragment, no signed parameters.

    A download link often carries a signature or token in its query (a CDN or
    cloud-storage URL); the note is a file that gets synced and shared, so those
    parameters are dropped. Plain ones (``?v=<video id>``) stay.
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    kept = []
    for item in parts.query.split("&"):
        name = unquote(item.split("=", 1)[0]).lower()
        if not item or name in _SECRET_QUERY_NAMES or name.startswith(_SECRET_QUERY_PREFIXES):
            continue
        kept.append(item)
    return urlunsplit((parts.scheme, netloc, parts.path, "&".join(kept), ""))


def _md_link(url: str) -> str:
    """``[text](target)`` that a ``)`` or space inside the address cannot break."""
    target = url
    for char, code in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("<", "%3C"), (">", "%3E")):
        target = target.replace(char, code)
    label = url.replace("[", "").replace("]", "")
    return f"[{label}]({target})"


def _untimed(segments: list[dict]) -> bool:
    return not any(s.get("start") is not None for s in segments)


def build_note(segments: list[dict], job: FinishedJob) -> str:
    """The note text: YAML front matter, then the Markdown writer's output.

    Segments without a start time (a ``.txt`` or ``.docx`` was the only file
    written) become plain paragraphs: no invented timestamps.
    """
    web = _is_web(job.source)
    source = clean_source_url(job.source) if web else os.path.basename(job.source)
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
    if _untimed(segments):
        heading = md_writer._escape_md_heading(safe_note_stem(job.title))
        paragraphs = [str(s.get("text", "")).strip() for s in segments]
        body = f"# {heading}\n\n" + "\n\n".join(p for p in paragraphs if p) + "\n"
    else:
        body = md_writer.write(segments, audio_path=safe_note_stem(job.title))
    if web and source:
        head, _sep, rest = body.partition("\n\n")
        body = f"{head}\n\n{_md_link(source)}\n\n{rest}"
    return "\n".join(front) + body


_QUOTES = "\"'\u201c\u201d\u2018\u2019"


def strip_path_quotes(raw: str | None) -> str:
    """The text of a pasted folder path without spaces or surrounding quotes."""
    text = (raw or "").strip()
    while len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text


def resolve_vault_dir(raw: str | None) -> str | None:
    """The absolute vault folder to use for a typed or pasted value, else None.

    Surrounding quotes (Explorer's "Copy as path") are removed and ``~`` is
    expanded. A relative path is refused with a log line: it would depend on
    whatever folder the app happened to start in.
    """
    text = strip_path_quotes(raw)
    if not text:
        return None
    path = os.path.expanduser(text)
    if not os.path.isabs(path):
        logger.warning("Obsidian note not written: the vault folder must be an "
                       "absolute path (for example C:\\Notes or ~/Notes)")
        return None
    return os.path.normpath(path)


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
        # File names only: a full path would carry the user's Windows account name.
        "outputs": [re.split(r"[\\/]", str(p))[-1] for p in job.output_paths],
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
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                # The receiver got the POST; following a redirect would send it
                # again (and could leave the host we were told to use).
                logger.info("finish webhook to %s answered with a redirect (%d); "
                            "counted as delivered, not followed", _origin(url), exc.code)
                return True
            logger.warning("finish webhook to %s was answered with HTTP %d",
                           _origin(url), exc.code)
            if exc.code < 500:
                return False  # the receiver refused it: a second try changes nothing
        except Exception as exc:  # noqa: BLE001 - a hand-off never breaks the job
            logger.warning("finish webhook to %s failed (try %d of 2): %s",
                           _origin(url), attempt, type(exc).__name__)
        if attempt == 1:
            sleep(WEBHOOK_RETRY_DELAY_S)
    return False


# --- entry points ------------------------------------------------------------

def load_segments(output_paths: list[str]) -> list[dict]:
    """The segments of the written transcript, read back from the output files.

    The transcription runs in a worker process and its "done" message carries no
    text, so the files are the source. The JSON first, then any other format
    ``core.convert`` reads (SRT, VTT, TSV ...), then this app's own Markdown and
    LRC files (timestamps kept), then plain ``.txt`` and ``.docx`` (no times: the
    segments have no ``start``). A PDF or HTML file is not read.
    """
    order = {ext: i for i, ext in enumerate(_READ_ORDER)}
    candidates = []
    for path in output_paths:
        if not isinstance(path, str) or not os.path.isfile(path):
            continue
        low = path.lower()
        ext = os.path.splitext(low)[1]
        if low.endswith(".chapters.json") or ext not in order:
            continue
        candidates.append((order[ext], path))
    for _rank, path in sorted(candidates):
        try:
            segments = _read_segments(path)
        except Exception:  # noqa: BLE001 - try the next written format
            continue
        if segments:
            return [s for s in segments if isinstance(s, dict)]
    return []


_READ_ORDER = (".json", ".srt", ".vtt", ".tsv", ".ass", ".ssa", ".eaf", ".inqscr",
               ".otr", ".md", ".lrc", ".txt", ".docx")
_MD_LINE = re.compile(r"^\*\*(\d+):(\d\d):(\d\d)\*\*\s+(?:_(.+?):_\s+)?(.*\S)\s*$")
_LRC_LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*\S)\s*$")


def _read_segments(path: str) -> list[dict]:
    ext = os.path.splitext(path.lower())[1]
    if ext == ".md":
        out = []
        for line in _read_lines(path):
            m = _MD_LINE.match(line)
            if m:
                h, mi, s, speaker, text = m.groups()
                seg = {"start": int(h) * 3600 + int(mi) * 60 + int(s), "text": text}
                if speaker:
                    seg["speaker"] = speaker
                out.append(seg)
        return out
    if ext == ".lrc":
        out = []
        for line in _read_lines(path):
            m = _LRC_LINE.match(line)
            if m:
                out.append({"start": int(m.group(1)) * 60 + float(m.group(2)),
                            "text": m.group(3)})
        return out
    if ext == ".txt":
        return [{"text": ln.strip()} for ln in _read_lines(path) if ln.strip()]
    if ext == ".docx":
        import docx  # python-docx: the same package the DOCX writer uses

        return [{"text": p.text.strip()} for p in docx.Document(path).paragraphs
                if p.text.strip()]
    from core import convert

    return convert.parse_to_segments(path)


def _read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        return handle.read().splitlines()


def deliver(config: Mapping[str, Any], job: FinishedJob) -> None:
    """Run the configured hand-offs for a FINISHED job. Never raises."""
    try:
        if job.status != "finished":
            return
        raw_vault = strip_path_quotes(str(config.get("obsidian_vault_dir") or ""))
        url = str(config.get("finish_webhook_url") or "").strip()
        if not raw_vault and not url:
            return
        vault = resolve_vault_dir(raw_vault) if raw_vault else None
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
                    kinds = sorted({os.path.splitext(str(p))[1].lower() or "?"
                                    for p in job.output_paths})
                    logger.info("Obsidian note skipped: no readable transcript among "
                                "the written files (%s)", ", ".join(kinds) or "none")
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
