"""Mixed-language audio over the web / LAN page: the optional second language.

The page (and a phone that opened it through the QR code) sends ``language2``
beside ``language``. The handler validates the pair and the job's task carries
it as ``task.languages``, the attribute the engine reads. Loopback sockets with
ephemeral ports only; the transcriber is a fake that records the task.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.server import httpd
from core.server.httpd import parse_second_language
from tests.core.test_server_security import _RunningServer, _request, _wait_terminal

_BOUND = "BOUND"
_HEADERS = {"Content-Type": f"multipart/form-data; boundary={_BOUND}"}


def _multipart_with_fields(fields: dict[str, str], filename: str = "class.wav",
                           payload: bytes = b"abc") -> bytes:
    """The browser's shape: the file part first, the text fields after it."""
    body = (
        f"--{_BOUND}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + payload + b"\r\n"
    for name, value in fields.items():
        body += (
            f"--{_BOUND}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode("utf-8")
    return body + f"--{_BOUND}--\r\n".encode()


class _Recorder:
    """A fake transcribe that writes the outputs and keeps what the task said."""

    def __init__(self) -> None:
        self.seen: list[tuple[object, object]] = []

    def __call__(self, task, progress_cb=None, log_cb=None, language_cb=None):
        self.seen.append((task.language, task.languages))
        base, _ = os.path.splitext(task.file_path)
        written = []
        for fmt in task.output_formats:
            path = f"{base}.{fmt}"
            Path(path).write_text(f"dummy {fmt}", encoding="utf-8")
            written.append(path)
        task.output_paths = written


@pytest.fixture
def faster_whisper_engine(monkeypatch):
    monkeypatch.setattr(httpd, "_server_engine_is_faster_whisper", lambda: True)


# --- the pure validator ---------------------------------------------------------

@pytest.mark.usefixtures("faster_whisper_engine")
@pytest.mark.parametrize("raw", ["", "   ", None, 7])
def test_no_second_language_is_a_one_language_job(raw):
    assert parse_second_language(raw, "zh") == ("", None)


@pytest.mark.usefixtures("faster_whisper_engine")
def test_a_valid_pair_returns_the_second_code():
    assert parse_second_language("en", "zh") == ("en", None)
    assert parse_second_language("EN-us", "zh") == ("en", None)


@pytest.mark.usefixtures("faster_whisper_engine")
@pytest.mark.parametrize(
    ("raw", "language", "needle"),
    [
        ("klingon", "zh", "Unknown second language"),
        ("en", "", "first language"),
        ("zh", "zh", "two different languages"),
    ],
)
def test_a_pair_that_cannot_work_is_refused_with_a_reason(raw, language, needle):
    code, problem = parse_second_language(raw, language)
    assert code == ""
    assert problem is not None and needle in problem


def test_another_engine_refuses_the_pair(monkeypatch):
    monkeypatch.setattr(httpd, "_server_engine_is_faster_whisper", lambda: False)
    code, problem = parse_second_language("en", "zh")
    assert code == ""
    assert problem is not None and "faster-whisper" in problem


def test_the_options_page_says_whether_the_tick_works(tmp_path, monkeypatch):
    for available in (True, False):
        monkeypatch.setattr(httpd, "_server_engine_is_faster_whisper", lambda a=available: a)
        with _RunningServer(tmp_path) as srv:
            status, raw = _request(srv, "GET", "/api/options")
        assert status == 200
        assert json.loads(raw)["mixed_language_available"] is available


# --- end to end through the HTTP handler ------------------------------------------

@pytest.mark.usefixtures("faster_whisper_engine")
def test_an_upload_with_two_languages_reaches_the_engine_as_a_pair(tmp_path):
    rec = _Recorder()
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs",
            _multipart_with_fields({"formats": "srt", "language": "zh", "language2": "en"}),
            _HEADERS)
        assert status == 202, raw
        job = _wait_terminal(srv.manager, json.loads(raw)["job_id"])
    assert job.status == "finished", job.error
    assert rec.seen == [("zh", ("zh", "en"))]


@pytest.mark.usefixtures("faster_whisper_engine")
def test_an_upload_without_a_second_language_stays_one_language(tmp_path):
    rec = _Recorder()
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs",
            _multipart_with_fields({"formats": "srt", "language": "fa"}), _HEADERS)
        assert status == 202, raw
        _wait_terminal(srv.manager, json.loads(raw)["job_id"])
    assert rec.seen == [("fa", None)]


@pytest.mark.usefixtures("faster_whisper_engine")
def test_an_upload_with_auto_and_a_second_language_is_refused(tmp_path):
    rec = _Recorder()
    with _RunningServer(tmp_path, transcribe_fn=rec) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs",
            _multipart_with_fields({"formats": "srt", "language": "", "language2": "en"}),
            _HEADERS)
        assert status == 400, raw
        assert "first language" in json.loads(raw)["error"]
        assert srv.manager.list() == []
    assert rec.seen == []


@pytest.mark.usefixtures("faster_whisper_engine")
def test_a_link_job_with_a_bad_pair_is_refused_before_it_is_queued(tmp_path):
    with _RunningServer(tmp_path, download_fn=lambda u, d: "") as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs",
            json.dumps({"url": "https://example.com/a.mp3", "language": "en",
                        "language2": "en"}).encode(),
            {"Content-Type": "application/json"})
        assert status == 400, raw
        assert "two different languages" in json.loads(raw)["error"]
        assert srv.manager.list() == []


# --- the page itself ----------------------------------------------------------------

def test_the_page_offers_the_tick_and_sends_the_second_language():
    page = (Path(httpd._STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    assert 'id="mixed"' in page and 'id="lang2"' in page
    assert 'fd.append("language2", lang2)' in page
    assert "payload.language2 = lang2" in page
