"""docs/SERVER.md must match the code it documents.

Checks the serve flags, the routes, the config keys, the OpenAI response
formats and the webhook payload keys against the real definitions, in both
directions (nothing documented that does not exist, nothing real left out).
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "SERVER.md")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def doc() -> str:
    with open(DOC, encoding="utf-8") as f:
        return f.read()


def _section(doc: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", doc,
                  re.S | re.M)
    assert m, f"section {heading!r} missing from SERVER.md"
    return m.group(1)


def _serve_flags() -> set[str]:
    import gui

    parser = gui._build_argparser()
    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    serve = sub.choices["serve"]
    flags: set[str] = set()
    for action in serve._actions:
        flags.update(o for o in action.option_strings if o.startswith("--")
                     and o != "--help")
    return flags


def test_every_serve_flag_is_documented_and_no_extra(doc: str) -> None:
    block = _section(doc, "Start it from the command line")
    options = block.split("Options of `serve`:", 1)[1].split("```")[1]
    documented = set(re.findall(r"^\s*(?:-\w, )?(--[a-z-]+)", options, re.M))
    assert documented == _serve_flags()


def test_documented_routes_exist_and_all_routes_are_documented(
        doc: str) -> None:
    from core.server.httpd import parse_route

    table = _section(doc, "JSON job API")
    rows = re.findall(r"^\| (GET|POST)\s+\| `([^`]+)` \|", table, re.M)
    assert rows, "route table not found"
    names: set[str] = set()
    for method, path in rows:
        concrete = (path.replace("<id>", "abc123")
                    .replace("?fmt=srt", ""))
        route = parse_route(method, concrete)
        assert route.name != "unknown", f"{method} {path} is not a real route"
        names.add(route.name)
    # Every logical route the parser knows must have a row.
    src = open(os.path.join(ROOT, "core", "server", "httpd.py"),
               encoding="utf-8").read()
    parser_src = src.split("def parse_route", 1)[1].split("def token_ok", 1)[0]
    known = set(re.findall(r'Route\(m, "([a-z_]+)"', parser_src))
    known |= {"result", "cancel", "pause", "resume", "outputs"}
    known.discard("unknown")
    assert names == known


def test_config_keys_documented_exist_in_defaults(doc: str) -> None:
    from core.config import DEFAULT_CONFIG

    block = _section(doc, "Configuration")
    keys = re.findall(r"^(server_[a-z_]+)\s", block, re.M)
    assert set(keys) == {k for k in DEFAULT_CONFIG if k.startswith("server_")}


def test_openai_response_formats_match(doc: str) -> None:
    from core.server.httpd import OPENAI_RESPONSE_FORMATS

    section = _section(doc, "OpenAI-compatible API")
    row = next(line for line in section.splitlines()
               if line.startswith("| `response_format`"))
    documented = set(re.findall(r"`([a-z_]+)`", row.split("|")[3]))
    assert documented == set(OPENAI_RESPONSE_FORMATS)


def test_webhook_payload_keys_match(doc: str) -> None:
    from core.server.jobs import Job, webhook_payload

    section = _section(doc, "Completion webhook")
    example = section.split("```", 2)[1]
    documented = set(re.findall(r'^\s*"([a-z_]+)":', example, re.M))
    job = Job(job_id="x", kind="upload", formats=["srt"])
    assert documented == set(webhook_payload(job))


def test_openai_models_payload_documented_id(doc: str) -> None:
    from core.server.httpd import JobRequestHandler

    payload = JobRequestHandler._openai_models_payload(None)  # type: ignore[arg-type]
    assert payload["data"][0]["id"] == "whisper-1"
    assert '"id": "whisper-1"' in doc


def test_auth_ways_documented(doc: str) -> None:
    from core.server.httpd import token_ok

    assert token_ok("s", "s", None)          # X-Auth-Token / Bearer value
    assert token_ok("s", None, "s")          # ?token=
    assert not token_ok("s", "wrong", None)
    section = _section(doc, "Authentication")
    for way in ("X-Auth-Token", "Authorization: Bearer", "?token="):
        assert way in section
