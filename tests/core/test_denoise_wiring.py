"""The denoise pre-process is actually WIRED INTO the transcription paths.

``tests/core/test_denoise.py`` proves the module behaves; this file proves
the transcriber calls it, hands it the right flags, and cleans up after
it. That seam is exactly where this repo has shipped silent bugs before:
a field omitted at the call site (for example in ``transcribe_command``)
is invisible to helper-level tests.
"""
from __future__ import annotations

import os

import pytest

from core import transcriber
from core.backends.base import LanguageInfo
from core.task import TranscriptionTask


# ------------------------------------------------------ the shared seam


def test_maybe_denoise_is_a_no_op_when_disabled(monkeypatch, tmp_path):
    src = str(tmp_path / "a.wav")
    monkeypatch.setitem(transcriber.config, "denoise_enabled", False)
    monkeypatch.setattr(
        "core.denoise.denoise_audio",
        lambda *a, **k: pytest.fail("denoise ran while disabled"),
    )
    assert transcriber._maybe_denoise(src) == (src, "")


def test_maybe_denoise_passes_the_configured_level(monkeypatch, tmp_path):
    src = str(tmp_path / "a.wav")
    seen: dict = {}

    def fake(path, **kwargs):
        seen.update(kwargs)
        return path

    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setitem(transcriber.config, "denoise_level", "strong")
    monkeypatch.setattr("core.denoise.denoise_audio", fake)
    transcriber._maybe_denoise(src, duration=42.0)
    assert seen["level"] == "strong"
    assert seen["duration_s"] == pytest.approx(42.0)
    assert seen["enabled"] is True


def test_maybe_denoise_blank_level_falls_back_to_auto(monkeypatch, tmp_path):
    src = str(tmp_path / "a.wav")
    seen: dict = {}
    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setitem(transcriber.config, "denoise_level", "")
    monkeypatch.setattr(
        "core.denoise.denoise_audio",
        lambda path, **kw: (seen.update(kw), path)[1],
    )
    transcriber._maybe_denoise(src)
    assert seen["level"] == "auto"


def test_full_file_render_is_cached_and_not_marked_for_deletion(
    monkeypatch, tmp_path
):
    """A cached render is owned by the cache — deleting it defeats the cache."""
    src = str(tmp_path / "a.wav")
    render = str(tmp_path / "cached_denoised.wav")
    seen: dict = {}
    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr(
        "core.denoise.denoise_audio",
        lambda path, **kw: (seen.update(kw), render)[1],
    )
    out, to_delete = transcriber._maybe_denoise(src, transient=False)
    assert out == render
    assert to_delete == ""
    assert seen["cache"] is True
    assert seen["work_dir"] is None


def test_transient_render_is_uncached_and_marked_for_deletion(
    monkeypatch, tmp_path
):
    """A clip/resume slice render could never be reused — don't cache it."""
    src = str(tmp_path / "slice.wav")
    render = str(tmp_path / "slice.denoised.wav")
    seen: dict = {}
    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr(
        "core.denoise.denoise_audio",
        lambda path, **kw: (seen.update(kw), render)[1],
    )
    out, to_delete = transcriber._maybe_denoise(src, transient=True)
    assert out == render
    assert to_delete == render
    assert seen["cache"] is False
    assert seen["work_dir"] is not None


def test_unchanged_path_is_never_marked_for_deletion(monkeypatch, tmp_path):
    """A reverted/skipped denoise returns the input — deleting it would
    destroy the user's source file."""
    src = str(tmp_path / "original.wav")
    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr("core.denoise.denoise_audio", lambda path, **kw: path)
    assert transcriber._maybe_denoise(src, transient=True) == (src, "")


def test_denoise_failure_never_breaks_the_transcription(monkeypatch, tmp_path):
    src = str(tmp_path / "a.wav")

    def boom(*a, **k):
        raise RuntimeError("denoise exploded")

    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr("core.denoise.denoise_audio", boom)
    logs: list[str] = []
    assert transcriber._maybe_denoise(src, log_cb=logs.append) == (src, "")
    assert any("denoise exploded" in line for line in logs)


# -------------------------------------------- alt backends get it too


class _FakeAltBackend:
    def __init__(self) -> None:
        self.seen_path: str | None = None

    def transcribe_to_segments(self, audio_path, **kwargs):
        self.seen_path = audio_path
        return (
            [{"start": 0.0, "end": 1.0, "text": "hello"}],
            LanguageInfo(language="en", probability=0.99),
        )


@pytest.fixture
def alt_backend_harness(monkeypatch):
    """Drive _transcribe_via_alt_backend with no model and no real audio."""
    backend = _FakeAltBackend()
    monkeypatch.setattr(
        transcriber, "_get_alt_backend", lambda name, status_cb=None: backend
    )
    monkeypatch.setattr(transcriber, "get_duration", lambda p: 600.0)
    monkeypatch.setattr(transcriber, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(transcriber, "_write_outputs", lambda *a, **k: [])
    monkeypatch.setattr(transcriber, "_write_chapter_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(
        transcriber, "_write_periodic_checkpoint", lambda *a, **k: None
    )
    return backend


def test_alt_backend_receives_the_denoised_audio(
    alt_backend_harness, monkeypatch, tmp_path
):
    """Noise hurts whisper.cpp and the cloud engines too, not just
    faster-whisper — they must not silently skip the pre-process."""
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"\x00" * 2048)
    render = tmp_path / "movie_denoised.wav"
    render.write_bytes(b"\x00" * 2048)

    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr("core.denoise.denoise_audio", lambda path, **kw: str(render))

    transcriber._transcribe_via_alt_backend(
        "whisper_cpp", TranscriptionTask(str(src)), None, None, None
    )
    assert alt_backend_harness.seen_path == str(render)


def test_alt_backend_gets_the_original_when_denoise_is_off(
    alt_backend_harness, monkeypatch, tmp_path
):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"\x00" * 2048)
    monkeypatch.setitem(transcriber.config, "denoise_enabled", False)
    monkeypatch.setattr(
        "core.denoise.denoise_audio",
        lambda *a, **k: pytest.fail("denoise ran while disabled"),
    )
    transcriber._transcribe_via_alt_backend(
        "whisper_cpp", TranscriptionTask(str(src)), None, None, None
    )
    assert alt_backend_harness.seen_path == str(src)


def test_clipped_alt_backend_cleans_up_both_temp_files(
    alt_backend_harness, monkeypatch, tmp_path
):
    """A clipped run makes TWO temps (slice, then its denoised copy).

    Leaking either one grows partials/ without bound across a queue.
    """
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"\x00" * 2048)
    slice_file = tmp_path / "clip.slice.wav"
    render = tmp_path / "clip.denoised.wav"

    def fake_slice(source_path, start_seconds, out_dir, end_seconds=None):
        slice_file.write_bytes(b"\x00" * 2048)
        return str(slice_file)

    def fake_denoise(path, **kwargs):
        assert path == str(slice_file)
        assert kwargs["cache"] is False  # a slice render is never cacheable
        render.write_bytes(b"\x00" * 2048)
        return str(render)

    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr(transcriber, "_slice_audio_from", fake_slice)
    monkeypatch.setattr("core.denoise.denoise_audio", fake_denoise)

    task = TranscriptionTask(str(src))
    task.clip_start = 120.0
    task.clip_end = 180.0
    transcriber._transcribe_via_alt_backend("whisper_cpp", task, None, None, None)

    assert alt_backend_harness.seen_path == str(render)
    assert not os.path.exists(slice_file), "clip slice leaked"
    assert not os.path.exists(render), "denoised slice leaked"
    assert src.exists(), "the user's source file must never be deleted"


def test_alt_backend_temp_cleanup_survives_a_backend_crash(
    alt_backend_harness, monkeypatch, tmp_path
):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"\x00" * 2048)
    render = tmp_path / "movie_denoised.wav"

    def fake_denoise(path, **kwargs):
        render.write_bytes(b"\x00" * 2048)
        return str(render)

    def exploding(audio_path, **kwargs):
        raise RuntimeError("backend died mid-transcribe")

    monkeypatch.setitem(transcriber.config, "denoise_enabled", True)
    monkeypatch.setattr("core.denoise.denoise_audio", fake_denoise)
    monkeypatch.setattr(
        alt_backend_harness, "transcribe_to_segments", exploding
    )

    task = TranscriptionTask(str(src))
    task.clip_start = 0.0
    with pytest.raises(RuntimeError, match="backend died"):
        transcriber._transcribe_via_alt_backend(
            "whisper_cpp", task, None, None, None
        )
    # transient=False here (no slice), so the render is cache-owned and
    # deliberately kept; the point is that the crash did not delete the
    # source or leave the call site half-cleaned.
    assert src.exists()
