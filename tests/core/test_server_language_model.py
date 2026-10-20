"""Web / LAN jobs run on an installed language model for their language (ADR 0016).

A Persian phone call sent through the web page came back from the general model with its first
30 seconds missing, while the Persian model already in the app transcribed it whole. These tests
pin the choice (made once, at submission), the one-model-in-memory slot, the fallback with a
visible warning, and what the page is told. No model is ever loaded: the engine is faked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import core.server as server_pkg
from core import language_models as lm
from core import transcriber as tr
from core.server import httpd
from tests.core.test_server_security import _RunningServer, _request, _wait_terminal

FA = lm.LANGUAGE_MODELS["fa"]
_BOUND = "BOUND"
_HEADERS = {"Content-Type": f"multipart/form-data; boundary={_BOUND}"}


def _upload(fields: dict[str, str]) -> bytes:
    body = (
        f"--{_BOUND}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"call.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n"
    ).encode() + b"abc\r\n"
    for name, value in fields.items():
        body += (f"--{_BOUND}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    return body + f"--{_BOUND}--\r\n".encode()


@pytest.fixture
def whisper_server(monkeypatch):
    """The server's engine is faster-whisper with a general model."""
    monkeypatch.setitem(tr.config, "transcribe_backend", "faster_whisper")
    monkeypatch.setitem(tr.config, "nvidia_asr_model_id", "nvidia/parakeet-tdt-0.6b-v3")


def _installed(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(lm, "installed_here", lambda row, cfg=None: value and row.engine == lm.ENGINE_TRANSFORMERS)


# --- the choice -------------------------------------------------------------------------

@pytest.mark.usefixtures("whisper_server")
def test_a_persian_job_uses_the_installed_persian_model(monkeypatch):
    _installed(monkeypatch, True)
    assert lm.web_job_model(tr.config, "fa") == FA


@pytest.mark.usefixtures("whisper_server")
@pytest.mark.parametrize(("language", "second"), [("", ""), ("en", ""), ("fa", "en"), ("zh", "")])
def test_no_language_model_for_auto_other_languages_pairs_or_models_not_installed(monkeypatch, language, second):
    _installed(monkeypatch, True)
    assert lm.web_job_model(tr.config, language, second) is None


@pytest.mark.usefixtures("whisper_server")
def test_a_model_that_is_not_installed_is_never_chosen(monkeypatch):
    _installed(monkeypatch, False)
    assert lm.web_job_model(tr.config, "fa") is None


def test_a_cloud_engine_server_keeps_its_engine(monkeypatch):
    _installed(monkeypatch, True)
    cfg = {"transcribe_backend": "cloud_stt"}
    assert lm.web_job_model(cfg, "fa") is None


def test_a_server_on_the_transformers_engine_keeps_its_own_model(monkeypatch):
    # Review finding: its own model stays in the engine cache; a second one breaks the one-model rule.
    _installed(monkeypatch, True)
    cfg = {"transcribe_backend": "nvidia_asr", "nvidia_asr_model_id": "nvidia/parakeet-tdt-0.6b-v3"}
    assert lm.web_job_model(cfg, "fa") is None


@pytest.mark.usefixtures("whisper_server")
def test_the_openai_route_and_mcp_also_use_the_language_model(tmp_path, monkeypatch):
    _installed(monkeypatch, True)
    rec = _Recorder()
    body = _upload({"model": "whisper-1", "language": "fa"})
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(srv, "POST", "/v1/audio/transcriptions", body, _HEADERS)
        assert status == 200, raw
    assert rec.seen == [FA.model]
    from core.server import mcp

    calls: list[dict[str, Any]] = []
    manager = SimpleNamespace(submit_url=lambda *a, **k: calls.append(k) or "job1")
    mcp._transcribe_url({"url": "https://example.com/a.mp3", "language": "fa"}, manager)
    assert calls[0]["language_model"] == (FA.model, FA.name)


def test_a_server_already_on_the_persian_model_needs_no_switch(monkeypatch):
    _installed(monkeypatch, True)
    cfg = {"transcribe_backend": "nvidia_asr", "nvidia_asr_model_id": FA.model}
    assert lm.web_job_model(cfg, "fa") is None


def test_installed_here_needs_the_engine_libraries(monkeypatch):
    from core.backends import nvidia_asr

    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: False)
    assert lm.installed_here(FA) is False
    assert lm.installed_here(lm.LANGUAGE_MODELS["zh"]) is False  # not a transformers row


def test_installed_here_needs_the_weights_in_the_cache(monkeypatch, tmp_path):
    from core.backends import nvidia_asr
    import huggingface_hub

    from core import optional_deps

    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: [])
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, name: str(snapshot / name))
    assert lm.installed_here(FA) is False  # config only, no weights
    (snapshot / "model.safetensors").write_bytes(b"x")
    assert lm.installed_here(FA) is True
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, name: None)
    assert lm.installed_here(FA) is False
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, name: str(snapshot / name))
    # Libraries older than the pins would be upgraded on load: a download, so not "installed".
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: ["transformers 5.14.1 (needs >=5.18)"])
    assert lm.installed_here(FA) is False


# --- through the HTTP handler --------------------------------------------------------------

class _Recorder:
    def __init__(self, warn: str = "") -> None:
        self.seen: list[str] = []
        self.warn = warn

    def __call__(self, task, progress_cb=None, log_cb=None, language_cb=None):
        self.seen.append(task.language_model)
        if self.warn:
            task.route_warning = self.warn
        base, _ = os.path.splitext(task.file_path)
        task.output_paths = []
        for fmt in task.output_formats:
            Path(f"{base}.{fmt}").write_text("[]" if fmt == "json" else "x", encoding="utf-8")
            task.output_paths.append(f"{base}.{fmt}")


@pytest.mark.usefixtures("whisper_server")
@pytest.mark.parametrize("installed", [True, False])
def test_the_choice_is_frozen_into_the_job_at_submission(tmp_path, monkeypatch, installed):
    _installed(monkeypatch, installed)
    rec = _Recorder()
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(srv, "POST", "/api/jobs",
                               _upload({"formats": "txt", "language": "fa"}), _HEADERS)
        assert status == 202, raw
        job_id = json.loads(raw)["job_id"]
        job = _wait_terminal(srv.manager, job_id)
        _status, raw = _request(srv, "GET", f"/api/jobs/{job_id}")
    assert job.status == "finished", job.error
    assert rec.seen == [FA.model if installed else ""]
    assert (json.loads(raw).get("language_model") == FA.name) is installed


@pytest.mark.usefixtures("whisper_server")
def test_a_model_that_did_not_load_is_reported_and_not_named(tmp_path, monkeypatch):
    _installed(monkeypatch, True)
    rec = _Recorder(warn="The model trained for this language could not load (x)")
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(srv, "POST", "/api/jobs",
                               _upload({"formats": "txt", "language": "fa"}), _HEADERS)
        job_id = json.loads(raw)["job_id"]
        _wait_terminal(srv.manager, job_id)
        _status, raw = _request(srv, "GET", f"/api/jobs/{job_id}")
    data = json.loads(raw)
    assert "could not load" in data["warning"]
    assert "language_model" not in data


@pytest.mark.usefixtures("whisper_server")
def test_options_tell_the_page_whether_the_model_is_used(tmp_path, monkeypatch):
    for installed in (True, False):
        _installed(monkeypatch, installed)
        with _RunningServer(tmp_path) as srv:
            _status, raw = _request(srv, "GET", "/api/options")
        note = json.loads(raw)["language_models"]["fa"]
        assert note["name"] == FA.name and note["ready"] is installed
        assert note["state"] == ("ready" if installed else "missing")


def test_the_page_shows_the_note_and_the_model_used():
    page = (Path(httpd._STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    assert 'id="lang_note"' in page and "d.language_models" in page
    assert "j.language_model" in page


# --- the real transcribe adapter: fallback and the one-model slot -----------------------------

def test_the_adapter_runs_the_language_model_and_keeps_one_model(monkeypatch):
    calls: list[Any] = []
    monkeypatch.setattr(tr, "transcribe_with_language_model",
                        lambda mid, task, *a: calls.append(("lm", mid)))
    monkeypatch.setattr(tr, "transcribe", lambda task, *a: calls.append(("general",)))
    monkeypatch.setattr(tr, "release_language_model", lambda: calls.append(("release",)))
    task = SimpleNamespace(language_model=FA.model, route_warning="")
    server_pkg._real_transcribe(task)
    assert calls == [("lm", FA.model)]
    calls.clear()
    server_pkg._real_transcribe(SimpleNamespace(language_model="", route_warning=""))
    assert calls == [("release",), ("general",)]


def test_a_load_failure_falls_back_to_the_general_model_with_a_warning(monkeypatch):
    calls: list[str] = []

    def _fail(*_a: Any) -> None:
        raise tr.LanguageModelLoadError("no torch")

    monkeypatch.setattr(tr, "transcribe_with_language_model", _fail)
    monkeypatch.setattr(tr, "transcribe", lambda task, *a: calls.append("general"))
    monkeypatch.setattr(tr, "release_language_model", lambda: calls.append("release"))
    task = SimpleNamespace(language_model=FA.model, route_warning="")
    server_pkg._real_transcribe(task)
    assert calls == ["release", "general"]
    assert "no torch" in task.route_warning


def test_an_error_after_the_model_loaded_is_not_retried(monkeypatch):
    monkeypatch.setattr(tr, "transcribe_with_language_model",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("decode failed")))
    monkeypatch.setattr(tr, "transcribe", lambda *a: pytest.fail("must not run twice"))
    with pytest.raises(RuntimeError, match="decode failed"):
        server_pkg._real_transcribe(SimpleNamespace(language_model=FA.model, route_warning=""))


class _FakeBackend:
    loaded: list[str] = []

    def __init__(self, config: dict[str, Any]) -> None:
        self.model_id = config["nvidia_asr_model_id"]
        self.unloaded = False

    def load(self, status_cb=None) -> bool:
        _FakeBackend.loaded.append(self.model_id)
        return self.model_id != "broken/model"

    def get_error(self) -> str:
        return "broken"

    def unload(self) -> None:
        self.unloaded = True


@pytest.fixture
def fake_slot(monkeypatch):
    from core.backends import nvidia_asr

    _FakeBackend.loaded = []
    monkeypatch.setattr(nvidia_asr, "NvidiaAsrBackend", _FakeBackend)
    monkeypatch.setitem(tr._LM_SLOT, "backend", None)
    monkeypatch.setitem(tr._LM_SLOT, "model_id", "")
    yield
    tr._LM_SLOT.update(backend=None, model_id="")


@pytest.mark.usefixtures("fake_slot")
def test_the_slot_loads_once_and_swaps_models_by_unloading():
    first = tr._language_model_backend(FA.model)
    assert tr._language_model_backend(FA.model) is first
    other = tr._language_model_backend("someone/other-model")
    assert first.unloaded and other is not first
    assert _FakeBackend.loaded == [FA.model, "someone/other-model"]
    assert tr.release_language_model() is True and other.unloaded
    assert tr.release_language_model() is False


@pytest.mark.usefixtures("fake_slot")
def test_a_model_that_fails_to_load_raises_the_load_error():
    with pytest.raises(tr.LanguageModelLoadError):
        tr._language_model_backend("broken/model")
    assert tr._LM_SLOT["backend"] is None


def test_releasing_the_general_model_keeps_it_reloadable(monkeypatch):
    monkeypatch.setattr(tr, "MODEL", object())
    monkeypatch.setattr(tr, "PIPELINE", object())
    monkeypatch.setattr(tr, "MODEL_READY", True)
    assert tr.release_default_model() is True
    assert tr.MODEL is None and tr.PIPELINE is None and tr.MODEL_READY is True
    assert tr.release_default_model() is False
