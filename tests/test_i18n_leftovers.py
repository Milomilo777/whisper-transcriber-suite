"""Small texts left over by the translation waves, converted with the language picker (no Tk root).

* the browser-cookie picker's "(off)" entry and the log-in hint (app/domain/cookies.py),
* the taskbar badge's description, "3 jobs" (app/theme/win_taskbar.py),
* the voice engine's two give-up messages (app/services/voice_clone_service.py),
* the tray menu's Exit / Quit (app/shortcuts.py).

``test_*_english_*`` pin the exact English each produced before the conversion (they passed on
the unconverted files); ``test_*_pseudo_*`` build the same texts in the qps-ploc pseudo-locale
and expect them marked, while stored values (the cookies setting) stay English.
"""
from __future__ import annotations

import time

import pytest

from app import i18n
from tests.app.i18n_walk import is_pseudo_marked


@pytest.fixture(autouse=True)
def _english_after():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo():
    i18n.set_language(i18n.PSEUDO_LOCALE)
    yield
    i18n.set_language("en")


# --- browser cookies -------------------------------------------------------------------------

HINT_OFF = ("This site wants you to be logged in: pick the browser you are logged in with under "
            "\"Log-in cookies\" and the link is checked again.")
HINT_ON = ("The site still asks for a login: check that you are logged in to it in firefox (on "
           "Windows, close firefox completely if it keeps failing).")
LOGIN_WALL = "ERROR: [Instagram] abc: login required. Use --cookies-from-browser"


def test_cookies_english_is_unchanged() -> None:
    from app.domain import cookies as ck

    assert ck.cookie_browser_choices("", platform="win32") == [
        "(off)", "chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"]
    assert ck.cookie_browser_choices("firefox:work", platform="darwin")[:2] == ["(off)", "safari"]
    assert ck.cookie_browser_choices("firefox:work", platform="win32")[-1] == "firefox:work"
    assert ck.cookie_browser_choices("(off)", platform="win32") == ck.cookie_browser_choices(
        "", platform="win32")
    assert ck.cookie_browser_label("") == "(off)"
    assert ck.cookie_browser_label(" chrome ") == "chrome"
    assert ck.cookie_browser_value("(off)") == ""
    assert ck.login_required_hint(LOGIN_WALL, "") == HINT_OFF
    assert ck.login_required_hint(LOGIN_WALL, "firefox") == HINT_ON


def test_cookies_pseudo_marks_the_texts_and_keeps_the_stored_value(pseudo: None) -> None:
    from app.domain import cookies as ck

    choices = ck.cookie_browser_choices("", platform="win32")
    off = choices[0]
    assert off != "(off)" and is_pseudo_marked(off)
    assert choices[1:] == ["chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"]
    assert ck.cookie_browser_label("") == off
    assert ck.cookie_browser_label(None) == off
    # The stored value never depends on the language: both labels mean "off".
    assert ck.cookie_browser_value(off) == ""
    assert ck.cookie_browser_value("(off)") == ""
    assert ck.cookie_browser_value("edge") == "edge"
    # A hand-edited setting is appended as before; the English label never is.
    assert ck.cookie_browser_choices("firefox:work", platform="win32")[-1] == "firefox:work"
    assert ck.cookie_browser_choices("(off)", platform="win32") == choices
    assert ck.cookie_browser_choices("edge", platform="win32") == choices
    assert is_pseudo_marked(ck.login_required_hint(LOGIN_WALL, ""))
    on = ck.login_required_hint(LOGIN_WALL, "firefox")
    assert is_pseudo_marked(on) and on.count("firefox") == 2


# --- taskbar badge ---------------------------------------------------------------------------

class _Native:
    def __init__(self) -> None:
        self.overlays: list[tuple[str | None, str]] = []

    def set_progress_state(self, _hwnd: int, _state: int) -> int:
        return 0

    def set_progress_value(self, _hwnd: int, _done: int, _total: int) -> int:
        return 0

    def set_overlay(self, _hwnd: int, label: str | None, text: str) -> int:
        self.overlays.append((label, text))
        return 0


def _overlay_texts(*counts: int) -> list[str]:
    from app.theme import win_taskbar as wt

    out: list[str] = []
    for count in counts:
        native = _Native()
        controller = wt._Controller(None, native, 1, None)
        assert controller.apply(wt.Snapshot(wt.TBPF_NORMAL, 50, count))
        out.append(native.overlays[-1][1])
    return out


def test_taskbar_badge_english_is_unchanged() -> None:
    assert _overlay_texts(1, 2, 12) == ["1 job", "2 jobs", "12 jobs"]


def test_taskbar_badge_pseudo_is_marked(pseudo: None) -> None:
    texts = _overlay_texts(1, 3)
    assert all(is_pseudo_marked(t) for t in texts), texts
    assert "3" in texts[1]


# --- voice engine give-up messages -----------------------------------------------------------

class _FakeProc:
    def __init__(self) -> None:
        import io
        self.stdin = io.StringIO()
        self.stdout = None

    def poll(self) -> None:
        return None


def _give_up(monkeypatch: pytest.MonkeyPatch, *, silent: bool, silence_s: float) -> tuple[str, list[str]]:
    from app.services import voice_clone_service as vcs

    w = vcs.VoiceCloneWorker("gui.py")
    w._process = _FakeProc()  # type: ignore[assignment]
    monkeypatch.setattr(w, "SILENCE_TIMEOUT_S", silence_s)
    monkeypatch.setattr(w, "WAIT_POLL_S", 0.01)
    monkeypatch.setattr(vcs.VoiceCloneWorker, "_kill_process_tree", staticmethod(lambda _p: None))
    logged: list[str] = []
    monkeypatch.setattr(vcs.logger, "info", lambda msg, *a: logged.append(msg % a))
    # A clock that runs a minute per reading, so a 3-minute silence takes no real time.
    clock = [time.monotonic()]

    def fast() -> float:
        clock[0] += 60.0
        return clock[0]

    if silent:
        monkeypatch.setattr(vcs, "GENERATE_TIMEOUT_S", 10.0 ** 9)
        w._last_seen = 0.0
    else:
        monkeypatch.setattr(vcs, "GENERATE_TIMEOUT_S", 0.05)
        w._last_seen = clock[0] + 10.0 ** 12  # never silent
    with monkeypatch.context() as m:
        m.setattr(vcs.time, "monotonic", fast)
        with pytest.raises(vcs.VoiceCloneWorkerError) as info:
            w.generate("hi", [], "out.wav", consent_accepted=True, timeout_s=0.05)
    return str(info.value), logged


SILENT_1 = ("The voice engine stopped responding (no sign of life for 1 minute) and was stopped. "
            "Click Generate to try again; if it happens again, restart the app.")
SILENT_3 = ("The voice engine stopped responding (no sign of life for 3 minutes) and was stopped. "
            "Click Generate to try again; if it happens again, restart the app.")
NO_ANSWER = "The voice-clone worker did not answer in time."


def test_voice_engine_english_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _give_up(monkeypatch, silent=True, silence_s=0.05)[0] == SILENT_1
    assert _give_up(monkeypatch, silent=True, silence_s=180)[0] == SILENT_3
    assert _give_up(monkeypatch, silent=False, silence_s=9999)[0] == NO_ANSWER


def test_voice_engine_pseudo_is_marked_and_the_log_stays_english(
        monkeypatch: pytest.MonkeyPatch, pseudo: None) -> None:
    for silent, silence_s in ((True, 180), (True, 0.05), (False, 9999)):
        shown, logged = _give_up(monkeypatch, silent=silent, silence_s=silence_s)
        assert is_pseudo_marked(shown), shown
        assert logged and all(line.isascii() for line in logged), logged
    shown, _logged = _give_up(monkeypatch, silent=True, silence_s=180)
    assert "3" in shown


# --- tray menu Exit / Quit -------------------------------------------------------------------

def test_quit_label_english_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import shortcuts

    monkeypatch.setattr(shortcuts, "is_mac", lambda: False)
    assert shortcuts.quit_label() == "Exit"
    monkeypatch.setattr(shortcuts, "is_mac", lambda: True)
    assert shortcuts.quit_label() == "Quit"


def test_quit_label_pseudo_is_marked(monkeypatch: pytest.MonkeyPatch, pseudo: None) -> None:
    from app import shortcuts

    for mac in (False, True):
        monkeypatch.setattr(shortcuts, "is_mac", lambda mac=mac: mac)
        assert is_pseudo_marked(shortcuts.quit_label())


def test_tray_exit_is_the_same_message_as_the_file_menu_exit(
        monkeypatch: pytest.MonkeyPatch, pseudo: None) -> None:
    from app import shortcuts

    monkeypatch.setattr(shortcuts, "is_mac", lambda: False)
    assert shortcuts.quit_label() == i18n._("Exit")  # app.py File menu: _("Exit")
