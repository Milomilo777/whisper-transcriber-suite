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


def test_peak_and_dbfs():
    assert av.pcm_to_peak(_silence(0.05)) == 0.0
    assert av.pcm_to_peak(_tone(0.05, amplitude=0.5)) == pytest.approx(0.5, abs=0.01)
    assert av.to_dbfs(0.0) == av.METER_FLOOR_DB
    assert av.to_dbfs(1.0) == pytest.approx(0.0)
    assert av.to_dbfs(0.5) == pytest.approx(-6.02, abs=0.05)
    assert av.meter_fraction(av.METER_FLOOR_DB) == 0.0
    assert av.meter_fraction(0.0) == 1.0


def _curve(seed=1):
    import random

    t = [0.0]
    c = av.IOS9Curve((255, 0, 0), rng=random.Random(seed), clock=lambda: t[0])
    return c, t


def test_ios9_curve_spawns_grows_and_respawns():
    c, t = _curve()
    c.advance(0.2)
    assert 2 <= c.no_of_curves <= 4
    assert all(a > 0 for a in c.amplitudes)
    for _ in range(200):  # grow in, then (after the despawn timeout) die out
        t[0] += 16
        c.advance(0.2)
    assert all(a == 0.0 for a in c.amplitudes)
    first_spawn = c.spawn_at
    c.note_max_y(10.0)
    c.note_max_y(0.0)  # collapsed below DEAD_PX -> respawn on next advance
    assert c.needs_spawn
    t[0] += 16
    c.advance(0.2)
    assert c.spawn_at != first_spawn and not c.needs_spawn


def test_ios9_frames_scale_the_step():
    a, _ = _curve(3)
    b, _ = _curve(3)
    a.advance(0.2, frames=2.0)
    b.advance(0.2)
    b.advance(0.2)
    assert a.amplitudes == pytest.approx(b.amplitudes)
    assert a.phases == pytest.approx(b.phases)


def test_ios9_curve_is_bounded_and_attenuated_at_the_edges():
    np = pytest.importorskip("numpy")
    c, t = _curve(5)
    for _ in range(30):
        t[0] += 16
        c.advance(0.2)
    i = np.arange(-av.GRAPH_X, av.GRAPH_X + 0.01, 0.05)
    y = c.y_values(i, 100.0, 1.0)
    assert (y >= 0).all() and y.max() <= 100.0
    assert y.max() > 5.0
    assert y[0] < 0.5 and y[-1] < 0.5


def test_render_frame_draws_waves_and_meter():
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    quiet = av.render_frame(400, 120, [], 0.0, meter_db=av.METER_FLOOR_DB)
    assert quiet.size == (400, 120)
    c, t = _curve(7)
    for _ in range(40):
        t[0] += 16
        c.advance(0.2)
    loud = av.render_frame(400, 120, [c], 1.0, meter_db=-3.0, peak_db=-1.0)
    import numpy as np
    bright = lambda img: int(np.asarray(img).sum())  # noqa: E731
    assert bright(loud) > bright(quiet)
    # The meter band turns red near 0 dBFS.
    r, g, b = loud.getpixel((362, 120 - 5))
    assert r > 150 and g < 120


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
    assert viz._photo is not None  # idle strip painted

    viz.set_active(True)
    for _ in range(10):
        viz.push_frames(_tone(0.05, amplitude=0.6), RATE)
        viz._tick()  # drain synchronously on the Tk thread
    root.update()
    assert viz.amplitude > av.IDLE_AMPLITUDE
    assert viz.meter_db > -10.0
    photo = viz._photo
    viz._tick()
    assert viz._photo is photo  # image reused, not recreated per frame
    viz.set_active(False)
    root.update()
    assert viz.amplitude == 0.0 and viz.meter_db == av.METER_FLOOR_DB
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
