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
import socket
import subprocess
import threading
from typing import Any, Callable

from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager

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
    """
    from core import transcriber as _trans
    _trans.transcribe(task, progress_cb, log_cb, language_cb)


def _download_url(url: str, dest_dir: str) -> str:
    """Download an http(s) ``url`` into ``dest_dir`` via bundled yt-dlp.

    Returns the saved media path. Uses the same end-of-options ``--``
    injection guard the desktop download service uses so a URL that starts
    with ``-`` can never be parsed as a yt-dlp flag (e.g. ``--exec``).
    """
    from core._proc import new_session_kwargs
    from core.paths import bin_dir, bundled_binary

    from core.js_runtime import yt_dlp_js_args

    yt_dlp = bundled_binary("yt-dlp")
    out_template = os.path.join(dest_dir, "%(title).200s.%(ext)s")
    command = [
        yt_dlp,
        *yt_dlp_js_args(yt_dlp),  # Deno for YouTube's JS challenges, if present
        "--ffmpeg-location", bin_dir(),
        "--no-playlist",
        "--newline",
        "-o", out_template,
        # End-of-options separator — URL is never treated as a flag.
        "--",
        url,
    ]
    logger.info("server: downloading %s", url)
    subprocess.run(
        command, check=True, capture_output=True, text=True,
        **new_session_kwargs(),
    )
    # Pick the newest file yt-dlp left in the dir.
    candidates = [
        os.path.join(dest_dir, n) for n in os.listdir(dest_dir)
        if os.path.isfile(os.path.join(dest_dir, n))
    ]
    if not candidates:
        raise RuntimeError("download produced no file")
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
        return [f"{scheme}://{host}:{port}/"]
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


def _port_is_free(host: str, port: int) -> bool:
    """True iff no listener currently holds ``host:port``.

    Deliberately does NOT set ``SO_REUSEADDR``. On Windows that flag lets
    two sockets bind the same address at once, so a reuse-address probe
    would call a port held by another listener "free" — defeating the
    point. A plain bind fails cleanly when something is already listening,
    which is exactly the "port already in use" case we want to detect.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
        self._manager: JobManager | None = None
        self._server: JobHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.host = ""
        self.port = 0
        self.token = ""
        self.https = False
        self.webhook_url = ""

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
        with self._lock:
            if self._server is not None and self._thread is not None \
                    and self._thread.is_alive():
                return  # already running — idempotent double-start guard
            if auto_port:
                port = find_available_port(port, host)
            ssl_context = None
            if https:
                from core.server.tls import build_server_ssl_context
                ssl_context = build_server_ssl_context()
            if self._load_model:
                _ensure_model_loaded()
            manager = JobManager(
                self._transcribe_fn, download_fn=self._download_fn,
                webhook_url=webhook_url,
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
            self._manager = manager
            self._server = server
            self.host = host
            # Reflect the port actually bound (matters for the port-0 case).
            self.port = int(server.server_address[1])
            self.token = token
            self.https = https
            self.webhook_url = (webhook_url or "").strip()
            self._thread = threading.Thread(
                target=server.serve_forever,
                name="server-http", daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop serving, close the socket, stop the worker (idempotent).

        ``server.shutdown()`` blocks until the ``serve_forever`` loop
        notices the shutdown request — unbounded in the stdlib, so if that
        thread died before ever reaching its poll, this would wait forever.
        Run it on a helper thread with a join timeout so ``stop()`` always
        returns.
        """
        with self._lock:
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
) -> int:
    """Run the HTTP job server forever (blocking). Returns an exit code.

    The ``gui.py serve`` entry point. Binds ``host:port`` (loading the
    model once unless ``load_model`` is False), prints the reachable
    URL(s), and serves until Ctrl+C. Built on :class:`ServerHandle` so the
    blocking CLI and the non-blocking GUI share one start/stop path.
    """
    handle = ServerHandle(load_model=load_model)
    try:
        # The CLI honours an explicit --port verbatim (auto_port off) so a
        # scripted caller binds exactly what it asked for, or sees the error.
        handle.start(host, port, token,
                     max_upload_mb=max_upload_mb, auto_port=False,
                     https=https, webhook_url=webhook_url)
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
        print(f"Completion webhooks POST to {webhook_url}")
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
