"""Windows DPI awareness (card C2.17): declared once, before the Tk root,
only on Windows; window sizes scale with the display."""
from __future__ import annotations

import ctypes
import sys
import types

import pytest

from app import dpi


@pytest.fixture(autouse=True)
def _fresh_awareness(monkeypatch):
    monkeypatch.setattr(dpi, "_awareness_result", None)


class _Fn:
    """A recording stand-in for one Win32 function."""

    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []
        self.argtypes = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def _windll(context=None, shcore=None, legacy=None):
    user32 = types.SimpleNamespace()
    if context is not None:
        user32.SetProcessDpiAwarenessContext = context
    if legacy is not None:
        user32.SetProcessDPIAware = legacy
    shcore_ns = types.SimpleNamespace()
    if shcore is not None:
        shcore_ns.SetProcessDpiAwareness = shcore
    return types.SimpleNamespace(user32=user32, shcore=shcore_ns)


def test_per_monitor_v2_is_declared_once():
    context = _Fn(1)
    windll = _windll(context=context)
    assert dpi.enable_dpi_awareness("win32", windll) == "per-monitor-v2"
    assert dpi.enable_dpi_awareness("win32", windll) == "per-monitor-v2"
    assert len(context.calls) == 1
    (arg,) = context.calls[0]
    assert isinstance(arg, ctypes.c_void_p) and arg.value == ctypes.c_void_p(-4).value
    assert context.argtypes == [ctypes.c_void_p]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_platforms_are_untouched(platform):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("windll must not be touched off Windows")

    assert dpi.enable_dpi_awareness(platform, Boom()) == "skipped"


def test_falls_back_to_shcore_on_older_windows():
    shcore = _Fn(0)
    windll = _windll(shcore=shcore)  # user32 has no ...Context function
    assert dpi.enable_dpi_awareness("win32", windll) == "per-monitor"
    assert shcore.calls == [(2,)]


def test_falls_back_to_legacy_system_aware():
    legacy = _Fn(1)
    windll = _windll(legacy=legacy)  # no Context function, no shcore function
    assert dpi.enable_dpi_awareness("win32", windll) == "system"
    assert len(legacy.calls) == 1


def test_already_declared_awareness_is_not_an_error():
    context = _Fn(0)  # Windows refuses: the manifest already fixed it
    shcore = _Fn(-2147024891)  # E_ACCESSDENIED
    legacy = _Fn(1)
    windll = _windll(context=context, shcore=shcore, legacy=legacy)
    assert dpi.enable_dpi_awareness("win32", windll) == "already-set"
    assert legacy.calls == []


def test_every_api_missing_does_not_raise():
    assert dpi.enable_dpi_awareness("win32", _windll()) == "unavailable"


def test_run_declares_awareness_before_the_root_exists(monkeypatch):
    import app as app_pkg

    order: list[str] = []

    class FakeApp:
        def __init__(self):
            order.append("root")

        def mainloop(self):
            order.append("mainloop")

    monkeypatch.setattr(dpi, "enable_dpi_awareness", lambda *a, **k: order.append("dpi"))
    monkeypatch.setitem(sys.modules, "app.app", types.SimpleNamespace(App=FakeApp))
    app_pkg.run()
    assert order == ["dpi", "root", "mainloop"]


class _Widget:
    def __init__(self, dpi_value, screen=(1920, 1080)):
        self._dpi, self._screen = dpi_value, screen

    def winfo_fpixels(self, _spec):
        return self._dpi

    def winfo_screenwidth(self):
        return self._screen[0]

    def winfo_screenheight(self):
        return self._screen[1]


@pytest.mark.parametrize(
    "dpi_value, factor", [(96, 1.0), (120, 1.25), (144, 1.5), (48, 1.0), (1000, 4.0)]
)
def test_scale_factor_on_windows(monkeypatch, dpi_value, factor):
    monkeypatch.setattr(sys, "platform", "win32")
    assert dpi.scale_factor(_Widget(dpi_value)) == pytest.approx(factor)
    assert dpi.scaled(_Widget(dpi_value), 100) == round(100 * factor)


def test_scale_factor_is_one_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert dpi.scale_factor(_Widget(192)) == 1.0
    # Not scaled, but still kept inside the screen (S10-5: a factor of 1.0 skipped the clamp,
    # so a 1180x720 viewer was taller than a 768-pixel screen with its panels).
    assert dpi.scaled_size(_Widget(192, screen=(1920, 1080)), 960, 640) == (960, 640)
    assert dpi.scaled_size(_Widget(192, screen=(800, 600)), 960, 640) == (760, 510)


def test_scaled_size_grows_with_the_display(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # A screen with room to spare (the margins now scale too, so 1080 pixels would clamp).
    assert dpi.scaled_size(_Widget(144, screen=(2560, 1440)), 960, 640) == (1440, 960)


def test_scaled_size_stays_inside_a_small_screen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # A 1366x768 laptop at 125 %: 1200x800 would not fit. Without a work area the margins
    # (40 x 90 at 96 dpi, for the taskbar and the title bar) scale too: 50 x 112.
    assert dpi.scaled_size(_Widget(120, screen=(1366, 768)), 960, 640) == (1200, 656)


def test_scaled_size_clamps_at_100_percent(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: None)
    # The viewer's 1180x720 on a 1366x768 laptop at 100 %.
    assert dpi.scaled_size(_Widget(96, screen=(1366, 768)), 1180, 720) == (1180, 678)


def test_scaled_size_uses_the_work_area(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # 1920x1080 at 150 % with a 60-pixel taskbar at the bottom.
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: (0, 0, 1920, 1020))
    w, h = dpi.scaled_size(_Widget(144), 1320, 900)
    assert (w, h) == (1920 - 24, 1020 - 72)
    assert dpi.work_area(_Widget(144)) == (0, 0, 1920, 1020, True)


def test_scaled_size_never_shrinks_below_the_floor(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: (0, 0, 300, 200))
    assert dpi.scaled_size(_Widget(96), 960, 640) == (320, 240)
    # A request under the floor stays as asked.
    assert dpi.scaled_size(_Widget(96), 200, 100) == (200, 100)


def test_work_area_reads_the_real_monitor():
    """The Win32 path answers for a real window (Windows only)."""
    if sys.platform != "win32":
        pytest.skip("Windows only")
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        root.withdraw()
        x, y, w, h, exact = dpi.work_area(root)
        assert exact is True
        assert w > 0 and h > 0
        assert h <= root.winfo_screenheight() and w <= root.winfo_screenwidth()
    finally:
        root.destroy()


def test_px_uses_the_remembered_scale(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dpi, "_process_factor", 1.0)
    assert dpi.px(560) == 560
    assert dpi.remember_scale(_Widget(144)) == 1.5
    assert dpi.px(560) == 840
    assert dpi.px(150) == 225


def test_scale_factor_survives_a_broken_widget(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    class Broken:
        def winfo_fpixels(self, _spec):
            raise RuntimeError("no display")

    assert dpi.scale_factor(Broken()) == 1.0


def test_an_unshown_dialog_measures_the_monitor_of_its_parent(monkeypatch):
    seen: list[int] = []

    class Win:
        def __init__(self, hwnd, mapped, master=None):
            self.hwnd, self.mapped, self.master = hwnd, mapped, master

        def winfo_ismapped(self):
            return self.mapped

        def winfo_toplevel(self):
            return self

        def state(self):
            return "normal"

        def winfo_id(self):
            seen.append(self.hwnd)
            raise RuntimeError("stop here: only the window asked about is under test")

    parent = Win(1, True)
    assert dpi._windows_work_area(Win(2, False, master=parent)) is None
    assert dpi._windows_work_area(Win(3, True, master=parent)) is None
    assert seen == [1, 3]


def test_a_mac_screen_keeps_room_for_the_menu_bar_title_bar_and_dock(monkeypatch):
    """The viewer's 1180x720 ran past the Dock of a 1280x800 Mac (S10-5 margins were for a taskbar)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert dpi.scaled_size(_Widget(96, screen=(1280, 800)), 1180, 720) == (1180, 660)
    assert dpi.scaled_size(_Widget(96, screen=(1280, 800)), 1320, 900) == (1240, 660)
    # A screen with room to spare, and a window already small enough, keep the asked size.
    assert dpi.scaled_size(_Widget(96, screen=(2560, 1440)), 1180, 720) == (1180, 720)
    assert dpi.scaled_size(_Widget(96, screen=(1280, 800)), 820, 520) == (820, 520)


def test_a_mac_window_keeps_the_floor_on_a_tiny_screen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert dpi.scaled_size(_Widget(96, screen=(600, 300)), 1180, 720) == (560, 240)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_the_screen_margins_are_unchanged_off_macos(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: None)
    assert dpi.scaled_size(_Widget(96, screen=(1280, 800)), 1180, 720) == (1180, 710)


# --- placing new windows (issue #8: Tk on Windows opened transient windows at (0, 0)) ---

_AREA = (0, 40, 1920, 1000)  # a taskbar docked at the top takes the first 40 px


def test_centred_position_puts_the_window_over_the_middle_of_its_parent():
    assert dpi.centred_position((400, 300, 800, 600), (400, 200), _AREA) == (600, 500)


def test_centred_position_counts_the_title_bar():
    assert dpi.centred_position((400, 300, 800, 600), (400, 200), _AREA, title=32) == (600, 484)


def test_centred_position_without_a_parent_uses_the_middle_of_the_area():
    assert dpi.centred_position(None, (400, 200), _AREA) == (760, 440)


def test_centred_position_never_puts_the_title_bar_under_a_top_taskbar():
    # The parent fills the top of the screen; a tall dialog over it would start above it.
    x, y = dpi.centred_position((0, 40, 1920, 300), (600, 700), _AREA, title=32)
    assert y == 40
    assert x == 660


def test_centred_position_keeps_the_window_inside_the_right_and_bottom_edges():
    x, y = dpi.centred_position((1700, 900, 400, 300), (600, 400), _AREA)
    assert (x, y) == (1920 - 600, 1040 - 400)


def test_centred_position_keeps_the_top_left_corner_of_a_window_larger_than_the_area():
    assert dpi.centred_position((0, 40, 1920, 1000), (2500, 1200), _AREA) == (0, 40)


def test_centred_position_works_on_a_monitor_left_of_the_primary_one():
    area = (-1920, 0, 1920, 1040)
    assert dpi.centred_position((-1600, 200, 800, 600), (400, 200), area) == (-1400, 400)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_place_over_leaves_other_platforms_alone(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)

    class _Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"touched {name}")

    dpi.place_over(_Untouchable(), _Untouchable())


def _windows_root():
    if sys.platform != "win32":
        pytest.skip("Windows only")
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    x, y, w, h, _exact = dpi.work_area(root)
    root.geometry(f"600x400+{x + 300}+{y + 200}")
    root.update()
    return root


def _centre(window):
    return window.winfo_rootx() + window.winfo_width() // 2, window.winfo_rooty() + window.winfo_height() // 2


@pytest.mark.parametrize("give_size", [True, False])
def test_a_transient_window_opens_over_its_parent_not_at_the_corner(give_size):
    """The real Tk behaviour behind issue #8, and the fix, on Windows."""
    import tkinter as tk
    from tkinter import ttk

    root = _windows_root()
    try:
        top = tk.Toplevel(root)
        top.transient(root)
        ttk.Label(top, text="A dialog " * 8).pack(padx=20, pady=40)
        if give_size:
            top.geometry("300x150")
            dpi.place_over(top, root, 300, 150)
        else:
            dpi.place_over(top, root)
        top.update()
        assert top.winfo_ismapped()
        assert (top.winfo_x(), top.winfo_y()) != (0, 0)
        (rx, ry), (tx, ty) = _centre(root), _centre(top)
        # Centred within the frame's border and title bar: geometry() places the frame.
        assert abs(rx - tx) <= dpi.scaled(top, 12)
        assert abs(ry - ty) <= dpi.scaled(top, dpi._TITLE_BAR)
    finally:
        root.destroy()


def test_place_over_keeps_a_grab_and_a_withdrawn_window_hidden():
    import tkinter as tk

    root = _windows_root()
    try:
        modal = tk.Toplevel(root)
        modal.transient(root)
        modal.grab_set()
        dpi.place_over(modal, root)
        modal.update()
        assert modal.winfo_ismapped()
        assert root.grab_current() is modal

        hidden = tk.Toplevel(root)
        hidden.withdraw()
        dpi.place_over(hidden, root)
        hidden.update()
        assert not hidden.winfo_ismapped()
    finally:
        root.destroy()


def test_the_unfixed_tk_default_is_the_corner():
    """Control: without place_over Tk on Windows really opens a transient window at (0, 0)."""
    import tkinter as tk

    root = _windows_root()
    try:
        top = tk.Toplevel(root)
        top.geometry("300x150")
        top.transient(root)
        top.update()
        assert (top.winfo_x(), top.winfo_y()) == (0, 0)
    finally:
        root.destroy()


def test_a_minimised_parent_keeps_its_own_monitor():
    """Minimised, a window sits at (-32000, -32000); its dialogs still belong on its monitor."""
    import tkinter as tk

    root = _windows_root()
    try:
        shown = dpi.work_area(root)
        root.iconify()
        root.update()
        assert root.state() == "iconic"
        top = tk.Toplevel(root)
        assert dpi.work_area(top) == shown
    finally:
        root.destroy()
