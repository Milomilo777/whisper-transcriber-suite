"""The stats Worker (platform/stats-worker/) stays in step with the app and with the PHP endpoint it replaces.

The Worker accepts the PHP script's form, so its caps must match ``$text_limits``; the app's default
``stats_url`` must point at the Worker's custom domain; problem reports sent through the stats form
must fit the Worker's caps. When Node.js 22.5+ is installed, the Worker's own tests run too. No network.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

from core import problem_report
from core.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "platform" / "stats-worker"
JS = (WORKER / "src" / "index.js").read_text(encoding="utf-8")
PHP = (ROOT / "platform" / "stats-server" / "transcription_stats.php").read_text(encoding="utf-8")
TOML = (WORKER / "wrangler.toml").read_text(encoding="utf-8")


def _worker_limits() -> dict[str, int]:
    block = re.search(r"export const TEXT_LIMITS = \{(.*?)\};", JS, re.S)
    assert block, "TEXT_LIMITS not found in src/index.js"
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", block.group(1))}


def _php_limits() -> dict[str, int]:
    block = re.search(r"\$text_limits = array\((.*?)\);", PHP, re.S)
    assert block, "$text_limits not found in transcription_stats.php"
    return {k: int(v) for k, v in re.findall(r"'(\w+)'\s*=>\s*(\d+)", block.group(1))}


def test_the_worker_keeps_the_php_text_limits():
    assert _worker_limits() == _php_limits()


def test_problem_reports_sent_through_the_stats_form_fit_the_worker():
    limits = _worker_limits()
    for field, size in problem_report.TEXT_FIELDS:
        assert size <= limits[field], field


def test_the_default_stats_url_is_the_workers_runs_endpoint():
    url = urlparse(DEFAULT_CONFIG["stats_url"])
    assert url.scheme == "https" and url.path == "/v1/runs"
    domains = re.findall(r'pattern\s*=\s*"([^"]+)"\s*,\s*custom_domain\s*=\s*true', TOML)
    assert url.hostname in domains
    assert "'/v1/runs'" in JS


def test_no_secret_is_configured_in_the_repo():
    assert not re.search(r"(?im)^\s*(STATS_USER|STATS_PASSWORD)\s*=", TOML)
    assert not re.search(r"(?im)^\s*\[vars\]", TOML)
    assert not (WORKER / ".dev.vars").exists()


def _node_version() -> tuple[int, int] | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


@pytest.mark.timeout(180)
def test_the_workers_own_tests_pass_when_node_is_available():
    version = _node_version()
    if version is None or version < (22, 5):
        pytest.skip("Node.js 22.5+ (node:sqlite) not installed")
    tests = sorted(str(p) for p in (WORKER / "test").glob("*.test.mjs"))
    result = subprocess.run(
        # Node 22 prints TAP when stdout is not a terminal, Node 23+ the spec format: pin one.
        ["node", "--test", "--test-reporter=spec", "--no-warnings=ExperimentalWarning", *tests],
        cwd=WORKER, capture_output=True, text=True, encoding="utf-8", timeout=170,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert re.search(r"(?m)^ℹ fail 0$", result.stdout), result.stdout[-2000:]
