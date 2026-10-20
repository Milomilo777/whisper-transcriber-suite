"""Language-specialised models (ADR 0015): the table, the suggestion and the switch back."""
from __future__ import annotations

import copy

import pytest

from core import language_models as lm
from core import model_manager as mm
from core.backends import nvidia_asr


def test_every_row_points_at_something_the_app_can_load():
    for code, row in lm.LANGUAGE_MODELS.items():
        assert row.language == code
        assert row.source.startswith("https://huggingface.co/")
        assert row.size_gb > 0 and row.licence and row.claim
        if row.engine == lm.ENGINE_WHISPER:
            entry = mm.MODEL_REGISTRY[row.model]
            assert entry["language"] == code
            assert entry["approx_size_gb"] == pytest.approx(row.size_gb)
        else:
            assert row.engine == lm.ENGINE_TRANSFORMERS
            assert "/" in row.model


def test_every_one_language_registry_model_has_a_row():
    tagged = {slug for slug, e in mm.MODEL_REGISTRY.items() if e.get("language")}
    assert tagged == {r.model for r in lm.LANGUAGE_MODELS.values() if r.engine == lm.ENGINE_WHISPER}


def test_persian_row_runs_through_its_recipe():
    row = lm.LANGUAGE_MODELS["fa"]
    recipe = nvidia_asr.recipe_for(row.model)
    assert recipe is not None and recipe["kind"] == "rnnt" and recipe["writes"] == "fa"
    assert nvidia_asr.recipe_for(row.model.upper()) is recipe  # repo ids are case-insensitive


@pytest.mark.parametrize("language", ["", None, "auto", "en", "xx", "pt,pt-BR,pt-PT"])
def test_no_row_for_auto_or_other_languages(language):
    assert lm.for_language(language) is None


@pytest.mark.parametrize("code,row", [("zh-Hans,zh-CN", "zh"), ("zh-Hant,zh-TW", "zh"), ("FA", "fa"),
                                      ("de-AT", "de"), ("ja_JP", "ja")])
def test_picker_codes_find_their_row(code, row):
    assert lm.for_language(code) is lm.LANGUAGE_MODELS[row]


def test_every_row_language_is_in_the_picker():
    from app.domain.languages import SUBTITLE_LANGUAGES

    picker = {lm.normalize(c) for _n, c in SUBTITLE_LANGUAGES}
    assert set(lm.LANGUAGE_MODELS) <= picker


def _whisper_cfg(slug="large-v3"):
    return {"transcribe_backend": "faster_whisper", "whisper_model": slug,
            "model": mm.catalog_resolve_entry({}, slug), "model_path": ""}


def test_offer_when_the_language_has_a_model_not_in_use():
    assert lm.suggestion(_whisper_cfg(), "fa") == ("offer", lm.LANGUAGE_MODELS["fa"])
    assert lm.suggestion(_whisper_cfg(), "zh") == ("offer", lm.LANGUAGE_MODELS["zh"])
    assert lm.suggestion(_whisper_cfg(), "en") is None
    assert lm.suggestion(_whisper_cfg(), None) is None


def test_nothing_to_say_when_the_right_model_is_active():
    cfg = lm.apply_language_model(_whisper_cfg(), lm.LANGUAGE_MODELS["fa"])
    assert lm.suggestion(cfg, "fa") is None


@pytest.mark.parametrize("language", ["en", None])
def test_leave_when_a_one_language_model_meets_another_language(language):
    cfg = lm.apply_language_model(_whisper_cfg(), lm.LANGUAGE_MODELS["fa"])
    assert lm.suggestion(cfg, language) == ("leave", lm.LANGUAGE_MODELS["fa"])


def test_another_languages_model_is_offered_directly():
    # Persian model active, Chinese picked: offer the Chinese model, not "switch back" first
    cfg = lm.apply_language_model(_whisper_cfg(), lm.LANGUAGE_MODELS["fa"])
    assert lm.suggestion(cfg, "zh") == ("offer", lm.LANGUAGE_MODELS["zh"])


def test_restore_brings_back_a_model_folder_the_user_picked():
    cfg = {**_whisper_cfg("large-v3"), "model_path": "D:/models/my-finetune"}
    before = copy.deepcopy(cfg)
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["de"])
    assert cfg["model_path"] == ""
    lm.restore_previous(cfg)
    assert cfg == before


def test_restore_from_a_remembered_transformers_language_model_goes_to_whisper():
    cfg = {"transcribe_backend": "faster_whisper", "whisper_model": "belle-large-v3-turbo-zh",
           lm.PREVIOUS_KEY: {"transcribe_backend": "nvidia_asr",
                             "nvidia_asr_model_id": "mehdi-hf/nemotron-asr-streaming-farsi"}}
    lm.restore_previous(cfg)
    assert cfg["transcribe_backend"] == "faster_whisper"
    assert cfg["whisper_model"] == mm.DEFAULT_MODEL_SLUG
    assert "nvidia_asr_model_id" not in cfg and lm.active(cfg) is None


def test_restore_to_parakeet_keeps_the_users_engine():
    cfg = {"transcribe_backend": "nvidia_asr", "nvidia_asr_model_id": "nvidia/parakeet-tdt-0.6b-v3",
           "whisper_model": "large-v3"}
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["fa"])
    lm.restore_previous(cfg)
    assert cfg["transcribe_backend"] == "nvidia_asr"
    assert cfg["nvidia_asr_model_id"] == "nvidia/parakeet-tdt-0.6b-v3"


def test_apply_and_restore_round_trip_for_a_whisper_row():
    cfg = _whisper_cfg("large-v3-turbo")
    before = copy.deepcopy(cfg)
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["ja"])
    assert cfg["whisper_model"] == "kotoba-whisper-v2.0"
    assert cfg["model"]["hf_repo"] == "kotoba-tech/kotoba-whisper-v2.0-faster"
    assert lm.active(cfg) is lm.LANGUAGE_MODELS["ja"]
    lm.restore_previous(cfg)
    assert cfg == before


def test_apply_and_restore_round_trip_for_the_transformers_row():
    cfg = {**_whisper_cfg(), "nvidia_asr_model_id": "nvidia/parakeet-tdt-0.6b-v3"}
    before = copy.deepcopy(cfg)
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["fa"])
    assert cfg["transcribe_backend"] == "nvidia_asr"
    assert cfg["nvidia_asr_model_id"] == "mehdi-hf/nemotron-asr-streaming-farsi"
    lm.restore_previous(cfg)
    assert cfg == before


def test_switching_between_rows_keeps_the_first_general_setup():
    cfg = _whisper_cfg("medium")
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["fa"])
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["zh"])
    assert lm.active(cfg) is lm.LANGUAGE_MODELS["zh"]
    lm.restore_previous(cfg)
    assert cfg["transcribe_backend"] == "faster_whisper" and cfg["whisper_model"] == "medium"
    assert "nvidia_asr_model_id" not in cfg  # never left pointing at the Persian model


def test_restore_without_memory_goes_to_whisper_default():
    cfg = {"transcribe_backend": "nvidia_asr", "nvidia_asr_model_id": "mehdi-hf/nemotron-asr-streaming-farsi"}
    lm.restore_previous(cfg)
    assert cfg["transcribe_backend"] == "faster_whisper"
    assert cfg["whisper_model"] == mm.DEFAULT_MODEL_SLUG
    assert lm.active(cfg) is None


def test_restore_never_returns_to_a_language_model():
    # memory written by hand (or by an older build) that names a language model
    cfg = {"transcribe_backend": "faster_whisper", "whisper_model": "large-v3",
           lm.PREVIOUS_KEY: {"transcribe_backend": "faster_whisper", "whisper_model": "belle-large-v3-turbo-zh"}}
    lm.restore_previous(cfg)
    assert cfg["whisper_model"] == mm.DEFAULT_MODEL_SLUG and lm.active(cfg) is None


@pytest.mark.parametrize("first,second", [("fa", "zh"), ("zh", "fa"), ("ja", "de")])
def test_switching_rows_leaves_no_key_of_the_first_row(first, second):
    cfg = {**_whisper_cfg("medium"), "nvidia_asr_model_id": "nvidia/parakeet-tdt-0.6b-v3"}
    before = copy.deepcopy(cfg)
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS[first])
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS[second])
    assert lm.active(cfg) is lm.LANGUAGE_MODELS[second]
    if lm.LANGUAGE_MODELS[second].engine == lm.ENGINE_WHISPER:
        assert cfg["nvidia_asr_model_id"] == "nvidia/parakeet-tdt-0.6b-v3"  # not the Persian model
    else:
        assert cfg["whisper_model"] == "medium"  # not the Chinese/Japanese one
    lm.restore_previous(cfg)
    assert cfg == before


def test_restore_keeps_a_model_folder_without_a_model_entry():
    cfg = {"transcribe_backend": "faster_whisper", "whisper_model": "large-v3", "model": None,
           "model_path": "D:/models/my-finetune"}
    lm.apply_language_model(cfg, lm.LANGUAGE_MODELS["th"])
    lm.restore_previous(cfg)
    assert cfg["model_path"] == "D:/models/my-finetune" and cfg["whisper_model"] == "large-v3"
