"""Work offline made visible: the Network log, the extra guard paths, the
open-connection check, Verify offline now and the status-line text."""
from __future__ import annotations

import ast
import errno
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from app.widgets import offline_status as status
from core import offline

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("offline_network_allowlist.txt")


@pytest.fixture(autouse=True)
def _fresh_log():
    offline.reset_activity()
    yield
    offline.reset_activity()


@pytest.fixture
def guard():
    offline.uninstall_network_guard()
    offline.install_network_guard()
    yield
    offline.uninstall_network_guard()


def _own_lan_address() -> str:
    """This computer's non-loopback IPv4 address (a UDP connect sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("203.0.113.1", 9))
        except OSError:
            pytest.skip("no network route on this computer")
        address = s.getsockname()[0]
    if address.startswith("127.") or address == "0.0.0.0":
        pytest.skip("only loopback addresses on this computer")
    return address


# --- the Network log ---------------------------------------------------------

def test_refused_and_skipped_are_counted_with_their_feature():
    text = offline.refused("downloading this link")
    offline.skipped("the update check")
    assert text == offline.message("downloading this link")
    act = offline.activity()
    assert act.counts[offline.REFUSED] == 1 and act.counts[offline.SKIPPED] == 1
    assert [(e.kind, e.feature, e.host) for e in act.events] == [
        (offline.REFUSED, "downloading this link", ""),
        (offline.SKIPPED, "the update check", ""),
    ]


def test_require_online_counts_its_refusal():
    offline.set_offline(True)
    with pytest.raises(offline.OfflineModeError):
        offline.require_online("downloading the Kokoro voice model")
    offline.set_offline(False)
    offline.require_online("downloading the Kokoro voice model")
    act = offline.activity()
    assert act.counts[offline.REFUSED] == 1
    assert act.events[-1].feature == "downloading the Kokoro voice model"


def test_counts_are_exact_across_threads_and_the_log_stays_bounded():
    def work() -> None:
        for _ in range(400):
            offline.skipped("x")
            offline.refused("y")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    act = offline.activity()
    assert act.counts[offline.SKIPPED] == 3200 and act.counts[offline.REFUSED] == 3200
    assert len(act.events) == offline._LOG_SIZE


def test_a_once_per_run_request_is_counted_once_per_count():
    for _ in range(3):
        offline.skipped("the online config", once=True)
    assert offline.activity().counts[offline.SKIPPED] == 1
    offline.reset_activity()
    offline.skipped("the online config", once=True)
    assert offline.activity().counts[offline.SKIPPED] == 1


def test_reading_the_config_while_offline_counts_the_online_config_once(monkeypatch):
    import core.config as cfg

    offline.set_offline(True)
    monkeypatch.setattr(cfg, "fetch_online_config", lambda url, *a, **k: {})
    for _ in range(3):
        cfg.load_config()
    skipped = [e.feature for e in offline.activity().events if e.kind == offline.SKIPPED]
    assert skipped == ["the online config"]


def test_only_requests_with_a_destination_count_as_not_sent(monkeypatch):
    import app.observability as obs
    import core.config as cfg
    from core import stats

    offline.set_offline(True)
    monkeypatch.setattr(cfg, "load_config", lambda *a, **k: {"telemetry_opt_in": True})
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("WHISPER_TELEMETRY_URL", raising=False)
    obs.init_sentry()
    obs.send_launch_ping_async()
    stats.post_stats_async({"telemetry_opt_in": True, "stats_url": ""}, {})
    assert offline.activity().counts[offline.SKIPPED] == 0
    monkeypatch.setenv("SENTRY_DSN", "https://dummy-credential-A@example.invalid/1")
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    assert obs.init_sentry() is False
    obs.send_launch_ping_async()
    features = [e.feature for e in offline.activity().events]
    assert features == ["crash reports", "the launch ping"]


def test_reset_starts_a_new_count():
    offline.skipped("x")
    before = time.time()
    offline.reset_activity()
    act = offline.activity()
    assert act.counts[offline.SKIPPED] == 0 and act.events == () and act.since >= before


def test_automatic_requests_count_as_skipped_while_offline():
    from core import stats, updates

    offline.set_offline(True)
    assert updates.check_for_update() is None
    assert stats.post_stats_async(
        {"telemetry_opt_in": True, "stats_url": "https://x.invalid"}, {}
    ) is False
    features = [e.feature for e in offline.activity().events if e.kind == offline.SKIPPED]
    assert features == ["the update check", "usage statistics"]


# --- the backstop: what it refuses and logs ----------------------------------

def test_a_refused_connection_names_the_host_and_the_caller(guard):
    offline.set_offline(True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(offline.OfflineModeError):
            s.connect(("203.0.113.1", 443))
    ev = offline.activity().events[-1]
    assert (ev.kind, ev.host) == (offline.REFUSED, "203.0.113.1")
    assert ev.feature.endswith("test_offline_activity")


def test_connect_ex_returns_an_error_number_and_logs_it(guard):
    offline.set_offline(True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        assert s.connect_ex(("203.0.113.1", 443)) == errno.EACCES
    assert offline.activity().counts[offline.REFUSED] == 1


def test_a_connection_on_this_computer_is_allowed_and_logged(guard):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        offline.set_offline(True)
        with socket.create_connection(server.getsockname(), timeout=5):
            pass
    act = offline.activity()
    assert act.counts[offline.LOCAL] == 1 and act.counts[offline.REFUSED] == 0
    assert act.events[-1].host == "127.0.0.1"


def test_udp_sends_and_lookups_outside_are_refused(guard):
    offline.set_offline(True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        with pytest.raises(offline.OfflineModeError):
            s.sendto(b"x", ("203.0.113.1", 9))
        s.sendto(b"x", ("127.0.0.1", 9))  # stays on this computer
        s.connect(("203.0.113.1", 9))  # only picks a route: still allowed
    for call, arg in ((socket.gethostbyname, "example.invalid"),
                      (socket.gethostbyname_ex, "example.invalid"),
                      (socket.gethostbyaddr, "8.8.8.8")):
        with pytest.raises(offline.OfflineModeError):
            call(arg)
    with pytest.raises(offline.OfflineModeError):
        socket.getnameinfo(("203.0.113.1", 80), socket.NI_NUMERICHOST)
    assert socket.getnameinfo(("127.0.0.1", 80), socket.NI_NUMERICHOST)[0] == "127.0.0.1"
    hosts = [e.host for e in offline.activity().events if e.kind == offline.REFUSED]
    assert hosts == ["203.0.113.1", "example.invalid", "example.invalid", "8.8.8.8", "203.0.113.1"]


def test_udp_send_to_this_pcs_own_lan_address_is_refused(guard):
    # Found by the wave-3 probe: TCP to the LAN address was refused, a UDP
    # datagram to it was delivered.
    address = _own_lan_address()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind((address, 0))
        rx.settimeout(0.5)
        offline.set_offline(True)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            with pytest.raises(offline.OfflineModeError):
                tx.sendto(b"leak", rx.getsockname())
        with pytest.raises(TimeoutError):
            rx.recvfrom(16)


def test_the_audit_paths_follow_the_switch_and_the_install():
    offline.uninstall_network_guard()
    offline.install_network_guard()
    try:
        offline.set_offline(False)
        socket.getnameinfo(("203.0.113.1", 80), socket.NI_NUMERICHOST)
        offline.set_offline(True)
        with pytest.raises(offline.OfflineModeError):
            socket.getnameinfo(("203.0.113.1", 80), socket.NI_NUMERICHOST)
    finally:
        offline.uninstall_network_guard()
    # The audit hook stays registered but acts only while the guard is installed.
    assert socket.getnameinfo(("203.0.113.1", 80), socket.NI_NUMERICHOST)[0] == "203.0.113.1"


def test_reverse_lookup_allowed_only_for_this_computer():
    for host in ("127.0.0.1", "::1", "localhost", socket.gethostname(), None):
        assert offline.reverse_lookup_allowed(host), host
    for host in ("8.8.8.8", "192.168.1.5", "example.com", "2606:4700::1111"):
        assert not offline.reverse_lookup_allowed(host), host


def test_calls_on_the_raw_socket_module_are_refused(guard):
    import _socket

    offline.set_offline(True)
    raw = _socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(offline.OfflineModeError):
            raw.connect(("203.0.113.1", 443))
    finally:
        raw.close()
    with pytest.raises(offline.OfflineModeError):
        _socket.getaddrinfo("work-offline-check.invalid", 80)


@pytest.mark.skipif(sys.platform != "win32", reason="the Proactor loop is Windows only")
def test_asyncio_proactor_connections_and_datagrams_are_refused(guard):
    import asyncio

    offline.set_offline(True)

    async def run() -> None:
        with pytest.raises(offline.OfflineModeError):
            await asyncio.open_connection("203.0.113.1", 443)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
        try:
            transport.sendto(b"x", ("203.0.113.1", 9))
            await asyncio.sleep(0.2)
        finally:
            transport.close()

    asyncio.run(run())
    hosts = [e.host for e in offline.activity().events if e.kind == offline.REFUSED]
    assert hosts == ["203.0.113.1", "203.0.113.1"]


def test_allowed_local_connections_never_push_refusals_out_of_the_log():
    offline.refused("downloading this link")
    for _ in range(offline._LOG_SIZE + 100):
        offline._record(offline.LOCAL, "core.llm", "127.0.0.1")
    act = offline.activity()
    assert [e.feature for e in act.events if e.kind == offline.REFUSED] == ["downloading this link"]
    assert act.counts[offline.LOCAL] == offline._LOG_SIZE + 100


def test_a_failing_look_shows_unknown_and_keeps_polling():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display")
    try:
        def boom() -> offline.ConnectionCheck:
            raise RuntimeError("boom")

        bar = status.OfflineStatusBar(root, post_to_main=lambda fn: fn(), poll=boom)
        bar.tick()
        assert bar.check is not None and not bar.check.ok
        assert "unknown" in bar.text_var.get() and bar._after_id is not None
        bar.hide()
    finally:
        root.destroy()


# --- Verify offline now --------------------------------------------------------

def test_verify_offline_now_shows_every_probe_refused(guard):
    offline.set_offline(True)
    probes = offline.self_test()
    assert [p.refused for p in probes] == [True, True, True], probes
    act = offline.activity()
    assert {(e.kind, e.feature) for e in act.events} == {(offline.TEST, "Verify offline now")}
    assert act.counts[offline.REFUSED] == 0 and act.counts[offline.TEST] == 3


def test_verify_offline_now_fails_without_the_guard(monkeypatch):
    # The mutation the card asks for: the guard bypassed, every probe must say so.
    offline.uninstall_network_guard()
    sent: list[object] = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, a: sent.append(a))
    monkeypatch.setattr(socket.socket, "sendto", lambda self, d, a: sent.append(a))
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, *a, **k: sent.append(h) or [])
    offline.set_offline(True)
    probes = offline.self_test()
    assert [p.refused for p in probes] == [False, False, False]
    assert all("NOT refused" in p.detail for p in probes)
    assert len(sent) == 3


def test_verify_offline_now_refuses_to_run_while_online():
    with pytest.raises(RuntimeError):
        offline.self_test()


# --- the open-connection check ------------------------------------------------

def test_poll_shows_a_connection_that_went_past_the_guard():
    # Deterministic stand-in for "bypass the guard once": a real connection to
    # this PC's own LAN address, opened without the guard.
    address = _own_lan_address()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((address, 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), timeout=5)
        accepted, _ = server.accept()
        try:
            check = offline.poll_connections()
            port = server.getsockname()[1]
            assert check.ok, check.error
            outgoing = [c for c in check.outside if c.remote == f"{address}:{port}"]
            incoming = [c for c in check.outside if c.incoming]
            assert outgoing and not outgoing[0].incoming and outgoing[0].protocol == "TCP"
            assert incoming
            assert status.bar_state(check, check.when) == "warning"
            assert "WARNING" in status.bar_text(check, offline.activity(), check.when)
        finally:
            accepted.close()
            client.close()
    after = offline.poll_connections()
    assert after.ok and not any(c.remote.endswith(f":{port}") for c in after.outside)


def test_poll_ignores_loopback_connections():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5):
            check = offline.poll_connections()
    assert check.ok and check.processes >= 1
    assert not any(c.remote.startswith("127.") for c in check.outside)


def test_poll_reports_when_it_cannot_look():
    check = offline.poll_connections(root_pid=2**31 - 7)
    assert not check.ok and check.error
    assert status.bar_state(check, check.when) == "unknown"


# --- the status line and the Network log text --------------------------------

def _check(outside: tuple[offline.OpenConnection, ...] = (), when: float | None = None):
    return offline.ConnectionCheck(time.time() if when is None else when, True, outside, processes=2)


def test_bar_is_clean_only_after_a_fresh_successful_look():
    now = time.time()
    assert status.bar_state(None, now) == "unknown"
    assert status.bar_state(offline.ConnectionCheck(now, False, error="boom"), now) == "unknown"
    assert status.bar_state(_check(when=now - status.FRESH_SECONDS - 1), now) == "unknown"
    assert status.bar_state(_check(when=now), now) == "clean"


def test_bar_text_never_claims_more_than_it_checked():
    now = time.time()
    act = offline.activity()
    for check in (None, offline.ConnectionCheck(now, False, error="boom"), _check(when=now - 99)):
        text = status.bar_text(check, act, now)
        assert "open connections unknown" in text and "no open connection" not in text
    clean = status.bar_text(_check(when=now), act, now)
    assert clean.startswith("Work offline: this app has no open TCP connection to another computer (checked ")
    for text in (clean, status.log_text(act, _check(when=now))):
        assert "0 bytes" not in text and "0 outside" not in text


def test_log_text_lists_events_connections_probes_and_limits():
    offline.refused("downloading this link")
    offline.skipped("the update check")
    conn = offline.OpenConnection(12, "python.exe", "TCP", "140.82.112.5:443", False)
    probes = [offline.ProbeResult("TCP connection to 203.0.113.1", True, "refused by Work offline")]
    text = status.log_text(offline.activity(), _check((conn,)), probes, time.time())
    assert "Refused: 1" in text and "Automatic requests not sent: 1" in text
    assert "WARNING  python.exe (pid 12) TCP outgoing 140.82.112.5:443" in text
    assert "OK  TCP connection to 203.0.113.1: refused by Work offline" in text
    assert "refused  downloading this link" in text and "not sent  the update check" in text
    assert "Bytes are not measured" in text and "send()" in text


# --- every network call asks first (or is listed with a reason) --------------

_NET_NAMES = frozenset({
    "urlopen", "urlretrieve", "build_opener", "create_connection", "HTTPConnection",
    "HTTPSConnection", "SMTP", "SMTP_SSL", "FTP", "snapshot_download", "hf_hub_download",
    "download_url_to_file", "load_state_dict_from_url", "download_model",
})
_NET_MODULES = frozenset({"requests", "httpx", "aiohttp", "websockets"})
_CHECK_NAMES = frozenset({
    "is_offline", "require_online", "refused", "skipped", "url_stays_local",
    "ensure_online", "_may_go_online",
})


def _dotted(node: ast.expr, aliases: dict[str, str] | None = None) -> str:
    parts: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):  # requests.Session().get
            node = node.func
        else:
            break
    if isinstance(node, ast.Name):
        parts.append((aliases or {}).get(node.id, node.id))
    return ".".join(reversed(parts))


def _is_network_call(name: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    head = name.split(".", 1)[0]
    if last in _NET_NAMES or name == "socket.socket":
        return True
    return head in _NET_MODULES and last[:1].islower() and last not in ("exceptions",)


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> full dotted name, from the module's imports (any depth)."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _functions(tree: ast.Module):
    """(qualified name, function node) for every function, nested ones included."""
    def walk(node: ast.AST, prefix: str):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{child.name}", child
                yield from walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def _network_functions() -> dict[str, bool]:
    """``path::qualified.name`` -> whether it asks core.offline itself."""
    found: dict[str, bool] = {}
    for path in sorted([*ROOT.glob("app/**/*.py"), *ROOT.glob("core/**/*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _aliases(tree)
        rel = path.relative_to(ROOT).as_posix()
        for qualname, node in _functions(tree):
            calls = [_dotted(n.func, aliases) for n in ast.walk(node) if isinstance(n, ast.Call)]
            if any(_is_network_call(c) for c in calls):
                asks = any(c.rsplit(".", 1)[-1] in _CHECK_NAMES for c in calls)
                found[f"{rel}::{qualname}"] = asks
    return found


def _allowlist() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, reason = line.partition("  ")
        assert reason.strip(), f"allow-list entry without a reason: {line}"
        entries[key.strip()] = reason.strip()
    return entries


def test_every_network_call_asks_work_offline_or_is_listed():
    found = _network_functions()
    allowed = _allowlist()
    unasked = sorted(k for k, asks in found.items() if not asks and k not in allowed)
    assert not unasked, (
        "These functions open a network connection without asking core.offline; "
        "add the check, or list them with a reason in "
        f"{ALLOWLIST.name}: {unasked}"
    )
    stale = sorted(k for k in allowed if k not in found)
    assert not stale, f"allow-list entries that no longer open a connection: {stale}"


def _scan_source(source: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _aliases(tree)
    return [_dotted(n.func, aliases) for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_the_scan_sees_a_new_unasked_call():
    # Negative controls for the rule above, including aliased imports.
    for source in (
        """import urllib.request
def f():
    urllib.request.urlopen('https://x')
""",
        """from urllib.request import urlopen as u
def f():
    u('https://x')
""",
        """import socket as s
def f():
    s.socket()
""",
        """from socket import socket
def f():
    socket()
""",
        """import requests
def f():
    requests.Session().get('https://x')
""",
    ):
        calls = _scan_source(source)
        assert any(_is_network_call(c) for c in calls), source
        assert not any(c.rsplit(".", 1)[-1] in _CHECK_NAMES for c in calls)
    assert len(_network_functions()) >= 20


def test_functions_are_keyed_by_their_qualified_name():
    tree = ast.parse("""class A:
    def go(self): pass
class B:
    def go(self): pass
""")
    assert [q for q, _ in _functions(tree)] == ["A.go", "B.go"]
