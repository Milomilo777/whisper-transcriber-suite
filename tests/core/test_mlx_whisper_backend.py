"""Apple-silicon (MLX) engine: probes, auto-selection, model download, result mapping.

Windowless and hermetic: platform, imports, the MLX package and the Hugging Face
download are all faked, so these run on any OS. The real thing runs in the
``apple-silicon-engine.yml`` workflow on a GitHub arm64 macOS runner.
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

from core.backends import availability as eng
from core.backends import mlx_whisper_be as mlx

# --------------------------------------------------------------------- helpers


def _fake_platform(monkeypatch, system: str, machine: str) -> None:
    monkeypatch.setattr(mlx.platform, "system", lambda: system)
    monkeypatch.setattr(mlx.platform, "machine", lambda: machine)


def _usable(monkeypatch, *, installed: bool = True) -> None:
    """Pretend this is an M-series Mac with (or without) mlx-whisper on disk."""
    _fake_platform(monkeypatch, "Darwin", "arm64")
    monkeypatch.setattr(mlx, "package_installed", lambda: installed)


def _install_model(folder: Path, weights: str = "weights.safetensors") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / weights).write_bytes(b"x" * 16)


@pytest.fixture
def cfg(tmp_path):
    return {"whisper_model": "large-v3-turbo", "hub_folder": str(tmp_path / "hub")}


# ------------------------------------------------------------------- platform


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Darwin", "arm64", True),
        ("Darwin", "x86_64", False),  # Intel Mac, or Python under Rosetta
        ("Windows", "AMD64", False),
        ("Windows", "ARM64", False),
        ("Linux", "aarch64", False),
        ("Linux", "x86_64", False),
    ],
)
def test_only_native_arm64_macos_counts(system, machine, expected):
    assert mlx.is_apple_silicon(system, machine) is expected


def test_availability_reason_names_the_gap(monkeypatch):
    _fake_platform(monkeypatch, "Windows", "AMD64")
    assert "Apple silicon" in mlx.availability_reason()
    _usable(monkeypatch, installed=False)
    assert "not installed" in mlx.availability_reason()
    _usable(monkeypatch)
    monkeypatch.setattr(mlx, "package_importable", lambda: False)
    assert "could not be loaded" in mlx.availability_reason()
    monkeypatch.setattr(mlx, "package_importable", lambda: True)
    assert mlx.availability_reason() == ""


def test_is_available_never_true_off_apple_silicon(monkeypatch):
    _fake_platform(monkeypatch, "Windows", "AMD64")
    monkeypatch.setattr(mlx, "package_importable", lambda: True)
    assert mlx.is_available() is False


# --------------------------------------------------------------- model mapping


def test_every_mapped_slug_is_a_catalog_slug_and_a_hub_repo():
    from core.model_manager import _merged_catalog

    catalog = _merged_catalog({})
    for slug, (repo, size) in mlx.MODEL_REPOS.items():
        assert slug in catalog, slug
        assert repo.startswith("mlx-community/"), repo
        assert size > 0


def test_language_fine_tunes_have_no_mlx_twin(cfg):
    for slug in ("kotoba-whisper-v2.0", "kb-whisper-large-sv", "large-v1"):
        assert not mlx.supports_model({**cfg, "whisper_model": slug})
    assert mlx.supports_model(cfg)
    assert mlx.repo_for(cfg) == "mlx-community/whisper-large-v3-turbo"


def test_model_present_needs_config_and_weights(cfg):
    assert not mlx.model_present(cfg)
    folder = mlx.model_folder(cfg)
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    assert not mlx.model_present(cfg)  # no weights yet
    (folder / "weights.npz").write_bytes(b"")
    assert not mlx.model_present(cfg)  # empty weights
    (folder / "weights.npz").write_bytes(b"x")
    assert mlx.model_present(cfg)


# ------------------------------------------------------------- engine selection


def test_auto_select_on_apple_silicon(monkeypatch, cfg):
    _usable(monkeypatch)
    merged = {**cfg, "transcribe_backend": "faster_whisper", "apple_silicon_engine": True}
    baseline = dict(merged)
    mlx.resolve_engine_choice(merged, baseline)
    assert merged["transcribe_backend"] == "mlx_whisper"
    # The automatic pick is not a saved choice: the baseline follows it.
    assert baseline["transcribe_backend"] == "mlx_whisper"


def test_opt_out_keeps_faster_whisper(monkeypatch, cfg):
    _usable(monkeypatch)
    merged = {**cfg, "transcribe_backend": "faster_whisper", "apple_silicon_engine": False}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Windows", "AMD64"), ("Darwin", "x86_64"), ("Linux", "x86_64"), ("Linux", "aarch64")],
)
def test_other_systems_never_get_the_engine(monkeypatch, cfg, system, machine):
    _fake_platform(monkeypatch, system, machine)
    monkeypatch.setattr(mlx, "package_installed", lambda: True)
    merged = {**cfg, "transcribe_backend": "faster_whisper", "apple_silicon_engine": True}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"


def test_a_saved_mlx_choice_falls_back_where_it_cannot_run(monkeypatch, cfg):
    _fake_platform(monkeypatch, "Windows", "AMD64")  # config.json synced from a Mac
    merged = {**cfg, "transcribe_backend": "mlx_whisper", "apple_silicon_engine": True}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"


def test_package_missing_or_model_unmapped_keeps_faster_whisper(monkeypatch, cfg):
    _usable(monkeypatch, installed=False)
    merged = {**cfg, "transcribe_backend": "faster_whisper", "apple_silicon_engine": True}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"
    _usable(monkeypatch)
    merged = {**cfg, "whisper_model": "kotoba-whisper-v2.0",
              "transcribe_backend": "faster_whisper", "apple_silicon_engine": True}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"


@pytest.mark.parametrize("chosen", ["whisper_cpp", "cloud_stt", "google_cloud_stt", "nvidia_asr"])
def test_an_explicit_other_engine_is_never_replaced(monkeypatch, cfg, chosen):
    _usable(monkeypatch)
    merged = {**cfg, "transcribe_backend": chosen, "apple_silicon_engine": True}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == chosen


def test_load_config_on_this_machine_keeps_the_old_default(monkeypatch):
    """On a system that is not an M-series Mac the loaded config is exactly as before."""
    from core import config as cfgmod

    monkeypatch.setattr(mlx.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mlx.platform, "machine", lambda: "AMD64")
    loaded = cfgmod.load_config(fetch_online=False)
    assert loaded["transcribe_backend"] == "faster_whisper"
    assert loaded["apple_silicon_engine"] is True


def test_load_config_selects_mlx_on_apple_silicon(monkeypatch):
    from core import config as cfgmod

    _usable(monkeypatch)
    loaded = cfgmod.load_config(fetch_online=False)
    assert loaded["transcribe_backend"] == "mlx_whisper"
    # Saved or not, the opt-out always wins over a stored mlx_whisper.
    loaded["apple_silicon_engine"] = False
    cfgmod.save_config(loaded)
    again = cfgmod.load_config(fetch_online=False)
    assert again["transcribe_backend"] == "faster_whisper"


def test_a_saved_mlx_choice_with_the_opt_out_on_reads_as_faster_whisper(monkeypatch, cfg):
    _usable(monkeypatch)
    merged = {**cfg, "transcribe_backend": "mlx_whisper", "apple_silicon_engine": False}
    mlx.resolve_engine_choice(merged, dict(merged))
    assert merged["transcribe_backend"] == "faster_whisper"


def test_picking_faster_whisper_in_the_list_opts_out(monkeypatch):
    from core import config as cfgmod

    _usable(monkeypatch)
    loaded = cfgmod.load_config(fetch_online=False)
    loaded["transcribe_backend"] = "faster_whisper"
    loaded["apple_silicon_engine"] = False
    cfgmod.save_config(loaded)
    again = cfgmod.load_config(fetch_online=False)
    assert again["transcribe_backend"] == "faster_whisper"


# ----------------------------------------------------------- picker + status


def test_picker_lists_the_engine_only_for_apple_silicon():
    off = [v for _label, v in eng.engine_choices(apple_silicon=False)]
    on = [v for _label, v in eng.engine_choices(apple_silicon=True)]
    assert "mlx_whisper" not in off
    assert on[0] == "faster_whisper" and "mlx_whisper" in on
    assert [v for v in on if v != "mlx_whisper"] == off


def test_normalise_engine_drops_mlx_where_it_is_not_listed(monkeypatch):
    monkeypatch.setattr(eng, "KNOWN_ENGINES", frozenset(v for _l, v in eng.engine_choices(False)))
    assert eng.normalise_engine("mlx_whisper") == "faster_whisper"


def test_default_engine_is_mlx_only_when_usable(monkeypatch, cfg):
    _fake_platform(monkeypatch, "Windows", "AMD64")
    assert eng.default_engine(cfg) == "faster_whisper"
    _usable(monkeypatch)
    assert eng.default_engine(cfg) == "mlx_whisper"
    assert eng.default_engine({**cfg, "apple_silicon_engine": False}) == "faster_whisper"


def test_status_lines(monkeypatch, cfg):
    monkeypatch.setattr(eng, "KNOWN_ENGINES", frozenset(v for _l, v in eng.engine_choices(True)))
    _usable(monkeypatch, installed=False)
    st = eng.engine_status("mlx_whisper", cfg, deep=False)
    assert not st.ready and st.blocked
    _usable(monkeypatch)
    st = eng.engine_status("mlx_whisper", cfg, deep=False)
    assert st.ready and "downloads on first run" in st.detail
    _install_model(mlx.model_folder(cfg))
    assert eng.engine_status("mlx_whisper", cfg, deep=False).detail == ""
    monkeypatch.setattr(mlx, "package_importable", lambda: False)
    st = eng.engine_status("mlx_whisper", cfg, deep=True)
    assert not st.ready and st.blocked


def test_get_backend_builds_the_engine():
    from core.backends import get_backend

    assert get_backend("mlx_whisper").name == "mlx_whisper"


# ------------------------------------------------------------- model download


def _fake_hub(monkeypatch, calls: list, *, write: bool = True, boom: Exception | None = None):
    def snapshot_download(*, repo_id, local_dir, allow_patterns):
        calls.append((repo_id, local_dir, tuple(allow_patterns)))
        if boom is not None:
            raise boom
        if write:
            _install_model(Path(local_dir))
        return local_dir

    mod = types.ModuleType("huggingface_hub")
    mod.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_ensure_downloads_only_the_model_files(monkeypatch, cfg):
    calls: list = []
    _fake_hub(monkeypatch, calls)
    events: list = []
    path = mlx.ensure_mlx_model(cfg, progress_cb=events.append)
    assert path == str(mlx.model_folder(cfg))
    assert calls == [("mlx-community/whisper-large-v3-turbo", path,
                      ("config.json", "weights.safetensors", "weights.npz"))]
    assert events[-1]["phase"] == "ready"
    assert mlx.model_present(cfg)


def test_ensure_skips_the_network_when_installed(monkeypatch, cfg):
    calls: list = []
    _fake_hub(monkeypatch, calls)
    _install_model(mlx.model_folder(cfg))
    mlx.ensure_mlx_model(cfg)
    assert calls == []


def test_ensure_refuses_in_offline_mode(monkeypatch, cfg):
    from core import offline

    calls: list = []
    _fake_hub(monkeypatch, calls)
    monkeypatch.setattr(offline, "require_online", lambda what: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        mlx.ensure_mlx_model(cfg)
    assert calls == []


def test_ensure_reports_a_failed_download(monkeypatch, cfg):
    from core.model_manager import HuggingFaceDownloadError

    _fake_hub(monkeypatch, [], boom=ConnectionError("no route"))
    with pytest.raises(HuggingFaceDownloadError):
        mlx.ensure_mlx_model(cfg)


def test_ensure_notices_a_download_without_weights(monkeypatch, cfg):
    from core.model_manager import HuggingFaceDownloadError

    _fake_hub(monkeypatch, [], write=False)
    with pytest.raises(HuggingFaceDownloadError):
        mlx.ensure_mlx_model(cfg)


def test_ensure_stops_when_cancelled(monkeypatch, cfg):
    from core.model_manager import DownloadCancelled

    calls: list = []
    _fake_hub(monkeypatch, calls)
    stop = threading.Event()
    stop.set()
    with pytest.raises(DownloadCancelled):
        mlx.ensure_mlx_model(cfg, cancel_event=stop)
    assert calls == []


def test_ensure_model_hands_mlx_configs_to_the_mlx_downloader(monkeypatch, cfg):
    from core import model_manager

    calls: list = []
    _fake_hub(monkeypatch, calls)
    out = model_manager.ensure_model({**cfg, "transcribe_backend": "mlx_whisper"})
    assert out == str(mlx.model_folder(cfg))
    assert calls and calls[0][0] == "mlx-community/whisper-large-v3-turbo"


# ----------------------------------------------------------------- the backend


def _fake_mlx_modules(monkeypatch, result: dict, seen: dict):
    core = types.ModuleType("mlx.core")
    core.float16 = "float16"  # type: ignore[attr-defined]
    pkg = types.ModuleType("mlx")
    pkg.core = core  # type: ignore[attr-defined]

    class ModelHolder:
        model = None
        model_path = None

        @classmethod
        def get_model(cls, path, dtype):
            seen["warm"] = (path, dtype)
            cls.model, cls.model_path = object(), path
            return cls.model

    def transcribe(audio, **kwargs):
        seen["audio"] = audio
        seen["kwargs"] = kwargs
        return result

    tmod = types.ModuleType("mlx_whisper.transcribe")
    tmod.ModelHolder = ModelHolder  # type: ignore[attr-defined]
    top = types.ModuleType("mlx_whisper")
    top.transcribe = transcribe  # type: ignore[attr-defined]
    top.transcribe_module = tmod  # type: ignore[attr-defined]
    for name, module in (("mlx", pkg), ("mlx.core", core), ("mlx_whisper", top),
                         ("mlx_whisper.transcribe", tmod)):
        monkeypatch.setitem(sys.modules, name, module)
    return ModelHolder


RESULT = {
    "text": " Hello world. Bye.",
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 1.5, "text": " Hello world.", "words": [
            {"word": " Hello", "start": 0.0, "end": 0.6, "probability": 0.9},
            {"word": " world.", "start": 0.7, "end": 1.5, "probability": 0.8},
        ]},
        {"start": 2.0, "end": 2.5, "text": " Bye.", "words": []},
    ],
}


def _loaded_backend(monkeypatch, cfg, result=RESULT):
    seen: dict = {}
    _usable(monkeypatch)
    monkeypatch.setattr(mlx, "package_importable", lambda: True)
    holder = _fake_mlx_modules(monkeypatch, result, seen)
    _install_model(mlx.model_folder(cfg))
    monkeypatch.setattr(mlx, "_decode_audio", lambda path: ("samples", path))
    be = mlx.MlxWhisperBackend(config=cfg)
    return be, seen, holder


def test_map_result_with_and_without_words():
    segs, lang = mlx.map_result(RESULT, want_words=True)
    assert lang == "en"
    assert segs[0] == {
        "start": 0.0, "end": 1.5, "text": "Hello world.",
        "words": [{"start": 0.0, "end": 0.6, "word": " Hello", "probability": 0.9},
                  {"start": 0.7, "end": 1.5, "word": " world.", "probability": 0.8}],
    }
    assert segs[1]["words"] == []
    plain, _ = mlx.map_result(RESULT, want_words=False)
    assert all("words" not in s for s in plain)
    assert mlx.map_result({}, want_words=True) == ([], "")


def test_load_and_transcribe_with_fakes(monkeypatch, cfg):
    be, seen, holder = _loaded_backend(monkeypatch, cfg)
    assert be.load() is True and be.is_ready()
    assert seen["warm"] == (str(mlx.model_folder(cfg)), "float16")
    logs: list[str] = []
    pct: list[int] = []
    segs, info = be.transcribe_to_segments(
        "a.wav", language="en", want_words=True, initial_prompt="names",
        progress_cb=pct.append, log_cb=logs.append, duration=3.0,
    )
    assert seen["audio"] == ("samples", "a.wav")
    assert seen["kwargs"] == {
        "path_or_hf_repo": str(mlx.model_folder(cfg)), "word_timestamps": True,
        "verbose": None, "language": "en", "initial_prompt": "names",
    }
    assert [s["text"] for s in segs] == ["Hello world.", "Bye."]
    assert (info.language, info.probability) == ("en", 1.0)
    assert pct[0] == 0 and pct[-1] == 100
    assert any("[0.00 --> 1.50]" in line for line in logs)
    be.unload()
    assert not be.is_ready() and holder.model is None


def test_auto_language_when_none_given(monkeypatch, cfg):
    be, seen, _ = _loaded_backend(monkeypatch, cfg)
    assert be.load()
    be.transcribe_to_segments("a.wav")
    assert "language" not in seen["kwargs"] and seen["kwargs"]["word_timestamps"] is False


def test_cancel_during_the_call_returns_nothing(monkeypatch, cfg):
    be, _seen, _ = _loaded_backend(monkeypatch, cfg)
    assert be.load()
    segs, _info = be.transcribe_to_segments("a.wav", cancelled=lambda: True)
    assert segs == []


def test_load_refuses_without_downloading(monkeypatch, cfg):
    calls: list = []
    _fake_hub(monkeypatch, calls)
    _usable(monkeypatch)
    monkeypatch.setattr(mlx, "package_importable", lambda: True)
    be = mlx.MlxWhisperBackend(config=cfg)  # model folder is empty
    statuses: list[str] = []
    assert be.load(statuses.append) is False
    assert "not downloaded" in (be.get_error() or "")
    assert calls == []  # never a silent download
    with pytest.raises(RuntimeError):
        be.transcribe_to_segments("a.wav")


def test_load_off_apple_silicon_fails_cleanly(monkeypatch, cfg):
    _fake_platform(monkeypatch, "Windows", "AMD64")
    be = mlx.MlxWhisperBackend(config=cfg)
    assert be.load() is False
    assert "Apple silicon" in (be.get_error() or "")


def test_load_with_an_unmapped_model_fails_cleanly(monkeypatch, cfg):
    _usable(monkeypatch)
    monkeypatch.setattr(mlx, "package_importable", lambda: True)
    be = mlx.MlxWhisperBackend(config={**cfg, "whisper_model": "kb-whisper-large-sv"})
    assert be.load() is False
    assert "no model" in (be.get_error() or "")
