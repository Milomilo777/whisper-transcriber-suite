"""Video Tiling: play one live stream as an N×N grid of identical tiles.

One live stream is downloaded **once** (yt-dlp → stdout) and shown as an N×N
grid of identical tiles (the ``fps=source_fps*N²,tile=NxN`` trick). It can fill
a single screen, or be fanned out across several monitors — one ffplay window
per selected monitor — for a multi-screen video wall.

This is a Tk-free port of the maintainer's hardened standalone video-tiler
(github.com/translation-robot/video-tiler) adapted to this project:

  * Lives in ``core`` and imports NO tkinter — the engine runs on a background
    worker thread; it talks to the UI through ``status``/``log`` callbacks.
  * Clean teardown uses :func:`core._proc.kill_process_tree` (taskkill /T on
    Windows) so ffmpeg/yt-dlp children are never orphaned — the bug the old
    ``proc.terminate()`` left behind.
  * Robust extraction (multiple player clients, retries, ``--`` URL guard),
    ``poll()`` liveness, exponential-backoff reconnect, and a self-heal that
    runs ``yt-dlp -U`` after repeated quick failures.
  * Monitor detection comes from :mod:`core.monitors` (also Tk-free; screeninfo
    optional with a ctypes Win32 fallback).

ffplay is NOT bundled with the app (only ffmpeg/ffprobe/yt-dlp are), so it is
resolved via :func:`core.paths.bundled_binary` and the UI degrades to a clear
"add ffplay" message when it's missing.
"""
from __future__ import annotations

import collections
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from . import monitors as _monitors
from ._proc import kill_process_tree, new_session_kwargs
from .paths import bin_dir, bundled_binary

logger = logging.getLogger(__name__)

# Robust YouTube extraction: try several player clients so one breaking does
# not break playback. Ignored by non-YouTube extractors, so it is always safe.
YT_PLAYER_CLIENTS = "default,android,tv,ios"

MIN_DIVISIONS = 1
MAX_DIVISIONS = 64

QUALITY_CHOICES = ["Auto", "1080p", "720p", "480p", "360p", "240p", "144p"]

# On Windows, keep helper processes (yt-dlp / ffplay) from flashing a console
# window. ffplay still shows its own SDL video window. No effect on other OSes.
#
# IMPORTANT: the long-lived yt-dlp / ffplay players are spawned with
# ``new_session_kwargs()`` (NOT this bare flag) so that on POSIX they LEAD
# THEIR OWN process group — otherwise ``core._proc.kill_process_tree`` would
# ``os.killpg`` the app's OWN group on Stop and take the whole app down with
# it. This constant is only for the short-lived, NOT-tree-killed
# ``yt-dlp -U`` / ``pip`` self-heal ``subprocess.run`` calls below.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

StatusCb = Callable[[str, str], None]  # (message, color)
LogCb = Callable[[str], None]


# --------------------------------------------------------------------------- #
#  Tool / URL discovery (pure-ish helpers)
# --------------------------------------------------------------------------- #
def ffplay_path() -> str:
    """Bundled bin/ffplay[.exe] if present, else the bare name (PATH)."""
    return bundled_binary("ffplay")


def ffplay_available() -> bool:
    """True if an ffplay binary can be found (bundled or on PATH)."""
    p = ffplay_path()
    return os.path.isfile(p) or shutil.which(p) is not None


# --------------------------------------------------------------------------- #
#  ffplay auto-download (P4-5) — pure helpers + the download driver
# --------------------------------------------------------------------------- #
ProgressCb = Callable[[str], None]


def ffplay_platform_key() -> str:
    """Map the running OS to the ``config['ffplay_downloads']`` key."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def select_ffplay_url(downloads: Any, platform_key: str | None = None) -> str:
    """Pick the ffplay download URL for *platform_key* from *downloads*.

    *downloads* is the ``ffplay_downloads`` dict (platform → URL). Returns the
    matching URL, or "" when the dict is missing/wrong-shaped, the key is
    absent, or its value is empty. Pure — no I/O.
    """
    if not isinstance(downloads, dict):
        return ""
    key = platform_key or ffplay_platform_key()
    val = downloads.get(key)
    return val.strip() if isinstance(val, str) else ""


def _ffplay_exe_name() -> str:
    return "ffplay.exe" if os.name == "nt" else "ffplay"


def extract_ffplay_from_zip(zip_path: str, dest_dir: str) -> str:
    """Extract just ``ffplay[.exe]`` from the zip at *zip_path* into *dest_dir*.

    Scans the archive for an entry whose basename is ``ffplay`` /
    ``ffplay.exe`` (case-insensitive; a member may live under e.g.
    ``ffmpeg-.../bin/ffplay.exe``) and writes ONLY that one file, flattened to
    ``dest_dir/ffplay[.exe]``. Returns the written path. Raises
    ``FileNotFoundError`` when the archive has no ffplay member, and lets
    ``zipfile.BadZipFile`` surface on a corrupt archive.

    Pure-ish: only touches *zip_path* (read) and *dest_dir* (write); no
    network. Unit-tested with a tiny in-memory zip.
    """
    import zipfile

    want = _ffplay_exe_name().lower()
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        member = None
        for name in zf.namelist():
            base = os.path.basename(name.replace("\\", "/")).lower()
            # Accept ffplay or ffplay.exe regardless of the host OS naming, so
            # a Windows zip extracted on a test host (or vice-versa) still
            # finds it; prefer the exact platform name when both appear.
            if base in ("ffplay", "ffplay.exe"):
                member = name
                if base == want:
                    break
        if member is None:
            raise FileNotFoundError(
                "The downloaded archive does not contain an ffplay binary."
            )
        target = os.path.join(dest_dir, _ffplay_exe_name())
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    # Best-effort exec bit on POSIX (no effect on Windows).
    if os.name != "nt":
        try:
            os.chmod(target, 0o755)
        except OSError:
            pass
    return target


def download_ffplay(
    progress_cb: Optional[ProgressCb] = None,
    config: Optional[dict] = None,
) -> bool:
    """Download ffplay for this platform into the app's ``bin/`` dir.

    Resolves the URL from ``config['ffplay_downloads'][<platform>]`` (loading
    the merged config when *config* is None). The URL may be a DIRECT
    ``ffplay[.exe]`` or a ``.zip`` of a full ffmpeg build that contains it —
    in the latter case only ffplay is extracted. ``.7z`` / ``.tar.*`` are NOT
    supported (stdlib only); they return False with a clear progress message.

    Returns True on success (ffplay is now in ``bin/``), False otherwise.
    Blocking — call on a daemon thread. Never raises: every failure is reported
    via *progress_cb* and returns False.
    """
    say = progress_cb or (lambda _m: None)
    try:
        if config is None:
            from .config import load_config
            config = load_config()
        url = select_ffplay_url(config.get("ffplay_downloads"))
        if not url:
            say("No ffplay download URL is configured for this platform.")
            return False

        bdir = bin_dir()
        os.makedirs(bdir, exist_ok=True)
        target = os.path.join(bdir, _ffplay_exe_name())

        lower = url.lower().split("?", 1)[0]
        if lower.endswith((".7z", ".tar.xz", ".tar.gz", ".tar.bz2", ".xz")):
            say(
                "The configured ffplay URL is a .7z/.tar archive, which this "
                "downloader can't open. Use a direct ffplay binary or a .zip."
            )
            return False

        is_zip = lower.endswith(".zip") or "/zip" in lower
        say("Downloading ffplay…")
        fd, tmp = tempfile.mkstemp(prefix="ffplay-dl-", suffix=".zip" if is_zip else "")
        os.close(fd)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "WhisperTranscriberSuite"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out)

            if is_zip:
                say("Extracting ffplay…")
                extract_ffplay_from_zip(tmp, bdir)
            else:
                # Direct binary — move it into place.
                shutil.move(tmp, target)
                tmp = ""  # consumed
                if os.name != "nt":
                    try:
                        os.chmod(target, 0o755)
                    except OSError:
                        pass
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        # A real ffplay binary is several MB; a 0-byte / truncated extract
        # (e.g. an empty zip member) must NOT be reported as ready — remove it
        # so bin/ffplay stays "missing" rather than a broken stub a retry skips.
        ok = os.path.isfile(target) and os.path.getsize(target) > 100 * 1024
        if os.path.isfile(target) and not ok:
            try:
                os.unlink(target)
            except OSError:
                pass
        say("ffplay is ready." if ok
            else "ffplay download did not produce a usable binary.")
        return ok
    except (urllib.error.URLError, OSError, ValueError) as e:
        say(f"ffplay download failed: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        say(f"ffplay download failed: {e}")
        return False


def is_valid_stream_url(url: Any) -> bool:
    """Accept only http(s) URLs.

    Guards yt-dlp against argument injection — a value starting with ``-``
    would otherwise be read as an option (``--exec`` / ``--config-location``)
    — and rejects junk before we ever spawn the extractor.
    """
    if not isinstance(url, str):
        return False
    u = url.strip()
    return u.lower().startswith(("http://", "https://"))


def _clamp_divisions(divisions: Any) -> int:
    try:
        n = int(divisions)
    except (TypeError, ValueError):
        return 3
    return max(MIN_DIVISIONS, min(MAX_DIVISIONS, n))


def clamp_divisions(raw: Any, lo: int = MIN_DIVISIONS, hi: int = MAX_DIVISIONS,
                    default: int = 3) -> int:
    """Clamp a grid-divisions value to ``[lo, hi]``; non-ints → ``default``.

    Guards the ffmpeg ``tile=NxN`` filter from garbage input.
    """
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


def select_format(quality: Optional[str], divisions: int) -> str:
    """yt-dlp ``-f`` selector. Manual quality wins; Auto lowers resolution as
    the grid gets denser (a 50x50 tile needs far less than 1080p). Always ends
    in ``/best`` so playback never fails just because a resolution is gone.
    """
    heights = {
        "1080p": 1080, "720p": 720, "480p": 480,
        "360p": 360, "240p": 240, "144p": 144,
    }
    h = heights.get(quality or "")
    if h is None:  # Auto
        if divisions <= 2:
            h = 1080
        elif divisions <= 4:
            h = 720
        elif divisions <= 17:
            h = 360
        elif divisions <= 35:
            h = 240
        else:
            h = 144
    return "best[height<={h}]/best[height<={h2}]/best".format(h=h, h2=h + 360)


def next_backoff(prev: float, cap: float = 30) -> float:
    """Exponential reconnect backoff, capped. Pure (so it is unit-testable)."""
    return min(prev * 2, cap)


def build_tile_filter(divisions: int) -> str:
    """ffmpeg ``-vf`` chain that tiles the source into an n×n grid.

    Grabs n*n successive frames and arranges them in a grid, bumping fps so the
    grid refreshes at the source rate. Preserved for callers/tests that don't
    pass a monitor size; :func:`core.monitors.tile_filter_for` is the
    size-aware variant the multi-monitor engine uses.
    """
    n = _clamp_divisions(divisions)
    return f"fps=source_fps*{n}*{n},tile={n}x{n}"


def build_yt_dlp_command(
    yt_dlp: str, url: str, divisions: int, quality: Optional[str] = None
) -> list[str]:
    """Return the robust yt-dlp argv that streams ``url`` to stdout.

    Multiple player clients, retries + socket timeout, a height-based ``-f``
    selector, and the URL after a ``--`` end-of-options marker so a value
    starting with ``-`` can never be parsed as an option (injection).
    """
    return [
        yt_dlp,
        "--extractor-args", "youtube:player_client=" + YT_PLAYER_CLIENTS,
        "--no-warnings",
        "--retries", "10",
        "--socket-timeout", "15",
        "-f", select_format(quality, _clamp_divisions(divisions)),
        "-o", "-",
        "--", url,
    ]


def build_commands(
    yt_dlp: str,
    ffplay: str,
    url: str,
    divisions: int,
    fmt: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """Return ``(yt_dlp_argv, ffplay_argv)`` for the single-window pipeline.

    Preserved for existing callers/tests. ``fmt`` (when given) overrides the
    auto height-based selector. ``--`` guards the URL against flag injection.
    """
    if fmt:
        yt_cmd = [
            yt_dlp,
            "--extractor-args", "youtube:player_client=" + YT_PLAYER_CLIENTS,
            "--no-warnings", "--retries", "10", "--socket-timeout", "15",
            "-f", fmt, "-o", "-", "--", url,
        ]
    else:
        yt_cmd = build_yt_dlp_command(yt_dlp, url, divisions)
    ffplay_cmd = [
        ffplay, "-autoexit", "-loglevel", "error", "-hide_banner", "-fs",
        "-vf", build_tile_filter(divisions), "-i", "-",
    ]
    return yt_cmd, ffplay_cmd


def _looks_like_pip_ytdlp(update_output: Optional[str]) -> bool:
    """True if ``yt-dlp -U`` output indicates a pip/package-manager install
    (which ``-U`` cannot self-update). Matches yt-dlp's specific phrases.
    Deliberately not a bare 'pip' substring (would false-match 'broken pipe').
    """
    s = (update_output or "").lower()
    needles = (
        "with pip", "via pip", "use pip", "pip or your package manager",
        "package manager", "tarball", "setup.py", "you installed",
        "use that to update", "not a self-contained",
    )
    return any(n in s for n in needles)


# --------------------------------------------------------------------------- #
#  Engine
# --------------------------------------------------------------------------- #
class TilingController:
    """Start/stop a robust, self-healing yt-dlp → ffplay tiling engine.

    Public surface preserved for existing callers: :meth:`is_running`,
    :meth:`start`, :meth:`stop`. A background worker thread runs the
    reconnect/backoff loop; it touches the UI only through the ``status`` /
    ``log`` callbacks passed to :meth:`start` (this module imports no tkinter).
    """

    HEALTHY_SECONDS = 60       # a session this long resets backoff + self-heal
    HEAL_AFTER_FAILS = 2       # consecutive failures before we update yt-dlp
    REHEAL_EVERY = 20          # re-arm self-heal every N failures
    OFFLINE_AFTER_FAILS = 10   # surface an explicit "offline" status past this
    ANNOUNCE_AFTER = 2.0       # only show "Playing" once a session survives this
    FANOUT_QUEUE_MAX = 32      # per-consumer buffer (small, to keep tiles synced)
    FANOUT_PUT_TIMEOUT = 2.0   # a consumer full THIS long is genuinely wedged

    def __init__(self) -> None:
        # _lock is an RLock because _start() calls _terminate().
        self._lock = threading.RLock()
        self._ytdlp: Optional[subprocess.Popen] = None
        self._ffplay: list[subprocess.Popen] = []
        self._consumers: list[dict[str, Any]] = []
        self._fanout_thread: Optional[threading.Thread] = None
        self._fanout_stop: Optional[threading.Event] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_tail: Optional[Any] = None
        self._worker: Optional[threading.Thread] = None
        # Monotonic run token. Every start() bumps it; each worker captures the
        # value it was launched with and exits the moment self._generation no
        # longer matches — so a revived OLD worker (e.g. one that was wedged in
        # a slow self-heal while start() flipped _play_flag back to True for a
        # NEW run) cannot keep looping over the new run's shared state.
        self._generation = 0

        # Run options (set on start, read by the worker thread).
        self._play_flag = False
        self._url = ""
        self._divisions = 3
        self._explicit_fmt: Optional[str] = None
        self._quality: Optional[str] = None
        self._mute = False
        self._multi_monitor = False
        self._selected_monitors: list[int] = []
        self._auto_restart = True
        self._status: StatusCb = lambda _m, _c: None
        self._log: LogCb = lambda _m: None
        self._fail_count = 0
        self._healed = False

    # ---- public API ------------------------------------------------------- #
    def is_running(self) -> bool:
        return bool(self._play_flag) or (
            self._worker is not None and self._worker.is_alive()
        )

    def start(
        self,
        url: str,
        divisions: int,
        *,
        fmt: Optional[str] = None,
        quality: Optional[str] = None,
        mute: bool = False,
        multi_monitor: bool = False,
        selected_monitors: Optional[list[int]] = None,
        auto_restart: bool = True,
        log: Optional[LogCb] = None,
        status: Optional[StatusCb] = None,
    ) -> None:
        """Launch the tiling engine on a background worker thread.

        Raises :class:`FileNotFoundError` if ffplay is absent or
        :class:`RuntimeError` on a blank/invalid URL; the caller surfaces the
        message. ``fmt`` (an explicit yt-dlp ``-f`` string, kept for back-compat
        callers) takes precedence over the ``quality`` band when both are given.
        """
        url = (url or "").strip()
        if not url:
            raise RuntimeError("Enter a stream URL first.")
        if not is_valid_stream_url(url):
            raise RuntimeError("Please enter a valid http(s) video URL.")
        if not ffplay_available():
            raise FileNotFoundError(
                "Video Tiling needs ffplay, which isn't bundled. Put "
                "ffplay[.exe] in the app's bin folder (it ships with the "
                "full ffmpeg build) or install ffmpeg so ffplay is on PATH."
            )
        self.stop()
        # Bump the run token FIRST: even if the prior worker is wedged (slow
        # self-heal / long backoff) and outlives the join below, it will see a
        # newer self._generation and exit instead of reviving its loop now that
        # _play_flag goes back to True for THIS run. (The race the generation
        # guard closes; the join below is only a best-effort tidy wait.)
        self._generation += 1
        # Best-effort wait for any prior worker to finish its non-blocking
        # teardown so we don't run two engines at once. Poll in short slices up
        # to a hard cap; if it is still wedged we proceed anyway — correctness
        # no longer depends on it exiting first (the generation guard does).
        old = self._worker
        if old is not None and old is not threading.current_thread():
            deadline = time.monotonic() + 5.0
            while old.is_alive() and time.monotonic() < deadline:
                old.join(timeout=0.25)

        self._url = url
        self._divisions = _clamp_divisions(divisions)
        # An explicit fmt overrides the quality band. We translate fmt into the
        # worker by storing it; select_format is bypassed when _explicit_fmt set.
        self._explicit_fmt = fmt
        self._quality = quality
        self._mute = bool(mute)
        self._multi_monitor = bool(multi_monitor)
        self._selected_monitors = list(selected_monitors or [])
        self._auto_restart = bool(auto_restart)
        self._status = status or (lambda _m, _c: None)
        self._log = log or (lambda _m: None)
        self._fail_count = 0
        self._healed = False
        self._play_flag = True

        self._log(
            f"Tiling {url} into a {self._divisions}×{self._divisions} grid"
            + (" (multi-monitor)" if multi_monitor else "")
            + "…"
        )
        my_gen = self._generation
        self._worker = threading.Thread(
            target=self._run, args=(my_gen,), daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        """Signal stop + fast non-blocking teardown (the UI never freezes).

        The worker's own terminal :meth:`_terminate` does the thread joins off
        the main thread.
        """
        if self._play_flag:
            logger.info("tiling: stop requested")
        self._play_flag = False
        self._terminate(join=False)

    def update_yt_dlp(
        self, *, silent: bool = True, log: Optional[LogCb] = None
    ) -> bool:
        """Run ``yt-dlp -U`` (with a pip fallback) on a background thread.

        Returns immediately (``True`` if the update thread was started). The
        actual update result is reported through ``log``. Gated so it never
        does the wrong thing in a frozen build: there ``-m pip`` would relaunch
        the app, so we log a "update manually" note instead.
        """
        cb = log or self._log

        def worker() -> None:
            self._self_heal_ytdlp(cb)

        threading.Thread(target=worker, daemon=True).start()
        return True

    # ---- command building ------------------------------------------------- #
    def _yt_dlp_argv(self, yt_path: str) -> list[str]:
        explicit = self._explicit_fmt
        if explicit:
            return [
                yt_path,
                "--extractor-args", "youtube:player_client=" + YT_PLAYER_CLIENTS,
                "--no-warnings", "--retries", "10", "--socket-timeout", "15",
                "-f", explicit, "-o", "-", "--", self._url,
            ]
        return build_yt_dlp_command(
            yt_path, self._url, self._divisions, self._quality
        )

    def _targets(self) -> tuple[list[_monitors.Monitor], bool]:
        mons = _monitors.list_monitors()
        targets = _monitors.select_monitors(
            mons, self._selected_monitors, self._multi_monitor
        )
        return targets, self._multi_monitor

    def _ffplay_argv(
        self, ff_path: str, mon: _monitors.Monitor, single: bool, muted: bool
    ) -> list[str]:
        # A SINGLE window uses true fullscreen (-fs). A multi-window wall uses a
        # borderless window placed on exactly one monitor (keyed on the target
        # COUNT, not the multi flag, so a 1-of-N selection still fills its
        # screen instead of leaving a desktop sliver).
        vf, ow, oh = _monitors.tile_filter_for(
            mon["width"], mon["height"], self._divisions
        )
        win = ["-fs"] if single else _monitors.window_opts_for(mon, ow, oh)
        audio = ["-an"] if muted else []
        return (
            [ff_path, "-i", "-", "-vf", vf, "-autoexit",
             "-loglevel", "warning", "-hide_banner"]
            + audio + win
        )

    # ---- run-token / activity guard --------------------------------------- #
    def _is_active(self, my_gen: int) -> bool:
        """True while THIS worker's run is the live one.

        A worker stays active only while a stop has not been requested AND its
        launch generation is still the current one. A revived OLD worker (whose
        generation was superseded by a newer start()) returns False here and
        exits, even though _play_flag is back to True for the new run.
        """
        return bool(self._play_flag) and self._generation == my_gen

    # ---- process lifecycle ------------------------------------------------ #
    def _start(self, my_gen: int) -> None:
        self._terminate(join=True)  # clean slate
        if not self._is_active(my_gen):
            return

        # Re-resolve tools every start so a transient absence self-recovers.
        yt_path = bundled_binary("yt-dlp")
        ff_path = ffplay_path()
        if not (os.path.isfile(yt_path) or shutil.which(yt_path)):
            raise RuntimeError("yt-dlp not found on PATH")
        if not (os.path.isfile(ff_path) or shutil.which(ff_path)):
            raise RuntimeError("ffplay not found on PATH")

        targets, multi = self._targets()
        muted = self._mute
        single = len(targets) <= 1
        logger.info(
            "tiling start: url=%s divisions=%d windows=%d multi=%s muted=%s",
            self._url, self._divisions, len(targets), multi, muted,
        )

        ytdlp = subprocess.Popen(
            self._yt_dlp_argv(yt_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            # CREATE_NO_WINDOW on Windows; start_new_session=True on POSIX so
            # kill_process_tree can killpg this child's OWN group (not the app's).
            **new_session_kwargs(),
        )
        # Drain yt-dlp stderr into a ring buffer so the log can say WHY a
        # session dropped (HTTP 403, format gone, geo-block, …).
        stderr_tail: "collections.deque[str]" = collections.deque(maxlen=40)
        stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(ytdlp.stderr, stderr_tail),
            daemon=True,
        )
        stderr_thread.start()

        ffplay: list[subprocess.Popen] = []
        consumers: list[dict[str, Any]] = []
        stop_event: Optional[threading.Event] = None
        fanout_thread: Optional[threading.Thread] = None
        try:
            if single:
                # One window reads the download directly (no fan-out thread).
                ffplay = [
                    subprocess.Popen(
                        self._ffplay_argv(ff_path, targets[0], True, muted),
                        stdin=ytdlp.stdout, stderr=subprocess.DEVNULL,
                        # See yt-dlp spawn: own session/group for safe teardown.
                        **new_session_kwargs(),
                    )
                ]
                # Let ffplay own the read end so yt-dlp gets SIGPIPE if it dies.
                if ytdlp.stdout:
                    ytdlp.stdout.close()
            else:
                # One window per monitor; the single download is fanned out to
                # each via its own bounded queue + writer thread, so one slow
                # screen cannot head-of-line-block the whole wall. Only the
                # first window keeps audio (rest get -an) to avoid echo.
                stop_event = threading.Event()
                for i, mon in enumerate(targets):
                    proc = subprocess.Popen(
                        self._ffplay_argv(ff_path, mon, False, muted or i > 0),
                        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        # See yt-dlp spawn: own session/group for safe teardown.
                        **new_session_kwargs(),
                    )
                    c: dict[str, Any] = {
                        "proc": proc,
                        "q": queue.Queue(maxsize=self.FANOUT_QUEUE_MAX),
                        "dead": False,
                    }
                    c["thread"] = threading.Thread(
                        target=self._consumer_writer, args=(c,), daemon=True
                    )
                    c["thread"].start()
                    ffplay.append(proc)
                    consumers.append(c)
                fanout_thread = threading.Thread(
                    target=self._fanout,
                    args=(ytdlp.stdout, stop_event, consumers),
                    daemon=True,
                )
                fanout_thread.start()
        except Exception:
            # A launch failure mid-setup (e.g. a later monitor's ffplay) must
            # not orphan the consumer-writer threads already started for the
            # earlier monitors: across reconnect attempts those daemon threads
            # would leak unbounded. Mirror the not-published teardown — signal
            # the fan-out stop_event and wake/join each started consumer (its
            # ffplay is killed below, and a None sentinel unblocks a writer
            # idle on an empty queue) — BEFORE re-raising.
            if stop_event:
                stop_event.set()
            kill_process_tree(ytdlp, force=True)
            for p in ffplay:
                kill_process_tree(p, force=True)
            # Reap what we just killed, exactly like _terminate does. Without
            # this, a launch failure that repeats across reconnect attempts
            # (the engine loops on it) would pile up POSIX zombies — the same
            # leak the _reap helper was added to close on the normal path.
            reap: list[Optional[subprocess.Popen]] = [ytdlp, *ffplay]
            self._reap(reap)
            for c in consumers:
                try:
                    c["q"].put_nowait(None)
                except Exception:  # noqa: BLE001
                    pass
            for c in consumers:
                t = c.get("thread")
                if t is not None:
                    try:
                        t.join(timeout=2)
                    except Exception:  # noqa: BLE001
                        pass
            raise

        # Publish under the lock. If a Stop landed during the launch (or a new
        # run superseded this worker), tear the freshly-built pipeline down
        # instead of leaving it orphaned.
        with self._lock:
            published = self._is_active(my_gen)
            if published:
                self._ytdlp = ytdlp
                self._stderr_tail = stderr_tail
                self._stderr_thread = stderr_thread
                self._ffplay = ffplay
                self._consumers = consumers
                self._fanout_stop = stop_event
                self._fanout_thread = fanout_thread
        if not published:
            if stop_event:
                stop_event.set()
            kill_process_tree(ytdlp, force=True)
            for p in ffplay:
                kill_process_tree(p, force=True)
            # Reap the killed children (see the launch-failure path above):
            # a Stop/restart that raced this launch must not leave un-waited
            # processes behind.
            reap: list[Optional[subprocess.Popen]] = [ytdlp, *ffplay]
            self._reap(reap)

    def _drain_stderr(self, stream: Any, tail: Any) -> None:
        """Keep the last lines of a subprocess's stderr for diagnosis."""
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                try:
                    line = raw.decode("utf-8", "ignore").rstrip()
                except Exception:  # noqa: BLE001
                    line = str(raw)
                if line:
                    tail.append(line)
        except Exception:  # noqa: BLE001
            pass

    def _retire(self, c: dict[str, Any]) -> None:
        """Retire one fallen-behind consumer. KILL the ffplay first (so a writer
        blocked in stdin.write faults out immediately), THEN close the pipe.
        Killing also flips poll(), so _alive() trips and the wall relaunches.
        """
        c["dead"] = True
        kill_process_tree(c["proc"], force=True)
        try:
            if c["proc"].stdin:
                c["proc"].stdin.close()
        except Exception:  # noqa: BLE001
            pass

    def _fanout(
        self, source: Any, stop_event: threading.Event,
        consumers: list[dict[str, Any]],
    ) -> None:
        """Reader: copy the one download to every consumer's queue.

        A consumer that cannot keep up is RETIRED (killed) rather than having
        bytes dropped (dropping bytes corrupts its container stream). A retired
        window fails _alive() (its dead flag + its now-exited process) so the
        wall relaunches promptly.
        """
        try:
            while not stop_event.is_set():
                chunk = source.read(65536) if source else b""
                if not chunk:
                    break
                live = 0
                for c in consumers:
                    if c.get("dead"):
                        continue
                    try:
                        c["q"].put(chunk, timeout=self.FANOUT_PUT_TIMEOUT)
                        live += 1
                    except queue.Full:
                        logger.warning(
                            "tiling fan-out: a player fell behind; retiring it"
                        )
                        self._retire(c)
                if live == 0:
                    break
        except Exception:  # noqa: BLE001
            pass
        finally:
            for c in consumers:
                try:
                    c["q"].put_nowait(None)
                except Exception:  # noqa: BLE001
                    pass

    def _consumer_writer(self, c: dict[str, Any]) -> None:
        """One per ffplay window: drain its queue to that window's stdin."""
        q, stdin = c["q"], c["proc"].stdin
        try:
            while True:
                chunk = q.get()
                if chunk is None:
                    break
                if stdin is None:
                    break
                stdin.write(chunk)
                stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                if stdin:
                    stdin.close()
            except Exception:  # noqa: BLE001
                pass

    def _alive(self) -> bool:
        # Require the download AND every player window to be alive. "all" (not
        # "any") means a single dead monitor in a multi-screen wall triggers a
        # clean relaunch instead of leaving that screen black. A consumer the
        # fan-out RETIRED is also treated as not-alive immediately.
        #
        # Snapshot the shared fields under the lock: a UI-thread Stop runs
        # _terminate concurrently and nulls self._ytdlp / rebinds the lists, so
        # reading self._ytdlp truthy and THEN calling .poll() on it unlocked
        # could hit None.poll() (AttributeError). The snapshot is consistent;
        # the (cheap) poll() calls then run outside the lock.
        with self._lock:
            ytdlp = self._ytdlp
            consumers = list(self._consumers)
            ffplay = list(self._ffplay)
        if not ytdlp or ytdlp.poll() is not None:
            return False
        if any(c.get("dead") for c in consumers):
            return False
        if not ffplay:
            return False
        return all(p.poll() is None for p in ffplay)

    def _death_reason(self) -> str:
        """Short human note for the log; call BEFORE _terminate."""
        # Same race as _alive(): snapshot under the lock so a concurrent Stop
        # nulling self._ytdlp can't turn the truthy-then-.poll() into a crash.
        with self._lock:
            ytdlp = self._ytdlp
            ffplay = list(self._ffplay)
            stderr_tail = list(self._stderr_tail or [])
        if not ytdlp or ytdlp.poll() is not None:
            tail = stderr_tail[-3:]
            extra = " [yt-dlp: {}]".format(" | ".join(tail)) if tail else ""
            return "the download ended" + extra
        dead = [
            i + 1 for i, p in enumerate(ffplay) if p.poll() is not None
        ]
        if dead:
            return "player window(s) #{} exited".format(
                ",".join(map(str, dead))
            )
        return "an unknown reason"

    @staticmethod
    def _reap(procs: list[Optional[subprocess.Popen]]) -> None:
        """Best-effort wait() on already-killed children so they don't linger
        as POSIX zombies (<defunct>).

        ``kill_process_tree`` only SIGNALS the tree; on POSIX the killed child
        stays a zombie until its parent (this app process) reaps it via wait().
        The reconnect loop tears a pipeline down on every dropped session, so
        over a long outage those un-reaped yt-dlp/ffplay processes would pile
        up. A short, never-raising wait() here collects each one. No-op /
        harmless on Windows (no zombies; the handle is just closed cleanly).
        """
        for p in procs:
            if p is None:
                continue
            try:
                p.wait(timeout=2)
            except Exception:  # noqa: BLE001 — TimeoutExpired or already reaped
                pass

    def _terminate(self, join: bool = True) -> None:
        """Tear down the pipeline. Fast steps (signal + kill + close) under the
        lock; the (possibly blocking) thread joins run OUTSIDE the lock and only
        when ``join=True`` — so a UI Stop never blocks on them. Each process is
        KILLED BEFORE its stdin is closed (killing makes the next write fail at
        once; closing the write end alone would not unblock a wedged reader).
        """
        reap: list[Optional[subprocess.Popen]] = []
        with self._lock:
            if self._fanout_stop:
                self._fanout_stop.set()
            # Kill the download first (the fan-out reader then sees EOF).
            if self._ytdlp:
                kill_process_tree(self._ytdlp, force=True)
                reap.append(self._ytdlp)
                self._ytdlp = None
            # Kill each player, THEN close its stdin and wake any idle writer.
            for c in self._consumers:
                kill_process_tree(c["proc"], force=True)
                reap.append(c["proc"])
                try:
                    if c["proc"].stdin:
                        c["proc"].stdin.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    c["q"].put_nowait(None)
                except Exception:  # noqa: BLE001
                    pass
            for p in self._ffplay:
                kill_process_tree(p, force=True)
                reap.append(p)
                if p.stdin:
                    try:
                        p.stdin.close()
                    except Exception:  # noqa: BLE001
                        pass
            threads = (
                [self._fanout_thread, self._stderr_thread]
                + [c.get("thread") for c in self._consumers]
            )
            self._ffplay = []
            self._consumers = []
            self._fanout_thread = None
            self._fanout_stop = None
            self._stderr_thread = None

        # Reap the killed children OUTSIDE the lock (wait() can block briefly)
        # so each dropped session's processes don't linger as POSIX zombies.
        self._reap(reap)

        if join:
            cur = threading.current_thread()
            for t in threads:
                if t and t.is_alive() and t is not cur:
                    t.join(timeout=2)
                    if t.is_alive():
                        logger.warning(
                            "tiling: a worker thread did not exit within 2s"
                        )

    # ---- worker entry point ----------------------------------------------- #
    def _wait_backoff(self, backoff: float, my_gen: int) -> None:
        waited = 0.0
        while self._is_active(my_gen) and waited < backoff:
            time.sleep(0.25)
            waited += 0.25

    def _run_self_heal(self, my_gen: int) -> None:
        """Run the in-loop self-heal off the worker thread, then wait for it in
        short interruptible slices.

        ``_self_heal_ytdlp`` blocks for up to ~8 minutes in ``yt-dlp -U`` / pip
        (neither child is tree-tracked, so _terminate can't kill them). Running
        it synchronously here would make Stop unresponsive for that whole
        window. Instead spawn it on a daemon thread (same pattern as
        :meth:`update_yt_dlp`) and poll our run token, so a Stop / new-run flips
        _is_active and the worker returns to its backoff promptly while the
        self-heal finishes in the background.
        """
        done = threading.Event()

        def worker() -> None:
            try:
                self._self_heal_ytdlp(self._log)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        while self._is_active(my_gen) and not done.wait(timeout=0.25):
            pass

    def _run(self, my_gen: int) -> None:
        self._status("Starting…", "#b06a00")
        backoff: float = 3
        while self._is_active(my_gen):
            ran_for = 0.0
            reason = "an unknown reason"
            try:
                self._start(my_gen)
                if not self._is_active(my_gen):
                    break
                started = time.time()
                announced = False
                self._status("Connecting…", "#b06a00")
                while self._is_active(my_gen) and self._alive():
                    if not announced and (time.time() - started) >= self.ANNOUNCE_AFTER:
                        announced = True
                        self._status("Playing", "#1f7a1f")
                    time.sleep(0.4)
                if not self._is_active(my_gen):
                    break
                ran_for = time.time() - started
                reason = self._death_reason()
            except Exception as e:  # noqa: BLE001
                ran_for = 0.0
                reason = "could not start playback: {}".format(e)
                logger.warning(reason)
                will_retry = self._auto_restart
                msg = (
                    "Could not start playback — retrying…" if will_retry
                    else "Could not start playback."
                )
                self._status(msg, "#b06a00")

            self._terminate(join=True)
            if ran_for >= self.HEALTHY_SECONDS:
                backoff, self._fail_count, self._healed = 3, 0, False

            if not self._auto_restart:
                logger.info(
                    "tiling ended (ran %.0fs, %s); auto-restart off → stop",
                    ran_for, reason,
                )
                break

            self._fail_count += 1
            logger.info(
                "tiling dropped after %.0fs (%s; failure #%d); backoff %ss",
                ran_for, reason, self._fail_count, backoff,
            )
            self._log(f"Tiling dropped ({reason}); reconnecting in {int(backoff)}s")

            # Self-heal: repeated quick failures usually mean the site changed
            # something, so update yt-dlp. Re-arm periodically so a fix shipped
            # days into an outage is still picked up.
            if self._fail_count % self.REHEAL_EVERY == 0:
                self._healed = False
            # Skip self-heal when a stop / new run is already pending: launching
            # an ~8-minute yt-dlp -U/pip on the way out is pure waste.
            if (
                self._fail_count >= self.HEAL_AFTER_FAILS
                and not self._healed
                and self._is_active(my_gen)
            ):
                self._healed = True
                logger.info("tiling self-heal: updating yt-dlp")
                # Off-thread + interruptible so Stop stays responsive even while
                # the (blocking, up-to-~8-min) yt-dlp -U / pip runs.
                self._run_self_heal(my_gen)

            if self._fail_count >= self.OFFLINE_AFTER_FAILS:
                self._status(
                    "Stream appears offline — retrying every {}s".format(int(backoff)),
                    "#b06a00",
                )
            else:
                self._status(
                    "Reconnecting in {}s…".format(int(backoff)), "#b06a00"
                )

            self._wait_backoff(backoff, my_gen)
            backoff = next_backoff(backoff)

        # Terminal teardown. A superseded OLD worker must NOT run _terminate /
        # touch shared state here: a NEWER run already owns self._ytdlp/_ffplay
        # (its own _start began by tearing the old pipeline down), so a stray
        # _terminate from this loser would kill the live run's processes and
        # null the fields it just published — the corruption this guard closes.
        # On a plain Stop the generation is unchanged, so we DO tear down and
        # show "Stopped." as before.
        if self._generation == my_gen:
            self._terminate(join=True)
            self._status("Stopped.", "#666666")

    def _self_heal_ytdlp(self, log: LogCb) -> None:
        """Update yt-dlp via ``-U`` with a pip fallback. Blocking; run on a
        background thread by the caller. Gated so it does the right thing in a
        frozen build (where ``-m pip`` would relaunch the app)."""
        if getattr(sys, "frozen", False):
            # The bundled yt-dlp lives inside the read-only app
            # bundle/install dir — `-U` can't overwrite it (and the pip
            # fallback below is already disabled for frozen builds), so
            # don't even attempt it.
            log("yt-dlp update needs a manual upgrade (frozen build).")
            return
        path = bundled_binary("yt-dlp")
        if not (os.path.isfile(path) or shutil.which(path)):
            log("Update yt-dlp: not found on PATH.")
            return
        try:
            res = subprocess.run(
                [path, "-U"], capture_output=True, text=True,
                timeout=180, creationflags=_CREATE_NO_WINDOW,
            )
            out = ((res.stdout or "") + (res.stderr or "")).strip()
            ok = res.returncode == 0
            # `-U` only self-updates a STANDALONE binary. A pip / console-script
            # install refuses it; update via pip instead — but NOT in a frozen
            # build (there sys.executable is the app exe; '-m pip' would launch
            # a second app instead of updating yt-dlp).
            if not ok and _looks_like_pip_ytdlp(out):
                if getattr(sys, "frozen", False):
                    logger.warning(
                        "yt-dlp is a pip/source install but this is a frozen "
                        "build — update yt-dlp manually"
                    )
                    log("yt-dlp update needs a manual pip upgrade (frozen build).")
                    return
                logger.info("yt-dlp -U is a no-op on a pip install; using pip")
                res = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                    capture_output=True, text=True,
                    timeout=300, creationflags=_CREATE_NO_WINDOW,
                )
                ok = res.returncode == 0
            log("yt-dlp update finished." if ok else "yt-dlp update failed.")
        except Exception as e:  # noqa: BLE001
            logger.warning("yt-dlp update error: %s", e)
            log("yt-dlp update failed.")
