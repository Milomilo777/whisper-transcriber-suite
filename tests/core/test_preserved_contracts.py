"""Contract repros for changes deliberately refused by the review brief."""
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from app.services.download_service import build_download_command
from app.services.format_service import looks_like_link
from core.backends.base import is_transient_error
from core.history import HistoryDB
from core.integrations.otranscribe import _segments_to_otr_string, fmt_otr_time
from core.server import httpd
from core.server.auth_throttle import AuthThrottle
from tests.core.test_download_command import _task


class _Handler(httpd.JobRequestHandler):
    """Drive the actual GET/POST/auth methods with byte streams, no socket."""
    def __init__(self, method, path, throttle, password="bad", token="secret"):
        self.command, self.path = method, path
        self.headers = {"Authorization": "Bearer " + password, "Content-Length": "2"}
        self.client_address = ("127.0.0.1", 0)
        self.rfile, self.wfile = io.BytesIO(b"{}"), io.BytesIO()
        self.connection = SimpleNamespace(settimeout=lambda seconds: None)
        self.close_connection = False
        self.response_headers = {}
        self.status = None
        self.service = SimpleNamespace(token=token, auth_throttle=throttle,
            session_key=b"k" * 32, ssl_context=None, manager=SimpleNamespace(),
            max_upload_bytes=1024)

    @property
    def _srv(self):
        return self.service

    def send_response(self, status, message=None):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass

    def dispatch(self):
        if self.command == "GET":
            self.do_GET()
        else:
            self.do_POST()
        return self.status, json.loads(self.wfile.getvalue())


@pytest.mark.parametrize("method,path", [("GET", "/api/health"), ("GET", "/v1/models"),
    ("POST", "/api/jobs"), ("POST", "/v1/audio/transcriptions")])
def test_tripping_attempt_is_401_next_attempt_is_429(method, path, monkeypatch):
    compared = []
    token_ok = httpd.token_ok

    def count(*args):
        compared.append(1)
        return token_ok(*args)

    monkeypatch.setattr(httpd, "token_ok", count)
    clock = [1000.0]
    throttle = AuthThrottle(free_attempts=0, base_delay=15, clock=lambda: clock[0])
    tripping = _Handler(method, path, throttle)
    assert tripping.dispatch()[0] == 401
    assert tripping._auth_wait == 0 and len(compared) == 1
    locked = _Handler(method, path, throttle)
    status, body = locked.dispatch()
    assert status == 429 and len(compared) == 1
    assert int(locked.response_headers["Retry-After"]) == throttle.peek("127.0.0.1")
    if path == "/v1/audio/transcriptions":
        assert body["error"]["code"] == "rate_limit_exceeded"
        assert json.loads(tripping.wfile.getvalue())["error"]["code"] == "invalid_api_key"
    if method == "POST":
        assert tripping.rfile.tell() == locked.rfile.tell() == 2
        assert tripping.close_connection and locked.close_connection
    clock[0] += 100
    correct = _Handler("GET", "/api/health", throttle, password="secret")
    assert correct.dispatch()[0] == 200
    assert throttle.peek("127.0.0.1") == 0


def test_retry_policy_does_not_repeat_a_bad_password_even_with_wait_header():
    for status, expected in [(401, False), (429, True)]:
        error = HTTPError("http://local.invalid", status, "error", {"Retry-After": "15"}, None)
        assert is_transient_error(error) is expected


@pytest.mark.parametrize("options", [None, {}])
def test_plain_run_keeps_canonical_empty_storage(tmp_path, options):
    db = HistoryDB(tmp_path / "history.db")
    try:
        row_id = db.insert_transcription("recording.wav", run_options=options)
        raw = db._conn.execute("SELECT run_options FROM transcriptions WHERE id=?", (row_id,)).fetchone()[0]
        assert raw == ""
        assert db.list_transcriptions()[0]["run_options"] == ""
        # The proposed spelling creates a second raw representation, while
        # the tolerant reader changes its public value's type as well.
        db._conn.execute("UPDATE transcriptions SET run_options='{}' WHERE id=?", (row_id,))
        db._conn.commit()
        assert db.list_transcriptions()[0]["run_options"] == {}
    finally:
        db.close()


@pytest.mark.parametrize("seconds,label,rounded", [(59.9, "0:59", "1:00"),
    (3599.9, "59:59", "1:00:00"), (1.5, "0:01", "0:02"), (2.5, "0:02", "0:02")])
def test_display_floors_while_click_target_keeps_fraction(seconds, label, rounded):
    assert fmt_otr_time(seconds) == label
    text = json.loads(_segments_to_otr_string([(seconds, seconds + 1, "spoken")]))["text"]
    assert f'data-timestamp="{seconds:.3f}"' in text
    assert f">{label}</span>" in text
    assert fmt_otr_time(round(seconds)) == rounded


@pytest.mark.parametrize("link", ["ytsearch:spoken words", "abcdefghijk", "youtu.be/abcdefghijk",
    "www.example.com/video", "HTTPS://example.com/video"])
def test_supported_links_are_not_limited_to_http_prefix(link):
    assert looks_like_link(link)
    command = build_download_command(_task(url=link), yt_dlp_path="yt-dlp", bin_path="")
    assert command[-2:] == ["--", link]
