"""Tests for app.observability — Sentry gate + launch ping gate."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def obs(monkeypatch):
    # Reload so module-level state is fresh per test.
    for m in [k for k in list(sys.modules) if k.startswith("app.observability")]:
        del sys.modules[m]
    import app.observability as o
    return o


def test_init_sentry_no_op_when_opt_out(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: False)
    assert obs.init_sentry() is False


def test_init_sentry_no_op_without_dsn(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert obs.init_sentry() is False


def test_init_sentry_runs_when_opt_in_and_dsn_set(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("SENTRY_DSN", "https://example.invalid/123")

    captured: dict = {}

    fake_mod = types.ModuleType("sentry_sdk")
    def _init(**kw):
        captured.update(kw)
    fake_mod.init = _init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_mod)

    assert obs.init_sentry() is True
    assert captured["dsn"] == "https://example.invalid/123"
    assert captured["send_default_pii"] is False


def test_launch_ping_skipped_without_opt_in(obs, monkeypatch):
    """opt_in=False → no thread spawned, no urlopen call."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: False)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    called = {"opened": False}
    monkeypatch.setattr(
        obs.urllib.request,
        "urlopen",
        lambda *_a, **_kw: called.__setitem__("opened", True) or types.SimpleNamespace(read=lambda: b""),
    )
    obs.send_launch_ping_async()
    # Daemon thread would have raced; we never spawned one, so the
    # call counter stays 0.
    import time
    time.sleep(0.1)
    assert called["opened"] is False


def test_launch_ping_skipped_without_url(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.delenv("WHISPER_TELEMETRY_URL", raising=False)
    obs.send_launch_ping_async()  # must not raise


@pytest.mark.parametrize("url", [
    "file:///etc/hosts",
    "ftp://collector.invalid/ping",
    "collector.invalid/ping",
])
def test_launch_ping_refuses_a_non_web_url(obs, monkeypatch, url):
    """The env var goes straight to urlopen, which opens file:// and ftp://."""
    import core._threads as threads

    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", url)
    started: list[str] = []
    monkeypatch.setattr(
        threads, "safe_thread", lambda *_a, **kw: started.append(kw.get("name", "")))
    obs.send_launch_ping_async()
    assert started == []


def test_launch_ping_still_starts_for_a_web_url(obs, monkeypatch):
    import core._threads as threads

    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "HTTPS://collector.invalid/ping")
    started: list[str] = []
    monkeypatch.setattr(
        threads, "safe_thread", lambda *_a, **kw: started.append(kw.get("name", "")))
    obs.send_launch_ping_async()
    assert started == ["launch-ping"]


def test_anonymised_id_is_stable(obs, monkeypatch, tmp_path):
    """Two calls in the same install yield the same id."""
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: tmp_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)
    a = obs._anonymised_id()
    b = obs._anonymised_id()
    assert a and a == b
    # The on-disk file matches what we returned.
    assert (tmp_path / "telemetry_id").read_text(encoding="utf-8").strip() == a


def test_init_sentry_swallows_sdk_init_failure(obs, monkeypatch):
    """A malformed DSN (or any other SDK init error) must not propagate.

    ``init_sentry`` is called unguarded from ``App.__init__``; an exception
    here aborts startup before the window exists."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("SENTRY_DSN", "not-even-a-url")

    fake_mod = types.ModuleType("sentry_sdk")

    def _init(**kw):
        raise RuntimeError("bad dsn")

    fake_mod.init = _init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_mod)

    assert obs.init_sentry() is False  # must not raise


def test_anonymised_id_empty_when_cache_dir_unavailable(obs, monkeypatch, tmp_path):
    """An unwritable cache path yields no id instead of raising."""
    blocker = tmp_path / "cache"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: blocker / "nested"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)

    assert obs._anonymised_id() == ""


def test_launch_ping_survives_unwritable_cache_dir(obs, monkeypatch, tmp_path):
    """The ping is best-effort on the Tk main thread: an id it cannot
    persist must be swallowed, not surfaced to the user as a launch crash."""
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("WHISPER_TELEMETRY_URL", "https://example.invalid/ping")
    blocker = tmp_path / "cache"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    fake_cfg = types.ModuleType("core.config")
    fake_cfg.user_cache_dir = lambda: blocker / "nested"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.config", fake_cfg)
    monkeypatch.setattr(
        obs.urllib.request,
        "urlopen",
        lambda *_a, **_kw: types.SimpleNamespace(read=lambda: b""),
    )

    obs.send_launch_ping_async()  # must not raise

    import time
    time.sleep(0.1)


# --- crash-report scrubbing --------------------------------------------------

def _strings(obj):
    """Every key and string value of a JSON-like object."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _sentry_event() -> dict:
    """A Sentry event shaped like sentry-sdk 2.x output, full of private data."""
    win_media = r"C:\Users\someone\Videos\Interview with Dr Zed 2026.mkv"
    return {
        "server_name": "HOST-PC-1234",
        "user": {"id": "someone"},
        "request": {"url": "http://localhost/someone"},
        "extra": {"sys.argv": ["WhisperTranscriber.exe", win_media]},
        "breadcrumbs": {"values": [
            {"category": "app", "message": "Transcribing /home/someone/Private Talk.wav"},
        ]},
        "logentry": {
            "message": "could not save %s",
            "params": [r"D:\someone\Private Talk.wav"],
            "formatted": r"could not save D:\someone\Private Talk.wav",
        },
        "message": "no transcript for 'Private Talk.wav'",
        "tags": {"source": "https://www.youtube.com/watch?v=someone"},
        "contexts": {"runtime": {"name": "CPython", "version": "3.14.4"}},
        "exception": {"values": [{
            "type": "FileNotFoundError",
            "module": None,
            "value": "[Errno 2] No such file or directory: " + repr(win_media),
            "stacktrace": {"frames": [{
                "filename": r"C:\Users\someone\AppData\Local\WTS\app\services\transcription_service.py",
                "abs_path": r"C:\Users\someone\AppData\Local\WTS\app\services\transcription_service.py",
                "module": "app.services.transcription_service",
                "function": "_run",
                "lineno": 42,
                "context_line": "    open(path)",
                "vars": {"path": repr(win_media)},
            }]},
        }]},
        "threads": {"values": [{"stacktrace": {"frames": [{
            "filename": "/home/someone/wts/core/worker.py",
            "abs_path": "/home/someone/wts/core/worker.py",
            "function": "run",
            "lineno": 7,
        }]}}]},
        "_extra_message": "failed on /tmp/مصاحبه-خصوصی-۱۴۰۵.wav after 3 tries",
    }


def test_scrubbed_event_keeps_no_path_name_or_host(obs):
    out = obs.scrub_sentry_event(_sentry_event(), {})
    blob = "\n".join(_strings(out))
    for leaked in ("someone", "Interview", "Dr Zed", "Private Talk", "youtube",
                   "HOST-PC-1234", "مصاحبه", "abs_path", "vars", "sys.argv",
                   "breadcrumbs", "server_name"):
        assert leaked not in blob, leaked
    # What the code itself defines survives, so the report stays useful.
    exc = out["exception"]["values"][0]
    assert exc["type"] == "FileNotFoundError"
    assert exc["value"].startswith("[Errno 2] No such file or directory: ")
    frame = exc["stacktrace"]["frames"][0]
    assert frame == {
        "filename": "transcription_service.py",
        "module": "app.services.transcription_service",
        "function": "_run",
        "lineno": 42,
        "context_line": "    open(path)",
    }
    assert out["threads"]["values"][0]["stacktrace"]["frames"][0]["filename"] == "worker.py"
    assert out["logentry"] == {"message": "could not save %s"}
    assert out["contexts"] == {"runtime": {"name": "CPython", "version": "3.14.4"}}


@pytest.mark.parametrize("text", [
    "KeyError: 'model'",
    "division by zero",
    "list index out of range",
    "3/4 segments written",
])
def test_scrub_keeps_messages_without_paths(obs, text):
    assert obs._scrub_text(text) == text


def test_init_sentry_scrubs_every_event(obs, monkeypatch):
    monkeypatch.setattr(obs, "_telemetry_opted_in", lambda: True)
    monkeypatch.setenv("SENTRY_DSN", "https://example.invalid/123")
    captured: dict = {}
    fake_mod = types.ModuleType("sentry_sdk")
    fake_mod.init = lambda **kw: captured.update(kw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_mod)

    assert obs.init_sentry() is True
    assert captured["before_send"] is obs.scrub_sentry_event
    assert captured["include_local_variables"] is False
    assert captured["max_breadcrumbs"] == 0
    assert captured["send_default_pii"] is False


# Runs in a child process: sentry_sdk.init patches logging and sys.excepthook
# for the whole process. The capturing transport keeps it off the network.
# The private strings are built at run time so the probe's own source lines
# (sent as frame context) do not contain them.
_PROBE = """
import json, logging, sys
import sentry_sdk
from sentry_sdk.transport import Transport

EVENTS = []

class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.payload.json is not None:
                EVENTS.append(item.payload.json)

sys.path.insert(0, sys.argv[2])
from app.observability import _sentry_options
opts = _sentry_options("https://key@example.invalid/1")
if sys.argv[1] == "plain":
    opts = {"dsn": opts["dsn"], "send_default_pii": False}
opts["transport"] = Capture
sentry_sdk.init(**opts)
sep, user = chr(92), "some" + "one"
media = sep.join(["C:", "Users", user, "Videos", "Inter" + "view 2026.mkv"])
log = logging.getLogger("probe")
log.warning("Transcribing " + media)
try:
    open(media, "rb")
except OSError:
    sentry_sdk.capture_exception()
log.error("could not save %s", "/home/" + user + "/Private " + "Talk.wav")
sentry_sdk.flush()
print(json.dumps(EVENTS))
"""


def _probe_events(tmp_path: Path, mode: str) -> list:
    probe = tmp_path / "crash_probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(probe), mode, str(REPO_ROOT)],
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(importlib.util.find_spec("sentry_sdk") is None,
                    reason="sentry-sdk (crash_reporting extra) not installed")
def test_real_sentry_events_carry_no_path_name_or_host(tmp_path):
    import socket
    private = ("someone", "Interview", "Private Talk", str(tmp_path),
               socket.gethostname())

    # Control: the SDK's default event does carry them, so the check can fail.
    plain = "\n".join(_strings(_probe_events(tmp_path, "plain")))
    assert all(p in plain for p in private)

    events = _probe_events(tmp_path, "scrubbed")
    assert len(events) == 2
    blob = "\n".join(_strings(events))
    for leaked in private + ("abs_path", "vars", "server_name"):
        assert leaked not in blob, leaked
    exc = events[0]["exception"]["values"][-1]
    assert exc["type"] == "FileNotFoundError"
    assert exc["stacktrace"]["frames"][-1]["filename"] == "crash_probe.py"
    assert events[1]["logentry"]["message"] == "could not save %s"
