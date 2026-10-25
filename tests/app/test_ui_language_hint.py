"""The first-run interface-language suggestion: every branch of the rule, the Win32 readers."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import i18n, ui_language_hint as hint

AVAILABLE = {"en": "reviewed", "de": "reviewed", "fa": "machine", "pt-BR": "machine",
             "zh-Hans": "machine", "fr": "machine"}
DE, FA, EN, FR, PT_BR = 0x0407, 0x0429, 0x0409, 0x040C, 0x0416


@pytest.fixture(autouse=True)
def _rtl_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "rtl_layout_ready", lambda: True)


def decide(config: dict[str, Any] | None = None, running: str = "en", fmt: str | None = "de-DE",
           keys: list[int] | None = None, available: Any = AVAILABLE) -> str | None:
    return hint.suggestion(config or {}, running_language=running, format_locale=fmt,
                           keyboard_langids=[EN, DE] if keys is None else keys, available=available)


def test_all_hints_agree_so_it_suggests() -> None:
    assert decide() == "de"
    assert decide(fmt="fa-IR", keys=[EN, FA]) == "fa"
    assert decide(fmt="pt-BR", keys=[PT_BR]) == "pt-BR"
    assert decide(fmt="zh-CN", keys=[0x0804]) == "zh-Hans"


@pytest.mark.parametrize("config", [
    {hint.HINT_KEY: True},                       # answered before
    {"ui_language": "en"},                       # explicit choice
    {"ui_language": "de"},
    {"ui_language": "qps-ploc"},
])
def test_an_answered_question_or_an_explicit_choice_gives_no_suggestion(config: dict[str, Any]) -> None:
    assert decide(config) is None


@pytest.mark.parametrize("config", [{}, {"ui_language": "auto"}, {"ui_language": ""}, {"ui_language": None}])
def test_unset_or_automatic_counts_as_no_explicit_choice(config: dict[str, Any]) -> None:
    assert decide(config) == "de"


def test_a_display_language_that_is_not_english_gives_no_suggestion() -> None:
    assert decide(running="fr") is None


@pytest.mark.parametrize(("fmt", "keys"), [
    ("en-US", [EN, DE]),        # format English: nothing to offer
    ("en-AU", [DE]),
    (None, [DE]),               # no format locale
    ("", [DE]),
    ("de-DE", []),              # no keyboard information
    ("de-DE", [EN]),            # keyboard missing
    ("de-DE", [FR]),            # keyboard conflicts
    ("fa-IR", [DE]),            # format and keyboard disagree
    ("ja-JP", [0x0411]),        # unsupported here: no catalog
    ("xx-YY", [DE]),            # nonsense
])
def test_missing_or_conflicting_hints_give_no_suggestion(fmt: str | None, keys: list[int]) -> None:
    assert decide(fmt=fmt, keys=keys) is None


def test_a_keyboard_of_another_sublanguage_still_counts() -> None:
    assert decide(keys=[0x0C07]) == "de"  # German (Austria)


def test_a_language_without_a_usable_catalog_is_never_suggested() -> None:
    assert decide(available={"en": "reviewed"}) is None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_only_windows_asks(platform: str) -> None:
    called: list[str] = []
    out = hint.suggestion_for_this_machine(
        {}, platform=platform, environ={}, read_locale=lambda: called.append("l") or "de-DE",
        read_keyboards=lambda: called.append("k") or [DE])
    assert out is None and called == []


def test_the_environment_override_means_no_suggestion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    assert hint.suggestion_for_this_machine(
        {}, platform="win32", environ={i18n.ENV_LANGUAGE: "qps-ploc"},
        read_locale=lambda: "de-DE", read_keyboards=lambda: [DE]) is None


def test_this_machine_path_uses_the_readers_and_survives_their_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    monkeypatch.setattr(i18n, "catalog_statuses", lambda: AVAILABLE)
    assert hint.suggestion_for_this_machine(
        {}, platform="win32", environ={}, read_locale=lambda: "de-DE", read_keyboards=lambda: [DE]) == "de"

    def boom() -> Any:
        raise OSError("blocked")

    assert hint.suggestion_for_this_machine(
        {}, platform="win32", environ={}, read_locale=boom, read_keyboards=lambda: [DE]) is None


# --- the Win32 readers with a fake windll ----------------------------------------------------

def _fake_windll(locale_name: str = "fa-IR", layouts: tuple[int, ...] = (0x04290429, 0x04090409)) -> Any:
    def get_locale(buf: Any, size: int) -> int:
        buf.value = locale_name
        return len(locale_name) + 1 if locale_name else 0

    def get_layouts(count: int, arr: Any) -> int:
        if count == 0:
            return len(layouts)
        for i, h in enumerate(layouts):
            arr[i] = h
        return len(layouts)

    return SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultLocaleName=get_locale),
                           user32=SimpleNamespace(GetKeyboardLayoutList=get_layouts))


def test_readers_return_what_windows_reports() -> None:
    assert hint.read_format_locale(_fake_windll()) == "fa-IR"
    assert hint.read_keyboard_langids(_fake_windll()) == [0x0429, 0x0409]


def test_readers_treat_every_failure_as_no_hint() -> None:
    assert hint.read_format_locale(_fake_windll(locale_name="")) is None
    assert hint.read_keyboard_langids(_fake_windll(layouts=())) == []
    assert hint.read_format_locale(SimpleNamespace()) is None  # no kernel32 at all
    assert hint.read_keyboard_langids(SimpleNamespace()) == []


# --- properties ------------------------------------------------------------------------------

def test_never_suggests_english_or_an_unsupported_code() -> None:
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")

    tags = st.sampled_from(["en-US", "de-DE", "fa-IR", "ja-JP", "xx", "pt-PT", "zh-TW", "", "C", "fr-CA"])
    ids = st.lists(st.sampled_from([EN, DE, FA, FR, PT_BR, 0x0411, 0x0804, 0x0000, 0xFFFF]), max_size=6)
    codes = st.lists(st.sampled_from(sorted(i18n.LANGUAGES_BY_CODE)), max_size=8, unique=True)

    @hypothesis.given(tags, ids, codes, st.sampled_from(["en", "de", "fa"]))
    @hypothesis.settings(max_examples=300, deadline=None)
    def check(tag: str, keys: list[int], offered: list[str], running: str) -> None:
        available = {c: "reviewed" for c in offered} | {"en": "reviewed"}
        out = decide(fmt=tag, keys=keys, running=running, available=available)
        if out is not None:
            assert out != "en" and out in i18n.LANGUAGES_BY_CODE and out in available
            assert running == "en" and hint.keyboard_matches(out, keys)

    check()
