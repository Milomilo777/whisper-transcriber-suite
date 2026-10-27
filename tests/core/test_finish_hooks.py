"""After a transcription finishes: Obsidian note and completion webhook.

Hermetic: files go to tmp dirs, the webhook receiver is a loopback listener.
No Tk. The dummy secret is neutral, never a real credential.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from core import finish_hooks as fh
from core import offline
from core.config import DEFAULT_CONFIG, LOCAL_ONLY_KEYS
from core.server.jobs import DEFAULT_WEBHOOK_HEADER

SECRET = "dummy-credential-A"
ROOT = Path(__file__).resolve().parents[2]

SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "Hello there."},
    {"start": 65.5, "end": 70.0, "text": "Second line.", "speaker": "Ann"},
]


def _job(tmp_path: Path, **kw: Any) -> fh.FinishedJob:
    base: dict[str, Any] = dict(
        job_id="h7", title="My talk", source=str(tmp_path / "talk.mp4"),
        status="finished", language="en", model="large-v3", duration=70.0,
        output_paths=[str(tmp_path / "talk.srt")], finished_at=1_790_000_000.0,
    )
    base.update(kw)
    return fh.FinishedJob(**base)


class _Receiver:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.statuses = list(statuses or [200])
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                outer.requests.append({"headers": dict(self.headers.items()),
                                       "body": json.loads(body)})
                code = outer.statuses.pop(0) if len(outer.statuses) > 1 else outer.statuses[0]
                self.send_response(code)
                self.end_headers()

            def log_message(self, *a: Any) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def receiver():
    made: list[_Receiver] = []

    def make(statuses: list[int] | None = None) -> _Receiver:
        r = _Receiver(statuses)
        made.append(r)
        return r

    yield make
    for r in made:
        r.close()


@pytest.fixture(autouse=True)
def _online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offline, "is_offline", lambda config=None: False)


# --- file names --------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('a<b>c:d"e/f\\g|h?i*j', "abcdefghij"),
    ("CON", "_CON"), ("nul", "_nul"), ("COM1.txt", "_COM1.txt"), ("lpt9", "_lpt9"),
    ("  spaced out  ", "spaced out"), ("dots...", "dots"), ("", "Transcript"),
    ("...", "Transcript"), ("tab\there\x00x", "tab herex"),
])
def test_safe_note_stem(raw: str, expected: str) -> None:
    assert fh.safe_note_stem(raw) == expected


def test_safe_note_stem_is_length_limited() -> None:
    assert len(fh.safe_note_stem("x" * 500)) <= 100


def test_unique_note_path_numbers_collisions(tmp_path: Path) -> None:
    (tmp_path / "T.md").write_text("a")
    (tmp_path / "T (1).md").write_text("b")
    assert fh.unique_note_path(str(tmp_path), "T") == str(tmp_path / "T (2).md")
    assert fh.unique_note_path(str(tmp_path), "New") == str(tmp_path / "New.md")


# --- the note ----------------------------------------------------------------

def test_note_has_front_matter_and_timestamps(tmp_path: Path) -> None:
    text = fh.build_note(SEGMENTS, _job(tmp_path))
    assert text.startswith("---\n")
    head, body = text[4:].split("\n---\n", 1)
    assert 'title: "My talk"' in head
    assert 'language: "en"' in head
    assert 'model: "large-v3"' in head
    assert "duration: 00:01:10" in head
    assert "date: 2026-" in head
    assert 'source: "talk.mp4"' in head
    assert "**00:00:00** Hello there." in body
    assert "**00:01:05** _Ann:_ Second line." in body


def test_note_links_a_web_source(tmp_path: Path) -> None:
    url = "https://example.com/watch?v=abc"
    text = fh.build_note(SEGMENTS, _job(tmp_path, source=url))
    assert f'source: "{url}"' in text
    assert f"[{url}]({url})" in text


def test_note_front_matter_survives_hostile_title(tmp_path: Path) -> None:
    text = fh.build_note(SEGMENTS, _job(tmp_path, title='x"\n---\ninjected: 1'))
    head = text.split("\n---\n", 1)[0]
    keys = {"---", "title", "source", "date", "language", "model", "duration", "tags"}
    assert {ln.split(":", 1)[0] for ln in head.splitlines()} <= keys
    assert text.count("\n---\n") == 1


def test_write_note_creates_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    path = fh.write_obsidian_note(str(vault), _job(tmp_path), SEGMENTS)
    assert path == str(vault / "My talk.md")
    assert "Hello there." in Path(path).read_text(encoding="utf-8")


def test_write_note_never_overwrites(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    mine = vault / "My talk.md"
    mine.write_text("my own edits", encoding="utf-8")
    path = fh.write_obsidian_note(str(vault), _job(tmp_path), SEGMENTS)
    assert path == str(vault / "My talk (1).md")
    assert mine.read_text(encoding="utf-8") == "my own edits"
    again = fh.write_obsidian_note(str(vault), _job(tmp_path), SEGMENTS)
    assert again == str(vault / "My talk (2).md")


def test_write_note_missing_vault_is_not_created(tmp_path: Path) -> None:
    vault = tmp_path / "typo"
    assert fh.write_obsidian_note(str(vault), _job(tmp_path), SEGMENTS) is None
    assert not vault.exists()


def test_write_note_uses_safe_name(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    path = fh.write_obsidian_note(str(vault), _job(tmp_path, title="CON"), SEGMENTS)
    assert path == str(vault / "_CON.md")


# --- webhook rules -----------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://example.com/h", True),
    ("http://localhost:5678/h", True),
    ("http://127.0.0.1/h", True),
    ("http://[::1]:8080/h", True),
    ("http://example.com/h", False),
    ("http://192.168.1.5/h", False),
    ("ftp://example.com/h", False),
    ("file:///etc/passwd", False),
    ("", False), ("not a url", False), ("https:///nohost", False),
])
def test_webhook_url_allowed(url: str, ok: bool) -> None:
    assert fh.webhook_url_allowed(url) is ok


def test_header_name_matches_the_server() -> None:
    assert fh.WEBHOOK_HEADER == DEFAULT_WEBHOOK_HEADER


def test_webhook_posts_small_json_without_text(tmp_path: Path, receiver) -> None:
    r = receiver()
    assert fh.send_webhook(r.url, _job(tmp_path), secret="", include_text=False,
                           segments=SEGMENTS) is True
    (req,) = r.requests
    body = req["body"]
    assert body["job_id"] == "h7" and body["title"] == "My talk"
    assert body["status"] == "finished" and body["language"] == "en"
    assert body["duration_seconds"] == 70.0
    assert body["outputs"] == [str(tmp_path / "talk.srt")]
    assert "transcript" not in body
    assert "Hello there" not in json.dumps(body)
    assert fh.WEBHOOK_HEADER not in req["headers"]


def test_webhook_includes_text_only_when_asked(tmp_path: Path, receiver) -> None:
    r = receiver()
    fh.send_webhook(r.url, _job(tmp_path), secret="", include_text=True,
                    segments=SEGMENTS)
    assert "Hello there." in r.requests[0]["body"]["transcript"]


def test_webhook_sends_secret_header(tmp_path: Path, receiver) -> None:
    r = receiver()
    fh.send_webhook(r.url, _job(tmp_path), secret=SECRET, include_text=False,
                    segments=[])
    assert r.requests[0]["headers"][fh.WEBHOOK_HEADER] == SECRET


def test_webhook_refuses_a_bad_secret(tmp_path: Path, receiver) -> None:
    r = receiver()
    ok = fh.send_webhook(r.url, _job(tmp_path), secret="bad\r\nX: y",
                         include_text=False, segments=[])
    assert ok is False and r.requests == []


def test_webhook_retries_once(tmp_path: Path, receiver) -> None:
    r = receiver([500, 200])
    sleeps: list[float] = []
    ok = fh.send_webhook(r.url, _job(tmp_path), secret="", include_text=False,
                         segments=[], sleep=sleeps.append)
    assert ok is True and len(r.requests) == 2 and len(sleeps) == 1


def test_webhook_gives_up_after_one_retry(tmp_path: Path, receiver) -> None:
    r = receiver([500])
    ok = fh.send_webhook(r.url, _job(tmp_path), secret="", include_text=False,
                         segments=[], sleep=lambda s: None)
    assert ok is False and len(r.requests) == 2


def test_webhook_refuses_plain_http_to_other_hosts(tmp_path: Path) -> None:
    calls: list[str] = []
    ok = fh.send_webhook("http://example.com/h", _job(tmp_path), secret="",
                         include_text=False, segments=[],
                         opener=lambda *a, **k: calls.append("x"))
    assert ok is False and calls == []


# --- deliver: the entry point ------------------------------------------------

def _config(tmp_path: Path, url: str = "", **kw: Any) -> dict[str, Any]:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    cfg: dict[str, Any] = {"obsidian_vault_dir": str(vault),
                           "finish_webhook_url": url,
                           "finish_webhook_secret": "",
                           "finish_webhook_include_text": False}
    cfg.update(kw)
    return cfg


def _write_json(tmp_path: Path) -> list[str]:
    p = tmp_path / "talk.json"
    p.write_text(json.dumps(SEGMENTS), encoding="utf-8")
    return [str(tmp_path / "talk.srt"), str(p)]


def test_deliver_does_both(tmp_path: Path, receiver) -> None:
    r = receiver()
    job = _job(tmp_path, output_paths=_write_json(tmp_path))
    fh.deliver(_config(tmp_path, r.url), job)
    assert (tmp_path / "vault" / "My talk.md").is_file()
    assert len(r.requests) == 1


def test_deliver_does_nothing_when_unset(tmp_path: Path) -> None:
    fh.deliver({"obsidian_vault_dir": "", "finish_webhook_url": ""},
               _job(tmp_path, output_paths=_write_json(tmp_path)))
    assert not (tmp_path / "vault").exists()


def test_deliver_skips_unfinished_jobs(tmp_path: Path, receiver) -> None:
    r = receiver()
    job = _job(tmp_path, status="error", output_paths=_write_json(tmp_path))
    fh.deliver(_config(tmp_path, r.url), job)
    assert r.requests == [] and not list((tmp_path / "vault").iterdir())


def test_offline_blocks_the_webhook_but_not_the_note(
        tmp_path: Path, receiver, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offline, "is_offline", lambda config=None: True)
    r = receiver()
    fh.deliver(_config(tmp_path, r.url), _job(tmp_path, output_paths=_write_json(tmp_path)))
    assert r.requests == []
    assert (tmp_path / "vault" / "My talk.md").is_file()


def test_webhook_failure_never_breaks_the_note_or_raises(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> bool:
        raise RuntimeError("receiver exploded")
    monkeypatch.setattr(fh, "send_webhook", boom)
    fh.deliver(_config(tmp_path, "https://example.com/h"),
               _job(tmp_path, output_paths=_write_json(tmp_path)))
    assert (tmp_path / "vault" / "My talk.md").is_file()


def test_note_failure_never_breaks_the_webhook(
        tmp_path: Path, receiver, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> str:
        raise OSError("disk full")
    monkeypatch.setattr(fh, "write_obsidian_note", boom)
    r = receiver()
    fh.deliver(_config(tmp_path, r.url), _job(tmp_path, output_paths=_write_json(tmp_path)))
    assert len(r.requests) == 1


def test_deliver_reads_segments_from_the_srt_when_no_json(
        tmp_path: Path) -> None:
    srt = tmp_path / "talk.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nFrom srt.\n", encoding="utf-8")
    fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=[str(srt)]))
    assert "From srt." in (tmp_path / "vault" / "My talk.md").read_text(encoding="utf-8")


def test_deliver_async_runs_on_a_daemon_thread(tmp_path: Path) -> None:
    t = fh.deliver_async(_config(tmp_path), _job(tmp_path, output_paths=_write_json(tmp_path)))
    assert t is not None and t.daemon
    t.join(10)
    assert (tmp_path / "vault" / "My talk.md").is_file()


# --- settings and docs -------------------------------------------------------

KEYS = ("obsidian_vault_dir", "finish_webhook_url", "finish_webhook_secret",
        "finish_webhook_include_text")


def test_keys_have_defaults_and_stay_local() -> None:
    for k in KEYS:
        assert k in DEFAULT_CONFIG, k
        assert k in LOCAL_ONLY_KEYS, k
    assert DEFAULT_CONFIG["obsidian_vault_dir"] == ""
    assert DEFAULT_CONFIG["finish_webhook_url"] == ""
    assert DEFAULT_CONFIG["finish_webhook_include_text"] is False


def test_keys_are_not_project_overridable() -> None:
    from core.config import PROJECT_ALLOWED_KEYS
    assert not set(KEYS) & set(PROJECT_ALLOWED_KEYS)


def test_docs_list_the_keys_and_the_network_row() -> None:
    md = (ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    for k in KEYS:
        assert f"| `{k}` |" in md, k
    net = md.split("## Network use", 1)[1]
    assert "Finish webhook" in net
