"""core.local_llm_server: managed llama-server child (start, readiness, no orphans) + streaming client.

A fake server script (tests/core/_fake_llama_server.py) is started exactly the
way the app starts the real llama-server. The real binary is exercised by
tests/smoke/test_local_llm_server_smoke.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from core import local_llm_server as lls

HERE = Path(__file__).resolve().parent
FAKE = HERE / "_fake_llama_server.py"
PARENT = HERE / "_llm_server_parent.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.fixture
def model(tmp_path: Path) -> Path:
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    return path


@pytest.fixture(autouse=True)
def _stop_servers(monkeypatch):
    for name in list(os.environ):
        if name.startswith("FAKE_LLAMA_"):
            monkeypatch.delenv(name)
    yield
    lls.stop_all()


def make(model: Path, tmp_path: Path, **opts) -> lls.LocalLLMServer:
    progress = opts.pop("on_progress", None)
    read_timeout = opts.pop("read_timeout_s", 30.0)
    options = lls.ServerOptions(model=model, peak_ram_mb=0, threads=2, **{"load_timeout_s": 20.0, **opts})
    return lls.LocalLLMServer(
        options, command=[sys.executable, str(FAKE)], log_path=tmp_path / "logs" / "llama-server.log",
        on_progress=progress, read_timeout_s=read_timeout)


def gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------- arguments and checks


def test_args_bind_loopback_random_port_and_never_carry_the_key(model):
    args = lls.server_args(["llama-server"], lls.ServerOptions(model=model, peak_ram_mb=1), threads=4)
    pairs = dict(zip(args, args[1:]))
    assert pairs["--host"] == "127.0.0.1"
    assert pairs["--port"] == "0"
    assert pairs["--cors-origins"] == "localhost"
    assert pairs["--reasoning"] == "off"
    assert pairs["-np"] == "1"
    assert pairs["-t"] == "4"
    assert pairs["-c"] == str(lls.DEFAULT_CONTEXT)
    assert pairs["-m"] == str(model)
    for flag in ("--no-webui", "--offline", "--no-cors-credentials", "--sleep-idle-seconds", "--cache-ram"):
        assert flag in args
    for banned in ("--api-key", "--api-key-file", "--tools", "--agent", "-ag", "-hf", "--webui", "--ui"):
        assert banned not in args


@pytest.mark.parametrize(("peak", "free", "ok"), [
    (3394, 3394 + lls.RAM_MARGIN_MB, True),
    (3394, 3394 + lls.RAM_MARGIN_MB - 1, False),
    (3394, None, True),  # cannot measure: do not block
])
def test_free_memory_check(peak, free, ok):
    if ok:
        lls.check_free_ram(peak, free)
    else:
        with pytest.raises(lls.LocalLLMError, match="free memory"):
            lls.check_free_ram(peak, free)


def test_start_refuses_when_memory_is_short(model, tmp_path, monkeypatch):
    monkeypatch.setattr(lls, "available_ram_mb", lambda: 100)
    server = make(model, tmp_path)
    with pytest.raises(lls.LocalLLMError, match="free memory"):
        server.start()
    assert server.pid is None


def test_messages_put_the_question_last_for_the_prompt_cache():
    msgs = lls.qa_messages(" rules ", "[E1] evidence", " why? ")
    assert msgs == [
        {"role": "system", "content": "rules\n\n[E1] evidence"},
        {"role": "user", "content": "why?"},
    ]


def test_physical_cores_is_positive():
    assert lls.physical_cores() >= 1


# ---------------------------------------------------------------- start and readiness


def test_start_finds_the_port_and_passes_the_key_only_in_the_environment(model, tmp_path, monkeypatch):
    info = tmp_path / "info.json"
    monkeypatch.setenv("FAKE_LLAMA_INFO", str(info))
    server = make(model, tmp_path)
    server.start()
    assert server.running()
    assert server.port and server.port > 0
    seen = json.loads(info.read_text(encoding="utf-8"))
    assert seen["has_key"] is True
    assert server._key and server._key not in " ".join(seen["argv"])
    assert not {"--api-key", "--api-key-file"} & set(seen["argv"])
    assert len(server._key) >= 40
    assert server._key not in server.log_path.read_text(encoding="utf-8", errors="replace")


def test_each_start_uses_a_new_key(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    first = server._key
    server.stop()
    assert server._key == ""
    server.start()
    assert server._key and server._key != first


def test_port_is_found_from_the_socket_when_the_log_line_is_missing(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_NO_PORT_LINE", "1")
    server = make(model, tmp_path)
    server.start()
    assert server.running() and server.port


# Starts its arguments as a child and waits, like a venv's python.exe launcher.
LAUNCHER = "import subprocess, sys; sys.exit(subprocess.call([sys.executable] + sys.argv[1:]))"


def test_port_is_found_when_a_launcher_starts_the_server(model, tmp_path, monkeypatch):
    """The socket belongs to the launcher's child, not to the process the app started."""
    monkeypatch.setenv("FAKE_LLAMA_NO_PORT_LINE", "1")
    server = lls.LocalLLMServer(
        lls.ServerOptions(model=model, peak_ram_mb=0, threads=2, load_timeout_s=20.0),
        command=[sys.executable, "-c", LAUNCHER, str(FAKE)], log_path=tmp_path / "logs" / "llama-server.log")
    server.start()
    assert server.running() and server.port


def test_loading_reports_progress_until_health_is_ok(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_LOAD_S", "1.5")
    calls: list[tuple[float, float]] = []
    server = make(model, tmp_path, on_progress=lambda e, t: calls.append((e, t)))
    started = time.monotonic()
    server.start()
    assert time.monotonic() - started >= 1.4
    assert calls and all(t == 20.0 for _, t in calls)
    assert calls[-1][0] > calls[0][0]


def test_load_timeout_stops_the_process(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_LOAD_S", "30")
    server = make(model, tmp_path, load_timeout_s=1.0)
    seen: list[int] = []
    server._on_progress = lambda e, t: seen.append(server.pid or 0)
    with pytest.raises(lls.LocalLLMError, match="did not finish loading"):
        server.start()
    assert seen and gone(seen[0])
    assert server.pid is None
    assert not list(lls.run_dir().glob("llama-server-*.json"))


def test_exit_during_start_reports_the_code_and_log_tail(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_EXIT_AT_START", "3")
    server = make(model, tmp_path)
    with pytest.raises(lls.LocalLLMError, match=r"exit code 3.*failing at start"):
        server.start()
    assert server.pid is None


def test_missing_model_is_refused_before_anything_starts(tmp_path, monkeypatch):
    info = tmp_path / "info.json"
    monkeypatch.setenv("FAKE_LLAMA_INFO", str(info))
    server = make(tmp_path / "nope.gguf", tmp_path)
    with pytest.raises(lls.LocalLLMError, match="model file is missing"):
        server.start()
    assert not info.exists()


def test_runtime_not_installed_is_a_clear_error(model, tmp_path, monkeypatch):
    monkeypatch.setattr(lls.llama_runtime, "installed_server", lambda: None)
    monkeypatch.setattr(lls.llama_runtime, "unsupported_reason", lambda: "")
    server = lls.LocalLLMServer(lls.ServerOptions(model=model, peak_ram_mb=0), log_path=tmp_path / "l.log")
    with pytest.raises(lls.LocalLLMError, match="not installed"):
        server.start()


def test_missing_vc_runtime_stops_the_start(model, tmp_path, monkeypatch):
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(lls.llama_runtime, "installed_server", lambda: exe)
    monkeypatch.setattr(lls.llama_runtime, "unsupported_reason", lambda: "")
    monkeypatch.setattr(lls.llama_runtime, "ensure_vc_runtime", lambda folder: ["msvcp140.dll"])
    server = lls.LocalLLMServer(lls.ServerOptions(model=model, peak_ram_mb=0), log_path=tmp_path / "l.log")
    with pytest.raises(lls.LocalLLMError, match="Visual C"):
        server.start()


def test_previous_log_is_kept_as_dot_one(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    server.stop()
    server.start()
    logs = sorted(x.name for x in (tmp_path / "logs").iterdir())
    assert (tmp_path / "logs" / "llama-server.1.log").is_file(), f"log rotation fell back to a side log: {logs}"
    assert (tmp_path / "logs" / "llama-server.log").is_file()


def test_log_rotation_retries_while_windows_holds_the_file(model, tmp_path, monkeypatch):
    """WinError 32 right after the old server ended must not lose the previous log."""
    server = make(model, tmp_path)
    server.start()
    server.stop()
    real, calls = os.replace, []

    def busy_twice(src, dst):
        if Path(src).suffix != ".log":
            return real(src, dst)  # the server record's own atomic write
        calls.append(src)
        if len(calls) <= 2:
            raise PermissionError(13, "being used by another process", None, 32)
        real(src, dst)

    monkeypatch.setattr(lls.os, "replace", busy_twice)
    server.start()
    assert len(calls) == 3
    assert (tmp_path / "logs" / "llama-server.1.log").is_file()
    assert not list((tmp_path / "logs").glob("llama-server-*.log"))


def test_stop_waits_for_the_launchers_children(model, tmp_path, monkeypatch):
    """A launcher's child keeps the log open: stop() must not return before it is gone."""
    marker = ["child-process"]
    waited: list[list[str]] = []
    monkeypatch.setattr(lls, "_descendants", lambda pid: marker)
    monkeypatch.setattr(lls, "_wait_descendants", lambda procs: waited.append(procs))
    server = make(model, tmp_path)
    server.start()
    server.stop()
    assert waited == [marker]


def test_wait_descendants_passes_the_procs_and_a_timeout_to_psutil(monkeypatch, caplog):
    seen: dict[str, object] = {}

    class Alive:
        pid = 4242

    def fake_wait(procs, timeout=None):
        seen.update(procs=procs, timeout=timeout)
        return [], list(procs)

    monkeypatch.setattr(psutil, "wait_procs", fake_wait)
    procs = [Alive()]
    with caplog.at_level("WARNING", logger=lls.logger.name):
        lls._wait_descendants(procs)
    assert seen == {"procs": procs, "timeout": lls._DESCENDANTS_WAIT_S}
    assert "4242" in caplog.text


def test_wait_descendants_is_quiet_when_all_ended(monkeypatch, caplog):
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: (list(procs), []))
    with caplog.at_level("WARNING", logger=lls.logger.name):
        lls._wait_descendants([object()])
    assert not caplog.records


def test_real_helpers_wait_until_a_real_child_is_gone():
    code = ("import subprocess, sys, time; "
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)']); "
            "print(c.pid, flush=True); time.sleep(30)")
    parent = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
    child = 0
    try:
        assert parent.stdout is not None
        child = int(parent.stdout.readline())
        found = lls._descendants(parent.pid)
        assert child in [p.pid for p in found]  # a python launcher may add a hop
        parent.kill()
        parent.wait(timeout=10)
        assert psutil.pid_exists(child)  # still running: the wait below has real work
        lls._wait_descendants(found)
        assert not psutil.pid_exists(child)
    finally:
        parent.kill()
        if child and psutil.pid_exists(child):
            try:
                psutil.Process(child).kill()
            except psutil.NoSuchProcess:
                pass


# ---------------------------------------------------------------- records and stop


def test_start_writes_a_record_and_stop_removes_it_and_the_process(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    pid = server.pid
    assert pid
    records = list(lls.run_dir().glob("llama-server-*.json"))
    assert len(records) == 1
    rec = json.loads(records[0].read_text(encoding="utf-8"))
    assert rec["pid"] == pid
    assert rec["owner_pid"] == os.getpid()
    assert os.path.normcase(rec["exe"]) == os.path.normcase(psutil.Process(pid).exe())
    server.stop()
    assert gone(pid)
    assert not records[0].exists()
    assert not server.running()
    server.stop()  # twice is fine


def test_stop_all_stops_every_server_of_this_process(model, tmp_path):
    a = make(model, tmp_path / "a")
    b = make(model, tmp_path / "b")
    a.start()
    b.start()
    pids = [a.pid, b.pid]
    lls.stop_all()
    assert all(p and gone(p) for p in pids)


def _spawn_fake(tmp_path: Path) -> subprocess.Popen[bytes]:
    env = dict(os.environ, LLAMA_API_KEY="k")
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", "0"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            psutil.Process(proc.pid).create_time()
            break
        except psutil.NoSuchProcess:
            time.sleep(0.05)
    return proc


@pytest.fixture
def other_app():
    """A live process standing in for another app window (pytest's own parent
    may already be gone in a detached run)."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WINDOW)
    try:
        yield psutil.Process(proc.pid)
    finally:
        proc.kill()
        proc.wait()


def _dead_owner() -> tuple[int, float]:
    p = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=NO_WINDOW)
    created = psutil.Process(p.pid).create_time() if psutil.pid_exists(p.pid) else 1.0
    p.wait()
    return p.pid, created


def _record(folder: Path, proc_pid: int, **overrides) -> Path:
    p = psutil.Process(proc_pid)
    owner_pid, owner_created = _dead_owner()
    rec = {"pid": proc_pid, "created": p.create_time(), "exe": p.exe(),
           "owner_pid": owner_pid, "owner_created": owner_created, **overrides}
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"llama-server-{proc_pid}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


@pytest.fixture
def fake_is_server(monkeypatch):
    """Let the reaper treat the python-based fake as a llama-server."""
    monkeypatch.setattr(lls, "_is_managed_exe", lambda exe: True)


def test_reaper_kills_a_server_whose_app_is_gone(tmp_path, fake_is_server):
    proc = _spawn_fake(tmp_path)
    try:
        path = _record(tmp_path / "run", proc.pid)
        assert lls.reap_stale_servers(tmp_path / "run") == [proc.pid]
        assert proc.wait(timeout=10) is not None
        assert not path.exists()
    finally:
        proc.kill()


@pytest.mark.parametrize("change", ["exe", "created"])
def test_reaper_never_kills_a_recycled_pid(tmp_path, change, fake_is_server):
    proc = _spawn_fake(tmp_path)
    try:
        overrides = {"exe": str(tmp_path / "other.exe")} if change == "exe" else {"created": 12345.0}
        path = _record(tmp_path / "run", proc.pid, **overrides)
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert proc.poll() is None
        assert not path.exists()  # the record is stale either way
    finally:
        proc.kill()
        proc.wait()


def test_reaper_leaves_the_server_of_another_running_app(tmp_path, fake_is_server, other_app):
    proc = _spawn_fake(tmp_path)
    try:
        path = _record(tmp_path / "run", proc.pid, owner_pid=other_app.pid, owner_created=other_app.create_time())
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert proc.poll() is None
        assert path.exists()
    finally:
        proc.kill()
        proc.wait()


def test_reaper_never_kills_a_program_that_is_not_the_runtime_server(tmp_path):
    """A planted record (right pid, start time and exe) still cannot kill python."""
    proc = _spawn_fake(tmp_path)
    try:
        path = _record(tmp_path / "run", proc.pid)
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert proc.poll() is None
        assert not path.exists()
    finally:
        proc.kill()
        proc.wait()


def test_only_the_runtime_folders_llama_server_counts_as_managed(tmp_path):
    root = lls.llama_runtime.runtime_root()
    assert lls._is_managed_exe(str(root / "b1" / lls.llama_runtime.server_exe_name()))
    assert not lls._is_managed_exe(str(root / "b1" / "python.exe"))
    assert not lls._is_managed_exe(str(tmp_path / lls.llama_runtime.server_exe_name()))
    assert not lls._is_managed_exe(str(root.parent / (root.name + "x") / lls.llama_runtime.server_exe_name()))


def test_reaper_keeps_the_record_of_a_live_but_unreadable_process(tmp_path, fake_is_server, monkeypatch):
    proc = _spawn_fake(tmp_path)
    try:
        path = _record(tmp_path / "run", proc.pid)
        real = lls._lookup
        monkeypatch.setattr(lls, "_lookup", lambda pid: lls._DENIED if pid == proc.pid else real(pid))
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert proc.poll() is None
        assert path.exists()
    finally:
        proc.kill()
        proc.wait()


def test_reaper_drops_the_record_of_a_server_that_was_unreadable_only_while_ending(
        tmp_path, fake_is_server, monkeypatch):
    """A process being torn down answers "denied" for a moment, then is gone."""
    proc = _spawn_fake(tmp_path)
    try:
        path = _record(tmp_path / "run", proc.pid)
        real = lls._lookup
        answers = [lls._DENIED, lls._DENIED]

        def ending(pid):
            if pid == proc.pid:
                return answers.pop(0) if answers else lls._GONE
            return real(pid)

        monkeypatch.setattr(lls, "_lookup", ending)
        monkeypatch.setattr(lls.time, "sleep", lambda s: None)
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert not path.exists()
    finally:
        proc.kill()
        proc.wait()


def test_reaper_tolerates_a_slightly_different_owner_start_time(tmp_path, fake_is_server, other_app):
    proc = _spawn_fake(tmp_path)
    try:
        _record(tmp_path / "run", proc.pid, owner_pid=other_app.pid, owner_created=other_app.create_time() + 0.5)
        assert lls.reap_stale_servers(tmp_path / "run") == []
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_reaper_running_while_a_record_is_written_spares_the_new_server(model, tmp_path, monkeypatch):
    seen: list[list[int]] = []
    real = lls._write_record

    def write_then_reap(path, record):
        real(path, record)
        monkeypatch.setattr(lls, "_is_managed_exe", lambda exe: True)
        seen.append(lls.reap_stale_servers())

    monkeypatch.setattr(lls, "_write_record", write_then_reap)
    server = make(model, tmp_path)
    server.start()
    assert seen == [[]]
    assert server.running()


def test_reaper_keeps_this_processes_managed_server(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    assert lls.reap_stale_servers() == []
    assert server.running()


def test_reaper_drops_unreadable_records(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    bad = folder / "llama-server-1.json"
    bad.write_text("{not json", encoding="utf-8")
    assert lls.reap_stale_servers(folder) == []
    assert not bad.exists()


def _start_parent(tmp_path: Path, model: Path) -> tuple[subprocess.Popen[str], int]:
    parent = subprocess.Popen(
        [sys.executable, str(PARENT), str(tmp_path / "run"), str(tmp_path / "srv.log"), str(FAKE), str(model)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
    assert parent.stdout is not None
    line = parent.stdout.readline()
    assert line.startswith("child "), line + parent.stdout.read()
    return parent, int(line.split()[1])


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows only")
def test_windows_job_object_ends_the_server_when_the_app_is_killed(model, tmp_path):
    parent, child = _start_parent(tmp_path, model)
    try:
        assert psutil.pid_exists(child)
        subprocess.run(["taskkill", "/F", "/PID", str(parent.pid)], check=True,
                       capture_output=True, creationflags=NO_WINDOW)
        parent.wait(timeout=10)
        assert gone(child), "llama-server outlived the killed app"
    finally:
        parent.kill()
        if psutil.pid_exists(child):
            psutil.Process(child).kill()


def test_a_killed_apps_server_is_gone_after_the_next_start(model, tmp_path, fake_is_server):
    """Windows: the Job Object ends it at once; elsewhere the next start reaps it."""
    parent, child = _start_parent(tmp_path, model)
    try:
        parent.kill()
        parent.wait(timeout=10)
        reaped = lls.reap_stale_servers(tmp_path / "run")
        assert gone(child), f"child {child} still alive after the reaper returned {reaped}"
        assert not list((tmp_path / "run").glob("llama-server-*.json"))
    finally:
        if psutil.pid_exists(child):
            try:
                psutil.Process(child).kill()
            except psutil.NoSuchProcess:
                pass


# ---------------------------------------------------------------- client


def test_streamed_answer_and_request_shape(model, tmp_path, monkeypatch):
    requests = tmp_path / "requests.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_REQUESTS", str(requests))
    monkeypatch.setenv("FAKE_LLAMA_PIECES", "4")
    server = make(model, tmp_path)
    msgs = lls.qa_messages("rules", "evidence", "question")
    with server.open_chat(msgs, max_tokens=64) as stream:
        pieces = list(stream)
    assert pieces == ["p0 ", "p1 ", "p2 ", "p3 "]
    assert stream.finish_reason == "stop"
    assert stream.timings == {"predicted_n": 4}
    body = json.loads(requests.read_text(encoding="utf-8").splitlines()[0])
    assert body["messages"] == msgs
    assert body["stream"] is True and body["max_tokens"] == 64 and body["cache_prompt"] is True


def test_first_request_starts_the_server(model, tmp_path):
    server = make(model, tmp_path)
    assert server.pid is None
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"
    assert server.running()


def test_wrong_key_is_refused(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    server._key = "wrong"
    with pytest.raises(lls.LocalLLMError, match="HTTP 401"):
        server.chat([{"role": "user", "content": "q"}])


def test_client_ignores_proxy_settings(model, tmp_path, monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    server = make(model, tmp_path)
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"


def test_cancel_from_another_thread_ends_the_answer_and_the_next_one_is_served(model, tmp_path, monkeypatch):
    gone_file = tmp_path / "gone.txt"
    monkeypatch.setenv("FAKE_LLAMA_PIECES", "200")
    monkeypatch.setenv("FAKE_LLAMA_PIECE_DELAY", "0.05")
    monkeypatch.setenv("FAKE_LLAMA_GONE", str(gone_file))
    server = make(model, tmp_path)
    got: list[str] = []
    stream = server.open_chat([{"role": "user", "content": "q"}])
    started = time.monotonic()

    def reader() -> None:
        for piece in stream:
            got.append(piece)

    t = threading.Thread(target=reader)
    t.start()
    while len(got) < 3:
        time.sleep(0.01)
        assert time.monotonic() - started < 10
    stream.cancel()
    t.join(timeout=5)
    assert not t.is_alive()
    assert stream.cancelled
    assert 3 <= len(got) < 200
    deadline = time.monotonic() + 5
    while not gone_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert gone_file.read_text(encoding="utf-8").startswith("gone ")
    with server.open_chat([{"role": "user", "content": "again"}]) as second:
        assert next(iter(second)) == "p0 "
        second.cancel()


def test_cancel_works_before_the_server_has_answered(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_HEADER_DELAY", "30")
    server = make(model, tmp_path)
    stream = server.open_chat([{"role": "user", "content": "q"}])
    got: list[str] = []
    t = threading.Thread(target=lambda: got.extend(stream))
    t.start()
    time.sleep(0.5)
    started = time.monotonic()
    stream.cancel()
    t.join(timeout=5)
    assert not t.is_alive(), "cancel did not interrupt the wait for the reply"
    assert time.monotonic() - started < 3
    assert got == []


def test_a_crash_is_restarted_once_then_reported(model, tmp_path, monkeypatch):
    crashes = tmp_path / "crashes.txt"
    crashes.write_text("2")
    monkeypatch.setenv("FAKE_LLAMA_CRASHES", str(crashes))
    server = make(model, tmp_path)
    server.start()
    first = server.pid
    with pytest.raises(lls.LocalLLMError, match="stopped unexpectedly"):
        server.chat([{"role": "user", "content": "q"}])
    with pytest.raises(lls.LocalLLMError, match="stopped unexpectedly"):
        server.chat([{"role": "user", "content": "q"}])  # restarted once, crashed again
    assert server.pid != first
    with pytest.raises(lls.LocalLLMError, match="again"):
        server.chat([{"role": "user", "content": "q"}])
    assert server.pid is None
    server.start()  # the user tries again: a fresh allowance
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"


def test_one_crash_then_success_keeps_working(model, tmp_path, monkeypatch):
    crashes = tmp_path / "crashes.txt"
    crashes.write_text("1")
    monkeypatch.setenv("FAKE_LLAMA_CRASHES", str(crashes))
    server = make(model, tmp_path)
    with pytest.raises(lls.LocalLLMError, match="stopped unexpectedly"):
        server.chat([{"role": "user", "content": "q"}])
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"


def test_read_timeout_is_an_error_not_a_hang(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_PIECES", "5")
    monkeypatch.setenv("FAKE_LLAMA_PIECE_DELAY", "3")
    server = make(model, tmp_path, read_timeout_s=0.5)
    started = time.monotonic()
    with pytest.raises(lls.LocalLLMError, match="Lost the connection"):
        server.chat([{"role": "user", "content": "q"}])
    assert time.monotonic() - started < 10


def test_a_reply_larger_than_the_cap_is_an_error(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_PIECES", "50")
    monkeypatch.setattr(lls, "_MAX_REPLY_BYTES", 500)
    server = make(model, tmp_path)
    with pytest.raises(lls.LocalLLMError, match="larger than expected"):
        server.chat([{"role": "user", "content": "q"}])


def test_a_later_crash_gets_its_own_restart_after_a_good_answer(model, tmp_path, monkeypatch):
    crashes = tmp_path / "crashes.txt"
    crashes.write_text("1")
    monkeypatch.setenv("FAKE_LLAMA_CRASHES", str(crashes))
    server = make(model, tmp_path)
    with pytest.raises(lls.LocalLLMError, match="stopped unexpectedly"):
        server.chat([{"role": "user", "content": "q"}])
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"  # restart 1
    crashes.write_text("1")
    with pytest.raises(lls.LocalLLMError, match="stopped unexpectedly"):
        server.chat([{"role": "user", "content": "q"}])
    assert server.chat([{"role": "user", "content": "q"}]) == "p0 p1 p2"  # restarted again


# ---------------------------------------------------------------- threads


def _start_in_thread(server: lls.LocalLLMServer) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            server.start()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    deadline = time.monotonic() + 10
    while server.pid is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return t, errors


def test_stop_during_a_load_does_not_wait_for_the_load(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_LOAD_S", "60")
    server = make(model, tmp_path, load_timeout_s=120.0)
    t, errors = _start_in_thread(server)
    pid = server.pid
    assert pid
    time.sleep(0.3)
    started = time.monotonic()
    server.stop()
    assert time.monotonic() - started < 5
    t.join(timeout=5)
    assert not t.is_alive()
    assert errors and isinstance(errors[0], lls.LocalLLMError) and "stopped while loading" in str(errors[0])
    assert gone(pid)
    assert server.pid is None


def test_state_reads_never_block_during_a_load(model, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_LOAD_S", "60")
    server = make(model, tmp_path, load_timeout_s=120.0)
    t, _ = _start_in_thread(server)
    started = time.monotonic()
    assert server.running() is False
    assert server.pid is not None
    assert time.monotonic() - started < 1
    server.stop()
    t.join(timeout=5)


def test_a_stop_before_start_does_not_abort_the_next_start(model, tmp_path):
    server = make(model, tmp_path)
    server.stop()
    server.start()
    assert server.running()


def test_open_chat_on_a_server_stopped_meanwhile_is_a_clear_error(model, tmp_path, monkeypatch):
    server = make(model, tmp_path)
    server.start()
    monkeypatch.setattr(server, "_ensure_running_locked", lambda gen: server._cleanup_locked())
    with pytest.raises(lls.LocalLLMError, match="not running"):
        server.open_chat([{"role": "user", "content": "q"}])


# ---------------------------------------------------------------- environment and log


def test_credentials_in_the_apps_environment_do_not_reach_the_server(model, tmp_path, monkeypatch):
    info = tmp_path / "info.json"
    monkeypatch.setenv("FAKE_LLAMA_INFO", str(info))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-credential-A")
    monkeypatch.setenv("HF_TOKEN", "dummy-credential-B")
    monkeypatch.setenv("LLAMA_ARG_TOOLS", "all")
    server = make(model, tmp_path)
    server.start()
    names = {n.upper() for n in json.loads(info.read_text(encoding="utf-8"))["env"]}
    assert "LLAMA_API_KEY" in names
    assert not {"ANTHROPIC_API_KEY", "HF_TOKEN", "LLAMA_ARG_TOOLS"} & names
    assert "PATH" in names


def test_server_env_keeps_ordinary_variables(monkeypatch):
    monkeypatch.setenv("SOME_SETTING", "1")
    monkeypatch.setenv("MY_PASSWORD", "dummy-credential-C")
    env = lls.server_env("k")
    assert env["LLAMA_API_KEY"] == "k"
    assert env["SOME_SETTING"] == "1"
    assert "MY_PASSWORD" not in env


def test_side_logs_of_earlier_runs_are_cleaned_up(model, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    side = logs / "llama-server-123-456.log"
    side.write_text("old", encoding="utf-8")
    server = make(model, tmp_path)
    server.start()
    assert not side.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_log_is_private_to_the_user(model, tmp_path):
    server = make(model, tmp_path)
    server.start()
    assert server.log_path.stat().st_mode & 0o077 == 0
