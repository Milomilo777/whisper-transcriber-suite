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


# --- the pseudo-locale --------------------------------------------------------------------------

# Texts the dialog shows that do not go through the translation layer, with the reason.
_NOT_OURS_REASONS = {
    "engine names": "the Engine picker's labels come from core.backends.availability (core/)",
    "cookie browsers": "the cookies picker's values come from app.domain.cookies (another file)",
    "format ids": "output format ids (SRT, VTT, ...) and product names (Express Scribe, InqScribe)",
    "video-site export": "the video-site team's export label and help stay English-only",
    "urls": "links show the URL itself",
    "core texts": "the model catalog's label/description and the usage line come from core/",
    "confirm action": "App._confirm_backend_switch splices this fragment into its own sentence",
}


def _not_ours() -> set[str]:
    from app.dialogs import advanced as adv
    from app.domain.cookies import cookie_browser_choices
    from core.backends.availability import ENGINE_CHOICES
    from core.writers import supported_formats

    texts = {label for label, _value in ENGINE_CHOICES}
    texts |= set(cookie_browser_choices(""))
    texts |= {name.upper() for name in supported_formats() if name not in adv._FORMAT_LABELS}
    texts |= {adv._FORMAT_LABELS[n] for n in adv._UNTRANSLATED_FORMAT_LABELS}
    texts.add(adv._FORMAT_HELP["smtv_docx"])
    texts |= {MODEL_INFO["label"], MODEL_INFO["info"], "Bare", CORE_USAGE}
    texts.add("action=Changing the model")
    return texts


def _flat_texts(states: dict[str, list[list[str]]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for state, rows in states.items():
        for row in rows:
            if state == "file_dialogs":
                out.append((state, row[0]))
                out.extend((state, label) for label, _pattern in json.loads(row[1]))
            elif state == "confirm_model_change" and not row[1].startswith("action="):
                out.append((state, row[1].split("=", 1)[1]))
            else:
                out.extend((state, t) for t in row[1:])
    return out


def test_pseudo_locale_leaves_no_dialog_text_untranslated(harness: _Harness) -> None:
    from app import i18n
    from tests.app.i18n_walk import is_pseudo_marked

    try:
        assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
        states = capture_states(harness)
    finally:
        i18n.set_language("en")
    allowed = _not_ours()
    left = sorted({(state, t) for state, t in _flat_texts(states)
                   if t.strip() and not is_pseudo_marked(t) and t not in allowed
                   and not t.startswith("https://")})
    assert left == []
    # Placeholder values survive inside the marked text.
    assert any("core says fine" in t for _s, t in _flat_texts(states))


def _pick_and_save(h: _Harness, language: str) -> dict[str, Any]:
    """Pick the 2nd LLM provider, the 4th denoise strength and the 2nd model by POSITION, save."""
    from app import i18n
    from app.dialogs import advanced as adv

    i18n.set_language(language)
    try:
        dlg = h.make(llm_provider="local", denoise_level="auto", denoise_enabled=True)
        dlg._llm_provider_display.set(adv._llm_provider_labels()[1])
        dlg._sync_llm_provider_rows()
        dlg._denoise_level_combo.current(3)
        dlg._on_denoise_level_selected()
        dlg._model_combo.current(1)
        h.saved.clear()
        dlg._save_and_close()
        assert len(h.saved) == 1
        return h.saved[0]
    finally:
        i18n.set_language("en")


def test_saving_in_the_pseudo_locale_writes_the_same_config(harness: _Harness) -> None:
    english = _pick_and_save(harness, "en")
    pseudo = _pick_and_save(harness, "qps-ploc")
    assert english["llm_provider"] == "remote"
    assert english["denoise_level"] == "strong"
    assert english == pseudo


def test_denoise_picker_shows_labels_and_keeps_stored_values(harness: _Harness) -> None:
    from app import i18n
    from app.dialogs import advanced as adv
    from tests.app.i18n_walk import is_pseudo_marked

    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        dlg = harness.make(denoise_level="light", denoise_enabled=True)
        shown = dlg._denoise_level_display.get()
        assert is_pseudo_marked(shown) and dlg._denoise_level.get() == "light"
        dlg._apply_noisy_audio_preset()  # stores "medium"
        assert dlg._denoise_level.get() == "medium"
        assert dlg._denoise_level_display.get() == adv._denoise_level_labels()["medium"]
        dlg._restore_transcription_defaults()
        assert dlg._denoise_level.get() == "auto"
        assert dlg._denoise_level_display.get() == adv._denoise_level_labels()["auto"]
    finally:
        i18n.set_language("en")


# --- windowless (no Tk root): the label <-> value maps ---------------------------------------

@pytest.fixture
def pseudo():
    from app import i18n
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        yield
    finally:
        i18n.set_language("en")


def test_windowless_llm_provider_labels_map_back_to_stored_values(pseudo: None) -> None:
    from app.dialogs import advanced as adv
    from tests.app.i18n_walk import is_pseudo_marked

    labels = adv._llm_provider_labels()
    assert all(is_pseudo_marked(label) for label in labels)
    for (english, value), shown in zip(adv._LLM_PROVIDER_CHOICES, labels):
        assert adv._llm_provider_value(shown) == value
        assert adv._llm_provider_value(english) == value  # an English label still maps
        assert adv._llm_provider_label(value) == shown
    assert adv._llm_provider_value("something else") == "local"


def test_windowless_denoise_labels_map_back_to_stored_values(pseudo: None) -> None:
    from app.dialogs import advanced as adv
    from tests.app.i18n_walk import is_pseudo_marked

    labels = adv._denoise_level_labels()
    assert list(labels) == list(adv._DENOISE_LEVELS)
    for value, shown in labels.items():
        assert is_pseudo_marked(shown)
        assert adv._denoise_level_value(shown) == value
        assert adv._denoise_level_value(value) == value
    assert adv._denoise_level_value("extreme") == "extreme"  # a hand-edited value survives


def test_windowless_format_labels(pseudo: None) -> None:
    from app.dialogs import advanced as adv
    from tests.app.i18n_walk import is_pseudo_marked

    assert is_pseudo_marked(adv._format_label("ass"))
    assert adv._format_label("srt") == "SRT"
    assert adv._format_label("smtv_docx") == adv._FORMAT_LABELS["smtv_docx"]
    assert adv._format_label("inqscribe") == "InqScribe"
    assert is_pseudo_marked(adv._format_help("srt"))
    assert adv._format_help("smtv_docx") == adv._FORMAT_HELP["smtv_docx"]
    assert is_pseudo_marked(adv._model_choice_label("Tiny (~75 MB)", True))


class _V:
    """A Tk variable stand-in: .get()/.set() on one slot."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


def _fake_dialog(app: Any, provider_label: str) -> types.SimpleNamespace:
    """What _save_and_close reads, as plain objects (see tests/core/test_advanced_simplified.py)."""
    return types.SimpleNamespace(
        app=app, _vad_enabled=_V(True), _vad_min_silence=_V(500), _vad_threshold=_V(0.5),
        _vad_speech_pad=_V(400), _format_vars={"srt": _V(True)}, _reset_hidden_tuning=False,
        _initial_prompt=_V(""), _hotwords=_V(""), _sb_vars={}, _cookies_browser=_V("(off)"),
        _cookies_browser_initial="(off)", _backend_display=_V("Faster-Whisper — offline, default"),
        _cloud_api_key=_V(""), _cloud_model=_V("gemini-3.5-flash"), _gcloud_credentials=_V(""),
        _gcloud_batch_mode=_V(False), _gcloud_bucket=_V(""), _gcloud_diarization=_V(False),
        _nvidia_model_id=_V(""), _alignment_enabled=_V(False), _hallucination_detect=_V(True),
        _demucs_enabled=_V(False), _denoise_enabled=_V(True), _denoise_level=_V("strong"),
        _ai_enabled=_V(True), _llm_provider_display=_V(provider_label),
        _llm_remote_base_url=_V("https://api.openai.com/v1"), _llm_remote_api_key=_V(""),
        _llm_remote_model=_V(""), _auto_chapters_enabled=_V(True), _model_display=_V("Large-v3"),
        _model_label_to_slug={"Large-v3": "large-v3"}, _telemetry_opt_in=_V(False),
        _work_offline=_V(False), _update_check_enabled=_V(True), _yt_dlp_update_mode=_V("ask"),
        _caption_choice_var=_V("ask"), _minimise_to_tray=_V(False), _tts_no_text_limit=_V(False),
        _subtitle_edit_path=_V(""), _watched_folder=_V(""), _watched_folder_enabled=_V(False),
        _sync_vad_controls_state=lambda: None, _sync_denoise_level_state=lambda: None,
        _teardown_mousewheel=lambda: None, destroy=lambda: None,
    )


def test_windowless_save_writes_the_same_config_in_every_language(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from app import i18n
    from app.dialogs import advanced as adv

    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(adv, "save_config", lambda cfg: saved.append(dict(cfg)))

    def save(language: str) -> dict[str, Any]:
        i18n.set_language(language)
        try:
            cfg = {"whisper_model": "large-v3", "transcribe_backend": "faster_whisper"}
            app = types.SimpleNamespace(
                app_config=cfg, log=lambda _m: None,
                transcription_service=types.SimpleNamespace(stop_all=lambda: None))
            adv.AdvancedDialog._save_and_close(  # type: ignore[arg-type]
                _fake_dialog(app, adv._llm_provider_labels()[1]))
            return saved[-1]
        finally:
            i18n.set_language("en")

    english = save("en")
    assert english["llm_provider"] == "remote" and english["denoise_level"] == "strong"
    assert save(i18n.PSEUDO_LOCALE) == english


def test_windowless_video_site_texts_never_reach_the_catalog() -> None:
    catalog = (Path(__file__).resolve().parents[2] / "app" / "locales" / "en.json").read_text(
        encoding="utf-8")
    for word in ("SMTV", "Supreme Master", "suprememastertv"):
        assert word not in catalog
