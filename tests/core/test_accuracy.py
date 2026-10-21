"""The Transcribe tab's Accuracy levels (core.accuracy): Fast / Balanced / Best per language and memory.

Pure functions, no Tk. The table pins the rows a person would check by hand; the property
tests cover every language and memory size the helpers accept.
"""
from __future__ import annotations

import pytest

from core import accuracy as acc
from core import hardware as hw
from core import language_defaults as ld
from core.model_manager import MODEL_REGISTRY

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - the property tests skip themselves
    given = settings = st = None  # type: ignore[assignment]

LADDER = ("small", "medium", "large-v3-turbo", "large-v3")  # smallest first
LANGUAGES = ["auto", "", "en", "de", *ld.MODEL_BY_LANGUAGE]
RAM_SIZES = [0.0, 4.0, 6.0, 16.0]


def _size_rank(slug: str) -> int:
    return LADDER.index(slug)


# ------------------------------------------------------------------ the table

@pytest.mark.parametrize("language,ram_gb,expected", [
    # unmeasured languages and Auto: Best is Large v3, Balanced is Turbo
    ("auto", 0.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3"}),
    ("en", 16.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3"}),
    ("fa", 16.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3"}),
    # 6 GB: Large v3 does not fit (6.5 GB), so Best is Turbo too
    ("auto", 6.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
    ("fa", 6.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
    # 4 GB: nothing above Small fits
    ("auto", 4.0, {"fast": "small", "balanced": "small", "best": "small"}),
    ("ar", 4.0, {"fast": "small", "balanced": "small", "best": "small"}),
    # languages whose measured Best is already Turbo: Balanced is the same model (Medium
    # would be slower and less accurate than Turbo)
    ("ar", 0.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
    ("zh", 16.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
    ("ru", 6.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
    ("es", 16.0, {"fast": "small", "balanced": "large-v3-turbo", "best": "large-v3-turbo"}),
])
def test_table(language: str, ram_gb: float, expected: dict[str, str]) -> None:
    assert acc.models_by_level(language, ram_gb) == expected
    for level, slug in expected.items():
        assert acc.model_for_level(language, level, ram_gb) == slug


def test_levels_are_fast_balanced_best_in_that_order() -> None:
    assert acc.LEVELS == ("fast", "balanced", "best")


def test_unknown_level_is_an_error() -> None:
    with pytest.raises(ValueError):
        acc.model_for_level("auto", "turbo")


@pytest.mark.parametrize("slug,language,ram_gb,expected", [
    ("large-v3-turbo", "auto", 0.0, "balanced"),
    ("large-v3", "auto", 0.0, "best"),
    ("small", "auto", 0.0, "fast"),
    ("large-v3-turbo", "ar", 16.0, "balanced"),  # Balanced and Best share it: the first
    ("medium", "ar", 16.0, None),  # Medium is no level anywhere
    ("medium", "auto", 16.0, None),
    ("large-v3", "ar", 16.0, None),  # bigger than the measured Best
    ("small.en", "en", 0.0, None),  # English-only twins are a Custom pick
    ("ivrit-large-v3-turbo-he", "he", 0.0, None),
    ("", "auto", 0.0, None),
    ("no-such-model", "auto", 0.0, None),
])
def test_level_for_model(slug: str, language: str, ram_gb: float, expected: str | None) -> None:
    assert acc.level_for_model(slug, language, ram_gb) == expected


def test_a_level_that_collides_reads_as_the_first_one() -> None:
    # 4 GB: every level is Small; the shown level is Fast, the cheapest of the three.
    assert acc.level_for_model("small", "auto", 4.0) == "fast"


def test_unknown_memory_means_no_cap() -> None:
    assert acc.models_by_level("auto", 0.0) == acc.models_by_level("auto", 64.0)


# ------------------------------------------------------------- properties

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ram_gb", RAM_SIZES)
def test_every_pick_is_a_catalog_model_that_fits_the_memory(language: str, ram_gb: float) -> None:
    picks = acc.models_by_level(language, ram_gb)
    assert set(picks) == set(acc.LEVELS)
    for slug in picks.values():
        assert slug in MODEL_REGISTRY
        assert slug in LADDER
        assert hw.fit_model_to_ram(slug, ram_gb) == slug


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ram_gb", RAM_SIZES)
def test_levels_grow_with_accuracy_and_differ_when_the_memory_allows(language: str, ram_gb: float) -> None:
    picks = acc.models_by_level(language, ram_gb)
    assert _size_rank(picks["fast"]) <= _size_rank(picks["balanced"]) <= _size_rank(picks["best"])
    assert picks["balanced"] == hw.fit_model_to_ram("large-v3-turbo", ram_gb)
    assert "medium" not in picks.values()
    if picks["balanced"] != "small":
        assert picks["balanced"] != picks["fast"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ram_gb", RAM_SIZES)
def test_the_model_of_a_level_reads_back_as_a_level_with_that_model(language: str, ram_gb: float) -> None:
    picks = acc.models_by_level(language, ram_gb)
    for level, slug in picks.items():
        shown = acc.level_for_model(slug, language, ram_gb)
        assert shown is not None
        assert picks[shown] == slug
        if len(set(picks.values())) == 3:
            assert shown == level


def test_balanced_is_turbo_for_every_language() -> None:
    for language in LANGUAGES:
        assert acc.models_by_level(language, 0.0)["balanced"] == "large-v3-turbo"


if st is not None:
    _languages = st.one_of(st.sampled_from(LANGUAGES), st.text(max_size=3))
    _ram = st.one_of(st.just(0.0), st.floats(min_value=0.0, max_value=128.0, allow_nan=False))

    @settings(max_examples=200, deadline=None)
    @given(language=_languages, ram_gb=_ram)
    def test_property_picks_fit_grow_and_read_back(language: str, ram_gb: float) -> None:
        picks = acc.models_by_level(language, ram_gb)
        ranks = [_size_rank(picks[level]) for level in acc.LEVELS]
        assert ranks == sorted(ranks)
        for level, slug in picks.items():
            assert hw.fit_model_to_ram(slug, ram_gb) == slug
            shown = acc.level_for_model(slug, language, ram_gb)
            assert shown is not None and picks[shown] == slug
            assert acc.model_for_level(language, level, ram_gb) == slug
