"""Edge cases for ``core.yt_dlp_update``: state records, seeding and result texts.

Covers how version records are read back (``_as_version``, ``_known_version``),
which records ``refresh_state`` carries over, that a failed state write or a
failed seed leaves no temporary file behind, and the plain-text results.
Hermetic: the cache folder is redirected under ``tmp_path`` and no yt-dlp is
started.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import core.yt_dlp_update as ytu
from core import offline


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "cache"
    folder.mkdir()
    monkeypatch.setattr(ytu, "cached_dir", lambda: folder)
    # An absolute path that does not exist: no bundled build is recorded.
    monkeypatch.setattr(ytu, "bundled_binary", lambda _name: str(tmp_path / "absent"))
    return folder


# --- reading versions back ---------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([2026, 9, 1], (2026, 9, 1)),
        ((2026, 9, 1), (2026, 9, 1)),
        ([1, True, 3], ()),  # a bool is an int to Python but not a version part
        ([1, 2, "3"], ()),
        ([1, 2.0], ()),
        ("2026.09.01", ()),
        (None, ()),
        ([], ()),
    ],
)
def test_as_version_accepts_only_whole_numbers(value, expected):
    assert ytu._as_version(value) == expected


def test_known_version_is_given_only_for_exactly_the_recorded_file():
    fp = [100, 200]
    good = {"path": "p", "fingerprint": fp, "version": [1, 2]}
    assert ytu._known_version(good, fp, path="p") == (1, 2)

    assert ytu._known_version(good, None, path="p") == ()  # file is gone
    assert ytu._known_version(good, [99, 99], path="p") == ()  # file changed
    assert ytu._known_version({**good, "path": "other"}, fp, path="p") == ()
    assert ytu._known_version({**good, "rejected": True}, fp, path="p") == ()
    assert ytu._known_version({**good, "version": "1.2"}, fp, path="p") == ()
    assert ytu._known_version({**good, "version": []}, fp, path="p") == ()
    assert ytu._known_version([1, 2, 3], fp, path="p") == ()  # not a record


def test_refresh_state_keeps_the_records_it_does_not_own(cache):
    ytu._save_state({
        "unsupported": {"path": "a", "fingerprint": [1, 2]},
        "bootstrap_refused": {"until": "2026-10-01T00:00:00+00:00"},
        "onedir": {"name": "onedir-1"},
        "onedir_retired": [{"name": "onedir-0"}],
    })

    state = ytu.refresh_state(version_of=lambda _path: (1, 2, 3))

    assert state["unsupported"] == {"path": "a", "fingerprint": [1, 2]}
    assert state["bootstrap_refused"] == {"until": "2026-10-01T00:00:00+00:00"}
    assert state["onedir"] == {"name": "onedir-1"}
    assert state["onedir_retired"] == [{"name": "onedir-0"}]
    assert "bundled" not in state and "cached" not in state


def test_refresh_state_drops_records_of_the_wrong_shape(cache):
    ytu._save_state({"unsupported": [1, 2, 3], "onedir_retired": "not a list"})
    state = ytu.refresh_state(version_of=lambda _path: (1, 2, 3))
    assert "unsupported" not in state
    assert "onedir_retired" not in state


# --- writing the state and seeding the copy ----------------------------------


def test_a_state_that_cannot_be_written_keeps_the_old_file_and_leaves_no_scratch(cache):
    ytu._save_state({"bundled": {"version": [1]}})
    with pytest.raises(TypeError):
        ytu._save_state({"bad": {1, 2, 3}})  # a set is not JSON

    assert json.loads((cache / "state.json").read_text(encoding="utf-8")) == {
        "bundled": {"version": [1]}
    }
    assert [p.name for p in cache.iterdir()] == ["state.json"]


def test_a_failed_seed_leaves_no_copy_behind_and_keeps_the_target(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.write_text("new build", encoding="utf-8")
    target = tmp_path / "cache" / "yt-dlp"
    target.parent.mkdir()
    target.write_text("old build", encoding="utf-8")

    real_replace = os.replace

    def refuse(src, dst, **kwargs):
        if str(src).endswith(".copy"):
            raise PermissionError("in use")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        ytu._seed(str(bundled), target)

    assert target.read_text(encoding="utf-8") == "old build"
    assert sorted(p.name for p in target.parent.iterdir()) == ["yt-dlp"]


def test_a_successful_seed_replaces_the_target(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.write_text("new build", encoding="utf-8")
    target = tmp_path / "cache" / "yt-dlp"

    ytu._seed(str(bundled), target)

    assert target.read_text(encoding="utf-8") == "new build"
    assert sorted(p.name for p in target.parent.iterdir()) == ["yt-dlp"]


# --- texts and results -------------------------------------------------------


def test_version_label_pads_every_part_after_the_first():
    assert ytu.version_label([2026, 9, 1]) == "2026.09.01"
    assert ytu.version_label([2026]) == "2026"
    assert ytu.version_label([0, 0, 0]) == "0.00.00"
    assert ytu.version_label([]) == ""


@pytest.mark.parametrize("status", ["offline", "busy", "unsupported", "unknown"])
def test_result_text_passes_the_message_of_other_statuses_through(status):
    result = ytu.UpdateResult(status=status, message="plain sentence")
    assert ytu.result_text(result) == "plain sentence"


def test_update_is_refused_while_working_offline(monkeypatch):
    monkeypatch.setattr(ytu, "can_self_update", lambda _bundled: True)
    monkeypatch.setattr(offline, "is_offline", lambda: True)

    result = ytu.update_cached_copy()

    assert result.status == "offline"
    assert result.message
    assert result.completed is False


def test_bidi_marks_do_not_hide_an_outdated_sign(monkeypatch):
    monkeypatch.setattr(ytu, "find_deno", lambda: None)
    outdated = "‏ signature extraction failed ‎ سلام"
    other = "ERROR: ‏ unable to download video data ‎ سلام"
    assert ytu.should_offer_update(outdated) is True
    assert ytu.should_offer_update(other) is False
