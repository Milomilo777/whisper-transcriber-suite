import pytest
import subprocess
from core.yt_dlp_update import run_killing_tree
import time

def test_run_killing_tree_subprocess_leak(monkeypatch):
    import sys
    # Create a simple python script that runs indefinitely
    # and if the tree leak exists, when we interrupt it with another exception
    # (not timeout), it will wait indefinitely.
    # Wait, we can mock communicate to raise a ValueError and see if we can catch it.

    class MockProcess:
        def __init__(self):
            self.pid = 12345
            self.returncode = None

        def communicate(self, timeout=None):
            raise ValueError("Some other error")

        def wait(self, timeout=None):
            return

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.wait() # Simulate what Popen.__exit__ does

        def poll(self):
            return None # Still running

    mock_proc = MockProcess()
    end_tree_called = []

    def mock_popen(*args, **kwargs):
        return mock_proc

    def mock_end_tree(proc):
        end_tree_called.append(proc)

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("core.yt_dlp_update._end_tree", mock_end_tree)

    with pytest.raises(ValueError):
        run_killing_tree(["some", "cmd"], timeout=1)

    assert end_tree_called == [mock_proc], "_end_tree should have been called for unhandled exception!"
