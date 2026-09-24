"""Tests for the pure helpers inside ``core.transcriber``.

The transcribe/load_model paths require a real Whisper model and live audio,
so they're covered by the Phase 2a smoke test (``test_transcribe_smoke.py``).
This file exercises only the side-effect-free pieces.
"""
from __future__ import annotations

import logging
import subprocess
import sys

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    """Import core.transcriber with WhisperModel and torch stubbed.

    Importing for real loads faster-whisper and may trigger a model probe; we
    don't want that in unit tests. Stub before first import — but only if not
    already imported, to keep tests cheap when run together.
    """
    if "core.transcriber" not in sys.modules:
        import types as _t
        fake_fw = _t.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


def test_fmt_zero(transcriber):
    assert transcriber.fmt(0) == "00:00:00"


def test_fmt_minutes_only(transcriber):
    assert transcriber.fmt(125.7) == "00:02:05"


def test_fmt_includes_hours(transcriber):
    assert transcriber.fmt(3661.999) == "01:01:01"


def test_log_writes_to_callback(transcriber):
    captured = []
    transcriber.log("hello", captured.append)
    assert captured == ["hello"]


def test_log_falls_back_to_logger(transcriber, caplog):
    with caplog.at_level(logging.INFO, logger="core.transcriber"):
        transcriber.log("fallback", None)
    assert any("fallback" in r.message for r in caplog.records)


def test_bundled_binary_returns_name_when_missing(transcriber, tmp_path, monkeypatch):
    import core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "bin_dir", lambda: str(tmp_path / "no-such-dir"))
    assert transcriber.bundled_binary("ffmpeg") == "ffmpeg"


def test_bundled_binary_returns_full_path_when_present(transcriber, tmp_path, monkeypatch):
    import core.paths as paths_mod
    bin_dir_path = tmp_path / "bin"
    bin_dir_path.mkdir()
    import os
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    fake = bin_dir_path / exe_name
    fake.write_text("stub")
    monkeypatch.setattr(paths_mod, "bin_dir", lambda: str(bin_dir_path))
    result = transcriber.bundled_binary("ffmpeg")
    assert result == str(fake)


def test_is_model_ready_initially_false(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "MODEL_READY", False)
    assert transcriber.is_model_ready() is False


def test_get_model_error_returns_module_state(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "MODEL_ERROR", "something broke")
    assert transcriber.get_model_error() == "something broke"


def test_detect_device_respects_explicit_setting(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "config", {"device": "cpu", "compute_type": "int8"})
    device, ct = transcriber.detect_device()
    assert device == "cpu"
    assert ct == "int8"


def test_detect_device_auto_falls_back_to_cpu(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "config", {"device": "auto", "compute_type": "int8"})
    # Make both ctranslate2 and torch report no CUDA
    import sys as _sys
    fake_ct2 = type(_sys)("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "ctranslate2", fake_ct2)
    fake_torch = type(_sys)("torch")
    class _Cuda:
        @staticmethod
        def is_available():
            return False
    fake_torch.cuda = _Cuda  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "torch", fake_torch)
    device, ct = transcriber.detect_device()
    assert device == "cpu"


def test_load_existing_model_missing_path_sets_error(transcriber, monkeypatch, tmp_path):
    monkeypatch.setattr(transcriber, "config", {
        "model_path": str(tmp_path / "no-such-model"),
        "device": "cpu",
        "compute_type": "int8",
    })
    statuses: list[str] = []
    ok = transcriber.load_existing_model(statuses.append)
    assert ok is False
    assert any("missing" in s.lower() for s in statuses)
    assert transcriber.get_model_error()


# ------------------------------------------------------------- atomic write --


def test_write_outputs_is_atomic_on_success(transcriber, tmp_path, monkeypatch):
    """Each output writer runs to <path>.part then os.replace's onto
    the final name. After a clean run only the final file should
    exist; no .part leftovers."""
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["srt", "json"],
    })
    seg = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    base = str(tmp_path / "out")
    written = transcriber._write_outputs(base, seg, str(tmp_path / "out.mp4"))

    import os
    assert sorted(os.path.basename(p) for p in written) == ["out.json", "out.srt"]
    for p in written:
        assert os.path.isfile(p)
        assert os.path.getsize(p) > 0
    # No .part files should be left behind.
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    assert leftovers == [], f"leftover .part files: {leftovers}"


def test_write_outputs_cleans_up_part_on_failure(transcriber, tmp_path, monkeypatch):
    """If the writer raises mid-write, the .part file must be unlinked
    and the final file must not exist or remain at its previous state."""
    monkeypatch.setattr(transcriber, "config", {"output_formats": ["srt"]})

    def _boom(*_a, **_kw):
        raise RuntimeError("writer exploded")

    # Replace the SRT writer with one that always raises.
    monkeypatch.setattr(transcriber, "get_writer", lambda _name: _boom)

    base = str(tmp_path / "out")
    with pytest.raises(RuntimeError, match="writer exploded"):
        transcriber._write_outputs(base, [], str(tmp_path / "out.mp4"))

    import os
    assert not os.path.exists(base + ".srt")
    assert not os.path.exists(base + ".srt.part")


def test_write_outputs_isolates_one_failing_writer(transcriber, tmp_path, monkeypatch):
    """Audit [16]: one writer raising must NOT discard the formats that
    wrote fine, must unlink only the failed .part, and must NOT raise
    (some output is better than none)."""
    monkeypatch.setattr(transcriber, "config", {"output_formats": ["srt", "json"]})
    real_get = transcriber.get_writer

    def _boom(*_a, **_kw):
        raise RuntimeError("json writer exploded")

    def fake_get_writer(name):
        return _boom if name == "json" else real_get(name)

    monkeypatch.setattr(transcriber, "get_writer", fake_get_writer)

    base = str(tmp_path / "out")
    seg = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    written = transcriber._write_outputs(base, seg, str(tmp_path / "out.mp4"))

    import os
    # The good SRT survived; the failing JSON is excluded — no exception.
    assert [os.path.basename(p) for p in written] == ["out.srt"]
    assert os.path.isfile(base + ".srt")
    assert not os.path.exists(base + ".json")
    # The failed JSON .part was cleaned up; no leftovers.
    assert [f for f in os.listdir(tmp_path) if f.endswith(".part")] == []


def test_write_outputs_binary_docx_path(transcriber, tmp_path, monkeypatch):
    """``docx`` is binary: _write_outputs must open the .part file in
    "wb" mode, write the python-docx zip bytes, and rename atomically.
    Verify the zip magic bytes survive and no .part file remains."""
    monkeypatch.setattr(transcriber, "config", {"output_formats": ["docx"]})
    seg = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    base = str(tmp_path / "binout")
    written = transcriber._write_outputs(base, seg, str(tmp_path / "binout.mp4"))

    import os
    assert len(written) == 1
    docx_path = written[0]
    assert docx_path.endswith(".docx")
    with open(docx_path, "rb") as f:
        head = f.read(4)
    assert head == b"PK\x03\x04", f"docx is not a valid zip: head={head!r}"
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    assert leftovers == []


def test_write_outputs_mixed_text_and_binary(transcriber, tmp_path, monkeypatch):
    """SRT + DOCX together: text writer goes through utf-8 write,
    binary writer through wb. Both files exist with the right
    magic / shape, neither leaves a .part behind."""
    monkeypatch.setattr(transcriber, "config", {"output_formats": ["srt", "docx", "md"]})
    seg = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    base = str(tmp_path / "mixed")
    written = transcriber._write_outputs(base, seg, str(tmp_path / "mixed.mp4"))

    import os
    by_ext = {os.path.splitext(p)[1]: p for p in written}
    assert sorted(by_ext.keys()) == [".docx", ".md", ".srt"]
    for p in written:
        assert os.path.isfile(p) and os.path.getsize(p) > 0
    # Quick magic checks
    with open(by_ext[".docx"], "rb") as f:
        assert f.read(4) == b"PK\x03\x04"
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".part")]
    assert leftovers == []


# ----------------------------------------------------- filename templating --


def test_render_filename_template_default_legacy_layout(transcriber, tmp_path):
    out = transcriber._render_filename_template(
        "{base}.{ext}",
        base=str(tmp_path / "file"),
        ext="srt",
    )
    assert out == str(tmp_path / "file") + ".srt"


def test_render_filename_template_supports_lang_and_speaker_count(transcriber, tmp_path):
    base = str(tmp_path / "show")
    out = transcriber._render_filename_template(
        "{base}.{lang}.{speaker_count}sp.{ext}",
        base=base,
        ext="srt",
        lang="en",
        speaker_count=3,
    )
    assert out == f"{base}.en.3sp.srt"


def test_render_filename_template_injects_iso_date(transcriber, tmp_path):
    out = transcriber._render_filename_template(
        "{base}-{date}.{ext}",
        base=str(tmp_path / "show"),
        ext="json",
        date="2026-05-20",
    )
    assert out.endswith("-2026-05-20.json")


def test_render_filename_template_subdirectory(transcriber):
    """A template that wraps {base} in a sibling folder must produce a
    valid path; _write_outputs creates the dir during the actual write."""
    out = transcriber._render_filename_template(
        "transcripts/{base}.{ext}",
        base="myvideo",
        ext="srt",
    )
    assert out == "transcripts/myvideo.srt"


def test_render_filename_template_unknown_token_is_preserved(transcriber):
    out = transcriber._render_filename_template(
        "{base}.{nope}.{ext}",
        base="x",
        ext="srt",
    )
    assert out == "x.{nope}.srt"


def test_render_filename_template_malformed_falls_back(transcriber):
    """Unbalanced braces in a config string must not break the write."""
    out = transcriber._render_filename_template(
        "{base.{ext}",
        base="x",
        ext="srt",
    )
    assert out == "x.srt"


def test_render_filename_template_positional_token_falls_back(transcriber):
    """A template that uses positional `{0}` instead of named tokens
    must fall back to the legacy layout rather than embed a literal
    `{0}` in the filename or raise."""
    out = transcriber._render_filename_template(
        "{0}.{ext}",
        base="x",
        ext="srt",
    )
    assert out == "x.srt"


def test_render_filename_template_path_traversal_rejected(transcriber, tmp_path):
    """``../etc/passwd.{ext}`` and similar templates that try to
    escape the source-media folder must fall back to the legacy
    layout instead of resolving outside the base directory."""
    base = str(tmp_path / "show")
    out = transcriber._render_filename_template(
        "../../../etc/passwd.{ext}",
        base=base,
        ext="srt",
    )
    # Legacy fallback when path-traversal is detected.
    assert out == base + ".srt"


def test_render_filename_template_zero_speaker_count_is_empty(transcriber):
    """``{speaker_count}`` renders empty when diarisation produced 0
    speakers — keeps the default filename clean when the feature is off."""
    out = transcriber._render_filename_template(
        "{base}.{speaker_count}{ext}",
        base="x",
        ext=".srt",
        speaker_count=0,
    )
    assert out == "x..srt"


def test_write_outputs_honours_template_config(transcriber, tmp_path, monkeypatch):
    """End-to-end: a template with {lang} + {speaker_count} produces
    the matching final filename, including the new path."""
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["srt"],
        "output_filename_template": "{base}.{lang}.{speaker_count}sp.{ext}",
    })
    seg = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    base = str(tmp_path / "show")
    written = transcriber._write_outputs(
        base, seg, str(tmp_path / "show.mp4"),
        lang="en", speaker_count=2,
    )
    import os
    assert len(written) == 1
    assert os.path.basename(written[0]) == "show.en.2sp.srt"
    assert os.path.isfile(written[0])


def test_write_outputs_raises_when_all_formats_unknown(transcriber, tmp_path, monkeypatch):
    """If the user has every output_format key spelled wrong (typo
    in the config, broken downstream tool clearing the list), the
    function used to return an empty list and the caller would log
    "Wrote 0 output file(s)" with no error. Now it must raise so the
    user gets a real, debuggable failure. Guard rail for audit A5."""
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["totally-bogus", "also-wrong"],
    })
    with pytest.raises(RuntimeError, match="None of the requested output formats"):
        transcriber._write_outputs(
            str(tmp_path / "out"), [{"start": 0, "end": 1, "text": "x"}],
            str(tmp_path / "out.mp4"),
        )


def test_write_outputs_silently_skips_unknown_in_mixed_list(transcriber, tmp_path, monkeypatch):
    """Mixed list (one known, one unknown) keeps the old skip
    behaviour — the known format still writes, the unknown is
    ignored. We only escalate to RuntimeError when EVERYTHING is
    unknown."""
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["srt", "totally-bogus"],
    })
    written = transcriber._write_outputs(
        str(tmp_path / "out"), [{"start": 0, "end": 1, "text": "hello"}],
        str(tmp_path / "out.mp4"),
    )
    assert len(written) == 1
    assert written[0].endswith(".srt")


def test_run_post_pipeline_flags_hallucinations_when_enabled(transcriber, monkeypatch):
    """With diarisation+alignment off and the detector enabled (default),
    suspect segments must be annotated by the post-pipeline pass."""
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": False,
        "alignment": "none",
        "hallucination_detect_enabled": True,
    })

    class _Task:
        file_path = "/dev/null"
        cancelled = False

    segs = [
        {"start": 0.0, "end": 1.0, "text": "Welcome back."},
        {"start": 1.0, "end": 2.0, "text": "Thanks for watching!"},
    ]
    n = transcriber._run_post_pipeline(_Task(), segs, "en", None)
    assert n == 0  # speaker_count
    assert segs[0].get("suspect") is None
    assert segs[1].get("suspect") is True
    assert segs[1]["suspect_reason"] == "bag-of-hallucinations"


def test_run_post_pipeline_respects_disabled_flag(transcriber, monkeypatch):
    """When ``hallucination_detect_enabled=False`` no segment is flagged
    even if it matches a known hallucination phrase."""
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": False,
        "alignment": "none",
        "hallucination_detect_enabled": False,
    })

    class _Task:
        file_path = "/dev/null"
        cancelled = False

    segs = [{"start": 0.0, "end": 1.0, "text": "Thanks for watching!"}]
    transcriber._run_post_pipeline(_Task(), segs, "en", None)
    assert segs[0].get("suspect") is None


def test_write_outputs_template_creates_subdirectories(transcriber, tmp_path, monkeypatch):
    """A template that nests outputs in a sibling folder must create
    that folder on the fly."""
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["srt"],
        "output_filename_template": "{base}/transcripts/{ext}.out",
    })
    seg = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    base = str(tmp_path / "show")
    written = transcriber._write_outputs(base, seg, str(tmp_path / "show.mp4"))
    import os
    assert len(written) == 1
    assert os.path.isfile(written[0])
    assert "transcripts" in written[0]


# -------------------------------------------------- slice temp-file hygiene --


def test_slice_audio_removes_partial_on_ffmpeg_failure(transcriber, tmp_path, monkeypatch):
    """ffmpeg opens its output before it knows the input decodes; a
    failed slice that exits non-zero must not leave a partial
    ``.slice.wav`` behind (callers only clean up the success path)."""
    out_dir = tmp_path / "partials"

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        with open(cmd[-1], "wb") as f:
            f.write(b"partial-header")
        return subprocess.CompletedProcess(cmd, 1, b"", b"decoder blew up")

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="ffmpeg slice failed"):
        transcriber._slice_audio_from("source.mp4", 10.0, out_dir, end_seconds=20.0)
    assert list(out_dir.glob("*.slice.wav")) == []


def test_slice_audio_removes_partial_on_timeout(transcriber, tmp_path, monkeypatch):
    """subprocess.run kills a timed-out ffmpeg, but the file ffmpeg had
    already opened survives the kill — clean it up on the raise path."""
    out_dir = tmp_path / "partials"

    def fake_run(cmd, timeout=None, **kwargs):  # noqa: ARG001
        with open(cmd[-1], "wb") as f:
            f.write(b"partial-header")
        raise subprocess.TimeoutExpired(cmd, timeout or 0)

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="timed out slicing"):
        transcriber._slice_audio_from("source.mp4", 10.0, out_dir)
    assert list(out_dir.glob("*.slice.wav")) == []


def test_slice_audio_keeps_the_slice_on_success(transcriber, tmp_path, monkeypatch):
    """Control: a successful slice is returned and left on disk for the
    caller to transcribe (and for the caller's finally to delete)."""
    out_dir = tmp_path / "partials"

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        with open(cmd[-1], "wb") as f:
            f.write(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)
    out = transcriber._slice_audio_from("source.mp4", 0.0, out_dir, end_seconds=5.0)
    import os
    assert os.path.isfile(out)
    assert out.endswith(".slice.wav")
