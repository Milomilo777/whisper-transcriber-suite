"""Advanced settings dialog (app/dialogs/advanced.py) and the translation layer.

* The English texts a person sees (window, labels, buttons, check/radio buttons, combobox values,
  hover help, status lines, message boxes, file-dialog titles) stay byte-identical to the capture
  ``tests/fixtures/i18n/i18n_wave_2_en.json``, made BEFORE the dialog's strings went through
  ``app/i18n.py``.
* Built in the ``qps-ploc`` pseudo-locale, every text the dialog owns is marked; the only
  exceptions are texts from core/ or other modules, product and format names and URLs (listed in
  ``_NOT_OURS`` with the reason).
* Combobox labels that map to stored config values (LLM provider, denoise strength, Whisper model)
  save exactly the same config in the pseudo-locale as in English.

The AdvancedDialog subclasses ``tk.Toplevel``, so most tests here need a real (withdrawn) Tk root
and skip without a display. The capture is rewritten only when ``WTS_CAPTURE_I18N=1`` is set or
the untracked trigger file ``tests/fixtures/i18n/.capture_wave_2`` exists.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_2_en.json"
TRIGGER = FIXTURE.with_name(".capture_wave_2")
MODEL_INFO = {"label": "Test model (core catalog)", "info": "Core catalog description.",
              "approx_size_gb": 1.5}
CORE_USAGE = "Core usage text (core.backends.google_cloud_stt.format_usage)"


def _capturing() -> bool:
    return os.environ.get("WTS_CAPTURE_I18N") == "1" or TRIGGER.exists()


class _Harness:
    """A withdrawn Tk root posing as the App, with every outside dependency made deterministic."""

    def __init__(self, mp: pytest.MonkeyPatch, tmp_path: Path) -> None:
        tk = pytest.importorskip("tkinter")
        from app.dialogs import advanced as adv
        from app.widgets import tooltip
        from core.backends import availability
        from core.backends.availability import EngineStatus

        self.tk = tk
        self.adv = adv
        self.mp = mp
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # no display available
            pytest.skip(f"Tk unavailable: {e}")
        self.root.withdraw()
        self.tmp_path = tmp_path
        self.logs: list[str] = []
        self.tooltips: list[str] = []
        self.messageboxes: list[list[str]] = []
        self.file_dialogs: list[list[str]] = []
        self.confirms: list[list[str]] = []
        self.saved: list[dict[str, Any]] = []
        self.save_error: Exception | None = None

        mp.setattr(adv.AdvancedDialog, "grab_set", lambda self, *a, **k: None)
        mp.setattr(adv, "place_over", lambda *_a, **_k: None)
        mp.setattr(adv, "sync_from_disk", lambda _cfg: None)
        mp.setattr(adv.AdvancedDialog, "_model_downloaded",
                   lambda _self, slug: slug == adv.DEFAULT_MODEL_SLUG)
        mp.setattr(adv, "catalog_entry_info", lambda _cfg, _slug: dict(MODEL_INFO))

        def _ready(value: Any, _cfg: Any, *, deep: bool = True) -> EngineStatus:
            return EngineStatus(str(value), True)

        mp.setattr(availability, "engine_status", _ready)
        mp.setattr(adv, "engine_status", _ready)
        mp.setattr(availability, "has_gcloud_key", lambda _cfg: False)
        mp.setattr(availability, "bundled_gcloud_key_path", lambda: "")
        mp.setattr(adv.tray, "unavailable_reason", lambda: "")
        import core.subtitle_edit as subtitle_edit
        import core.updates as updates
        import core.yt_dlp_update as ytu
        mp.setattr(subtitle_edit, "is_supported", lambda *a, **k: True)
        mp.setattr(ytu, "can_self_update", lambda *a, **k: True)
        mp.setattr(updates, "disabled_by_environment", lambda *a, **k: False)
        from core.backends import google_cloud_stt as gcs
        mp.setattr(gcs, "format_usage", lambda *a, **k: CORE_USAGE)

        def _record_help(original: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(parent: Any, text: Any, *a: Any, **k: Any) -> Any:
                if isinstance(text, str):
                    self.tooltips.append(text)
                return original(parent, text, *a, **k)
            return wrapper

        def _record_section(parent: Any, title: str, help_text: str, *a: Any, **k: Any) -> Any:
            self.tooltips.append(help_text)
            return tooltip.section_labelframe(parent, title, help_text, *a, **k)

        mp.setattr(adv, "help_icon", _record_help(tooltip.help_icon))
        mp.setattr(adv, "section_labelframe", _record_section)

        from tkinter import filedialog, messagebox

        def _showerror(title: str, message: str, **_k: Any) -> None:
            self.messageboxes.append([str(title), str(message)])

        def _file_dialog(**kwargs: Any) -> str:
            types_ = [list(t) for t in kwargs.get("filetypes", [])]
            self.file_dialogs.append([str(kwargs.get("title", "")), json.dumps(types_)])
            return ""

        mp.setattr(messagebox, "showerror", _showerror)
        mp.setattr(filedialog, "askopenfilename", _file_dialog)
        mp.setattr(filedialog, "askdirectory", _file_dialog)
        import core._threads as threads
        mp.setattr(threads, "safe_thread", lambda target, *a, **k: target())

        def _save(cfg: dict[str, Any]) -> None:
            if self.save_error is not None:
                raise self.save_error
            self.saved.append(dict(cfg))

        mp.setattr(adv, "save_config", _save)

        root: Any = self.root
        root.log = self.logs.append
        root.log_threadsafe = self.logs.append
        root.post_to_main = lambda fn: fn()
        root.transcription_service = types.SimpleNamespace(
            stop_all=lambda: None, restart_when_idle=lambda: None)

        def _confirm(_parent: Any, **kwargs: Any) -> bool:
            self.confirms.append([f"{k}={v}" for k, v in sorted(kwargs.items())])
            return False

        root._confirm_backend_switch = _confirm
        self.made: list[Any] = []

    def make(self, **cfg_overrides: Any) -> Any:
        from core.config import DEFAULT_CONFIG
        cfg = dict(DEFAULT_CONFIG)
        cfg["hub_folder"] = str(self.tmp_path / "models")
        cfg.update(cfg_overrides)
        root: Any = self.root
        root.app_config = cfg
        dlg = self.adv.AdvancedDialog(root)
        self.made.append(dlg)
        return dlg

    def new_toplevel(self, dlg: Any, action: Callable[[], None]) -> Any:
        before = set(dlg.winfo_children())
        action()
        found = [w for w in dlg.winfo_children()
                 if w not in before and isinstance(w, self.tk.Toplevel)]
        assert len(found) == 1, found
        return found[0]

    def close(self) -> None:
        for dlg in self.made:
            try:
                dlg.destroy()
            except self.tk.TclError:
                pass
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    h = _Harness(monkeypatch, tmp_path)
    try:
        yield h
    finally:
        h.close()


def _rows(pairs: list[tuple[str, str]]) -> list[list[str]]:
    return [[path, text] for path, text in pairs]


def _var_writes(var: Any) -> list[str]:
    """Every value written to a Tk variable from now on (status lines change several times)."""
    seen: list[str] = []
    var.trace_add("write", lambda *_a: seen.append(str(var.get())))
    return seen


def capture_states(h: _Harness) -> dict[str, list[list[str]]]:
    """The texts a person can see in each state of the dialog."""
    from tests.app.i18n_walk import visible_texts
    from core.backends.availability import VALUE_TO_LABEL
    import core.backends.cloud_stt as cloud_stt
    import core.backends.google_cloud_stt as gcs
    import core.offline as offline
    import core.optional_deps as optional_deps
    import core.updates as updates
    import core.yt_dlp_update as ytu
    from core.backends import availability

    states: dict[str, list[list[str]]] = {}
    dlg = h.make()
    states["dialog"] = _rows(visible_texts(dlg))
    states["tooltips"] = [[f"tooltip#{i}", t] for i, t in enumerate(h.tooltips)]
    states["model_combo_tooltip"] = [["reason", dlg._model_picker_disabled_reason()]]

    for value in ("whisper_cpp", "cloud_stt", "google_cloud_stt", "nvidia_asr"):
        dlg._backend_display.set(VALUE_TO_LABEL[value])
        dlg._sync_engine_sections()
        states[f"nav:{value}"] = _rows(visible_texts(dlg._nav_frame))
        states[f"model_combo_tooltip:{value}"] = [["reason", dlg._model_picker_disabled_reason()]]
    for value in ("cloud_stt", "google_cloud_stt"):
        frame = dlg._engine_setup_frames[value]
        frame.toggle()
        states[f"header_open:{value}"] = [["header", str(frame.header.cget("text"))]]
        frame.toggle()
    dlg._toggle_vad_sliders()
    states["fine_tune_open"] = [["link", str(dlg._vad_tune_link.cget("text"))]]
    dlg._toggle_vad_sliders()

    info = h.new_toplevel(dlg, dlg._show_model_info)
    states["model_info"] = _rows(visible_texts(info))
    info.destroy()
    h.mp.setattr(h.adv, "catalog_entry_info",
                 lambda _cfg, _slug: {"label": "Bare", "info": "", "approx_size_gb": 0})
    info = h.new_toplevel(dlg, dlg._show_model_info)
    states["model_info_bare"] = _rows(visible_texts(info))
    info.destroy()
    help_top = h.new_toplevel(dlg, dlg._show_gcloud_help)
    states["gcloud_help"] = _rows(visible_texts(help_top))
    help_top.destroy()

    # Gemini key test: no key, a failing check, a passing check.
    cloud_writes = _var_writes(dlg._cloud_test_result)
    dlg._cloud_api_key.set("")
    dlg._test_cloud_key()

    class _Cloud:
        result: Any = (True, "core says fine")

        def __init__(self, config: Any) -> None:
            pass

        def load(self) -> None:
            pass

        def ping_key(self) -> Any:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    h.mp.setattr(cloud_stt, "CloudSttBackend", _Cloud)
    dlg._cloud_api_key.set("dummy-credential-A")
    dlg._test_cloud_key()
    _Cloud.result = (False, "core says no")
    dlg._test_cloud_key()
    _Cloud.result = RuntimeError("boom")
    dlg._test_cloud_key()
    states["gemini_key_test"] = [["status", t] for t in cloud_writes]

    # Google Cloud connection test: every branch.
    gc_writes = _var_writes(dlg._gcloud_test_result)
    h.mp.setattr(gcs, "bundled_credentials_path", lambda: "")
    dlg._gcloud_credentials.set("")
    dlg._test_gcloud_connection()
    dlg._gcloud_credentials.set("key.json")
    h.mp.setattr(gcs, "runtime_available", lambda: False)
    h.mp.setattr(optional_deps, "install", lambda *a, **k: False)
    h.mp.setattr(offline, "is_offline", lambda *a, **k: False)
    dlg._test_gcloud_connection()

    class _Gcs:
        load_ok = False
        client_error: Exception | None = None

        def __init__(self, config: Any) -> None:
            pass

        def load(self) -> bool:
            return self.load_ok

        def get_error(self) -> str:
            return "core error text"

        def _build_client(self) -> None:
            if self.client_error is not None:
                raise self.client_error

    h.mp.setattr(gcs, "runtime_available", lambda: True)
    h.mp.setattr(gcs, "GoogleCloudSttBackend", _Gcs)
    dlg._test_gcloud_connection()
    _Gcs.load_ok = True
    _Gcs.client_error = RuntimeError("client boom")
    dlg._test_gcloud_connection()
    _Gcs.client_error = None
    dlg._test_gcloud_connection()
    h.mp.setattr(gcs, "bundled_credentials_path", lambda: "bundled.json")
    dlg._gcloud_credentials.set("")
    dlg._test_gcloud_connection()

    def _broken(config: Any) -> Any:
        raise RuntimeError("ctor boom")

    h.mp.setattr(gcs, "GoogleCloudSttBackend", _broken)
    dlg._test_gcloud_connection()
    states["gcloud_connection_test"] = [["status", t] for t in gc_writes]

    h.mp.setattr(availability, "bundled_gcloud_key_path", lambda: "bundled.json")
    shown_bundled = dlg._gcloud_path_display()
    h.mp.setattr(availability, "bundled_gcloud_key_path", lambda: "")
    states["gcloud_path"] = [["bundled", shown_bundled], ["none", dlg._gcloud_path_display()]]

    usage_writes = _var_writes(dlg._gcloud_usage_text)
    import core.backends as backends_pkg
    h.mp.setitem(sys.modules, "core.backends.google_cloud_stt", None)
    h.mp.delattr(backends_pkg, "google_cloud_stt")
    dlg._refresh_gcloud_usage()  # the import fails: "Usage unavailable: ..."
    h.mp.setitem(sys.modules, "core.backends.google_cloud_stt", gcs)
    h.mp.setattr(backends_pkg, "google_cloud_stt", gcs, raising=False)
    states["gcloud_usage_unavailable"] = [["usage", t] for t in usage_writes]

    dlg._browse_subtitle_edit()
    dlg._browse_watched_folder()
    dlg._browse_gcloud_credentials()
    states["file_dialogs"] = list(h.file_dialogs)

    h.save_error = OSError("disk full")
    dlg._save_and_close()
    h.save_error = None
    states["save_failed"] = list(h.messageboxes)

    # Other build-time variants: no self-update, updater turned off by the environment.
    h.mp.setattr(ytu, "can_self_update", lambda *a, **k: False)
    h.mp.setattr(updates, "disabled_by_environment", lambda *a, **k: True)
    first = {t for _p, t in states["dialog"]}
    second = h.make()
    states["dialog_variant_texts"] = [["variant", t] for _p, t in visible_texts(second)
                                      if t not in first]

    # A model change asks before restarting a busy worker.
    labels = list(second.tk.splitlist(second._model_combo.cget("values")))
    current = second._model_display.get()
    second._model_display.set(next(lbl for lbl in labels if lbl != current))
    second._save_and_close()
    states["confirm_model_change"] = [["confirm", t] for t in (h.confirms[-1] if h.confirms else [])]
    return states


def test_capture_or_compare_english_texts(harness: _Harness) -> None:
    """English: every state shows exactly the texts captured before the conversion."""
    from app import i18n
    i18n.set_language("en")
    states = capture_states(harness)
    if _capturing():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(states, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert states == expected
