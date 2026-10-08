"""Text to Voice jobs never redo or lose finished work (core/tts_job.py):
a finished job is remembered, a damaged piece is redone instead of failing
every join, two app instances never share one job, speechless pieces
(scene breaks) are not sent to the engine, and Thai/Lao text without
spaces is never cut between a leading vowel and its consonant."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import tts_job
from tests.core.test_tts_job import TEXT, VOICE, FakeEngine, _open, _write_wav  # noqa: F401


@pytest.fixture
def small_pieces(monkeypatch):
    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 60)


# ------------------------------------------------------- finished jobs (S08-7)


def test_a_finished_job_is_remembered_and_not_spoken_again(tmp_path, small_pieces):
    first = _open(tmp_path)
    tts_job.run(first, FakeEngine())
    before = first.output_path.stat().st_mtime_ns

    again = _open(tmp_path)
    assert again.finished
    assert again.pending() == []
    engine = FakeEngine()
    result = tts_job.run(again, engine)
    assert engine.spoken == []  # nothing re-spoken
    assert result.pieces_run == 0
    assert Path(result.output_path) == first.output_path
    assert first.output_path.stat().st_mtime_ns == before  # output.wav not rewritten
    assert result.audio_seconds == pytest.approx(
        sum(len(p.strip()) / 10.0 for p in first.pieces))


def test_a_finished_marker_without_its_output_is_not_trusted(tmp_path, small_pieces):
    job = _open(tmp_path)
    tts_job.run(job, FakeEngine())
    job.output_path.unlink()
    again = _open(tmp_path)
    assert not again.finished
    assert len(again.pending()) == len(again.pieces)


def test_start_over_on_a_finished_job_speaks_it_again(tmp_path, small_pieces):
    tts_job.run(_open(tmp_path), FakeEngine())
    again = _open(tmp_path)
    again.discard()
    assert not again.finished
    engine = FakeEngine()
    tts_job.run(again, engine)
    assert engine.spoken == [p.strip() for p in again.pieces]
    assert _open(tmp_path).finished


# ------------------------------------------------- damaged pieces (B1)


def _cut_in_half(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])  # the header still claims every frame


def test_a_truncated_piece_is_not_taken_over_as_done(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    for index in (0, 1):  # two pieces finished by an earlier run
        path = job.piece_path(index)
        engine(job.pieces[index].strip(), str(path), lambda _f: None)
        job.record(index, 1.0)
    _cut_in_half(job.piece_path(0))
    again = _open(tmp_path)
    assert sorted(again.done) == [1]


def test_join_drops_a_piece_that_turned_out_short_and_the_next_run_redoes_it(
        tmp_path, small_pieces, monkeypatch):
    job = _open(tmp_path)
    engine = FakeEngine()
    for index in range(len(job.pieces)):
        engine(job.pieces[index].strip(), str(job.piece_path(index)), lambda _f: None)
        job.record(index, 1.0)
    # Piece 2 loses its tail after it was recorded (a lost write); the
    # take-over check is skipped here so join() meets the damage itself.
    _cut_in_half(job.piece_path(1))
    with pytest.raises(RuntimeError, match="piece 2"):
        job.join()
    assert 1 not in job.done
    assert job.piece_path(0).is_file()  # the good pieces are kept
    again = _open(tmp_path)
    assert again.pending() == [1]
    engine2 = FakeEngine()
    tts_job.run(again, engine2)
    assert engine2.spoken == [again.pieces[1].strip()]
    assert again.output_path.is_file()


def test_record_flushes_the_piece_to_disk_before_saving_progress(tmp_path, small_pieces,
                                                                  monkeypatch):
    synced: list = []
    real = os.fsync

    def spy(fd: int) -> None:
        synced.append(fd)
        real(fd)

    job = _open(tmp_path)
    FakeEngine()(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None)
    monkeypatch.setattr(tts_job.os, "fsync", spy)
    job.record(0, 1.0)
    # One fsync for the piece, one for the progress file written after it.
    assert len(synced) >= 2


# ------------------------------------------------- one job, one instance (B3)


def test_a_job_another_instance_is_running_cannot_run_or_be_discarded(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    engine(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None)
    job.record(0, 1.0)
    other = _open(tmp_path)  # the second window's view of the same job
    with job.claimed():
        with pytest.raises(tts_job.JobBusy):
            tts_job.run(other, FakeEngine())
        with pytest.raises(tts_job.JobBusy):
            other.discard()
        assert other.piece_path(0).is_file()  # the first window's piece survives
    other.discard()  # free again once the first one is done
    assert not other.piece_path(0).exists()


def test_the_lock_is_released_after_a_run_and_after_an_error(tmp_path, small_pieces):
    job = _open(tmp_path)

    def broken(_text: str, _path: str, _cb) -> float:
        raise RuntimeError("engine fell over")

    with pytest.raises(RuntimeError, match="engine fell over"):
        tts_job.run(job, broken)
    tts_job.run(_open(tmp_path), FakeEngine())  # not left locked


# --------------------------------------------- speechless pieces (S08-4)


def test_a_scene_break_piece_is_not_sent_to_the_engine(tmp_path, monkeypatch):
    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 500)
    para = "word " * 99 + "ends."  # exactly one piece: the break cannot join either side
    text = para + "\n***\n" + para
    job = tts_job.open_job("kokoro", text, VOICE, 1.0, root=tmp_path)
    assert any(p.strip() == "***" for p in job.pieces)  # the splitter's own cut

    def engine(piece: str, path: str, cb) -> float:
        if not any(ch.isalnum() for ch in piece):
            return 0.0  # a real engine writes no audio for "***"
        return FakeEngine()(piece, path, cb)

    result = tts_job.run(job, engine)
    assert Path(result.output_path).is_file()
    assert result.audio_seconds > 0


def test_a_job_with_no_speech_at_all_is_refused(tmp_path, small_pieces):
    with pytest.raises(ValueError, match="nothing to speak"):
        tts_job.Job(tmp_path, "k" * 64, "kokoro", ["*** ", "--- ", "..."])


# ------------------------------------------------ Thai and Lao (S08-5)


_THAI_LEADING = set("\u0e40\u0e41\u0e42\u0e43\u0e44")
_LAO_LEADING = set("\u0ec0\u0ec1\u0ec2\u0ec3\u0ec4")


def test_a_hard_cut_never_falls_right_after_a_leading_vowel():
    """No leading vowel in the window's second half: the fallback cut must
    still not separate the one before it from its consonant."""
    ko, sara_e, mai_ek = "\u0e01", "\u0e40", "\u0e48"
    text = ko + ko + sara_e + ko + mai_ek + ko * 3
    pieces = tts_job.split_text(text, 4)
    assert pieces[0] == ko + ko
    assert all(tts_job._joins_next(ch) for ch in "\u0e40\u0e41\u0e42\u0e43\u0e44"
               "\u0ec0\u0ec1\u0ec2\u0ec3\u0ec4")


@pytest.mark.parametrize("text, lead", [
    # Thai, no spaces and no punctuation (the reviewer's probe text).
    ("\u0e40\u0e14\u0e47\u0e01\u0e44\u0e17\u0e22\u0e44\u0e1b\u0e42\u0e23\u0e07\u0e40\u0e23"
     "\u0e35\u0e22\u0e19\u0e41\u0e15\u0e48\u0e40\u0e0a\u0e49\u0e32\u0e40\u0e1e\u0e23\u0e32"
     "\u0e30\u0e43\u0e08\u0e14\u0e35" * 200, _THAI_LEADING),
    # Lao, the same shape.
    ("\u0ec0\u0e94\u0eb1\u0e81\u0ec4\u0e9b\u0ec2\u0eae\u0e87\u0ec0\u0eae\u0e8d\u0e99" * 300,
     _LAO_LEADING),
], ids=["thai", "lao"])
@pytest.mark.parametrize("limit", [37, 500, 2000])
def test_thai_and_lao_are_never_cut_after_a_leading_vowel(text, lead, limit):
    pieces = tts_job.split_text(text, limit)
    assert "".join(pieces) == text
    assert len(pieces) > 1
    assert all(len(p.strip()) <= limit for p in pieces)
    assert [i for i, p in enumerate(pieces[:-1]) if p[-1] in lead] == []
    # Sara Am and the other following vowels stay with their syllable too.
    assert [p[:1] for p in pieces[1:] if p[0] in "\u0e30\u0e32\u0e33\u0e45\u0eb0\u0eb2\u0eb3"] == []


# ------------------------------------------------ fresh review (C2.62)


def test_a_window_opened_before_another_finished_the_job_speaks_nothing(tmp_path, small_pieces):
    stale = _open(tmp_path)  # window B planned the job ...
    tts_job.run(_open(tmp_path), FakeEngine())  # ... window A then finished it
    out = stale.folder / tts_job.OUTPUT_FILE
    stamp = out.stat().st_mtime_ns
    engine = FakeEngine()
    result = tts_job.run(stale, engine)
    assert engine.spoken == [] and result.pieces_run == 0
    assert out.stat().st_mtime_ns == stamp


def test_a_window_opened_earlier_skips_pieces_another_finished_meanwhile(tmp_path, small_pieces):
    stale = _open(tmp_path)
    other = _open(tmp_path)
    engine = FakeEngine()
    for index in (0, 1):
        engine(other.pieces[index].strip(), str(other.piece_path(index)), lambda _f: None)
        other.record(index, 1.0)
    engine2 = FakeEngine()
    tts_job.run(stale, engine2)
    assert engine2.spoken == [p.strip() for p in stale.pieces[2:]]


def test_on_joined_runs_before_the_job_is_marked_finished(tmp_path, small_pieces):
    job = _open(tmp_path)
    seen: list = []

    def on_joined(path: Path) -> None:
        seen.append((path.is_file(), job.finished_path.exists()))

    tts_job.run(job, FakeEngine(), on_joined=on_joined)
    assert seen == [(True, False)]
    assert _open(tmp_path).finished


def test_a_failing_on_joined_leaves_the_job_unfinished_with_its_pieces(tmp_path, small_pieces):
    job = _open(tmp_path)

    def boom(_path: Path) -> None:
        raise RuntimeError("crash while writing the consent record")

    with pytest.raises(RuntimeError, match="consent record"):
        tts_job.run(job, FakeEngine(), on_joined=boom)
    again = _open(tmp_path)
    assert not again.finished and again.pending() == []  # the next run only joins
    engine = FakeEngine()
    tts_job.run(again, engine)
    assert engine.spoken == [] and _open(tmp_path).finished
