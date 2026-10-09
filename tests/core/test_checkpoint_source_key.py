"""``core._checkpoint.source_key`` and the path helpers built on it.

A source path can hold lone surrogate code points: Windows allows unpaired
UTF-16 units in file names, and on POSIX Python maps undecodable name bytes
to surrogates (``surrogateescape``). The key must still be computed so the
checkpoint helpers answer "no checkpoint" instead of raising in the middle
of a transcription.
"""
from __future__ import annotations

import hashlib
import os
import re

import pytest

from core import _checkpoint as cp

_LONE_SURROGATE_NAMES = ["clip-\ud83d-a.mp4", "clip-\udc80-b.mp4"]


@pytest.fixture
def partials(monkeypatch, tmp_path):
    folder = tmp_path / "partials"
    folder.mkdir()
    monkeypatch.setattr(cp, "partials_dir", lambda: folder)
    return folder


def test_key_of_ordinary_path_is_the_sha1_of_the_normalised_path(tmp_path):
    path = str(tmp_path / "talk.mp4")
    expected = hashlib.sha1(
        os.path.normcase(os.path.abspath(path)).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    assert cp.source_key(path) == expected


def test_key_is_stable_and_differs_per_path(tmp_path):
    a = cp.source_key(str(tmp_path / "a.mp4"))
    assert a == cp.source_key(str(tmp_path / "a.mp4"))
    assert a != cp.source_key(str(tmp_path / "b.mp4"))


@pytest.mark.parametrize("name", _LONE_SURROGATE_NAMES)
def test_key_of_path_with_lone_surrogate_is_a_sha1(tmp_path, name):
    key = cp.source_key(str(tmp_path / name))
    assert re.fullmatch(r"[0-9a-f]{40}", key)


def test_different_lone_surrogates_get_different_keys(tmp_path):
    keys = {cp.source_key(str(tmp_path / n)) for n in _LONE_SURROGATE_NAMES}
    assert len(keys) == len(_LONE_SURROGATE_NAMES)


@pytest.mark.parametrize("name", _LONE_SURROGATE_NAMES)
def test_lookup_helpers_report_no_checkpoint_for_such_a_path(partials, tmp_path, name):
    path = str(tmp_path / name)
    assert cp.has_checkpoint(path) is False
    assert cp.load_checkpoint(path) is None
    cp.delete_checkpoint(path)  # must not raise
