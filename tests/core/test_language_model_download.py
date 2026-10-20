"""Web jobs use the installed Whisper-engine language models too, and the web page may ask the
computer to download a language model (ADR 0018).

A phone user who picks a language with a model trained for it learns whether the computer has it,
and can ask the computer to fetch it without touching the desktop's own engine. No model is loaded
and nothing is downloaded: engines, downloads and threads are faked.
"""
from __future__ import annotations

import json
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core import language_model_fetch as fetch
from core import language_models as lm
from core import transcriber as tr
from core.server import httpd
from tests.core.test_server_security import _RunningServer, _request

FA = lm.LANGUAGE_MODELS["fa"]
ZH = lm.LANGUAGE_MODELS["zh"]


@pytest.fixture
def whisper_cfg(monkeypatch, tmp_path):
    """The server runs the Whisper engine with a general model; models live under tmp_path."""
    monkeypatch.setitem(tr.config, "transcribe_backend", "faster_whisper")
    monkeypatch.setitem(tr.config, "whisper_model", "large-v3-turbo")
    monkeypatch.setitem(tr.config, "nvidia_asr_model_id", "nvidia/parakeet-tdt-0.6b-v3")
    monkeypatch.setitem(tr.config, "hub_folder", str(tmp_path / "hub"))
    return tr.config


@pytest.fixture(autouse=True)
def clean_fetch_state():
    fetch._STATE.clear()
    yield
    fetch._STATE.clear()


def _put_weights(cfg: dict[str, Any], row: lm.LanguageModel) -> Path:
    folder = Path(lm.whisper_model_folder(cfg, row))
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"weights")
    return folder


# --- the choice now covers Whisper-engine rows ---------------------------------------------------

def test_whisper_rows_have_a_folder_under_the_model_folder(whisper_cfg, tmp_path):
    folder = Path(lm.whisper_model_folder(whisper_cfg, ZH))
    assert folder.parent == tmp_path / "hub"
    assert lm.whisper_model_folder(whisper_cfg, FA) == ""


def test_a_whisper_row_is_installed_only_with_its_weights(whisper_cfg):
    assert lm.installed_here(ZH, whisper_cfg) is False
    folder = Path(lm.whisper_model_folder(whisper_cfg, ZH))
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    assert lm.installed_here(ZH, whisper_cfg) is False  # a killed download leaves only this
    (folder / "model.bin").write_bytes(b"weights")
    assert lm.installed_here(ZH, whisper_cfg) is True


def test_a_chinese_job_uses_the_installed_chinese_model(whisper_cfg):
    assert lm.web_job_model(whisper_cfg, "zh") is None
    _put_weights(whisper_cfg, ZH)
    assert lm.web_job_model(whisper_cfg, "zh") == ZH
    assert lm.web_job_model(whisper_cfg, "zh", "en") is None  # mixed-language jobs keep the general model


def test_a_server_already_on_the_chinese_model_needs_no_switch(whisper_cfg, monkeypatch):
    _put_weights(whisper_cfg, ZH)
    monkeypatch.setitem(whisper_cfg, "whisper_model", ZH.model)
    assert lm.web_job_model(whisper_cfg, "zh") is None


def test_by_model_finds_rows_by_slug_or_repo():
    assert lm.by_model(ZH.model) == ZH
    assert lm.by_model(FA.model.upper()) == FA
    assert lm.by_model("") is None and lm.by_model("someone/else") is None


# --- the Whisper slot runs the general Whisper path on the language model ------------------------

@dataclass
class _Seg:
    start: float
    end: float
    text: str
    words: Any = None
    avg_logprob: float = -0.2
    no_speech_prob: float = 0.01
    compression_ratio: float = 1.2


class _Engine:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, audio_path: str, **kwargs: Any):
        self.calls += 1
        return iter([_Seg(0.0, 2.0, self.text)]), types.SimpleNamespace(language="zh", language_probability=0.99)


@pytest.fixture
def engine_env(monkeypatch, tmp_path, whisper_cfg):
    import core._checkpoint as cp
    import core.config as cfg

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    for key, value in {"demucs_enabled": False, "denoise_enabled": False, "diarization_enabled": False,
                       "auto_chapters_enabled": False, "hallucination_detect_enabled": False,
                       "alignment": "none", "ai_enabled": False, "word_timestamps": False}.items():
        monkeypatch.setitem(tr.config, key, value)
    general = _Engine("general model text")
    monkeypatch.setattr(tr, "MODEL", general)
    monkeypatch.setattr(tr, "PIPELINE", None, raising=False)
    monkeypatch.setattr(tr, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(tr, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(tr, "get_duration", lambda p: 2.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda p: None)
    written: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(tr, "_write_outputs", lambda base, segs, *a, **k: written.append(list(segs)) or [])
    language_engine = _Engine("中文模型的文字")
    loads: list[str] = []

    def fake_load(path, device, compute_type, status_cb=None):
        loads.append(str(path))
        return language_engine

    monkeypatch.setattr(tr, "_load_whisper_model_self_healing", fake_load)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda model: None)
    monkeypatch.setitem(tr._LM_SLOT, "backend", None)
    monkeypatch.setitem(tr._LM_SLOT, "model_id", "")
    yield types.SimpleNamespace(general=general, language=language_engine, written=written, loads=loads,
                                tmp=tmp_path)
    tr._LM_SLOT.update(backend=None, model_id="")
    tr._LM_RUNNER.slot = None


def _task(tmp_path: Path):
    from core.task import TranscriptionTask

    audio = tmp_path / "call.wav"
    audio.write_bytes(b"RIFF")
    task = TranscriptionTask(file_path=str(audio))
    task.language = "zh"
    task.output_formats = ["txt"]
    return task


def test_a_routed_chinese_job_runs_on_the_chinese_model_only(engine_env, whisper_cfg):
    folder = _put_weights(whisper_cfg, ZH)
    tr.transcribe_with_language_model(ZH.model, _task(engine_env.tmp))
    assert engine_env.language.calls == 1 and engine_env.general.calls == 0
    assert engine_env.loads == [str(folder)]
    assert engine_env.written[-1][0]["text"].strip() == "中文模型的文字"
    assert tr.MODEL is None  # one model in memory: the general one was freed
    assert getattr(tr._LM_RUNNER, "slot", None) is None  # the next general job is not affected


def test_the_next_general_job_does_not_use_the_language_model(engine_env, whisper_cfg, monkeypatch):
    _put_weights(whisper_cfg, ZH)
    tr.transcribe_with_language_model(ZH.model, _task(engine_env.tmp))
    reloaded = _Engine("general again")

    def lazy_load(status_cb=None):
        monkeypatch.setattr(tr, "MODEL", reloaded)

    monkeypatch.setattr(tr, "_ensure_default_backend_loaded", lazy_load)
    tr.release_language_model()
    tr.transcribe(_task(engine_env.tmp))
    assert reloaded.calls == 1 and engine_env.language.calls == 1
    assert engine_env.written[-1][0]["text"].strip() == "general again"


def test_the_slot_is_cleared_when_the_job_fails(engine_env, whisper_cfg, monkeypatch):
    _put_weights(whisper_cfg, ZH)
    monkeypatch.setattr(tr, "transcribe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("decode failed")))
    with pytest.raises(RuntimeError, match="decode failed"):
        tr.transcribe_with_language_model(ZH.model, _task(engine_env.tmp))
    assert getattr(tr._LM_RUNNER, "slot", None) is None


def test_missing_files_raise_the_load_error_so_the_general_model_runs(engine_env):
    with pytest.raises(tr.LanguageModelLoadError, match="missing"):
        tr.transcribe_with_language_model(ZH.model, _task(engine_env.tmp))
    assert tr._LM_SLOT["backend"] is None


def test_a_desktop_engine_switch_after_queueing_raises_the_load_error(engine_env, whisper_cfg, monkeypatch):
    _put_weights(whisper_cfg, ZH)
    monkeypatch.setitem(tr.config, "transcribe_backend", "cloud_stt")
    with pytest.raises(tr.LanguageModelLoadError, match="cloud_stt"):
        tr.transcribe_with_language_model(ZH.model, _task(engine_env.tmp))
    assert engine_env.loads == [] and engine_env.general.calls == 0


def test_a_checkpoint_names_the_language_model(engine_env):
    tr._LM_RUNNER.slot = tr._WhisperLanguageModel(ZH.model, "x")
    try:
        assert tr._current_backend_and_model() == ("faster_whisper", ZH.model)
    finally:
        tr._LM_RUNNER.slot = None
    assert tr._current_backend_and_model()[1] != ZH.model


def test_the_collapse_rescue_also_reads_on_the_language_model(engine_env, monkeypatch):
    # Review finding: the rescue of ADR 0017 read the global MODEL, which a routed job frees.
    from core.backends import nvidia_asr

    monkeypatch.setattr(tr, "MODEL", None)
    monkeypatch.setattr(nvidia_asr, "_decode_window", lambda *a: (_ for _ in ()).throw(OSError("no audio")))
    segs = [{"start": 0.0, "end": 30.0, "text": "a b"}]
    slot = tr._WhisperLanguageModel(ZH.model, "x")
    slot.model = engine_env.language
    logs: list[str] = []
    tr._LM_RUNNER.slot = slot
    try:
        out = tr._rescue_collapsed(_task(engine_env.tmp), segs, "x.wav", {}, False, "zh", 35.0, logs.append)
    finally:
        tr._LM_RUNNER.slot = None
    assert out == segs  # the decode failure keeps the transcript ...
    assert any("Checking 1 stretch" in line for line in logs)  # ... but the rescue did look


def test_an_unfinished_whisper_download_is_not_installed(whisper_cfg):
    folder = _put_weights(whisper_cfg, ZH)
    blob = folder / ".cache" / "huggingface" / "download" / "tokenizer.json.abc.incomplete"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"part")
    assert lm.installed_here(ZH, whisper_cfg) is False
    blob.unlink()
    assert lm.installed_here(ZH, whisper_cfg) is True


def test_the_override_is_per_thread(engine_env):
    tr._LM_RUNNER.slot = tr._WhisperLanguageModel(ZH.model, "x")
    seen: list[Any] = []
    try:
        t = threading.Thread(target=lambda: seen.append(getattr(tr._LM_RUNNER, "slot", None)))
        t.start()
        t.join()
    finally:
        tr._LM_RUNNER.slot = None
    assert seen == [None]


# --- the download ------------------------------------------------------------------------------

def _wait_done(language: str) -> dict[str, Any]:
    for _ in range(200):
        state = fetch.status(language)
        if state and state["state"] != "downloading":
            return state
        threading.Event().wait(0.02)
    raise AssertionError("download thread did not finish")


@pytest.fixture
def online(monkeypatch):
    from core import offline

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)


@pytest.mark.usefixtures("online")
def test_fetch_refuses_unknown_languages_and_reports_installed_ones(whisper_cfg):
    assert fetch.start("en", whisper_cfg)[0] == "unknown"
    assert fetch.start("", whisper_cfg)[0] == "unknown"
    _put_weights(whisper_cfg, ZH)
    assert fetch.start("zh", whisper_cfg)[0] == "installed"


def test_fetch_refuses_while_offline(whisper_cfg, monkeypatch):
    from core import offline

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    outcome, message = fetch.start("zh", whisper_cfg)
    assert outcome == "refused" and "offline" in message.lower()
    assert fetch.status("zh") is None


@pytest.mark.usefixtures("online")
def test_fetch_refuses_without_room_on_the_disk(whisper_cfg, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "disk_usage", lambda p: types.SimpleNamespace(free=10 * 1024 ** 2))
    outcome, message = fetch.start("zh", whisper_cfg)
    assert outcome == "refused" and "disk space" in message


@pytest.mark.usefixtures("online")
def test_a_whisper_row_downloads_into_its_folder_without_switching_the_desktop(whisper_cfg, monkeypatch):
    import core.model_manager as mm

    calls: list[dict[str, Any]] = []
    gate = threading.Event()

    def fake_ensure(cfg, status_cb=None, progress_cb=None, cancel_event=None):
        calls.append(cfg)
        progress_cb({"phase": "download", "percent": 40})
        gate.wait(5)
        folder = Path(cfg["model_path"])
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"w")
        return str(folder)

    monkeypatch.setattr(mm, "ensure_model", fake_ensure)
    before = dict(whisper_cfg)
    assert fetch.start("zh", whisper_cfg)[0] == "started"
    assert fetch.start("de", whisper_cfg)[0] == "busy"  # one download at a time
    for _ in range(100):
        if (fetch.status("zh") or {}).get("percent") == 40:
            break
        threading.Event().wait(0.02)
    assert fetch.status("zh")["percent"] == 40
    gate.set()
    assert _wait_done("zh")["state"] == "done"
    assert calls[0]["model_path"] == lm.whisper_model_folder(whisper_cfg, ZH)
    assert calls[0]["model"]["name"]
    assert dict(whisper_cfg) == before  # the desktop's engine and model are untouched
    assert lm.web_job_model(whisper_cfg, "zh") == ZH


@pytest.mark.usefixtures("online")
def test_a_failed_download_is_reported_and_may_be_retried(whisper_cfg, monkeypatch):
    import core.model_manager as mm

    def broken(cfg, *a, **k):
        raise RuntimeError("Model download from huggingface.co failed: 503")

    monkeypatch.setattr(mm, "ensure_model", broken)
    assert fetch.start("zh", whisper_cfg)[0] == "started"
    state = _wait_done("zh")
    assert state["state"] == "failed" and "503" in state["message"]
    assert fetch.start("zh", whisper_cfg)[0] == "started"
    _wait_done("zh")


@pytest.mark.usefixtures("online")
def test_an_unexpected_exit_never_leaves_the_download_busy(whisper_cfg, monkeypatch):
    monkeypatch.setattr(fetch, "_fetch_whisper", lambda *a: (_ for _ in ()).throw(SystemExit(3)))
    monkeypatch.setattr(threading, "excepthook", lambda args: None)  # the thread's SystemExit is expected
    assert fetch.start("zh", whisper_cfg)[0] == "started"
    assert _wait_done("zh")["state"] == "failed"
    assert fetch.busy() is False


@pytest.mark.usefixtures("online")
def test_a_download_that_leaves_no_weights_is_a_failure(whisper_cfg, monkeypatch):
    import core.model_manager as mm

    monkeypatch.setattr(mm, "ensure_model", lambda cfg, *a, **k: cfg["model_path"])
    fetch.start("zh", whisper_cfg)
    state = _wait_done("zh")
    assert state["state"] == "failed" and "not complete" in state["message"]


class _FakeEngine:
    prepared: list[str] = []
    ok = True

    def __init__(self, config: dict[str, Any]) -> None:
        self.model_id = config["nvidia_asr_model_id"]

    def prepare_engine(self, status_cb=None, cancel_event=None) -> bool:
        _FakeEngine.prepared.append(self.model_id)
        return _FakeEngine.ok

    def get_error(self) -> str:
        return "pip failed"


@pytest.fixture
def transformers_env(monkeypatch, tmp_path, whisper_cfg):
    import huggingface_hub
    from huggingface_hub import constants

    from core import optional_deps
    from core.backends import nvidia_asr

    _FakeEngine.prepared = []
    _FakeEngine.ok = True
    monkeypatch.setattr(nvidia_asr, "NvidiaAsrBackend", _FakeEngine)
    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: [])
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path / "hf"))
    downloads: list[tuple[str, Any]] = []
    snap = tmp_path / "hf" / "snap"

    def fake_snapshot(repo, ignore_patterns=None, **kw):
        downloads.append((repo, ignore_patterns))
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "config.json").write_text("{}", encoding="utf-8")
        (snap / "model.safetensors").write_bytes(b"w")
        return str(snap)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, name: str(snap / name) if (snap / name).exists() else None)
    return downloads


@pytest.mark.usefixtures("online")
def test_the_persian_model_installs_its_engine_then_its_files(transformers_env, whisper_cfg):
    assert fetch.start("fa", whisper_cfg)[0] == "started"
    assert _wait_done("fa")["state"] == "done"
    assert _FakeEngine.prepared == [FA.model]
    assert transformers_env == [(FA.model, fetch._SKIP_FILES)]  # never the duplicate .nemo checkpoint
    assert lm.web_job_model(whisper_cfg, "fa") == FA


def test_a_persian_download_still_running_is_not_installed(transformers_env, tmp_path):
    snap = tmp_path / "hf" / "snap"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    (snap / "model.safetensors").write_bytes(b"w")
    blobs = snap.parent.parent / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / "abc.incomplete").write_bytes(b"part")
    assert lm.installed_here(FA) is False
    (blobs / "abc.incomplete").unlink()
    assert lm.installed_here(FA) is True


@pytest.mark.usefixtures("online")
def test_an_engine_install_failure_stops_before_the_model_download(transformers_env, whisper_cfg):
    _FakeEngine.ok = False
    fetch.start("fa", whisper_cfg)
    state = _wait_done("fa")
    assert state["state"] == "failed" and "pip failed" in state["message"]
    assert transformers_env == []


@pytest.mark.usefixtures("online")
def test_a_build_that_cannot_install_refuses_when_the_engine_is_missing(transformers_env, whisper_cfg,
                                                                      monkeypatch):
    from core import optional_deps
    from core.backends import nvidia_asr

    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: False)
    monkeypatch.setattr(optional_deps, "can_install", lambda: False)
    outcome, message = fetch.start("fa", whisper_cfg)
    assert outcome == "refused" and message == optional_deps.FROZEN_INSTALL_MESSAGE


def test_prepare_engine_loads_no_model(monkeypatch):
    from core import optional_deps
    from core.backends import nvidia_asr

    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: [])
    monkeypatch.setattr(nvidia_asr, "_import_torch_and_transformers",
                        lambda: pytest.fail("prepare_engine must not import or load the model"))
    backend = nvidia_asr.NvidiaAsrBackend(config={"nvidia_asr_model_id": FA.model})
    assert backend.prepare_engine() is True
    assert backend.is_ready() is False


# --- through the HTTP server -------------------------------------------------------------------

def test_the_route_is_parsed():
    route = httpd.parse_route("POST", "/api/language-models/zh/download")
    assert (route.name, route.job_id) == ("language_model_download", "zh")
    assert httpd.parse_route("POST", "/api/language-models/zh").name == "unknown"


@pytest.mark.usefixtures("online")
def test_the_page_asks_and_options_report_progress_then_ready(tmp_path, whisper_cfg, monkeypatch):
    import core.model_manager as mm

    gate = threading.Event()

    def fake_ensure(cfg, status_cb=None, progress_cb=None, cancel_event=None):
        progress_cb({"phase": "download", "percent": 12})
        gate.wait(5)
        folder = Path(cfg["model_path"])
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"w")
        return str(folder)

    monkeypatch.setattr(mm, "ensure_model", fake_ensure)
    with _RunningServer(tmp_path) as srv:
        _s, raw = _request(srv, "GET", "/api/options")
        note = json.loads(raw)["language_models"]["zh"]
        assert note["state"] == "missing" and note["size_gb"] == round(ZH.size_gb, 1)
        status, raw = _request(srv, "POST", "/api/language-models/zh/download", b"")
        assert status == 202 and json.loads(raw)["outcome"] == "started"
        status, raw = _request(srv, "POST", "/api/language-models/de/download", b"")
        assert status == 409 and json.loads(raw)["outcome"] == "busy"
        for _ in range(100):
            _s, raw = _request(srv, "GET", "/api/options")
            note = json.loads(raw)["language_models"]["zh"]
            if note.get("percent") == 12:
                break
            threading.Event().wait(0.02)
        assert note["state"] == "downloading" and note["percent"] == 12
        gate.set()
        _wait_done("zh")
        _s, raw = _request(srv, "GET", "/api/options")
        note = json.loads(raw)["language_models"]["zh"]
        assert note["state"] == "ready" and note["ready"] is True
        status, raw = _request(srv, "POST", "/api/language-models/xx/download", b"")
        assert status == 404


def test_the_download_needs_the_password_when_one_is_set(tmp_path, whisper_cfg, monkeypatch):
    monkeypatch.setattr(fetch, "start", lambda *a: pytest.fail("must not start"))
    with _RunningServer(tmp_path, token="s3cret") as srv:
        status, _raw = _request(srv, "POST", "/api/language-models/zh/download", b"")
        assert status == 401
        status, _raw = _request(srv, "POST", "/api/language-models/zh/download", b"",
                                {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors",
                                 "X-Auth-Token": "s3cret"})
        assert status == 403


def test_options_say_when_the_engine_cannot_use_language_models(tmp_path, monkeypatch):
    monkeypatch.setitem(tr.config, "transcribe_backend", "cloud_stt")
    with _RunningServer(tmp_path) as srv:
        _s, raw = _request(srv, "GET", "/api/options")
    notes = json.loads(raw)["language_models"]
    assert {n["state"] for n in notes.values()} == {"other_engine"}
    assert set(notes) == {code for code in lm.LANGUAGE_MODELS if code in httpd.WEB_LANGUAGE_CODES}


def test_the_page_has_the_download_button_and_names_hebrew():
    page = (Path(httpd._STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    assert 'id="lang_dl"' in page and '"/api/language-models/"' in page and '"/download"' in page
    assert 'he: "Hebrew"' in page
