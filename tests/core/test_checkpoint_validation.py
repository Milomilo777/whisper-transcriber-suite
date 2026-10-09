"""Edge cases for ``core._checkpoint.validate_checkpoint``.

Each rejection branch must return a human-readable reason (the caller
deletes the stale partial and shows the text), and only a checkpoint that
matches the source file, backend, model and config fingerprint may resume.
Hermetic: real files under ``tmp_path``, no network, no model.
"""
from __future__ import annotations

import os

import pytest

from core._checkpoint import SCHEMA_VERSION, validate_checkpoint


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"0123456789")
    return p


def _payload(src, **overrides):
    st = os.stat(src)
    data = {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(src),
        "source_size": int(st.st_size),
        "source_mtime": float(st.st_mtime),
        "backend": "b",
        "model_name": "m",
        "config_fingerprint": "c",
        "segments": [],
    }
    data.update(overrides)
    return data


def _validate(data):
    return validate_checkpoint(
        data, backend="b", model_name="m", cfg_fingerprint="c"
    )


def test_matching_checkpoint_is_usable(source):
    assert _validate(_payload(source)) == ""


def test_non_dict_payload_is_rejected():
    assert _validate(["not", "a", "dict"]) == "checkpoint payload is not a dict"  # type: ignore[arg-type]


def test_other_schema_version_is_rejected(source):
    reason = _validate(_payload(source, schema_version=SCHEMA_VERSION + 1))
    assert "schema_version" in reason


@pytest.mark.parametrize("value", [None, "", 5])
def test_missing_or_non_string_source_path_is_rejected(source, value):
    assert _validate(_payload(source, source_path=value)) == (
        "checkpoint missing source_path"
    )


def test_payload_without_source_path_key_is_rejected(source):
    data = _payload(source)
    del data["source_path"]
    assert _validate(data) == "checkpoint missing source_path"


def test_source_that_no_longer_exists_is_rejected(source, tmp_path):
    gone = tmp_path / "gone.wav"
    reason = _validate(_payload(source, source_path=str(gone)))
    assert reason == f"source file no longer exists: {gone}"


def test_directory_in_place_of_source_is_rejected(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    reason = _validate(_payload(folder))
    assert reason.startswith("source file no longer exists")


def test_changed_size_is_rejected(source):
    reason = _validate(_payload(source, source_size=3))
    assert reason == "source file size has changed since checkpoint"


def test_missing_size_is_rejected(source):
    data = _payload(source)
    del data["source_size"]
    assert "size" in _validate(data)


def test_changed_mtime_is_rejected(source):
    st = os.stat(source)
    reason = _validate(_payload(source, source_mtime=st.st_mtime + 60.0))
    assert reason == "source file mtime has changed since checkpoint"


def test_sub_millisecond_mtime_drift_is_tolerated(source):
    st = os.stat(source)
    assert _validate(_payload(source, source_mtime=st.st_mtime + 0.0005)) == ""


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"backend": "other"}, "backend changed"),
        ({"model_name": "other"}, "model changed"),
        ({"config_fingerprint": "other"}, "config changed"),
    ],
)
def test_backend_model_and_config_mismatch_are_rejected(source, override, needle):
    assert needle in _validate(_payload(source, **override))


@pytest.mark.parametrize("segments", [None, "text", {"a": 1}])
def test_segments_must_be_a_list(source, segments):
    reason = _validate(_payload(source, segments=segments))
    assert reason == "checkpoint segments field is not a list"
