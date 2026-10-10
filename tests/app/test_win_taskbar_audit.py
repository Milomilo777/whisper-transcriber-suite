import pytest
from app.theme import win_taskbar as wt

def test_badge_label_audit():
    """Characterization test for badge_label."""
    assert wt.badge_label(0) == "0"
    assert wt.badge_label(9) == "9"
    assert wt.badge_label(10) == "9+"
    assert wt.badge_label(-1) == "-1"

def test_render_badge_audit():
    """Characterization test for render_badge."""
    with pytest.raises(ValueError, match="badge size too small"):
        wt.render_badge("1", 7)
    
    with pytest.raises(ValueError, match="cannot draw badge text 'unknown'"):
        wt.render_badge("unknown", 16)
        
    with pytest.raises(ValueError, match="badge text '12345' does not fit 8 pixels"):
        wt.render_badge("12345", 8)

    bgra = wt.render_badge("9+", 16)
    assert len(bgra) == 16 * 16 * 4

def test_summarize_audit():
    """Characterization test for summarize."""
    class DummyTask:
        def __init__(self, status, progress=0):
            self.status = status
            self.progress = progress

    assert wt.summarize([], []) == wt.Snapshot()
    assert wt.summarize([DummyTask("waiting")], []) == wt.Snapshot(wt.TBPF_NOPROGRESS, 0, 1)
    
    # Check NaN and string handling via _percent
    assert wt.summarize([DummyTask("running", float('nan'))], []) == wt.Snapshot(wt.TBPF_INDETERMINATE, 0, 1)
    assert wt.summarize([DummyTask("running", "invalid")], []) == wt.Snapshot(wt.TBPF_INDETERMINATE, 0, 1)

def test_env_disabled_audit(monkeypatch):
    """Characterization test for env_disabled."""
    monkeypatch.delenv(wt.ENV_KILL_SWITCH, raising=False)
    assert wt.env_disabled() is False
    
    monkeypatch.setenv(wt.ENV_KILL_SWITCH, "1")
    assert wt.env_disabled() is True

def test_enabled_audit(monkeypatch):
    """Characterization test for enabled."""
    wt.set_enabled(True)
    monkeypatch.delenv(wt.ENV_KILL_SWITCH, raising=False)
    wt._session_off = False
    
    assert wt.enabled("win32") is True
    assert wt.enabled("linux") is False

def test_download_finished_for_user_audit():
    class DummyItem:
        def __init__(self, make_subbed_video=False):
            self.make_subbed_video = make_subbed_video
            
    assert wt._download_finished_for_user(DummyItem(), None) is False
    assert wt._download_finished_for_user(DummyItem(True), "burning") is True
    assert wt._download_finished_for_user(DummyItem(True), "transcribing") is True
    assert wt._download_finished_for_user(DummyItem(True), "running") is False
    assert wt._download_finished_for_user(DummyItem(False), "running") is True
    assert wt._download_finished_for_user(DummyItem(False), "paused") is True

def test_chime_on_audit():
    class RootMock:
        pass
    root = RootMock()
    assert wt._chime_on(root) is False
    
    class VarMock:
        def get(self): return 1
    root.chime_on_complete_var = VarMock()
    assert wt._chime_on(root) is True

def test_chained_audit():
    class TaskMock:
        pass
    task = TaskMock()
    assert wt._chained(task) is False
    
    task.source_download = TaskMock()
    task.source_download.make_subbed_video = True
    assert wt._chained(task) is True

def test_has_work_audit():
    class TaskMock:
        def __init__(self, status):
            self.status = status
            
    assert wt._has_work([], []) is False
    assert wt._has_work([TaskMock("waiting")], []) is True
    assert wt._has_work([TaskMock("error")], []) is True
    assert wt._has_work([TaskMock("finished")], []) is False

def test_average_audit():
    assert wt._average([]) == 0
    assert wt._average([10.5, 20.5]) == 16
    assert wt._average([10.6]) == 11

def test_percent_audit():
    assert wt._percent(50) == 50.0
    assert wt._percent(-10) == 0.0
    assert wt._percent(150) == 100.0
    assert wt._percent(float('nan')) == 0.0
    assert wt._percent(None) == 0.0
    assert wt._percent("abc") == 0.0

def test_clear_error_if_seen_audit():
    class NativeMock:
        def is_foreground(self, hwnd):
            return True
            
    class CtlMock:
        def __init__(self):
            self.error_since = None
            self.native = NativeMock()
            self.hwnd = 1
            
    ctl = CtlMock()
    # error_since is None, does nothing
    wt._clear_error_if_seen(ctl, 10.0)
    
    # Not enough time passed
    ctl.error_since = 9.0
    wt._clear_error_if_seen(ctl, 10.0)
    assert ctl.error_since == 9.0
    
    # Enough time passed and window in foreground -> clear
    ctl.error_since = 1.0
    wt._clear_error_if_seen(ctl, 10.0)
    assert ctl.error_since is None

def test_failed_round_audit():
    class CtlMock:
        def __init__(self):
            self.applied = wt.Snapshot()
            self.failures = 0
            
    ctl = CtlMock()
    
    wt._failed_round(ctl, "test")
    assert ctl.applied is None
    assert ctl.failures == 1
    
    # Max failures triggers give_up
    ctl.failures = wt.MAX_FAILURES - 1
    wt._failed_round(ctl, "test")
    assert ctl.failures == wt.MAX_FAILURES
    assert wt._session_off is True
    
    wt._session_off = False # Reset state

def test_note_failure_audit():
    wt._failed.clear()
    wt._note_failure("key1", "test %s", "arg")
    assert "key1" in wt._failed
    
    # Same key should not be logged again
    wt._note_failure("key1", "test %s", "arg")
    
    wt._failed.clear()

def test_is_withdrawn_audit():
    class RootMock:
        def state(self): return "withdrawn"
    assert wt._is_withdrawn(RootMock()) is True
    
    class RootMock2:
        def state(self): return "normal"
    assert wt._is_withdrawn(RootMock2()) is False
    
    class RootMock3:
        def state(self): raise ValueError("destroyed")
    assert wt._is_withdrawn(RootMock3()) is True

def test_marker_blocks_invalid_utf8_audit(tmp_path):
    marker = tmp_path / "marker"
    marker.write_bytes(b"\xff\xfe\x00\x00")
    # This raised UnicodeDecodeError before the fix. Now it returns True (blocks)
    # because it falls back to text = None, which then skips to the warning log.
    assert wt.marker_blocks(marker) is True

