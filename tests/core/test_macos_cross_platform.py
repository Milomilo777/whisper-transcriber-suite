"""Cross-platform (macOS) branch tests for the new session features.

This host is Windows; these tests FORCE the macOS / POSIX code paths so the
mac-correct branches are exercised even though no Mac is available.

We deliberately do NOT mutate the real ``os.name`` (that breaks ``pathlib``
on Windows — it refuses to instantiate ``PosixPath``). Instead each test
installs a tiny ``_PosixOs`` shim — a proxy that forwards every attribute to
the real ``os`` EXCEPT ``name`` (forced to ``"posix"``) — onto the specific
module under test (e.g. ``_proc.os``). That flips only the
``os.name == "nt"`` guards in that module while leaving stdlib intact.

They prove the guards added/verified during the macOS-support pass:

  * core._proc: ``new_session_kwargs`` gives POSIX children their own session
    (``start_new_session``) and no Windows creationflags.
  * core.updates: the GitHub check is pure stdlib urllib — no winreg / Win32.

Hermetic: no tk.Tk(), no model, no real display, no network.
"""
from __future__ import annotations

import os
import sys

from core import _proc


class _PosixOs:
    """Proxy to the real ``os`` module that reports ``name == "posix"``.

    Forwarding everything else (path, makedirs, listdir, getpgid, ...) keeps
    the module-under-test fully functional while flipping its
    ``os.name == "nt"`` guards to the macOS branch. pathlib (which reads the
    real ``os.name``) is untouched.
    """

    name = "posix"

    def __getattr__(self, item):
        return getattr(os, item)


def _force_posix(monkeypatch, module):
    monkeypatch.setattr(module, "os", _PosixOs())


# --------------------------------------------------------------------------- #
#  core._proc — child processes get their own session on POSIX
# --------------------------------------------------------------------------- #
def test_new_session_kwargs_posix_shape(monkeypatch):
    """Forced-POSIX: kwargs isolate the child (start_new_session) and carry
    NO Windows creationflags."""
    _force_posix(monkeypatch, _proc)
    kw = _proc.new_session_kwargs()
    assert kw == {"start_new_session": True}


# --------------------------------------------------------------------------- #
#  core.updates — pure stdlib, no Win32 / registry (cross-platform)
# --------------------------------------------------------------------------- #
def test_updates_check_is_silent_and_platform_neutral(monkeypatch):
    """``check_for_update`` uses urllib only; a stubbed 404 (private repo)
    returns None on any platform — no winreg / Win32 involved."""
    from core import updates

    def _boom(*a, **k):
        raise updates.urllib.error.HTTPError(
            "http://x", 404, "Not Found", {}, None  # type: ignore[arg-type]
        )

    monkeypatch.setattr(updates.urllib.request, "urlopen", _boom)
    # Pretend we're on mac for good measure; the code path is identical.
    monkeypatch.setattr(sys, "platform", "darwin")
    assert updates.check_for_update(timeout=1) is None


def test_updates_module_has_no_winreg_import():
    """Static guard: the update check must not import winreg / windll."""
    from core import updates as _u

    with open(_u.__file__, "r", encoding="utf-8") as fp:
        src = fp.read()
    assert "winreg" not in src
    assert "windll" not in src
