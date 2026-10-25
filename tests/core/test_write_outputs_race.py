"""F1 repro: two parallel workers whose outputs share a stem both pick
collision index 0 (the exists-probe is not atomic with the write) and the
second os.replace overwrites the first transcript.

Simulated with two threads and a barrier inside the writer so both probe
before either publishes, which is what two workers finishing close together
do for real (same stem: a.mp4 + a.wav, or two clips of one file).
"""
from __future__ import annotations

import os
import threading

import core.transcriber as tr


def test_two_sources_same_stem_lose_one_transcript(tmp_path, monkeypatch):
    base = str(tmp_path / "talk")
    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, list[str]] = {}

    def slow_writer(segments, audio_path):
        barrier.wait()  # both threads have probed the index by now
        return f"transcript of {os.path.basename(audio_path)}\n"

    monkeypatch.setattr(tr, "get_writer", lambda name: slow_writer)

    errors: dict[str, str] = {}

    def run(src: str) -> None:
        try:
            results[src] = tr._write_outputs(
                base, [{"start": 0.0, "end": 1.0, "text": "hi"}], src, ["srt"]
            )
        except Exception as e:  # noqa: BLE001 - recorded, see the assertion
            results[src] = []
            errors[src] = f"{type(e).__name__}: {e}"

    threads = [
        threading.Thread(target=run, args=(str(tmp_path / "talk.mp4"),)),
        threading.Thread(target=run, args=(str(tmp_path / "talk.wav"),)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    written = sorted(p for paths in results.values() for p in paths)
    on_disk = sorted(str(p) for p in tmp_path.glob("talk*.srt"))
    # Expected: two distinct transcripts on disk, both runs successful.
    # Observed: either both "succeed" and one overwrote the other (POSIX), or the
    # two os.replace calls collide and one run fails with WinError 5 (Windows).
    assert not errors and len(on_disk) == 2, (
        f"on disk {on_disk}; reported {written}; errors {errors}"
    )


def test_failed_writer_removes_only_its_own_placeholder(tmp_path, monkeypatch):
    """A writer failure must not leave an empty claimed file behind, and a
    file that already existed (an earlier run) must never be removed."""
    base = str(tmp_path / "talk")
    (tmp_path / "talk.srt").write_text("earlier run", encoding="utf-8")

    def ok_writer(segments, audio_path):
        return "new\n"

    def bad_writer(segments, audio_path):
        raise ValueError("boom")

    monkeypatch.setattr(
        tr, "get_writer", lambda name: bad_writer if name == "json" else ok_writer
    )
    written = tr._write_outputs(base, [], str(tmp_path / "talk.mp4"), ["srt", "json"])
    assert [os.path.basename(p) for p in written] == ["talk (1).srt"]
    assert (tmp_path / "talk.srt").read_text(encoding="utf-8") == "earlier run"
    assert not (tmp_path / "talk (1).json").exists()
    assert not (tmp_path / "talk.json").exists()
    assert (tmp_path / "talk (1).srt").read_text(encoding="utf-8") == "new\n"


def test_claim_error_on_existing_file_never_overwrites_it(tmp_path, monkeypatch):
    """A transient PermissionError (scanner) when claiming an EXISTING name
    must move to the next index, not authorise overwriting that file."""
    base = str(tmp_path / "talk")
    existing = tmp_path / "talk.srt"
    existing.write_bytes(b"earlier transcript\n")
    real_open = os.open

    def flaky_open(path, flags, *a, **k):
        if os.path.basename(str(path)) == "talk.srt":
            raise PermissionError(13, "Access is denied")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", flaky_open)
    monkeypatch.setattr(tr, "get_writer", lambda name: lambda seg, ap: "new\n")
    written = tr._write_outputs(base, [], str(tmp_path / "talk.mp4"), ["srt"])
    assert existing.read_bytes() == b"earlier transcript\n"
    assert [os.path.basename(p) for p in written] == ["talk (1).srt"]


def test_all_writers_failing_leaves_no_claim_files(tmp_path, monkeypatch):
    """Every unpublished claim, the chapters sidecar included, is removed."""
    base = str(tmp_path / "talk")

    def bad(seg, ap):
        raise ValueError("boom")

    monkeypatch.setattr(tr, "get_writer", lambda name: bad)
    chapters = [{"start": 0.0, "title": "One"}]
    import pytest
    with pytest.raises(RuntimeError):
        tr._write_outputs(
            base, [], str(tmp_path / "talk.mp4"), ["srt", "json"], chapters=chapters
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == []
