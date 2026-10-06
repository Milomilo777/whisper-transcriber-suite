"""Kokoro ready-made voices (core/tts_kokoro.py) -- no model needed."""
from __future__ import annotations

import pytest

from core import tts_kokoro as k


def test_voice_table_matches_the_model_order():
    # sherpa-onnx kokoro-multi-lang-v1_0: ids 0..52, em_santa appended at 53.
    assert len(k.VOICES) == 54
    assert [v.sid for v in k.VOICES] == list(range(54))
    assert k.voice_by_key("af_heart").sid == 3
    assert k.voice_by_key("am_adam").sid == 11
    assert k.voice_by_key("zm_yunyang").sid == 52
    assert k.voice_by_key("em_santa").sid == 53


def test_voice_labels_and_languages():
    heart = k.voice_by_key("af_heart")
    assert heart.label == "Heart — US English, female"
    assert k.voice_by_key("bm_george").lang_code == "en-gb"
    assert k.voice_by_key("jf_alpha").language == "Japanese"
    assert k.voice_by_key("hm_psi").gender == "male"
    assert len({v.label for v in k.VOICES}) == len(k.VOICES)


def test_unknown_voice_falls_back_to_default():
    assert k.voice_by_key("nope").key == k.DEFAULT_VOICE


def test_is_downloaded_false_for_empty_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "model_dir", lambda: tmp_path / "missing")
    assert k.is_downloaded() is False


def test_generate_rejects_empty_text():
    with pytest.raises(ValueError):
        k.generate("   ", "af_heart", "out.wav")


def test_generate_uses_the_shared_pass_limit(monkeypatch):
    """One call is one pass; longer texts go through core.tts_job in pieces."""
    from core import tts_plan

    monkeypatch.setattr(k, "_load", lambda _lang: pytest.fail("loaded a model"))
    with pytest.raises(ValueError, match=f"limit for one generation is {tts_plan.MAX_PASS_CHARS}"):
        k.generate("a" * (tts_plan.MAX_PASS_CHARS + 1), "af_heart", "out.wav")


def test_measure_speed_never_downloads(monkeypatch):
    monkeypatch.setattr(k, "is_downloaded", lambda: False)
    monkeypatch.setattr(k, "download", lambda **_k: pytest.fail("download started"))
    monkeypatch.setattr(k, "generate", lambda *_a, **_k: pytest.fail("generated"))
    with pytest.raises(RuntimeError, match="not downloaded"):
        k.measure_speed()


def test_measure_speed_speaks_the_fixed_text_and_removes_its_file(monkeypatch):
    import os

    from core import tts_plan

    seen = {}

    def fake_generate(text, voice, out, cancel_event=None, **_k):
        seen.update(text=text, voice=voice, out=out, cancel=cancel_event)
        with open(out, "wb") as f:
            f.write(b"RIFF")
        return k.KokoroResult(out, 10.0, 6.5)

    monkeypatch.setattr(k, "is_downloaded", lambda: True)
    monkeypatch.setattr(k, "generate", fake_generate)
    marker = object()
    result = k.measure_speed(cancel_event=marker)  # type: ignore[arg-type]
    assert (result.audio_seconds, result.elapsed_seconds) == (10.0, 6.5)
    assert seen["text"] == tts_plan.CALIBRATION_TEXT
    assert seen["voice"] == k.DEFAULT_VOICE and seen["cancel"] is marker
    assert not os.path.exists(seen["out"])
