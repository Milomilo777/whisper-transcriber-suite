"""Tests for :class:`app.dialogs.model_loading.ModelLoadingDialog`.

Two real failure modes are pinned here:

1. The dialog is closed from the worker-event poll loop through a
   *deferred* ``post_to_main(mark_success_and_close)`` callback. If the
   user clicked Cancel first, that late callback used to set
   ``success = True`` on the already-destroyed dialog — contradicting the
   ``False`` the caller had already read (and acted on by tearing the
   worker down). Whichever close path runs first must own the final
   ``success`` value.
2. The centre-on-parent maths clamped every coordinate to ``>= 0``.
   A parent on a monitor left of / above the primary has negative root
   coordinates, so the dialog was yanked onto the primary display; a
   minimised parent (Windows reports root coords ``-32000``) landed at
   ``(0, 0)``. The fallback must centre on the screen instead, and the
   absolute-negative ``+-`` geometry form must be preserved.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


class _FakeMaster:
    """Minimal stand-in for a Tk master window (no display needed)."""

    def __init__(
        self,
        *,
        x: int = 100,
        y: int = 100,
        w: int = 800,
        h: int = 600,
        viewable: bool = True,
        screen: tuple[int, int] = (1920, 1080),
    ) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h
        self.viewable = viewable
        self.screen = screen

    def winfo_viewable(self) -> bool:
        return self.viewable

    def winfo_rootx(self) -> int:
        return self.x

    def winfo_rooty(self) -> int:
        return self.y

    def winfo_width(self) -> int:
        return self.w

    def winfo_height(self) -> int:
        return self.h

    def winfo_screenwidth(self) -> int:
        return self.screen[0]

    def winfo_screenheight(self) -> int:
        return self.screen[1]


@pytest.fixture
def tk_root():
    """Hidden Tk root, destroyed at teardown (same pattern as the other
    dialog tests)."""
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _make_dialog(root):
    from app.dialogs.model_loading import ModelLoadingDialog

    dialog = ModelLoadingDialog(root)
    dialog.withdraw()
    return dialog


# ---------------------------------------------------------------------------
# Position maths (pure — no Tk needed)
# ---------------------------------------------------------------------------


def test_centres_over_parent_on_primary_monitor():
    from app.dialogs.model_loading import _compute_position

    assert _compute_position(_FakeMaster(x=100, y=100), 400, 200) == (300, 300)


def test_clamps_for_primary_parent_near_top_left_corner():
    from app.dialogs.model_loading import _compute_position

    # Parent itself is on the primary display, so keeping the dialog
    # on-screen by clamping to 0 cannot move it to another monitor.
    assert _compute_position(_FakeMaster(x=0, y=0, w=200, h=100), 420, 200) == (0, 0)


def test_keeps_negative_parent_coordinates_on_secondary_monitor():
    from app.dialogs.model_loading import _compute_position

    master = _FakeMaster(x=-1200, y=-50)
    # x = -1200 + (800 - 420)//2, y = -50 + (600 - 200)//2.
    # The old max(x, 0) clamp returned (0, 150) here — dialog jumped to
    # the primary display while its parent was on a monitor to the left.
    assert _compute_position(master, 420, 200) == (-1010, 150)


def test_minimised_parent_falls_back_to_screen_centre():
    from app.dialogs.model_loading import _compute_position

    master = _FakeMaster(x=-32000, y=-32000, viewable=False)
    # (1920 - 420)//2, (1080 - 200)//2 — parent-based maths would have
    # placed the dialog around -31600.
    assert _compute_position(master, 420, 200) == (750, 440)


# ---------------------------------------------------------------------------
# Close-path ordering (real dialog)
# ---------------------------------------------------------------------------


def test_late_ready_after_cancel_does_not_resurrect_success(tk_root):
    """The exact race: user Cancel runs, then the deferred
    post_to_main(mark_success_and_close) callback drains."""
    dialog = _make_dialog(tk_root)
    dialog.cancel()
    assert dialog.success is False

    dialog.mark_success_and_close()  # deferred ready callback, too late

    assert dialog.success is False, (
        "late ready callback must not overwrite the user's Cancel"
    )
    assert not dialog.winfo_exists()


def test_cancel_after_ready_keeps_success_true(tk_root):
    dialog = _make_dialog(tk_root)
    dialog.mark_success_and_close()
    assert dialog.success is True

    dialog.cancel()  # e.g. a queued WM_DELETE for the vanished window

    assert dialog.success is True
    assert not dialog.winfo_exists()


def test_repeated_close_calls_are_noops(tk_root):
    dialog = _make_dialog(tk_root)
    dialog.cancel()
    dialog.cancel()
    dialog.mark_success_and_close()
    assert dialog.success is False


# ---------------------------------------------------------------------------
# Geometry applied to the real dialog
# ---------------------------------------------------------------------------


def test_dialog_geometry_preserves_negative_parent_position(tk_root, monkeypatch):
    from app.dialogs.model_loading import ModelLoadingDialog

    monkeypatch.setattr(tk_root, "winfo_viewable", lambda: 1)
    monkeypatch.setattr(tk_root, "winfo_rootx", lambda: -1200)
    monkeypatch.setattr(tk_root, "winfo_rooty", lambda: -50)
    monkeypatch.setattr(tk_root, "winfo_width", lambda: 800)
    monkeypatch.setattr(tk_root, "winfo_height", lambda: 600)
    monkeypatch.setattr(tk_root, "winfo_screenwidth", lambda: 1920)
    monkeypatch.setattr(tk_root, "winfo_screenheight", lambda: 1080)

    dialog = ModelLoadingDialog(tk_root)
    dialog.withdraw()
    try:
        # "+-..." is Tk's absolute-negative form; a plain "-..." would
        # mean "px from the right screen edge" and land on the primary.
        assert "+-" in dialog.geometry(), (
            f"expected negative-position geometry, got {dialog.geometry()!r}"
        )
    finally:
        dialog.destroy()


def test_dialog_geometry_screen_centres_for_minimised_parent(tk_root, monkeypatch):
    from app.dialogs.model_loading import ModelLoadingDialog

    monkeypatch.setattr(tk_root, "winfo_viewable", lambda: 0)
    monkeypatch.setattr(tk_root, "winfo_rootx", lambda: -32000)
    monkeypatch.setattr(tk_root, "winfo_rooty", lambda: -32000)
    monkeypatch.setattr(tk_root, "winfo_screenwidth", lambda: 1920)
    monkeypatch.setattr(tk_root, "winfo_screenheight", lambda: 1080)

    dialog = ModelLoadingDialog(tk_root)
    dialog.withdraw()
    try:
        w, h = dialog.winfo_width(), dialog.winfo_height()
        expected = f"+{(1920 - w) // 2}+{(1080 - h) // 2}"
        assert expected in dialog.geometry(), (
            f"expected screen-centred {expected!r}, got {dialog.geometry()!r}"
        )
    finally:
        dialog.destroy()
