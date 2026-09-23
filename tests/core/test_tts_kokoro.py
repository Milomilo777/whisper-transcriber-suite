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
