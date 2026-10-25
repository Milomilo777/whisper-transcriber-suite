"""Recorder.stop() aborts a microphone read that does not return.

Uses a fake ``sounddevice`` stream; no audio device is ever opened.
"""
from __future__ import annotations

import sys
import threading
import time
import types
import wave

from core import recorder as rec


class _BlockingStream:
    """read() blocks until abort() is called, like a wedged capture driver."""

    samplerate = 16_000

    def __init__(self, reads_before_block: int = 2):
        self.aborted = threading.Event()
        self.entered_block = threading.Event()
        self._left = reads_before_block

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def abort(self):
        self.aborted.set()

    def read(self, n):
        if self._left > 0:
            self._left -= 1
            time.sleep(0.01)
            return (b"\x01\x02" * n, False)
        self.entered_block.set()
        if self.aborted.wait(timeout=30):
            raise RuntimeError("Stream is stopped")
        return (b"", False)


def _install(monkeypatch, stream):
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.RawInputStream = lambda **kw: stream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)


def test_stop_aborts_a_blocked_read_and_ends_the_thread(tmp_path, monkeypatch):
    stream = _BlockingStream()
    _install(monkeypatch, stream)
    out = tmp_path / "wedged.wav"
    r = rec.Recorder(output_path=str(out), mode="mic")
    r.start()
    assert stream.entered_block.wait(timeout=5)
    began = time.monotonic()
    r.stop(timeout=5.0)
    elapsed = time.monotonic() - began
    assert stream.aborted.is_set(), "a blocked read must be aborted"
    assert not r.is_running(), "the capture thread must have ended"
    assert elapsed < 4.0
    assert r.last_error is None, "an abort caused by Stop is not a recording failure"
    assert r._stream is None
    with wave.open(str(out), "rb") as wf:  # closed by the capture thread itself
        assert wf.getnframes() > 0


def test_a_prompt_read_is_never_aborted(tmp_path, monkeypatch):
    class _Quick(_BlockingStream):
        def read(self, n):
            time.sleep(0.01)
            return (b"\x01\x02" * n, False)

    stream = _Quick()
    _install(monkeypatch, stream)
    r = rec.Recorder(output_path=str(tmp_path / "ok.wav"), mode="mic")
    r.start()
    time.sleep(0.1)
    r.stop()
    assert not stream.aborted.is_set()
    assert not r.is_running()


def test_a_real_failure_still_sets_last_error(tmp_path, monkeypatch):
    class _Broken(_BlockingStream):
        def read(self, n):
            raise RuntimeError("device unplugged")

    _install(monkeypatch, _Broken())
    r = rec.Recorder(output_path=str(tmp_path / "bad.wav"), mode="mic")
    r.start()
    assert r._thread is not None
    r._thread.join(timeout=5)
    assert r.last_error and "unplugged" in r.last_error
