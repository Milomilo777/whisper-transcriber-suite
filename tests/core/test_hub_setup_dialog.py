"""Tests for the first-run Hub Folder dialog."""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


from app.dialogs.hub_setup import HubSetupDialog, ensure_hub_configured
from core import hub


@pytest.fixture
def tk_root():
    """Yield a hidden Tk root that is destroyed at fixture teardown.

    Creating a fresh ``tk.Tk()`` per test was causing intermittent
    Tcl-state corruption when run with many sibling Tk-using tests
    (transcript_viewer, hardware_wizard, etc.). Sharing a root
    per-test via a fixture lets us reliably clean it up + keeps the
    test units independent.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.update_idletasks()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass


# ---------- ensure_hub_configured short-circuit -------------------------------


def test_ensure_hub_configured_returns_existing_path_without_dialog():
    """When the config already has a hub_folder, no dialog should
    be constructed and the existing path is returned verbatim.

    Note: we deliberately use a mock master here instead of a real
    ``tk.Tk()`` root because this code path early-returns before
    touching the master. Real Tk roots in a test suite that runs
    many Tk-heavy tests (transcript_viewer, hardware_wizard,
    hub_setup_dialog construction, …) sometimes accumulate state
    that surfaces as a flaky failure on this lone test. The mock
    keeps the unit pure.
    """
    from unittest.mock import MagicMock

    cfg = {"hub_folder": "/some/path"}
    fake_master = MagicMock()

    # Use a save that fails loudly if invoked — proves no dialog
    # construction happened.
    def _fail_save(_c):
        raise AssertionError("save should not be called on the no-op path")

    out = ensure_hub_configured(fake_master, cfg, save=_fail_save)
    assert out == "/some/path"
    # The master must NOT have been used for any Tk operation
    # (no HubSetupDialog constructed → no method calls on master).
    assert not fake_master.method_calls, (
        f"master should not be touched on the no-op path, got "
        f"{fake_master.method_calls}"
    )


def test_ensure_hub_configured_returns_default_when_unset_and_opens_dialog(tmp_path, monkeypatch):
    """When hub_folder is missing, the helper returns the default
    string for the session AND constructs a HubSetupDialog.

    We mock the dialog class so we can assert it was called with
    the right args WITHOUT racing other Tk-heavy tests in the
    suite (same flake-mitigation pattern as the no-dialog test).
    """
    from unittest.mock import MagicMock, patch

    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {}
    fake_master = MagicMock()
    fake_save = MagicMock()
    fake_on_done = MagicMock()

    with patch("app.dialogs.hub_setup.HubSetupDialog") as MockDialog:
        out = ensure_hub_configured(
            fake_master, cfg, save=fake_save, on_done=fake_on_done,
        )
        # Returns the platform-default string for the session.
        assert out == str(tmp_path / hub.HUB_SUBFOLDER_NAME)
        # Dialog was constructed exactly once with the right args.
        MockDialog.assert_called_once_with(
            fake_master, cfg, save=fake_save, on_done=fake_on_done,
        )


# ---------- dialog OK persists + closes ---------------------------------------


def test_dialog_ok_writes_hub_folder_and_invokes_save(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {}
    saved_payloads: list[dict] = []
    dlg = HubSetupDialog(tk_root, cfg, save=saved_payloads.append)
    # Type a custom path into the entry.
    custom = str(tmp_path / "my_custom_hub")
    dlg._path_var.set(custom)
    dlg._on_ok()
    assert cfg["hub_folder"] == custom
    assert dlg.chosen_path == custom
    assert dlg.saved is True
    assert len(saved_payloads) == 1
    assert saved_payloads[0]["hub_folder"] == custom


def test_dialog_use_default_resets_entry_and_saves(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {"hub_folder": ""}
    saved_payloads: list[dict] = []
    dlg = HubSetupDialog(tk_root, cfg, save=saved_payloads.append)
    # User edited the path to nonsense; "Use default" should
    # reset before saving.
    dlg._path_var.set("/garbage")
    dlg._on_use_default()
    expected = str(tmp_path / hub.HUB_SUBFOLDER_NAME)
    assert cfg["hub_folder"] == expected
    assert dlg.chosen_path == expected
    assert dlg.saved is True


def test_dialog_ok_derives_model_path_from_the_configured_model(tk_root, tmp_path, monkeypatch):
    """_on_ok() must build model_path for whichever model is actually
    configured, not hardcode faster-whisper-large-v3.

    Regression guard: this dialog also reopens mid-flow to retry a
    non-writable folder for a download already in progress (see
    ModelDownloadDialog._handle_not_writable), which can be for ANY
    model the user picked -- hardcoding large-v3 here used to silently
    redirect model_path at the wrong model's cache folder.
    """
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {"model": {"name": "faster-whisper-medium"}}
    dlg = HubSetupDialog(tk_root, cfg, save=lambda _c: None)
    custom = str(tmp_path / "my_custom_hub")
    dlg._path_var.set(custom)
    dlg._on_ok()
    assert "faster-whisper-medium" in cfg["model_path"]
    assert "large-v3" not in cfg["model_path"]


def test_dialog_ok_falls_back_to_default_model_when_none_configured(tk_root, tmp_path, monkeypatch):
    """No 'model' key yet (genuine first run) still resolves to the app's
    real default, matching the pre-fix hardcoded behavior for that case."""
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg: dict = {}
    dlg = HubSetupDialog(tk_root, cfg, save=lambda _c: None)
    custom = str(tmp_path / "my_custom_hub")
    dlg._path_var.set(custom)
    dlg._on_ok()
    assert "faster-whisper-large-v3" in cfg["model_path"]


def test_dialog_cancel_does_not_save(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {"hub_folder": ""}
    saved_payloads: list[dict] = []
    dlg = HubSetupDialog(tk_root, cfg, save=saved_payloads.append)
    dlg._path_var.set("/some/typed/path")
    dlg._on_cancel()
    # Cancel returns the default but does NOT mutate config.
    assert cfg["hub_folder"] == ""
    assert saved_payloads == []
    assert dlg.saved is False
    # Caller still gets a usable path for the session.
    assert dlg.chosen_path == str(tmp_path / hub.HUB_SUBFOLDER_NAME)


# ---------- on_done callback --------------------------------------------------


def test_on_done_callback_receives_saved_path(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {"hub_folder": ""}
    received: list[str] = []
    dlg = HubSetupDialog(
        tk_root, cfg,
        save=lambda _c: None,
        on_done=received.append,
    )
    custom = str(tmp_path / "external")
    dlg._path_var.set(custom)
    dlg._on_ok()
    assert received == [custom]


def test_on_done_callback_swallows_exceptions(tk_root, tmp_path, monkeypatch):
    """A broken on_done callback must not crash the dialog flow —
    the user has already committed; subsequent failures are logged
    but the dialog must still close cleanly."""
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    cfg = {"hub_folder": ""}

    def _boom(_p):
        raise RuntimeError("callback boom")

    dlg = HubSetupDialog(
        tk_root, cfg,
        save=lambda _c: None,
        on_done=_boom,
    )
    dlg._on_use_default()
    # No exception escaped; dialog destroyed itself.
    assert not dlg.winfo_exists()


# ---------- writability probe cleanup -----------------------------------------


def test_probe_writable_leaves_no_temp_file_when_unlink_fails_once(
    tk_root, tmp_path, monkeypatch
):
    """A transient unlink failure (e.g. an AV scanner holding the file)
    must not leave the probe file behind in the user's hub folder — the
    probe is retried once during error cleanup. Pre-fix, the failed
    unlink was swallowed and the stray '.whisper-write-test-*' file
    stayed in the folder."""
    import app.dialogs.hub_setup as hs

    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)
    monkeypatch.setattr(hs.messagebox, "showwarning", lambda *a, **kw: None)

    dlg = HubSetupDialog(tk_root, {}, save=lambda _c: None)
    target = tmp_path / "probe_target"

    real_unlink = hs.os.unlink
    calls = {"n": 0}

    def _flaky_unlink(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient lock")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(hs.os, "unlink", _flaky_unlink)

    assert dlg._probe_writable(str(target)) is False
    assert list(target.iterdir()) == []


def test_probe_writable_returns_true_and_cleans_up_on_success(
    tk_root, tmp_path, monkeypatch
):
    """Happy path unchanged: the probe file is created, deleted, and the
    folder is left empty."""
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)

    dlg = HubSetupDialog(tk_root, {}, save=lambda _c: None)
    target = tmp_path / "probe_ok"

    assert dlg._probe_writable(str(target)) is True
    assert list(target.iterdir()) == []


# ---------- save_callback failure tolerance -----------------------------------


def test_dialog_save_failure_still_closes_cleanly(tk_root, tmp_path, monkeypatch):
    """A save failure (disk-full, permissions) must not leave the
    dialog open. saved must read False so the caller can retry."""
    monkeypatch.setattr(hub, "default_hub_folder", lambda: tmp_path / hub.HUB_SUBFOLDER_NAME)

    def _broken_save(_c):
        raise OSError("disk full")

    cfg = {"hub_folder": ""}
    dlg = HubSetupDialog(tk_root, cfg, save=_broken_save)
    dlg._on_ok()
    # cfg was still mutated in-memory (the OK semantics).
    assert cfg["hub_folder"]
    assert dlg.saved is False
    assert not dlg.winfo_exists()
