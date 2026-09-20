"""Tests for the backend abstraction."""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def backends_module(monkeypatch):
    """Stub faster_whisper before importing the backends package."""
    if "faster_whisper" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fake_fw
    # Discard any prior import — the package may have been imported by
    # an earlier test with different stubs. Snapshot the existing module
    # objects first so teardown can put them back: other test modules hold
    # references to the original core.backends.* objects (e.g.
    # test_engine_selector's module-level ``availability`` import). If we
    # left our freshly-reimported objects in sys.modules, those tests'
    # monkeypatches would target a stale object while production code
    # re-imports the new one — a silent cross-file isolation leak.
    saved = {
        m: sys.modules[m]
        for m in list(sys.modules)
        if m.startswith("core.backends")
    }
    for mod in saved:
        del sys.modules[mod]
    import core.backends as be
    yield be
    # Restore the original modules so later tests see the same objects they
    # imported at collection time.
    for m in [m for m in list(sys.modules) if m.startswith("core.backends")]:
        del sys.modules[m]
    sys.modules.update(saved)


def test_get_backend_default_is_faster_whisper(backends_module):
    b = backends_module.get_backend("")
    assert b.name == "faster_whisper"


def test_get_backend_unknown_falls_back_to_default(backends_module):
    b = backends_module.get_backend("does_not_exist")
    assert b.name == "faster_whisper"


def test_get_backend_returns_whisper_cpp_when_requested(backends_module):
    b = backends_module.get_backend("whisper_cpp")
    assert b.name == "whisper_cpp"


def test_language_info_dataclass(backends_module):
    li = backends_module.LanguageInfo(language="en", probability=0.95)
    assert li.language == "en"
    assert li.probability == 0.95


def test_whisper_cpp_backend_load_without_model_fails(backends_module, monkeypatch, tmp_path):
    """Without the ggml file on disk, the load step must set an error
    rather than crashing the worker process."""
    from core.backends import whisper_cpp as wc

    monkeypatch.setattr(wc, "default_model_path", lambda: tmp_path / "missing.bin")
    # Force is_available to True so we hit the model-path check (we
    # need to pretend pywhispercpp is installed for the test).
    monkeypatch.setattr(wc, "is_available", lambda: True)
    backend = wc.WhisperCppBackend()
    statuses: list[str] = []
    ok = backend.load(statuses.append)
    assert ok is False
    assert backend.get_error()
    assert "missing" in (backend.get_error() or "").lower()


def test_whisper_cpp_backend_load_without_pywhispercpp_fails(backends_module, monkeypatch):
    from core.backends import whisper_cpp as wc

    monkeypatch.setattr(wc, "is_available", lambda: False)
    monkeypatch.setattr(wc, "availability_reason", lambda: "pywhispercpp not installed")
    backend = wc.WhisperCppBackend()
    ok = backend.load(lambda _s: None)
    assert ok is False
    assert "pywhispercpp" in (backend.get_error() or "")


def test_whisper_cpp_centisecond_segments_normalise(backends_module, monkeypatch):
    """Older pywhispercpp builds expose t0/t1 in centiseconds; the
    backend must convert them to seconds before handing the segments
    to the writer."""
    from core.backends import whisper_cpp as wc

    class _FakeSeg:
        def __init__(self, t0, t1, text):
            self.t0 = t0
            self.t1 = t1
            self.text = text

    class _FakeModel:
        detected_language = "en"
        def transcribe(self, *_a, **_kw):
            return [
                _FakeSeg(0, 250, "hello world"),       # 0 → 2.5 s
                _FakeSeg(250, 500, "second segment"),  # 2.5 → 5 s
            ]

    backend = wc.WhisperCppBackend()
    backend._model = _FakeModel()  # type: ignore[attr-defined]
    backend._ready = True  # type: ignore[attr-defined]

    segs, lang = backend.transcribe_to_segments(
        "/tmp/fake.wav",
        duration=5.0,
    )
    assert len(segs) == 2
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 2.5
    assert segs[1]["start"] == 2.5
    assert segs[1]["end"] == 5.0
    assert lang.language == "en"


def test_whisper_cpp_word_timestamps_emit_empty_list(backends_module):
    """pywhispercpp doesn't expose word timestamps; the backend must
    still surface a `words: []` field so downstream writers don't
    KeyError when word_timestamps is enabled."""
    from core.backends import whisper_cpp as wc

    class _FakeSeg:
        start = 0.0
        end = 1.0
        text = "hi"

    class _FakeModel:
        detected_language = ""
        def transcribe(self, *_a, **_kw):
            return [_FakeSeg()]

    backend = wc.WhisperCppBackend()
    backend._model = _FakeModel()  # type: ignore[attr-defined]
    backend._ready = True  # type: ignore[attr-defined]

    segs, _ = backend.transcribe_to_segments(
        "/tmp/fake.wav",
        want_words=True,
    )
    assert "words" in segs[0]
    assert segs[0]["words"] == []


def test_whisper_cpp_cancel_short_circuits(backends_module):
    """A cancelled task must short-circuit the segment loop."""
    from core.backends import whisper_cpp as wc

    class _FakeSeg:
        def __init__(self, i): self.start, self.end, self.text = i, i + 1, f"s{i}"

    class _FakeModel:
        detected_language = ""
        def transcribe(self, *_a, **_kw):
            return [_FakeSeg(i) for i in range(5)]

    backend = wc.WhisperCppBackend()
    backend._model = _FakeModel()  # type: ignore[attr-defined]
    backend._ready = True  # type: ignore[attr-defined]

    state = {"calls": 0}

    def cancelled_after_two() -> bool:
        state["calls"] += 1
        return state["calls"] > 2

    segs, _ = backend.transcribe_to_segments(
        "/tmp/fake.wav",
        cancelled=cancelled_after_two,
    )
    assert len(segs) < 5


def test_whisper_cpp_download_passes_socket_timeout(monkeypatch, tmp_path):
    """A stalled connection must fail instead of hanging forever — urlopen
    needs an explicit timeout (mirrors core/llm.py's download). A failed
    download must also not leave the .part file behind."""
    from core.backends import whisper_cpp as wc

    dest = tmp_path / wc.DEFAULT_MODEL_NAME
    seen: dict[str, float | None] = {}

    def fake_urlopen(url, timeout=None):  # noqa: ANN001
        seen["timeout"] = timeout
        raise wc.urllib.error.URLError("network down")

    monkeypatch.setattr(wc.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(wc.urllib.error.URLError):
        wc.download_default_model(dest=dest)
    assert seen["timeout"] is not None and seen["timeout"] > 0
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    assert not dest.exists()


def test_whisper_cpp_download_cleans_part_on_mid_stream_failure(monkeypatch, tmp_path):
    """A connection reset partway through must remove the (up to ~1.1 GB)
    partial download instead of leaving it on disk."""
    from core.backends import whisper_cpp as wc

    class _FailingStream:
        def __init__(self) -> None:
            self._first = True

        def __enter__(self) -> "_FailingStream":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def getheader(self, name: str):  # noqa: ANN001
            return None

        def read(self, n: int = -1) -> bytes:
            if self._first:
                self._first = False
                return b"x" * 4096
            raise OSError("connection reset by peer")

    dest = tmp_path / wc.DEFAULT_MODEL_NAME
    monkeypatch.setattr(
        wc.urllib.request, "urlopen", lambda url, timeout=None: _FailingStream()
    )
    with pytest.raises(OSError):
        wc.download_default_model(dest=dest)
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    assert not dest.exists()


# ------------------------------------------------------- availability hardening
#
# Regression coverage for the 2026-08-15 crash (see
# core/backends/google_cloud_stt.py's matching comment for the full story):
# GC firing mid-import of a heavy C-extension package faulted the process.
# pywhispercpp is the same risk class, so is_available() got the same
# shared-lock + gc.disable() defense pre-emptively (core/_gc_import_guard.py).
# These run the REAL is_available() body (no monkeypatch) — hermetic either
# way, since the ImportError path (pywhispercpp need not be installed here)
# and the success path both go through the same guard.


def test_whisper_cpp_is_available_restores_gc_state():
    import gc

    from core.backends import whisper_cpp as wc

    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            wc.is_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_whisper_cpp_is_available_serializes_concurrent_calls():
    import threading

    from core._gc_import_guard import _lock as guard_lock
    from core.backends import whisper_cpp as wc

    acquired = guard_lock.acquire(timeout=1.0)
    assert acquired, "test setup: could not acquire the lock"
    result: dict[str, bool] = {}

    def call():
        result["done"] = wc.is_available()

    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=0.3)
    try:
        assert t.is_alive(), "is_available() did not block on the lock"
    finally:
        guard_lock.release()
    t.join(timeout=3.0)
    assert not t.is_alive(), "is_available() never returned after unlock"
    assert "done" in result
