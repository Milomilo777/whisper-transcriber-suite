"""Regression tests for the deep-audit thread-marshalling + selection fixes.

These exercise the high-severity fixes against a lightweight fake ``self`` so
no real Tk root is built (the Python-3.14 box intermittently can't construct
one, and the logic under test is pure orchestration):

  BUG A  refresh() must preserve the Queue Treeview selection across its
         every-500ms delete()+re-insert() rebuild, otherwise the per-task
         action bar disables itself ~0.5s after a click. Covered via the pure
         _iids_for_tasks helper AND a fake-tree refresh round-trip.
  BUG C  App.log_threadsafe must marshal the write onto the Tk main thread.

(BUG B covered the Video Tiling callbacks; its tests went with that feature.)
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("tkinter")

from app.app import App, _iids_for_tasks
from app.domain.tasks import TranscriptionTask, VideoDownloadTask


# --- BUG A: pure iid<->task remapping --------------------------------------


def test_iids_for_tasks_maps_selected_tasks_to_new_iids():
    t1, t2, t3 = (TranscriptionTask(f"/f{i}.mp4") for i in range(3))
    # A fresh rebuild assigned brand-new iids to the same task objects.
    new_row_map = {"I100": t1, "I101": t2, "I102": t3}
    # t1 and t3 were selected before the rebuild (their OLD iids are gone).
    assert _iids_for_tasks(new_row_map, [t1, t3]) == ["I100", "I102"]


def test_iids_for_tasks_empty_selection_is_empty():
    t1 = TranscriptionTask("/a.mp4")
    assert _iids_for_tasks({"X": t1}, []) == []


def test_iids_for_tasks_drops_tasks_no_longer_in_queue():
    t1, gone = TranscriptionTask("/a.mp4"), TranscriptionTask("/gone.mp4")
    # ``gone`` was selected but has since left the queue (not in row_map).
    assert _iids_for_tasks({"R1": t1}, [t1, gone]) == ["R1"]


def test_iids_for_tasks_matches_by_identity_not_equality():
    # Two distinct tasks for the same path must NOT be conflated.
    a = TranscriptionTask("/same.mp4")
    b = TranscriptionTask("/same.mp4")
    assert _iids_for_tasks({"K1": a, "K2": b}, [a]) == ["K1"]


# --- BUG A: refresh() preserves selection across the rebuild ---------------


class _FakeTree:
    """Just enough Treeview surface for refresh() + _selected_tasks()."""

    def __init__(self) -> None:
        self._children: list[str] = []
        self._sel: tuple[str, ...] = ()
        self._n = 0

    def get_children(self):
        return tuple(self._children)

    def delete(self, *iids):
        for i in iids:
            if i in self._children:
                self._children.remove(i)
        self._sel = tuple(s for s in self._sel if s in self._children)

    def insert(self, _parent, _index, values=(), tags=()):
        self._n += 1
        iid = f"I{self._n}"
        self._children.append(iid)
        return iid

    def selection(self):
        return self._sel

    def selection_set(self, iids):
        self._sel = tuple(iids)

    def focus(self, iid=None):
        if iid is not None:
            self._focus = iid
        return getattr(self, "_focus", "")


def _fake_refresh_app(queue):
    tree = _FakeTree()
    state = {"action_bar_calls": 0}

    app = types.SimpleNamespace(
        tree=tree,
        row_map={},
        queue=queue,
        _row_progress_text=lambda *_a: "",
        fmt_time=lambda _t: "",
        _refresh_window_title=lambda: None,
        _ensure_animation=lambda: None,
    )
    app._selected_tasks = lambda: App._selected_tasks(app)  # type: ignore[arg-type]

    def _update_bar() -> None:
        state["action_bar_calls"] += 1
        # The whole point: at the moment the action bar recomputes, the
        # selection must still be present.
        app._selection_at_bar = tree.selection()

    app._update_queue_action_bar = _update_bar
    app._state = state
    app._tree = tree
    return app


def test_refresh_preserves_selection_across_rebuild():
    t1, t2, t3 = (TranscriptionTask(f"/f{i}.mp4") for i in range(3))
    for t in (t1, t2, t3):
        t.status = "running"
    app = _fake_refresh_app([t1, t2, t3])

    # First refresh builds the rows.
    App.refresh(app)  # type: ignore[arg-type]
    iids = list(app._tree.get_children())
    assert len(iids) == 3
    # User selects the middle row.
    app._tree.selection_set((iids[1],))
    assert App._selected_tasks(app) == [t2]  # type: ignore[arg-type]

    # The next 500ms tick rebuilds the tree from scratch.
    App.refresh(app)  # type: ignore[arg-type]

    # Selection survived onto the new iid for the SAME task...
    assert App._selected_tasks(app) == [t2]  # type: ignore[arg-type]
    # ...and the action bar saw a non-empty selection when it recomputed.
    assert app._selection_at_bar != ()
    assert app._state["action_bar_calls"] == 2


def test_refresh_empty_selection_stays_empty():
    t1 = TranscriptionTask("/a.mp4")
    t1.status = "waiting"
    app = _fake_refresh_app([t1])
    App.refresh(app)  # type: ignore[arg-type]
    App.refresh(app)  # type: ignore[arg-type]
    assert App._selected_tasks(app) == []  # type: ignore[arg-type]
    assert app._selection_at_bar == ()


# --- BUG D: refresh_download_queue() preserves selection (2026-08-14) ------
#
# refresh_download_queue() had the exact same delete()+re-insert() rebuild
# as refresh() above, minus the selection-preservation fix -- unlike
# refresh(), it ran with NO snapshot/restore step, so a selected download
# row lost its selection on every drained event (frequent while a download
# is active), disabling the Pause/Resume/Cancel action bar mid-download.


def _fake_download_refresh_app(queue):
    tree = _FakeTree()
    app = types.SimpleNamespace(
        download_tree=tree,
        download_row_map={},
        download_queue=queue,
        _download_row_progress=lambda _t: 0,
        _row_progress_text=lambda *_a: "",
        fmt_time=lambda _t: "",
        _refresh_window_title=lambda: None,
        _ensure_animation=lambda: None,
        _update_download_action_bar=lambda: None,
    )
    app._selected_downloads = lambda: App._selected_downloads(app)  # type: ignore[arg-type]
    return app


def _download_task(title: str) -> VideoDownloadTask:
    return VideoDownloadTask(
        url=f"https://example.com/{title}", folder=".",
        format_label="best", format_info={}, title=title,
    )


def test_refresh_download_queue_preserves_selection_across_rebuild():
    d1, d2, d3 = (_download_task(f"v{i}") for i in range(3))
    for d in (d1, d2, d3):
        d.status = "running"
    app = _fake_download_refresh_app([d1, d2, d3])

    App.refresh_download_queue(app)  # type: ignore[arg-type]
    iids = list(app.download_tree.get_children())
    assert len(iids) == 3
    app.download_tree.selection_set((iids[1],))
    assert App._selected_downloads(app) == [d2]  # type: ignore[arg-type]

    # A drained download event rebuilds the tree from scratch, same as the
    # transcription queue's 500ms refresh().
    App.refresh_download_queue(app)  # type: ignore[arg-type]

    assert App._selected_downloads(app) == [d2]  # type: ignore[arg-type]


def test_refresh_download_queue_empty_selection_stays_empty():
    d1 = _download_task("only")
    d1.status = "waiting"
    app = _fake_download_refresh_app([d1])
    App.refresh_download_queue(app)  # type: ignore[arg-type]
    App.refresh_download_queue(app)  # type: ignore[arg-type]
    assert App._selected_downloads(app) == []  # type: ignore[arg-type]


# --- BUG B + C: thread marshalling -----------------------------------------


def _marshal_app():
    """Fake whose post_to_main records + runs the callable inline."""
    posted: list = []
    log_msgs: list[str] = []

    def _post(fn):
        posted.append(fn)
        fn()  # run inline so we can observe the marshalled effect

    app = types.SimpleNamespace(
        post_to_main=_post,
        log=lambda m: log_msgs.append(m),
        _posted=posted,
        _log_msgs=log_msgs,
    )
    return app


def test_log_threadsafe_marshals_through_post_to_main():
    app = _marshal_app()
    App.log_threadsafe(app, "hello from a worker thread")  # type: ignore[arg-type]
    # Went through post_to_main (not a direct widget write)...
    assert len(app._posted) == 1
    # ...and ultimately reached log().
    assert app._log_msgs == ["hello from a worker thread"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
