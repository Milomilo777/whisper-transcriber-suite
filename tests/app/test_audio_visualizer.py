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


def test_spectrum_silence_is_all_zeros():
    assert av.compute_spectrum(_silence(0.2), 16) == [0.0] * 16


def test_spectrum_empty_input_is_zeros():
    assert av.compute_spectrum(b"", 8) == [0.0] * 8


def test_spectrum_tone_lights_bands():
    levels = av.compute_spectrum(_tone(0.3, amplitude=0.6), 16)
    assert len(levels) == 16
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert max(levels) > 0.1


def test_spectrum_louder_tone_reads_higher():
    # Relative-peak normalisation means shape is stable, but the
    # loudness gate still separates whisper from silence-adjacent.
    whisper = av.compute_spectrum(_tone(0.3, amplitude=0.05), 16)
    normal = av.compute_spectrum(_tone(0.3, amplitude=0.6), 16)
    assert max(normal) >= max(whisper)


def test_heights_map_levels_to_pixels():
    assert av.heights_for_levels([0.0, 0.5, 1.0, 2.0, -1.0], 100) == [0, 50, 100, 100, 0]


def test_band_color_endpoints_differ():
    assert av.band_color(0.0) != av.band_color(1.0)
    assert av.band_color(0.0).startswith("#")
    assert av.band_color(1.0).startswith("#")


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
    assert viz._levels == [0.0] * viz.num_bands

    viz.set_active(True)
    viz.push_frames(_tone(0.2, amplitude=0.6), RATE)
    # Drain one tick synchronously on the Tk thread.
    viz._tick()
    root.update()
    assert max(viz._levels) > 0.0
    viz.set_active(False)
    root.update()
    assert viz._levels == [0.0] * viz.num_bands
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
