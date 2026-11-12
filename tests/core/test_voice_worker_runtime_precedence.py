"""Import conflicting stand-in runtimes through the actual worker protocol."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("cache_packages", [("torch", "omnivoice"), ("torch",), ("omnivoice",), ()])
def test_voice_worker_prefers_cached_voice_stack_without_changing_host(tmp_path, cache_packages):
    base = tmp_path / "base"
    cache = tmp_path / "cache"
    base.mkdir()
    cache.mkdir()
    cached_runtime = set(cache_packages) == {"torch", "omnivoice"}
    host_version = "host-legacy" if cached_runtime else "host-compatible"
    for root, version in [(base, host_version), (cache, "cache-compatible")]:
        if root == cache and "torch" not in cache_packages:
            continue
        package = root / "torch"
        package.mkdir()
        (package / "__init__.py").write_text(f"__version__ = {version!r}\n", encoding="utf-8")
    if "omnivoice" in cache_packages:
        package = cache / "omnivoice"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
    if cached_runtime:
        scipy = cache / "scipy"
        (scipy / "linalg").mkdir(parents=True)
        (scipy / "__init__.py").write_text("", encoding="utf-8")
        (scipy / "linalg/__init__.py").write_text(
            "import builtins, sys\nassert sys.platform != 'win32' or not getattr(builtins, '_stdin_started', False), "
            "'Native import happened after the stdin reader started'\n", encoding="utf-8")
    expected = "cache-compatible" if cached_runtime else "host-compatible"
    script = r'''
import builtins, json, sys, threading, types
from core import optional_deps, voice_clone_worker
base, cache, expected = sys.argv[1:]
sys.path.insert(0, base)
optional_deps.extras_dir = lambda: cache
voice_clone_worker.setup_logging = lambda *a, **kw: None
original_start = threading.Thread.start
def start(thread):
    if thread.name == "voiceclone-stdin":
        builtins._stdin_started = True
    return original_start(thread)
threading.Thread.start = start
if expected != "cache-compatible":
    scipy = types.ModuleType("scipy")
    scipy.__path__ = []
    sys.modules["scipy"] = scipy
    sys.modules["scipy.linalg"] = types.ModuleType("scipy.linalg")
fake = types.ModuleType("core.voice_clone")
def load_model(device):
    import torch
    import scipy.linalg
    if torch.__version__ != expected:
        raise RuntimeError("Host runtime overrode the feature runtime: " + torch.__version__)
    return object()
fake.load_model = load_model
fake.generate = lambda *_a, **_kw: types.SimpleNamespace(
    output_path="synthetic.wav",audio_seconds=1.0,elapsed_seconds=0.1,warning="")
sys.modules["core.voice_clone"] = fake
raise SystemExit(voice_clone_worker.main())
'''
    env = dict(os.environ, WTS_PROFILE_DIR=str(tmp_path / "profile"))
    request = {"action": "generate", "id": "test", "text": "A test.", "output_path": "unused.wav"}
    result = subprocess.run(
        [sys.executable, "-c", script, str(base), str(cache), expected],
        cwd=Path(__file__).resolve().parents[2], env=env,
        input=json.dumps(request) + '\n{"action":"shutdown"}\n',
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert any(e["event"] == "done" for e in events), events
    assert not any(e["event"] in {"error", "model_error"} for e in events), events
    # A separate host interpreter still sees its own installed runtime.
    host_script = ("import sys; from core import optional_deps; "
                   "sys.path.insert(0,sys.argv[1]); optional_deps.extras_dir=lambda:sys.argv[2]; "
                   "optional_deps.activate(); import torch; print(torch.__version__)")
    host = subprocess.run([sys.executable, "-c", host_script, str(base), str(cache)],
                          cwd=Path(__file__).resolve().parents[2], env=env,
                          capture_output=True, text=True, timeout=10)
    assert host.returncode == 0
    assert host.stdout.strip() == host_version


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native-library initialization")
@pytest.mark.parametrize("failure", ["scipy", "numpy", "native-abi"])
def test_windows_worker_reports_broken_prewarm_but_allows_missing_optional_scipy(tmp_path, failure):
    script = r'''
import sys, types
from core import voice_clone_worker as worker
worker.setup_logging = lambda *a, **kw: None
def import_runtime(name):
    if sys.argv[1] == "native-abi":
        raise OSError("Native runtime ABI failure")
    raise ModuleNotFoundError("Missing " + sys.argv[1], name=sys.argv[1])
worker.importlib.import_module = import_runtime
sys.modules["core.voice_clone"] = types.ModuleType("core.voice_clone")
raise SystemExit(worker.main())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, failure], cwd=Path(__file__).resolve().parents[2],
        env=dict(os.environ, WTS_PROFILE_DIR=str(tmp_path / "profile")),
        input='{"action":"shutdown"}\n', capture_output=True, text=True, timeout=10,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    if failure == "scipy":
        assert result.returncode == 0 and any(e["event"] == "ready" for e in events)
        assert not any(e["event"] == "model_error" for e in events)
    else:
        assert result.returncode == 1
        assert not any(e["event"] == "ready" for e in events)
        assert any(e["event"] == "model_error" and "initialization failed" in e["message"] for e in events)
