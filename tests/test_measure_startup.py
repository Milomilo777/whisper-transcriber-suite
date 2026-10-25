"""measure_startup must clean up only the process it spawned.

The old cleanup ran ``taskkill /F /IM WhisperTranscriberSuite.exe``: /IM
matches EVERY process with that image name, so measuring while the real
installed app was open force-killed the user's session, and measuring a
renamed copy (the documented usage) leaked the measured app.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import measure_startup as ms  # noqa: E402


def test_measure_kills_only_the_process_it_started(monkeypatch):
    class _Proc:
        pid = 4242

    seen: dict[str, object] = {}

    monkeypatch.setattr(ms.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(
        ms.subprocess, "run", lambda cmd, **k: seen.setdefault("cmd", cmd)
    )
    monkeypatch.setattr(ms, "_find_window_with_title", lambda pid, title: 99)
    monkeypatch.setattr(ms.time, "sleep", lambda _s: None)

    assert ms.measure(Path("some.exe")) is not None

    cmd = list(seen["cmd"])  # type: ignore[arg-type]
    assert "/PID" in cmd and "4242" in cmd, cmd
    assert "/IM" not in cmd, cmd
    assert "/T" in cmd, cmd  # the spawned worker tree goes with it
