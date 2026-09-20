"""LLM panel — local Qwen2.5-1.5B-Instruct, or a remote OpenAI-compatible
endpoint the user points at themselves.

The AI Layer (v0.8 Phase 2) provides post-processing of a finished
transcript, from either provider:

  * **Summarise**  — bullet-point digest of the conversation.
  * **Action items** — extracted as a JSON list (best-effort parse of
    the model's response).
  * **Ask question** — single-turn Q&A scoped to the transcript.
  * **Translate**  — language-pair translation through the LLM, so
    we don't need a separate NLLB model.

Two providers, chosen via ``config["llm_provider"]`` ("local" is the
default):

  * :class:`LLMRunner` — Qwen2.5-1.5B-Instruct via llama-cpp-python,
    **download-on-first-use**, NOT bundled. Qwen2.5-1.5B Q4_K_M is
    ~1 GB; bundling pushes Portable from 450 MB → 1.45 GB. Instead
    a one-click "Enable AI features" button downloads the model
    into ``user_cache_dir()/llm/``. The wizard reports
    :func:`is_model_present` so the UI can show "Install AI model"
    vs "Ready" states. **Lazy import** of llama-cpp-python so the
    module is safe to import even when the optional dep isn't
    installed. **Singleton model** — keeps one llama_cpp.Llama
    instance to avoid the multi-second reload cost on every call.
  * :class:`RemoteLLMRunner` — any OpenAI-compatible
    ``/chat/completions`` endpoint the user configures with their own
    base URL, model name, and API key (the real OpenAI API, or a
    self-hosted server such as Ollama/LM Studio/vLLM, or a third-party
    proxy like OpenRouter). No local model, no extra dependency —
    every call is one ``urllib.request`` HTTP round trip.

:func:`build_runner_from_config` picks the configured provider so
callers (the auto-chapter titler, the transcript viewer's AI panel)
don't need to know which one is active — both expose the same 4-method
surface.

When neither provider is available/configured, every public function
either returns ``None`` / raises :class:`LLMUnavailable` /
:class:`RemoteLLMError` so the UI can swap to a "feature off"
placeholder. No silent partial work.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ._gc_import_guard import gc_disabled_import
from .config import user_cache_dir

logger = logging.getLogger(__name__)


DEFAULT_MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/"
    "resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
DEFAULT_MODEL_SIZE_BYTES = 1_117_000_000  # ~1.04 GB; tolerance check only


# ---------------------------------------------------------------- availability


class LLMUnavailable(RuntimeError):
    """Raised when llama-cpp-python isn't installed."""


def runtime_available() -> bool:
    """True iff llama-cpp-python imports cleanly.

    llama-cpp-python wraps native ggml bindings, a heavy C-extension
    package -- see core/_gc_import_guard.py for why the import runs
    under a shared, process-wide GC-disable guard.
    """
    with gc_disabled_import():
        try:
            import llama_cpp  # type: ignore[import-not-found] # noqa: F401
        except ImportError:
            return False
        else:
            return True


def runtime_availability_reason() -> str:
    if runtime_available():
        return ""
    return (
        "llama-cpp-python not installed — `pip install llama-cpp-python` "
        "to enable AI features."
    )


# ---------------------------------------------------------------- model file


def model_dir() -> Path:
    return user_cache_dir() / "llm"


def default_model_path() -> Path:
    return model_dir() / DEFAULT_MODEL_NAME


def is_model_present(path: Path | None = None) -> bool:
    """True iff the model file exists and looks sane (≥ 100 MB)."""
    p = path if path is not None else default_model_path()
    if not p.exists():
        return False
    try:
        return p.stat().st_size > 100_000_000
    except OSError:
        return False


def download_default_model(
    *,
    log: Callable[[str], None] | None = None,
    url: str = DEFAULT_MODEL_URL,
    dest: Path | None = None,
    chunk_size: int = 1 << 20,
    cancel_event: threading.Event | None = None,
) -> str:
    """Download the LLM model to ``model_dir()`` atomically.

    Writes to ``<dest>.part`` and ``os.replace``s on success so a
    partial download (network drop, user-cancel) never leaves the
    user with a half-broken model file. Returns the absolute path.

    Idempotent: a full pre-existing file is detected via size sanity
    check and skipped.
    """
    dest = dest if dest is not None else default_model_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_model_present(dest):
        if log:
            log(f"LLM model already present at {dest}")
        return str(dest)
    part = dest.with_suffix(dest.suffix + ".part")
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass
    if log:
        log(f"Downloading LLM model from {url} → {dest} (~1 GB)…")
    req = urllib.request.Request(url, headers={"User-Agent": "WhisperTranscriberSuite/0.8"})
    started = time.time()
    bytes_done = 0
    cancelled = False
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("content-length") or 0)
            with open(part, "wb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        break
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_done += len(chunk)
                    if log and total:
                        pct = int(bytes_done / total * 100)
                        if pct % 5 == 0:
                            log(f"  …{pct}% ({bytes_done/1e9:.2f} / {total/1e9:.2f} GB)")
    except Exception:
        # File handle now closed by `with`; safe to unlink the
        # partial download before re-raising. Windows in particular
        # refuses os.unlink on a handle that's still open, so we
        # MUST exit the with-block first.
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    if cancelled:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise RuntimeError("LLM download cancelled")
    os.replace(part, dest)
    if log:
        elapsed = time.time() - started
        log(f"LLM model ready at {dest} (in {elapsed:.1f}s)")
    return str(dest)


# ---------------------------------------------------------------- runner


@dataclass
class LLMConfig:
    model_path: str
    n_ctx: int = 4096
    n_threads: int = 0  # 0 means default = os.cpu_count()
    n_gpu_layers: int = 0  # CPU-only by default; user can boost
    seed: int = 42


# ---------------------------------------------------------------- prompts
#
# Shared between LLMRunner and RemoteLLMRunner so the two providers ask
# the model the same question — only the transport (_chat) differs.


def _summarise_prompt(text: str, max_bullets: int) -> str:
    return (
        f"Summarise the following transcript in at most {max_bullets} "
        "concise bullet points. Keep proper names and technical terms "
        "verbatim. Do not invent details that aren't in the source.\n\n"
        f"Transcript:\n\"\"\"\n{text}\n\"\"\""
    )


def _action_items_prompt(text: str) -> str:
    return (
        "Extract the actionable to-do items from this transcript. "
        "Respond ONLY with a JSON array of strings. If there are "
        "no actions, respond with []. Do not include any prose.\n\n"
        f"Transcript:\n\"\"\"\n{text}\n\"\"\""
    )


def _ask_prompt(text: str, question: str) -> str:
    return (
        "Answer the question using ONLY information from the transcript "
        "below. If the answer isn't in the transcript, say "
        "\"Not in transcript.\"\n\n"
        f"Transcript:\n\"\"\"\n{text}\n\"\"\"\n\n"
        f"Question: {question}"
    )


def _translate_prompt(text: str, target_language: str) -> str:
    return (
        f"Translate the following text into {target_language}. "
        "Preserve proper names and technical terms verbatim. "
        "Respond with only the translation, no explanations.\n\n"
        f"\"\"\"\n{text}\n\"\"\""
    )


#: Matching quote-mark pairs some models wrap a short translation in
#: despite being told "respond with only the translation" — observed
#: with the local Qwen2.5-1.5B model on single-sentence/segment inputs
#: (2026-08-16 real-hardware test: 2 of 4 segments in a bilingual-subtitle
#: pass came back as e.g. '"D\'accord, on va passer..."'). A full
#: multi-sentence transcript translation was never observed doing this —
#: only short, single-segment ones — which tracks with a small model
#: pattern-matching "short quoted-looking input" to "wrap the output the
#: same way".
_WRAPPING_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"))


def _strip_wrapped_quotes(text: str) -> str:
    """Strip ONE matching layer of leading+trailing quote marks.

    Only strips when the first and last characters form one of
    ``_WRAPPING_QUOTE_PAIRS`` — a translation that legitimately starts
    with a quoted phrase (mismatched or single-sided punctuation) is
    left untouched rather than mangled.
    """
    t = text.strip()
    if len(t) < 2:
        return t
    for open_q, close_q in _WRAPPING_QUOTE_PAIRS:
        if t[0] == open_q and t[-1] == close_q:
            return t[1:-1].strip()
    return t


# ---------------------------------------------------------------- context fitting
#
# The local model is loaded with a fixed ``n_ctx`` (4096 by default) and
# llama-cpp-python raises ``ValueError`` *before decoding* once the
# rendered prompt reaches that many tokens. The transcript viewer feeds
# whole transcripts to ``summarise`` / ``action_items`` / ``ask`` /
# ``translate``, so anything longer than a few thousand words used to
# fail with a raw "Requested tokens ... exceed context window" error
# instead of a result. Fit the request to the window instead: trim an
# oversized prompt and never let prompt + answer exceed ``n_ctx``.

#: Slice of ``n_ctx`` charged to the chat template + special tokens.
_CONTEXT_OVERHEAD_TOKENS = 64
#: How many tokens each message costs the chat template itself.
_PER_MESSAGE_OVERHEAD_TOKENS = 4
#: Fallback chars-per-token ratio when the loaded model exposes no
#: usable ``tokenize``. English runs ~4 chars/token; 3 keeps the
#: estimate on the safe side for other scripts.
_CHARS_PER_TOKEN = 3
#: Inserted where an over-long prompt was cut apart.
_TRUNCATION_MARKER = " […truncated to fit the model's context window…] "


def _token_counter(llama: Any) -> Callable[[str], int]:
    """Return an exact token counter for a loaded model, else an estimate.

    Prefers the model's own tokenizer — correct for CJK and other
    scripts where a chars-per-token estimate is badly wrong — and falls
    back to a conservative character ratio if the loaded object does
    not expose a usable ``tokenize``. Never raises.
    """
    tokenize = getattr(llama, "tokenize", None)
    if callable(tokenize):
        def _count(text: str) -> int:
            try:
                tokens: Any = tokenize(text.encode("utf-8"), add_bos=False)
                return len(tokens)
            except Exception:  # noqa: BLE001 — counting must never break a call
                return max(1, len(text) // _CHARS_PER_TOKEN)
        return _count
    return lambda text: max(1, len(text) // _CHARS_PER_TOKEN)


def _truncate_middle(text: str, keep_chars: int) -> str:
    """Keep ``keep_chars`` characters from the head and tail of ``text``.

    The middle-ellipsis shape is deliberate: an ``ask`` prompt ends with
    the user's question and the transcript starts the text, so cutting
    only the middle preserves both.
    """
    if keep_chars >= len(text):
        return text
    if keep_chars <= len(_TRUNCATION_MARKER):
        return text[:keep_chars]
    remaining = keep_chars - len(_TRUNCATION_MARKER)
    head = remaining // 2
    return text[:head] + _TRUNCATION_MARKER + text[len(text) - (remaining - head):]


def _shrink_to_tokens(
    text: str, allowed_tokens: int, count_tokens: Callable[[str], int]
) -> str:
    """Trim ``text`` (head + tail) until ``count_tokens`` says it fits."""
    if allowed_tokens <= 0:
        return ""
    if count_tokens(text) <= allowed_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if count_tokens(_truncate_middle(text, mid)) <= allowed_tokens:
            low = mid
        else:
            high = mid - 1
    return _truncate_middle(text, low)


def _fit_messages_to_context(
    messages: list[dict[str, str]],
    max_tokens: int,
    n_ctx: int,
    count_tokens: Callable[[str], int],
) -> tuple[list[dict[str, str]], int]:
    """Clamp one chat request so prompt + answer fit inside ``n_ctx``.

    Only the longest message (the transcript) is shrunk, and any room
    freed by that shrink is handed to the answer. Returns a new message
    list plus the output-token cap to pass to the model.
    """
    n_ctx = max(1, int(n_ctx))
    budget = max(128, n_ctx - _CONTEXT_OVERHEAD_TOKENS)
    contents = [str(m.get("content") or "") for m in messages]
    overhead = _PER_MESSAGE_OVERHEAD_TOKENS * len(messages)
    counts = [count_tokens(c) for c in contents]
    # Cap the answer to half the window first, so a long transcript still
    # gets the other half instead of the request failing outright.
    output_tokens = max(1, min(int(max_tokens), max(1, budget // 2)))
    prompt_budget = max(1, budget - output_tokens)
    total = sum(counts)
    if total + overhead > prompt_budget:
        longest = max(range(len(contents)), key=lambda i: counts[i])
        allowed = prompt_budget - overhead - (total - counts[longest])
        before = counts[longest]
        contents[longest] = _shrink_to_tokens(
            contents[longest], max(1, allowed), count_tokens
        )
        counts[longest] = count_tokens(contents[longest])
        logger.warning(
            "Prompt exceeds the model's %d-token context window; "
            "truncated the transcript from %d to %d tokens.",
            n_ctx, before, counts[longest],
        )
    output_tokens = max(1, min(int(max_tokens), budget - overhead - sum(counts)))
    fitted = [dict(m, content=c) for m, c in zip(messages, contents)]
    return fitted, output_tokens


class LLMRunner:
    """Wraps a single llama_cpp.Llama instance.

    Cheap to instantiate (no model load). Call :meth:`load` to
    actually create the underlying Llama; first prompt after load
    pays the JIT cost.
    """

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._llama: Any = None
        self._lock = threading.Lock()

    def is_loaded(self) -> bool:
        return self._llama is not None

    def load(self) -> None:
        if self._llama is not None:
            return
        if not runtime_available():
            raise LLMUnavailable(runtime_availability_reason())
        if not Path(self.cfg.model_path).exists():
            raise FileNotFoundError(
                f"LLM model file missing: {self.cfg.model_path}. "
                "Download it via the Advanced dialog's 'Install AI model' button."
            )
        from llama_cpp import Llama  # type: ignore[import-not-found]
        kwargs: dict[str, Any] = {
            "model_path": self.cfg.model_path,
            "n_ctx": self.cfg.n_ctx,
            "n_gpu_layers": self.cfg.n_gpu_layers,
            "seed": self.cfg.seed,
            "verbose": False,
        }
        if self.cfg.n_threads > 0:
            kwargs["n_threads"] = self.cfg.n_threads
        self._llama = Llama(**kwargs)

    def unload(self) -> None:
        with self._lock:
            self._llama = None

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str:
        """Run one chat completion. Caller holds the lock."""
        with self._lock:
            self.load()
            assert self._llama is not None
            messages, max_tokens = _fit_messages_to_context(
                messages, max_tokens, self.cfg.n_ctx, _token_counter(self._llama)
            )
            out = self._llama.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        try:
            return str(out["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return ""

    # ---------- task-specific entry points -------------------------

    def summarise(self, transcript_text: str, *, max_bullets: int = 8) -> str:
        """Bullet-point summary of the transcript."""
        return self._chat(
            [{"role": "user", "content": _summarise_prompt(transcript_text, max_bullets)}],
            max_tokens=600,
        )

    def action_items(self, transcript_text: str) -> list[str]:
        """Pull out action items as a JSON list of strings.

        We ask the model for strict JSON; if parsing fails we return
        an empty list rather than guessing — the UI surfaces that
        as "no action items detected".
        """
        raw = self._chat(
            [{"role": "user", "content": _action_items_prompt(transcript_text)}],
            max_tokens=400,
        )
        return _parse_json_list(raw)

    def ask(self, transcript_text: str, question: str) -> str:
        return self._chat(
            [{"role": "user", "content": _ask_prompt(transcript_text, question)}],
            max_tokens=400,
        )

    def translate(
        self, text: str, *, target_language: str = "English"
    ) -> str:
        return _strip_wrapped_quotes(self._chat(
            [{"role": "user", "content": _translate_prompt(text, target_language)}],
            max_tokens=max(256, int(len(text.split()) * 1.5)),
        ))


def _parse_json_list(raw: str) -> list[str]:
    """Best-effort JSON-array parse of an LLM response.

    Strips common chat-style wrappers (markdown fences, leading
    explanatory text) before parsing, and decodes only the first JSON
    value that starts at the array bracket — a chatty model that appends
    a sentence AFTER a perfectly good array (``["a"] Let me know…``)
    used to make the whole response unparseable, silently turning real
    action items into "none detected". Returns ``[]`` on any error.
    """
    if not raw:
        return []
    text = raw.strip()
    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence + optional language tag.
        lines = lines[1:]
        # Drop the closing fence.
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Find the first '[' that opens the array; leading prose and any
    # trailing prose after the array's closing bracket are both ignored.
    start = text.find("[")
    if start == -1:
        return []
    try:
        data, _end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if isinstance(item, (str, int, float))]


# ---------------------------------------------------------------- remote runner


class RemoteLLMError(RuntimeError):
    """Raised when a remote OpenAI-compatible endpoint call fails."""


@dataclass
class RemoteLLMConfig:
    """Connection details for a user-supplied OpenAI-compatible endpoint.

    Works with the real OpenAI API, or any self-hosted / third-party
    server that speaks the same ``POST {base_url}/chat/completions``
    shape (Ollama, LM Studio, vLLM, OpenRouter, ...). ``api_key`` may
    be blank for a local server that doesn't require one.
    """
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 120.0


class RemoteLLMRunner:
    """Same 4-method surface as :class:`LLMRunner`, over HTTP.

    Duck-type compatible with LLMRunner so callers (core.chapters'
    title_chapters_with_llm, the transcript viewer's AI panel) don't
    need to know which provider is active. No local model, no GPU/CPU
    inference cost here — every call is one HTTP request via the
    stdlib ``urllib.request`` (no new third-party dependency, matching
    core/backends/cloud_stt.py's transport style).
    """

    def __init__(self, cfg: RemoteLLMConfig) -> None:
        self.cfg = cfg

    def is_loaded(self) -> bool:
        # Nothing to "load" for an HTTP client — always ready to try.
        return True

    def load(self) -> None:
        return None

    def unload(self) -> None:
        return None

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str:
        base = self.cfg.base_url.rstrip("/")
        url = f"{base}/chat/completions"
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                pass
            raise RemoteLLMError(
                f"{url} returned HTTP {e.code}: {body or e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RemoteLLMError(f"Could not reach {url}: {e.reason}") from e
        try:
            data = json.loads(raw.decode("utf-8"))
            return str(data["choices"][0]["message"]["content"] or "").strip()
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise RemoteLLMError(
                f"{url} returned an unexpected response shape: {e}"
            ) from e

    def summarise(self, transcript_text: str, *, max_bullets: int = 8) -> str:
        return self._chat(
            [{"role": "user", "content": _summarise_prompt(transcript_text, max_bullets)}],
            max_tokens=600,
        )

    def action_items(self, transcript_text: str) -> list[str]:
        raw = self._chat(
            [{"role": "user", "content": _action_items_prompt(transcript_text)}],
            max_tokens=400,
        )
        return _parse_json_list(raw)

    def ask(self, transcript_text: str, question: str) -> str:
        return self._chat(
            [{"role": "user", "content": _ask_prompt(transcript_text, question)}],
            max_tokens=400,
        )

    def translate(self, text: str, *, target_language: str = "English") -> str:
        return _strip_wrapped_quotes(self._chat(
            [{"role": "user", "content": _translate_prompt(text, target_language)}],
            max_tokens=max(256, int(len(text.split()) * 1.5)),
        ))


# ---------------------------------------------------------------- factory


def build_runner_from_config(
    config: dict[str, Any],
) -> "LLMRunner | RemoteLLMRunner | None":
    """Construct the configured LLM runner, or ``None`` when unavailable.

    Reads ``ai_enabled`` (master on/off) and ``llm_provider``
    ("local"/"remote") plus that provider's own settings. Never
    raises: every failure mode (dep missing, model file missing,
    remote endpoint not yet configured) returns ``None`` so callers
    can treat "no runner" as "skip this optional step" uniformly,
    whether it's the auto-chapter titler in core.transcriber or the
    transcript viewer's AI panel.
    """
    if not config.get("ai_enabled", False):
        return None
    provider = str(config.get("llm_provider") or "local").strip().lower()
    if provider == "remote":
        base_url = (config.get("llm_remote_base_url") or "").strip()
        model = (config.get("llm_remote_model") or "").strip()
        if not base_url or not model:
            return None
        return RemoteLLMRunner(RemoteLLMConfig(
            base_url=base_url,
            model=model,
            api_key=(config.get("llm_remote_api_key") or "").strip(),
        ))
    try:
        if not runtime_available():
            return None
        model_path = (config.get("ai_model_path") or "").strip()
        if not model_path:
            model_path = str(default_model_path())
        if not is_model_present(Path(model_path)):
            return None
        runner = LLMRunner(LLMConfig(model_path=model_path))
        runner.load()
        return runner
    except Exception:  # noqa: BLE001
        return None


def translate_segments(
    runner: Any,
    segments: list[dict[str, Any]],
    *,
    target_language: str = "English",
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[str]:
    """Translate each segment's text independently — one call per segment.

    A single whole-transcript :meth:`translate` call is faster but
    doesn't guarantee a 1:1 line count with the source segments — an
    LLM can merge or reword across boundaries, especially a small
    local model. The bilingual-subtitle writer needs an EXACT
    per-cue pairing, so this trades speed for that guarantee.

    Returns a list the same length as ``segments``. An empty source
    segment or a translation failure yields ``""`` at that index
    rather than raising, so one bad segment doesn't discard an
    otherwise-good pass; ``progress_cb(done, total)`` (if given) is
    called after every segment, and ``cancel_event`` (if set)
    short-circuits the remaining segments to ``""``.
    """
    out: list[str] = []
    total = len(segments)
    for i, seg in enumerate(segments):
        if cancel_event is not None and cancel_event.is_set():
            out.append("")
        else:
            text = (seg.get("text") or "").strip()
            if not text:
                out.append("")
            else:
                try:
                    out.append(runner.translate(text, target_language=target_language))
                except Exception as e:  # noqa: BLE001
                    logger.warning("translate_segments: segment %d failed: %s", i, e)
                    out.append("")
        if progress_cb is not None:
            try:
                progress_cb(i + 1, total)
            except Exception:  # noqa: BLE001
                pass
    return out
