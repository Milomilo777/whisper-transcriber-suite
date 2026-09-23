"""Regression: SMTV CDN basename must be sanitised before the path is formed.

``_run_smtv_task`` derives the output basename from the CDN ``?file=`` value,
which is attacker-influenceable. An NTFS ADS colon ("a:b") or a Windows
reserved device stem (CON/PRN/NUL/COM1...) used verbatim reaches
``os.path.join`` and yields a zero-byte / redirected file or an OSError on
write. The fix runs the chosen basename through the same sanitiser smtv.py
already applies in ``filename_for()``.

These tests stub ``_stream_smtv_file`` (no network), supply a cached
``SmtvEpisode`` (no fetch), and use a ``SimpleNamespace`` App (no Tk root),
then capture the path the streamer was handed to assert it was sanitised.
"""
from __future__ import annotations

import os
import queue
import types

import pytest

from app.services.download_service import DownloadService
from core.integrations import smtv as smtv_mod


def _episode() -> smtv_mod.SmtvEpisode:
    return smtv_mod.SmtvEpisode(
        vid="123",
        title="Some Episode",
        page_url="https://suprememastertv.com/en1/v/123.html",
        lang_prefix="en",
        transcript_text="",
    )


def _task(tmp_path, cdn_url: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        folder=str(tmp_path),
        url="https://suprememastertv.com/en1/v/123.html",
        cancelled=False,
        format_info={
            "mode": "Audio and video",
            "audio": None,
            "video": {
                "kind": "smtv",
                "mode": "video-best",
                "quality": "video-best",
                "url": cdn_url,
            },
            "output": "mp4",
            "episode": _episode(),
        },
    )


def _run_capturing_basename(tmp_path, cdn_url: str) -> str:
    """Run _run_smtv_task with a stubbed streamer; return the captured basename."""
    captured: dict[str, str] = {}

    def _fake_stream(self, task, url, dest_path, **_kw):
        # dest_path is target_path + ".part"; record the basename actually
        # used to form the on-disk path.
        captured["basename"] = os.path.basename(dest_path)[: -len(".part")]
        with open(dest_path, "wb") as f:
            f.write(b"data")

    app = types.SimpleNamespace(download_events=queue.Queue())
    svc = DownloadService(app)  # type: ignore[arg-type]
    svc._stream_smtv_file = types.MethodType(_fake_stream, svc)  # type: ignore[assignment]

    task = _task(tmp_path, cdn_url)
    svc._run_smtv_task(task)  # type: ignore[arg-type]
    return captured["basename"]


def test_smtv_cdn_basename_with_ads_colon_is_sanitised(tmp_path):
    # ?file= carries an NTFS alternate-data-stream colon.
    basename = _run_capturing_basename(
        tmp_path, "https://cdn.example/get?file=evil:stream.mp4"
    )
    assert ":" not in basename
    assert basename == "evil_stream.mp4"


def test_smtv_cdn_reserved_device_stem_is_prefixed(tmp_path):
    # ?file= carries a Windows reserved device name as the stem.
    basename = _run_capturing_basename(
        tmp_path, "https://cdn.example/get?file=CON.mp4"
    )
    assert basename == "_CON.mp4"


def test_smtv_cdn_clean_basename_is_unchanged(tmp_path):
    # A normal basename must pass through untouched (no over-sanitising).
    basename = _run_capturing_basename(
        tmp_path, "https://cdn.example/get?file=clip-720.mp4"
    )
    assert basename == "clip-720.mp4"
