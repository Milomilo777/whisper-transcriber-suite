"""Regression: write_checkpoint's tmp file must be unique per call.

Found by an adversarial review (2026-09-22): the tmp path used to be a
fixed ``<key>.json.tmp``, so two writers for the SAME source (e.g. two
app instances both resuming the same interrupted transcription) could
open/truncate/write the same inode, producing a torn final file despite
the os.replace rename being individually atomic. write_checkpoint now
uses tempfile.mkstemp for a name unique to each call.
"""
from __future__ import annotations

import json
import threading
import time

from core import _checkpoint as cp


def _write(source, suffix, barrier, errors):
    barrier.wait()
    try:
        cp.write_checkpoint(
            source,
            backend="faster_whisper",
            model_name=f"model-{suffix}",
            language="en",
            language_probability=0.9,
            cfg_fingerprint="x",
            last_end_time=float(suffix),
            segments=[{"start": 0.0, "end": float(suffix), "text": f"seg-{suffix}"}],
            checkpoint_time=time.time(),
        )
    except BaseException as e:  # noqa: BLE001
        errors.append(e)


def test_concurrent_writes_for_the_same_source_never_produce_a_torn_file(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    source = str(tmp_path / "audio.wav")
    (tmp_path / "audio.wav").write_bytes(b"x")

    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    threads = [
        threading.Thread(target=_write, args=(source, i, barrier, errors))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert all(not t.is_alive() for t in threads)
    assert not errors, f"a concurrent writer raised: {errors}"

    # No stray .tmp files left behind (each writer's own unique tmp was
    # renamed away or cleaned up on failure).
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"leaked tmp file(s): {leftover}"

    # Whichever writer's os.replace landed last, the result must be a
    # single, fully-valid JSON document -- never a torn/interleaved mix
    # of two writers' bytes.
    result = cp.load_checkpoint(source)
    assert result is not None, "final checkpoint file failed to load"
    path = cp.checkpoint_path(source)
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    json.loads(raw)  # raises if the bytes are interleaved/corrupt
