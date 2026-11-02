"""Job progress stays monotonic across phases and frontend callbacks."""
import threading

import pytest
from hypothesis import given, settings, strategies as st

from core.job_progress import JobProgress


def test_out_of_order_updates_and_heartbeats():
    seen = []
    progress = JobProgress(seen.append, diarization=True)
    for phase, fraction in [("transcription", 1), ("diarization", 0),
                            ("diarization", 0.5), ("transcription", 0.2),
                            ("diarization", 0.1), ("diarization", 1),
                            ("finish", 1), ("transcription", 0)]:
        progress.update(phase, fraction)
    assert seen == [85, 85, 92, 92, 92, 99, 100, 100]


@pytest.mark.parametrize("enabled,end", [(True, 85), (False, 99)])
def test_slices_and_completion(enabled, end):
    seen = []
    progress = JobProgress(seen.append, diarization=enabled)
    progress.transcription(-200)
    progress.transcription(200)
    assert seen == [0, end]
    progress.finish()
    assert seen[-1] == 100


def test_nonfinite_updates_cannot_complete_job():
    seen = []
    progress = JobProgress(seen.append, diarization=True)
    for fraction in [float("nan"), float("inf"), -float("inf")]:
        assert progress.update("finish", fraction) == 0
    assert not seen


@settings(database=None)
@given(st.lists(st.tuples(st.sampled_from(["transcription", "diarization", "finish"]),
                         st.floats(allow_nan=True, allow_infinity=True)), max_size=100))
def test_progress_monotonic_property(updates):
    seen = []
    progress = JobProgress(seen.append, diarization=True)
    for phase, fraction in updates:
        progress.update(phase, fraction)
    assert seen == sorted(seen)
    assert all(0 <= percent <= 100 for percent in seen)


def test_callback_emission_is_serialized():
    seen = []
    progress = JobProgress(seen.append, diarization=True)
    threads = [threading.Thread(target=lambda: [progress.transcription(i) for i in range(100)])
               for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(seen) == 300
    assert seen == sorted(seen)
