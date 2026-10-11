"""Shared, process-wide guard for a heavy C-extension import/probe.

A real Windows native fault (``STATUS_BREAKPOINT``) was observed and
traced to Python's garbage collector running mid-import of a heavy
C-extension package (google-cloud-speech's protobuf/proto-plus stack, in
the confirmed case), triggered by unrelated allocation pressure
elsewhere in the process -- not by two threads importing the SAME
package at once. See ADR 0008 in ``docs/DECISIONS.md`` for the full
multi-round investigation.

``gc.disable()``/``gc.enable()`` are PROCESS-GLOBAL, not thread-local or
lock-scoped. An earlier version of this mitigation gave every guarded
call site (``core.alignment``, ``core.backends.availability``,
``core.backends.google_cloud_stt``, ``core.backends.whisper_cpp``,
``core.diarization``, ``core.hardware``, ``core.llm``, ``core.search``,
``core.separator``, ``core.voiceprint``) its OWN ``threading.Lock()``.
That does not actually serialize them against each other: two of these
probes running concurrently on different daemon threads (e.g. the
engine-status probe and the Hardware Wizard's re-probe) block on
DIFFERENT locks, so neither waits for the other. Whichever import
finishes first re-enables GC process-wide while the other thread's
import is still mid-construction -- reproducing the exact crash this
mitigation exists to prevent. ADR 0008 already documented multiple
concurrent probe threads racing in practice, so this is a realistic
scenario, not a hypothetical one.

Every guarded call site must therefore share ONE lock. This module is
that lock.
"""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager
from typing import Iterator

_lock = threading.RLock()


@contextmanager
def gc_disabled_import() -> Iterator[None]:
    """Serialize + disable GC for the duration of a risky heavy import.

    Blocks until any other guarded import elsewhere in the process
    finishes, then disables GC for the body, restoring the PRIOR
    process-wide GC state (not unconditionally re-enabling it) on exit.
    """
    with _lock:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            yield
        finally:
            if was_enabled:
                gc.enable()
