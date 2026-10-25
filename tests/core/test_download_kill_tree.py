"""Stopping a yt-dlp download ends its children first, so the frozen yt-dlp.exe
bootloader can leave by itself and delete its ``_MEI*`` unpack folder in TEMP
(about 24 MB stayed behind per ``taskkill /T /F``).

Hermetic: the process and the kill helpers are faked.
"""
from __future__ import annotations

from core import _proc


class _Proc:
    pid = 77

    def __init__(self, alive_after_children=False):
        self.alive = True
        self.alive_after_children = alive_after_children

    def poll(self):
        return None if self.alive else 0


def _tree_order(monkeypatch, *, children=1, exits_by_itself=True):
    order: list[str] = []
    proc = _Proc()
    monkeypatch.setattr(_proc, "_kill_descendants", lambda p: order.append("children") or children)
    monkeypatch.setattr(_proc, "_wait_for_exit", lambda p, t: order.append("wait") or exits_by_itself)
    monkeypatch.setattr(
        _proc, "kill_process_tree",
        lambda p, force=False, timeout=5.0: order.append(f"tree(force={force})"),
    )
    return proc, order


def test_download_kill_ends_the_children_first_then_waits(monkeypatch):
    proc, order = _tree_order(monkeypatch)
    _proc.kill_download_tree(proc, children_first=True)
    assert order == ["children", "wait"]        # the bootloader left by itself: no taskkill /T /F


def test_download_kill_falls_back_to_the_forced_tree_kill(monkeypatch):
    proc, order = _tree_order(monkeypatch, exits_by_itself=False)
    _proc.kill_download_tree(proc, children_first=True)
    assert order == ["children", "wait", "tree(force=True)"]


def test_download_kill_without_children_goes_straight_to_the_tree_kill(monkeypatch):
    proc, order = _tree_order(monkeypatch, children=0)
    _proc.kill_download_tree(proc, children_first=True)
    assert order == ["children", "tree(force=True)"]


def test_download_kill_off_windows_keeps_the_graceful_tree_kill(monkeypatch):
    proc, order = _tree_order(monkeypatch)
    _proc.kill_download_tree(proc, children_first=False)
    assert order == ["tree(force=False)"]


def test_download_kill_ignores_a_finished_or_missing_process(monkeypatch):
    proc, order = _tree_order(monkeypatch)
    proc.alive = False
    _proc.kill_download_tree(proc, children_first=True)
    _proc.kill_download_tree(None)
    assert order == []
