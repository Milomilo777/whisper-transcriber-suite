"""Work offline (core.offline): the switch, the config layer and the socket backstop.

The call sites that ask the switch are covered in test_offline_call_sites.py.
"""
from __future__ import annotations

import json
import math
import socket
import threading

import pytest

import core.config as cfg
from core import offline


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """config.json in tmp_path; the switch is read from it (no in-memory value)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(cfg, "config_path", lambda: str(config_dir / "config.json"))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))
    monkeypatch.setattr(offline, "_override", None)
    monkeypatch.setattr(offline, "_last_saved", False)
    return config_dir / "config.json"


@pytest.fixture
def guard():
    """Install the socket backstop for one test and always remove it again."""
    offline.install_network_guard()
    try:
        yield
    finally:
        offline.uninstall_network_guard()


# --- the switch --------------------------------------------------------------

def test_message_names_the_action_and_the_switch():
    text = offline.message("downloading this link")
    assert text.startswith("Offline mode is on: downloading this link needs the internet.")
    assert offline.SWITCH_NAME in text and "File > Work offline" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), (1, True), (0, False), (1.0, True), (0.0, False),
     ("true", True), ("false", False),
     # Neither clearly on nor clearly off: fail closed (offline).
     (math.nan, True), (math.inf, True), ("junk", True), (None, True), ([1], True)],
)
def test_flag_from_follows_the_loaders_coercion(value, expected):
    assert offline.flag_from({offline.CONFIG_KEY: value}) is expected


def test_flag_from_defaults_to_off():
    assert offline.flag_from({}) is False


def test_in_memory_switch_wins_over_the_file(isolated_config):
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    offline.set_offline(False)
    assert offline.is_offline() is False
    offline.set_offline(True)
    assert offline.is_offline() is True
    assert offline.is_offline({"work_offline": False}) is True
    offline.set_offline(None)
    assert offline.is_offline() is True


def test_a_given_config_dict_is_used_instead_of_the_file(isolated_config):
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    assert offline.is_offline({"work_offline": False}) is False
    assert offline.is_offline({}) is False
    assert offline.is_offline({"work_offline": True}) is True


def test_the_file_is_read_on_every_call(isolated_config):
    assert offline.is_offline() is False  # no config.json yet
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    assert offline.is_offline() is True
    isolated_config.write_text(json.dumps({"work_offline": False}), encoding="utf-8")
    assert offline.is_offline() is False


@pytest.mark.parametrize("body", ["{not json", "[1, 2]", '"text"'])
def test_a_damaged_config_without_a_backup_counts_as_on(isolated_config, body):
    # The saved choice is unknown: fail closed rather than go online.
    isolated_config.write_text(body, encoding="utf-8")
    assert offline.is_offline() is True


def test_a_damaged_config_reads_the_switch_from_its_backup(isolated_config):
    bak = isolated_config.with_name(isolated_config.name + ".bak")
    bak.write_text(json.dumps({"work_offline": False}), encoding="utf-8")
    isolated_config.write_text("{not json", encoding="utf-8")
    assert offline.is_offline() is False


def test_a_transient_read_error_keeps_the_last_value(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    assert offline.is_offline() is True

    def locked(*_a, **_k):
        raise PermissionError("being replaced")

    monkeypatch.setattr("builtins.open", locked)
    assert offline.is_offline() is True


def test_require_online_refuses_only_while_offline():
    offline.set_offline(False)
    offline.require_online("anything")  # no raise
    offline.set_offline(True)
    with pytest.raises(offline.OfflineModeError) as info:
        offline.require_online("downloading the model tiny")
    assert isinstance(info.value, ConnectionError)
    assert str(info.value) == offline.message("downloading the model tiny")


# --- config: local only, and the online config is not fetched -----------------

def test_work_offline_is_a_local_only_key_with_an_off_default():
    assert cfg.DEFAULT_CONFIG["work_offline"] is False
    assert "work_offline" in cfg.LOCAL_ONLY_KEYS
    assert "work_offline" not in cfg.ONLINE_ALLOWED_KEYS


def test_the_online_layer_can_never_set_or_clear_it():
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"work_offline": False}, {"work_offline": True})
    assert merged["work_offline"] is True
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"work_offline": True}, {})
    assert merged["work_offline"] is False


def _record_fetches(monkeypatch) -> list[str]:
    urls: list[str] = []

    def fake_fetch(url, **_kw):
        urls.append(url)
        return {"latest_version": "9.9.9"} if url else {"latest_version": "cached"}

    monkeypatch.setattr(cfg, "fetch_online_config", fake_fetch)
    cfg.refresh_online_config()
    return urls


def test_online_config_is_not_fetched_while_offline(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    urls = _record_fetches(monkeypatch)
    merged = cfg.load_config()
    assert urls == [""]  # only the cache read, no URL
    assert merged["latest_version"] == "cached"
    assert merged["work_offline"] is True


def test_online_config_is_fetched_while_online(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"work_offline": False}), encoding="utf-8")
    urls = _record_fetches(monkeypatch)
    cfg.load_config()
    assert urls == [cfg.DEFAULT_CONFIG["config_url"]]


def test_the_in_memory_switch_also_stops_the_fetch(isolated_config, monkeypatch):
    isolated_config.write_text("{}", encoding="utf-8")
    offline.set_offline(True)
    urls = _record_fetches(monkeypatch)
    cfg.load_config()
    assert urls == [""]


def test_offline_load_makes_no_request(isolated_config, monkeypatch):
    """The real fetch with a URL would call urlopen; offline it must not."""
    isolated_config.write_text(json.dumps({"work_offline": True}), encoding="utf-8")
    cfg.refresh_online_config()

    def boom(*_a, **_k):
        raise AssertionError("urlopen called while offline")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", boom)
    cfg.load_config()


def test_the_choice_survives_a_save_and_a_reload(isolated_config, monkeypatch):
    _record_fetches(monkeypatch)
    conf = cfg.load_config()
    conf["work_offline"] = True
    cfg.save_config(conf)
    assert json.loads(isolated_config.read_text(encoding="utf-8"))["work_offline"] is True
    assert offline.is_offline() is True
    assert cfg.load_config()["work_offline"] is True


# --- the socket backstop -----------------------------------------------------

def test_connect_allowed_only_on_this_computer():
    tcp, udp = socket.SOCK_STREAM, socket.SOCK_DGRAM
    v4, v6 = socket.AF_INET, socket.AF_INET6
    assert offline.connect_allowed(v4, tcp, ("127.0.0.1", 80))
    assert offline.connect_allowed(v4, tcp, ("127.8.9.10", 80))
    assert offline.connect_allowed(v4, tcp, ("localhost", 80))
    assert offline.connect_allowed(v6, tcp, ("::1", 80, 0, 0))
    assert not offline.connect_allowed(v4, tcp, ("93.184.216.34", 443))
    assert not offline.connect_allowed(v4, tcp, ("192.168.1.10", 443))
    assert not offline.connect_allowed(v4, tcp, ("example.com", 443))
    assert not offline.connect_allowed(v6, tcp, ("2606:4700::1111", 443, 0, 0))
    assert not offline.connect_allowed(v4, tcp, "bogus")
    assert offline.connect_allowed(v4, udp, ("8.8.8.8", 80))  # route pick, sends nothing
    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is not None:
        assert offline.connect_allowed(af_unix, tcp, "/tmp/sock")


def test_lookup_allowed_only_without_a_query():
    for host in (None, "", "localhost", "LOCALHOST", "a.localhost", "127.0.0.1", "8.8.8.8",
                 "::1", b"localhost", socket.gethostname()):
        assert offline.lookup_allowed(host), host
    for host in ("example.com", "smch.ir", "api.github.com", b"huggingface.co"):
        assert not offline.lookup_allowed(host), host


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def connect(self, _sock, address):
        self.calls.append(("connect", address))

    def connect_ex(self, _sock, address):
        self.calls.append(("connect_ex", address))
        return 0

    def getaddrinfo(self, host, *_a, **_k):
        self.calls.append(("getaddrinfo", host))
        return []


@pytest.fixture
def recorded_socket(monkeypatch):
    """socket's real entry points replaced by a recorder, then the guard on top."""
    offline.uninstall_network_guard()  # the guard must wrap the recorder
    rec = _Recorder()
    monkeypatch.setattr(socket.socket, "connect", rec.connect)
    monkeypatch.setattr(socket.socket, "connect_ex", rec.connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", rec.getaddrinfo)
    offline.install_network_guard()
    try:
        yield rec
    finally:
        offline.uninstall_network_guard()


def test_backstop_refuses_remote_connections_and_lookups_while_offline(recorded_socket):
    offline.set_offline(True)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(offline.OfflineModeError, match="Offline mode is on"):
            s.connect(("93.184.216.34", 443))
        with pytest.raises(offline.OfflineModeError):
            s.connect_ex(("93.184.216.34", 443))
        with pytest.raises(offline.OfflineModeError, match="smch.ir"):
            socket.getaddrinfo("smch.ir", 443)
        with pytest.raises(OSError):  # what urllib / requests already handle
            socket.getaddrinfo("api.github.com", 443)
        assert recorded_socket.calls == []
        s.connect(("127.0.0.1", 9))
        socket.getaddrinfo("localhost", 9)
        assert recorded_socket.calls == [("connect", ("127.0.0.1", 9)), ("getaddrinfo", "localhost")]
    finally:
        s.close()


def test_backstop_lets_everything_through_while_online(recorded_socket):
    offline.set_offline(False)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("93.184.216.34", 443))
        socket.getaddrinfo("smch.ir", 443)
    finally:
        s.close()
    assert recorded_socket.calls == [("connect", ("93.184.216.34", 443)), ("getaddrinfo", "smch.ir")]


def test_backstop_follows_the_switch_without_reinstalling(recorded_socket):
    offline.set_offline(True)
    with pytest.raises(offline.OfflineModeError):
        socket.getaddrinfo("smch.ir", 443)
    offline.set_offline(False)
    socket.getaddrinfo("smch.ir", 443)
    assert recorded_socket.calls == [("getaddrinfo", "smch.ir")]


def test_install_is_idempotent_and_uninstall_restores(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(socket, "getaddrinfo", rec.getaddrinfo)
    offline.install_network_guard()
    patched = socket.getaddrinfo
    offline.install_network_guard()
    assert socket.getaddrinfo is patched and offline.network_guard_installed()
    offline.uninstall_network_guard()
    assert socket.getaddrinfo == rec.getaddrinfo
    assert not offline.network_guard_installed()
    offline.uninstall_network_guard()  # a second call is a no-op


def test_backstop_blocks_a_real_http_request_before_any_lookup(guard, monkeypatch):
    """urllib through the real socket module: refused at the name lookup."""
    import urllib.error
    import urllib.request

    offline.set_offline(True)
    with pytest.raises((urllib.error.URLError, OSError)) as info:
        urllib.request.urlopen("https://api.github.com/", timeout=5)
    assert "Offline mode is on" in str(info.value)


def test_backstop_keeps_loopback_working(guard):
    """A real TCP round trip to a local listener still works while offline."""
    offline.set_offline(True)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    got: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            got.append(conn.recv(5))

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        with socket.create_connection(("localhost", port), timeout=5) as c:
            c.sendall(b"hello")
        t.join(5)
    finally:
        server.close()
    assert got == [b"hello"]


# --- child processes ---------------------------------------------------------

def test_child_env_points_proxies_at_a_closed_local_port_while_offline():
    base = {"PATH": "x", "NO_PROXY": "*", "no_proxy": "*", "HTTPS_PROXY": "http://corp:8080"}
    offline.set_offline(True)
    env = offline.child_env(base)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert env[name] == "http://127.0.0.1:9"
    assert "NO_PROXY" not in env and "no_proxy" not in env
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["PATH"] == "x"
    assert base["HTTPS_PROXY"] == "http://corp:8080"  # the input is not changed


def test_child_env_is_a_plain_copy_while_online():
    base = {"PATH": "x", "NO_PROXY": "*"}
    offline.set_offline(False)
    env = offline.child_env(base)
    assert env == base and env is not base


# --- docs --------------------------------------------------------------------

def _network_rows() -> list[list[str]]:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    section = text.split("\n## Network use", 1)[1].split("\n## ", 1)[0]
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines() if line.startswith("|")
    ]


def test_network_table_says_what_work_offline_does_to_every_row():
    rows = _network_rows()
    header, separator, body = rows[0], rows[1], rows[2:]
    assert header[-1] == "Blocked by Work offline"
    assert len(separator) == len(header)
    assert len(body) >= 15  # parser control: the table has its rows
    for row in body:
        assert len(row) == len(header), row[0]
        assert row[-1].startswith(("Yes", "Outbound only")), row[0]


def test_config_reference_documents_the_key():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `work_offline` |"))
    assert "| bool | `false` |" in row and "Local only" in row
    assert "File → Work offline" in text and "Advanced → App behaviour" in text
