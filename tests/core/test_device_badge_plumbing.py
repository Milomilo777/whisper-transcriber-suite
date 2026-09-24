"""Tests for the R3 parent-side device-badge plumbing (no Tk root).

Covers the TranscriptionService.update_model_state / _refresh_device_badge /
_maybe_warn_cpu logic with a hand-rolled fake App, including the key
backward-compat case: an OLD worker whose "ready" event omitted the device
fields (worker dict has blank defaults) must not crash and must not warn.
"""
from __future__ import annotations

from typing import Any

from app.services.transcription_service import TranscriptionService


class _Var:
    def __init__(self, value=""):
        self._v = value

    def set(self, v):
        self._v = v

    def get(self):
        return self._v


class _FakeProc:
    def poll(self):
        return None


class _FakeApp:
    def __init__(self, workers, config=None):
        self.workers = workers
        self.status_var = _Var("")
        self.app_config = config if config is not None else {"cpu_warning_shown": False}
        self.worker_ready = False
        self.model_ready = False
        self.model_loading = False
        self.badge_calls: list[tuple[str, str]] = []
        self.warn_calls: list[bool] = []
        self.logs: list[str] = []

    def apply_device_badge(self, text, kind, worker):
        self.badge_calls.append((text, kind))

    def warn_cpu_once(self, downgraded):
        self.warn_calls.append(downgraded)

    def log(self, msg):
        self.logs.append(msg)


def _worker(**kw):
    base = {
        "id": 1, "token": "t", "process": _FakeProc(), "ready": True,
        "task": None, "device": "", "compute_type": "",
        "requested_device": "", "downgraded": False,
    }
    base.update(kw)
    return base


def _svc(app):
    return TranscriptionService(app)  # type: ignore[arg-type]


def test_gpu_worker_sets_green_badge(monkeypatch):
    app = _FakeApp([_worker(device="cuda", compute_type="float16")])
    svc = _svc(app)
    svc.update_model_state()
    assert app.badge_calls
    text, kind = app.badge_calls[-1]
    assert kind == "gpu"
    assert "GPU" in text and "float16" in text
    assert app.warn_calls == []  # never warn on GPU


def test_cpu_downgraded_worker_sets_amber_and_warns_once(monkeypatch):
    app = _FakeApp([
        _worker(device="cpu", compute_type="int8",
                requested_device="cuda", downgraded=True),
    ])
    svc = _svc(app)
    svc.update_model_state()
    text, kind = app.badge_calls[-1]
    assert kind == "cpu_downgraded"
    assert "CPU" in text
    assert app.warn_calls == [True]
    assert app.app_config["cpu_warning_shown"] is True

    # Second ready event must NOT warn again (flag persisted).
    app.warn_calls.clear()
    svc.update_model_state()
    assert app.warn_calls == []


def test_plain_cpu_only_host_does_not_warn(monkeypatch):
    """No GPU at all => nothing actionable => no warning."""
    import core.hardware as hw

    app = _FakeApp([_worker(device="cpu", compute_type="int8")])
    svc = _svc(app)
    # No NVIDIA GPU on this host at all.
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=False, gpu_present=False, reason="No NVIDIA CUDA GPU was found.",
    ))
    svc.update_model_state()
    text, kind = app.badge_calls[-1]
    assert kind == "cpu"
    assert app.warn_calls == []  # genuine CPU-only box — no nag


def test_cpu_with_detected_but_unusable_gpu_warns(monkeypatch):
    import core.hardware as hw

    app = _FakeApp([_worker(device="cpu", compute_type="int8")])
    svc = _svc(app)
    # An NVIDIA GPU is on the host but not usable (e.g. cuBLAS missing).
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=False, gpu_present=True, reason="cuBLAS missing",
    ))
    svc.update_model_state()
    assert app.warn_calls == [False]


def test_old_worker_without_device_fields_is_tolerated(monkeypatch):
    """Backward-compat: an OLD worker reported a bare ready (blank device).

    _refresh_device_badge must not crash and must not warn (no info to act on).
    """
    app = _FakeApp([_worker()])  # device="" — old-worker default
    svc = _svc(app)
    svc.update_model_state()  # must not raise
    assert app.badge_calls == []  # no informed worker => no badge update
    assert app.warn_calls == []
