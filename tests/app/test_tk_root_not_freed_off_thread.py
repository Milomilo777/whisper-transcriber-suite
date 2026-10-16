"""The Tk root must never be finalized by a GC pass on a worker thread.

Freeing the Tcl interpreter off its own thread makes Tcl abort the whole
process ("Tcl_AsyncDelete: async handler deleted by the wrong thread",
Windows fatal exception 0x80000003). After ``app.run()`` returns, the App
is cyclic garbage unless something keeps it alive, and ``end_process``
flushes on a daemon thread where the next GC pass could free it.

Runs in a subprocess because the failure mode kills the interpreter.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent(
    """
    import gc, sys, threading, tkinter as tk
    sys.path.insert(0, sys.argv[1])
    gc.disable()  # only the explicit pass below may collect
    try:
        tk.Tk().destroy()
    except tk.TclError as e:
        print('NO_DISPLAY', e)
        sys.exit(0)
    import app, app.dpi, app.crash_report, app.i18n, core.offline

    app.dpi.enable_dpi_awareness = lambda: None
    core.offline.install_network_guard = lambda: None
    app.crash_report.install_excepthook = lambda: None
    app.i18n.init_language = lambda _load: None

    class FakeApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            self.cycle = self  # real App objects sit in reference cycles

        def mainloop(self, n=0):
            self.update()
            self.destroy()

    import app.app as app_module
    app_module.App = FakeApp
    app.run()

    worker = threading.Thread(target=gc.collect, name="not-main")
    worker.start()
    worker.join()
    print("survived", flush=True)
    """
)


def test_root_is_not_freed_on_a_worker_thread_after_run(tmp_path):
    script = tmp_path / "run_then_collect.py"
    script.write_text(SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode == 0 and "NO_DISPLAY" in proc.stdout:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "survived" in proc.stdout
    assert "wrong thread" not in proc.stderr
