"""Modal-grab hand-over for the Advanced dialog's child windows.

Tk keeps a single grab per display and does not stack them: a child's
``grab_set()`` silently replaces the owner's, and destroying the child does
NOT hand the grab back. The Report-a-problem window, the error dialog and
the HardwareWizard all implement the restore; these tests pin the same
contract for the Advanced dialog's own popups (model info, gcloud help)
and for the hub-folder picker it launches.
"""
from __future__ import annotations

import time
import tkinter as tk

import pytest

from core.config import DEFAULT_CONFIG


def _pump_until(root, cond, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def _advanced(root, tmp_path, monkeypatch):
    """A real AdvancedDialog over a dressed-up root, with the grab held."""
    from app.dialogs import advanced as adv

    cfg = dict(DEFAULT_CONFIG)
    cfg["hub_folder"] = str(tmp_path / "models")
    root.app_config = cfg
    root.log = lambda _m: None
    # Keep the test off the real screen geometry work (the display-theme
    # tests cover that); the grab is what matters here.
    dlg = adv.AdvancedDialog(root)
    if not _pump_until(root, dlg.winfo_viewable):
        dlg.destroy()
        pytest.skip("no visible desktop: windows never map")
    dlg.grab_set()
    assert root.grab_current() is dlg
    return dlg


def _top_level_child(dlg) -> tk.Toplevel:
    tops = [w for w in dlg.winfo_children() if isinstance(w, tk.Toplevel)]
    assert tops, "expected the popup Toplevel to exist"
    return tops[-1]


def test_model_info_popup_takes_the_grab_and_hands_it_back(
        root, tmp_path, monkeypatch):
    dlg = _advanced(root, tmp_path, monkeypatch)
    try:
        from app.dialogs import advanced as adv

        monkeypatch.setattr(
            adv, "catalog_entry_info",
            lambda cfg, slug: {"label": "Model", "info": "Words",
                               "approx_size_gb": 1},
        )
        dlg._show_model_info()
        top = _top_level_child(dlg)
        assert _pump_until(root, lambda: root.grab_current() is top), (
            "the info popup must hold the grab while open"
        )
        top.destroy()
        root.update()
        assert root.grab_current() is dlg, (
            "closing the info popup must make Advanced modal again"
        )
    finally:
        dlg.destroy()


def test_gcloud_help_popup_takes_the_grab_and_hands_it_back(
        root, tmp_path, monkeypatch):
    dlg = _advanced(root, tmp_path, monkeypatch)
    try:
        dlg._show_gcloud_help()
        top = _top_level_child(dlg)
        assert _pump_until(root, lambda: root.grab_current() is top), (
            "the help popup must hold the grab while open"
        )
        top.destroy()
        root.update()
        assert root.grab_current() is dlg, (
            "closing the help popup must make Advanced modal again"
        )
    finally:
        dlg.destroy()


def test_hub_picker_close_hands_the_grab_back_to_advanced(
        root, tmp_path, monkeypatch):
    dlg = _advanced(root, tmp_path, monkeypatch)
    try:
        from app.dialogs.hub_setup import HubSetupDialog

        picker = HubSetupDialog(
            dlg, dict(DEFAULT_CONFIG), save=lambda cfg: None,
            on_done=lambda _path: None,
        )
        assert _pump_until(root, lambda: root.grab_current() is picker), (
            "the hub picker must hold the grab while open"
        )
        picker._close(str(tmp_path / "hub"))
        root.update()
        assert root.grab_current() is dlg, (
            "closing the hub picker must make Advanced modal again"
        )
    finally:
        dlg.destroy()
