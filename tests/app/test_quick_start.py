"""Quick start window (app.dialogs.quick_start) and its wiring into the app.

Covers: shown once on a new install, never for an existing config, Skip keeps today's
behaviour, the chosen model and folder are saved, and nothing touches the network while
the window is open. Config tests use an isolated config folder under tmp_path.
"""
from __future__ import annotations

import json
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.dialogs import quick_start as qs
from core import config as cfg
from core import hardware as hw
from core import hub
from core.model_manager import DEFAULT_MODEL_SLUG, MODEL_REGISTRY

_CPU = hw.CudaStatus(usable=False, gpu_present=False)
_GPU = hw.CudaStatus(usable=True, gpu_present=True, gpu_name="NVIDIA Test GPU", memory_mb=8192)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point every app folder at tmp_path; returns the config.json path."""
    for kind in ("config", "cache", "log", "data"):
        folder = tmp_path / kind
        folder.mkdir()
        monkeypatch.setattr(cfg, f"user_{kind}_dir", lambda folder=folder: folder)
    path = tmp_path / "config" / "config.json"
    monkeypatch.setattr(cfg, "config_path", lambda: str(path))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))
    return path


def _load():
    return cfg.load_config(fetch_online=False)


# ------------------------------------------------------------ shown once

def test_new_install_shows_the_window(isolated_config):
    assert not isolated_config.exists()
    config = _load()
    assert config["quick_start_done"] is False
    assert qs.should_show(config)


def test_existing_config_from_an_older_version_never_shows_it(isolated_config):
    isolated_config.write_text(json.dumps({"theme": "dark", "hub_folder": ""}), encoding="utf-8")
    config = _load()
    assert config["quick_start_done"] is True
    assert not qs.should_show(config)


def test_an_unreadable_config_counts_as_an_existing_install(isolated_config):
    isolated_config.write_bytes(b'{"theme": "dark", "hub_fol')  # truncated
    assert not qs.should_show(_load())
    assert isolated_config.with_name("config.json.corrupt").exists()


def test_a_deleted_config_is_a_fresh_start(isolated_config):
    cfg.save_config(_load())
    cfg.save_config(_load())  # leaves config.json.bak behind
    isolated_config.unlink()
    assert isolated_config.with_name("config.json.bak").exists()
    assert qs.should_show(_load())


def test_a_new_user_who_closed_the_app_before_deciding_sees_it_again(isolated_config):
    cfg.save_config(_load())  # e.g. the window geometry saved on exit
    assert json.loads(isolated_config.read_text(encoding="utf-8"))["quick_start_done"] is False
    assert qs.should_show(_load())


@pytest.mark.parametrize("finish", [False, True])
def test_never_shows_again_after_skip_or_finish(isolated_config, tmp_path, finish):
    config = _load()
    choice = qs.QuickStartChoice("fa", "fast", str(tmp_path / "out")) if finish else None
    qs.apply_choice(config, choice)
    cfg.save_config(config)
    assert not qs.should_show(_load())


def test_config_switch_turns_it_off(isolated_config):
    isolated_config.write_text(
        json.dumps({"quick_start_enabled": False, "quick_start_done": False}), encoding="utf-8",
    )
    assert not qs.should_show(_load())


@pytest.mark.parametrize(
    "enabled, done, shown",
    [(True, False, True), (True, True, False), (False, False, False), (False, True, False)],
)
def test_should_show_truth_table(enabled, done, shown):
    assert qs.should_show({"quick_start_enabled": enabled, "quick_start_done": done}) is shown


def test_a_config_without_the_keys_is_not_a_new_install():
    assert not qs.should_show({})


# ------------------------------------------------------------ outcomes

def test_skip_changes_nothing_but_the_done_flag(isolated_config):
    config = _load()
    before = json.loads(json.dumps(config))
    qs.apply_choice(config, None)
    assert config.pop("quick_start_done") is True
    before.pop("quick_start_done")
    assert config == before
    assert config["whisper_model"] == DEFAULT_MODEL_SLUG and config["hub_folder"] == ""


@pytest.mark.parametrize(
    "language, mode, slug",
    [("fa", "fast", "small"), ("fa", "best", "large-v3"), ("es", "best", "large-v3-turbo"),
     ("en", "fast", "small"), ("", "best", DEFAULT_MODEL_SLUG)],
)
def test_finish_saves_the_chosen_model_and_folder(isolated_config, tmp_path, language, mode, slug):
    config = _load()
    out = str(tmp_path / "out")
    qs.apply_choice(config, qs.QuickStartChoice(language, mode, out))
    cfg.save_config(config)
    saved = _load()
    assert saved["whisper_model"] == slug
    assert saved["model"]["name"] == MODEL_REGISTRY[slug]["name"]
    assert saved["download_folder"] == out
    assert saved["hub_folder"] == hub.normalise_hub_path(str(hub.default_hub_folder()))
    assert saved["model_path"].endswith(MODEL_REGISTRY[slug]["name"])
    assert not qs.should_show(saved)


def test_finish_keeps_a_model_folder_that_is_already_set(tmp_path):
    config = {"hub_folder": str(tmp_path / "hub"), "whisper_model": "large-v3"}
    qs.apply_choice(config, qs.QuickStartChoice("fa", "fast", str(tmp_path)))
    assert config["hub_folder"] == str(tmp_path / "hub")


def test_a_model_missing_from_the_catalog_keeps_the_current_one(tmp_path, monkeypatch):
    import core.model_manager as mm

    monkeypatch.setattr(mm, "catalog_resolve_entry", lambda c, s: None)
    config = {"whisper_model": "large-v3", "model": {"name": "x"}, "model_path": "keep"}
    qs.apply_choice(config, qs.QuickStartChoice("fa", "fast", str(tmp_path)))
    assert (config["whisper_model"], config["model_path"]) == ("large-v3", "keep")
    assert config["download_folder"] == str(tmp_path)


# ------------------------------------------------------------ helpers

def test_language_options():
    options = qs.language_options()
    assert options[0] == (qs.AUTO_LANGUAGE_LABEL, "")
    codes = dict(options)
    assert codes["Persian"] == "fa"
    assert codes["Chinese (Simplified)"] == "zh" and codes["Chinese (Traditional)"] == "zh"
    assert all(code for _label, code in options[1:])
    assert len({label for label, _code in options}) == len(options)


@pytest.mark.parametrize(
    "seconds, text",
    [(4.8, "under 10 seconds"), (28.2, "about 30 seconds"), (85.2, "about 1 min 30 s"),
     (134.4, "about 2 min 15 s"), (120.0, "about 2 min"), (57.4, "about 55 seconds"),
     (57.6, "about 1 min"), (59.0, "about 1 min")],
)
def test_format_per_minute(seconds, text):
    assert qs.format_per_minute(seconds) == text


def test_default_output_folder_prefers_the_saved_one(tmp_path):
    assert qs.default_output_folder({"download_folder": str(tmp_path)}) == str(tmp_path)
    assert qs.default_output_folder({"download_folder": ""})


# ------------------------------------------------------------ estimates

def test_cpu_estimate_uses_the_benchmark_speed():
    est = hw.estimate_seconds_per_audio_minute("large-v3", _CPU, physical_cores=4)
    assert est is not None
    assert est == pytest.approx(60 * hw.CPU_SECONDS_PER_AUDIO_SECOND["large-v3"])
    assert hw.estimate_seconds_per_audio_minute("large-v3", _CPU, physical_cores=8) == est
    assert hw.estimate_seconds_per_audio_minute("large-v3", _CPU, physical_cores=0) == est
    assert hw.estimate_seconds_per_audio_minute("large-v3", _CPU, physical_cores=2) == (
        pytest.approx(2 * est))


def test_small_is_faster_than_large_everywhere():
    for status in (_CPU, _GPU):
        small = hw.estimate_seconds_per_audio_minute("small", status, physical_cores=4)
        large = hw.estimate_seconds_per_audio_minute("large-v3", status, physical_cores=4)
        assert small is not None and large is not None and small < large


def test_gpu_estimate_follows_the_published_figure():
    est = hw.estimate_seconds_per_audio_minute("large-v3", _GPU, physical_cores=2)
    assert est == pytest.approx(60 * 63 / 780)


@pytest.mark.parametrize(
    "memory_mb, on_gpu",
    [(0, {"small", "large-v3-turbo", "large-v3"}), (2048, {"small"}),
     (4096, {"small", "large-v3-turbo"}), (8192, {"small", "large-v3-turbo", "large-v3"})],
)
def test_a_model_too_big_for_the_gpu_memory_gets_the_cpu_time(memory_mb, on_gpu):
    gpu = hw.CudaStatus(usable=True, gpu_present=True, memory_mb=memory_mb)
    for slug in ("small", "large-v3-turbo", "large-v3"):
        cpu = hw.estimate_seconds_per_audio_minute(slug, _CPU, physical_cores=4)
        est = hw.estimate_seconds_per_audio_minute(slug, gpu, physical_cores=4)
        assert hw.runs_on_gpu(slug, gpu) is (slug in on_gpu)
        assert (est != cpu) is (slug in on_gpu), slug


def test_unknown_model_has_no_estimate():
    assert hw.estimate_seconds_per_audio_minute("distil-large-v3", _CPU, physical_cores=4) is None


# ------------------------------------------------------------ the window

@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _pump(root, until, timeout=60.0):
    deadline = time.monotonic() + timeout
    while not until():
        assert time.monotonic() < deadline, "timed out waiting for the window"
        root.update()
        time.sleep(0.02)


def _open(root, config, probe=lambda: (_CPU, 4)):
    results: list = []
    dialog = qs.QuickStartDialog(root, config, on_done=results.append, probe=probe)
    _pump(root, lambda: dialog._hardware is not None)
    return dialog, results


def test_window_shows_sizes_and_times_and_follows_the_language(tk_root, tmp_path):
    dialog, _results = _open(tk_root, {"download_folder": str(tmp_path)})
    fast, best = dialog.mode_detail_vars["fast"].get(), dialog.mode_detail_vars["best"].get()
    assert fast == "Small · about 500 MB download · about 30 seconds per minute of audio"
    assert best == "Large v3 · about 3 GB download · about 2 min 15 s per minute of audio"
    assert "4-core processor" in dialog.hardware_var.get()
    dialog.language_var.set("Spanish")
    dialog.language_combo.event_generate("<<ComboboxSelected>>")
    tk_root.update()
    assert dialog.mode_detail_vars["best"].get().startswith("Large v3 Turbo · about 1.6 GB")
    shown = [str(w.cget("text")) for w in _all_widgets(dialog) if "text" in w.keys()]
    shown += [dialog.hardware_var.get()] + [v.get() for v in dialog.mode_detail_vars.values()]
    text = " ".join(shown).lower()
    assert "Speed or quality".lower() in text  # the scan sees the window's words
    assert "statistic" not in text and "usage" not in text
    dialog.skip()


def _all_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _all_widgets(child)


def test_finish_returns_the_choice_and_creates_the_folder(tk_root, tmp_path):
    out = tmp_path / "new" / "folder"
    dialog, results = _open(tk_root, {"download_folder": str(out)})
    dialog.language_var.set("Persian")
    dialog.mode_var.set("best")
    dialog.finish()
    assert results == [qs.QuickStartChoice("fa", "best", str(out))]
    assert results[0].model_slug == "large-v3"
    assert out.is_dir()
    assert not dialog.winfo_exists()


@pytest.mark.parametrize("how", ["skip", "close"])
def test_skip_and_closing_return_none_once(tk_root, tmp_path, how):
    dialog, results = _open(tk_root, {"download_folder": str(tmp_path)})
    if how == "skip":
        dialog.skip()
    else:
        tk_root.eval(dialog.protocol("WM_DELETE_WINDOW"))
    dialog.skip()  # a second close does nothing
    assert results == [None]


def test_finish_without_a_folder_keeps_the_window_open(tk_root, monkeypatch):
    warnings: list = []
    monkeypatch.setattr(qs.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
    dialog, results = _open(tk_root, {})
    dialog.folder_var.set("   ")
    dialog.finish()
    assert results == [] and len(warnings) == 1 and dialog.winfo_exists()
    dialog.skip()


def test_a_relative_folder_is_made_absolute(tk_root, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dialog, results = _open(tk_root, {})
    dialog.folder_var.set("rel_out")
    dialog.finish()
    assert results[0].output_folder == str(tmp_path / "rel_out")
    assert (tmp_path / "rel_out").is_dir()


def test_an_impossible_folder_name_keeps_the_window_open(tk_root, monkeypatch):
    warnings: list = []
    monkeypatch.setattr(qs.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
    dialog, results = _open(tk_root, {})
    dialog.folder_var.set("bad\x00name")
    dialog.finish()
    assert results == [] and len(warnings) == 1 and dialog.winfo_exists()
    dialog.skip()


def test_a_failing_window_leaves_nothing_behind(tk_root, monkeypatch):
    def broken():
        raise RuntimeError("no languages")

    monkeypatch.setattr(qs, "language_options", broken)
    with pytest.raises(RuntimeError):
        qs.QuickStartDialog(tk_root, {}, on_done=lambda c: None, probe=lambda: (_CPU, 4))
    tk_root.update()
    assert tk_root.winfo_children() == []


def test_hardware_check_failure_still_lets_the_user_finish(tk_root, tmp_path):
    def broken():
        raise RuntimeError("no GPU check")

    results: list = []
    dialog = qs.QuickStartDialog(
        tk_root, {"download_folder": str(tmp_path)}, on_done=results.append, probe=broken,
    )
    _pump(tk_root, lambda: "Could not check" in dialog.hardware_var.get())
    assert "per minute" not in dialog.mode_detail_vars["fast"].get()
    dialog.finish()
    assert results == [qs.QuickStartChoice("", "fast", str(tmp_path))]


def test_no_network_call_while_the_window_is_open(tk_root, tmp_path, monkeypatch):
    """Real hardware probe, every choice changed, then Finish: no socket is opened and
    no model download starts."""
    import core.model_manager as mm

    attempts: list = []

    def refuse(*args, **kwargs):
        attempts.append(args[:2])
        raise OSError("network call during the quick start window")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(mm, "ensure_model", refuse)

    results: list = []
    dialog = qs.QuickStartDialog(
        tk_root, {"download_folder": str(tmp_path)}, on_done=results.append,
    )
    _pump(tk_root, lambda: dialog._hardware is not None or "Could not" in dialog.hardware_var.get())
    for label in ("Persian", "English", qs.AUTO_LANGUAGE_LABEL, "Japanese"):
        dialog.language_var.set(label)
        dialog.language_combo.event_generate("<<ComboboxSelected>>")
        tk_root.update()
    dialog.mode_var.set("best")
    dialog.finish()
    assert results and results[0].language == "ja"
    assert attempts == []


# ------------------------------------------------------------ app wiring

def test_app_start_opens_the_window_for_a_new_install(monkeypatch):
    import app.app as app_mod

    opened = MagicMock()
    monkeypatch.setattr(app_mod, "QuickStartDialog", opened)
    fake = SimpleNamespace(
        app_config={"quick_start_enabled": True, "quick_start_done": False},
        _ensure_hub_folder=MagicMock(), _on_quick_start_done=MagicMock(),
        _quick_start_open=False,
    )
    app_mod.App._on_start(fake)  # type: ignore[arg-type]
    assert opened.call_count == 1 and fake._quick_start_open is True
    fake._ensure_hub_folder.assert_not_called()


def test_app_start_falls_back_to_the_old_path_when_the_window_fails(monkeypatch):
    import app.app as app_mod

    monkeypatch.setattr(app_mod, "QuickStartDialog", MagicMock(side_effect=RuntimeError("x")))
    fake = SimpleNamespace(
        app_config={"quick_start_enabled": True, "quick_start_done": False},
        _ensure_hub_folder=MagicMock(), _on_quick_start_done=MagicMock(),
        _quick_start_open=False,
    )
    app_mod.App._on_start(fake)  # type: ignore[arg-type]
    fake._ensure_hub_folder.assert_called_once()
    assert fake._quick_start_open is False


def test_app_start_skips_the_window_for_an_existing_user(monkeypatch):
    import app.app as app_mod

    opened = MagicMock()
    monkeypatch.setattr(app_mod, "QuickStartDialog", opened)
    fake = SimpleNamespace(
        app_config={"quick_start_enabled": True, "quick_start_done": True},
        _ensure_hub_folder=MagicMock(), _quick_start_open=False,
    )
    app_mod.App._on_start(fake)  # type: ignore[arg-type]
    opened.assert_not_called()
    fake._ensure_hub_folder.assert_called_once()


def _fake_app(monkeypatch, tmp_path):
    import app.app as app_mod

    saved: list = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(json.loads(json.dumps(c))))
    fake = SimpleNamespace(
        app_config={"quick_start_done": False, "hub_folder": "", "whisper_model": "large-v3",
                    "download_folder": ""},
        _quick_start_open=True, _ensure_hub_folder=MagicMock(),
        _refresh_model_selector=MagicMock(), log=MagicMock(),
        download_folder_var=MagicMock(),
    )
    return app_mod, fake, saved


def test_app_skip_saves_done_then_runs_todays_model_folder_picker(monkeypatch, tmp_path):
    app_mod, fake, saved = _fake_app(monkeypatch, tmp_path)
    app_mod.App._on_quick_start_done(fake, None)  # type: ignore[arg-type]
    assert saved and saved[-1]["quick_start_done"] is True
    assert saved[-1]["whisper_model"] == "large-v3"
    fake._ensure_hub_folder.assert_called_once()
    assert fake._quick_start_open is False


def test_app_finish_saves_before_updating_the_widgets(monkeypatch, tmp_path):
    app_mod, fake, saved = _fake_app(monkeypatch, tmp_path)
    order: list = []
    fake._refresh_model_selector.side_effect = lambda: order.append("ui")
    monkeypatch.setattr(app_mod, "save_config", lambda c: (order.append("save"), saved.append(dict(c))))
    app_mod.App._on_quick_start_done(  # type: ignore[arg-type]
        fake, qs.QuickStartChoice("fa", "fast", str(tmp_path)),
    )
    assert order == ["save", "ui"]
    assert saved[-1]["whisper_model"] == "small" and saved[-1]["quick_start_done"] is True
    fake.download_folder_var.set.assert_called_once_with(str(tmp_path))
    fake._ensure_hub_folder.assert_not_called()


def test_update_check_waits_until_the_window_has_closed():
    import app.app as app_mod

    fake = SimpleNamespace(
        _closing=False, _quick_start_open=True, after=MagicMock(),
        _run_update_check=MagicMock(), app_config={"update_check_enabled": True},
        _maybe_quiet_update_check=MagicMock(),
    )
    app_mod.App._maybe_quiet_update_check(fake)  # type: ignore[arg-type]
    fake.after.assert_called_once_with(4000, fake._maybe_quiet_update_check)
    fake._run_update_check.assert_not_called()
