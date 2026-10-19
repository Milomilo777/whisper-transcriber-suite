"""Real llama-server run: start, answer, cancel, auth, CORS, stop (core.local_llm_server).

Needs the pinned runtime already installed and a GGUF model:

    set WHISPER_SMOKE_LLAMA_RUNTIME=%LOCALAPPDATA%\\WhisperTranscriberSuite\\Cache\\tools\\llama.cpp\\b11514
    set WHISPER_SMOKE_LLAMA_MODEL=C:\\models\\gemma-4-E2B-it-Q4_K_M.gguf
    set WHISPER_SMOKE_LLAMA_PEAK_MB=3394   (optional; the model's measured peak)

Skips itself when either path is missing. Loads the model once (~35 s and
~3 GB of memory for Gemma 4 E2B on a 4-core CPU).
"""
from __future__ import annotations

import http.client
import os
import threading
import time
from pathlib import Path

import psutil
import pytest

from core import llama_runtime, offline
from core import local_llm_server as lls

RUNTIME = Path(os.environ.get("WHISPER_SMOKE_LLAMA_RUNTIME", "") or "missing")
MODEL = Path(os.environ.get("WHISPER_SMOKE_LLAMA_MODEL", "") or "missing")
PEAK_MB = int(os.environ.get("WHISPER_SMOKE_LLAMA_PEAK_MB", "3394"))

pytestmark = pytest.mark.skipif(
    not (RUNTIME / llama_runtime.server_exe_name()).is_file() or not MODEL.is_file(),
    reason="set WHISPER_SMOKE_LLAMA_RUNTIME and WHISPER_SMOKE_LLAMA_MODEL",
)


@pytest.fixture(scope="module")
def server():
    mp = pytest.MonkeyPatch()
    mp.setattr(llama_runtime, "runtime_dir", lambda: RUNTIME)
    srv = lls.LocalLLMServer(lls.ServerOptions(model=MODEL, peak_ram_mb=PEAK_MB))
    srv.start()
    yield srv
    pid = srv.pid
    srv.stop()
    mp.undo()
    assert pid is not None and not psutil.pid_exists(pid), "llama-server outlived stop()"


def _get(port: int, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        resp.read()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}
    finally:
        conn.close()


def test_only_health_is_open_and_the_key_is_required(server):
    port = server.port
    assert _get(port, "/health", {})[0] == 200
    assert _get(port, "/v1/models", {})[0] == 401
    assert _get(port, "/v1/models", {"Authorization": "Bearer wrong"})[0] == 401
    assert _get(port, "/v1/models", {"Authorization": f"Bearer {server._key}"})[0] == 200


def test_other_sites_get_no_cors_permission(server):
    auth = {"Authorization": f"Bearer {server._key}"}
    # Look-alike hosts a web page could really have. (llama-server b11514 does
    # echo "http://evil.example:80@localhost", but a browser never sends
    # user info in Origin, and non-browser clients ignore CORS anyway.)
    for origin in ("https://evil.example", "http://localhost.evil.example", "http://127.0.0.1.evil.example"):
        _, headers = _get(server.port, "/v1/models", {**auth, "Origin": origin})
        assert "access-control-allow-origin" not in headers, origin
    _, headers = _get(server.port, "/v1/models", {**auth, "Origin": "http://localhost:5000"})
    assert headers.get("access-control-allow-origin") == "http://localhost:5000"


def test_three_questions_then_cancel_then_one_more(server):
    rules = "Answer in one short sentence using only the transcript."
    evidence = "[E1] The meeting starts at nine.\n[E2] Lunch is served at noon.\n[E3] Anna leads the session."
    for q in ("When does the meeting start?", "When is lunch?", "Who leads the session?"):
        answer = server.chat(lls.qa_messages(rules, evidence, q), max_tokens=40)
        assert answer.strip(), q
    stream = server.open_chat(lls.qa_messages(rules, evidence, "Write a long story about the meeting."),
                              max_tokens=400)
    got: list[str] = []

    def read() -> None:
        for piece in stream:
            got.append(piece)
            if len(got) == 5:
                stream.cancel()

    t = threading.Thread(target=read)
    t.start()
    t.join(timeout=120)
    assert not t.is_alive() and stream.cancelled and len(got) >= 5
    assert stream.finish_reason is None
    started = time.monotonic()
    assert server.chat(lls.qa_messages(rules, evidence, "Who leads the session?"), max_tokens=20)
    assert time.monotonic() - started < 60


def test_server_talks_to_no_other_computer(server):
    check = offline.poll_connections(server.pid)
    assert check.ok, check.error
    assert check.outside == ()
