"""Headless first-run persistence, model disclosure and dismiss recovery."""
from copy import deepcopy
from functools import partial
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app import app as app_mod
from app.dialogs import quick_start as qs
from core import config as cfgmod
from core import language_models as lm


class Var:
    def __init__(self, master=None, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def trace_add(self, *args):
        pass


def host(tmp_path):
    return NS(app_config={"quick_start_done": False, "whisper_model": "large-v3",
              "transcribe_backend": lm.ENGINE_WHISPER, "hub_folder": str(tmp_path / "models"),
              "download_folder": "old", "nested": {"unchanged": True}},
              _quick_start_open=True, _ensure_hub_folder=MagicMock(),
              _refresh_model_selector=MagicMock(), _refresh_engine_selector=MagicMock(),
              _refresh_language_model_hint=MagicMock(), log=MagicMock())


def fail_save(_config):
    raise OSError("synthetic config write failure")


def dialog(tmp_path, on_done):
    result = NS(_closed=False, _poll_id="original-poll", _on_done=on_done,
                _poll=MagicMock(), after=MagicMock(return_value="retry-poll"),
                after_cancel=MagicMock(), grab_release=MagicMock(), grab_set=MagicMock(),
                destroy=MagicMock(), _on_try_sample=MagicMock(),
                choice=lambda: qs.QuickStartChoice("fa", "best", str(tmp_path), ram_gb=16))
    result._close = partial(qs.QuickStartDialog._close, result)
    result.skip = partial(qs.QuickStartDialog.skip, result)
    if hasattr(qs.QuickStartDialog, "dismiss"):
        result.dismiss = partial(qs.QuickStartDialog.dismiss, result)
    return result


def test_finish_save_failure_is_atomic_and_retryable(monkeypatch, tmp_path):
    current = host(tmp_path); before = deepcopy(current.app_config)
    monkeypatch.setattr(app_mod, "save_config", fail_save)
    accepted = app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("fa", "best", str(tmp_path)))
    assert accepted is False
    assert current.app_config == before
    assert current._quick_start_open is True
    current._refresh_model_selector.assert_not_called()
    assert not any(str(call.args[0]).startswith("Quick start: model") for call in current.log.call_args_list)


def test_partial_choice_failure_does_not_change_live_config(monkeypatch, tmp_path):
    current = host(tmp_path); before = deepcopy(current.app_config)
    def broken(candidate, choice):
        candidate["nested"]["unchanged"] = False
        candidate["quick_start_done"] = True
        raise ValueError("synthetic choice failure after mutation")
    monkeypatch.setattr(app_mod, "apply_choice", broken)
    save = MagicMock(); monkeypatch.setattr(app_mod, "save_config", save)
    assert app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("fa", "best", str(tmp_path))) is False
    assert current.app_config == before
    save.assert_not_called()


def test_failed_persian_best_then_spanish_fast_keeps_whisper(monkeypatch, tmp_path):
    current = host(tmp_path); original = current.app_config
    monkeypatch.setattr(app_mod, "save_config", fail_save)
    assert app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("fa", "best", str(tmp_path))) is False
    saved = []; monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(deepcopy(c)))
    assert app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("es", "fast", str(tmp_path))) is True
    assert current.app_config is original
    assert current.app_config["transcribe_backend"] == lm.ENGINE_WHISPER
    assert not current.app_config.get("nvidia_asr_model_id")
    assert saved[-1] == current.app_config


def test_finish_does_not_destroy_or_try_sample_after_save_failure(monkeypatch, tmp_path):
    current = host(tmp_path); before = deepcopy(current.app_config)
    monkeypatch.setattr(app_mod, "save_config", fail_save)
    warning = MagicMock(); monkeypatch.setattr(qs.messagebox, "showwarning", warning)
    fake = dialog(tmp_path, lambda choice: app_mod.App._on_quick_start_done(current, choice))
    qs.QuickStartDialog.finish(fake, try_sample=True)
    assert current.app_config == before
    assert fake._closed is False
    fake.destroy.assert_not_called()
    fake._on_try_sample.assert_not_called()
    fake.grab_set.assert_called_once()
    assert fake._poll_id == "retry-poll"
    warning.assert_called_once()


def test_skip_can_continue_when_config_is_unwritable(monkeypatch, tmp_path):
    current = host(tmp_path); before = deepcopy(current.app_config)
    monkeypatch.setattr(app_mod, "save_config", fail_save)
    assert app_mod.App._on_quick_start_done(current, None) is True
    assert current.app_config == before
    assert current._quick_start_open is False
    current._ensure_hub_folder.assert_called_once()


def details(language, ram_gb=16):
    return NS(language_code=lambda: language, _ram_gb=ram_gb, _config={}, _hardware=None,
              language_var=Var(value="Persian" if language == "fa" else "Spanish"),
              language_model_note_var=Var(),
              mode_detail_vars={m: Var() for m, _ in qs.MODES}, _refresh_try_button=MagicMock())


def test_best_quality_discloses_language_and_engine_feature_limits(monkeypatch):
    monkeypatch.setattr(qs, "short_model_name", lambda *args: "Whisper")
    state = details("fa")
    qs.QuickStartDialog._refresh_details(state)
    note = state.language_model_note_var.get()
    assert lm.LANGUAGE_MODELS["fa"].name in note and "Persian only" in note
    assert "transformers" in note and "1 GB" in note
    assert "no word-level timestamps" in note and "hot words, prompt" in note


@pytest.mark.parametrize("language,ram", [("es", 16), ("fa", 4)])
def test_whisper_choices_have_no_one_language_warning(monkeypatch, language, ram):
    monkeypatch.setattr(qs, "short_model_name", lambda *args: "Whisper")
    state = details(language, ram)
    qs.QuickStartDialog._refresh_details(state)
    assert state.language_model_note_var.get() == ""


@pytest.mark.parametrize("action", ["close", "escape"])
def test_close_and_escape_leave_first_run_available(monkeypatch, tmp_path, action):
    current = host(tmp_path); before = deepcopy(current.app_config)
    save = MagicMock(); monkeypatch.setattr(app_mod, "save_config", save)
    fake = dialog(tmp_path, lambda choice: app_mod.App._on_quick_start_done(current, choice))
    bindings = {}; protocols = {}
    for name in ("title", "transient", "resizable", "_build", "_refresh_details", "update_idletasks", "_center_on", "_check", "_refresh_try_button"):
        setattr(fake, name, MagicMock())
    fake.protocol = lambda name, callback: protocols.setdefault(name, callback)
    fake.bind = lambda name, callback: bindings.setdefault(name, callback)
    monkeypatch.setattr(qs.tk, "StringVar", Var)
    monkeypatch.setattr(qs.threading, "Thread", lambda **kwargs: NS(start=lambda: None))
    qs.QuickStartDialog._open_window(fake, NS(), current.app_config, fake._on_done, lambda: None)
    if action == "close":
        protocols["WM_DELETE_WINDOW"]()
    else:
        bindings["<Escape>"](None)
    assert qs.should_show(current.app_config)
    assert current.app_config == before
    save.assert_not_called()
    assert current._quick_start_open is False
    current._ensure_hub_folder.assert_called_once()


def test_explicit_skip_is_still_persistent(monkeypatch, tmp_path):
    current = host(tmp_path); saved = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(deepcopy(c)))
    fake = dialog(tmp_path, lambda choice: app_mod.App._on_quick_start_done(current, choice))
    qs.QuickStartDialog.skip(fake)
    assert saved[-1]["quick_start_done"] is True
    assert not qs.should_show(current.app_config)
    fake.destroy.assert_called_once()


def test_legacy_callback_returning_none_can_finish_and_try_sample(tmp_path):
    accepted = []
    fake = dialog(tmp_path, accepted.append)
    qs.QuickStartDialog.finish(fake, try_sample=True)
    assert len(accepted) == 1 and isinstance(accepted[0], qs.QuickStartChoice)
    fake.destroy.assert_called_once()
    fake._on_try_sample.assert_called_once()


@pytest.fixture
def real_loaded_config(monkeypatch, tmp_path):
    directory = tmp_path / "configuration"
    directory.mkdir()
    monkeypatch.setattr(cfgmod, "user_config_dir", lambda: directory)
    monkeypatch.setattr(cfgmod, "_legacy_config_path", lambda: str(tmp_path / "absent.json"))
    cfgmod._forget_last_good()
    loaded = cfgmod.load_config(fetch_online=False)
    loaded.update(quick_start_done=False, whisper_model="large-v3",
                  transcribe_backend=lm.ENGINE_WHISPER, download_folder=str(tmp_path / "old"))
    cfgmod.save_config(loaded)
    return loaded, directory / "config.json"


def test_successful_finish_preserves_loaded_config_merge_baseline(monkeypatch, tmp_path, real_loaded_config):
    import json

    loaded, path = real_loaded_config
    current = host(tmp_path)
    current.app_config = loaded
    monkeypatch.setattr(app_mod, "save_config", cfgmod.save_config)
    wizard_folder = str(tmp_path / "wizard")
    assert app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("es", "fast", wizard_folder)) is True
    assert current.app_config is loaded
    other = cfgmod.load_config(fetch_online=False)
    other.update(whisper_model="medium", download_folder=str(tmp_path / "other-instance"))
    cfgmod.save_config(other)
    new_theme = "dark" if loaded.get("theme") != "dark" else "light"
    loaded["theme"] = new_theme
    cfgmod.save_config(loaded)
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["whisper_model"] == "medium"
    assert disk["download_folder"] == str(tmp_path / "other-instance")
    assert disk["theme"] == new_theme


def test_real_save_failure_preserves_loaded_metadata_and_disk(monkeypatch, tmp_path, real_loaded_config):
    loaded, path = real_loaded_config
    current = host(tmp_path)
    current.app_config = loaded
    before = deepcopy(loaded)
    metadata = deepcopy(loaded.__dict__)
    disk = path.read_bytes()
    monkeypatch.setattr(app_mod, "save_config", cfgmod.save_config)
    monkeypatch.setattr(cfgmod, "_write_disk_dict", lambda *args: fail_save(None))
    assert app_mod.App._on_quick_start_done(current, qs.QuickStartChoice("es", "fast", str(tmp_path))) is False
    assert loaded == before
    assert loaded.__dict__ == metadata
    assert path.read_bytes() == disk
