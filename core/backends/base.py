"""Backend interface for transcription engines."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class LanguageInfo:
    """Detected-language metadata returned by every backend.

    Mirrors the relevant ``faster_whisper`` ``info`` fields without
    forcing the rest of the pipeline to import faster_whisper just
    to look at language results.
    """
    language: str = ""
    probability: float = 0.0


class Backend(ABC):
    """Abstract transcription backend.

    Implementations track their own model state (whether the model
    is loaded, what device it's running on, etc.). The transcriber
    dispatcher creates one backend per worker process at module
    import time and keeps it alive for the worker's lifetime.
    """

    name: str = ""

    @abstractmethod
    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Load the model into memory. Returns True on success."""

    @abstractmethod
    def is_ready(self) -> bool:
        """True iff the model is loaded and ready to transcribe."""

    @abstractmethod
    def transcribe_to_segments(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        want_words: bool = False,
        vad_parameters: dict[str, Any] | None = None,
        initial_prompt: str | None = None,
        hotwords: str | None = None,
        batch_size: int = 16,
        progress_cb: Callable[[int], None] | None = None,
        log_cb: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        paused: Callable[[], bool] | None = None,
        duration: float = 0.0,
    ) -> tuple[list[dict[str, Any]], LanguageInfo]:
        """Transcribe one audio file.

        Returns a tuple of (segments_data, language_info), where each
        segment dict has at minimum ``start``, ``end``, ``text`` and,
        when ``want_words`` is True, a ``words`` list of
        ``{start, end, word, probability}`` dicts.
        """

    def unload(self) -> None:
        """Release the model. Default impl is a no-op for backends
        that rely on Python GC."""
        return None

    def get_error(self) -> str | None:
        """Optional last-error message exposed to the UI."""
        return None


# ---------------------------------------------------------------- cloud helpers
# Shared by the paid cloud engines (Gemini, Google Cloud): a chunk request that
# hits a rate limit or a flaky connection is tried again, and a run that dies
# after some chunks keeps what was already paid for.

# Waits before the 2nd, 3rd and 4th try of one chunk request.
RETRY_DELAYS_S: tuple[float, ...] = (3.0, 10.0, 30.0)
MAX_RETRY_AFTER_S = 60.0
_RETRYABLE_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})
# Google client-library error classes (matched by name: the library is optional).
_RETRYABLE_GOOGLE_NAMES = frozenset({
    "ResourceExhausted", "TooManyRequests", "ServiceUnavailable",
    "DeadlineExceeded", "GatewayTimeout", "InternalServerError", "BadGateway",
    "Aborted",
})


class PartialResultError(RuntimeError):
    """A cloud run failed after some chunks were transcribed (and paid for).

    ``segments`` are those finished chunks on the original timeline; the
    transcriber saves them as a resume checkpoint before the error is reported.
    """

    def __init__(self, message: str, segments: list[dict[str, Any]],
                 language: str = "") -> None:
        super().__init__(message)
        self.segments = segments
        self.language = language


def _error_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(chain) < 8:
        chain.append(cur)
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return chain


def is_transient_error(exc: BaseException) -> bool:
    """True for failures a retry can fix: rate limit, 5xx, timeout, reset.

    Never for a bad request or an invalid key (HTTP 400/401/403/404): those
    would fail the same way again and a retry only wastes time (and money).
    """
    import http.client
    import urllib.error

    for err in _error_chain(exc):
        if isinstance(err, urllib.error.HTTPError):
            return err.code in _RETRYABLE_HTTP
        if type(err).__name__ in _RETRYABLE_GOOGLE_NAMES:
            return True
        code = getattr(err, "code", None)
        if isinstance(code, int) and not isinstance(err, OSError):
            if code in _RETRYABLE_HTTP:
                return True
        if isinstance(err, urllib.error.URLError):
            reason = err.reason
            if isinstance(reason, (TimeoutError, ConnectionResetError,
                                   ConnectionAbortedError)):
                return True
            continue
        if isinstance(err, (TimeoutError, ConnectionError,
                            http.client.HTTPException)):
            return True
    return False


def _retry_after(exc: BaseException) -> float:
    import urllib.error

    for err in _error_chain(exc):
        if isinstance(err, urllib.error.HTTPError):
            try:
                value = float((err.headers.get("Retry-After") or "").strip())
            except (AttributeError, TypeError, ValueError):
                return 0.0
            return max(0.0, min(value, MAX_RETRY_AFTER_S))
    return 0.0


def call_with_retries(
    fn: Callable[[], Any],
    *,
    label: str,
    cancelled: Callable[[], bool] | None = None,
    log_cb: Callable[[str], None] | None = None,
    delays: tuple[float, ...] | None = None,
) -> Any:
    """Run ``fn``; on a transient failure wait (backoff) and try again.

    After the last try, or on a failure that is not transient, the error is
    raised unchanged. The wait ends early when ``cancelled()`` turns true,
    which also raises the last error (the caller then sees the Stop).
    """
    import time

    waits = RETRY_DELAYS_S if delays is None else delays
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt >= len(waits) or not is_transient_error(exc):
                raise
            if cancelled is not None and cancelled():
                raise
            wait = _retry_after(exc) or waits[attempt]
            attempt += 1
            if log_cb:
                log_cb(
                    f"{label}: temporary problem ({type(exc).__name__}); "
                    f"trying again in {wait:.0f} s "
                    f"(retry {attempt}/{len(waits)})."
                )
            end = time.monotonic() + wait
            while time.monotonic() < end:
                if cancelled is not None and cancelled():
                    raise
                time.sleep(min(0.25, max(0.0, end - time.monotonic())))
