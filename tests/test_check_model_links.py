"""Tests for tools/check_model_links.py (no network): extraction from the real source files and the verdict rules."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_model_links", ROOT / "tools" / "check_model_links.py")
assert spec and spec.loader
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)

NO_SLEEP = lambda _s: None  # noqa: E731


def test_extracts_the_real_repositories_and_scripts():
    repos = links.hf_repos()
    assert "Systran/faster-whisper-tiny" in repos  # the app catalog
    assert "onnx-community/whisper-small" in repos  # the Try page
    assert "onnx-community/whisper-large-v3-turbo_timestamped" in repos
    assert any("transformers" in u for u in links.script_urls())
    assert len(repos) >= 10


def make_fetch(bad: dict[str, tuple[int, bytes]] | None = None):
    bad = bad or {}

    def fetch(url: str) -> tuple[int, bytes]:
        if url in bad:
            return bad[url]
        if url.startswith(links.HF_API):
            return 200, json.dumps({"siblings": [{"rfilename": "config.json"}]}).encode()
        return 200, b"x"
    return fetch


def test_all_fine_gives_exit_zero():
    code, lines = links.run(make_fetch(), sleep=NO_SLEEP)
    assert code == 0 and all(not ln.startswith("FAIL") for ln in lines)


def test_a_missing_repository_fails():
    code, lines = links.run(make_fetch({links.HF_API + "onnx-community/whisper-small": (404, b"")}), sleep=NO_SLEEP)
    assert code == 1
    assert any(ln.startswith("FAIL") and "onnx-community/whisper-small" in ln and "404" in ln for ln in lines)


def test_a_repository_without_files_fails():
    empty = (200, json.dumps({"siblings": []}).encode())
    code, lines = links.run(make_fetch({links.HF_API + "Systran/faster-whisper-tiny": empty}), sleep=NO_SLEEP)
    assert code == 1 and any("no files listed" in ln for ln in lines)


def test_rate_limit_only_warns_and_network_errors_are_retried():
    code, lines = links.run(make_fetch({links.HF_API + "Systran/faster-whisper-tiny": (429, b"")}), sleep=NO_SLEEP)
    assert code == 0 and any(ln.startswith("WARN") for ln in lines)
    calls: list[str] = []

    def flaky(url: str) -> tuple[int, bytes]:
        calls.append(url)
        return (0, b"") if len(calls) < 3 else (200, b"x")
    assert links.check("https://example.test/a", flaky, NO_SLEEP) == (200, b"x") and len(calls) == 3
    assert links.check("https://example.test/b", lambda _u: (0, b""), NO_SLEEP)[0] == 0  # gives up, reports unreachable


def test_a_dead_script_link_fails():
    dead = {u: (404, b"") for u in links.script_urls()}
    code, lines = links.run(make_fetch(dead), sleep=NO_SLEEP)
    assert code == 1 and any(ln.startswith("FAIL") and "cdn.jsdelivr.net" in ln for ln in lines)
