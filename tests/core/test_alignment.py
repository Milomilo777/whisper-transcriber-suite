"""Tests for the stable-ts alignment post-processor."""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def alignment_module():
    # Stable-ts is an opt-in dep; mock the import so the module
    # itself can be tested without installing it.
    for mod in [m for m in list(sys.modules) if m.startswith("core.alignment")]:
        del sys.modules[mod]
    import core.alignment as a
    return a


def test_is_available_returns_false_when_module_missing(alignment_module, monkeypatch):
    # Pretend stable_whisper isn't importable.
    monkeypatch.setitem(sys.modules, "stable_whisper", None)
    # Module-level cache could already say True from a previous test
    # run, so call directly.
    assert alignment_module.is_available() is False
    assert "stable-ts" in alignment_module.availability_reason()


def test_is_available_restores_gc_state(alignment_module):
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); stable-ts pulls torch, same risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            alignment_module.is_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_refine_raises_when_unavailable(alignment_module, monkeypatch):
    monkeypatch.setattr(alignment_module, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="stable-ts"):
        alignment_module.refine_word_timestamps_in_place(
            "/tmp/fake.wav",
            [{"start": 0.0, "end": 1.0, "text": "hi"}],
        )


def test_refine_noop_on_empty_segments(alignment_module, monkeypatch):
    monkeypatch.setattr(alignment_module, "is_available", lambda: True)
    monkeypatch.setitem(sys.modules, "stable_whisper", types.ModuleType("stable_whisper"))
    out: list[dict] = []
    ok = alignment_module.refine_word_timestamps_in_place("/tmp/fake.wav", out)
    assert out == []
    assert ok is False


def test_refine_splices_words_back(alignment_module, monkeypatch, tmp_path):
    """When the loaded model's .align() returns a WhisperResult with
    refined word lists, those word lists must end up on
    segments_data."""
    monkeypatch.setattr(alignment_module, "is_available", lambda: True)

    # Build a fake stable_whisper module with WhisperResult + a fake
    # model exposing .align(...) — matches the real 2.19 API surface.
    class _FakeWord:
        def __init__(self, start, end, word, probability=0.9):
            self.start, self.end, self.word, self.probability = start, end, word, probability

    class _FakeSeg:
        def __init__(self, words):
            self.words = words

    class _FakeResult:
        def __init__(self, payload=None, segments=None, language=None):
            if payload is not None:
                self._payload = payload
                self.language = payload.get("language", "en")
                self.segments = []
            else:
                self.segments = segments or []
                self.language = language or "en"

    class _FakeModel:
        def align(self, _audio, coarse_result, **_kw):
            return _FakeResult(segments=[
                _FakeSeg([_FakeWord(0.0, 0.5, "hello"),
                          _FakeWord(0.5, 1.0, "world")])
                for _ in getattr(coarse_result, "_payload", {"segments": [None]}).get("segments", [None])
            ])

    fake_sw = types.ModuleType("stable_whisper")
    fake_sw.WhisperResult = _FakeResult  # type: ignore[attr-defined]
    fake_sw.load_model = lambda _name: _FakeModel()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_whisper", fake_sw)

    # refine_word_timestamps_in_place now requires the audio file to
    # exist on disk; create a tiny placeholder.
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    segs = [{"start": 0.0, "end": 1.0, "text": "hello world"}]
    ok = alignment_module.refine_word_timestamps_in_place(str(audio), segs)
    assert ok is True
    assert "words" in segs[0]
    words = segs[0]["words"]
    assert len(words) == 2
    assert words[0]["word"] == "hello"
    assert words[1]["word"] == "world"
    assert words[1]["start"] == 0.5


def test_refine_keeps_index_alignment_with_non_string_text(alignment_module, monkeypatch, tmp_path):
    """A segment with missing text must stay in the WhisperResult
    payload. The splice-back is index-based, so the old filter that
    dropped non-string-text segments shifted every later segment's
    words onto the wrong segment."""
    monkeypatch.setattr(alignment_module, "is_available", lambda: True)

    class _FakeWord:
        def __init__(self, start, end, word):
            self.start, self.end, self.word, self.probability = start, end, word, 0.9

    class _FakeSeg:
        def __init__(self, words):
            self.words = words

    class _FakeResult:
        def __init__(self, payload=None, segments=None, language=None):
            if payload is not None:
                self._payload = payload
                self.language = payload.get("language", "en")
                self.segments = []
            else:
                self.segments = segments or []
                self.language = language or "en"

    class _FakeModel:
        def align(self, _audio, coarse_result, **_kw):
            # Mimic stable-ts: one refined segment per payload segment,
            # with no words for an empty-text segment.
            out = []
            for raw in coarse_result._payload["segments"]:
                if raw["text"].strip():
                    out.append(_FakeSeg([_FakeWord(raw["start"], raw["end"], "hello")]))
                else:
                    out.append(_FakeSeg([]))
            return _FakeResult(segments=out)

    fake_sw = types.ModuleType("stable_whisper")
    fake_sw.WhisperResult = _FakeResult  # type: ignore[attr-defined]
    fake_sw.load_model = lambda _name: _FakeModel()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_whisper", fake_sw)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    segs = [
        {"start": 0.0, "end": 1.0, "text": None},
        {"start": 1.0, "end": 2.0, "text": "hello"},
    ]
    ok = alignment_module.refine_word_timestamps_in_place(str(audio), segs)
    assert ok is True
    assert "words" not in segs[0]
    assert segs[1]["words"][0]["word"] == "hello"


def test_refine_handles_align_returning_none(alignment_module, monkeypatch, tmp_path):
    """stable-ts returns None when alignment fails internally; the
    wrapper must not AttributeError on .segments."""
    monkeypatch.setattr(alignment_module, "is_available", lambda: True)

    class _FakeResult:
        def __init__(self, payload=None, **_kw):
            self._payload = payload or {}
            self.language = (payload or {}).get("language", "en")
            self.segments = []

    class _FakeModel:
        def align(self, *_a, **_kw):
            return None

    fake_sw = types.ModuleType("stable_whisper")
    fake_sw.WhisperResult = _FakeResult  # type: ignore[attr-defined]
    fake_sw.load_model = lambda _n: _FakeModel()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_whisper", fake_sw)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    segs = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    ok = alignment_module.refine_word_timestamps_in_place(str(audio), segs)
    assert ok is False
    # segments_data must not have been mutated to a bad state.
    assert segs[0]["text"] == "hello"


def test_refine_raises_on_missing_audio(alignment_module, monkeypatch):
    """A clean FileNotFoundError is more useful than an obscure
    librosa / ffmpeg failure deeper down."""
    monkeypatch.setattr(alignment_module, "is_available", lambda: True)
    monkeypatch.setitem(sys.modules, "stable_whisper", types.ModuleType("stable_whisper"))
    with pytest.raises(FileNotFoundError):
        alignment_module.refine_word_timestamps_in_place(
            "/no/such/audio.wav",
            [{"start": 0.0, "end": 1.0, "text": "hi"}],
        )
