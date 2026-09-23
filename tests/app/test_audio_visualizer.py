"""Tests for the Live tab audio visualizer (app/widgets/audio_visualizer.py).

Pure DSP helpers are tested with synthetic PCM — no sound card needed.
Widget tests build on a real Tk root but never start a session, matching
tests/app/test_live_tab.py conventions.
"""
from __future__ import annotations

import array
import math
import types

import pytest

from app.widgets import audio_visualizer as av

RATE = 16_000


def _tone(seconds: float, *, amplitude: float, freq: float = 220.0) -> bytes:
    n = int(seconds * RATE)
    peak = int(amplitude * 32767)
    samples = array.array(
        "h",
        (int(peak * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)),
    )
    return samples.tobytes()


def _silence(seconds: float) -> bytes:
    return _tone(seconds, amplitude=0.0)


# ---------------------------------------------------------- pure helpers


def test_rms_silence_is_zero():
    assert av.pcm_to_rms(b"") == 0.0
    assert av.pcm_to_rms(_silence(0.1)) == pytest.approx(0.0, abs=1e-3)


def test_rms_scales_with_amplitude():
    quiet = av.pcm_to_rms(_tone(0.1, amplitude=0.1))
    loud = av.pcm_to_rms(_tone(0.1, amplitude=0.8))
    assert 0.0 < quiet < loud <= 1.0


def test_level_is_log_scaled_and_clamped():
    assert av.level_from_rms(0.0) == 0.0
    assert av.level_from_rms(10 ** (-70 / 20)) == 0.0          # below the floor
    assert av.level_from_rms(1.0) == 1.0                       # clamped
    speech = av.level_from_rms(10 ** (-26 / 20))
    assert 0.6 < speech < 0.9                                  # normal speech reads high


def test_blend_pre_multiplies_opacity_over_background():
    assert av.blend(1.0) == "#%02x%02x%02x" % av._WAVE_RGB
    assert av.blend(0.0) == av._BG
    assert av.blend(0.5) not in (av.blend(0.0), av.blend(1.0))


def test_curve_points_flat_when_silent_and_bounded_when_loud():
    width, hm = 400.0, 49.0
    for curve in av.CURVES:
        flat = av.curve_points(curve, width, hm, 0.0, 1.0)
        assert flat[0] == 0.0 and flat[-2] == pytest.approx(width)
        assert all(y == pytest.approx(hm) for y in flat[1::2])
        loud = av.curve_points(curve, width, hm, 1.0, 1.0)
        ys = loud[1::2]
        assert max(abs(y - hm) for y in ys) > 0.0
        assert all(0.0 <= y <= 2 * hm for y in ys)


def test_curve_edges_are_attenuated_to_the_centre_line():
    # SiriWave's global attenuation pins both ends of every curve near the
    # centre, so the wave swells in the middle only.
    pts = av.curve_points(av.CURVES[-1], 400.0, 49.0, 1.0, 0.7)
    ys = pts[1::2]
    mid = ys[len(ys) // 2 - 10: len(ys) // 2 + 10]
    assert abs(ys[0] - 49.0) < 1.0 and abs(ys[-1] - 49.0) < 1.0
    assert max(abs(y - 49.0) for y in mid) > 5.0


# ------------------------------------------------------- meter plumbing


def test_live_session_forwards_frames_to_meter(tmp_path):
    from core import live

    seen: list[tuple[bytes, int]] = []
    session = live.LiveSession(
        transcribe_chunk=lambda _p: "",
        work_dir=str(tmp_path / "work"),
        on_meter=lambda pcm, rate: seen.append((pcm, rate)),
    )
    pcm = _tone(0.1, amplitude=0.5)
    session._on_frames(pcm, RATE)
    assert seen, "on_meter was not called"
    assert seen[0][0] == pcm
    assert seen[0][1] == RATE


def test_live_session_meter_exception_does_not_break_capture(tmp_path):
    from core import live

    def _boom(_pcm: bytes, _rate: int) -> None:
        raise RuntimeError("meter exploded")

    session = live.LiveSession(
        transcribe_chunk=lambda _p: "",
        work_dir=str(tmp_path / "work"),
        on_meter=_boom,
    )
    # Must not raise — a broken meter must never kill a session.
    session._on_frames(_tone(0.1, amplitude=0.5), RATE)


def test_live_session_without_meter_still_works(tmp_path):
    from core import live

    session = live.LiveSession(
        transcribe_chunk=lambda _p: "", work_dir=str(tmp_path / "work")
    )
    session._on_frames(_tone(0.1, amplitude=0.5), RATE)


# -------------------------------------------------------------- widget

# NOTE: a single module-scoped Tk root on purpose. Each extra Tk() in
# one pytest process costs a Tcl interpreter; the full hermetic suite
# already creates dozens (see tests/app/test_live_tab.py), and adding
# one root per widget test here tipped Windows into
# "_tkinter.TclError: invalid command name tcl_findLibrary" late in a
# full run while every file passed in isolation.

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover — headless CI without a display
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def test_widget_builds_pushes_and_idles(root):
    from tkinter import ttk

    frame = ttk.Frame(root)
    viz = av.AudioVisualizer(frame)
    viz.frame.pack(fill="both", expand=True)
    root.update()
    assert viz._active is False
    assert viz.amplitude == 0.0

    viz.set_active(True)
    for _ in range(10):
        viz.push_frames(_tone(0.05, amplitude=0.6), RATE)
        viz._tick()  # drain synchronously on the Tk thread
    root.update()
    assert viz.amplitude > av.IDLE_AMPLITUDE
    assert len(viz._line_ids) == len(av.CURVES)
    ids = list(viz._line_ids)
    viz._tick()
    assert viz._line_ids == ids  # items reused, not recreated per frame
    viz.set_active(False)
    root.update()
    assert viz.amplitude == 0.0 and viz._line_ids == []
    frame.destroy()


def test_live_tab_embeds_visualizer(root):
    """build_live_tab wires the meter section onto the tab."""
    from tkinter import ttk

    from app.widgets import live_tab

    app = types.SimpleNamespace()
    app.app_config = {}
    app.entry_file = "gui.py"
    app.logged: list[str] = []
    app.log = app.logged.append
    app.posted: list = []
    app.post_to_main = lambda fn: (app.posted.append(fn), fn())[1]
    app.after = root.after
    app.clipboard_clear = root.clipboard_clear
    app.clipboard_append = root.clipboard_append
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack(fill="both", expand=True)
    root.update()
    assert getattr(app, "live_visualizer", None) is not None
    # Start/stop lifecycle toggles the redraw loop without a session.
    live_tab._started(app, None, types.SimpleNamespace(drain_events=lambda: []))
    assert app.live_visualizer._active is True
    live_tab._stopped(app)
    assert app.live_visualizer._active is False
    frame.destroy()
