"""core.stats must keep its "stats never break anything" promise even when
the psutil wheel is missing (e.g. a source checkout whose venv predates the
1.5.0 requirements bump). Before the guard, ``import core.stats`` itself
raised ImportError — which would have propagated out of the task-done
handler that imports it.

The block is simulated by planting ``sys.modules["psutil"] = None`` (the
canonical way to force ImportError for an import statement) and reloading
the module; the finally-block restores the real module for the rest of the
suite.
"""
from __future__ import annotations

import importlib
import sys


def test_stats_import_and_payload_survive_missing_psutil():
    import core.stats as stats_mod

    orig = sys.modules.get("psutil")
    sys.modules["psutil"] = None  # type: ignore[assignment]
    try:
        reloaded = importlib.reload(stats_mod)
        assert reloaded.psutil is None

        payload = reloaded.build_stats_payload(
            model="large-v3",
            language="en",
            audio_duration=12.5,
            transcription_time=3.25,
            status="done",
            word_count=42,
        )
        # The two psutil-backed fields degrade to "0"...
        assert payload["cpu_count"] == "0"
        assert payload["mem_total"] == "0"
        # ...while everything else still works normally.
        assert payload["model"] == "large-v3"
        assert payload["word_count"] == "42"
        assert payload["audio_duration"] == "12.500"
    finally:
        if orig is not None:
            sys.modules["psutil"] = orig
        else:
            sys.modules.pop("psutil", None)
        importlib.reload(stats_mod)


def test_stats_payload_uses_real_psutil_when_present():
    import core.stats as stats_mod

    assert stats_mod.psutil is not None
    payload = stats_mod.build_stats_payload(
        model="m", language="", audio_duration=0.0,
        transcription_time=0.0, status="done", word_count=0,
    )
    assert int(payload["cpu_count"]) >= 1
    assert int(payload["mem_total"]) > 0
