"""Cross-platform process-tree termination.

``Popen.terminate()`` / ``Popen.kill()`` only signal the immediate child.
On Windows ``TerminateProcess`` does NOT cascade to descendants, so a
worker's ffmpeg / ffprobe / demucs grandchildren (or yt-dlp's ffmpeg merge
child) are orphaned when the parent is killed — they keep running, hold the
source/output file handle open, burn CPU/RAM, and on CUDA can leave a stale
GPU allocation. These helpers kill the WHOLE tree:

  * Windows — ``taskkill /T`` (optionally ``/F``) walks the PID tree.
  * POSIX   — ``os.killpg`` the process group (the caller must spawn the
              process with ``start_new_session=True`` so it leads its own
              group); falls back to signalling just the parent.

Every function is best-effort and never raises.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def new_session_kwargs() -> dict[str, Any]:
    """Popen kwargs that isolate the child so its tree can be killed later.

    Windows: ``CREATE_NO_WINDOW`` (suppress console flash) — the tree is
    reached via ``taskkill /T`` on the PID, no extra flags needed.
    POSIX: ``start_new_session=True`` so the child leads a new process
    group that ``os.killpg`` can target.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def _wait_for_exit(process: Any, timeout: float) -> bool:
    """Poll ``process`` until it exits or ``timeout`` elapses. Never raises.

    Returns True once the process has exited, False on timeout. Used by the
    POSIX graceful path to decide whether a SIGTERM took effect before
    escalating to SIGKILL.
    """
    import time as _time

    deadline = _time.monotonic() + max(0.0, timeout)
    while True:
        try:
            if process.poll() is not None:
                return True
        except Exception:  # noqa: BLE001
            # Can't tell — treat as not-yet-exited so we still escalate.
            return False
        if _time.monotonic() >= deadline:
            return False
        _time.sleep(0.05)


def kill_process_tree(
    process: Any, *, force: bool = False, timeout: float = 5.0
) -> None:
    """Terminate ``process`` and all its descendants. Never raises.

    ``force=False`` requests a graceful tree terminate (taskkill without
    ``/F`` / ``SIGTERM``); ``force=True`` is the hard kill (``/F`` /
    ``SIGKILL``). Safe to call on a ``None`` or already-exited process.

    On POSIX the child must have been spawned with
    ``new_session_kwargs()`` (``start_new_session=True``) so it leads its
    own process group. If the PID instead resolves into THIS process's
    group, the group is deliberately not signalled — only the parent is —
    so a caller that skipped the spawn helper can never make the app kill
    itself (see the guard below).
    """
    if process is None:
        return
    pid = getattr(process, "pid", None)
    try:
        if pid is None or process.poll() is not None:
            return
    except Exception:  # noqa: BLE001
        return

    if os.name == "nt":
        # A graceful taskkill (no /F) posts WM_CLOSE to top-level windows.
        # yt-dlp.exe and its ffmpeg merge child are WINDOWLESS console
        # processes, so they ignore WM_CLOSE; taskkill then returns a
        # non-zero exit code ("This process can only be terminated forcefully
        # (with /F option)") and the tree keeps running. subprocess.run is
        # not check=True, so that failure was previously swallowed and the
        # Cancel/Pause/close paths orphaned yt-dlp/ffmpeg (holding the
        # .part/output handle). When the graceful pass reports failure, fall
        # through to a forced /F tree-kill so the tree actually dies.
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        try:
            result = subprocess.run(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=timeout,
            )
            rc = getattr(result, "returncode", 0)
            if force or not isinstance(rc, int) or rc == 0:
                return
            # Graceful taskkill could not terminate the tree — escalate to /F.
            logger.debug(
                "graceful taskkill for pid %s returned %s; escalating to /F",
                pid, rc,
            )
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=timeout,
            )
            return
        except Exception:  # noqa: BLE001
            logger.debug("taskkill tree failed for pid %s; signalling parent",
                         pid, exc_info=True)
    else:
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        sig = sigkill if force else signal.SIGTERM
        try:
            pgid = os.getpgid(pid)
            own_pgid = os.getpgid(0)
        except Exception:  # noqa: BLE001
            logger.debug("could not resolve process group for pid %s",
                         pid, exc_info=True)
        else:
            if pgid == own_pgid:
                # Safety net: every real call site spawns its child with
                # new_session_kwargs() so the tree leads its OWN group. If a
                # future call site forgets that (or the OS recycled the pid
                # onto a process in our group between poll() and here),
                # killpg would signal THIS process's group and take the app
                # down along with the tree. Refuse and fall through to the
                # parent-only signal.
                logger.debug(
                    "pid %s resolves to this process's own group (%s); "
                    "refusing to killpg our own group",
                    pid, own_pgid,
                )
            else:
                try:
                    os.killpg(pgid, sig)
                    if force or sigkill == signal.SIGTERM:
                        # Hard kill already sent, or this platform has no
                        # distinct SIGKILL — nothing left to escalate to.
                        return
                    # Graceful pass sent SIGTERM. A wedged child (stuck
                    # ffmpeg / demucs) can ignore it and survive, holding
                    # the source/output handle open. Mirror the Windows
                    # graceful->/F escalation: give the group up to
                    # ``timeout`` to exit, then SIGKILL the group.
                    if _wait_for_exit(process, timeout):
                        return
                    logger.debug(
                        "graceful SIGTERM for pid %s did not exit within "
                        "%.1fs; escalating to SIGKILL",
                        pid, timeout,
                    )
                    os.killpg(pgid, sigkill)
                    return
                except Exception:  # noqa: BLE001
                    logger.debug("killpg failed for pid %s; signalling parent",
                                 pid, exc_info=True)

    # Last resort: signal just the parent (better than nothing).
    try:
        process.kill() if force else process.terminate()
    except Exception:  # noqa: BLE001
        pass
