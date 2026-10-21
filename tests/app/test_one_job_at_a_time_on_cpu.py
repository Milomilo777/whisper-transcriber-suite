"""On a CPU the app runs one transcription at a time unless the user set another number.

Two jobs at once on a CPU each load the model (about 3 GB) and share the cores, so both run at
half speed and the machine slows down (deep review of tabs 1-3, 2026-10-21). ``parallel_workers``
0 (the new default) means automatic: 1 until a worker reports a GPU, then 2. Older versions wrote
the old default 2 into every config.json, and no window ever offered the setting, so a stored 2
reads as automatic; any other number is the user's own and is kept.
"""
from __future__ import annotations

import json
import queue
from types import SimpleNamespace

import pytest

from app.services.transcription_service import TranscriptionService
from core import config


def _worker(device: str = "", ready: bool = True) -> dict:
    return {"id": 1, "process": SimpleNamespace(pid=111, poll=lambda: None),
            "ready": ready, "task": object(), "device": device}


def _svc(parallel_workers: int, workers: list) -> TranscriptionService:
    app = SimpleNamespace(workers=workers, queue=[], parallel_workers=parallel_workers,
                          worker_events=queue.Queue(), app_config={})
    return TranscriptionService(app)  # type: ignore[arg-type]


@pytest.mark.parametrize("configured, workers, expected", [
    (0, [], 1),                       # device not known yet: start one
    (0, [_worker("cpu")], 1),
    (0, [_worker("cuda")], 2),
    (0, [_worker("cuda", ready=False)], 1),  # still loading: no proof of a GPU yet
    (1, [_worker("cuda")], 1),        # the user's own number wins
    (3, [_worker("cpu")], 3),
])
def test_the_worker_limit(configured: int, workers: list, expected: int) -> None:
    assert _svc(configured, workers).worker_limit() == expected


def test_dispatch_starts_one_worker_on_an_unknown_device(monkeypatch) -> None:
    from core.task import TranscriptionTask

    svc = _svc(0, [])
    svc.app.queue = [TranscriptionTask("a.mp3"), TranscriptionTask("b.mp3")]
    started: list[bool] = []
    monkeypatch.setattr(svc, "start_worker", lambda temporary=False: started.append(temporary))
    monkeypatch.setattr(svc, "_retire_stale_idle_workers", lambda: None)
    svc.dispatch_waiting()
    assert started == [True]


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "fetch_online_config", lambda url: {})
    monkeypatch.setattr(config.platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path / "data"))
    monkeypatch.setattr(config.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config"))
    yield tmp_path


@pytest.mark.parametrize("stored, expected", [(None, 0), (2, 0), (1, 1), (4, 4)])
def test_the_stored_setting(isolated_config, stored, expected) -> None:
    data = {"theme": "dark"} if stored is None else {"parallel_workers": stored}
    (isolated_config / "config.json").write_text(json.dumps(data), encoding="utf-8")
    assert config.load_config(fetch_online=False)["parallel_workers"] == expected
