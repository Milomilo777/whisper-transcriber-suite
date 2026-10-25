"""Managed ``llama-server`` child for "Ask (offline)" and its streaming client.

The pinned llama.cpp runtime (``core.llama_runtime``, ADR 0013) runs as a
child process of the app, reachable only from this computer:

* ``--host 127.0.0.1 --port 0``: the OS picks a free port; the app finds it
  from the child's listening socket (or the ``listening on`` log line).
* A fresh random API key per start, passed through the environment
  (``LLAMA_API_KEY``; argv is visible to other users) and never logged.
  Only ``/health`` answers without it. ``--cors-origins localhost`` keeps
  web pages of other sites from reading any answer.
* ``--offline``, ``--no-webui``, ``--reasoning off``, one slot, a small host
  prompt cache, ``--sleep-idle-seconds`` (the model leaves memory when idle;
  the next request loads it again).

No orphan server, however the app ends:

* Windows: the child is put in a Job Object with KILL_ON_JOB_CLOSE; when the
  app's process ends for any reason, Windows closes the handle and kills it.
* Every OS: a record per running server (pid, start time, exe, owner) under
  the runtime folder; the next start kills a server whose owner is gone,
  after checking that the pid still belongs to that exact program (never by
  image name). ``stop_all`` runs at interpreter exit.
* An unexpected exit is restarted once on the next request; a second one is
  an error the UI shows.

The client speaks the OpenAI-compatible streaming chat API over a plain
loopback ``http.client`` connection (no proxy, never a remote default URL).
Cancel closes the connection; the server then serves the next request.

Tk-free; safe to import from the worker, the server and the UI.
"""
from __future__ import annotations

import atexit
import http.client
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from . import llama_runtime
from ._proc import kill_process_tree, new_session_kwargs
from .config import user_log_dir

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
# Context window of the default model profile (ADR 0013 measurement: -c 8192).
DEFAULT_CONTEXT = 8192
# Measured load on the reference PC: 33.8-35.7 s (Gemma 4 E2B, AVX2 path).
# Older CPUs (SSE4.2 path) and slow disks are slower: allow ~8x.
DEFAULT_LOAD_TIMEOUT_S = 300.0
# Free memory asked for on top of the model's measured peak.
RAM_MARGIN_MB = 512
DEFAULT_CACHE_RAM_MB = 512
DEFAULT_IDLE_SLEEP_S = 300
# One socket read may wait this long: the first answer over a long
# transcript reads the whole prompt first (64 s for 3k tokens on the
# reference PC), and a sleeping server loads its model again.
DEFAULT_READ_TIMEOUT_S = 600.0
CONNECT_TIMEOUT_S = 5.0
# A single streamed line longer than this is not a chat chunk.
_MAX_LINE = 1 << 20
# A whole streamed reply larger than this is not an answer (a few thousand
# tokens are well under 1 MB of SSE).
_MAX_REPLY_BYTES = 16 << 20
_LISTENING_RE = re.compile(r"listening on http://127\.0\.0\.1:(\d+)")
_LOG_NAME = "llama-server.log"


class LocalLLMError(RuntimeError):
    """The offline AI engine could not start or answer; the message is for the user."""


@dataclass(frozen=True)
class ServerOptions:
    """What to run: the model file and its measured needs."""

    model: Path
    peak_ram_mb: int
    context: int = DEFAULT_CONTEXT
    threads: int = 0  # 0 = this computer's physical cores
    cache_ram_mb: int = DEFAULT_CACHE_RAM_MB
    idle_sleep_s: int = DEFAULT_IDLE_SLEEP_S
    load_timeout_s: float = DEFAULT_LOAD_TIMEOUT_S


# ---------------------------------------------------------------- checks


def physical_cores() -> int:
    try:
        import psutil  # noqa: PLC0415

        n = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001 - psutil missing: estimate below
        n = None
    if not n:
        n = max(1, (os.cpu_count() or 2) // 2)
    return int(n)


def available_ram_mb() -> int | None:
    try:
        import psutil  # noqa: PLC0415

        return int(psutil.virtual_memory().available // (1024 * 1024))
    except Exception:  # noqa: BLE001
        logger.warning("Could not read the free memory", exc_info=True)
        return None


def check_free_ram(peak_ram_mb: int, available_mb: int | None) -> None:
    """Refuse to start when the model would not fit in the free memory now."""
    if available_mb is None:
        return
    need = peak_ram_mb + RAM_MARGIN_MB
    if available_mb < need:
        raise LocalLLMError(
            f"The offline AI needs about {need / 1024:.1f} GB of free memory to start; "
            f"this computer has {available_mb / 1024:.1f} GB free right now. "
            "Close other programs and try again."
        )


def server_args(command: list[str], options: ServerOptions, threads: int) -> list[str]:
    """The full argv. The API key is NOT here: it travels in the environment."""
    return [
        *command,
        "--host", LOOPBACK,
        "--port", "0",
        "--no-webui",
        "--cors-origins", "localhost",
        "--no-cors-credentials",
        "--offline",
        "--reasoning", "off",
        "-c", str(options.context),
        "-t", str(threads),
        "-np", "1",
        "--cache-ram", str(options.cache_ram_mb),
        "--sleep-idle-seconds", str(options.idle_sleep_s),
        "-m", str(options.model),
    ]


# Variables that look like credentials stay with the app: the server needs none.
_SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE", re.IGNORECASE)


def server_env(key: str) -> dict[str, str]:
    """``llama_runtime.child_env()`` without credential-like variables, plus the API key."""
    env = {k: v for k, v in llama_runtime.child_env().items() if not _SECRET_NAME_RE.search(k)}
    env["LLAMA_API_KEY"] = key
    return env


def qa_messages(rules: str, evidence: str, question: str) -> list[dict[str, str]]:
    """Chat messages in prompt-cache order: rules and evidence first, the question last.

    Follow-up questions over the same evidence then reuse the server's cache
    and start answering in about a second (ADR 0013 measurement).
    """
    return [
        {"role": "system", "content": f"{rules.strip()}\n\n{evidence.strip()}"},
        {"role": "user", "content": question.strip()},
    ]


# ---------------------------------------------------------------- Windows Job Object


class _WinJob:
    """A Job Object that kills its processes when its last handle closes.

    The app keeps the only handle; when the app's process ends (even when it
    is killed), Windows closes it and ends the server.
    """

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    # Declared here so type checkers for other platforms know them too.
    _ctypes: Any
    _k32: Any
    _handle: int | None = None

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Job Objects exist only on Windows")
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class _Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _Basic),
                ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        self._ctypes = ctypes
        self._k32 = k32
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        self._handle = handle
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
                handle, self._EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.close()
            raise OSError(err, "SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        k32 = self._k32
        proc = k32.OpenProcess(self._PROCESS_SET_QUOTA | self._PROCESS_TERMINATE, False, pid)
        if not proc:
            raise OSError(self._ctypes.get_last_error(), f"OpenProcess({pid}) failed")
        try:
            if not k32.AssignProcessToJobObject(self._handle, proc):
                raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            k32.CloseHandle(proc)

    def close(self) -> None:
        """Close the handle; every process still in the job ends."""
        handle, self._handle = self._handle, None
        if handle:
            self._k32.CloseHandle(handle)


# ---------------------------------------------------------------- server records + reaper


def run_dir() -> Path:
    """One JSON record per running server (any app window on this account)."""
    return llama_runtime.runtime_root() / "run"


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_managed_exe(exe: str) -> bool:
    """True for a ``llama-server`` inside the app's runtime folder.

    The reaper kills nothing else, so a planted record cannot point it at
    an unrelated program.
    """
    path = Path(os.path.realpath(exe))
    if os.path.normcase(path.name) != os.path.normcase(llama_runtime.server_exe_name()):
        return False
    root = os.path.normcase(os.path.realpath(llama_runtime.runtime_root()))
    return os.path.normcase(str(path)).startswith(root + os.sep)


# A start time read again later can differ by a fraction of a second on
# Linux (it is derived from the boot time). Used only where a mismatch
# would mean killing something: an owner within this is "still running".
_START_TIME_SLACK_S = 2.0

_GONE = "gone"
_DENIED = "denied"


def _lookup(pid: int) -> tuple[float, str] | str:
    """(start time, executable path) of a live process, ``_GONE`` or ``_DENIED``."""
    import psutil  # noqa: PLC0415

    try:
        p = psutil.Process(pid)
        return float(p.create_time()), p.exe()
    except psutil.NoSuchProcess:  # ZombieProcess too
        return _GONE
    except (psutil.Error, OSError):
        return _DENIED


def _settled_lookup(pid: int, wait_s: float = 3.0) -> tuple[float, str] | str:
    """Like ``_lookup``, but gives a process that is still ending time to finish.

    A process that was just killed (by its Job Object, or by the reaper's
    caller) can answer "access denied" for a moment while Windows tears it
    down. Treating that as "alive but unreadable" would keep its record
    forever, so a ``_DENIED`` answer is asked again for up to ``wait_s``.
    A process that stays unreadable is still reported as ``_DENIED``.
    """
    found = _lookup(pid)
    deadline = time.monotonic() + wait_s
    while found == _DENIED and time.monotonic() < deadline:
        time.sleep(0.1)
        found = _lookup(pid)
    return found


def _process_identity(pid: int) -> tuple[float, str] | None:
    """(start time, executable path) of a live process, or None."""
    try:
        found = _lookup(pid)
    except Exception:  # noqa: BLE001 - psutil missing
        return None
    return found if isinstance(found, tuple) else None


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)


# Servers started by THIS process and not yet stopped, by pid.
_live: dict[int, "LocalLLMServer"] = {}
_live_lock = threading.Lock()
_atexit_registered = False


def reap_stale_servers(folder: Path | None = None) -> list[int]:
    """Kill servers whose app is gone; returns the pids killed.

    A record is acted on only when its owner (pid + start time) no longer
    runs, or is this process but the server is not one it still manages.
    The server is killed only when its pid still has the recorded start
    time AND executable, and that executable is the runtime's
    ``llama-server``: a recycled pid or a planted record never kills
    another program.
    """
    folder = folder or run_dir()
    try:
        records = sorted(folder.glob("llama-server-*.json"))
    except OSError as e:
        logger.warning("Could not list %s: %s", folder, e)
        return []
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        logger.warning("psutil is missing: cannot check for a leftover offline AI server")
        return []
    killed: list[int] = []
    me = os.getpid()
    for path in records:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            pid, created, exe = int(rec["pid"]), float(rec["created"]), str(rec["exe"])
            owner_pid, owner_created = int(rec["owner_pid"]), float(rec["owner_created"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("Ignoring an unreadable server record %s: %s", path, e)
            _remove(path)
            continue
        if pid <= 1 or pid == me:
            _remove(path)
            continue
        owner = _settled_lookup(owner_pid)
        if owner == _DENIED or (
                isinstance(owner, tuple) and abs(owner[0] - owner_created) <= _START_TIME_SLACK_S):
            if owner_pid != me:
                continue  # another app window's server (or cannot tell)
            with _live_lock:
                if pid in _live:
                    continue  # ours, still managed
        ident = _settled_lookup(pid)
        if ident == _DENIED:
            continue  # alive but unreadable: keep the record, never guess
        if (not isinstance(ident, tuple) or ident[0] != created or not _same_path(ident[1], exe)
                or not _is_managed_exe(ident[1])):
            _remove(path)  # already gone, or the pid now belongs to another program
            continue
        try:
            proc = psutil.Process(pid)
            proc.kill()
            proc.wait(timeout=10)
            killed.append(pid)
            logger.info("Stopped a leftover offline AI server (pid %d)", pid)
        except psutil.NoSuchProcess:
            pass
        except Exception as e:  # noqa: BLE001 - keep the record, try again next time
            logger.warning("Could not stop the leftover offline AI server pid %d: %s", pid, e)
            continue
        _remove(path)
    return killed


def stop_all() -> None:
    """Stop every server this process started (runs at interpreter exit)."""
    with _live_lock:
        servers = list(_live.values())
    for server in servers:
        try:
            server.stop()
        except Exception:  # noqa: BLE001 - exit path: stop the others anyway
            logger.warning("Could not stop the offline AI server", exc_info=True)


# ---------------------------------------------------------------- log file


_ROTATE_RETRY_S = 5.0
_DESCENDANTS_WAIT_S = 5.0


def _descendants(pid: int) -> list[Any]:
    try:
        import psutil  # noqa: PLC0415

        return psutil.Process(pid).children(recursive=True)
    except Exception:  # noqa: BLE001 - psutil missing or the process is already gone
        return []


def _wait_descendants(procs: list[Any]) -> None:
    """Wait (bounded) until the given child processes are really gone."""
    if not procs:
        return
    try:
        import psutil  # noqa: PLC0415

        _, alive = psutil.wait_procs(procs, timeout=_DESCENDANTS_WAIT_S)
    except Exception:  # noqa: BLE001
        return
    if alive:
        logger.warning("Offline AI server children still running after stop: %s", [p.pid for p in alive])


def _open_log(path: Path) -> tuple[Any, Path]:
    """Open a fresh log for one server run; the previous run's log is kept as ``.1``.

    Owner-only on Linux/macOS: error lines can quote parts of a prompt.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Side logs of earlier runs whose main log was still open (see below).
    for old in path.parent.glob(f"{path.stem}-*{path.suffix}"):
        try:
            old.unlink()
        except OSError:
            pass  # still open by a server that has not ended yet
    if path.exists():
        previous = path.with_name(path.stem + ".1" + path.suffix)
        # Windows keeps the file locked for a moment after the last writer ended
        # (a launcher's child still shutting down, an antivirus scan): retry briefly.
        deadline = time.monotonic() + _ROTATE_RETRY_S
        while True:
            try:
                os.replace(path, previous)
                break
            except OSError as e:
                if time.monotonic() < deadline and isinstance(e, PermissionError):
                    logger.info("Log %s is busy, retrying the rotation: %s", path, e)
                    time.sleep(0.1)
                    continue
                # Still open by a server that has not ended yet: write beside it.
                logger.warning("Could not rotate %s: %s", path, e)
                path = path.with_name(f"{path.stem}-{os.getpid()}-{int(time.time())}{path.suffix}")
                break
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    return os.fdopen(fd, "wb"), path


def _log_tail(path: Path, lines: int = 3) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-lines:]
    return " | ".join(tail)


# ---------------------------------------------------------------- the server


class LocalLLMServer:
    """One managed ``llama-server`` child and the streaming client for it.

    ``command`` replaces the runtime's ``llama-server`` (tests start a fake
    server script this way). ``on_progress(elapsed_s, timeout_s)`` is called
    while the model loads.
    """

    def __init__(
        self,
        options: ServerOptions,
        *,
        command: list[str] | None = None,
        log_path: Path | None = None,
        on_progress: Callable[[float, float], None] | None = None,
        read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        self.options = options
        self._command = command
        self._log_base = log_path or (user_log_dir() / _LOG_NAME)
        self.log_path = self._log_base
        self._on_progress = on_progress
        self.read_timeout_s = read_timeout_s
        # Held for state changes and during a load; stop() never waits for a
        # whole load: it bumps _stop_gen first and the load gives up within 0.25 s.
        self._lock = threading.RLock()
        self._stop_gen = 0
        self._proc: subprocess.Popen[Any] | None = None
        self._job: _WinJob | None = None
        self._record: Path | None = None
        self._port: int | None = None
        self._key = ""
        self._restarts = 0

    # ------------------------------------------------------------ state

    # Lock-free reads (one snapshot each): safe from the UI thread during a load.

    @property
    def pid(self) -> int | None:
        proc = self._proc
        return proc.pid if proc is not None else None

    @property
    def port(self) -> int | None:
        return self._port

    def running(self) -> bool:
        """Started, loaded and not exited. Never blocks."""
        proc, port = self._proc, self._port
        return proc is not None and port is not None and proc.poll() is None

    # ------------------------------------------------------------ start / stop

    def _resolve_command(self) -> list[str]:
        if self._command is not None:
            return list(self._command)
        reason = llama_runtime.unsupported_reason()
        if reason:
            raise LocalLLMError(reason)
        exe = llama_runtime.installed_server()
        if exe is None:
            raise LocalLLMError("The offline AI engine (llama.cpp) is not installed yet.")
        missing = llama_runtime.ensure_vc_runtime(exe.parent)
        if missing:
            raise LocalLLMError(llama_runtime.vc_runtime_message(missing))
        return [str(exe)]

    def start(self) -> None:
        """Start the server and wait until the model is loaded. Resets the restart allowance."""
        stop_gen = self._stop_gen
        with self._lock:
            self._restarts = 0
            self._start_locked(stop_gen)

    def _start_locked(self, stop_gen: int) -> None:
        if self._proc is not None:
            if self._proc.poll() is None and self._port is not None:
                return
            self._cleanup_locked()
        if not self.options.model.is_file():
            raise LocalLLMError(f"The offline AI model file is missing: {self.options.model}")
        reap_stale_servers()
        check_free_ram(self.options.peak_ram_mb, available_ram_mb())
        command = self._resolve_command()
        threads = self.options.threads or physical_cores()
        args = server_args(command, self.options, threads)
        key = secrets.token_urlsafe(32)
        env = server_env(key)
        exe_dir = Path(command[0]).parent
        log, self.log_path = _open_log(self._log_base)
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(exe_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **new_session_kwargs(),
            )
        except OSError as e:
            raise LocalLLMError(f"Could not start the offline AI engine: {e}") from e
        finally:
            log.close()
        self._proc, self._key, self._port = proc, key, None
        # Managed before its record exists, so no reaper can take it for a leftover.
        with _live_lock:
            _live[proc.pid] = self
            global _atexit_registered
            if not _atexit_registered:
                atexit.register(stop_all)
                _atexit_registered = True
        self._attach_job_locked(proc.pid)
        self._write_record_locked(proc.pid)
        try:
            self._wait_ready_locked(stop_gen)
        except BaseException:
            self._cleanup_locked()
            raise
        logger.info("Offline AI server ready (pid %d, port %d)", proc.pid, self._port or 0)

    def _attach_job_locked(self, pid: int) -> None:
        if sys.platform != "win32":
            return
        try:
            job = _WinJob()
            job.assign(pid)
        except OSError as e:
            # The pid record + reaper still cover a crash of the app.
            logger.warning("Could not tie the offline AI server to the app's lifetime: %s", e)
            return
        self._job = job

    def _write_record_locked(self, pid: int) -> None:
        ident = _process_identity(pid)
        owner = _process_identity(os.getpid())
        if ident is None or owner is None:
            logger.warning("Could not record the offline AI server (pid %d) for a later clean-up", pid)
            return
        path = run_dir() / f"llama-server-{pid}.json"
        try:
            _write_record(path, {
                "pid": pid, "created": ident[0], "exe": ident[1],
                "owner_pid": os.getpid(), "owner_created": owner[0],
            })
        except OSError as e:
            logger.warning("Could not write %s: %s", path, e)
            return
        self._record = path

    def _find_port(self, pid: int) -> int | None:
        try:
            m = _LISTENING_RE.search(self.log_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        if m:
            return int(m.group(1))
        # llama-server binds before it loads the model but logs the port only
        # after loading: the socket table shows it earlier.
        try:
            import psutil  # noqa: PLC0415

            # A launcher (a venv's python.exe, a wrapper script) holds no socket
            # itself: the server is its child, so look at the whole tree.
            proc = psutil.Process(pid)
            for p in [proc, *proc.children(recursive=True)]:
                for conn in p.net_connections(kind="tcp"):
                    if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.ip == LOOPBACK:
                        return int(conn.laddr.port)
        except Exception:  # noqa: BLE001 - not yet listening, or not readable
            pass
        return None

    def _exit_message(self, code: int) -> str:
        if sys.platform == "win32" and (code & 0xFFFFFFFF) in llama_runtime.LOADER_FAILURES:
            return llama_runtime.vc_runtime_message([])
        tail = _log_tail(self.log_path)
        return f"The offline AI engine stopped while starting (exit code {code}). {tail}".strip()

    def _wait_ready_locked(self, stop_gen: int) -> None:
        proc = self._proc
        if proc is None:
            raise LocalLLMError("The offline AI engine is not running.")
        timeout = self.options.load_timeout_s
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            if self._stop_gen != stop_gen:
                raise LocalLLMError("The offline AI engine was stopped while loading.")
            code = proc.poll()
            if code is not None:
                raise LocalLLMError(self._exit_message(code))
            if self._port is None:
                self._port = self._find_port(proc.pid)
            if self._port is not None and self._health(self._port) == 200:
                return
            if elapsed > timeout:
                raise LocalLLMError(
                    f"The offline AI engine did not finish loading within {timeout:.0f} s.")
            if self._on_progress is not None:
                try:
                    self._on_progress(elapsed, timeout)
                except Exception:  # noqa: BLE001 - a UI callback must not stop the load
                    logger.warning("progress callback failed", exc_info=True)
            time.sleep(0.25)

    @staticmethod
    def _health(port: int) -> int | None:
        conn = http.client.HTTPConnection(LOOPBACK, port, timeout=CONNECT_TIMEOUT_S)
        try:
            conn.request("GET", "/health")
            resp = conn.getresponse()
            resp.read()
            return resp.status
        except (OSError, http.client.HTTPException):
            return None
        finally:
            conn.close()

    def stop(self) -> None:
        """Stop the server (and forget its key). Safe to call when not running.

        A load in progress in another thread gives up within about 0.25 s
        instead of finishing first.
        """
        self._stop_gen += 1  # read by the loading thread without the lock
        with self._lock:
            self._cleanup_locked()
            self._restarts = 0

    def _cleanup_locked(self) -> None:
        proc, self._proc = self._proc, None
        self._port, self._key = None, ""
        descendants: list[Any] = []
        if proc is not None:
            if proc.poll() is None:
                # A launcher (venv python.exe) leaves a child that keeps the log open.
                descendants = _descendants(proc.pid)
                if sys.platform == "win32":
                    # llama-server ignores taskkill's close request; it has no children.
                    try:
                        proc.kill()
                    except OSError:
                        pass
                else:
                    kill_process_tree(proc, force=False, timeout=5.0)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("The offline AI server (pid %d) did not stop in time", proc.pid)
            with _live_lock:
                _live.pop(proc.pid, None)
        if self._job is not None:
            self._job.close()
            self._job = None
        _wait_descendants(descendants)
        if self._record is not None:
            if proc is None or proc.poll() is not None:
                _remove(self._record)
            self._record = None

    def ensure_running(self) -> None:
        """Start on first use; after an unexpected exit restart once, then fail."""
        stop_gen = self._stop_gen
        with self._lock:
            self._ensure_running_locked(stop_gen)

    def _ensure_running_locked(self, stop_gen: int) -> None:
        if self._proc is None:
            self._start_locked(stop_gen)
            return
        code = self._proc.poll()
        if code is None and self._port is not None:
            return
        if self._restarts >= 1:
            self._cleanup_locked()
            raise LocalLLMError(
                "The offline AI engine stopped unexpectedly again "
                f"(exit code {code}). {_log_tail(self.log_path)}".strip())
        self._restarts += 1
        logger.warning("The offline AI server ended unexpectedly (exit code %s); restarting", code)
        self._cleanup_locked()
        self._start_locked(stop_gen)

    def _answered(self) -> None:
        """A complete answer: the next unexpected exit gets its own restart again."""
        self._restarts = 0

    # ------------------------------------------------------------ client

    def open_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> "ChatStream":
        """Send a streaming chat request; iterate the result for text pieces."""
        stop_gen = self._stop_gen
        with self._lock:
            self._ensure_running_locked(stop_gen)
            port, key = self._port, self._key
        if port is None:
            raise LocalLLMError("The offline AI engine is not running.")
        payload = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "cache_prompt": True,
        }).encode("utf-8")
        conn = http.client.HTTPConnection(LOOPBACK, port, timeout=CONNECT_TIMEOUT_S)
        try:
            conn.connect()
            sock = conn.sock
            if sock is None:
                raise ConnectionError("no socket")
            sock.settimeout(self.read_timeout_s)
            conn.request("POST", "/v1/chat/completions", body=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            })
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise LocalLLMError(self._lost_message(e)) from e
        # The reply is read by the stream, so cancel() also works while the
        # server is still reading the prompt and has not answered yet.
        return ChatStream(conn, sock, self._lost_message, on_complete=self._answered)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """The whole answer of one request (no streaming to the caller)."""
        with self.open_chat(messages, **kwargs) as stream:
            return "".join(stream).strip()

    def _lost_message(self, error: BaseException) -> str:
        proc = self._proc
        code = None
        if proc is not None:
            # A dying server drops the connection a moment before it exits.
            try:
                code = proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                code = None
        if code is not None:
            return f"The offline AI engine stopped unexpectedly (exit code {code}). {_log_tail(self.log_path)}".strip()
        return f"Lost the connection to the offline AI engine ({type(error).__name__}: {error})."


class ChatStream:
    """The text pieces of one streamed answer. ``cancel()`` works from any thread."""

    def __init__(
        self,
        conn: http.client.HTTPConnection,
        sock: socket.socket,
        lost: Callable[[BaseException], str],
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self._conn = conn
        # Kept apart from ``conn``: http.client drops conn.sock once the
        # response owns the connection, but the socket must stay reachable.
        self._sock = sock
        self._resp: http.client.HTTPResponse | None = None
        self._lost = lost
        self._on_complete = on_complete
        self._received = 0
        self._cancelled = threading.Event()
        self.finish_reason: str | None = None
        self.timings: dict[str, Any] = {}

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Stop the answer: the connection closes and the server stops generating.

        Only shuts the socket down: a read blocked in another thread then
        returns at once, and the reading side closes the connection.
        """
        self._cancelled.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if sys.platform == "win32":
            # Windows does not wake a read blocked in another thread on
            # shutdown (measured on Python 3.14); closing the handle does.
            try:
                fd = self._sock.detach()
                if fd >= 0:
                    socket.close(fd)
            except OSError:
                pass

    def close(self) -> None:
        for closer in ((self._resp.close if self._resp is not None else None), self._conn.close, self._sock.close):
            if closer is None:
                continue
            try:
                closer()
            except OSError:
                pass

    def __enter__(self) -> "ChatStream":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _complete(self) -> None:
        if self._on_complete is not None:
            self._on_complete()

    def _response(self) -> http.client.HTTPResponse | None:
        """The reply's status and headers; None once cancelled."""
        if self._resp is not None:
            return self._resp
        try:
            resp = self._conn.getresponse()
        except (OSError, ValueError, AttributeError, http.client.HTTPException) as e:
            if self._cancelled.is_set():
                return None
            raise LocalLLMError(self._lost(e)) from e
        self._resp = resp
        if resp.status != 200:
            body = resp.read(2000).decode("utf-8", errors="replace")
            raise LocalLLMError(f"The offline AI engine refused the question (HTTP {resp.status}): {body}")
        return resp

    def __iter__(self) -> Iterator[str]:
        try:
            resp = self._response()
            while resp is not None and not self._cancelled.is_set():
                try:
                    raw = resp.readline(_MAX_LINE)
                except (OSError, ValueError, AttributeError, http.client.HTTPException) as e:
                    if self._cancelled.is_set():
                        return
                    raise LocalLLMError(self._lost(e)) from e
                if not raw:
                    if self._cancelled.is_set():
                        return
                    if self.finish_reason is not None:
                        self._complete()
                        return
                    raise LocalLLMError(self._lost(ConnectionError("the answer ended early")))
                self._received += len(raw)
                if self._received > _MAX_REPLY_BYTES:
                    raise LocalLLMError("The offline AI engine sent a reply larger than expected.")
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    self._complete()
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as e:
                    raise LocalLLMError(f"The offline AI engine sent an unreadable reply: {e}") from e
                if not isinstance(chunk, dict):
                    continue
                if "error" in chunk:
                    raise LocalLLMError(f"The offline AI engine reported an error: {chunk['error']}")
                if isinstance(chunk.get("timings"), dict):
                    self.timings = chunk["timings"]
                for choice in chunk.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    if choice.get("finish_reason"):
                        self.finish_reason = str(choice["finish_reason"])
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield str(piece)
        finally:
            self.close()
