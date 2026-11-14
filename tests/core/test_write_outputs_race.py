"""F1 repro: two parallel workers whose outputs share a stem both pick
collision index 0 (the exists-probe is not atomic with the write) and the
second os.replace overwrites the first transcript.

Simulated with two threads and a barrier inside the writer so both probe
before either publishes, which is what two workers finishing close together
do for real (same stem: a.mp4 + a.wav, or two clips of one file).
"""
from __future__ import annotations

import os
from pathlib import Path
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


def test_failed_claim_of_absent_name_is_never_published_to(tmp_path, monkeypatch):
    """A claim that fails on a name that looks absent must not authorise
    publishing there: a concurrent writer's file at that name survives."""
    base = str(tmp_path / "talk")
    target = tmp_path / "talk.srt"
    real_open = os.open

    def flaky_open(path, flags, *a, **k):
        if os.path.basename(str(path)) == "talk.srt":
            raise PermissionError(13, "Access is denied")
        return real_open(path, flags, *a, **k)

    def writer(segments, audio_path):
        # the concurrent writer wins the name between our check and replace
        target.write_bytes(b"concurrent transcript\n")
        return "mine\n"

    monkeypatch.setattr(os, "open", flaky_open)
    monkeypatch.setattr(tr, "get_writer", lambda name: writer)
    written = tr._write_outputs(base, [], str(tmp_path / "talk.mp4"), ["srt"])
    assert target.read_bytes() == b"concurrent transcript\n"
    assert [os.path.basename(p) for p in written] == ["talk (1).srt"]
    assert (tmp_path / "talk (1).srt").read_text(encoding="utf-8") == "mine\n"


def test_no_claimable_name_fails_instead_of_writing_unclaimed(tmp_path, monkeypatch):
    base = str(tmp_path / "talk")

    def deny(path, flags, *a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "open", deny)
    monkeypatch.setattr(tr, "get_writer", lambda name: lambda s, a: "x\n")
    import pytest
    with pytest.raises(RuntimeError):
        tr._write_outputs(base, [], str(tmp_path / "talk.mp4"), ["srt"])
    assert list(tmp_path.iterdir()) == []


def test_partial_writer_failure_keeps_checkpoint_and_successful_output(tmp_path, monkeypatch):
    """A requested format failing must not turn a resumable run into done."""
    from core.task import TranscriptionTask
    import pytest

    source = tmp_path / "resume.wav"
    source.write_bytes(b"audio")
    checkpoint = tmp_path / "resume.checkpoint"
    checkpoint.write_text("completed transcript", encoding="utf-8")
    task = TranscriptionTask(str(source))
    task.output_formats = ["srt", "json"]
    progress = []

    def writer(name):
        def render(segments, audio):
            if name == "json":
                raise PermissionError("selected JSON unavailable")
            return "saved transcript\n"
        return render

    monkeypatch.setattr(tr, "get_writer", writer)
    monkeypatch.setattr(tr._checkpoint, "delete_checkpoint", lambda _: checkpoint.unlink())
    monkeypatch.setattr(tr._checkpoint, "user_data_dir", lambda: tmp_path / "profile")
    with pytest.raises(RuntimeError, match="json"):
        tr._write_resumed_outputs(
            task, [{"start": 0., "end": 1., "text": "saved transcript"}],
            "en", 0, None, progress.append,
        )
    assert checkpoint.read_text(encoding="utf-8") == "completed transcript"
    assert progress == []
    assert len(task.output_paths) == 1
    assert Path(task.output_paths[0]).read_text(encoding="utf-8") == "saved transcript\n"
    recovery = list((tmp_path / "profile" / "transcript-recovery").glob("*.json"))
    assert len(recovery) == 1
    assert "saved transcript" in recovery[0].read_text(encoding="utf-8")


def test_partial_failure_preserves_outputs_when_recovery_cannot_be_written(tmp_path, monkeypatch):
    import pytest
    from core.task import TranscriptionTask

    for failure in (MemoryError("format OOM"), PermissionError("format denied")):
        source = str(tmp_path / (type(failure).__name__ + ".wav"))
        task = TranscriptionTask(source)
        calls = []

        def writer(name):
            def render(segments, audio):
                if name == "json":
                    raise failure
                return "saved text\n"
            return render

        def unavailable_recovery(*args):
            calls.append(True)
            raise OSError("recovery unavailable")

        monkeypatch.setattr(tr, "get_writer", writer)
        monkeypatch.setattr(tr, "_keep_output_recovery", unavailable_recovery)
        with pytest.raises(RuntimeError, match="json") as caught:
            tr._write_task_outputs(task, source[:-4], [], source, ["srt", "json"])
        assert caught.value.__cause__ is failure
        assert len(task.output_paths) == 1
        assert Path(task.output_paths[0]).read_text(encoding="utf-8") == "saved text\n"
        assert calls == ([] if isinstance(failure, MemoryError) else [True])
