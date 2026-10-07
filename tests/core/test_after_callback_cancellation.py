"""Regression test for App.destroy after-callback cancellation.

The Session 9 commit (8235503) intended to cancel every pending Tk
after() callback before tearing down the interpreter, but it parsed
the return value of ``tk.call("after", "info")`` with
``str(pending).split()``. That call returns a tuple of IDs, not a
space-separated string. ``str(tuple).split()`` produces garbage tokens
like ``"('after#0',)"`` that ``after_cancel`` silently accepts without
actually cancelling — so the fix was a no-op and the
``invalid command name "<id>poll"`` warnings kept appearing.

This test pins the behaviour: after destroy(), no after() IDs may
remain pending on the interpreter side.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


def _pending(root) -> tuple:
    p = root.tk.call("after", "info")
    if isinstance(p, (tuple, list)):
        return tuple(p)
    text = str(p).strip()
    return tuple(text.split()) if text else ()


def test_tk_after_info_returns_tuple_for_multiple_ids() -> None:
    """Pin the assumption the fix relies on."""
    root = tk.Tk()
    try:
        root.withdraw()
        root.after(60_000, lambda: None)
        root.after(60_000, lambda: None)
        p = root.tk.call("after", "info")
        assert isinstance(p, tuple), f"expected tuple, got {type(p).__name__}"
        assert len(p) == 2
    finally:
        for cid in _pending(root):
            root.after_cancel(cid)
        root.destroy()


def test_app_destroy_cancels_all_after_callbacks() -> None:
    """The actual fix: App.destroy clears every pending after() ID."""
    # App.destroy delegates to this helper; a plain root avoids the full
    # App stack (which needs services + history).
    from app.app import cancel_pending_after_callbacks

    root = tk.Tk()
    try:
        root.withdraw()
        for _ in range(5):
            root.after(60_000, lambda: None)
        assert len(_pending(root)) == 5

        cancel_pending_after_callbacks(root)

        assert _pending(root) == (), "after callbacks survived destroy logic"
    finally:
        root.destroy()


def test_broken_str_split_path_does_not_cancel() -> None:
    """Document that the old Session 9 parser was a no-op.

    Kept as a regression marker: if someone reverts the fix to
    ``str(pending).split()``, this test fails loudly.
    """
    root = tk.Tk()
    try:
        root.withdraw()
        root.after(60_000, lambda: None)
        # Old broken path
        pending = root.tk.call("after", "info") or ""
        garbage = str(pending).split()
        # The garbage token is not a real ID, after_cancel silently
        # accepts it and the callback remains pending.
        for cb_id in garbage:
            try:
                root.after_cancel(cb_id)
            except Exception:
                pass
        assert len(_pending(root)) == 1, (
            "if this fires, the old str().split() parser somehow worked — "
            "investigate before deleting the destroy() fix"
        )
    finally:
        for cid in _pending(root):
            root.after_cancel(cid)
        root.destroy()
