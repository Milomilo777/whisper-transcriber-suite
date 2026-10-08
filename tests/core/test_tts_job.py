"""Long Text to Voice jobs written piece by piece (core/tts_job.py): the
splitter, resuming an unfinished job, the join, the AI-generated tag and the
scratch sweep that must keep unfinished jobs."""
from __future__ import annotations

import json
import os
import random
import threading
import time
import unicodedata
import wave
from pathlib import Path

import pytest

from core import synthetic_audio, tts_job, tts_plan

RATE = 1000  # fake engines write 1,000 frames per second of "speech"


# ------------------------------------------------------------------ splitting

_WORD_CHARS = "abcdefghij" + "\u0633\u0644\u0627\u0645\u062f\u0646\u06cc\u0627" + "\u65e5\u672c\u8a9e\u4e2d\u6587" + "\u0915\u0937"
_MARKS = ("\u0301", "\u064e", "\u094d", "\u200d", "\ufe0f")
_SEPARATORS = (" ", " ", " ", "  ", "\n", "\n\n", "\t")
_ENDS = (".", "!", "?", "...", ",", ";", ":", "\u3002", "\u061f", "\u060c", ".\"", "")


def _cluster(rng: random.Random) -> str:
    """A base character with up to two marks/joiners after it."""
    return rng.choice(_WORD_CHARS) + "".join(rng.choice(_MARKS) for _ in range(rng.randint(0, 2)))


def _random_text(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.randint(0, 40)):
        word = "".join(_cluster(rng) for _ in range(rng.randint(1, 12)))
        parts.append(word + rng.choice(_ENDS) + rng.choice(_SEPARATORS))
    lead = rng.choice(("", " ", "\n"))
    return lead + "".join(parts)


def _check_split(text: str, max_chars: int, pieces: "list[str]") -> None:
    assert "".join(pieces) == text, "text lost or reordered"
    assert all(pieces), "empty piece"
    for p in pieces:
        assert len(p.strip()) <= max_chars, (max_chars, p)
    if text.strip():
        assert all(p.strip() for p in pieces), "a piece of spaces only"
    if max_chars >= 3:  # every cluster here is at most 3 characters long
        for p in pieces[1:]:
            assert not tts_job._continues_cluster(p[0]), ("split inside a cluster", p[:3])


def test_split_property_random_texts():
    """Property-style check over 3,000 random texts in several scripts: the
    pieces give back the whole text in order, none is over the limit, none
    is empty or only spaces, and no piece starts inside a character cluster."""
    rng = random.Random(2025)
    for _ in range(3000):
        text = _random_text(rng)
        max_chars = rng.randint(1, 80)
        _check_split(text, max_chars, tts_job.split_text(text, max_chars))


@pytest.mark.parametrize("engine", sorted(tts_job.PIECE_CHARS))
def test_split_property_at_the_real_piece_sizes(engine):
    rng = random.Random(7)
    limit = tts_job.PIECE_CHARS[engine]
    for _ in range(200):
        text = "".join(_random_text(rng) for _ in range(rng.randint(1, 30)))
        pieces = tts_job.split_text(text, limit)
        _check_split(text, limit, pieces)
        assert all(len(p.strip()) <= tts_plan.MAX_PASS_CHARS for p in pieces)


def test_split_cuts_at_sentence_ends_first():
    text = "One two three. Four five six! Seven eight nine? Ten."
    assert tts_job.split_text(text, 30) == [
        "One two three. Four five six! ", "Seven eight nine? Ten."]


def test_split_long_sentence_at_clauses_then_spaces_then_hard():
    assert tts_job.split_text("aaaa bbbb, cccc dddd", 12) == ["aaaa bbbb, ", "cccc dddd"]
    assert tts_job.split_text("aaaa bbbb cccc", 10) == ["aaaa bbbb ", "cccc"]
    assert tts_job.split_text("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_split_hard_cut_keeps_marks_with_their_letter():
    text = "k\u094d\u0937" * 4  # Devanagari conjuncts, no spaces
    pieces = tts_job.split_text(text, 4)
    assert "".join(pieces) == text
    assert all(not unicodedata.combining(p[0]) and p[0] != "\u200d" for p in pieces)


def test_split_hard_cut_never_splits_a_conjunct():
    ka, virama, ssa = chr(0x915), chr(0x94D), chr(0x937)  # Devanagari k + virama + ssa
    text = (ka + virama + ssa) * 4
    for limit in range(3, 9):
        pieces = tts_job.split_text(text, limit)
        assert "".join(pieces) == text
        assert all(len(p) % 3 == 0 for p in pieces), (limit, pieces)


def test_split_hard_cut_keeps_emoji_sequences_and_jamo_whole():
    zwj = chr(0x200D)
    family = chr(0x1F468) + zwj + chr(0x1F469) + zwj + chr(0x1F467)  # ZWJ sequence
    thumbs = chr(0x1F44D) + chr(0x1F3FD)                              # with a skin tone
    jamo = chr(0x1100) + chr(0x1161) + chr(0x11A8)                    # decomposed Hangul
    for unit in (family, thumbs, jamo):
        text = unit * 6
        for limit in range(len(unit), 3 * len(unit)):
            pieces = tts_job.split_text(text, limit)
            assert "".join(pieces) == text
            assert all(len(p) % len(unit) == 0 for p in pieces), (unit, limit, pieces)


def test_split_cjk_and_persian_sentence_ends():
    assert tts_job.split_text("\u4f60\u597d\u3002\u6211\u5f88\u597d\u3002\u8c22\u8c22\u3002", 4) == ["\u4f60\u597d\u3002", "\u6211\u5f88\u597d\u3002", "\u8c22\u8c22\u3002"]
    assert tts_job.split_text("\u0633\u0644\u0627\u0645\u061f \u062e\u0648\u0628\u06cc. \u0645\u0645\u0646\u0648\u0646", 7) == ["\u0633\u0644\u0627\u0645\u061f ", "\u062e\u0648\u0628\u06cc. ", "\u0645\u0645\u0646\u0648\u0646"]


def test_split_whitespace_never_becomes_its_own_piece():
    text = "First sentence here." + "\n" * 50 + "Second one."
    pieces = tts_job.split_text(text, 25)
    assert pieces == ["First sentence here." + "\n" * 50, "Second one."]


def test_split_rejects_a_zero_limit():
    with pytest.raises(ValueError):
        tts_job.split_text("abc", 0)


def test_property_check_fails_on_a_broken_splitter(monkeypatch):
    """The property check above catches a splitter that drops the spaces at
    a cut (a deliberately broken version)."""
    real = tts_job._split_long

    def broken(seg: str, max_chars: int) -> "list[str]":
        return [p.rstrip(" ") or p for p in real(seg, max_chars)]

    monkeypatch.setattr(tts_job, "_split_long", broken)
    text = "aaaa bbbb cccc dddd eeee"
    with pytest.raises(AssertionError, match="text lost"):
        _check_split(text, 10, tts_job.split_text(text, 10))


# ------------------------------------------------------------------ job helpers


def _write_wav(path: str, seconds: float, rate: int = RATE, value: int = 1) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(value.to_bytes(2, "little", signed=True) * int(seconds * rate))


class FakeEngine:
    """Writes one WAV per piece: one second per 10 characters, each piece's
    samples set to its own number so the join order can be checked."""

    def __init__(self, cancel_after: "int | None" = None,
                 cancel_event: "threading.Event | None" = None) -> None:
        self.spoken: list[str] = []
        self.cancel_after = cancel_after
        self.cancel_event = cancel_event

    def __call__(self, text: str, path: str, on_fraction) -> float:
        self.spoken.append(text)
        on_fraction(0.5)
        _write_wav(path, len(text) / 10.0, value=len(self.spoken))
        synthetic_audio.tag_wav(path)  # the real engines tag every file they write
        on_fraction(1.0)
        if self.cancel_after is not None and len(self.spoken) >= self.cancel_after:
            assert self.cancel_event is not None
            self.cancel_event.set()
        return len(text) / 20.0


TEXT = " ".join(f"Sentence number {i} is here." for i in range(1, 13))
VOICE: "dict[str, object]" = {"voice": "af_heart"}


@pytest.fixture
def small_pieces(monkeypatch):
    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 60)


def _open(root: Path, text: str = TEXT, voice: "dict[str, object] | None" = None,
          speed: float = 1.0):
    return tts_job.open_job("kokoro", text, voice or VOICE, speed, root=root)


# ------------------------------------------------------------------ run / resume


def test_run_speaks_every_piece_and_joins_one_file(tmp_path, small_pieces):
    job = _open(tmp_path)
    assert len(job.pieces) > 3
    engine = FakeEngine()
    result = tts_job.run(job, engine)
    assert engine.spoken == [p.strip() for p in job.pieces]
    out = Path(result.output_path)
    assert out == job.output_path and out.is_file()
    assert not job.parts_dir.exists()  # pieces removed after a checked join
    assert result.pieces_run == len(job.pieces)
    assert result.audio_seconds == pytest.approx(sum(len(p.strip()) / 10.0 for p in job.pieces))


def test_join_equals_the_pieces_concatenated(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    for i in job.pending():
        compute = engine(job.pieces[i].strip(), str(job.piece_path(i)), lambda _f: None)
        job.record(i, compute)
    expected = b""
    for i in range(len(job.pieces)):
        with wave.open(str(job.piece_path(i)), "rb") as w:
            expected += w.readframes(w.getnframes())
    out = job.join()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
        assert w.readframes(w.getnframes()) == expected


def test_final_file_and_pieces_carry_the_ai_tag(tmp_path, small_pieces):
    job = _open(tmp_path)
    cancel = threading.Event()
    with pytest.raises(tts_job.Cancelled):
        tts_job.run(job, FakeEngine(cancel_after=1, cancel_event=cancel), cancel_event=cancel)
    piece = job.piece_path(0)
    assert synthetic_audio.read_info(piece)["ICMT"] == synthetic_audio.AI_COMMENT
    result = tts_job.run(_open(tmp_path), FakeEngine())
    info = synthetic_audio.read_info(result.output_path)
    assert info["ICMT"] == synthetic_audio.AI_COMMENT
    assert info["ISFT"].startswith(synthetic_audio.APP_DISPLAY_NAME)


def test_cancel_keeps_finished_pieces_and_resume_skips_them(tmp_path, small_pieces):
    cancel = threading.Event()
    first = FakeEngine(cancel_after=2, cancel_event=cancel)
    with pytest.raises(tts_job.Cancelled):
        tts_job.run(_open(tmp_path), first, cancel_event=cancel)
    assert len(first.spoken) == 2

    again = _open(tmp_path)  # a new run (new app session) of the same job
    assert sorted(again.done) == [0, 1]
    second = FakeEngine()
    result = tts_job.run(again, second)
    assert second.spoken == [p.strip() for p in again.pieces[2:]]
    assert result.pieces_run == len(again.pieces) - 2
    with wave.open(result.output_path, "rb") as w:
        total = w.getnframes()
    assert total == sum(int(len(p.strip()) / 10.0 * RATE) for p in again.pieces)


def test_crash_mid_piece_redoes_only_that_piece(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    for i in (0, 1):
        job.record(i, engine(job.pieces[i].strip(), str(job.piece_path(i)), lambda _f: None))
    # Power cut while piece 3 was being written: a half file, never recorded.
    job.piece_path(2).write_bytes(b"RIFF\x00\x00")
    again = _open(tmp_path)
    assert sorted(again.done) == [0, 1]
    assert again.pending()[0] == 2


def test_a_recorded_piece_that_changed_on_disk_is_redone(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    job.record(0, engine(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None))
    _write_wav(str(job.piece_path(0)), 0.5)  # shorter than recorded
    assert _open(tmp_path).done == {}


@pytest.mark.parametrize("change", ["text", "voice", "speed"])
def test_another_text_voice_or_speed_is_another_job(tmp_path, small_pieces, change):
    job = _open(tmp_path)
    job.record(0, FakeEngine()(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None))
    other = {"text": dict(text=TEXT + " One more."), "voice": dict(voice={"voice": "am_adam"}),
             "speed": dict(speed=1.25)}[change]
    assert _open(tmp_path, **other).done == {}
    assert sorted(_open(tmp_path).done) == [0]  # the original job is untouched


def test_damaged_progress_file_starts_fresh(tmp_path, small_pieces):
    job = _open(tmp_path)
    job.record(0, FakeEngine()(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None))
    job.progress_path.write_text("{not json", encoding="utf-8")
    assert _open(tmp_path).done == {}


def test_progress_file_is_small_and_names_no_text(tmp_path, small_pieces):
    job = _open(tmp_path)
    job.record(0, FakeEngine()(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None))
    data = json.loads(job.progress_path.read_text(encoding="utf-8"))
    assert data["key"] == job.key and list(data["done"]) == ["0"]
    assert "Sentence" not in job.progress_path.read_text(encoding="utf-8")


def test_discard_forgets_the_pieces(tmp_path, small_pieces):
    job = _open(tmp_path)
    job.record(0, FakeEngine()(job.pieces[0].strip(), str(job.piece_path(0)), lambda _f: None))
    job.discard()
    assert job.done == {} and not job.parts_dir.exists()
    assert _open(tmp_path).done == {}


def test_join_refuses_pieces_in_another_format(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    for i in job.pending():
        job.record(i, engine(job.pieces[i].strip(), str(job.piece_path(i)), lambda _f: None))
    _write_wav(str(job.piece_path(1)), len(job.pieces[1].strip()) / 10.0, rate=RATE * 2)
    job.done[1] = tts_job.PieceDone(
        int(len(job.pieces[1].strip()) / 10.0 * RATE * 2), 1.0, 1.0)
    with pytest.raises(RuntimeError, match="another audio format"):
        job.join()
    assert job.parts_dir.exists() and not job.output_path.exists()  # pieces kept


def test_join_removes_temp_files_a_killed_join_left(tmp_path, small_pieces):
    job = _open(tmp_path)
    engine = FakeEngine()
    for i in job.pending():
        job.record(i, engine(job.pieces[i].strip(), str(job.piece_path(i)), lambda _f: None))
    (job.folder / ".join-dead.wav").write_bytes(b"x" * 100)
    (job.folder / ".tag-dead.tmp").write_bytes(b"x" * 100)
    job.join()
    # Only the joined file and its finished marker are left (no temp files).
    assert sorted(p.name for p in job.folder.iterdir()) == [
        tts_job.FINISHED_FILE, tts_job.OUTPUT_FILE]


def test_join_before_all_pieces_are_done_raises(tmp_path, small_pieces):
    with pytest.raises(RuntimeError, match="not finished"):
        _open(tmp_path).join()


def test_an_engine_error_keeps_the_finished_pieces(tmp_path, small_pieces):
    calls = []

    def flaky(text: str, path: str, on_fraction) -> float:
        calls.append(text)
        if len(calls) == 3:
            raise RuntimeError("engine broke")
        _write_wav(path, 1.0)
        return 0.5

    with pytest.raises(RuntimeError, match="engine broke"):
        tts_job.run(_open(tmp_path), flaky)
    assert sorted(_open(tmp_path).done) == [0, 1]


# ------------------------------------------------------------------ progress


def test_progress_reports_time_left_from_measured_speed(tmp_path, small_pieces):
    job = _open(tmp_path)
    seen: list[tts_job.Progress] = []
    tts_job.run(job, FakeEngine(), on_progress=seen.append, fallback_per_unit=1.0)
    assert seen[0].pieces_done == 0 and seen[0].fraction == 0.0
    # Before any piece is done: the fallback figure (1 s per unit).
    assert seen[0].seconds_left == pytest.approx(job.total_units)
    assert seen[-1].pieces_done == len(job.pieces) and seen[-1].fraction == pytest.approx(1.0)
    assert seen[-1].seconds_left == pytest.approx(0.0)
    fractions = [p.fraction for p in seen]
    assert fractions == sorted(fractions)


def test_seconds_left_maths(tmp_path, small_pieces):
    job = _open(tmp_path)
    assert tts_job.seconds_left(job) is None
    assert tts_job.seconds_left(job, fallback_per_unit=2.0) == pytest.approx(2 * job.total_units)
    job.done[0] = tts_job.PieceDone(1000, 1.0, 10.0)  # 10 s for piece 1
    per_unit = 10.0 / job.units[0]
    assert tts_job.seconds_left(job) == pytest.approx((job.total_units - job.units[0]) * per_unit)


# ------------------------------------------------------------------ sweep


def test_sweep_keeps_unfinished_jobs_longer(tmp_path, monkeypatch, small_pieces):
    from core import config, voice_clone

    monkeypatch.setattr(config, "user_cache_dir", lambda: tmp_path)
    root = tmp_path / "voice_clone"
    old = time.time() - 10 * 86400
    ancient = time.time() - 40 * 86400

    def unfinished(name: str, when: float) -> Path:
        job = tts_job.Job(root, name * 4, "kokoro", ["Hello there."])
        _write_wav(str(job.piece_path(0)), 1.0)
        job.record(0, 1.0)
        for p in (job.progress_path, job.parts_dir, job.folder):
            os.utime(p, (when, when))
        return job.folder

    kept = unfinished("aaaa", old)          # 10 days: kept (unfinished)
    swept = unfinished("bbbb", ancient)     # 40 days: swept
    session = root / "20260101-000000"      # an ordinary 10-day-old session dir
    session.mkdir(parents=True)
    os.utime(session, (old, old))
    voice_clone.sweep_old_session_dirs()
    assert kept.exists()
    assert not swept.exists() and not session.exists()


# ------------------------------------------------------------------ limits


def test_text_limit_follows_the_local_setting():
    assert tts_plan.text_limit(None) == tts_plan.MAX_TEXT_CHARS == 100_000
    assert tts_plan.text_limit({}) == tts_plan.MAX_TEXT_CHARS
    assert tts_plan.text_limit({tts_plan.NO_LIMIT_KEY: False}) == tts_plan.MAX_TEXT_CHARS
    assert tts_plan.text_limit({tts_plan.NO_LIMIT_KEY: "yes"}) == tts_plan.MAX_TEXT_CHARS
    assert tts_plan.text_limit({tts_plan.NO_LIMIT_KEY: True}) is None


def test_no_limit_key_is_local_only_and_off_by_default(monkeypatch):
    from core import config as cfg

    assert cfg.DEFAULT_CONFIG[tts_plan.NO_LIMIT_KEY] is False
    assert tts_plan.NO_LIMIT_KEY in cfg.LOCAL_ONLY_KEYS
    assert tts_plan.NO_LIMIT_KEY not in cfg.ONLINE_ALLOWED_KEYS
    # Even a mistaken allowlist entry cannot let the online layer turn it on.
    monkeypatch.setattr(cfg, "ONLINE_ALLOWED_KEYS",
                        cfg.ONLINE_ALLOWED_KEYS | {tts_plan.NO_LIMIT_KEY})
    merged = cfg.merge_config_sources(
        {tts_plan.NO_LIMIT_KEY: False}, {tts_plan.NO_LIMIT_KEY: True}, None)
    assert merged[tts_plan.NO_LIMIT_KEY] is False


def test_piece_job_needs_room_for_pieces_and_the_joined_file():
    """Peak: every piece, the joined file and its tagged copy at once."""
    est = tts_plan.estimate("word " * 2000, "kokoro", "cpu")
    assert tts_plan.piece_job_need_bytes(est) == pytest.approx(3 * est.size_high, abs=1)
    assert tts_plan.piece_job_need_bytes(est, 0.0) == pytest.approx(2 * est.size_high, abs=1)
    disk = tts_plan.check_disk(est, need_bytes=123)
    assert disk.need_bytes == 123
