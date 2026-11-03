"""The fresh worker must see the allocator before importing native code."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from core import hardware


@pytest.mark.parametrize("platform,expected", [
    ("win32", "cub_caching"),
    ("darwin", None),
    ("linux", None),
])
def test_allocator_is_windows_only_and_never_probes_in_the_parent(monkeypatch, platform, expected):
    monkeypatch.delenv("CT2_CUDA_ALLOCATOR", raising=False)
    monkeypatch.setattr(hardware.sys, "platform", platform)
    def probe(*a, **kw):
        raise AssertionError("native GPU libraries must stay out of the app process")
    monkeypatch.setattr(hardware, "detect_device_for", probe)
    monkeypatch.setattr(hardware, "cuda_status", probe, raising=False)
    env = hardware.transcription_worker_env()
    assert env.get("CT2_CUDA_ALLOCATOR") == expected
    assert "CT2_CUDA_ALLOCATOR" not in os.environ


def test_allocator_preserves_explicit_user_override(monkeypatch):
    monkeypatch.setenv("CT2_CUDA_ALLOCATOR", "cuda_malloc_async")
    monkeypatch.setattr(hardware.sys, "platform", "win32")
    assert hardware.transcription_worker_env()["CT2_CUDA_ALLOCATOR"] == "cuda_malloc_async"


def test_real_child_import_observes_allocator_before_ctranslate2(monkeypatch, tmp_path):
    # A recorded driver crash cannot be reproduced hermetically. This real
    # child instead verifies the ordering with an import-time assertion.
    monkeypatch.delenv("CT2_CUDA_ALLOCATOR", raising=False)
    if sys.platform != "win32":
        pytest.skip("The workaround is Windows-specific")
    (tmp_path / "ctranslate2.py").write_text(
        "import os\nassert os.environ['CT2_CUDA_ALLOCATOR'] == 'cub_caching'\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, "-c", "import ctranslate2; print('allocator ready')"],
                            cwd=tmp_path, env=hardware.transcription_worker_env(),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "allocator ready"
    assert "CT2_CUDA_ALLOCATOR" not in os.environ


@pytest.mark.parametrize("live", [False, True])
def test_both_launchers_pass_prepared_environment_to_popen(monkeypatch, live):
    from types import SimpleNamespace

    from app.services import live_service, transcription_service

    seen = []
    def environment():
        return {"CT2_CUDA_ALLOCATOR": "cub_caching"}
    def popen(*args, **kwargs):
        seen.append(kwargs["env"])
        raise OSError("stop before a real worker is launched")
    monkeypatch.setattr(hardware, "transcription_worker_env", environment)
    monkeypatch.setattr(subprocess, "Popen", popen)
    config = {"device": "cuda"}
    if live:
        with pytest.raises(live_service.LiveWorkerError, match="stop before"):
            live_service.LiveTranscriber("gui.py").start(wait_ready=False)
    else:
        app = SimpleNamespace(app_config=config, workers=[], next_worker_id=1, entry_file="gui.py",
                              status_var=SimpleNamespace(set=lambda value: None))
        service = transcription_service.TranscriptionService(app)
        monkeypatch.setattr(service, "_engine_snapshot", lambda: {})
        monkeypatch.setattr(service, "update_model_state", lambda: None)
        with pytest.raises(OSError, match="stop before"):
            service.start_worker()
    assert len(seen) == 1 and seen[0]["CT2_CUDA_ALLOCATOR"] == "cub_caching"
    assert seen[0]["WHISPER_WORKER_TOKEN"]
