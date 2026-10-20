"""The Persian Nemotron recipe of the local transformers engine, without torch or a model.

The runner is a stand-in; the real model ran on a 73 s Persian phone call (11.5 s on a
4-core laptop CPU) before this code was written.
"""
from __future__ import annotations

import numpy as np
import pytest

from core import optional_deps
from core.backends import nvidia_asr as na

SR = na.TARGET_SR
real_outdated = optional_deps.outdated  # bound before conftest's autouse patch


@pytest.mark.parametrize(
    "spans,limit,total,expected",
    [
        ([], 10, 100, []),
        ([(0, 4), (5, 9)], 10, 100, [(0, 9)]),                  # neighbours join
        ([(0, 4), (8, 12)], 10, 100, [(0, 4), (8, 12)]),        # joined piece would be too long
        ([(0, 25)], 10, 100, [(0, 9), (9, 18), (18, 25)]),      # one long span: equal parts
        ([(-5, 3), (90, 120)], 10, 100, [(0, 3), (90, 100)]),   # clipped to the window
        ([(5, 5), (7, 6)], 10, 100, []),                        # empty spans dropped
        ([(0, 100), (20, 60)], 200, 200, [(0, 100)]),           # overlap never shortens a piece
        ([(0, 8), (5, 30)], 10, 100, [(0, 8), (8, 16), (16, 24), (24, 30)]),  # only the new part is added
        ([(0, 10)], 0, 100, []),                                # no limit: nothing (never divide by 0)
    ],
)
def test_group_speech(spans, limit, total, expected):
    assert na.group_speech(spans, limit, total) == expected


def test_group_speech_keeps_every_sample_of_every_span():
    spans = [(100, 900), (950, 4000), (4100, 4200), (9000, 30000)]
    pieces = na.group_speech(spans, 5000, 32000)
    assert all(0 < b - a <= 5000 for a, b in pieces)
    assert all(b0 <= a1 for (_a0, b0), (a1, _b1) in zip(pieces, pieces[1:]))  # in order, no overlap
    covered = set()
    for a, b in pieces:
        covered.update(range(a, b))
    assert all(s in covered for a, b in spans for s in range(a, b))


def test_speech_pieces_finds_nothing_in_silence():
    assert na.speech_pieces(np.zeros(SR * 5, dtype=np.float32)) == []


def test_speech_pieces_falls_back_without_vad(monkeypatch):
    import faster_whisper.vad as vad

    def broken(*_a, **_k):
        raise RuntimeError("no onnxruntime")

    monkeypatch.setattr(vad, "get_speech_timestamps", broken)
    assert na.speech_pieces(np.zeros(SR, dtype=np.float32)) is None


class _FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, audio):
        self.calls.append(len(audio))
        return f"  متن {len(self.calls)} "


def _ready_backend(monkeypatch, windows, pieces):
    be = na.NvidiaAsrBackend({"nvidia_asr_model_id": "mehdi-hf/nemotron-asr-streaming-farsi"})
    be._read_config()
    be._recipe = na.recipe_for(be._model_id)
    be._runner = _FakeRunner()  # type: ignore[assignment]
    be._ready = True
    monkeypatch.setattr(na, "plan_chunks", lambda *a, **k: windows)
    monkeypatch.setattr(na, "_decode_window", lambda path, a, b: np.ones(int((b - a) * SR), dtype=np.float32))
    monkeypatch.setattr(na, "speech_pieces", lambda audio: pieces)
    return be


def test_rnnt_segments_are_timed_per_piece_on_the_file_timeline(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 30.0), (30.0, 40.0)], [(SR, 3 * SR), (5 * SR, 9 * SR)])
    logs = []
    segs, info = be.transcribe_to_segments("x.wav", language="en", log_cb=logs.append, duration=40.0)
    assert [(s["start"], s["end"], s["text"]) for s in segs] == [
        (1.0, 3.0, "متن 1"), (5.0, 9.0, "متن 2"), (31.0, 33.0, "متن 3"), (35.0, 39.0, "متن 4"),
    ]
    assert be._runner.calls == [2 * SR, 4 * SR, 2 * SR, 4 * SR]  # type: ignore[union-attr]
    assert any("transcribes 'fa' only" in line for line in logs)  # English was picked
    assert info.language == "fa"  # what the model writes, not what was picked


def test_rnnt_without_vad_still_sends_pieces_within_the_limit(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 30.0)], None)
    segs, _ = be.transcribe_to_segments("x.wav", language="fa", duration=30.0)
    assert [(s["start"], s["end"]) for s in segs] == [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)]


@pytest.mark.parametrize("picked", [None, "en", "fa"])
def test_rnnt_reports_the_language_it_writes(monkeypatch, picked):
    # the writers use it for the script (right to left for Persian)
    be = _ready_backend(monkeypatch, [(0.0, 5.0)], [(0, SR)])
    _segs, info = be.transcribe_to_segments("x.wav", language=picked, duration=5.0)
    assert info.language == "fa"


def test_rnnt_skips_scraps_too_short_for_the_features(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 5.0)], [(0, SR), (2 * SR, 2 * SR + 100)])
    segs, _ = be.transcribe_to_segments("x.wav", language="fa", duration=5.0)
    assert len(segs) == 1 and be._runner.calls == [SR]  # type: ignore[union-attr]


def test_rnnt_waits_while_paused(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 5.0)], [(0, SR), (2 * SR, 3 * SR)])
    polls = {"n": 0}

    def paused():
        polls["n"] += 1
        return polls["n"] <= 2  # paused for the first two checks

    monkeypatch.setattr(na.time, "sleep", lambda _s: None)
    segs, _ = be.transcribe_to_segments("x.wav", language="fa", paused=paused, duration=5.0)
    assert len(segs) == 2 and polls["n"] >= 3


def test_rnnt_cancel_stops_between_pieces(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 30.0)], [(0, SR), (2 * SR, 3 * SR), (4 * SR, 5 * SR)])
    runner = be._runner

    def cancelled():
        return len(runner.calls) >= 1  # type: ignore[union-attr]

    segs, _ = be.transcribe_to_segments("x.wav", language="fa", cancelled=cancelled, duration=30.0)
    assert len(segs) == 1


def test_rnnt_failure_names_the_model(monkeypatch):
    be = _ready_backend(monkeypatch, [(0.0, 10.0)], [(0, SR)])

    def boom(_audio):
        raise ValueError("bad input")

    be._runner = boom  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="nemotron-asr-streaming-farsi failed: bad input"):
        be.transcribe_to_segments("x.wav", language="fa", duration=10.0)


def test_load_builds_the_rnnt_runner_not_the_pipeline(monkeypatch):
    built = {}

    class _Torch:
        float32 = "f32"

        class cuda:
            @staticmethod
            def is_available():
                return False

    monkeypatch.setattr(na, "_deps_available", lambda: True)
    monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: (_Torch, None))
    monkeypatch.setattr(na, "_build_pipeline", lambda *a: pytest.fail("pipeline used for an RNNT recipe"))

    def fake_build(model_id, device, dtype, recipe):
        built.update(model_id=model_id, device=device, dtype=dtype, language=recipe["language"])
        return _FakeRunner()

    monkeypatch.setattr(na, "_build_rnnt", fake_build)
    be = na.NvidiaAsrBackend({"nvidia_asr_model_id": "mehdi-hf/nemotron-asr-streaming-farsi"})
    assert be.load() is True
    assert built == {"model_id": "mehdi-hf/nemotron-asr-streaming-farsi", "device": "cpu", "dtype": "f32",
                     "language": "fa-IR"}


def test_load_upgrades_an_outdated_install_first(monkeypatch):
    state = {"stale": ["transformers 5.15.0 (needs >=5.18,<=5.20.2)"], "installs": []}
    monkeypatch.setattr(na, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: list(state["stale"]))
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps, "upgrade_plan", lambda feature: (["transformers>=5.18,<=5.20.2"], []))

    def fake_install(feature, log_cb=None, cancel_event=None, timeout=0, force=False, packages=None):
        state["installs"].append((feature, force, packages))
        state["stale"] = []
        return True

    monkeypatch.setattr(optional_deps, "install", fake_install)
    monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: pytest.fail("imported before the upgrade") if state["stale"] else (None, None))
    be = na.NvidiaAsrBackend({})
    be._update_outdated(None, None)
    assert state["installs"] == [("nvidia_asr", True, ["transformers>=5.18,<=5.20.2"])]  # torch is not downloaded again


def test_load_stops_when_the_upgrade_does_not_take(monkeypatch):
    monkeypatch.setattr(na, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: ["transformers 5.14.1 (needs >=5.18,<=5.20.2)"])
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps, "upgrade_plan", lambda feature: (["transformers>=5.18,<=5.20.2"], []))
    monkeypatch.setattr(optional_deps, "install", lambda *a, **k: True)
    be = na.NvidiaAsrBackend({})
    msgs = []
    assert be.load(msgs.append) is False
    assert "still out of date" in (be.get_error() or "")


def test_load_on_a_frozen_mac_says_it_cannot_update(monkeypatch):
    monkeypatch.setattr(na, "_deps_available", lambda: True)
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: ["transformers 5.15.0 (needs >=5.18,<=5.20.2)"])
    monkeypatch.setattr(optional_deps, "can_install", lambda: False)
    monkeypatch.setattr(optional_deps, "upgrade_plan", lambda feature: (["transformers>=5.18,<=5.20.2"], []))
    monkeypatch.setattr(optional_deps, "install", lambda *a, **k: pytest.fail("no pip in a frozen app"))
    be = na.NvidiaAsrBackend({})
    assert be.load() is False
    assert "needs an update" in (be.get_error() or "")


@pytest.mark.parametrize(
    "version,clauses,ok",
    [
        ("5.20.2", ">=5.18,<=5.20.2", True),
        ("5.18.0", ">=5.18,<=5.20.2", True),
        ("5.15.0", ">=5.18,<=5.20.2", False),
        ("5.21.0", ">=5.18,<=5.20.2", False),
        ("5.20.2.post1", ">=5.18,<=5.20.2", True),
        ("5.19.0rc1", ">=5.18,<=5.20.2", True),
        ("5.18.0rc1", ">=5.18,<=5.20.2", False),   # a pre-release comes before 5.18
        ("5.18.0.dev0", ">=5.18", False),
        ("5.20.0", "<=5.20", True),                # 5.20.0 is 5.20
        ("5.18", "==5.18.0", True),
        ("0.23.1", ">=0.23.1,<0.24", True),
        ("0.24.0", ">=0.23.1,<0.24", False),
        ("2.12.0+cpu", "", True),
    ],
)
def test_version_satisfies(version, clauses, ok):
    assert optional_deps.version_satisfies(version, clauses) is ok


def test_superseded_dist_infos(tmp_path):
    for name in ("transformers-5.15.0.dist-info", "transformers-5.20.2.dist-info", "tokenizers-0.22.2.dist-info",
                 "torch-2.9.0.dist-info", "Huggingface_Hub-1.14.0.dist-info", "transformers"):
        (tmp_path / name).mkdir()
    old = optional_deps._superseded_dist_infos(
        ["transformers", "transformers-5.20.2.dist-info", "huggingface_hub-1.33.0.dist-info"], str(tmp_path))
    assert sorted(p.split("\\")[-1].split("/")[-1] for p in old) == [
        "Huggingface_Hub-1.14.0.dist-info", "transformers-5.15.0.dist-info"]


def test_upgrade_plan_splits_our_copies_from_the_environments(monkeypatch, tmp_path):
    ours = tmp_path / "pylibs"
    ours.mkdir()

    class _Dist:
        def __init__(self, version, where):
            self.version, self._where = version, where

        def locate_file(self, _p):
            return self._where

    dists = {"transformers": _Dist("5.15.0", ours), "torch": _Dist("2.1.0", tmp_path / "site-packages")}

    def fake_distribution(name):
        if name not in dists:
            raise optional_deps.importlib.metadata.PackageNotFoundError(name)
        return dists[name]

    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(ours))
    monkeypatch.setattr(optional_deps, "activate", lambda: None)
    monkeypatch.setattr(optional_deps.importlib.metadata, "distribution", fake_distribution)
    assert optional_deps.upgrade_plan("nvidia_asr") == (["transformers>=5.18,<=5.20.2"], [])
    dists["transformers"] = _Dist("5.14.1", tmp_path / "site-packages")
    assert optional_deps.upgrade_plan("nvidia_asr") == ([], ["transformers 5.14.1 (needs >=5.18,<=5.20.2)"])


def test_an_outdated_copy_in_the_environment_is_not_downloaded_again(monkeypatch):
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: ["transformers 5.14.1 (needs >=5.18,<=5.20.2)"])
    monkeypatch.setattr(optional_deps, "upgrade_plan",
                        lambda feature: ([], ["transformers 5.14.1 (needs >=5.18,<=5.20.2)"]))
    monkeypatch.setattr(optional_deps, "install", lambda *a, **k: pytest.fail("pip for a package it cannot replace"))
    be = na.NvidiaAsrBackend({})
    assert be._update_outdated(None, None) is False
    assert "pip install -U" in (be.get_error() or "")


def test_outdated_reports_only_pinned_packages_outside_their_pin(monkeypatch):
    versions = {"transformers": "5.15.0", "torch": "2.1.0", "librosa": "0.9"}

    def fake_version(name):
        if name not in versions:
            raise optional_deps.importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(optional_deps.importlib.metadata, "version", fake_version)
    monkeypatch.setattr(optional_deps, "activate", lambda: None)
    assert real_outdated("nvidia_asr") == ["transformers 5.15.0 (needs >=5.18,<=5.20.2)"]
    versions["transformers"] = "5.20.2"
    assert real_outdated("nvidia_asr") == []
    del versions["transformers"]
    assert real_outdated("nvidia_asr") == []  # not installed: is_available decides, not this


def test_a_failed_or_cancelled_update_says_so(monkeypatch):
    monkeypatch.setattr(optional_deps, "outdated", lambda feature: ["transformers 5.15.0 (needs >=5.18,<=5.20.2)"])
    monkeypatch.setattr(optional_deps, "upgrade_plan", lambda feature: (["transformers>=5.18,<=5.20.2"], []))
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps, "install", lambda *a, **k: False)
    be = na.NvidiaAsrBackend({})
    assert be._update_outdated(None, None) is False
    err = be.get_error() or ""
    assert "Could not update" in err and "still out of date" not in err


@pytest.mark.parametrize("picked,warned", [("fa_IR", False), ("fa,fa-IR", False), ("FA", False), ("en-US", True)])
def test_language_note_reads_picker_codes(monkeypatch, picked, warned):
    be = _ready_backend(monkeypatch, [(0.0, 5.0)], [(0, SR)])
    logs = []
    be.transcribe_to_segments("x.wav", language=picked, log_cb=logs.append, duration=5.0)
    assert any("transcribes 'fa' only" in line for line in logs) is warned
