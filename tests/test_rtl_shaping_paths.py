"""Real app paths on Linux whose shaped text loses its identity (round 5), Hebrew, Persian, Arabic.

A ``rtl_shaping.Shaped`` carries its logical text, but slicing, ``str()``, ``"\\n".join``, an
f-string or a round trip through Tk give a plain ``str``. Text that LEAVES the screen (clipboard,
log file, window title) then goes through ``i18n.plain()``, which also finds whole lines that
``visual()`` made, by text. Placeholders and ``display()`` never do that. The oracle for each path
is the same code run on Windows, whose text is the catalog text with direction marks.
No Tk root; the platform is a patched ``sys.platform``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("arabic_reshaper")
pytest.importorskip("bidi")

from app import i18n, rtl_shaping  # noqa: E402 - after the importorskip lines

LOCALES = Path(__file__).resolve().parents[1] / "app" / "locales"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(i18n.ENV_LANGUAGE, raising=False)
    # The Hebrew shaping code is tested although it is not switched on for Linux (SHAPED_LANGUAGES).
    monkeypatch.setattr(rtl_shaping, "SHAPED_LANGUAGES", frozenset({"fa", "ar", "he"}))
    for memory in (rtl_shaping._VISUAL_TO_LOGICAL, rtl_shaping._BY_FIRST_CHAR, rtl_shaping._CACHE,
                   rtl_shaping._HEBREW_TO_LOGICAL):
        memory.clear()
    i18n.set_language("en")
    yield
    i18n.set_language("en")
    rtl_shaping.uninstall_title_hook()


def run_on(monkeypatch: pytest.MonkeyPatch, platform: str, code: str, fn):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "platform", platform)
    assert i18n.set_language(code) == code
    return fn()


def canonical_and_linux(monkeypatch: pytest.MonkeyPatch, code: str, fn):  # type: ignore[no-untyped-def]
    """(logical text via Windows, plain() of the Linux text)."""
    on_windows = i18n.plain(run_on(monkeypatch, "win32", code, fn))
    on_linux = run_on(monkeypatch, "linux", code, fn)
    assert on_linux != on_windows  # the screen text really is shaped
    return on_windows, on_linux


CODES = ["he", "fa", "ar"]


def _messages(code: str) -> dict[str, str]:
    doc = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in doc["messages"].items()  # one line each, so lines can be compared
            if isinstance(v, str) and v and "{" not in v and "\x04" not in k and "\n" not in v
            and v == v.strip()}


@pytest.mark.parametrize("code", CODES)
def test_caption_languages_line_joined_from_results(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    from app.domain import languages

    langs = {c: "manual" for c in ("en", "de", "fr", "es", "it", "ja", "ko", "pt", "ru", "tr")}
    langs.update({"nl": "auto", "pl": "auto"})

    def build() -> str:
        return languages.caption_availability_text(langs, prefer=("en",))

    logical_text, shown = canonical_and_linux(monkeypatch, code, build)
    assert i18n.plain(shown) == logical_text


@pytest.mark.parametrize("code", CODES)
def test_console_copy_of_text_read_back_from_tk(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    """txt.get() gives a plain str of lines made by _(): plain() must give the catalog lines."""
    messages = _messages(code)
    keys = list(messages)[:200]
    monkeypatch.setattr(sys, "platform", "linux")
    i18n.set_language(code)
    data = "\n".join(str(i18n._(k)) for k in keys)  # what Tk hands back: no identity
    bad = [k for k, line in zip(keys, i18n.plain(data).split("\n")) if line != messages[k]]
    assert bad == []


@pytest.mark.parametrize("code", CODES)
def test_lines_with_leading_spaces_and_str_conversions(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    messages = _messages(code)
    keys = list(messages)[:100]
    monkeypatch.setattr(sys, "platform", "linux")
    i18n.set_language(code)
    text = "\n".join("  " + str(i18n._(k)) + " " for k in keys)  # a log built with str() and join
    expected = "\n".join("  " + messages[k] + " " for k in keys)
    assert i18n.plain(text) == expected
    assert i18n.plain(str(i18n._(keys[0]))) == messages[keys[0]]  # notice.py / transcript_viewer.py


@pytest.mark.parametrize("code", CODES)
def test_offline_log_text_copy(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    from app.widgets import offline_status as ost
    from core import offline

    act = offline.Activity(since=0.0, counts={offline.REFUSED: 2}, events=(
        offline.NetEvent(3_700.0, offline.REFUSED, "Update check", "example.com"),
        offline.NetEvent(3_800.0, offline.SKIPPED, "Update check"),
    ))
    check = offline.ConnectionCheck(100.0, True, (), processes=1)
    probes = [offline.ProbeResult("Host-name lookup", True, "refused as expected"),
              offline.ProbeResult("TCP connect", False, "it connected")]

    def build() -> str:
        return ost.log_text(act, check, probes, 5_000.0)

    logical_text, shown = canonical_and_linux(monkeypatch, code, build)
    assert i18n.plain(shown) == logical_text
    # After a round trip through a Text widget only whole lines are known. The event lines mix a
    # time, a feature name and a shaped word in one f-string: the one remaining class (below).
    back = i18n.plain(str(shown)).split("\n")
    bad = [a for a, b in zip(back, logical_text.split("\n")) if a != b]
    assert len(back) == len(logical_text.split("\n"))
    assert len(bad) <= len(act.events) if code == "he" else bad == []


def test_help_menu_label_with_the_update_dot_is_shaped_as_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import app as app_module

    monkeypatch.setattr(sys, "platform", "linux")
    i18n.set_language("he")
    label = app_module._help_label_with_dot()
    word = i18n.translate(app_module._HELP_MENU_LABEL)
    assert i18n.plain(label) == i18n.plain(word) + " " + chr(0x25CF)
    assert label == rtl_shaping.visual(i18n.plain(word) + " " + chr(0x25CF), logical_input=True)
    assert label.startswith(chr(0x25CF))  # the dot ends a right-to-left label: it sits at the left


def test_join_gives_plain_text_when_nothing_is_shaped(monkeypatch: pytest.MonkeyPatch) -> None:
    for platform in ("win32", "darwin"):
        monkeypatch.setattr(sys, "platform", platform)
        i18n.set_language("he")
        parts = [i18n._("Show"), i18n._("Hide")]
        joined = rtl_shaping.join(", ", parts)
        assert type(joined) is str and joined == ", ".join(parts)
    assert rtl_shaping.join("\n", ["a", "b"]) == "a\nb"


def test_a_window_title_that_lost_its_identity_still_gets_logical_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Wm:
        def __init__(self) -> None:
            self.titles: list[object] = []

        def wm_title(self, string: object = None) -> None:
            self.titles.append(string)

        title = wm_title

    class Dialog:
        def show(self, **options: object) -> None:
            return None

    monkeypatch.setattr(sys, "platform", "linux")
    i18n.set_language("he")
    shown = i18n._("Exit")
    restore = rtl_shaping.install_title_hook(wm=Wm, dialog=Dialog)
    try:
        wm = Wm()
        wm.title(str(shown))  # a plain str, as after a trip through Tk
        wm.title("  " + str(shown))
        assert wm.titles == [shown.logical, "  " + shown.logical]
    finally:
        restore()
