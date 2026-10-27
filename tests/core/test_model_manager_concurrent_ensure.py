"""Concurrent ``ensure_model`` calls for the same model must not race.

The download dialog's worker thread and the transcribe worker's
first-use ensure can both want the same missing model at once. They run
in one process, so the serialization belongs in ``ensure_model`` itself
(no lock exists there today).
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

from core import model_manager as mm
from core import offline


ENTRY = mm.MODEL_REGISTRY["small"]


def _config(model_path: Path) -> dict:
    return {
        "model": {"name": ENTRY["name"], "hf_repo": ENTRY["hf_repo"]},
        "model_path": str(model_path),
    }


def test_concurrent_ensure_of_the_same_model_downloads_it_once(
    tmp_path, monkeypatch,
):
    model_path = tmp_path / "cache" / f"models--Systran--{ENTRY['name']}"
    first_in_download = threading.Event()
    second_download_started = threading.Event()
    calls: list[int] = []

    def download_model(ref, output_dir=None, **_kw):
        calls.append(threading.get_ident())
        if len(calls) == 1:
            first_in_download.set()
            # Hold the first download open long enough that a racing
            # second call would reach it too; a serialized second call
            # cannot arrive until this one has returned.
            second_download_started.wait(1.0)
        else:
            second_download_started.set()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_bytes(b"weights")
        return str(out)

    fake = types.ModuleType("faster_whisper.utils")
    fake.download_model = download_model  # type: ignore[attr-defined]
    fake._MODELS = {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", fake)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)

    results: list[str] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(mm.ensure_model(_config(model_path)))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    first = threading.Thread(target=run)
    first.start()
    assert first_in_download.wait(5.0), "the first call never reached the download"
    second = threading.Thread(target=run)
    second.start()
    first.join(15.0)
    second.join(15.0)

    assert not errors, errors
    assert results == [str(model_path), str(model_path)]
    assert len(calls) == 1, "both callers downloaded the same model at once"
    assert not second_download_started.is_set()


def test_sequential_ensure_after_a_finished_download_does_not_redownload(
    tmp_path, monkeypatch,
):
    """The lock must not break the plain retry: once the weights exist a
    later ``ensure_model`` call returns without touching the network."""
    model_path = tmp_path / "cache" / f"models--Systran--{ENTRY['name']}"
    calls: list[str] = []

    def download_model(ref, output_dir=None, **_kw):
        calls.append(ref)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_bytes(b"weights")
        return str(out)

    fake = types.ModuleType("faster_whisper.utils")
    fake.download_model = download_model  # type: ignore[attr-defined]
    fake._MODELS = {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", fake)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)

    assert Path(mm.ensure_model(_config(model_path))) == model_path
    statuses: list[str] = []
    assert Path(mm.ensure_model(_config(model_path), status_cb=statuses.append)) == model_path
    assert calls == [ENTRY["hf_repo"]]
    assert statuses == ["Model already installed"]


def test_a_waiting_ensure_honours_cancel_instead_of_blocking(
    tmp_path, monkeypatch,
):
    """A caller queued behind a running download must stop waiting when its
    own cancel event is set, not block until the other download ends."""
    model_path = tmp_path / "cache" / f"models--Systran--{ENTRY['name']}"
    monkeypatch.setattr(mm, "_ENSURE_LOCK_POLL_SECONDS", 0.05)
    holder = mm._ensure_model_lock(model_path)
    assert holder.acquire(timeout=1.0)
    cancel = threading.Event()
    outcome: list[BaseException | str] = []

    def run() -> None:
        try:
            outcome.append(mm.ensure_model(_config(model_path), cancel_event=cancel))
        except BaseException as e:  # noqa: BLE001
            outcome.append(e)

    waiter = threading.Thread(target=run)
    try:
        waiter.start()
        waiter.join(0.3)
        assert waiter.is_alive(), "the call must wait while the lock is held"
        cancel.set()
        waiter.join(5.0)
        assert not waiter.is_alive(), "cancel did not end the wait"
    finally:
        holder.release()
        waiter.join(5.0)
    assert len(outcome) == 1 and isinstance(outcome[0], mm.DownloadCancelled), outcome
