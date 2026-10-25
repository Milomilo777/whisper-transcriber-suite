def test_transcribe_inf_nan_duration(monkeypatch):
    from core.backends.nvidia_asr import NvidiaAsrBackend
    import core.backends.nvidia_asr as na

    b = NvidiaAsrBackend(config={})
    b._ready = True
    b._model = True
    b._pipe = lambda *a, **k: ({"text": "hi"}, False)

    # Monkeypatch get_duration to return something so we know it fell back
    # but we want it to fall back and then we intercept plan_chunks to see what it gets.
    import core.transcriber as t
    monkeypatch.setattr(t, "get_duration", lambda path: float('inf'))

    captured_durations = []
    # *args/**kwargs: the real call site has grown keyword-only planning
    # knobs (max_unknown_chunks); the interception itself is unchanged.
    def fake_plan_chunks(duration, chunk_seconds, *args, **kwargs):
        captured_durations.append(duration)
        return []

    monkeypatch.setattr(na, "plan_chunks", fake_plan_chunks)

    # We also mock _decode_window just in case, but plan_chunks returning [] prevents the loop from running.
    monkeypatch.setattr(na, "_decode_window", lambda *a, **k: None)

    b.transcribe_to_segments("dummy", duration=float('inf'))
    b.transcribe_to_segments("dummy", duration=float('nan'))

    assert captured_durations == [0.0, 0.0]
