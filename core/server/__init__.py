"""Optional local-network / web HTTP job server for Whisper Transcriber Suite.

Public surface:

  * :class:`ServerHandle` — a start/stop-able, non-blocking wrapper around
    :class:`~core.server.httpd.JobHTTPServer`. ``start()`` binds the socket
    and runs ``serve_forever`` on a daemon thread; ``stop()`` tears it down
    cleanly; ``is_running()`` reports state; ``urls()`` lists the reachable
    addresses. This is what the GUI drives so the server runs IN-PROCESS
    without blocking the Tk loop.
  * :func:`run_server` — the blocking ``gui.py serve`` entry point, built on
    top of :class:`ServerHandle`.
  * :func:`find_available_port` — pick a free TCP port, preferring a given
    one and falling back to an OS-assigned ephemeral port if it is taken.
  * :func:`reachable_urls` — the loopback / LAN URLs to print on startup.

Tk-free; imports nothing from ``app/``. Stdlib only (plus the bundled
yt-dlp.exe for URL downloads, the same binary the desktop app uses).
"""
from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from core.server import lanfetch
from core.server.dlproxy import shared_proxy
from core.server.httpd import JobHTTPServer
from core.server.jobs import (
    DEFAULT_WEBHOOK_HEADER,
    DownloadCancelled,
    DownloadLimits,
    JobManager,
    strip_url_secrets,
    webhook_header_name_valid,
    webhook_secret_valid,
    webhook_url_is_plain_http,
)

logger = logging.getLogger(__name__)

__all__ = [
    "run_server",
    "reachable_urls",
    "find_available_port",
    "ServerHandle",
    "JobHTTPServer",
    "JobManager",
]

# A loopback bind reaches only this machine and never trips the Windows
# firewall prompt; the all-interfaces bind is the LAN-share case.
HOST_LOOPBACK = "127.0.0.1"
HOST_LAN = "0.0.0.0"


def _real_transcribe(
    task: Any,
    progress_cb: Any = None,
    log_cb: Any = None,
    language_cb: Any = None,
) -> None:
    """Thin adapter onto ``core.transcriber.transcribe`` (lazy import).

    Imported lazily so ``core.server`` stays importable (and unit-testable)
    without dragging in faster-whisper.

    A job that names a language model (``task.language_model``, chosen at submission,
    ADR 0016) runs on it; when that model cannot load, the job runs on the server's
    engine and says so in ``task.route_warning``. Only one model is kept in memory.
    """
    from core import transcriber as _trans
    model_id = str(getattr(task, "language_model", "") or "")
    if model_id:
        try:
            _trans.transcribe_with_language_model(model_id, task, progress_cb, log_cb, language_cb)
            return
        except _trans.LanguageModelLoadError as e:
            logger.warning("server: language model %s did not load (%s); using the general model",
                           model_id, e)
            task.route_warning = (
                f"The model trained for this language could not load ({e}); the general model "
                "transcribed this file instead.")
    _trans.release_language_model()
    _trans.transcribe(task, progress_cb, log_cb, language_cb)


# yt-dlp's unfinished files END in one of these: "x.f137.mp4.part",
# "x.mp4.part-Frag12", "x.mp4.ytdl". Anchored: a title may contain
# "Part-1" or ".tmp." and still be the media.
_NOT_MEDIA_RE = re.compile(
    r"\.(part(-Frag\d+)?|ytdl|temp|tmp)$", re.IGNORECASE)
# yt-dlp's post-processing copy "x.temp.mp4" (replaced by "x.mp4" when done).
_POST_TEMP_RE = re.compile(r"^(?P<stem>.+)\.temp(?P<ext>\.[^.]+)$",
                           re.IGNORECASE)


def _is_downloaded_media(dest_dir: str, name: str) -> bool:
    """True for a finished, non-empty file that can be the downloaded media.

    The job folder also holds the ``.wts-job`` marker (and later the
    ``.whisperproject.json`` override); neither, a hidden file, an empty
    file nor an unfinished download is media. A ``x.temp.mp4`` beside the
    final ``x.mp4`` is yt-dlp's leftover; alone it may be a real title, so
    it counts as media.
    """
    if name.startswith(".") or _NOT_MEDIA_RE.search(name):
        return False
    post = _POST_TEMP_RE.match(name)
    if post and os.path.isfile(
            os.path.join(dest_dir, post["stem"] + post["ext"])):
        return False
    path = os.path.join(dest_dir, name)
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _proxy_environment(proxy_url: str) -> dict[str, str]:
    """The child's environment with every request routed to the guard proxy.

    The proxy password travels in the environment, not in the command line, so
    it never appears in an error text or a log line (``CalledProcessError``
    carries the command). Any proxy setting already in the environment is
    replaced, and ``NO_PROXY`` is emptied so nothing bypasses the guard.
    """
    env = dict(os.environ)
    for name in list(env):
        if name.lower() in ("http_proxy", "https_proxy", "all_proxy",
                            "no_proxy", "ftp_proxy"):
            del env[name]
    env.update({"HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url,
                "ALL_PROXY": proxy_url, "NO_PROXY": ""})
    return env


# yt-dlp option value: every extractor except the generic one.
GENERIC_EXTRACTOR_OFF = "default,-generic"
# yt-dlp's message when no extractor accepts the address (with the generic one
# switched off that is every direct media link and every unknown site).
_UNSUPPORTED_URL_RE = re.compile(
    r"Unsupported URL|No suitable extractor", re.IGNORECASE)
DIRECT_LINK_REFUSED = (
    "this link is not from a site the server can download from. The server "
    "does not fetch plain media links or unknown pages (so it cannot be "
    "aimed at other computers on its network); upload the file instead, "
    "or use a link from a supported video site")


def _download_url(url: str, dest_dir: str,
                  limits: DownloadLimits | None = None) -> str:
    """Download an http(s) ``url`` into ``dest_dir`` via bundled yt-dlp.

    Returns the saved media path. Uses the same end-of-options ``--``
    injection guard the desktop download service uses so a URL that starts
    with ``-`` can never be parsed as a yt-dlp flag (e.g. ``--exec``).

    ``limits`` (given by the job manager) bounds the run: the job's cancel
    flag stops it, ``max_bytes`` caps the file and ``timeout_s`` the total
    time, so one stalled or huge download cannot hold the single worker.
    """
    from core._proc import kill_process_tree, new_session_kwargs
    from core.paths import bin_dir

    from core import yt_dlp_update
    from core.js_runtime import yt_dlp_js_args

    # A direct link to a host inside an operator-listed local network
    # (server_allowed_private_networks) is fetched by the app's own guarded
    # downloader: yt-dlp's generic extractor is off, so it would be refused.
    if lanfetch.is_lan_direct_url(url):
        return lanfetch.fetch(url, dest_dir, limits)
    # Started on first use. If it cannot start, the job fails: a server job
    # never downloads without the connect-time address check.
    try:
        proxy = shared_proxy()
    except OSError as exc:
        raise RuntimeError(
            "the download guard could not start; the link was not "
            f"downloaded ({exc.strerror or 'network error'})") from exc
    # Short title: the job folder plus this name plus the output suffixes
    # must stay inside Windows' path limit.
    out_template = os.path.join(dest_dir, "%(title).80s.%(ext)s")
    # Registered as a running download: an update of the user-writable
    # yt-dlp copy waits for it, and this waits for a running update.
    with yt_dlp_update.download_running():
        yt_dlp = yt_dlp_update.resolve_yt_dlp_path()  # newer of bundled / updated copy
        command = [
            yt_dlp,
            *yt_dlp_js_args(yt_dlp),  # Deno for YouTube's JS challenges, if present
            "--ffmpeg-location", bin_dir(),
            "--no-playlist",
            "--newline",
            # The generic extractor fetches ANY address, including a plain
            # media link that points at an internal host or follows a redirect
            # to one, and this app cannot see the requests yt-dlp makes. The
            # named site extractors only talk to their own sites. A server
            # job therefore never uses it (a direct media link is refused
            # below); the desktop Download tab keeps it.
            "--use-extractors", GENERIC_EXTRACTOR_OFF,
            # yt-dlp's native downloaders keep fragment fetches inside
            # yt-dlp, so they use the proxy (set through the environment
            # below) as well.
            "--downloader", "native",
            # The frozen yt-dlp.exe ignores PYTHONUTF8 and prints cp1252,
            # dropping non-Latin title characters from its output.
            "--encoding", "utf-8",
            "-o", out_template,
        ]
        if limits is not None and limits.max_bytes > 0:
            command += ["--max-filesize", str(limits.max_bytes)]
        # End-of-options separator: the URL is never treated as a flag.
        command += ["--", url]
        logger.info("server: downloading %s", strip_url_secrets(url))
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=_proxy_environment(proxy.url),
            **new_session_kwargs(),
        )
        try:
            started = time.monotonic()
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                reason = ""
                if limits is not None and limits.cancelled():
                    reason = "cancelled"
                elif (limits is not None and limits.timeout_s > 0
                      and time.monotonic() - started > limits.timeout_s):
                    reason = "timeout"
                if reason:
                    kill_process_tree(process, force=True)
                    try:
                        process.communicate(timeout=10)
                    except (subprocess.TimeoutExpired, OSError, ValueError):
                        pass
                    if reason == "cancelled":
                        raise DownloadCancelled()
                    minutes = int((limits.timeout_s if limits else 0) // 60)
                    raise TimeoutError(
                        f"the download took longer than {minutes} minutes and "
                        "was stopped")
            if process.returncode:
                if _UNSUPPORTED_URL_RE.search(stderr or ""):
                    raise RuntimeError(DIRECT_LINK_REFUSED)
                raise subprocess.CalledProcessError(
                    process.returncode, command, stdout, stderr)
        finally:
            if process.returncode is None:  # still running: an exception left it behind
                kill_process_tree(process, force=True)
                try:
                    process.communicate(timeout=10)
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    pass
    # Pick the newest media file yt-dlp left in the dir.
    candidates = [
        os.path.join(dest_dir, n) for n in os.listdir(dest_dir)
        if _is_downloaded_media(dest_dir, n)
    ]
    if not candidates:
        # yt-dlp skips a file over --max-filesize and still exits 0.
        if "max-filesize" in (stdout or "").lower():
            raise RuntimeError(
                "download produced no file: the file is larger than the "
                "server's download limit")
        raise RuntimeError(
            "download produced no file"
            + (" (it may be larger than the server's download limit)"
               if limits is not None and limits.max_bytes > 0 else ""))
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def _ensure_model_loaded() -> None:
    """Make sure the model is present + loaded before serving.

    Downloads it on first run (same path the GUI uses) then loads it into
    the module-global so the first job doesn't pay the cold-load cost.
    """
    from core import transcriber as _trans
    from core.config import load_config
    from core.model_manager import ensure_model

    cfg = load_config()
    _trans.config.update(cfg)
    try:
        ensure_model(cfg, status_cb=lambda m: logger.info("server: %s", m))
    except Exception as e:  # noqa: BLE001
        logger.warning("server: ensure_model failed (%s); "
                       "the first job may need to download it", e)
    if not _trans.load_existing_model(lambda m: logger.info("server: %s", m)):
        err = _trans.get_model_error() or "unknown error"
        logger.warning("server: model not loaded yet (%s); "
                       "jobs will report the error until it is", err)


def reachable_urls(host: str, port: int, https: bool = False) -> list[str]:
    """Human-facing URLs to print on startup.

    For a loopback bind, just the loopback URL. For an all-interfaces bind
    (``0.0.0.0``), the loopback URL plus this machine's best-guess LAN IP so
    the operator can hand the address to people on the network. ``https``
    switches the scheme for the opt-in TLS mode.
    """
    scheme = "https" if https else "http"
    if host not in ("0.0.0.0", "::", ""):
        bracketed = f"[{host}]" if ":" in host else host
        return [f"{scheme}://{bracketed}:{port}/"]
    urls = [f"{scheme}://127.0.0.1:{port}/"]
    lan_ip = _primary_lan_ip()
    if lan_ip:
        urls.append(f"{scheme}://{lan_ip}:{port}/")
    return urls


def _primary_lan_ip() -> str:
    """Best-effort primary LAN IPv4 (no packets actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting a UDP socket just picks the outbound interface; no
        # traffic leaves the machine.
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except OSError:
        return ""
    finally:
        s.close()


def _family(host: str) -> socket.AddressFamily:
    """AF_INET6 for an IPv6 literal such as ``::1`` (``serve --host``), else AF_INET."""
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def _port_is_free(host: str, port: int) -> bool:
    """True iff no listener currently holds ``host:port``.

    Deliberately does NOT set ``SO_REUSEADDR``. On Windows that flag lets
    two sockets bind the same address at once, so a reuse-address probe
    would call a port held by another listener "free" — defeating the
    point. A plain bind fails cleanly when something is already listening,
    which is exactly the "port already in use" case we want to detect.
    """
    s = socket.socket(_family(host), socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_available_port(preferred: int = 8765, host: str = HOST_LOOPBACK) -> int:
    """Return a bindable TCP port, preferring ``preferred``.

    Behaviour (documented so callers can rely on it):

      * If ``preferred`` is free on ``host``, return it unchanged.
      * Otherwise ask the OS for any free ephemeral port (bind to port 0)
        and return that — so "port already in use" never blocks startup;
        the GUI reports the port it actually got.

    Probing ``host`` (not always loopback) matters because a port can be
    free on ``127.0.0.1`` yet taken on ``0.0.0.0`` (or vice-versa); the
    caller passes whichever host it is about to bind.
    """
    if 1 <= int(preferred) <= 65535 and _port_is_free(host, int(preferred)):
        return int(preferred)
    s = socket.socket(_family(host), socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


# Type aliases for the injected callables (the JobManager's Protocol +
# DownloadFn), so a typed caller can annotate against them.
TranscribeFnT = Callable[..., None]
DownloadFnT = Callable[[str, str], str]


class ServerHandle:
    """Start/stop-able, NON-BLOCKING handle around the job HTTP server.

    Designed for the GUI: it owns a :class:`JobManager` and a
    :class:`JobHTTPServer`, runs ``serve_forever`` on a daemon thread, and
    exposes a tiny lifecycle (``start`` / ``stop`` / ``is_running``) plus
    the bound ``host`` / ``port`` and reachable :meth:`urls`.

    Tk-free. The desktop app constructs one, calls :meth:`start` from a
    background thread (so the bind + optional model load don't freeze the
    UI), and marshals the result back onto the Tk thread itself.

    Idempotent: :meth:`start` while already running is a no-op; :meth:`stop`
    while stopped is a no-op. A handle is single-shot per ``start`` — after
    ``stop`` it can be started again (a fresh server/manager are built).
    """

    def __init__(
        self,
        *,
        transcribe_fn: TranscribeFnT | None = None,
        download_fn: DownloadFnT | None = None,
        load_model: bool = True,
    ) -> None:
        # The real engine by default; tests inject a fake that just writes
        # dummy output files so no model ever loads.
        self._transcribe_fn = transcribe_fn or _real_transcribe
        self._download_fn = download_fn if download_fn is not None else _download_url
        self._load_model = load_model
        self._lock = threading.Lock()
        # Signalled when a start() finishes, so a concurrent start() can wait
        # for it without holding the lock through the model load.
        self._start_done = threading.Condition(self._lock)
        self._manager: JobManager | None = None
        self._server: JobHTTPServer | None = None
        self._thread: threading.Thread | None = None
        # start() is between its guard and publishing the server; stop()
        # during that window sets _start_cancelled (see start()).
        self._starting = False
        self._start_cancelled = False
        self.host = ""
        self.port = 0
        self.token = ""
        self.https = False
        self.webhook_url = ""
        # Only whether a secret header is sent: the secret itself is never
        # kept on the handle.
        self.webhook_secret_set = False
        self.webhook_header = ""

    def is_running(self) -> bool:
        with self._lock:
            return self._server is not None and self._thread is not None \
                and self._thread.is_alive()

    def start(
        self,
        host: str = HOST_LOOPBACK,
        port: int = 8765,
        token: str = "",
        *,
        max_upload_mb: int = 512,
        auto_port: bool = True,
        https: bool = False,
        webhook_url: str = "",
        webhook_secret: str = "",
        webhook_header: str = "",
    ) -> None:
        """Bind + start serving on a daemon thread (idempotent).

        Raises :class:`OSError` if the socket can't be bound (and
        ``auto_port`` didn't already fall back to a free port). The GUI
        catches that and shows a plain message. ``https`` wraps the socket
        in TLS with a self-signed certificate generated under
        ``user_data_dir()`` on first use; a certificate that can't be
        produced raises :class:`RuntimeError` rather than silently serving
        plaintext.
        """
        # The slow part (first-run model download, certificate generation)
        # runs WITHOUT the lock: holding it there blocked is_running() and
        # stop() — the app's exit path — until the download finished. A
        # stop() meanwhile cancels this start, which then returns without
        # serving. A concurrent start() waits for this one, then starts
        # itself only if this one was cancelled.
        with self._start_done:
            while self._starting:
                self._start_done.wait()
            if (self._server is not None and self._thread is not None
                    and self._thread.is_alive()):
                return  # already running — idempotent double-start guard
            self._starting = True
            self._start_cancelled = False
        if webhook_secret:
            if (webhook_header
                    and not webhook_header_name_valid(webhook_header)):
                # The app shows this text in its "could not start" box.
                raise ValueError(
                    "The webhook header name is not a valid HTTP header "
                    "name (or is one the request sets itself).")
            if not webhook_secret_valid(webhook_secret):
                logger.warning(
                    "server: the webhook secret cannot be used in an HTTP "
                    "header; every webhook delivery will be refused")
            elif webhook_url_is_plain_http(webhook_url):
                logger.warning(
                    "server: the webhook secret is sent in plain text to an "
                    "http:// address; use an https:// receiver")
        try:
            if auto_port:
                port = find_available_port(port, host)
            ssl_context = None
            if https:
                from core.server.tls import build_server_ssl_context
                ssl_context = build_server_ssl_context()
            if self._load_model:
                _ensure_model_loaded()
            with self._lock:
                if self._start_cancelled:
                    logger.info("server: start cancelled by stop() while starting")
                    return
            manager = JobManager(
                self._transcribe_fn, download_fn=self._download_fn,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret, webhook_header=webhook_header,
            )
            manager.start()
            try:
                server = JobHTTPServer(
                    (host, port), manager,
                    token=token, max_upload_mb=max_upload_mb,
                    ssl_context=ssl_context,
                )
            except OSError:
                manager.stop()
                raise
            with self._lock:
                if self._start_cancelled:
                    cancelled = True
                else:
                    cancelled = False
                    self._manager = manager
                    self._server = server
                    self.host = host
                    # Reflect the port actually bound (matters for the port-0 case).
                    self.port = int(server.server_address[1])
                    self.token = token
                    self.https = https
                    self.webhook_url = (webhook_url or "").strip()
                    self.webhook_secret_set = bool(webhook_secret)
                    self.webhook_header = (
                        webhook_header or DEFAULT_WEBHOOK_HEADER)
                    self._thread = threading.Thread(
                        target=server.serve_forever,
                        name="server-http", daemon=True,
                    )
                    self._thread.start()
            if cancelled:
                logger.info("server: start cancelled by stop() while starting")
                server.server_close()
                manager.stop()
        finally:
            with self._start_done:
                self._starting = False
                self._start_done.notify_all()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop serving, close the socket, stop the worker (idempotent).

        ``server.shutdown()`` blocks until the ``serve_forever`` loop
        notices the shutdown request — unbounded in the stdlib, so if that
        thread died before ever reaching its poll, this would wait forever.
        Run it on a helper thread with a join timeout so ``stop()`` always
        returns.
        """
        with self._lock:
            # A start() still loading the model sees this and never serves.
            self._start_cancelled = True
            server = self._server
            manager = self._manager
            thread = self._thread
            self._server = None
            self._manager = None
            self._thread = None
        if server is not None:
            shutdown_thread = threading.Thread(
                target=server.shutdown, name="server-shutdown", daemon=True,
            )
            shutdown_thread.start()
            shutdown_thread.join(timeout=timeout)
            if shutdown_thread.is_alive():
                logger.warning(
                    "server: shutdown() did not complete within %.1fs", timeout,
                )
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                logger.exception("server: error during shutdown")
        if thread is not None:
            thread.join(timeout=timeout)
        if manager is not None:
            manager.stop(timeout=timeout)

    def urls(self) -> list[str]:
        """Reachable URLs for the current bind (empty when not running)."""
        if not self.is_running():
            return []
        return reachable_urls(self.host, self.port, self.https)


def run_server(
    host: str = HOST_LOOPBACK,
    port: int = 8765,
    token: str = "",
    *,
    max_upload_mb: int = 512,
    load_model: bool = True,
    https: bool = False,
    webhook_url: str = "",
    webhook_secret: str = "",
    webhook_header: str = "",
) -> int:
    """Run the HTTP job server forever (blocking). Returns an exit code.

    The ``gui.py serve`` entry point. Binds ``host:port`` (loading the
    model once unless ``load_model`` is False), prints the reachable
    URL(s), and serves until Ctrl+C. Built on :class:`ServerHandle` so the
    blocking CLI and the non-blocking GUI share one start/stop path.
    """
    if webhook_secret and not webhook_secret_valid(webhook_secret):
        # Judged on the value as given (never trimmed) and never echoed.
        print("The webhook secret cannot be used in an HTTP header (control "
              "characters, characters outside Latin-1, or a space at either "
              "end). Nothing was started.", file=sys.stderr, flush=True)
        return 1
    if (webhook_secret and webhook_header
            and not webhook_header_name_valid(webhook_header)):
        print("The webhook header name is not a valid HTTP header name (or is "
              "one the request sets itself, such as Content-Type or Host). "
              "Nothing was started.", file=sys.stderr, flush=True)
        return 1
    handle = ServerHandle(load_model=load_model)
    try:
        # The CLI honours an explicit --port verbatim (auto_port off) so a
        # scripted caller binds exactly what it asked for, or sees the error.
        handle.start(host, port, token,
                     max_upload_mb=max_upload_mb, auto_port=False,
                     https=https, webhook_url=webhook_url,
                     webhook_secret=webhook_secret,
                     webhook_header=webhook_header)
    except OSError as e:
        logger.error("server: could not bind %s:%s — %s", host, port, e)
        return 1
    except RuntimeError as e:
        # HTTPS was explicitly requested but no certificate could be made;
        # fail loudly rather than silently serving plaintext.
        logger.error("server: HTTPS setup failed — %s", e)
        return 1

    is_lan = host in (HOST_LAN, "::", "")
    print("Whisper Transcriber Suite server listening on:")
    for url in handle.urls():
        print(f"  {url}")
    if is_lan:
        print("LAN mode: bound to all interfaces. Windows Defender may prompt "
              "to allow access — this is expected for the LAN case.")
    else:
        print("Loopback only (this machine). Use --lan to share on the network.")
    if token:
        print("Auth token required (X-Auth-Token header, ?token=, or an "
              "OpenAI-style Authorization: Bearer).")
    if https:
        print("HTTPS on (self-signed certificate — accept the browser "
              "warning once).")
    if webhook_url:
        # Origin only: the rest of a webhook URL often holds its secret.
        from core.server.jobs import redact_url
        print(f"Completion webhooks POST to {redact_url(webhook_url)}")
        if webhook_secret:
            # The header name only; the secret itself is never printed.
            print("Webhook secret set: sent in the "
                  f"{handle.webhook_header} header.")
            if webhook_url_is_plain_http(webhook_url):
                print("Warning: the webhook URL is http://, so the secret "
                      "travels in plain text. Use an https:// receiver.")
    print("Press Ctrl+C to stop.")

    try:
        # Block the main thread until interrupted; the handle's daemon
        # thread is doing the actual serving.
        t = handle._thread
        while t is not None and t.is_alive():
            t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        handle.stop()
    return 0
