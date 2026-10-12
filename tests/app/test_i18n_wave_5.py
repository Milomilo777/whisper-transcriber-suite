"""Translation wave 5 (shared widgets): English unchanged, every widget-owned text translated.

``tests/fixtures/i18n/i18n_wave_5_en.json`` was captured from these modules BEFORE their texts
went through the translation layer (app/i18n.py):

* ``"pure"``: texts built without a window (the Work offline status line and Network log text,
  the tray menu and reasons, the open-file / open-folder messages, Subtitle Edit messages);
  captured and checked windowless (``-k pure``).
* ``"tk"``: the windows and bars built on a real Tk root (hardware wizard, Network log window,
  offline status bar, update / downloader / star bars, What's new, Update command, error
  dialog, console menu, notice, help icon). These tests create a Tk root.

Each state is captured in English (must equal the fixture byte for byte) and in the
pseudo-locale qps-ploc (every text the modules own must be pseudo-marked; the exceptions are
listed with their reason). To recapture after a deliberate English change, create the file
``tests/fixtures/i18n/CAPTURE_WAVE_5`` and run this file; the capture tests then rewrite their
section of the fixture.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest

from app import i18n

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_5_en.json"
SENTINEL = FIXTURE.parent / "CAPTURE_WAVE_5"


@pytest.fixture
def english() -> Iterator[None]:
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo() -> Iterator[None]:
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    try:
        yield
    finally:
        i18n.set_language("en")


class Calls:
    """Records messagebox / show_error / notify calls as [name, title-or-kind, text, ...]."""

    def __init__(self, answer: bool = False) -> None:
        self.rows: list[list[str]] = []
        self.answer = answer

    def _rec(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            row = [name] + [str(a) for a in args if isinstance(a, str)]
            for key in ("title", "message", "detail", "action", "question"):
                if isinstance(kwargs.get(key), str):
                    row.append(f"{key}={kwargs[key]}")
            self.rows.append(row)
            return self.answer
        return call

    def messagebox(self) -> SimpleNamespace:
        return SimpleNamespace(**{n: self._rec(n) for n in (
            "showinfo", "showwarning", "showerror", "askyesno", "askokcancel")})

    def show_error(self) -> Callable[..., Any]:
        rec = self._rec("show_error")

        def show_error(_parent: Any, *args: Any, **kwargs: Any) -> None:
            rec(*args, **kwargs)
        return show_error


def _gm_clock(when: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(when))


# --------------------------------------------------------------------------- pure (no window)

def capture_pure(mp: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Texts the wave-5 modules build without a Tk root, keyed by state."""
    from app.widgets import offline_status as ost
    from app.widgets import platform as plat
    from app.widgets import subtitle_edit as ui
    from app.widgets import tray
    from core import offline
    from core import subtitle_edit as core_se

    out: dict[str, Any] = {}

    # Work offline: the status line and the Network log text
    mp.setattr(ost, "_clock", _gm_clock)
    conn_out = offline.OpenConnection(pid=42, process="python.exe", protocol="TCP",
                                      remote="203.0.113.5:443", incoming=False)
    conn_in = offline.OpenConnection(pid=7, process="ffmpeg.exe", protocol="UDP",
                                     remote="198.51.100.9:5000", incoming=True)
    now = 10_000.0
    act = offline.Activity(since=3_600.0, counts={offline.REFUSED: 3, offline.SKIPPED: 1,
                                                  offline.LOCAL: 2, offline.TEST: 4},
                           events=(
                               offline.NetEvent(3_700.0, offline.REFUSED, "Model download",
                                                "huggingface.co"),
                               offline.NetEvent(3_800.0, offline.SKIPPED, "Update check"),
                               offline.NetEvent(3_900.0, offline.LOCAL, "Local server",
                                                "127.0.0.1"),
                               offline.NetEvent(4_000.0, offline.TEST, "Self test",
                                                "example.com"),
                               offline.NetEvent(4_100.0, "other-kind", "Something"),
                           ))
    act_none = offline.Activity(since=0.0, counts={offline.SKIPPED: 2}, events=())
    act_zero = offline.Activity(since=0.0, counts={}, events=())
    warn1 = offline.ConnectionCheck(now - 2, True, (conn_out,), processes=1)
    warn2 = offline.ConnectionCheck(now - 2, True, (conn_out, conn_in), processes=3)
    clean1 = offline.ConnectionCheck(now - 5, True, (), processes=1)
    clean2 = offline.ConnectionCheck(now - 5, True, (), processes=2)
    failed = offline.ConnectionCheck(now - 5, False, error="PermissionError: denied")
    old = offline.ConnectionCheck(now - 100, True, (), processes=1)
    for name, check, a in (("warn1", warn1, act), ("warn2", warn2, act), ("clean", clean1, act),
                           ("clean_zero", clean2, act_zero), ("none", None, act_none),
                           ("failed", failed, act), ("old", old, act)):
        out[f"offline.bar.{name}"] = ost.bar_text(check, a, now)
    probes = [offline.ProbeResult("Host-name lookup", True, "refused as expected"),
              offline.ProbeResult("TCP connect", False, "it connected")]
    out["offline.log.unchecked"] = ost.log_text(act, None)
    out["offline.log.failed"] = ost.log_text(act, failed)
    out["offline.log.clean_one"] = ost.log_text(act, clean1, probes, 5_000.0)
    out["offline.log.warn_many"] = ost.log_text(act_none, warn2, probes, None)

    # Tray: the reasons shown in Advanced settings and the tray menu
    mp.setattr(tray, "_try_load_pystray", lambda: (None, None))
    out["tray.reason.no_pystray"] = tray.availability_reason()
    mp.setattr(tray, "_try_load_pystray", lambda: (object(), None))
    out["tray.reason.no_pillow"] = tray.availability_reason()
    mp.setattr(tray.sys, "platform", "win32")
    out["tray.unavailable.no_pillow"] = tray.unavailable_reason()
    mp.setattr(tray, "availability_reason", lambda: "")
    out["tray.unavailable.missing"] = tray.unavailable_reason()
    mp.setattr(tray.sys, "platform", "darwin")
    out["tray.unavailable.mac"] = tray.unavailable_reason()
    mp.setattr(tray.sys, "platform", "win32")
    labels: list[str] = []

    class _Item:
        def __init__(self, text: Any, _action: Any, **_k: Any) -> None:
            labels.append(text() if callable(text) else str(text))

    class _Menu:
        SEPARATOR = object()

        def __init__(self, *_items: Any) -> None: ...

    class _Icon:
        def __init__(self, _name: str, _image: Any, title: str, _menu: Any) -> None:
            labels.append(f"icon title: {title}")

        def run(self) -> None: ...

        def stop(self) -> None: ...

    controller = tray.TrayController(SimpleNamespace(post_to_main=lambda _fn: None))  # type: ignore[arg-type]
    controller._pystray = SimpleNamespace(Menu=_Menu, MenuItem=_Item, Icon=_Icon)
    controller._pil = object()
    mp.setattr(tray, "_build_icon_image", lambda **_k: None)
    controller.start()
    controller.stop()
    out["tray.menu"] = labels

    # Open a file / a folder
    calls = Calls()
    mp.setattr(plat, "messagebox", calls.messagebox())
    mp.setattr(plat, "show_error", calls.show_error())
    import app.widgets.notice as notice_mod
    mp.setattr(notice_mod, "notify", lambda _w, text, kind="info": calls.rows.append(
        ["notify", kind, text]))

    class _Top:
        pass

    mp.setattr(plat, "tk", SimpleNamespace(Tk=_Top, Toplevel=_Top, TclError=RuntimeError,
                                           Misc=object))
    mp.setattr(plat, "is_darwin", lambda: True)
    out["platform.reveal.mac"] = plat.reveal_label("Open JSON folder")
    out["platform.folder.mac"] = plat.folder_label("Open log folder", "Log Folder")
    out["platform.folder.mac_default"] = plat.folder_label("Open folder")
    mp.setattr(plat, "is_darwin", lambda: False)
    out["platform.reveal.other"] = plat.reveal_label("Open JSON folder")
    for name, path, shown in (("ext_shown", "/x/a.mkv", True), ("ext_hidden", "/x/a.mkv", False),
                              ("bare_shown", "/x/README", True), ("bare_hidden", "/x/README", False)):
        mp.setattr(plat, "open_folder", lambda *_a, _s=shown, **_k: _s)
        plat._reveal_with_notice(path, parent=object())  # type: ignore[arg-type]
        plat._reveal_with_notice(path, parent=None)
    mp.setattr(plat, "open_async", lambda _p, _parent, done, **_k: done(OSError("disk on fire")))
    plat.open_file("/x/a.srt")
    plat.open_file("/x/a.srt", parent=_Top())  # type: ignore[arg-type]
    plat.open_file("/x/a.srt", error_text="Could not play it.")
    out["platform.calls.open"] = calls.rows
    calls.rows = []
    out["platform.calls.folder"] = _folder_calls(mp, plat, _ORIGINAL_OPEN_FOLDER, calls, tmp_path,
                                                 _Top)

    # Subtitle Edit
    se_calls = Calls(answer=False)
    mp.setattr(ui, "messagebox", se_calls.messagebox())
    mp.setattr(ui, "show_error", se_calls.show_error())
    parent_top = SimpleNamespace(winfo_toplevel=lambda: _Top())
    parent_plain = SimpleNamespace(winfo_toplevel=lambda: object())
    mp.setattr(ui, "tk", SimpleNamespace(Tk=_Top, Toplevel=_Top, Misc=object))
    mp.setattr(core_se, "find_subtitle_edit", lambda _configured: None)
    ui.open_in_subtitle_edit(parent_plain, {core_se.CONFIG_KEY: "D:/SE/SubtitleEdit.exe"}, "a.srt")  # type: ignore[arg-type]
    ui.open_in_subtitle_edit(parent_plain, {}, "a.srt")  # type: ignore[arg-type]
    mp.setattr(core_se, "find_subtitle_edit", lambda _configured: "C:/SE/SubtitleEdit.exe")
    ui.open_in_subtitle_edit(parent_plain, {}, None)  # type: ignore[arg-type]

    def _missing(_exe: str, _path: str) -> None:
        raise FileNotFoundError("gone")

    def _broken(_exe: str, _path: str) -> None:
        raise OSError("access denied")

    mp.setattr(core_se, "open_in_subtitle_edit", _missing)
    ui.open_in_subtitle_edit(parent_plain, {}, "D:/subs/a.srt")  # type: ignore[arg-type]
    mp.setattr(core_se, "open_in_subtitle_edit", _broken)
    ui.open_in_subtitle_edit(parent_top, {}, "D:/subs/a.srt")  # type: ignore[arg-type]
    ui.open_in_subtitle_edit(parent_plain, {}, "D:/subs/a.srt")  # type: ignore[arg-type]
    out["subtitle_edit.calls"] = se_calls.rows
    out["subtitle_edit.button"] = i18n.translate(ui.BUTTON_TEXT)
    out["subtitle_edit.help"] = i18n.translate(ui.HELP_TEXT)
    return out


from app.widgets import platform as _platform_for_original  # noqa: E402

_ORIGINAL_OPEN_FOLDER = _platform_for_original.open_folder


def _folder_calls(mp: pytest.MonkeyPatch, plat: Any, open_folder: Callable[..., bool],
                  calls: Calls, tmp_path: Path, top_cls: type) -> list[list[str]]:
    """open_folder: a missing folder (empty and named), and a folder that fails to open."""
    open_folder("", None)
    open_folder("Z:/no/such/folder", object())

    def _boom(_path: str) -> None:
        raise OSError("explorer crashed")

    mp.setattr(plat.os, "startfile", _boom, raising=False)
    mp.setattr(plat.subprocess, "run", lambda *_a, **_k: _boom(""))
    open_folder(str(tmp_path), None)
    open_folder(str(tmp_path), top_cls())
    return calls.rows


_SEGMENT = re.compile(r"\[[^\[\]]*? ~+\]")
_CALL_KEYS = ("title", "message", "detail", "action", "question")

# Test inputs that sit inside a widget-owned sentence as placeholder values, and texts that are
# not these modules' own (product names, core messages, the caller's text, exception details).
DATA = (
    "python.exe", "ffmpeg.exe", "203.0.113.5:443", "198.51.100.9:5000", "PermissionError: denied",
    "Model download", "huggingface.co", "Update check", "Local server", "127.0.0.1",
    "Self test", "example.com", "other-kind", "Something", "Host-name lookup",
    "refused as expected", "TCP connect", "it connected", "cannot run the self-test",
    "D:/SE/SubtitleEdit.exe", "D:/subs/a.srt", "Z:/no/such/folder", "X:/extras",
    "disk on fire", "explorer crashed", "access denied", "Could not play it.",
    "icon title: Whisper Transcriber Suite",  # the product name
    "NVIDIA CUDA (float16) — RTX 9999", "Snapdragon X NPU (QNN)", "CPU int8",  # core tier labels
    "NVIDIA CUDA — NVIDIA GPU",  # product names on the "needs setup" row
    "The driver is too old. Update it.",  # core.hardware's CudaStatus.summary()
    "pip broke", "read-only disk", "no psutil",
    "Exit",  # shortcuts.quit_label() (app/shortcuts.py, not this wave)
    "Caller title", "Caller message.", "Traceback", "Caller notice", "Caller help",
    "offer", "progress", "result",  # the bar texts come from app.py
    "Faster start", "One thing", "Another",  # release-note headline and highlights
)


def unmarked(text: str) -> bool:
    """True when ``text`` has a letter outside every (possibly nested) pseudo-locale segment,
    after the known test data is removed."""
    rest = text
    for d in sorted(DATA, key=len, reverse=True):
        rest = rest.replace(d, "")
    while True:
        new = _SEGMENT.sub("", rest)
        if new == rest:
            break
        rest = new
    return any(c.isalpha() for c in rest)


def _unmarked_in(states: dict[str, Any], skip: tuple[str, ...] = ()) -> list[str]:
    bad: list[str] = []

    def check(text: str) -> None:
        for line in text.split("\n"):
            if unmarked(line):
                bad.append(line)

    for key, value in states.items():
        if key in skip:
            continue
        items = [value] if isinstance(value, str) else value
        for item in items:
            if isinstance(item, str):
                check(item)
                continue
            # a call row: [call name, args..., key=value ...]; the call name is not text
            for part in item[1:]:
                if part in ("info", "success", "warning"):
                    continue  # a notice kind
                head, sep, tail = part.partition("=")
                check(tail if sep and head in _CALL_KEYS else part)
    return bad


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.is_file() else {}


def _write_section(section: str, states: dict[str, Any]) -> None:
    doc = _load_fixture()
    doc[section] = states
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
                        .encode("utf-8"))


def test_capture_pure_fixture(english: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not SENTINEL.exists():
        pytest.skip("capture runs only when tests/fixtures/i18n/CAPTURE_WAVE_5 exists")
    _write_section("pure", capture_pure(monkeypatch, tmp_path))


def test_pure_english_texts_match_the_capture_made_before_translation(
        english: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    expected = _load_fixture()["pure"]
    got = json.loads(json.dumps(capture_pure(monkeypatch, tmp_path)))
    assert got == expected


def test_pure_pseudo_locale_leaves_no_text_untranslated(
        pseudo: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_pure(monkeypatch, tmp_path)
    assert _unmarked_in(states, skip=("platform.reveal.other",)) == []


def test_pure_placeholder_values_survive_the_pseudo_locale(
        pseudo: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The data a sentence carries (counts, hosts, paths, versions) is still in it."""
    states = capture_pure(monkeypatch, tmp_path)
    assert "203.0.113.5:443" in states["offline.bar.warn1"]
    assert "pid 42" in states["offline.bar.warn1"] or "42" in states["offline.bar.warn1"]
    assert "huggingface.co" in states["offline.log.unchecked"]
    assert "Something" in states["offline.log.unchecked"]  # an unknown kind is shown as is
    assert any("D:/subs/a.srt" in part for row in states["subtitle_edit.calls"] for part in row)
    assert any(".mkv" in part for row in states["platform.calls.open"] for part in row)


def test_constants_are_marked_for_the_catalog() -> None:
    """Module constants shown elsewhere are N_()-marked, so translate() finds them in en.json."""
    from app.widgets import offline_status as ost
    from app.widgets import subtitle_edit as ui
    from app.widgets import update_bar as ub
    messages = json.loads((Path(__file__).resolve().parents[2] / "app" / "locales" / "en.json")
                          .read_text(encoding="utf-8"))["messages"]
    wanted = [ui.BUTTON_TEXT, ui.HELP_TEXT, *ost.LIMITS, *ost._KIND_WORDS.values(),
              *(text for _key, text in ub.UpdateBar.BUTTONS),
              *(text for _key, text in ub.StarBar.BUTTONS)]
    assert [w for w in wanted if w not in messages] == []


def test_stored_keys_stay_english_in_the_pseudo_locale(pseudo: None) -> None:
    """Button keys and the offline bar state are identifiers, not shown text."""
    from app.widgets import offline_status as ost
    from app.widgets import update_bar as ub
    from core import offline
    assert [k for k, _t in ub.UpdateBar.BUTTONS] == ["whats_new", "download", "later", "skip"]
    assert [k for k, _t in ub.StarBar.BUTTONS] == ["open", "not_now", "never"]
    check = offline.ConnectionCheck(100.0, True, (), processes=1)
    assert ost.bar_state(check, 110.0) == "clean"


# --------------------------------------------------------------------------- tk (real root)

def _texts(widget: Any) -> list[str]:
    from tests.app.i18n_walk import visible_texts
    return [text for _path, text in visible_texts(widget)]


def _tree_texts(tree: Any) -> list[str]:
    out = [str(tree.heading(c, "text")) for c in tree["columns"]]
    for iid in tree.get_children():
        out.extend(str(v) for v in tree.item(iid, "values"))
    return [t for t in out if t.strip()]


def _find_button(root: Any, text: str) -> Any:
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            if w.winfo_class() in ("TButton", "Button") and str(w.cget("text")) == text:
                return w
        except Exception:  # noqa: BLE001
            pass
        stack.extend(w.winfo_children())
    raise AssertionError(f"no button {text!r}")


def capture_tk(mp: pytest.MonkeyPatch) -> dict[str, Any]:
    tk = pytest.importorskip("tkinter")
    from tkinter import ttk

    from app.widgets import console as console_mod
    from app.widgets import error_dialog
    from app.widgets import hardware_wizard as hwz
    from app.widgets import offline_status as ost
    from app.widgets import update_bar as ub
    from app.widgets.notice import host_for
    from app.widgets.tooltip import help_icon
    from core import hardware as hw
    from core import offline

    out: dict[str, Any] = {}
    root = tk.Tk()
    root.withdraw()
    try:
        # ---- hardware wizard
        calls = Calls(answer=False)
        mp.setattr(hwz, "messagebox", calls.messagebox())
        mp.setattr(hwz, "show_error", calls.show_error())
        mp.setattr(hwz, "place_over", lambda *_a, **_k: None)
        mp.setattr(hwz.HardwareWizard, "_reprobe", lambda self: None)
        mp.setattr(hwz.offline, "is_offline", lambda: False)
        from core import optional_deps
        mp.setattr(optional_deps, "extras_dir", lambda: "X:/extras")
        mp.setattr(optional_deps, "is_available", lambda _name: False)
        tiers = [
            hw.Tier("cuda_float16", "NVIDIA CUDA (float16) — RTX 9999", "cuda", "float16"),
            hw.Tier("qnn_npu", "Snapdragon X NPU (QNN)", "cpu", "int8", backend="qnn_npu"),
            hw.Tier("cpu_int8", "CPU int8", "cpu", "int8"),
        ]
        status = hw.CudaStatus(usable=False, gpu_present=True, reason="The driver is too old.",
                               fix="Update it.", gpu_name="", can_install_runtime=True)
        wiz = hwz.HardwareWizard(root)
        wiz.withdraw()
        out["hw.initial"] = _texts(wiz) + _tree_texts(wiz.tree)
        wiz._reprobe_done(wiz._probe_seq, tiers, status)
        out["hw.probed"] = _texts(wiz) + _tree_texts(wiz.tree)
        wiz.tree.focus("1")
        wiz._on_select(None)
        out["hw.select_unsupported"] = _texts(wiz)
        wiz._save_and_close()
        wiz.tree.focus("0")
        wiz._on_select(None)
        out["hw.select_supported"] = _texts(wiz)
        wiz._selected_idx = -1
        wiz._save_and_close()
        wiz._run_in_background = lambda fn, done: done(fn(), None)  # type: ignore[method-assign]
        mp.setattr(hw, "diagnostics_report", lambda: "REPORT")
        wiz._copy_diagnostics()
        out["hw.diagnostics"] = _texts(wiz)
        wiz._install_gpu_support()  # asked, answered no
        calls.answer = True

        def _install_fails(_fn: Any, done: Any) -> None:
            done(False, RuntimeError("pip broke"))

        wiz._run_in_background = _install_fails  # type: ignore[method-assign]
        wiz._install_gpu_support()
        out["hw.install_failed"] = _texts(wiz)
        wiz._reprobe_done(wiz._probe_seq, [], None)
        out["hw.no_tiers"] = _texts(wiz) + _tree_texts(wiz.tree)

        def _save_fails(_tier: Any) -> None:
            raise OSError("read-only disk")

        mp.setattr(hw, "save_hardware_choice", _save_fails)
        wiz._reprobe_done(wiz._probe_seq, tiers[2:], None)
        wiz._user_picked = True
        wiz._save_and_close()
        confirm_calls = Calls(answer=False)
        fake_app = SimpleNamespace(
            transcription_service=SimpleNamespace(active_workers=lambda: [1], stop_all=lambda: None),
            _confirm_backend_switch=confirm_calls._rec("confirm"),
            log=lambda _line: None,
        )
        wiz.app = fake_app  # type: ignore[assignment]
        wiz._restart_idle_engine()
        out["hw.calls"] = calls.rows + confirm_calls.rows
        wiz._on_close()

        # ---- Network log window and the offline status bar
        mp.setattr(ost, "_clock", _gm_clock)
        act = offline.Activity(since=3_600.0, counts={offline.REFUSED: 1}, events=())
        mp.setattr(offline, "activity", lambda: act)
        check = offline.ConnectionCheck(time.time(), True, (), processes=1)
        posted: list[Callable[[], None]] = []
        win = ost.NetworkLogWindow(root, get_check=lambda: check, post_to_main=posted.append)
        win.withdraw()
        out["offline.window"] = _texts(win)

        def _self_test_fails() -> list[Any]:
            raise RuntimeError("cannot run the self-test")

        mp.setattr(offline, "self_test", _self_test_fails)
        win.verify()
        deadline = time.time() + 10
        while not posted and time.time() < deadline:
            time.sleep(0.02)
        for fn in posted:
            fn()
        out["offline.window.verify_failed"] = [
            line for line in win.content().split("\n") if "self-test" in line]
        win.destroy()
        frame = ttk.Frame(root)
        frame.pack()
        unknown = offline.ConnectionCheck(time.time(), False, error="no psutil")
        bar = ost.OfflineStatusBar(root, post_to_main=posted.append, poll=lambda: unknown)
        bar.show(before=frame)
        out["offline.bar"] = _texts(bar)
        bar.destroy()

        # ---- the quiet bars and their two windows
        noop: Callable[[], None] = lambda: None  # noqa: E731
        upd = ub.UpdateBar(root, on_whats_new=noop, on_download=noop, on_later=noop, on_skip=noop)
        out["bar.update"] = _texts(upd)
        dl = ub.DownloaderUpdateBar(root, on_update=noop, on_dismiss=noop)
        dl.show_offer("offer", before=frame)
        out["bar.downloader.offer"] = _texts(dl)
        dl.show_progress("progress", before=frame)
        out["bar.downloader.progress"] = _texts(dl)
        dl.show_result("result", before=frame, can_retry=False)
        out["bar.downloader.result"] = _texts(dl)
        star = ub.StarBar(root, on_open=noop, on_not_now=noop, on_never=noop)
        out["bar.star"] = _texts(star)
        for w in (upd, dl, star):
            w.destroy()
        mp.setattr(ub, "place_over", lambda *_a, **_k: None)
        top = ub.show_whats_new(root, version="9.9.9", headline="Faster start",
                                highlights=("One thing", "Another"), on_full_notes=noop)
        out["whats_new.full"] = _texts(top)
        top.destroy()
        top = ub.show_whats_new(root, version="9.9.9", headline="", highlights=(),
                                on_full_notes=noop)
        out["whats_new.empty"] = _texts(top)
        top.destroy()
        top = ub.show_update_command(root, version="9.9.9", command="git pull")
        out["update_command"] = _texts(top)
        _find_button(top, i18n._("Copy")).invoke()
        out["update_command.copied"] = _texts(top)
        top.destroy()

        # ---- error dialog (title and message are the caller's), console menu, notice, help icon
        before = set(root.winfo_children())
        error_dialog.show_error(root, "Caller title", "Caller message.", detail="Traceback")
        dlg = next(w for w in root.winfo_children() if w not in before)
        out["error_dialog"] = _texts(dlg)
        _find_button(dlg, i18n._("Show details ▸")).invoke()
        out["error_dialog.open"] = _texts(dlg)
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()
        holder = ttk.Frame(root)
        console_mod.build_console(holder)
        out["console"] = _texts(holder)
        host_for(holder).post("Caller notice")
        out["notice"] = _texts(host_for(holder).frame)
        out["help_icon"] = _texts(help_icon(holder, "Caller help"))
        holder.destroy()
    finally:
        root.destroy()
    return out


# Texts in the tk capture that are not these modules' own (data or the caller's text).
@pytest.mark.timeout(120)
def test_capture_tk_fixture(english: None, monkeypatch: pytest.MonkeyPatch) -> None:
    if not SENTINEL.exists():
        pytest.skip("capture runs only when tests/fixtures/i18n/CAPTURE_WAVE_5 exists")
    _write_section("tk", capture_tk(monkeypatch))


@pytest.mark.timeout(120)
def test_tk_english_texts_match_the_capture_made_before_translation(
        english: None, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _load_fixture()["tk"]
    got = json.loads(json.dumps(capture_tk(monkeypatch)))
    assert got == expected


@pytest.mark.timeout(120)
def test_tk_pseudo_locale_leaves_no_text_untranslated(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    states = capture_tk(monkeypatch)
    assert _unmarked_in(states) == []


@pytest.mark.timeout(120)
def test_tk_hardware_choice_saved_is_the_same_tier_in_the_pseudo_locale(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The saved hardware.json content is the tier itself, never a displayed label."""
    tk = pytest.importorskip("tkinter")
    from app.widgets import hardware_wizard as hwz
    from core import hardware as hw
    saved: list[Any] = []
    monkeypatch.setattr(hwz, "place_over", lambda *_a, **_k: None)
    monkeypatch.setattr(hwz.HardwareWizard, "_reprobe", lambda self: None)
    monkeypatch.setattr(hw, "save_hardware_choice", lambda tier: saved.append(tier) or "p")
    tier = hw.Tier("cpu_int8", "CPU int8", "cpu", "int8")
    root = tk.Tk()
    root.withdraw()
    try:
        wiz = hwz.HardwareWizard(root)
        wiz.withdraw()
        wiz._reprobe_done(wiz._probe_seq, [tier], None)
        wiz._user_picked = True
        wiz._save_and_close()
    finally:
        root.destroy()
    assert saved == [tier]
    assert hw.tier_to_dict(saved[0])["label"] == "CPU int8"

