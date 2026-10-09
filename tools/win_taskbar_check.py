"""Opens ONE small window and drives its taskbar button through the real Windows calls.

Uses the app's own code (``app.theme.win_taskbar``) with the real ITaskbarList3, but no
transcription: a fake queue walks through running 0..100 %, pause, resume, a failure, a badge
of 1, 3 and 12 jobs, and a finished job (flash). Look at the taskbar button while it runs, then
the script clears everything and closes itself. Windows only.

    python tools/win_taskbar_check.py            # about 14 seconds
    python tools/win_taskbar_check.py --fast     # shorter pauses, no waiting for you to look

Exit code 0 when every taskbar call returned a success HRESULT, 1 otherwise.
The start marker goes to a temporary folder, never into the real app data folder.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.theme import win_taskbar as wt  # noqa: E402


class Recorder:
    """Wraps the real native layer; remembers every HRESULT it returned."""

    def __init__(self, native: Any) -> None:
        self._native = native
        self.results: list[tuple[str, int]] = []
        self.flashes = 0

    def __getattr__(self, name: str):
        target = getattr(self._native, name)
        if not callable(target):
            return target

        def call(*args, **kwargs):
            value = target(*args, **kwargs)
            if name == "flash":
                self.flashes += 1
            if name.startswith("set_") or name in ("create",):
                self.results.append((name, value if isinstance(value, int) else 0))
            return value
        return call


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("Windows only")
        return 0
    step_ms = 150 if args.fast else 700

    marker_dir = Path(tempfile.mkdtemp(prefix="wts_taskbar_check_"))
    wt.marker_path = lambda: marker_dir / wt.MARKER_NAME           # type: ignore[assignment]
    recorder: Recorder | None = None

    def factory() -> Recorder:
        nonlocal recorder
        recorder = Recorder(wt._Native())
        return recorder

    wt._native_factory = factory                                   # type: ignore[assignment]
    wt.set_enabled(True)

    root = tk.Tk()
    root.title("taskbar check (closes itself)")
    root.geometry("360x80+80+80")
    tk.Label(root, text="Watch this window's taskbar button").pack(expand=True)
    queue: list[SimpleNamespace] = []
    root.queue = queue                                             # type: ignore[attr-defined]
    root.download_queue = []                                       # type: ignore[attr-defined]
    root.chime_on_complete_var = SimpleNamespace(get=lambda: True)  # type: ignore[attr-defined]

    def job(status: str, progress: float = 0) -> SimpleNamespace:
        return SimpleNamespace(status=status, progress=progress)

    primary = job("running", 0)
    script: list[tuple[str, object]] = [("running 0 percent (marquee)", lambda: queue.append(primary))]
    for pct in (10, 35, 60, 85):
        script.append((f"running {pct} percent", lambda p=pct: setattr(primary, "progress", p)))
    script += [
        ("paused (yellow)", lambda: setattr(primary, "status", "paused")),
        ("running again", lambda: setattr(primary, "status", "running")),
        ("3 jobs in the queue (badge 3)", lambda: queue.extend([job("waiting"), job("waiting")])),
        ("12 jobs in the queue (badge 9+)", lambda: queue.extend(job("waiting") for _ in range(9))),
        ("a job failed (red)", lambda: queue.append(job("error"))),
        ("only waiting jobs left (badge, no bar)", lambda: [setattr(primary, "status", "cancelled")]),
        ("everything done (cleared)", lambda: queue.clear()),
    ]
    # a finished job: the flash fires when this window is not the foreground window
    finishing = job("running", 50)
    script += [
        ("one more job running; the window is minimised", lambda: (queue.append(finishing), root.iconify())),
        ("it finished (flash if the window is behind)", lambda: setattr(finishing, "status", "finished")),
        ("cleared again", lambda: queue.clear()),
    ]

    state = {"i": 0, "clock": 0.0}

    def tick() -> None:
        if state["i"] >= len(script):
            wt.shutdown()
            root.after(300, root.destroy)
            return
        label, action = script[state["i"]]
        state["i"] += 1
        action()                                                   # type: ignore[operator]
        state["clock"] += 1.0                                      # one simulated second per step
        print(f"step {state['i']:2d}: {label}", flush=True)
        # the 2-per-second throttle is real time; the steps are far enough apart
        wt.sync(root, now=state["clock"] * 10)
        root.after(step_ms, tick)

    root.after(300, tick)
    root.mainloop()

    results = recorder.results if recorder else []
    bad = [(name, hr & 0xFFFFFFFF) for name, hr in results if hr < 0]
    print(f"taskbar calls: {len(results)}, refused: {len(bad)}, "
          f"flashes: {recorder.flashes if recorder else 0}")
    for name, hr in bad:
        print(f"  refused {name}: HRESULT {hr:#x}")
    leftover = list(marker_dir.glob("*"))
    print(f"start marker left behind: {bool(leftover)}")
    if not results:
        print("no taskbar call was made")
        return 1
    return 1 if bad or leftover else 0


if __name__ == "__main__":
    sys.exit(main())
