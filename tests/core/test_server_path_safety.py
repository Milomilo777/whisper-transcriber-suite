"""Hostile file names and ids against the job server's file handling.

CodeQL's ``py/path-injection`` marks the two ``open()`` calls that copy a
streamed upload (``JobRequestHandler._extract_upload_from_file`` and
``_copy_range``). The source side is a ``tempfile.mkstemp`` path the server
chose; the destination is ``os.path.join(job.work_dir, _safe_filename(name))``.
These tests pin the guards with concrete hostile input, over real HTTP:

* an upload name can never place the media outside its own job folder, and
  nothing else is created outside the jobs root;
* ``fmt`` and the job id of a download request are lookup keys, never part of
  a path, so no file outside the job's recorded outputs can be read.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from pathlib import Path

import pytest

from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager

_SENTINEL_TEXT = "sentinel-file-content-A"
_BACKSLASH = chr(92)


def _transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    written = []
    for fmt in task.output_formats:
        path = f"{base}.{fmt}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
        written.append(path)
    task.output_paths = written
    if progress_cb:
        progress_cb(100)


class _Server:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs_root = root / "server_jobs"

    def __enter__(self):
        self.manager = JobManager(
            _transcribe, jobs_root=str(self.jobs_root), record_history=False)
        self.manager.start()
        self.server = JobHTTPServer(("127.0.0.1", 0), self.manager)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def wait_terminal(self, job_id, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.manager.get(job_id)
            if job is not None and job.status in (
                    "finished", "error", "cancelled"):
                return job
            time.sleep(0.05)
        raise AssertionError(f"job {job_id} did not finish")


def _multipart(filename: str, payload: bytes) -> bytes:
    return (
        '--BOUND\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'
    ).encode("utf-8") + payload + b"\r\n--BOUND--\r\n"


_HOSTILE_NAMES = [
    "../../evil.wav",
    ".." + _BACKSLASH + ".." + _BACKSLASH + "evil.wav",
    "/etc/passwd",
    "C:" + _BACKSLASH + "Windows" + _BACKSLASH + "evil.wav",
    "C:evil.wav",
    _BACKSLASH * 2 + "server" + _BACKSLASH + "share" + _BACKSLASH + "evil.wav",
    "evil.wav:stream",
    "evil.wav::$DATA",
    "..",
    "...",
    ". .",
    "%2e%2e%2fevil.wav",
    "..%5cevil.wav",
    "CON",
    "nul.wav",
    "aux.",
    "COM1.wav",
    "LPT9",
    "evil.wav. . ",
    "．．／evil.wav",   # fullwidth full stops and solidus
    "..∕evil.wav",             # division slash
    "‮txt.wav",                # right-to-left override
    "~1/evil.wav",
]


def _files_under(root: Path) -> set[Path]:
    return {p.resolve() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "name", _HOSTILE_NAMES,
    ids=lambda n: n.encode("ascii", "backslashreplace").decode()[:30])
def test_upload_name_cannot_leave_the_job_folder(tmp_path, name):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text(_SENTINEL_TEXT, encoding="utf-8")
    with _Server(tmp_path) as srv:
        status, raw = srv.request(
            "POST", "/api/jobs", _multipart(name, b"RIFF" * 8),
            {"Content-Type": "multipart/form-data; boundary=BOUND"})
        assert status == 202, raw
        job = srv.wait_terminal(json.loads(raw)["job_id"])
        assert job.status == "finished", job.error

        job_dir = (srv.jobs_root / job.job_id).resolve()
        media = Path(job.media_path).resolve()
        assert media.parent == job_dir, (name, media)
        base = media.name
        assert base and not any(c in base for c in '/\\:*?"<>|')
        assert base not in (".", "..") and base == base.rstrip(". ")
        assert base.split(".", 1)[0].rstrip(" ").upper() not in {
            "CON", "PRN", "AUX", "NUL"}

        # Nothing was written anywhere but the jobs root and this job's own
        # copy of its results; the sentinel (a stand-in for any file a
        # traversal could reach) is untouched.
        allowed_dirs = (srv.jobs_root.resolve(),
                        (tmp_path / "server_outputs" / job.job_id[:12]).resolve())
        stray = {p for p in _files_under(tmp_path)
                 if p != sentinel.resolve()
                 and not any(d in p.parents for d in allowed_dirs)}
        assert not stray, stray
        assert sentinel.read_text(encoding="utf-8") == _SENTINEL_TEXT


def test_download_fmt_and_job_id_are_lookup_keys_not_paths(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text(_SENTINEL_TEXT, encoding="utf-8")
    with _Server(tmp_path) as srv:
        status, raw = srv.request(
            "POST", "/api/jobs", _multipart("clip.wav", b"RIFF" * 8),
            {"Content-Type": "multipart/form-data; boundary=BOUND"})
        assert status == 202, raw
        job = srv.wait_terminal(json.loads(raw)["job_id"])
        assert job.status == "finished", job.error

        hostile_fmts = [
            "../../secret.txt", "..%2F..%2Fsecret.txt", "%2e%2e/secret.txt",
            str(secret).replace(_BACKSLASH, "/"), str(secret).replace("/", "%2F"),
            "secret.txt", "txt", "..", "x%00", "srt:stream",
        ]
        for fmt in hostile_fmts:
            status, raw = srv.request(
                "GET", f"/api/jobs/{job.job_id}/result?fmt={fmt}")
            assert status in (400, 404), (fmt, status)
            assert _SENTINEL_TEXT.encode() not in raw, fmt

        hostile_ids = [
            "..", "%2e%2e", "..%2f..%2fsecret.txt", "secret.txt",
            "..%5c..%5csecret.txt", job.job_id + "%2f..%2f..%2fsecret.txt",
        ]
        for jid in hostile_ids:
            for suffix in ("", "/result?fmt=srt", "/outputs"):
                status, raw = srv.request("GET", f"/api/jobs/{jid}{suffix}")
                assert status in (400, 404), (jid, suffix, status)
                assert _SENTINEL_TEXT.encode() not in raw, (jid, suffix)

        # Unknown paths never map onto the file system.
        for path in ("/../secret.txt", "/static/../../secret.txt",
                     "/%2e%2e/secret.txt", "/api/../secret.txt"):
            status, raw = srv.request("GET", path)
            assert _SENTINEL_TEXT.encode() not in raw, path

        # The legitimate download still works.
        status, raw = srv.request(
            "GET", f"/api/jobs/{job.job_id}/result?fmt=srt")
        assert status == 200 and raw == b"dummy srt"
