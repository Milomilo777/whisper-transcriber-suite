"""Actual reference-recording controllers with fake capture and no Tk/device."""
import ast
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import wave

import _tkinter
import pytest


ROOT = Path(__file__).resolve().parents[1]


def compile_selected(path, namespace, names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", None) in names
                or (isinstance(node, ast.Assign)
                    and any(getattr(target, "id", None) in names for target in node.targets))]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[])),
                 str(path), "exec"), namespace)


def duration(path):
    with wave.open(str(path), "rb") as stream:
        return stream.getnframes() / stream.getframerate()


@pytest.fixture
def flow(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reference path tests must not create Tk, devices, subprocesses or timers")

    monkeypatch.setattr(_tkinter, "create", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    config = ModuleType("core.config")
    config.user_cache_dir = lambda: tmp_path / "cache"
    monkeypatch.setitem(sys.modules, "core.config", config)
    voice = ModuleType("core.voice_clone")
    voice.__package__ = "core"
    voice.__dict__.update(os=os, time=SimpleNamespace(strftime=lambda *_: "20000101-120000"),
                          dataclass=dataclass, get_duration=duration, require_audio_stream=duration)
    monkeypatch.setitem(sys.modules, "core.voice_clone", voice)
    compile_selected(ROOT / "core/voice_clone.py", voice.__dict__, {
        "session_work_dir", "ReferenceIssue", "validate_reference_sample",
        "MIN_REFERENCE_SECONDS", "MAX_REFERENCE_SECONDS", "MAX_REFERENCE_SAMPLES",
    })
    state = SimpleNamespace(mode="complete", captures=[], errors=[], statuses=[])

    class Recorder:
        def __init__(self, output_path, mode):
            assert mode == "mic"
            self.output_path, self.last_error = output_path, None
            state.captures.append(self)

        def start(self):
            if state.mode == "failed-open":
                self.last_error = "synthetic device open failure"
                return
            with wave.open(self.output_path, "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(bytes([len(state.captures), 0]) * 64000)

        def stop(self):
            return self.output_path

        def is_running(self):
            return False

    recorder = ModuleType("core.recorder")
    recorder.Recorder = Recorder
    recorder.mic_available = lambda: True
    recorder.mic_availability_reason = forbidden
    monkeypatch.setitem(sys.modules, "core.recorder", recorder)
    threads = ModuleType("core._threads")
    threads.safe_thread = lambda worker, **kwargs: worker()
    monkeypatch.setitem(sys.modules, "core._threads", threads)
    namespace = {"os": os, "_": lambda text, **values: text.format(**values),
                 "ngettext": lambda one, many, n: one.format(n=n), "display": lambda text: text,
                 "show_error": lambda *args, **kwargs: state.errors.append((args, kwargs)),
                 "_sync_lock": lambda app: None, "_refresh_samples_listbox": lambda app: None,
                 "_reset_consent": lambda app: False, "_tick_recording": lambda *args: None,
                 "_poll_recording_stop": forbidden, "_SAMPLE_SECONDS": 10}
    compile_selected(ROOT / "app/widgets/voice_clone_tab.py", namespace, {
        "_record_sample", "_finish_recording", "_remove_sample", "_validate_and_add_sample",
        "_finish_adding_sample", "_samples_changed_status",
    })
    app = SimpleNamespace(vc_samples=[], vc_recorder=None, vc_busy=False, vc_confirm_open=False,
                          vc_record_btn=SimpleNamespace(configure=lambda **kwargs: None),
                          vc_status_var=SimpleNamespace(set=state.statuses.append),
                          vc_samples_listbox=SimpleNamespace(curselection=lambda: (0,)),
                          post_to_main=lambda callback: callback())
    return SimpleNamespace(app=app, state=state, namespace=namespace,
                           call=lambda name: namespace[name](app))


@pytest.mark.parametrize("next_mode", ["complete", "failed-open"])
def test_record_remove_record_uses_new_path_and_never_adopts_old_audio(flow, next_mode):
    flow.call("_record_sample")
    first = Path(flow.app.vc_recorder.output_path)
    original = first.read_bytes()
    flow.call("_finish_recording")
    assert flow.app.vc_samples == [str(first)]
    flow.call("_remove_sample")
    assert flow.app.vc_samples == []

    flow.state.mode = next_mode
    flow.call("_record_sample")
    second = Path(flow.app.vc_recorder.output_path)
    assert first.name == second.name == "sample_1.wav"
    assert first.parent != second.parent
    if next_mode == "failed-open":
        assert not second.exists()
    else:
        assert second.read_bytes() != original
    flow.call("_finish_recording")

    assert first.read_bytes() == original
    assert flow.app.vc_recorder is None
    if next_mode == "failed-open":
        assert flow.app.vc_samples == []
        assert "Recording failed" in str(flow.state.errors)
        assert "synthetic device open failure" in str(flow.state.errors)
    else:
        assert flow.app.vc_samples == [str(second)]
        assert not flow.state.errors
