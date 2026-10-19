"""A real HTTP server on 127.0.0.1 that serves one file, with knobs for faults.

Used by the verified-download and llama-runtime tests instead of mocks, so
the real ``urllib`` paths (Range, 206, 416, a stream cut mid-body) run.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class FileServerState:
    payload: bytes = b""
    # Close the connection after this many body bytes of the NEXT response
    # (Content-Length still announces the full length); None = no cut.
    cut_after: int | None = None
    ignore_range: bool = False
    status: int | None = None  # force this status (e.g. 404)
    ranges: list[str | None] = field(default_factory=list)  # Range header per request

    @property
    def requests(self) -> int:
        return len(self.ranges)


class _Handler(BaseHTTPRequestHandler):
    state: FileServerState  # set per server

    def log_message(self, format, *args):  # noqa: A002, ANN001, ANN002
        pass

    def do_GET(self):  # noqa: N802
        st = self.server.state  # type: ignore[attr-defined]
        rng = self.headers.get("Range")
        st.ranges.append(rng)
        if st.status is not None:
            self.send_response(st.status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = st.payload
        start = 0
        m = re.match(r"bytes=(\d+)-$", rng or "")
        if m and not st.ignore_range:
            start = int(m.group(1))
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        chunk = body[start:]
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        if st.cut_after is not None:
            cut, st.cut_after = st.cut_after, None
            self.wfile.write(chunk[:cut])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(chunk)


class FakeFileServer:
    def __init__(self) -> None:
        self.state = FileServerState()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.state = self.state  # type: ignore[attr-defined]
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def url(self, name: str = "file.bin") -> str:
        return f"{self.base_url}/{name}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
