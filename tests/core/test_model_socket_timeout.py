"""A response owns its makefile reference and temporary socket timeout."""
import io

import pytest

from core.model_download import _SocketReader


class _Socket:
    def __init__(self, timeout):
        self.timeout = timeout
        self.changes = []
        self.holder = io.BytesIO()
        self.fail_restore = False

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.changes.append(timeout)
        if self.fail_restore:
            raise OSError("test socket unavailable")
        self.timeout = timeout

    def makefile(self, *args, **kwargs):
        return self.holder


@pytest.mark.parametrize("original", [None, 5.0, 0.75])
def test_response_close_restores_actual_timeout_once(original):
    sock = _Socket(original)
    reader = _SocketReader(sock, None, 3, None)
    assert sock.timeout == 0.1
    reader.close()
    assert sock.timeout == original
    assert sock.holder.closed and reader.closed
    assert sock.changes == [0.1, original]
    reader.close()
    assert sock.changes == [0.1, original]


def test_restore_failure_still_closes_holder_and_reader():
    sock = _Socket(5.0)
    reader = _SocketReader(sock, None, 3, None)
    sock.fail_restore = True
    with pytest.raises(OSError, match="test socket unavailable"):
        reader.close()
    assert sock.holder.closed and reader.closed
    count = len(sock.changes)
    reader.close()
    assert len(sock.changes) == count
