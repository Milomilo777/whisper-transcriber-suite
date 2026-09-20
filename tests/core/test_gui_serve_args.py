"""Tests for ``gui.py serve`` argument handling.

``--port`` used to be a plain ``int``, so ``--port 70000`` / ``--port -1``
reached ``socket.bind``, which raises ``OverflowError`` — not an
``OSError``, so ``run_server``'s bind-failure handler misses it and the
CLI died with a raw traceback instead of a usage error.
"""
from __future__ import annotations

import pytest

import gui


def test_serve_port_accepts_bindable_ports():
    parser = gui._build_argparser()
    assert parser.parse_args(["serve", "--port", "0"]).port == 0
    assert parser.parse_args(["serve", "--port", "65535"]).port == 65535


@pytest.mark.parametrize("bad", ["70000", "-1", "65536", "not-a-port"])
def test_serve_port_rejects_unbindable_values(bad: str):
    parser = gui._build_argparser()
    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--port", bad])


def _install_fake_run_server(monkeypatch):
    import core.server as server_mod

    captured: dict = {}

    def fake_run_server(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(server_mod, "run_server", fake_run_server)
    return captured


def test_cli_serve_forwards_explicit_flags(monkeypatch):
    captured = _install_fake_run_server(monkeypatch)
    monkeypatch.setattr(
        "core.config.load_config",
        lambda: {"server_port": 9000, "server_max_upload_mb": 128},
    )

    args = gui._build_argparser().parse_args([
        "serve",
        "--host", "192.168.1.7",
        "--port", "8765",
        "--token", "secret",
        "--max-upload-mb", "64",
    ])
    assert gui._cli_serve(args) == 0
    assert captured == {
        "host": "192.168.1.7",
        "port": 8765,
        "token": "secret",
        "max_upload_mb": 64,
    }


def test_cli_serve_falls_back_to_config_values(monkeypatch):
    captured = _install_fake_run_server(monkeypatch)
    monkeypatch.setattr(
        "core.config.load_config",
        lambda: {"server_port": 9001, "server_max_upload_mb": 256},
    )

    args = gui._build_argparser().parse_args(["serve"])
    assert gui._cli_serve(args) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["max_upload_mb"] == 256


def test_cli_serve_lan_binds_all_interfaces(monkeypatch):
    captured = _install_fake_run_server(monkeypatch)
    monkeypatch.setattr(
        "core.config.load_config",
        lambda: {"server_port": 8765, "server_max_upload_mb": 512},
    )

    args = gui._build_argparser().parse_args(
        ["serve", "--host", "192.168.1.7", "--lan"]
    )
    assert gui._cli_serve(args) == 0
    assert captured["host"] == "0.0.0.0"


@pytest.mark.parametrize("bad_port", [70000, -1, 65536, "not-a-port", None])
def test_cli_serve_rejects_invalid_config_port(monkeypatch, bad_port, capsys):
    """A hand-edited config ``server_port`` must fail clean, not traceback.

    ``--port`` is validated by ``_port_number``, but the config fallback used
    to flow verbatim into ``socket.bind``: out-of-range ints raised
    ``OverflowError`` (which ``run_server``'s ``except OSError`` misses) and
    non-numeric values died in ``int()`` — both raw tracebacks.
    """
    called = []

    def fake_run_server(**kwargs):
        called.append(kwargs)
        return 0

    import core.server as server_mod

    monkeypatch.setattr(server_mod, "run_server", fake_run_server)
    monkeypatch.setattr(
        "core.config.load_config",
        lambda: {"server_port": bad_port, "server_max_upload_mb": 512},
    )

    args = gui._build_argparser().parse_args(["serve"])
    assert gui._cli_serve(args) == 1
    assert called == [], "run_server must not be reached with a bad port"
    assert "server_port" in capsys.readouterr().err
