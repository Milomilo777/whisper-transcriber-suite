import pytest
from core.server import _download_url

def test_download_url_process_leak(tmp_path, monkeypatch):
    import subprocess

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.returncode = None
            self.killed = False

        def communicate(self, timeout=None):
            raise KeyboardInterrupt("Simulated interrupt")

        def kill(self):
            self.killed = True

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    import core.yt_dlp_update
    import contextlib
    @contextlib.contextmanager
    def fake_download_running():
        yield

    monkeypatch.setattr(core.yt_dlp_update, "download_running", fake_download_running)
    monkeypatch.setattr(core.yt_dlp_update, "resolve_yt_dlp_path", lambda: "fake_yt_dlp")

    killed = []
    def fake_kill_process_tree(proc, force=False):
        killed.append(proc)
        proc.killed = True

    # Needs to patch where it's used since it's imported via 'from ... import'
    import core.server
    monkeypatch.setattr(core.server, "kill_process_tree", fake_kill_process_tree, raising=False)
    # the function is defined in __init__.py, so we should also check that module specifically if it's separate
    # Actually _download_url is in core.server.__init__ and imports inside the function!
    # Wait, in the code, `from core._proc import kill_process_tree` is INSIDE _download_url.
    # Therefore it is dynamically loaded from core._proc during execution. Mocking core._proc should work!
    # But let's verify if communicate(timeout=10) also raises KeyboardInterrupt.
    # We should only raise on the first call.
    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.returncode = None
            self.killed = False
            self.comm_count = 0

        def communicate(self, timeout=None):
            self.comm_count += 1
            if self.comm_count == 1:
                raise KeyboardInterrupt("Simulated interrupt")
            return "", ""

        def kill(self):
            self.killed = True

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    import core._proc
    monkeypatch.setattr(core._proc, "kill_process_tree", fake_kill_process_tree)

    with pytest.raises(KeyboardInterrupt):
        _download_url("http://example.com", str(tmp_path))

    assert len(killed) == 1, "The process was not killed on KeyboardInterrupt!"
