"""AI-generated tag + local consent record for synthesised audio
(core/synthetic_audio.py, called by core/voice_clone.py and core/tts_kokoro.py)."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import types
import wave
from pathlib import Path

import pytest

from core import synthetic_audio as sa
from core import tts_kokoro, voice_clone


def _write_wav(path: Path, frames: bytes, *, sampwidth: int = 2, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(frames)


def _chunks(raw: bytes) -> "list[tuple[bytes, bytes]]":
    """Independent top-level RIFF parser: (chunk id, body)."""
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    out, pos = [], 12
    while pos + 8 <= len(raw):
        cid, size = struct.unpack("<4sI", raw[pos:pos + 8])
        out.append((cid, raw[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return out


def _data(raw: bytes) -> bytes:
    return next(body for cid, body in _chunks(raw) if cid == b"data")


def _frames(path: Path) -> "tuple[tuple, bytes]":
    with wave.open(str(path), "rb") as w:
        return (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), \
            w.readframes(w.getnframes())


PCM = bytes(range(256)) * 40  # 10240 bytes, not silence


# ---------- tag_wav ------------------------------------------------------


def test_tag_wav_adds_info_and_keeps_frames(tmp_path):
    plain, tagged = tmp_path / "plain.wav", tmp_path / "tagged.wav"
    _write_wav(plain, PCM)
    _write_wav(tagged, PCM)
    sa.tag_wav(tagged)

    raw = tagged.read_bytes()
    assert struct.unpack("<I", raw[4:8])[0] == len(raw) - 8
    ids = [cid for cid, _ in _chunks(raw)]
    assert ids == [b"fmt ", b"LIST", b"data"]
    info = next(body for cid, body in _chunks(raw) if cid == b"LIST")
    assert info.startswith(b"INFO")
    assert b"ICMT" in info and sa.AI_COMMENT.encode() + b"\x00" in info
    assert b"ISFT" in info
    assert sa.read_info(tagged) == {"ICMT": sa.AI_COMMENT, "ISFT": sa.software_name()}
    assert _data(raw) == _data(plain.read_bytes()) == PCM
    assert _frames(tagged) == _frames(plain)


def test_software_name_carries_the_version():
    import core

    assert sa.software_name() == f"Whisper Transcriber Suite {core.__version__}"


def test_tag_wav_twice_keeps_one_info_chunk(tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, PCM)
    sa.tag_wav(p)
    first = p.read_bytes()
    sa.tag_wav(p)
    assert p.read_bytes() == first
    assert [cid for cid, _ in _chunks(first)].count(b"LIST") == 1


def test_tag_wav_keeps_other_chunks_and_info_entries(tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, PCM)
    raw = p.read_bytes()
    fmt = _chunks(raw)[0][1]
    # A foreign file: custom chunk, an INFO list after data with a title
    # and an old comment, and an odd-sized chunk that needs a pad byte.
    old_info = b"INFO" + b"INAM" + struct.pack("<I", 6) + b"Title\x00" + \
        b"ICMT" + struct.pack("<I", 4) + b"old\x00"
    body = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"junk" + struct.pack("<I", 3) + b"xyz\x00"
            + b"data" + struct.pack("<I", len(PCM)) + PCM
            + b"LIST" + struct.pack("<I", len(old_info)) + old_info)
    p.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)

    sa.tag_wav(p)
    chunks = _chunks(p.read_bytes())
    assert [cid for cid, _ in chunks] == [b"fmt ", b"junk", b"LIST", b"data"]
    assert chunks[1][1] == b"xyz"
    assert sa.read_info(p) == {"ISFT": sa.software_name(), "ICMT": sa.AI_COMMENT,
                               "INAM": "Title"}
    assert _frames(p)[1] == PCM


def test_tag_wav_odd_sized_data_chunk(tmp_path):
    p = tmp_path / "odd.wav"
    _write_wav(p, b"\x01\x02\x03", sampwidth=1)  # 3 bytes: data needs a pad byte
    before = _frames(p)
    sa.tag_wav(p)
    raw = p.read_bytes()
    assert len(raw) % 2 == 0
    assert _data(raw) == b"\x01\x02\x03"
    assert _frames(p) == before


@pytest.mark.parametrize("content", [
    b"not a wav at all",
    b"RIFF\x10\x00\x00\x00WAVEfmt \x10\x00\x00\x00",  # fmt runs past the end
    b"RIFF\x04\x00\x00\x00WAVE",                       # no fmt / data
])
def test_tag_wav_rejects_bad_input_and_leaves_it_alone(tmp_path, content):
    p = tmp_path / "bad.wav"
    p.write_bytes(content)
    with pytest.raises(ValueError):
        sa.tag_wav(p)
    assert p.read_bytes() == content
    assert [f.name for f in tmp_path.iterdir()] == ["bad.wav"]  # no temp file left


def test_tag_wav_file_opens_with_soundfile(tmp_path):
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    samples = np.sin(np.linspace(0, 200, 4801)).astype(np.float32) * 0.5
    plain, tagged = tmp_path / "plain.wav", tmp_path / "tagged.wav"
    sf.write(str(plain), samples, 24000)
    sf.write(str(tagged), samples, 24000)
    sa.tag_wav(tagged)
    assert _data(tagged.read_bytes()) == _data(plain.read_bytes())
    a, rate = sf.read(str(tagged), dtype="int16")
    b, _ = sf.read(str(plain), dtype="int16")
    assert rate == 24000 and (a == b).all()
    with sf.SoundFile(str(tagged)) as f:
        assert f.comment == sa.AI_COMMENT  # libsndfile reads ICMT itself


# ---------- consent record -------------------------------------------------


def test_append_consent_record_fields_and_append(tmp_path):
    out = tmp_path / "out.wav"
    _write_wav(out, PCM)
    refs = [tmp_path / "r1.wav", tmp_path / "r2.wav"]
    refs[0].write_bytes(b"first reference")
    refs[1].write_bytes(b"second reference")
    log = tmp_path / "logs" / "consent.jsonl"

    rec = sa.append_consent_record(out, [str(r) for r in refs], consent_accepted=True,
                                   engine="omnivoice", log_path=log)
    sa.append_consent_record(out, [str(refs[0])], consent_accepted=True,
                             engine="omnivoice", log_path=log)
    lines = log.read_bytes().split(b"\n")
    assert lines[-1] == b"" and len(lines) == 3  # two LF-terminated lines
    first = json.loads(lines[0])
    assert first == rec
    assert set(first) == {"time_utc", "output_file", "output_sha256", "reference_sha256",
                          "consent_accepted", "engine", "app_version"}
    assert first["output_file"] == str(out.resolve())
    assert first["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert first["reference_sha256"] == [
        hashlib.sha256(b"first reference").hexdigest(),
        hashlib.sha256(b"second reference").hexdigest(),
    ]
    assert first["consent_accepted"] is True
    assert first["time_utc"].endswith("Z")
    assert len(json.loads(lines[1])["reference_sha256"]) == 1


def test_append_consent_record_needs_a_reference(tmp_path):
    with pytest.raises(ValueError):
        sa.append_consent_record(tmp_path / "o.wav", [], consent_accepted=True,
                                 engine="omnivoice", log_path=tmp_path / "c.jsonl")
    assert not (tmp_path / "c.jsonl").exists()


def test_consent_log_lives_in_the_user_data_dir(monkeypatch, tmp_path):
    import core.config

    monkeypatch.setattr(core.config, "user_data_dir", lambda: tmp_path)
    assert sa.consent_log_path() == tmp_path / "voice_clone_consent.jsonl"


# ---------- both writers -------------------------------------------------


@pytest.fixture
def consent_log(monkeypatch, tmp_path):
    log = tmp_path / "data" / "voice_clone_consent.jsonl"
    monkeypatch.setattr(sa, "consent_log_path", lambda: log)
    return log


def _expected_pcm(samples: "list[float]") -> bytes:
    np = pytest.importorskip("numpy")
    arr = np.asarray(samples, dtype=np.float32)
    return (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def test_kokoro_output_is_tagged_and_frames_unchanged(monkeypatch, tmp_path, consent_log):
    samples = [((i % 50) - 25) / 30.0 for i in range(2401)]  # some clip past +-1

    class FakeEngine:
        def generate(self, text, sid, speed, callback):
            callback(None, 1.0)
            return types.SimpleNamespace(samples=samples, sample_rate=24000)

    monkeypatch.setattr(tts_kokoro, "_load", lambda lang: FakeEngine())
    out = tmp_path / "out" / "output.wav"
    result = tts_kokoro.generate("Hello there.", "af_heart", str(out))

    assert result.output_path == str(out)
    assert sa.read_info(out)["ICMT"] == sa.AI_COMMENT
    params, frames = _frames(out)
    assert params == (1, 2, 24000, 2401)
    assert frames == _expected_pcm(samples)
    assert not consent_log.exists()  # ready-made voice: no reference audio


def _wave_soundfile(written: list) -> types.SimpleNamespace:
    """Stand-in for the on-demand ``soundfile`` that writes a real 16-bit WAV."""
    def write(path, data, sr):
        written.append((path, sr))
        pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767)) for x in data)
        _write_wav(Path(path), pcm, rate=sr)
    return types.SimpleNamespace(write=write)


class _FakeModel:
    def __init__(self):
        self.calls: list[dict] = []

    def generate(self, **kw):
        self.calls.append(kw)
        return [[0.25, -0.5, 0.75] * 800]


def test_voice_clone_with_reference_tags_and_records_consent(monkeypatch, tmp_path, consent_log):
    written: list = []
    monkeypatch.setitem(sys.modules, "soundfile", _wave_soundfile(written))
    refs = []
    for i in range(4):  # one more than MAX_REFERENCE_SAMPLES
        r = tmp_path / f"ref{i}.wav"
        r.write_bytes(f"reference {i}".encode())
        refs.append(str(r))
    combined = tmp_path / "combined.wav"

    def fake_concat(paths):
        combined.write_bytes(b"combined")
        return str(combined)

    monkeypatch.setattr(voice_clone, "_concat_references", fake_concat)
    out = tmp_path / "session" / "output.wav"
    model = _FakeModel()
    voice_clone.generate(model, "hello", refs, str(out), consent_accepted=True)

    assert model.calls[0]["ref_audio"] == str(combined)
    assert sa.read_info(out)["ICMT"] == sa.AI_COMMENT
    lines = consent_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["engine"] == "omnivoice" and rec["consent_accepted"] is True
    assert rec["reference_sha256"] == [
        hashlib.sha256(f"reference {i}".encode()).hexdigest()
        for i in range(voice_clone.MAX_REFERENCE_SAMPLES)
    ]
    assert rec["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_voice_clone_design_mode_tags_without_consent_record(monkeypatch, tmp_path, consent_log):
    written: list = []
    monkeypatch.setitem(sys.modules, "soundfile", _wave_soundfile(written))
    out = tmp_path / "output.wav"
    voice_clone.generate(_FakeModel(), "hi", [], str(out), consent_accepted=False,
                         instruct="female")
    voice_clone.generate(_FakeModel(), "hi", [], str(out), consent_accepted=False)
    assert len(written) == 2
    assert sa.read_info(out)["ICMT"] == sa.AI_COMMENT
    assert _frames(out)[0] == (1, 2, 24000, 2400)
    assert not consent_log.exists()


# ---------- failure paths (review findings) ------------------------------


def test_tag_wav_leaves_no_temp_when_the_source_cannot_be_opened(monkeypatch, tmp_path):
    p = tmp_path / "locked.wav"
    _write_wav(p, PCM)
    before = p.read_bytes()

    def deny(*_a, **_k):
        raise PermissionError("held open by another program")

    monkeypatch.setattr(sa, "open", deny, raising=False)  # shadows builtins.open
    with pytest.raises(PermissionError):
        sa.tag_wav(p)
    monkeypatch.undo()
    assert p.read_bytes() == before
    assert [f.name for f in tmp_path.iterdir()] == ["locked.wav"]


def test_tag_wav_retries_a_briefly_locked_rename(monkeypatch, tmp_path):
    import os

    p = tmp_path / "a.wav"
    _write_wav(p, PCM)
    real_replace = os.replace
    attempts: list[str] = []

    def flaky(src, dst):
        attempts.append(src)
        if len(attempts) < 3:
            raise PermissionError("[WinError 5] Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(sa, "_REPLACE_RETRY_DELAYS", (0, 0, 0, 0))
    monkeypatch.setattr(sa.os, "replace", flaky)
    sa.tag_wav(p)
    monkeypatch.undo()
    assert len(attempts) == 3
    assert sa.read_info(p)["ICMT"] == sa.AI_COMMENT
    assert [f.name for f in tmp_path.iterdir()] == ["a.wav"]


def test_tag_wav_gives_up_on_a_lasting_lock_and_cleans_up(monkeypatch, tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, PCM)
    before = p.read_bytes()

    def locked(src, dst):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(sa, "_REPLACE_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(sa.os, "replace", locked)
    with pytest.raises(PermissionError):
        sa.tag_wav(p)
    monkeypatch.undo()
    assert p.read_bytes() == before
    assert [f.name for f in tmp_path.iterdir()] == ["a.wav"]


def test_voice_clone_keeps_the_result_when_the_consent_log_fails(monkeypatch, tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_bytes(b"")  # the log's parent folder is a file -> OSError
    monkeypatch.setattr(sa, "consent_log_path", lambda: blocker / "voice_clone_consent.jsonl")
    monkeypatch.setitem(sys.modules, "soundfile", _wave_soundfile([]))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"reference")
    out = tmp_path / "output.wav"

    result = voice_clone.generate(_FakeModel(), "hello", [str(ref)], str(out),
                                  consent_accepted=True)
    assert result.output_path == str(out)
    assert "consent record could not be saved" in result.warning
    assert sa.read_info(out)["ICMT"] == sa.AI_COMMENT


def test_voice_clone_result_has_no_warning_normally(monkeypatch, tmp_path, consent_log):
    monkeypatch.setitem(sys.modules, "soundfile", _wave_soundfile([]))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"reference")
    result = voice_clone.generate(_FakeModel(), "hello", [str(ref)],
                                  str(tmp_path / "o.wav"), consent_accepted=True)
    assert result.warning == ""
    assert consent_log.exists()


def test_worker_done_event_carries_the_warning(monkeypatch, capsys):
    import io

    from core import voice_clone_worker as vw

    monkeypatch.setattr(vw, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(voice_clone, "load_model", lambda device: object())
    monkeypatch.setattr(voice_clone, "generate", lambda *a, **k: voice_clone.GenerateResult(
        output_path="o.wav", audio_seconds=1.0, elapsed_seconds=2.0, warning="no record"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"action": "generate", "id": "r1", "text": "hi"}) + "\n"
        + json.dumps({"action": "shutdown"}) + "\n"))
    assert vw.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    done = [e for e in events if e["event"] == "done"]
    assert len(done) == 1 and done[0]["warning"] == "no record"


@pytest.mark.parametrize("sent, expected", [({"warning": "no record"}, "no record"), ({}, "")])
def test_service_passes_the_warning_through(sent, expected):
    import threading

    from app.services.voice_clone_service import VoiceCloneWorker

    worker = VoiceCloneWorker("entry.py")
    slot = {"event": threading.Event(), "result": None, "error": None}
    worker._pending["r1"] = slot
    worker._handle({"event": "done", "id": "r1", "output_path": "o.wav",
                    "audio_seconds": 1.0, "elapsed_seconds": 2.0, **sent})
    assert slot["event"].is_set()
    assert slot["result"]["warning"] == expected


@pytest.mark.parametrize("warning", ["The local consent record could not be saved: boom", ""])
def test_tab_shows_the_consent_warning(warning):
    from unittest import mock

    from app.widgets import voice_clone_tab

    app = mock.MagicMock()
    voice_clone_tab._generate_done(app, {"output_path": "o.wav", "audio_seconds": 3.0,
                                         "elapsed_seconds": 9.0, "warning": warning})
    status = app.vc_status_var.set.call_args[0][0]
    logged = [c[0][0] for c in app.log.call_args_list]
    if warning:
        assert "consent record was not saved" in status
        assert warning in logged
    else:
        assert "Warning" not in status
        assert logged == ["Text to voice finished: o.wav"]
