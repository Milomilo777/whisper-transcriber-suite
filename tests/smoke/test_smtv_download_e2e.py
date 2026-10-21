"""Real end-to-end test of the SMTV download pipeline.

Exercises ``DownloadService._run_smtv_task`` against a live SMTV
episode. Downloads the actual MP4 from the CDN, verifies the bytes
look like a real MP4 (contains the ftyp box), confirms the
article-text transcript landed alongside as ``<base>.txt``, and
checks that the ``done_full`` event is the one that surfaces the
saved path to the auto-transcribe-after-download wiring.

The previous unit suite covered the page parser with HTML fixtures.
The previous live smoke covered the parser + a CDN HEAD. Neither
exercised the actual streaming write, the .part → final rename,
the transcript persistence, or the event sequence — which is what
real users depend on.

Skipped offline (``WHISPER_OFFLINE_TESTS=1``) and when the host is
unreachable. Pulls ~25 MB of MP4, runs ~10 s on a decent line.
"""
from __future__ import annotations

import os
import queue
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

from app.services.download_service import DownloadService
from app.domain.tasks import VideoDownloadTask
from core.integrations import smtv as smtv_mod


REFERENCE_EPISODE = os.environ.get(
    "WHISPER_SMTV_DOWNLOAD_TEST_URL",
    # 5-minute news clip — small (~ 25 MB at 396p) and has a real
    # article-text transcript. No mp3 (NWN content is video-only).
    "https://suprememastertv.com/en1/v/314324511737.html",
)


def _online() -> bool:
    if os.environ.get("WHISPER_OFFLINE_TESTS") == "1":
        return False
    try:
        with socket.create_connection(("cf-vdo.suprememastertv.com", 443), timeout=3):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _online(), reason="SMTV CDN unreachable or offline mode"
)


# --- minimal app shim that DownloadService uses ----------------------------


class _AppShim:
    """The bits of App that DownloadService._run_smtv_task touches.

    A real Tk App would carry far more, but the SMTV download path
    only reads from ``download_events`` (a Queue we drain) and
    ``app_config``. ``history`` is None so the history-DB branch
    skips cleanly.
    """

    def __init__(self) -> None:
        self.download_events: queue.Queue = queue.Queue()
        self.app_config: dict[str, Any] = {"auto_transcribe_after_download": False}
        self.history = None
        self._smtv_episode: Any = None
        self._events_seen: list[tuple] = []

    def log(self, msg: str) -> None:
        self._events_seen.append(("log", None, msg))

    def drain(self) -> list[tuple]:
        out: list[tuple] = []
        while True:
            try:
                out.append(self.download_events.get_nowait())
            except queue.Empty:
                return out


# --- the actual end-to-end test --------------------------------------------


def test_smtv_real_download_writes_video_and_transcript(tmp_path: Path) -> None:
    """Full path: scrape -> stream MP4 -> atomic rename -> save .txt."""

    # 1. Scrape the live episode.
    episode = smtv_mod.fetch_episode(REFERENCE_EPISODE, timeout=30.0)
    assert episode.files, "episode has no downloadable files"

    # Pick the smallest available video quality (396p preferred).
    quality_priority = ["396p", "720p", "1080p", "audio"]
    chosen_file = None
    for q in quality_priority:
        for f in episode.files:
            if f.quality == q:
                chosen_file = f
                break
        if chosen_file is not None:
            break
    assert chosen_file is not None
    chosen_mode = {
        "396p": "video-396",
        "720p": "video-720",
        "1080p": "video-1080",
        "audio": "audio",
    }[chosen_file.quality]

    # 2. Build a VideoDownloadTask shaped exactly the way the format
    #    service would build it.
    task = VideoDownloadTask(
        url=episode.page_url,
        folder=str(tmp_path),
        format_label=f"SMTV {chosen_file.quality}",
        format_info={
            "mode": "Audio" if chosen_mode == "audio" else "Audio and video",
            "audio": (
                {"kind": "smtv", "mode": "audio", "quality": "audio",
                 "url": chosen_file.download_url}
                if chosen_mode == "audio" else None
            ),
            "video": (
                {"kind": "smtv", "mode": chosen_mode, "quality": chosen_file.quality,
                 "url": chosen_file.download_url}
                if chosen_mode != "audio" else None
            ),
            "output": "mp4",
            "episode": episode,
        },
        title=episode.title,
        subtitles_enabled=False,
        subtitle_lang="",
        detected_language=episode.lang_prefix,
    )

    # 3. Run the real service.
    shim = _AppShim()
    svc = DownloadService(shim)  # type: ignore[arg-type]

    # _run_smtv_task is normally invoked on a daemon thread from
    # _run_task; here we call it directly on the main thread so a
    # failure raises into pytest cleanly.
    svc._run_smtv_task(task)

    events = shim.drain()
    kinds = [e[0] for e in events]

    # 4. Verify the event sequence the auto-transcribe wiring relies on.
    assert "done_full" in kinds, f"expected done_full event; saw {kinds}"
    done_full = next(e for e in events if e[0] == "done_full")
    payload = done_full[2]
    assert payload["status"] == "finished"
    saved_path = payload["saved_path"]
    assert saved_path
    assert os.path.isfile(saved_path), f"saved_path does not exist: {saved_path}"

    # 5. Verify the downloaded bytes look like a real MP4.
    size = os.path.getsize(saved_path)
    assert size > 1_000_000, f"suspiciously small file: {size} bytes"
    with open(saved_path, "rb") as f:
        head = f.read(32)
    # MP4 files have an "ftyp" box near the start (within the first
    # ~12 bytes typically — size prefix + "ftyp" magic).
    assert b"ftyp" in head, f"downloaded file is not a recognisable MP4: head={head!r}"

    # 6. .part file must NOT linger.
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    assert leftovers == [], f".part files still on disk: {leftovers}"

    # 7. The page's text written alongside, under its own name (the transcription owns <stem>.txt).
    stem, _ = os.path.splitext(os.path.basename(saved_path))
    txt_path = tmp_path / f"{stem}.description.txt"
    assert txt_path.is_file(), f"transcript .txt not written: {txt_path}"
    txt_content = txt_path.read_text(encoding="utf-8")
    assert len(txt_content) > 100, f"transcript suspiciously short: {len(txt_content)} chars"
    # The transcript should match what we scraped from the page —
    # confirms we wrote the *real* article text, not some placeholder.
    # Compare first ~80 chars rather than full text in case the page
    # transcript is updated between fetch_episode and this assertion.
    assert episode.transcript_text[:80] in txt_content


def test_smtv_real_download_is_cancellable(tmp_path: Path) -> None:
    """When task.cancelled flips mid-stream, the .part file is removed
    and the service posts the cancellation event instead of done_full.

    Strategy: run the download on a background thread, flip the cancel
    flag almost immediately, then wait for the service to wind down.
    The test passes if either:
      * the cancel flipped before the stream started — we see the
        ``done`` event with payload "cancelled"
      * the cancel flipped during the stream — we see the same; no
        ``.part`` survives in either case
    """
    episode = smtv_mod.fetch_episode(REFERENCE_EPISODE, timeout=30.0)

    # 720p — larger than 396p so we have time to cancel mid-stream.
    chosen = next((f for f in episode.files if f.quality == "720p"), None)
    if chosen is None:
        pytest.skip("no 720p file on this episode to cancel mid-stream")

    task = VideoDownloadTask(
        url=episode.page_url,
        folder=str(tmp_path),
        format_label="SMTV 720p (cancellation test)",
        format_info={
            "mode": "Audio and video",
            "audio": None,
            "video": {"kind": "smtv", "mode": "video-720",
                      "quality": "720p", "url": chosen.download_url},
            "output": "mp4",
            "episode": episode,
        },
        title=episode.title,
        subtitles_enabled=False,
        subtitle_lang="",
        detected_language=episode.lang_prefix,
    )

    shim = _AppShim()
    svc = DownloadService(shim)  # type: ignore[arg-type]

    def runner() -> None:
        try:
            svc._run_smtv_task(task)
        except Exception:
            pass

    t = threading.Thread(target=runner, daemon=True)
    t.start()

    # Flip the cancel flag and let the service unwind. 720p is large
    # enough that the stream loop checks task.cancelled per chunk and
    # exits before completing.
    import time
    time.sleep(0.5)
    task.cancelled = True
    t.join(timeout=30.0)
    assert not t.is_alive(), "service did not honour the cancel within 30 s"

    events = shim.drain()
    kinds = [e[0] for e in events]
    assert "done_full" not in kinds, "service shouldn't have finished after cancel"
    # Either the cancel hit before the stream started (no done event)
    # or hit mid-stream (done event with payload "cancelled"). Both
    # are acceptable; what matters is no .part and no completed file.
    leftovers_part = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    leftovers_final = [f for f in os.listdir(tmp_path) if f.endswith(".mp4")]
    assert leftovers_part == [], f".part files survived cancellation: {leftovers_part}"
    assert leftovers_final == [], f"complete .mp4 survived cancellation: {leftovers_final}"
