"""Tests for the Clone Your Voice / Text to Voice domain module.

OmniVoice/torch are on-demand deps (see core.optional_deps, feature
"voice_clone"); these tests exercise validation and error paths that
never need those heavy imports, mirroring the mocking approach in
test_alignment.py for a similarly-optional dependency.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import types

import pytest

from core import voice_clone


# ---------- validate_reference_sample ------------------------------------


def test_validate_reference_sample_missing_file():
    issue = voice_clone.validate_reference_sample("/nowhere/at/all.wav")
    assert issue is not None
    assert "not found" in issue.message.lower()


def test_validate_reference_sample_blocking_classification(monkeypatch, tmp_path):
    issue = voice_clone.validate_reference_sample("/nowhere/at/all.wav")
    assert issue is not None
    assert issue.blocking is True

    clip = tmp_path / "short.wav"
    clip.write_bytes(b"\x00")
    monkeypatch.setattr(voice_clone, "get_duration", lambda p: 1.0)
    issue = voice_clone.validate_reference_sample(str(clip))
    assert issue is not None
    assert issue.blocking is False


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
    assert issue.too_long is False  # nothing to auto-fix for "too short"


def test_validate_reference_sample_too_long(monkeypatch, tmp_path):
    clip = tmp_path / "long.wav"
    clip.write_bytes(b"\x00")
    monkeypatch.setattr(voice_clone, "get_duration", lambda p: 30.0)
    issue = voice_clone.validate_reference_sample(str(clip))
    assert issue is not None
    assert "long" in issue.message.lower()
    assert issue.too_long is True  # signals the caller can auto-trim


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
        voice_clone.generate(object(), "   ", ["/x.wav"], "/out.wav", consent_accepted=True)


def test_generate_raises_on_text_too_long():
    long_text = "a" * (voice_clone.MAX_TEXT_CHARS + 1)
    with pytest.raises(ValueError, match="characters"):
        voice_clone.generate(object(), long_text, ["/x.wav"], "/out.wav", consent_accepted=True)


def test_generate_without_reference_uses_design_or_auto(monkeypatch, tmp_path):
    calls: list[dict] = []

    class FakeModel:
        def generate(self, **kw):
            calls.append(kw)
            return [[0.0] * 2400]

    written: list = []
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(
        write=lambda path, data, sr: written.append((path, sr))))
    out = str(tmp_path / "o.wav")
    voice_clone.generate(FakeModel(), "hi", [], out, consent_accepted=False,
                         instruct="female, low pitch", language="en", speed=1.2)
    voice_clone.generate(FakeModel(), "hi", [], out, consent_accepted=False)
    assert calls[0] == {"text": "hi", "instruct": "female, low pitch",
                        "language": "en", "speed": 1.2}
    assert calls[1] == {"text": "hi"}
    assert len(written) == 2


def test_cloning_still_requires_consent():
    with pytest.raises(ValueError, match="Consent"):
        voice_clone.generate(object(), "hello", ["/x.wav"], "/out.wav", consent_accepted=False)


def test_build_instruct():
    assert voice_clone.build_instruct("female", None, "low pitch", whisper=True) == \
        "female, low pitch, whisper"
    assert voice_clone.build_instruct() == ""


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


# ---------- sweep_old_session_dirs -----------------------------------------


def test_sweep_old_session_dirs_removes_only_aged_out_dirs(monkeypatch, tmp_path):
    from core import config as _cfg
    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: tmp_path)

    root = tmp_path / "voice_clone"
    old_dir = root / "20200101-000000"
    fresh_dir = root / "20990101-000000"
    old_dir.mkdir(parents=True)
    fresh_dir.mkdir(parents=True)
    (old_dir / "sample_1.wav").write_bytes(b"\x00")
    (fresh_dir / "sample_1.wav").write_bytes(b"\x00")

    old_time = time.time() - 30 * 86400
    os.utime(old_dir, (old_time, old_time))

    voice_clone.sweep_old_session_dirs(max_age_days=7.0)

    assert not old_dir.exists()
    assert fresh_dir.exists()


def test_sweep_old_session_dirs_missing_root_is_a_noop(monkeypatch, tmp_path):
    from core import config as _cfg
    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: tmp_path)
    # No "voice_clone" dir exists under tmp_path at all -- must not raise.
    voice_clone.sweep_old_session_dirs()


# ---------- _concat_references cleans up its own temp file on failure -----


def test_concat_references_removes_temp_file_on_ffmpeg_failure(monkeypatch, tmp_path):
    seen: dict = {}

    def _fake_run(cmd, **kwargs):
        seen["out_path"] = cmd[-1]
        return types.SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    ref1 = tmp_path / "a.wav"
    ref2 = tmp_path / "b.wav"
    ref1.write_bytes(b"\x00")
    ref2.write_bytes(b"\x00")

    with pytest.raises(RuntimeError, match="Could not combine"):
        voice_clone._concat_references([str(ref1), str(ref2)])

    assert seen.get("out_path"), "fake subprocess.run was never called"
    assert not os.path.isfile(seen["out_path"]), "leaked temp WAV on ffmpeg failure"


def test_concat_references_keeps_temp_file_on_success(monkeypatch, tmp_path):
    def _fake_run(cmd, **kwargs):
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    ref1 = tmp_path / "a.wav"
    ref2 = tmp_path / "b.wav"
    ref1.write_bytes(b"\x00")
    ref2.write_bytes(b"\x00")

    out_path = voice_clone._concat_references([str(ref1), str(ref2)])
    try:
        assert os.path.isfile(out_path)
    finally:
        os.remove(out_path)


# ---------- trim_reference_sample ------------------------------------------


def test_trim_reference_sample_writes_to_output_path(monkeypatch, tmp_path):
    def _fake_run(cmd, **kwargs):
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00trimmed")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    src = tmp_path / "long.wav"
    src.write_bytes(b"\x00" * 100)
    dest = tmp_path / "out" / "trimmed.wav"

    voice_clone.trim_reference_sample(str(src), str(dest), max_seconds=10.0)

    assert dest.is_file()
    assert dest.read_bytes() == b"\x00trimmed"


def test_trim_reference_sample_raises_and_cleans_up_on_ffmpeg_failure(monkeypatch, tmp_path):
    def _fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    src = tmp_path / "long.wav"
    src.write_bytes(b"\x00")
    dest = tmp_path / "trimmed.wav"

    with pytest.raises(RuntimeError, match="Could not trim"):
        voice_clone.trim_reference_sample(str(src), str(dest))

    assert not dest.exists()
    # No stray "<dest>*"-prefixed staging file left behind in tmp_path either.
    assert list(tmp_path.iterdir()) == [src]
