"""Shared pytest fixtures for the core test suite.

The ``_isolate_transcriber_globals`` autouse guard used to live here; it
moved to ``tests/conftest.py`` (the shared root) 2026-08-15 so
``tests/smoke/`` inherits it too, after ``test_v08_real_file_e2e.py`` moved
there. See that file's docstring for the full story.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_model_manifest(tmp_path_factory, monkeypatch):
    """Legacy tests use an empty manifest; pinned tests inject their own entries."""
    from core import model_download

    manifest = tmp_path_factory.mktemp("model-manifest") / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(model_download, "MANIFEST_PATH", manifest)


@pytest.fixture(autouse=True)
def _default_offline_backend(monkeypatch):
    """Pin core.transcriber's active backend to faster_whisper for tests.

    ``core.transcriber.config`` is loaded once at import; on a dev/build
    machine that ships ``creds/gcloud_stt.json`` the resolved default becomes
    ``google_cloud_stt``, which silently routes tests that mock the offline
    ``MODEL`` through the cloud path and breaks them. Forcing the offline
    backend here makes the suite deterministic regardless of whether a bundled
    key is present (mirrors CI). ``setitem`` is auto-reverted, and a test that
    explicitly exercises a cloud backend (by reassigning ``config``) still
    wins.
    """
    try:
        import core.transcriber as _t
    except Exception:  # noqa: BLE001
        return
    if isinstance(getattr(_t, "config", None), dict):
        monkeypatch.setitem(_t.config, "transcribe_backend", "faster_whisper")
