import pytest
from core.speed_meter import (
    format_duration,
    format_speed,
    format_time_left,
    SpeedMeter,
    device_label,
    summary_line,
    _opt_float,
    reset_speed,
    apply_live_speed,
    apply_final_speed,
    speed_cell,
    task_summary_line,
)

class TestSpeedMeterFormat:
    def test_format_duration(self):
        assert format_duration(0.5) == "under 1 s"
        assert format_duration(59.4) == "59 s"
        assert format_duration(60) == "1 min"
        assert format_duration(61) == "1 min 1 s"
        assert format_duration(3600) == "1 h"
        assert format_duration(3660) == "1 h 1 min"
        assert format_duration(3661) == "1 h 1 min"
        assert format_duration(float('nan')) == "under 1 s"
        assert format_duration(float('inf')) == "under 1 s"
        assert format_duration(-10.0) == "under 1 s"

    def test_format_speed(self):
        assert format_speed(None) == ""
        assert format_speed(-1) == ""
        assert format_speed(0) == ""
        assert format_speed(0.05) == "under 0.1x"
        assert format_speed(11.54) == "11.5x"
        assert format_speed(100.1) == "100x"
        assert format_speed(float('inf')) == ""
        assert format_speed(float('nan')) == ""

    def test_format_time_left(self):
        assert format_time_left(None) == ""
        assert format_time_left(-1) == "audio done"
        assert format_time_left(0) == "audio done"
        assert format_time_left(0.5) == "under 1 min left"
        assert format_time_left(59) == "under 1 min left"
        assert format_time_left(60) == "1 min left"
        assert format_time_left(61) == "2 min left"
        assert format_time_left(3600) == "1 h left"
        assert format_time_left(3660) == "1 h 1 min left"
        assert format_time_left(float('inf')) == ""
        assert format_time_left(float('nan')) == ""

    def test_device_label(self):
        assert device_label("cuda:0") == "GPU"
        assert device_label("gpu") == "GPU"
        assert device_label("cpu") == "CPU"
        assert device_label("mps") == "Apple GPU"
        assert device_label("metal") == "Apple GPU"
        assert device_label("") == ""

    def test_summary_line(self):
        assert summary_line(0, 10) == ""
        assert summary_line(10, 0.5) == ""
        assert summary_line(10, 10) == "10 s of audio transcribed in 10 s (1.0x)"
        assert summary_line(10, 20) == "10 s of audio transcribed in 20 s (0.5x, slower than the recording plays)"
        assert summary_line(3600, 360, model="faster-whisper-small", device="cuda:0", resumed=True) == "1 h of audio transcribed in 6 min (10.0x) with small on GPU, counting only the part done after resuming"

    def test_opt_float(self):
        assert _opt_float(None) is None
        assert _opt_float("123.4") == 123.4
        assert _opt_float("inf") is None
        assert _opt_float("nan") is None
        assert _opt_float("-1.0") is None
        assert _opt_float(0.0) == 0.0

class TestSpeedMeterTaskFields:
    class DummyTask:
        pass

    def test_apply_live_speed(self):
        t = self.DummyTask()
        apply_live_speed(t, {"speed_live": False, "speed_x": 2.0, "eta_s": 10.0})
        assert t.speed_live is False
        assert t.live_speed_x == 2.0
        assert t.live_eta_s == 10.0
        
        # update with None and check formatting
        t.status = "running"
        t.paused = False
        assert speed_cell(t) == "shown when done"

    def test_apply_final_speed(self):
        t = self.DummyTask()
        apply_final_speed(t, {"speed_x": 5.0, "speed_audio_s": 10.0, "speed_seconds": 2.0, "speed_resumed": True, "model": "large", "device": "cpu"})
        assert t.speed_x == 5.0
        assert t.speed_audio_s == 10.0
        assert t.speed_seconds == 2.0
        assert t.speed_resumed is True
        assert t.speed_model == "large"
        assert t.speed_device == "cpu"
        assert t.live_eta_s is None
        assert task_summary_line(t) == "10 s of audio transcribed in 2 s (5.0x) with large on CPU, counting only the part done after resuming"

class TestSpeedMeter:
    def test_basic_eta(self):
        sm = SpeedMeter(end_pos_s=100.0, start_pos_s=0.0)
        sm._clock = lambda: 0.0
        sm.start()
        sm.update(10.0)
        
        sm._clock = lambda: 10.0
        sm.update(50.0) # speed = 40/10 = 4.0, ETA = 12.5
        assert sm.speed_x == 4.0
        assert sm.eta_s == 12.5
        
        sm._clock = lambda: 20.0
        sm.update(50.0) # dt=20, dp=40 -> speed=2.0
        assert sm.eta_s == pytest.approx(11.353, 0.01)

    def test_zero_dt_speed(self):
        sm = SpeedMeter(end_pos_s=100.0)
        sm._clock = lambda: 10.0
        sm.start()
        sm.update(10.0)
        
        # dt = 0 but diff > 0
        sm._clock = lambda: 10.0
        sm.update(20.0)
        assert sm.speed_x is None

    def test_negative_elapsed(self):
        sm = SpeedMeter(end_pos_s=100.0)
        sm._clock = lambda: 10.0
        sm.start()
        sm._clock = lambda: 5.0
        assert sm.elapsed() == 0.0

    def test_finish(self):
        sm = SpeedMeter(end_pos_s=100.0)
        sm._clock = lambda: 0.0
        sm.start()
        sm._clock = lambda: 10.0
        sm.update(50.0)
        sm.finish()
        
        assert sm.eta_s == 0.0
        assert sm.audio_s == 100.0
        assert sm.average_x == 10.0
        
    def test_unknown_length(self):
        sm = SpeedMeter(end_pos_s=0.0) # 0 <= start_pos 0 means unknown
        sm._clock = lambda: 0.0
        sm.start()
        sm.update(10.0)
        
        sm._clock = lambda: 10.0
        sm.update(50.0)
        assert sm.speed_x is not None
        assert sm.eta_s is None
