"""English-only models paired with another language (core helpers).

An English-only Whisper model turns Persian speech into made-up English
text with no error; these helpers let the Live and Transcribe tabs notice
the pair before anything runs.
"""
from __future__ import annotations

import pytest

from core import live_model as lm
from core import model_manager as mm

ENGLISH_ONLY = [
    "tiny.en", "base.en", "small.en", "medium.en",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
]
MULTILINGUAL = [
    "tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "deepdml-large-v3-turbo",
]


def test_every_built_in_model_is_classified():
    assert sorted(ENGLISH_ONLY + MULTILINGUAL) == sorted(mm.MODEL_REGISTRY)


@pytest.mark.parametrize("slug", ENGLISH_ONLY)
def test_english_only_models(slug):
    assert mm.is_english_only({}, slug) is True


@pytest.mark.parametrize("slug", MULTILINGUAL)
def test_multilingual_models(slug):
    assert mm.is_english_only({}, slug) is False


def test_every_catalog_entry_that_says_english_only_is_flagged():
    for slug, entry in mm.MODEL_REGISTRY.items():
        assert ("English-only" in entry["info"]) == (mm.is_english_only({}, slug) is True), slug


def test_custom_model_is_unknown():
    assert mm.is_english_only({}, "my-finetune") is None
    assert mm.is_english_only({}, "") is None


def test_online_catalog_entries():
    cfg = {"model_catalog": {
        # No flag: the .en suffix decides.
        "large-v4.en": {"name": "faster-whisper-large-v4.en", "hf_repo": "org/v4-en"},
        "large-v4": {"name": "faster-whisper-large-v4", "hf_repo": "org/v4"},
        # An explicit flag wins over the name.
        "odd.en": {"name": "odd-en", "hf_repo": "org/odd", "english_only": False},
        "small": {"english_only": True, "name": "faster-whisper-small"},
        # A non-bool flag is ignored, the suffix decides.
        "weird": {"name": "weird", "hf_repo": "org/weird", "english_only": "yes"},
    }}
    assert mm.is_english_only(cfg, "large-v4.en") is True
    assert mm.is_english_only(cfg, "large-v4") is False
    assert mm.is_english_only(cfg, "odd.en") is False
    assert mm.is_english_only(cfg, "small") is True
    assert mm.is_english_only(cfg, "weird") is False


@pytest.mark.parametrize("slug,language,expected", [
    ("tiny.en", "en", False),
    ("tiny.en", "EN", False),
    ("tiny.en", "fa", True),
    ("tiny.en", None, True),       # auto-detect cannot rescue an English-only model
    ("tiny.en", "", True),
    ("distil-large-v3", "de", True),
    ("small", "fa", False),
    ("large-v3-turbo", None, False),
    ("my-finetune", "fa", False),  # unknown model: stay silent
])
def test_english_only_mismatch(slug, language, expected):
    assert mm.english_only_mismatch({}, slug, language) is expected


@pytest.mark.parametrize("slug,expected", [
    ("tiny.en", "tiny"),
    ("base.en", "base"),
    ("small.en", "small"),
    ("medium.en", "medium"),
    ("distil-small.en", "small"),
    ("distil-medium.en", "medium"),
    ("distil-large-v2", "large-v3-turbo"),
    ("distil-large-v3", "large-v3-turbo"),
    ("distil-large-v3.5", "large-v3-turbo"),
    ("unknown.en", "small"),  # no multilingual twin in the catalog
])
def test_multilingual_counterpart(slug, expected):
    got = mm.multilingual_counterpart({}, slug)
    assert got == expected
    assert mm.is_english_only({}, got) is False


def test_counterpart_never_returns_an_english_only_model():
    for slug in ENGLISH_ONLY:
        assert mm.is_english_only({}, mm.multilingual_counterpart({}, slug)) is False


@pytest.mark.parametrize("choice,language,device,expected", [
    ("tiny.en", "fa", "cpu", "tiny.en"),
    ("main", "fa", "cpu", "large-v3"),       # main model, default slug
    ("auto", "fa", "cpu", "small"),
    ("auto", "fa", "cuda", "large-v3"),
])
def test_effective_live_slug(choice, language, device, expected):
    assert lm.effective_live_slug({"live_model": choice}, language, device) == expected


def test_effective_live_slug_follows_the_main_model():
    cfg = {"live_model": "main", "whisper_model": "medium.en"}
    assert lm.effective_live_slug(cfg, "fa", "cuda") == "medium.en"


def test_live_alternative_on_a_cpu_is_the_live_recommendation():
    assert lm.live_alternative({}, "fa", "cpu", "tiny.en") == ("small", "small")
    assert lm.live_alternative({}, None, "cpu", "medium.en") == ("small", "small")


def test_live_alternative_on_a_gpu_prefers_a_multilingual_main_model():
    cfg = {"whisper_model": "large-v3"}
    assert lm.live_alternative(cfg, "fa", "cuda", "tiny.en") == ("main", "large-v3")


def test_live_alternative_on_a_gpu_with_an_english_only_main_model():
    cfg = {"whisper_model": "distil-large-v3"}
    assert lm.live_alternative(cfg, "fa", "cuda", "distil-large-v3") == (
        "large-v3-turbo", "large-v3-turbo",
    )
