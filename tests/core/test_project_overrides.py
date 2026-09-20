"""Tests for per-folder ``.whisperproject.json`` overrides."""
from __future__ import annotations

import json
import os

import pytest

from core.config import (
    PROJECT_FILE_NAME,
    find_project_file,
    load_project_overrides,
    merge_project_overrides,
)


def test_find_project_file_in_same_directory(tmp_path):
    f = tmp_path / PROJECT_FILE_NAME
    f.write_text("{}", encoding="utf-8")
    media = tmp_path / "show.mp4"
    media.write_bytes(b"x")
    assert find_project_file(str(media)) == f


def test_find_project_file_walks_up(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    f = tmp_path / PROJECT_FILE_NAME
    f.write_text("{}", encoding="utf-8")
    media = deep / "show.mp4"
    media.write_bytes(b"x")
    assert find_project_file(str(media)) == f


def test_find_project_file_none_when_absent(tmp_path):
    media = tmp_path / "show.mp4"
    media.write_bytes(b"x")
    assert find_project_file(str(media)) is None


def test_load_project_overrides_returns_dict(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({"output_formats": ["srt", "txt"], "hotwords": "Anthropic"}),
        encoding="utf-8",
    )
    out = load_project_overrides(str(tmp_path))
    assert out == {"output_formats": ["srt", "txt"], "hotwords": "Anthropic"}


def test_load_project_overrides_silent_on_bad_json(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text("{not valid", encoding="utf-8")
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_silent_on_non_object(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text("[1,2,3]", encoding="utf-8")
    assert load_project_overrides(str(tmp_path)) == {}


def test_merge_project_overrides_shallow_top_level(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({"hotwords": "OpenAI"}), encoding="utf-8"
    )
    base = {"hotwords": "", "output_formats": ["srt"]}
    out = merge_project_overrides(base, str(tmp_path / "a.wav"))
    assert out["hotwords"] == "OpenAI"
    assert out["output_formats"] == ["srt"]
    # Base must be unchanged (we deep-copied).
    assert base["hotwords"] == ""


def test_merge_project_overrides_nested_dict_one_level(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({"model": {"name": "tiny"}}), encoding="utf-8"
    )
    base = {"model": {"name": "large", "url": "https://example/"}, "device": "cpu"}
    out = merge_project_overrides(base, str(tmp_path / "a.wav"))
    assert out["model"]["name"] == "tiny"
    # The url key is preserved by the deep merge.
    assert out["model"]["url"] == "https://example/"
    assert out["device"] == "cpu"


def test_merge_project_overrides_no_file_returns_base(tmp_path):
    base = {"hotwords": "kept"}
    out = merge_project_overrides(base, str(tmp_path / "x.wav"))
    assert out == base


def test_merge_project_overrides_deep_merge_more_than_one_level(tmp_path):
    """Recursive deep-merge: a 3-level override keeps untouched
    leaf keys at every depth."""
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({"model": {"sub": {"deeper": 1}}}),
        encoding="utf-8",
    )
    base = {"model": {"sub": {"other": 2, "deeper": 0}, "name": "large"}}
    out = merge_project_overrides(base, str(tmp_path / "a.wav"))
    assert out["model"]["name"] == "large"
    assert out["model"]["sub"]["other"] == 2
    assert out["model"]["sub"]["deeper"] == 1


def test_load_project_overrides_silent_on_bad_encoding(tmp_path):
    """A file saved in cp1252 with non-UTF8 bytes must not crash —
    a corrupt project file should silently degrade."""
    raw = "{\"hotwords\": \"caf\xe9\"}".encode("cp1252")
    (tmp_path / PROJECT_FILE_NAME).write_bytes(raw)
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_drops_null_for_known_key(tmp_path):
    """A JSON null is never a valid value for a known key.

    It used to pass ``_validate_overrides`` untouched, so ``None`` reached the
    runtime coercions in ``core.transcriber._apply_runtime_overrides``
    (``int(config["diarization_num_speakers"])``), raising TypeError and
    failing the transcription for every file under that folder.
    """
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({
            "diarization_num_speakers": None,
            "diarization_cluster_threshold": None,
            "diarization_enabled": None,
            "output_formats": None,
        }),
        encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_never_raises_on_infinity(tmp_path):
    """``Infinity`` for an int-typed key used to raise OverflowError out of
    this "never raises" loader (``int(float('inf'))``). It must be dropped."""
    (tmp_path / PROJECT_FILE_NAME).write_text(
        '{"parallel_workers": Infinity}', encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_never_raises_on_numeric_overflow(tmp_path):
    """A finite-but-huge JSON integer (``1e400`` parses to inf; a long digit
    string stays an int) must not crash the numeric coercion either."""
    (tmp_path / PROJECT_FILE_NAME).write_text(
        '{"vad_threshold": ' + "9" * 400 + "}", encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_drops_nan_for_numeric_key(tmp_path):
    (tmp_path / PROJECT_FILE_NAME).write_text(
        '{"vad_threshold": NaN}', encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {}


def test_load_project_overrides_keeps_valid_values(tmp_path):
    """The valid-value path must be untouched by the null/non-finite guard."""
    (tmp_path / PROJECT_FILE_NAME).write_text(
        json.dumps({
            "diarization_num_speakers": 3,
            "diarization_cluster_threshold": 0.7,
            "diarization_enabled": True,
            "parallel_workers": 4,
            "vad_threshold": 0.25,
            "output_formats": ["srt"],
            "hotwords": "Anthropic",
        }),
        encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {
        "diarization_num_speakers": 3,
        "diarization_cluster_threshold": 0.7,
        "diarization_enabled": True,
        "parallel_workers": 4,
        "vad_threshold": 0.25,
        "output_formats": ["srt"],
        "hotwords": "Anthropic",
    }


def test_load_project_overrides_survives_deeply_nested_file(tmp_path):
    """A pathologically nested project file raises RecursionError from the
    JSON scanner — must be ignored like any malformed file, never raised."""
    (tmp_path / PROJECT_FILE_NAME).write_text(
        "[" * 100000 + "]" * 100000, encoding="utf-8",
    )
    assert load_project_overrides(str(tmp_path)) == {}


@pytest.mark.skipif(
    os.name != "nt",
    reason="This test monkeypatches os.name='nt'; on POSIX that makes pathlib build a "
    "WindowsPath (uninstantiable on Python <=3.12), which crashes pytest's own "
    "report machinery (INTERNALERROR). The UNC drive-mounted probe is a Windows-only "
    "path — _drive_is_mounted() returns True immediately off Windows.",
)
def test_drive_is_mounted_unc_skips_blocking_probe(monkeypatch):
    """UNC paths must not trigger a (potentially blocking) .exists()
    probe — the SMB timeout can be 30 s and would freeze launch."""
    from core import config as _cfg

    if not hasattr(_cfg, "_drive_is_mounted"):
        return  # private helper renamed/removed; skip
    monkeypatch.setattr(_cfg.os, "name", "nt")

    calls = {"exists": 0}
    original_exists = _cfg.Path.exists

    def _counting_exists(self):
        calls["exists"] += 1
        return original_exists(self)

    monkeypatch.setattr(_cfg.Path, "exists", _counting_exists)
    # A UNC path must return True without hitting Path.exists.
    assert _cfg._drive_is_mounted("\\\\server\\share\\file.wav") is True
    assert calls["exists"] == 0
