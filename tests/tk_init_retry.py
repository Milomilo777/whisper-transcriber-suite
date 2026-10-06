"""Bounded retry for one transient Tcl start-up fault, used by ``tests/conftest.py``.

On Windows a full hermetic run (about 130-140 ``tk.Tk()`` roots into the run) occasionally
fails inside ``tk.Tk()`` itself with ``Can't find a usable init.tcl ... couldn't read file
".../init.tcl"``, although the file is readable from Python in the same process and every
affected test passes alone. The read fails transiently inside Tcl, before any test code runs.

The same fault surfaces under three spellings, depending on which library script Tcl failed to
read first: the ``init.tcl`` message above, ``Can't find a usable tk.tcl ...`` and the follow-on
``invalid command name "tcl_findLibrary"`` (``init.tcl`` defines that command, so it only appears
when ``init.tcl`` was not read). All three are retried; they are one fault.

Only those errors are retried, at most ``MAX_TRIES`` attempts in total. Any other
``TclError`` (for example "no display name") propagates at once. Every retry is printed and
counted; ``tests/conftest.py`` reports the count in the pytest summary, so the fault is never
hidden. After the last attempt the original error is raised unchanged.
"""
from __future__ import annotations

import sys
from typing import Any, Callable

MAX_TRIES = 3
_MARKERS = ("init.tcl", "tk.tcl", 'invalid command name "tcl_findLibrary"')

retries: list[str] = []


def is_init_tcl_error(exc: BaseException) -> bool:
    """True only for the Tcl "cannot read its library script" start-up error."""
    if type(exc).__name__ != "TclError":
        return False
    text = str(exc)
    return any(marker in text for marker in _MARKERS)


def wrap_init(original: Callable[..., Any]) -> Callable[..., Any]:
    """Return a ``Tk.__init__`` replacement that retries the init.tcl error."""

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, MAX_TRIES + 1):
            try:
                return original(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — re-raised unless it is the one known fault
                if not is_init_tcl_error(exc) or attempt == MAX_TRIES:
                    raise
                first_line = str(exc).splitlines()[0][:120]
                retries.append(first_line)
                print(
                    f"[tk-init-retry] tk.Tk() failed ({first_line}); "
                    f"retry {attempt}/{MAX_TRIES - 1}",
                    file=sys.stderr,
                )

    wrapper.__wrapped__ = original  # type: ignore[attr-defined]
    return wrapper
