"""The interface's translated speed texts say in English exactly what core.speed_meter says,
and while the speed is measured they also say how much audio is done (deep review,
2026-10-21: "measuring speed..." stood for about a minute on a CPU run). Windowless.
"""
from __future__ import annotations

import types

import pytest

from app.domain import speed_text as st
from core import speed_meter as sm

SECONDS = [0, 0.4, 1, 7.4, 59.6, 60, 61, 185, 3599, 3600, 3660, 6372.48, 7200, float("nan"), -5]
SPEEDS = [None, 0.0, 0.05, 0.1, 0.6, 1.0, 4.83, 11.5, 99.96, 150.0, float("inf")]
ETAS = [None, -1, 0, 30, 59.9, 60, 61, 360, 3540, 3600, 3660, 7322, float("nan")]


@pytest.mark.parametrize("seconds", SECONDS)
def test_durations_match_core(seconds):
    assert st.duration_text(seconds) == sm.format_duration(seconds)


@pytest.mark.parametrize("x", SPEEDS)
def test_speeds_match_core(x):
    assert st.speed_text(x) == sm.format_speed(x)


@pytest.mark.parametrize("eta", ETAS)
def test_time_left_matches_core(eta):
    assert st.time_left_text(eta) == sm.format_time_left(eta)


@pytest.mark.parametrize("x", SPEEDS)
@pytest.mark.parametrize("eta", [None, 0, 360, 7322])
def test_live_cell_matches_core_without_audio(x, eta):
    assert st.live_text(x, eta) == sm.live_cell(x, eta)


@pytest.mark.parametrize("audio, took", [(0, 10), (2520, 219.13), (2, 3.3), (30, 0.5), (5400, 12000)])
@pytest.mark.parametrize("model", ["", "faster-whisper-small", "large-v3"])
@pytest.mark.parametrize("device", ["", "cpu", "cuda:0", "mps", "tpu"])
@pytest.mark.parametrize("resumed", [False, True])
def test_summary_matches_core(audio, took, model, device, resumed):
    assert st.summary_text(audio, took, model, device, resumed) == \
        sm.summary_line(audio, took, model, device, resumed)


def test_measuring_says_how_much_audio_is_done():
    assert st.live_text(None, None, 36.1) == "measuring speed... (36 s of audio done)"
    assert st.live_text(None, None, 95.0) == "measuring speed... (1 min 35 s of audio done)"
    assert st.live_text(None, None, 0.4) == "measuring speed..."
    assert st.live_text(None, None, None) == "measuring speed..."
    # once a rate exists the audio is not repeated
    assert st.live_text(3.7, 2940, 66.4) == "about 3.7x, 49 min left"


def test_the_cell_follows_the_task_states():
    task = types.SimpleNamespace(status="running")
    assert st.speed_cell_text(task) == sm.speed_cell(task) == "measuring speed..."
    sm.apply_live_speed(task, {"percent": 0, "audio_s": 36.1})
    assert task.live_audio_s == pytest.approx(36.1)
    assert st.speed_cell_text(task) == "measuring speed... (36 s of audio done)"
    sm.apply_live_speed(task, {"percent": 40, "speed_x": 4.83, "eta_s": 360.0, "audio_s": 600})
    assert st.speed_cell_text(task) == sm.speed_cell(task) == "about 4.8x, 6 min left"
    task.status = "paused"
    assert st.speed_cell_text(task) == "paused"
    task.status, task.speed_live = "running", False
    assert st.speed_cell_text(task) == sm.speed_cell(task) == "shown when done"
    sm.apply_final_speed(task, {"speed_x": 11.5, "speed_audio_s": 2520.0, "speed_seconds": 219.13,
                                "model": "small", "device": "cpu"})
    task.status = "finished"
    assert st.speed_cell_text(task) == "11.5x"
    assert st.task_summary_text(task) == sm.task_summary_line(task) == \
        "42 min of audio transcribed in 3 min 39 s (11.5x) with small on CPU"


def test_the_interface_uses_the_translated_texts():
    import inspect

    from app.app import App

    assert "speed_cell_text(t)" in inspect.getsource(App)
    assert "task_summary_text(task)" in inspect.getsource(App)
