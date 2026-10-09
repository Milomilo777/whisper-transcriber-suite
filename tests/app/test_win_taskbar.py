"""Windows taskbar progress, job badge and flash (card C2.76).

COM is faked at the ``_Native`` boundary, so the logic, the guards and the order of calls are
pinned on every OS. The vtable test builds a fake COM object out of ctypes callbacks and checks
that each wrapper method lands on the slot the Windows SDK header gives it (Windows only); one
last test talks to the real taskbar on a Windows PC (a withdrawn Tk window only).
"""
from __future__ import annotations

import ctypes
import glob
import logging
import re
import subprocess
import sys
import threading
import tkinter as tk
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.theme import win_taskbar as wt
from core import config as cfg

ROOT = Path(__file__).resolve().parents[2]
HWND = 0x1_2345_6789   # above 32 bits on purpose: a truncated handle must show in the tests


# ----------------------------------------------------------------------------- fakes

class Crash(BaseException):
    """A hard crash: nothing in the integration may catch it (an access violation is not caught)."""


class FakeNative:
    """Records every call. ``hr`` maps a method name to the HRESULT it returns."""

    def __init__(self, marker: Path | None = None) -> None:
        self.marker = marker
        self.calls: list[tuple[Any, ...]] = []
        self.hr: dict[str, int] = {}
        self.raises: dict[str, BaseException] = {}
        self.foreground = False
        self.button_cb: Any = None
        self.marker_seen: list[bool] = []
        self.closed = 0

    def _do(self, name: str, *args: Any) -> int:
        self.calls.append((name, *args))
        if self.marker is not None and name in ("co_initialize", "create", "state", "value", "overlay"):
            self.marker_seen.append(self.marker.exists())
        if name in self.raises:
            raise self.raises[name]
        return self.hr.get(name, 0)

    def co_initialize(self) -> None:
        self._do("co_initialize")

    def create(self) -> None:
        self._do("create")

    def top_window(self, widget_id: int) -> int:
        self.calls.append(("top_window", widget_id))
        return HWND

    def watch_button_created(self, hwnd: int, callback: Any) -> None:
        self._do("watch", hwnd)
        self.button_cb = callback

    def set_progress_state(self, hwnd: int, flag: int) -> int:
        return self._do("state", hwnd, flag)

    def set_progress_value(self, hwnd: int, done: int, total: int) -> int:
        return self._do("value", hwnd, done, total)

    def set_overlay(self, hwnd: int, label: str | None, text: str) -> int:
        if label is not None and "overlay_icon" in self.raises:   # only the real badge, not a clear
            self.calls.append(("overlay", hwnd, label, text))
            raise self.raises["overlay_icon"]
        return self._do("overlay", hwnd, label, text)

    def is_foreground(self, hwnd: int) -> bool:
        return self.foreground

    def flash(self, hwnd: int, count: int) -> None:
        self._do("flash", hwnd, count)

    def close(self) -> None:
        self.closed += 1

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def only(self, name: str) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == name]


def task(status: str, progress: float = 0) -> SimpleNamespace:
    return SimpleNamespace(status=status, progress=progress)


def make_root(queue: list[Any] | None = None, downloads: list[Any] | None = None,
              chime: bool = True, state: str = "normal") -> SimpleNamespace:
    return SimpleNamespace(
        queue=queue if queue is not None else [],
        download_queue=downloads if downloads is not None else [],
        chime_on_complete_var=SimpleNamespace(get=lambda: chime),
        winfo_id=lambda: 77, state=lambda: state,
    )


@pytest.fixture
def tb(monkeypatch, tmp_path):
    """Windows, config on, a fake native layer, the marker in a temp folder."""
    marker = tmp_path / "taskbar.marker"
    native = FakeNative(marker)
    monkeypatch.setattr(wt, "_platform", lambda: "win32")
    monkeypatch.setattr(wt, "marker_path", lambda: marker)
    monkeypatch.setattr(wt, "_native_factory", lambda: native)
    monkeypatch.setattr(wt, "_app_version", lambda: "9.9.9")
    wt.set_enabled(True)
    return SimpleNamespace(native=native, marker=marker)


# ------------------------------------------------------------------ SDK numbers pinned

def test_the_vtable_slots_follow_the_sdk_header_order() -> None:
    methods = list(wt.ITASKBAR_LIST3_METHODS)
    assert methods[:3] == ["QueryInterface", "AddRef", "Release"]                  # IUnknown
    assert methods[3:8] == ["HrInit", "AddTab", "DeleteTab", "ActivateTab", "SetActiveAlt"]
    assert methods[8:9] == ["MarkFullscreenWindow"]                                # ITaskbarList2
    assert methods[9:] == [                                                        # ITaskbarList3
        "SetProgressValue", "SetProgressState", "RegisterTab", "UnregisterTab", "SetTabOrder",
        "SetTabActive", "ThumbBarAddButtons", "ThumbBarUpdateButtons", "ThumbBarSetImageList",
        "SetOverlayIcon", "SetThumbnailTooltip", "SetThumbnailClip"]
    assert len(methods) == 21


def test_the_slots_used_are_the_numbers_from_the_header() -> None:
    assert (wt.SLOT_RELEASE, wt.SLOT_HR_INIT) == (2, 3)
    assert (wt.SLOT_SET_PROGRESS_VALUE, wt.SLOT_SET_PROGRESS_STATE) == (9, 10)
    assert wt.SLOT_SET_OVERLAY_ICON == 18


def _sdk_header() -> str | None:
    pattern = r"C:\Program Files (x86)\Windows Kits\10\Include\*\um\ShObjIdl_core.h"
    found = sorted(glob.glob(pattern))
    return found[-1] if found else None


@pytest.mark.skipif(_sdk_header() is None, reason="Windows SDK header not installed")
def test_the_slots_match_the_installed_sdk_header() -> None:
    """Re-derive the slot order from the real header on a machine that has the SDK."""
    text = Path(str(_sdk_header())).read_text(encoding="utf-8", errors="replace")

    def methods_of(interface: str) -> list[str]:
        start = text.index(f"{interface} : public")
        body = text[start:text.index("};", start)]
        return re.findall(r"virtual HRESULT STDMETHODCALLTYPE\s+(\w+)", body)

    derived = ["QueryInterface", "AddRef", "Release"]
    for interface in ("ITaskbarList", "ITaskbarList2", "ITaskbarList3"):
        derived += methods_of(interface)
    assert derived == list(wt.ITASKBAR_LIST3_METHODS)


def test_the_guids_are_the_sdk_ones() -> None:
    assert uuid.UUID(wt.CLSID_TASKBAR_LIST) == uuid.UUID("56FDF344-FD6D-11d0-958A-006097C9A090")
    assert uuid.UUID(wt.IID_ITASKBAR_LIST3) == uuid.UUID("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")


def test_a_guid_has_the_windows_memory_layout() -> None:
    guid = wt._guid(wt.IID_ITASKBAR_LIST3)
    assert ctypes.sizeof(guid) == 16
    assert ctypes.string_at(ctypes.addressof(guid), 16) == uuid.UUID(wt.IID_ITASKBAR_LIST3).bytes_le


def test_the_progress_flags_are_the_sdk_ones() -> None:
    assert (wt.TBPF_NOPROGRESS, wt.TBPF_INDETERMINATE, wt.TBPF_NORMAL,
            wt.TBPF_ERROR, wt.TBPF_PAUSED) == (0, 1, 2, 4, 8)


@pytest.mark.skipif(sys.platform != "win32", reason="stdcall vtable call needs Windows")
def test_each_wrapper_method_calls_its_own_vtable_slot() -> None:
    """A fake COM object whose 21 slots record who was called, with which 64-bit arguments."""
    seen: list[tuple[str, tuple[Any, ...]]] = []
    keep: list[Any] = []
    functype = ctypes.WINFUNCTYPE  # type: ignore[attr-defined]
    void_p, hresult = ctypes.c_void_p, ctypes.c_long
    prototypes = {
        "Release": functype(ctypes.c_ulong, void_p),
        "HrInit": functype(hresult, void_p),
        "SetProgressValue": functype(hresult, void_p, void_p, ctypes.c_ulonglong, ctypes.c_ulonglong),
        "SetProgressState": functype(hresult, void_p, void_p, ctypes.c_int),
        "SetOverlayIcon": functype(hresult, void_p, void_p, void_p, ctypes.c_wchar_p),
    }
    unused = functype(hresult, void_p)

    def recorder(name: str):
        def call(*args: Any) -> int:
            seen.append((name, args[1:]))
            return 0
        return call

    slots: list[Any] = []
    for name in wt.ITASKBAR_LIST3_METHODS:
        callback = prototypes.get(name, unused)(recorder(name))
        keep.append(callback)
        slots.append(ctypes.cast(callback, ctypes.c_void_p))
    table = (ctypes.c_void_p * len(slots))(*[s.value for s in slots])
    obj = ctypes.c_void_p(ctypes.addressof(table))
    com = wt._ComObject(ctypes.addressof(obj))

    assert com.hr_init() == 0
    assert com.set_progress_value(HWND, 40, 100) == 0
    assert com.set_progress_state(HWND, wt.TBPF_PAUSED) == 0
    assert com.set_overlay_icon(HWND, 0xABCDEF012, "3 jobs") == 0
    assert com.set_overlay_icon(HWND, None, "") == 0
    com.release()
    assert seen == [
        ("HrInit", ()),
        ("SetProgressValue", (HWND, 40, 100)),
        ("SetProgressState", (HWND, 8)),
        ("SetOverlayIcon", (HWND, 0xABCDEF012, "3 jobs")),
        ("SetOverlayIcon", (HWND, None, "")),
        ("Release", ()),
    ]


def test_a_null_interface_pointer_is_refused() -> None:
    with pytest.raises(wt.ComError):
        wt._ComObject(0)


# ------------------------------------------------------------------------ kill switch

def test_nothing_is_enabled_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(wt, "_platform", lambda: "darwin")
    assert wt.enabled() is False
    assert wt.enabled("linux") is False
    assert wt.enabled("win32") is True


def test_the_env_switch_is_read_live(monkeypatch) -> None:
    assert wt.enabled("win32") is True
    monkeypatch.setenv(wt.ENV_KILL_SWITCH, "1")
    assert wt.enabled("win32") is False
    monkeypatch.setenv(wt.ENV_KILL_SWITCH, "0")
    assert wt.enabled("win32") is True


@pytest.mark.parametrize("value, expected", [
    (True, True), (False, False), (None, True), ("false", False), ("False", False),
    ("0", False), ("off", False), ("", False), ("true", True), ("1", True),
])
def test_the_config_value_is_coerced_not_just_truthy(value, expected) -> None:
    wt.set_enabled(value)
    assert wt.enabled("win32") is expected


def test_the_config_default_is_on_and_a_bool() -> None:
    assert cfg.DEFAULT_CONFIG["native_taskbar"] is True


def test_the_kill_switch_means_no_native_layer_is_even_built(tb) -> None:
    wt.set_enabled(False)
    built: list[int] = []
    wt._native_factory = lambda: built.append(1) or tb.native
    wt.sync(make_root([task("running", 10)]), now=1.0)
    assert built == [] and tb.native.calls == [] and not tb.marker.exists()


def test_switching_off_while_running_releases_everything(tb) -> None:
    root = make_root([task("running", 10)])
    wt.sync(root, now=1.0)
    assert tb.native.closed == 0
    wt.set_enabled(False)
    wt.sync(root, now=3.0)
    assert tb.native.closed == 1


def test_off_windows_sync_does_nothing(tb, monkeypatch) -> None:
    monkeypatch.setattr(wt, "_platform", lambda: "linux")
    wt.sync(make_root([task("running", 10)]), now=1.0)
    assert tb.native.calls == []


# --------------------------------------------------------------------------- snapshot

@pytest.mark.parametrize("queue, downloads, error, expected", [
    ([], [], False, wt.Snapshot(wt.TBPF_NOPROGRESS, 0, 0)),
    ([task("running", 40)], [], False, wt.Snapshot(wt.TBPF_NORMAL, 40, 1)),
    ([task("running", 40), task("running", 60)], [], False, wt.Snapshot(wt.TBPF_NORMAL, 50, 2)),
    ([task("running", 0)], [], False, wt.Snapshot(wt.TBPF_INDETERMINATE, 0, 1)),
    ([task("paused", 30)], [], False, wt.Snapshot(wt.TBPF_PAUSED, 30, 1)),
    ([task("paused", 30), task("running", 80)], [], False, wt.Snapshot(wt.TBPF_NORMAL, 80, 2)),
    ([task("waiting"), task("waiting")], [], False, wt.Snapshot(wt.TBPF_NOPROGRESS, 0, 2)),
    ([task("finished"), task("cancelled"), task("error")], [], False, wt.Snapshot()),
    ([task("running", 20)], [], True, wt.Snapshot(wt.TBPF_ERROR, 20, 1)),
    ([task("running", 0)], [], True, wt.Snapshot(wt.TBPF_ERROR, 100, 1)),
    ([task("error")], [], True, wt.Snapshot(wt.TBPF_ERROR, 100, 0)),
    ([task("paused", 70)], [], True, wt.Snapshot(wt.TBPF_ERROR, 70, 1)),
    ([task("running", 150)], [], False, wt.Snapshot(wt.TBPF_NORMAL, 100, 1)),
    ([task("running", -5), task("running", 50)], [], False, wt.Snapshot(wt.TBPF_NORMAL, 25, 2)),
    ([task("running", None)], [], False, wt.Snapshot(wt.TBPF_INDETERMINATE, 0, 1)),
    ([task("running", float("nan"))], [], False, wt.Snapshot(wt.TBPF_INDETERMINATE, 0, 1)),
    ([], [task("running", 10)], False, wt.Snapshot(wt.TBPF_NORMAL, 10, 1)),
    ([], [task("burning", 90)], False, wt.Snapshot(wt.TBPF_NORMAL, 90, 1)),
    ([], [task("waiting"), task("paused", 5)], False, wt.Snapshot(wt.TBPF_PAUSED, 5, 2)),
    # a download "transcribing" is its transcription task in the other queue: counted once
    ([task("running", 30)], [task("transcribing", 30)], False, wt.Snapshot(wt.TBPF_NORMAL, 30, 1)),
    ([], [task("finished"), task("error"), task("cancelled")], False, wt.Snapshot()),
])
def test_the_snapshot_for_a_queue(queue, downloads, error, expected) -> None:
    assert wt.summarize(queue, downloads, error=error) == expected


def test_a_download_uses_the_apps_row_progress_when_given() -> None:
    snap = wt.summarize([], [task("running", 5)], download_progress=lambda item: 66)
    assert snap == wt.Snapshot(wt.TBPF_NORMAL, 66, 1)


@pytest.mark.parametrize("count, label", [(1, "1"), (9, "9"), (10, "9+"), (250, "9+")])
def test_the_badge_text(count, label) -> None:
    assert wt.badge_label(count) == label


# ------------------------------------------------------------------------ badge icon

def _pixels(label: str, size: int) -> list[list[tuple[int, int, int, int]]]:
    data = wt.render_badge(label, size)
    assert len(data) == size * size * 4
    flat = [tuple(data[i:i + 4]) for i in range(0, len(data), 4)]
    return [flat[y * size:(y + 1) * size] for y in range(size)]


@pytest.mark.parametrize("size", [16, 20, 24, 32, 48])
@pytest.mark.parametrize("label", ["1", "7", "9+"])
def test_the_badge_is_a_red_square_with_white_text(size, label) -> None:
    rows = _pixels(label, size)
    red = (0x1C, 0x2B, 0xC4, 0xFF)   # BGRA
    white = (0xFF, 0xFF, 0xFF, 0xFF)
    flat = [p for row in rows for p in row]
    assert set(flat) <= {red, white, (0, 0, 0, 0)}
    assert flat.count(white) > 0 and flat.count(red) > flat.count(white)
    assert rows[0][0] == (0, 0, 0, 0) and rows[-1][-1] == (0, 0, 0, 0)   # rounded corners
    assert rows[size // 2][0] == red                                      # the edge is the badge
    # the text keeps one pixel of margin on every side: nothing white touches the border
    border = rows[0] + rows[-1] + [row[0] for row in rows] + [row[-1] for row in rows]
    assert white not in border


def test_the_badge_text_is_centred() -> None:
    size = 16
    rows = _pixels("8", size)
    white_x = [x for row in rows for x, p in enumerate(row) if p == (0xFF, 0xFF, 0xFF, 0xFF)]
    white_y = [y for y, row in enumerate(rows) for p in row if p == (0xFF, 0xFF, 0xFF, 0xFF)]
    assert abs((min(white_x) + max(white_x)) - (size - 1)) <= 1
    assert abs((min(white_y) + max(white_y)) - (size - 1)) <= 1


def test_the_digit_8_has_the_expected_pixel_count() -> None:
    # 3x5 font: "8" lights 13 cells; at 16 px the scale is 2, so 13 * 4 pixels.
    white = sum(p == (0xFF, 0xFF, 0xFF, 0xFF) for row in _pixels("8", 16) for p in row)
    assert white == 13 * 4


@pytest.mark.parametrize("bad", ["", "a", "-1", "123", "9+9"])
def test_a_label_that_cannot_be_drawn_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        wt.render_badge(bad, 16)


def test_a_tiny_size_is_refused() -> None:
    with pytest.raises(ValueError):
        wt.render_badge("1", 4)


# ------------------------------------------------------------------- first activation

def test_nothing_happens_while_the_queue_is_empty(tb) -> None:
    wt.sync(make_root(), now=1.0)
    assert tb.native.calls == [] and not tb.marker.exists()


def test_the_first_job_sets_up_com_then_shows_state_value_and_badge(tb) -> None:
    root = make_root([task("running", 40)])
    wt.sync(root, now=1.0)
    n = tb.native
    assert n.names() == [
        "top_window", "co_initialize", "create", "watch",
        "value", "state", "overlay",                      # the plain-call smoke test
        "state", "value", "overlay"]                      # the real update
    assert n.calls[0] == ("top_window", 77)
    smoke, real = n.calls[4:7], n.calls[7:]
    assert smoke == [("value", HWND, 0, 100), ("state", HWND, wt.TBPF_NOPROGRESS),
                     ("overlay", HWND, None, "")]
    assert real == [("state", HWND, wt.TBPF_NORMAL), ("value", HWND, 40, 100),
                    ("overlay", HWND, "1", "1 job")]


def test_the_marker_exists_during_com_setup_and_is_gone_after_the_first_update(tb) -> None:
    wt.sync(make_root([task("running", 40)]), now=1.0)
    assert tb.native.marker_seen and all(tb.native.marker_seen)   # present at every setup call
    assert not tb.marker.exists()


def test_the_marker_stays_while_the_first_update_has_not_happened(tb) -> None:
    root = make_root([task("running", 40)])
    tb.native.raises["overlay_icon"] = Crash()  # the first badge icon call "crashes the process"
    with pytest.raises(Crash):
        wt.sync(root, now=1.0)
    assert tb.marker.exists()


def test_a_python_error_before_the_first_update_is_not_a_crash(tb, monkeypatch) -> None:
    """Only a crash may leave the marker; an exception the code catches must not."""
    real = wt.summarize
    seen = {"n": 0}

    def flaky(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] == 2:           # the second call is the one after the set-up
            raise RuntimeError("bug in the snapshot")
        return real(*args, **kwargs)

    monkeypatch.setattr(wt, "summarize", flaky)
    wt.sync(make_root([task("running", 1)]), now=1.0)    # must not raise
    assert not tb.marker.exists()


def test_a_crash_during_com_setup_disables_the_next_start(tb, caplog) -> None:
    tb.native.raises["create"] = Crash()
    with pytest.raises(Crash):
        wt.sync(make_root([task("running", 1)]), now=1.0)
    assert tb.marker.exists()
    # "next start": fresh process state, same marker on disk
    wt.reset_for_tests()
    built: list[int] = []
    fresh = FakeNative(tb.marker)
    wt.set_enabled(True)
    wt._native_factory = lambda: built.append(1) or fresh
    with caplog.at_level(logging.WARNING, logger=wt.logger.name):
        wt.sync(make_root([task("running", 1)]), now=1.0)
        wt.sync(make_root([task("running", 1)]), now=9.0)
    assert fresh.names() == ["top_window"]            # no COM call at all
    assert tb.marker.exists()                          # kept, so the next start stays off too
    assert "crashed while setting up" in caplog.text and str(tb.marker) in caplog.text


def test_a_marker_of_another_app_version_is_stale_and_ignored(tb) -> None:
    tb.marker.write_text("1.0.0", encoding="utf-8")
    wt.sync(make_root([task("running", 1)]), now=1.0)
    assert "create" in tb.native.names()
    assert not tb.marker.exists()


def test_a_marker_of_this_version_blocks(tb) -> None:
    tb.marker.write_text("9.9.9", encoding="utf-8")
    wt.sync(make_root([task("running", 1)]), now=1.0)
    assert "create" not in tb.native.names()


def test_an_unwritable_marker_keeps_the_integration_off(tb, monkeypatch, caplog) -> None:
    blocker = tb.marker.parent / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(wt, "marker_path", lambda: blocker / "taskbar.marker")
    with caplog.at_level(logging.WARNING, logger=wt.logger.name):
        wt.sync(make_root([task("running", 1)]), now=1.0)
    assert "co_initialize" not in tb.native.names()
    assert "cannot be written" in caplog.text


@pytest.mark.parametrize("where", ["co_initialize", "create", "watch_hr", "first_state"])
def test_a_handled_setup_failure_removes_the_marker_and_stays_off(tb, where, caplog) -> None:
    if where == "co_initialize":
        tb.native.raises["co_initialize"] = wt.ComError("mta")
    elif where == "create":
        tb.native.raises["create"] = wt.ComError("no class")
    elif where == "first_state":
        tb.native.hr["state"] = -2147467259     # E_FAIL
    root = make_root([task("running", 1)])
    if where == "watch_hr":
        tb.native.raises["watch"] = OSError("no comctl32")
    with caplog.at_level(logging.WARNING, logger=wt.logger.name):
        wt.sync(root, now=1.0)
        wt.sync(root, now=5.0)
    assert not tb.marker.exists()
    if where == "watch_hr":
        # losing only the Explorer-restart hook must not turn the whole feature off
        assert "state" in tb.native.names() and tb.native.closed == 0
        return
    assert tb.native.closed == 1
    assert "off for this session" in caplog.text
    assert tb.native.names().count("co_initialize") <= 1    # never retried within the session


def test_a_window_without_a_frame_yet_is_retried_without_marker(tb) -> None:
    tb.native.top_window = lambda widget_id: 0           # type: ignore[method-assign]
    wt.sync(make_root([task("running", 1)]), now=1.0)
    assert not tb.marker.exists() and "co_initialize" not in tb.native.names()
    tb.native.top_window = lambda widget_id: HWND        # type: ignore[method-assign]
    wt.sync(make_root([task("running", 1)]), now=2.0)
    assert "create" in tb.native.names()


def test_a_withdrawn_window_is_left_alone(tb) -> None:
    wt.sync(make_root([task("running", 1)], state="withdrawn"), now=1.0)
    assert tb.native.calls == []


def test_a_minimised_window_still_gets_its_progress(tb) -> None:
    wt.sync(make_root([task("running", 1)], state="iconic"), now=1.0)
    assert ("state", HWND, wt.TBPF_NORMAL) in tb.native.calls


def test_only_the_main_thread_may_use_com(tb) -> None:
    root = make_root([task("running", 1)])
    thread = threading.Thread(target=lambda: wt.sync(root, now=1.0))
    thread.start()
    thread.join()
    assert tb.native.calls == []


# ------------------------------------------------------------------------- updates

def test_a_changed_percent_sends_only_the_value(tb) -> None:
    job = task("running", 10)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.calls.clear()
    job.progress = 11
    wt.sync(root, now=2.0)
    assert tb.native.calls == [("value", HWND, 11, 100)]


def test_an_unchanged_state_sends_nothing(tb) -> None:
    root = make_root([task("running", 10)])
    wt.sync(root, now=1.0)
    tb.native.calls.clear()
    for second in (2.0, 3.0, 4.0):
        wt.sync(root, now=second)
    assert tb.native.calls == []


def test_pause_resume_and_idle_follow_the_queue(tb) -> None:
    job = task("running", 50)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.calls.clear()
    job.status = "paused"
    wt.sync(root, now=2.0)
    assert tb.native.calls == [("state", HWND, wt.TBPF_PAUSED), ("value", HWND, 50, 100)]
    tb.native.calls.clear()
    job.status = "running"
    wt.sync(root, now=3.0)
    assert tb.native.calls == [("state", HWND, wt.TBPF_NORMAL), ("value", HWND, 50, 100)]
    tb.native.calls.clear()
    job.status = "cancelled"
    wt.sync(root, now=4.0)
    assert tb.native.calls == [("state", HWND, wt.TBPF_NOPROGRESS), ("overlay", HWND, None, "")]


def test_the_badge_counts_queued_and_running_jobs(tb) -> None:
    root = make_root([task("running", 10), task("waiting"), task("waiting")])
    wt.sync(root, now=1.0)
    assert tb.native.only("overlay")[-1] == ("overlay", HWND, "3", "3 jobs")
    root.queue.extend(task("waiting") for _ in range(8))
    wt.sync(root, now=2.0)
    assert tb.native.only("overlay")[-1] == ("overlay", HWND, "9+", "11 jobs")


def test_waiting_jobs_alone_show_a_badge_but_no_bar(tb) -> None:
    wt.sync(make_root([task("waiting")]), now=1.0)
    assert tb.native.only("overlay")[-1] == ("overlay", HWND, "1", "1 job")
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_NOPROGRESS)


def test_never_more_than_two_rounds_per_second(tb) -> None:
    job = task("running", 0)
    root = make_root([job])
    wt.sync(root, now=0.0)
    tb.native.calls.clear()
    time = 0.0
    for step in range(1, 201):            # 20 s of refreshes, one every 100 ms
        time = step / 10
        job.progress = step % 100 + 1     # the percent changes on every refresh
        wt.sync(root, now=time)
    values = tb.native.only("value")
    assert 0 < len(values) <= 2 * 20     # 20 seconds, at most two rounds per second


def test_a_state_change_inside_the_throttle_window_is_not_lost(tb) -> None:
    job = task("running", 10)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.calls.clear()
    job.status = "paused"
    wt.sync(root, now=1.2)                # too soon: skipped
    assert tb.native.calls == []
    wt.sync(root, now=1.5)                # next round picks it up
    assert ("state", HWND, wt.TBPF_PAUSED) in tb.native.calls


# ----------------------------------------------------------------------- failure latch

def test_a_failed_job_turns_the_bar_red_and_it_stays_until_seen(tb) -> None:
    job = task("running", 30)
    root = make_root([job])
    wt.sync(root, now=1.0)
    job.status = "error"
    wt.sync(root, now=2.0)
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_ERROR)
    assert tb.native.only("value")[-1] == ("value", HWND, 100, 100)
    tb.native.foreground = False
    wt.sync(root, now=60.0)               # long after, window still behind: still red
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_ERROR)


def test_the_red_bar_clears_when_the_window_is_in_front_after_a_few_seconds(tb) -> None:
    job = task("running", 30)
    root = make_root([job])
    wt.sync(root, now=1.0)
    job.status = "error"
    wt.sync(root, now=2.0)
    tb.native.foreground = True
    wt.sync(root, now=3.0)                # in front but only 1 s: the user may have missed it
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_ERROR)
    wt.sync(root, now=2.0 + wt.ERROR_MIN_SECONDS)
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_NOPROGRESS)


def test_a_job_that_fails_before_it_was_ever_shown_still_turns_the_bar_red(tb) -> None:
    wt.sync(make_root([task("error")]), now=1.0)
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_ERROR)


def test_one_error_is_latched_once(tb) -> None:
    bad = task("error")
    root = make_root([bad, task("running", 10)])
    wt.sync(root, now=1.0)
    tb.native.foreground = True
    wt.sync(root, now=10.0)               # cleared
    assert tb.native.only("state")[-1][2] == wt.TBPF_NORMAL
    wt.sync(root, now=11.0)               # the same failed row must not turn it red again
    assert tb.native.only("state")[-1][2] == wt.TBPF_NORMAL


def test_a_running_job_next_to_a_failed_one_shows_red_with_its_progress(tb) -> None:
    root = make_root([task("running", 45), task("error")])
    wt.sync(root, now=1.0)
    assert tb.native.only("state")[-1] == ("state", HWND, wt.TBPF_ERROR)
    assert tb.native.only("value")[-1] == ("value", HWND, 45, 100)


# ----------------------------------------------------------------------------- flash

def _finish(tb, *, chime=True, foreground=False, how="finished", extra=()):
    job = task("running", 50)
    root = make_root([job, *extra], chime=chime)
    wt.sync(root, now=1.0)
    tb.native.foreground = foreground
    job.status = how
    wt.sync(root, now=2.0)
    return tb.native.only("flash")


def test_a_finished_job_flashes_once_when_the_window_is_behind(tb) -> None:
    assert _finish(tb) == [("flash", HWND, wt.FLASH_COUNT)]


def test_no_flash_when_the_window_is_in_front(tb) -> None:
    assert _finish(tb, foreground=True) == []


def test_no_flash_when_the_chime_setting_is_off(tb) -> None:
    assert _finish(tb, chime=False) == []


@pytest.mark.parametrize("how", ["cancelled", "error"])
def test_no_flash_for_a_cancelled_or_failed_job(tb, how) -> None:
    assert _finish(tb, how=how) == []


def test_two_jobs_finishing_together_flash_once(tb) -> None:
    a, b = task("running", 50), task("running", 60)
    root = make_root([a, b])
    wt.sync(root, now=1.0)
    a.status = b.status = "finished"
    wt.sync(root, now=2.0)
    assert len(tb.native.only("flash")) == 1


def test_a_finished_download_flashes_too(tb) -> None:
    d = task("running", 20)
    root = make_root([], [d])
    wt.sync(root, now=1.0)
    d.status = "finished"
    wt.sync(root, now=2.0)
    assert len(tb.native.only("flash")) == 1


def test_a_row_that_was_already_finished_when_first_seen_does_not_flash(tb) -> None:
    root = make_root([task("finished"), task("running", 5)])
    wt.sync(root, now=1.0)
    wt.sync(root, now=2.0)
    assert tb.native.only("flash") == []


def test_one_finish_is_flashed_once_even_if_the_row_stays(tb) -> None:
    job = task("running", 50)
    root = make_root([job])
    wt.sync(root, now=1.0)
    job.status = "finished"
    for second in (2.0, 3.0, 4.0):
        wt.sync(root, now=second)
    assert len(tb.native.only("flash")) == 1


def test_a_flash_failure_never_reaches_the_caller(tb) -> None:
    job = task("running", 50)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.raises["flash"] = OSError("no user32")
    job.status = "finished"
    wt.sync(root, now=2.0)                # must not raise


# ------------------------------------------------------- Explorer restart / failures

def test_taskbar_button_created_rebuilds_the_object_and_reapplies_everything(tb) -> None:
    root = make_root([task("running", 40), task("waiting")])
    wt.sync(root, now=1.0)
    assert tb.native.button_cb is not None
    tb.native.calls.clear()
    tb.native.button_cb()                 # Explorer restarted: the message arrives
    wt.sync(root, now=2.0)
    assert tb.native.names() == ["create", "state", "value", "overlay"]
    assert tb.native.calls[-1] == ("overlay", HWND, "2", "2 jobs")
    tb.native.calls.clear()
    wt.sync(root, now=3.0)
    assert tb.native.calls == []          # and it settles


def test_the_button_message_does_no_work_inside_the_window_procedure(tb) -> None:
    root = make_root([task("running", 40)])
    wt.sync(root, now=1.0)
    tb.native.calls.clear()
    tb.native.button_cb()
    assert tb.native.calls == []


def test_a_failing_recreate_is_retried_and_counted(tb) -> None:
    root = make_root([task("running", 40)])
    wt.sync(root, now=1.0)
    tb.native.button_cb()
    tb.native.raises["create"] = wt.ComError("explorer is down")
    for step in range(2, 2 + wt.MAX_FAILURES):
        wt.sync(root, now=float(step))
    assert tb.native.closed == 1          # given up after MAX_FAILURES rounds
    tb.native.calls.clear()
    wt.sync(root, now=99.0)
    assert tb.native.calls == []


def test_a_refused_call_is_retried_next_round(tb) -> None:
    job = task("running", 40)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.hr["value"] = -2147023174       # RPC server unavailable
    job.progress = 41
    wt.sync(root, now=2.0)
    tb.native.hr.clear()
    tb.native.calls.clear()
    wt.sync(root, now=3.0)
    assert ("value", HWND, 41, 100) in tb.native.calls
    assert tb.native.closed == 0


def test_five_refused_rounds_in_a_row_switch_the_integration_off(tb, caplog) -> None:
    job = task("running", 40)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.hr["value"] = -2147023174
    with caplog.at_level(logging.WARNING, logger=wt.logger.name):
        for step in range(2, 2 + wt.MAX_FAILURES):
            job.progress = step
            wt.sync(root, now=float(step))
    assert tb.native.closed == 1
    assert "off for this session" in caplog.text
    tb.native.calls.clear()
    wt.sync(root, now=50.0)
    assert tb.native.calls == []


def test_a_python_error_in_a_native_call_is_counted_and_never_raised(tb) -> None:
    job = task("running", 40)
    root = make_root([job])
    wt.sync(root, now=1.0)
    tb.native.raises["value"] = OSError("boom")
    job.progress = 50
    wt.sync(root, now=2.0)                # does not raise
    assert tb.native.closed == 0


def test_success_resets_the_failure_count(tb) -> None:
    job = task("running", 40)
    root = make_root([job])
    wt.sync(root, now=1.0)
    for round_ in range(3):
        tb.native.hr["value"] = -1
        job.progress += 1
        wt.sync(root, now=2.0 + 2 * round_)
        tb.native.hr.clear()
        job.progress += 1
        wt.sync(root, now=3.0 + 2 * round_)
    assert tb.native.closed == 0


# ------------------------------------------------------------------ release on exit

def test_shutdown_releases_once_and_nothing_restarts_after_it(tb) -> None:
    root = make_root([task("running", 40)])
    wt.sync(root, now=1.0)
    wt.shutdown()
    wt.shutdown()
    assert tb.native.closed == 1
    tb.native.calls.clear()
    wt.sync(root, now=9.0)
    assert tb.native.calls == []


def test_shutdown_never_raises_so_the_window_can_always_close(tb, monkeypatch) -> None:
    def boom() -> None:
        raise OSError("release failed")

    monkeypatch.setattr(wt, "_release", boom)
    wt.shutdown()                      # must not raise


def test_shutdown_before_any_job_is_harmless(tb) -> None:
    wt.shutdown()
    assert tb.native.calls == []


def test_a_second_window_gets_its_own_setup(tb) -> None:
    first, second = make_root([task("running", 1)]), make_root([task("running", 2)])
    wt.sync(first, now=1.0)
    wt.sync(second, now=2.0)
    assert tb.native.closed == 1
    assert tb.native.names().count("create") == 2


# ------------------------------------------------------------------- import / wiring

def test_importing_the_module_loads_no_windows_dll() -> None:
    """The module must import on macOS/Linux: no WinDLL or WINFUNCTYPE use at import time."""
    code = (
        "import ctypes\n"
        "def _boom(*a, **k): raise AssertionError('Windows DLL touched at import')\n"
        "ctypes.WinDLL = _boom\n"
        "ctypes.WINFUNCTYPE = _boom\n"
        "ctypes.windll = None\n"
        "import app.theme.win_taskbar as m\n"
        "assert m.enabled('darwin') is False\n"
        "print('ok')\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def _app_text() -> str:
    return (ROOT / "app" / "app.py").read_text(encoding="utf-8")


def test_the_app_reads_the_config_key() -> None:
    assert 'win_taskbar.set_enabled(self.app_config.get("native_taskbar", True))' in _app_text()


def test_the_app_refresh_calls_sync_and_destroy_calls_shutdown() -> None:
    text = _app_text()
    refresh = text[text.index("    def refresh(self) -> None:"):text.index("    def refresh_download_queue")]
    assert "win_taskbar.sync(self)" in refresh
    destroy = text[text.index("    def destroy(self) -> None:"):text.index("    # Tabs ---")]
    assert destroy.index("win_taskbar.shutdown()") < destroy.index("super().destroy()")


def test_destroying_the_app_window_releases_the_taskbar(monkeypatch) -> None:
    from app.app import App
    calls: list[str] = []
    monkeypatch.setattr(wt, "shutdown", lambda: calls.append("shutdown"))
    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    root.destroy()
    assert calls == ["shutdown"]


@pytest.mark.parametrize("spec", [
    "whisper_project_onefile.spec", "whisper_project_onedir.spec",
    "platform/macos/pyinstaller/whisper_project_mac.spec"])
def test_every_pyinstaller_spec_lists_the_module(spec) -> None:
    assert "'app.theme.win_taskbar'," in (ROOT / spec).read_text(encoding="utf-8")


def test_the_kill_switch_is_documented() -> None:
    text = (ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    assert "`native_taskbar`" in text and wt.ENV_KILL_SWITCH in text


# ------------------------------------------------------------------- the real taskbar

@pytest.mark.skipif(sys.platform != "win32", reason="real ITaskbarList3 needs Windows")
def test_the_real_taskbar_accepts_every_call_on_a_withdrawn_window() -> None:
    """Real COM on a hidden Tk window: setup, state, value, badge, flash, clean release."""
    root = tk.Tk()
    root.withdraw()
    native = None
    try:
        root.update_idletasks()
        native = wt._Native()
        hwnd = native.top_window(int(root.winfo_id()))
        assert hwnd
        try:
            native.co_initialize()
        except wt.ComError as exc:
            pytest.skip(f"this thread cannot use an STA ({exc})")
        native.create()
        hits: list[int] = []
        native.watch_button_created(hwnd, lambda: hits.append(1))
        # The message Explorer sends after a restart, posted by hand: the window hook must see it.
        user32 = ctypes.WinDLL("user32")  # type: ignore[attr-defined]
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                                        ctypes.c_ssize_t]
        message = user32.RegisterWindowMessageW(wt.TASKBAR_BUTTON_CREATED)
        assert message
        assert user32.PostMessageW(hwnd, message, 0, 0)
        for _ in range(20):
            root.update()
            if hits:
                break
        assert hits == [1]
        assert native.set_progress_state(hwnd, wt.TBPF_NORMAL) >= 0
        assert native.set_progress_value(hwnd, 33, 100) >= 0
        assert native.set_progress_state(hwnd, wt.TBPF_PAUSED) >= 0
        assert native.set_progress_state(hwnd, wt.TBPF_ERROR) >= 0
        assert native.set_overlay(hwnd, "3", "3 jobs") >= 0
        assert native.set_overlay(hwnd, "9+", "12 jobs") >= 0
        assert native.set_overlay(hwnd, None, "") >= 0
        assert native.set_progress_state(hwnd, wt.TBPF_NOPROGRESS) >= 0
        assert native.small_icon_size() >= 16
        assert native.is_foreground(hwnd) is False   # a hidden window is never the active one
        native.create()               # what an Explorer restart does: a second object
        assert native.set_progress_state(hwnd, wt.TBPF_NOPROGRESS) >= 0
    finally:
        if native is not None:
            native.close()
        root.destroy()
