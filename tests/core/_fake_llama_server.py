"""A stand-in for llama-server, started the way the app starts the real one.

Behaviour comes from FAKE_LLAMA_* environment variables (the app strips only
LLAMA_* / GGML_* from the child's environment):

  FAKE_LLAMA_INFO          write {"argv", "has_key", "env" names} here as JSON at start
  FAKE_LLAMA_LOAD_S        seconds of "loading" (/health 503) before ready
  FAKE_LLAMA_NO_PORT_LINE  "1": never print the "listening on" line
  FAKE_LLAMA_EXIT_AT_START exit with this code right away
  FAKE_LLAMA_CRASHES       file holding a count: each chat request with a
                           count > 0 decrements it and kills the process
  FAKE_LLAMA_PIECES        number of streamed pieces (default 3)
  FAKE_LLAMA_PIECE_DELAY   seconds between pieces (default 0)
  FAKE_LLAMA_HEADER_DELAY  seconds before the reply starts ("reading the prompt")
  FAKE_LLAMA_REQUESTS      append each chat request body (one JSON per line)
  FAKE_LLAMA_GONE          append "gone <n>" when the client disconnects
                           after n pieces
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEY = os.environ.get("LLAMA_API_KEY", "")
LOAD_S = float(os.environ.get("FAKE_LLAMA_LOAD_S", "0") or 0)
READY = threading.Event()


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("request " + (fmt % args) + "\n")
        sys.stdout.flush()

    def _send(self, code: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            if READY.is_set():
                self._send(200, {"status": "ok"})
            else:
                self._send(503, {"error": {"message": "Loading model"}})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {KEY}" or not KEY:
            self._send(401, {"error": {"message": "Invalid API Key"}})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        requests = _env_path("FAKE_LLAMA_REQUESTS")
        if requests is not None:
            with open(requests, "a", encoding="utf-8") as fh:
                fh.write(body.decode("utf-8") + "\n")
        crashes = _env_path("FAKE_LLAMA_CRASHES")
        if crashes is not None and crashes.is_file():
            left = int(crashes.read_text() or 0)
            if left > 0:
                crashes.write_text(str(left - 1))
                os._exit(7)
        time.sleep(float(os.environ.get("FAKE_LLAMA_HEADER_DELAY", "0") or 0))
        pieces = int(os.environ.get("FAKE_LLAMA_PIECES", "3"))
        delay = float(os.environ.get("FAKE_LLAMA_PIECE_DELAY", "0") or 0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        sent = 0
        try:
            for i in range(pieces):
                chunk = {"choices": [{"index": 0, "finish_reason": None, "delta": {"content": f"p{i} "}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                sent += 1
                time.sleep(delay)
            end = {"choices": [{"index": 0, "finish_reason": "stop", "delta": {}}], "timings": {"predicted_n": pieces}}
            self.wfile.write(f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except OSError:
            gone = _env_path("FAKE_LLAMA_GONE")
            if gone is not None:
                with open(gone, "a", encoding="utf-8") as fh:
                    fh.write(f"gone {sent}\n")


def main() -> None:
    info = _env_path("FAKE_LLAMA_INFO")
    if info is not None:
        info.write_text(json.dumps({"argv": sys.argv[1:], "has_key": bool(KEY), "env": sorted(os.environ)}),
                        encoding="utf-8")
    code = os.environ.get("FAKE_LLAMA_EXIT_AT_START")
    if code:
        print("fake: failing at start", flush=True)
        sys.exit(int(code))
    argv = sys.argv[1:]
    host = argv[argv.index("--host") + 1]
    port = int(argv[argv.index("--port") + 1])
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("fake: loading model", flush=True)
    time.sleep(LOAD_S)
    READY.set()
    if os.environ.get("FAKE_LLAMA_NO_PORT_LINE") != "1":
        print(f"main: server is listening on http://{host}:{server.server_address[1]}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
