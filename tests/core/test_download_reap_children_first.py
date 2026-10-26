"""The cleanup after a failed download run ends yt-dlp's children first.

``_reap_process`` is the safety net of ``_run_task``: when an exception leaves yt-dlp running it
kills the process. A forced tree kill that ends the frozen yt-dlp.exe bootloader before its Python
child leaves the 24 MB ``%TEMP%\\_MEI*`` unpack folder behind, so the net must use the same
children-first order as Cancel, Pause and exit (``core._proc.kill_download_tree``).
"""
from __future__ import annotations

import types

from app.services import download_service as ds


def test_reap_process_kills_children_first(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ds, "kill_download_tree",
        lambda proc, **kw: calls.append(("download_tree", kw)),
    )
    monkeypatch.setattr(
        ds, "kill_process_tree",
        lambda proc, **kw: calls.append(("process_tree", kw)), raising=False,
    )
    proc = types.SimpleNamespace(
        stdout=None, poll=lambda: None, wait=lambda timeout=None: 0,
    )
    ds._reap_process(proc)  # type: ignore[arg-type]
    assert [c[0] for c in calls] == ["download_tree"]
    assert calls[0][1].get("children_first") is True
