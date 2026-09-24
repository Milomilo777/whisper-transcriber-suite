"""gui.main() must call multiprocessing.freeze_support() before anything else.

In a frozen build multiprocessing re-launches the app executable for its
helper processes; freeze_support() diverts those launches. It has to run
before the worker branches and argparse see argv (macOS open issue #1 in
docs/MACOS_BUILD_NOTES.md).
"""
from __future__ import annotations

import multiprocessing
import sys

import gui


def test_freeze_support_runs_before_the_worker_branch(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(multiprocessing, "freeze_support", lambda: calls.append("freeze"))
    import core.worker as worker

    monkeypatch.setattr(worker, "main", lambda: calls.append("worker") or 0)
    monkeypatch.setattr(sys, "argv", ["gui.py", "--worker"])
    assert gui.main() == 0
    assert calls == ["freeze", "worker"]
