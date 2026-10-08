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
