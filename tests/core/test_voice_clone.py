"""Tests for the Clone Your Voice / Text to Voice domain module.

OmniVoice/torch are on-demand deps (see core.optional_deps, feature
"voice_clone"); these tests exercise validation and error paths that
never need those heavy imports, mirroring the mocking approach in
test_alignment.py for a similarly-optional dependency.
"""
from __future__ import annotations

import sys
import types

import pytest

from core import voice_clone


# ---------- validate_reference_sample ------------------------------------


def test_validate_reference_sample_missing_file():
    issue = voice_clone.validate_reference_sample("/nowhere/at/all.wav")
    assert issue is not None
    assert "not found" in issue.message.lower()


def test_validate_reference_sample_empty_path():
    issue = voice_clone.validate_reference_sample("")
    assert issue is not None


def test_validate_reference_sample_too_short(monkeypatch, tmp_path):
    clip = tmp_path / "short.wav"
    clip.write_bytes(b"\x00")
    monkeypatch.setattr(voice_clone, "get_duration", lambda p: 1.0)
    issue = voice_clone.validate_reference_sample(str(clip))
    assert issue is not None
    assert "short" in issue.message.lower()


def test_validate_reference_sample_too_long(monkeypatch, tmp_path):
    clip = tmp_path / "long.wav"
    clip.write_bytes(b"\x00")
    monkeypatch.setattr(voice_clone, "get_duration", lambda p: 30.0)
    issue = voice_clone.validate_reference_sample(str(clip))
    assert issue is not None
    assert "long" in issue.message.lower()


def test_validate_reference_sample_good_length(monkeypatch, tmp_path):
    clip = tmp_path / "good.wav"
    clip.write_bytes(b"\x00")
    monkeypatch.setattr(voice_clone, "get_duration", lambda p: 6.0)
    assert voice_clone.validate_reference_sample(str(clip)) is None


def test_validate_reference_sample_unreadable_reports_issue_not_raise(monkeypatch, tmp_path):
    clip = tmp_path / "bad.wav"
    clip.write_bytes(b"\x00")

    def _boom(p):
        raise RuntimeError("ffprobe exploded")

    monkeypatch.setattr(voice_clone, "get_duration", _boom)
    issue = voice_clone.validate_reference_sample(str(clip))
    assert issue is not None
    assert "could not read" in issue.message.lower()


# ---------- generate: input validation (no heavy import touched) --------


def test_generate_raises_on_empty_text():
    with pytest.raises(ValueError, match="No text"):
        voice_clone.generate(object(), "   ", ["/x.wav"], "/out.wav")


def test_generate_raises_on_text_too_long():
    long_text = "a" * (voice_clone.MAX_TEXT_CHARS + 1)
    with pytest.raises(ValueError, match="characters"):
        voice_clone.generate(object(), long_text, ["/x.wav"], "/out.wav")


def test_generate_raises_on_no_reference_paths():
    with pytest.raises(ValueError, match="reference"):
        voice_clone.generate(object(), "hello", [], "/out.wav")


# ---------- default_device ------------------------------------------------


def test_default_device_cpu_when_cuda_unavailable(monkeypatch):
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert voice_clone.default_device() == "cpu"


def test_default_device_cuda_when_available(monkeypatch):
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert voice_clone.default_device() == "cuda"


def test_default_device_defaults_to_cpu_when_torch_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert voice_clone.default_device() == "cpu"


# ---------- is_available / ensure_installed delegate to optional_deps ----


def test_is_available_delegates_to_optional_deps(monkeypatch):
    monkeypatch.setattr(voice_clone.optional_deps, "is_available", lambda feature: feature == "voice_clone")
    assert voice_clone.is_available() is True


def test_ensure_installed_short_circuits_when_already_available(monkeypatch):
    monkeypatch.setattr(voice_clone, "is_available", lambda: True)
    calls = []
    monkeypatch.setattr(
        voice_clone.optional_deps, "install",
        lambda *a, **k: calls.append((a, k)) or True,
    )
    assert voice_clone.ensure_installed() is True
    assert calls == []


# ---------- session_work_dir -----------------------------------------------


def test_session_work_dir_is_under_user_cache(monkeypatch, tmp_path):
    from core import config as _cfg
    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: tmp_path)
    out = voice_clone.session_work_dir()
    assert str(tmp_path) in out
    assert "voice_clone" in out
