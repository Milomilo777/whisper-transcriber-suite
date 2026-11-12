"""Reference validation finishes on Tk without losing consent or sample limits."""
from pathlib import Path

import pytest

from app import i18n
from app.widgets import voice_clone_tab as tab
from core import _threads, voice_clone
from tests.app.test_voice_clone_tab import (
    _build, _clone_mode, _state, _tick, _write_wav, fakes, no_dialogs, root,
)


@pytest.fixture
def pending_samples(root, fakes, monkeypatch):
    language = i18n.current_language()
    i18n.set_language("en")
    try:
        app = _build(root, fakes)
        _clone_mode(app, ["previous.wav"])
        _tick(app)
        workers, callbacks = [], []
        monkeypatch.setattr(_threads, "safe_thread", lambda fn, **kwargs: workers.append(fn))
        app.post_to_main = callbacks.append
        yield app, workers, callbacks
    finally:
        i18n.set_language(language)


@pytest.mark.parametrize("result", ["valid", "blocked", "warning", "trimmed", "trim_failed"])
def test_deferred_reference_validation_preserves_source_and_consent(
    pending_samples, no_dialogs, monkeypatch, tmp_path, result,
):
    app, workers, callbacks = pending_samples
    source = tmp_path / "reference \u0622\u0632\u0645\u0627\u06cc\u0634.wav"
    _write_wav(str(source), 12)
    original = source.read_bytes()
    issue = None if result == "valid" else voice_clone.ReferenceIssue(
        str(source), "synthetic reference issue", blocking=result == "blocked",
        too_long=result in {"trimmed", "trim_failed"},
    )
    monkeypatch.setattr(voice_clone, "validate_reference_sample", lambda path: issue)
    outputs = []

    def trim(path, output):
        assert path == str(source)
        if result == "trim_failed":
            raise RuntimeError("synthetic trim failure")
        _write_wav(output, 10)
        outputs.append(output)

    monkeypatch.setattr(voice_clone, "trim_reference_sample", trim)
    tab._validate_and_add_sample(app, str(source))
    assert len(workers) == 1 and not callbacks
    assert app.vc_samples == ["previous.wav"] and app.vc_consent_var.get()
    workers.pop()()
    assert len(callbacks) == 1
    assert app.vc_samples == ["previous.wav"] and app.vc_consent_var.get()
    callbacks.pop()()
    assert source.read_bytes() == original
    if result == "blocked":
        assert app.vc_samples == ["previous.wav"]
        assert app.vc_consent_var.get() and _state(app) == "normal"
    else:
        expected = outputs[0] if result == "trimmed" else str(source)
        assert app.vc_samples == ["previous.wav", expected]
        assert not app.vc_consent_var.get() and _state(app) == "disabled"
        assert app.vc_samples_listbox.size() == 2
    assert len(no_dialogs) == (0 if result in {"valid", "trimmed"} else 1)
    if outputs:
        assert Path(outputs[0]).is_file() and outputs[0] != str(source)


def test_out_of_order_reference_completions_enforce_limit_on_tk(
    pending_samples, no_dialogs, monkeypatch, tmp_path,
):
    app, workers, callbacks = pending_samples
    app.vc_samples.clear()
    monkeypatch.setattr(voice_clone, "validate_reference_sample", lambda path: None)
    sources = [str(tmp_path / f"voice-{index}.wav") for index in range(4)]
    for path in sources:
        _write_wav(path, 4)
        tab._validate_and_add_sample(app, path)
    assert len(workers) == 4 and app.vc_samples == []
    for worker in reversed(workers):
        worker()
    assert len(callbacks) == 4 and app.vc_samples == []
    for callback in callbacks:
        callback()
    assert app.vc_samples == sources[:0:-1]
    assert len(app.vc_samples) == voice_clone.MAX_REFERENCE_SAMPLES
    assert app.vc_samples_listbox.size() == voice_clone.MAX_REFERENCE_SAMPLES
    assert len(no_dialogs) == 1 and "Sample limit reached" in str(no_dialogs[0])
    assert not app.vc_consent_var.get() and _state(app) == "disabled"
    tab._validate_and_add_sample(app, sources[0])
    assert len(workers) == 4 and len(no_dialogs) == 2
