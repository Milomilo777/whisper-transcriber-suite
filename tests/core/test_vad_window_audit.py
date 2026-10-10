from core import vad_window

def test_window_seconds_audit_returns_0_on_nan():
    # Hypothesis: window_seconds returns 0.0 for NaN.
    assert vad_window.window_seconds({"vad_window_s": float("nan")}) == 0.0

def test_window_samples_audit_raises_on_nan_inf():
    # Defect Hypothesis: _window_samples raises ValueError or OverflowError on NaN/inf.
    # Fixed to return 0.
    assert vad_window._window_samples(float("nan"), 512) == 0
    assert vad_window._window_samples(float("inf"), 512) == 0

def test_whole_file_model_audit_handles_missing_call():
    class MissingCall:
        pass
    assert vad_window._whole_file_model(MissingCall) is False

def test_whole_file_model_audit_handles_wrong_signature():
    class WrongSig:
        def __call__(self, arg1):
            pass
    assert vad_window._whole_file_model(WrongSig) is False
