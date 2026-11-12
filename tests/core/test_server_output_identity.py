"""An input stem must not change which transcript format an API serves."""
import http.client
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import pytest

from core import transcriber
from core.config import DEFAULT_CONFIG
from core.server.jobs import Job, JobManager
from core.task import TranscriptionTask
from tests.core.test_alt_backend_clip import _FakeAltBackend
from tests.core.test_cuda_decode_recovery import Engine, decode, segment
from tests.core.test_server_http_control import _RunningServer, _submit_upload, _wait_finished


_REAL_WRITE_OUTPUTS = transcriber._write_outputs


@pytest.mark.parametrize("formats", [
    ["txt", "express_scribe"], ["express_scribe", "txt"], ["txt"], ["express_scribe"],
])
@pytest.mark.parametrize("stem", ["meeting", "meeting.express_scribe"])
@pytest.mark.parametrize("template", ["{base}.{ext}", "{base}.express_scribe.{ext}"])
@pytest.mark.parametrize("indexed", [False, True])
def test_filename_suffix_does_not_swap_text_downloads(
    tmp_path, monkeypatch, formats, stem, template, indexed,
):
    media = tmp_path / f"{stem}.wav"
    with wave.open(str(media), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000)
    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": template,
    })
    if indexed:
        # A prior completed run forces the writer's shared collision index.
        transcriber._write_outputs(
            str(media.with_suffix("")), [{"start": 0, "end": 1, "text": "Earlier"}],
            str(media), formats=formats,
        )
    written = transcriber._write_outputs(
        str(media.with_suffix("")), [{"start": 0, "end": 1, "text": "Hello"}],
        str(media), formats=formats,
    )
    job = Job(job_id="test", kind="upload", formats=formats,
              media_path=str(media), work_dir=str(tmp_path))
    manager = object.__new__(JobManager)
    job.outputs = manager._collect_outputs(job, SimpleNamespace(output_paths=written))
    manager._lock = threading.RLock()
    manager._jobs = {job.job_id: job}
    assert {key for key, _path in job.outputs} == set(formats)
    expected = {"txt": "Hello\n", "express_scribe": "[00:00:00] Hello\n"}
    for fmt in formats:
        result = manager.output_path(job.job_id, fmt)
        assert result is not None
        assert Path(result).read_text(encoding="utf-8-sig") == expected[fmt]


@pytest.mark.parametrize("formats", [["txt", "express_scribe"], ["express_scribe", "txt"]])
@pytest.mark.parametrize("failed_format", ["txt", "express_scribe"])
def test_one_failed_writer_does_not_relabel_the_surviving_format(
    tmp_path, monkeypatch, formats, failed_format,
):
    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": "{base}.{ext}",
    })
    real_get_writer = transcriber.get_writer

    def get_writer(fmt):
        if fmt == failed_format:
            raise OSError("simulated writer failure")
        return real_get_writer(fmt)

    monkeypatch.setattr(transcriber, "get_writer", get_writer)
    media = tmp_path / "meeting.express_scribe.wav"
    media.write_bytes(b"synthetic input identity")
    written = transcriber._write_outputs(
        str(media.with_suffix("")), [{"start": 0, "end": 1, "text": "Hello"}],
        str(media), formats=formats,
    )
    job = Job(job_id="test", kind="upload", formats=formats,
              media_path=str(media), work_dir=str(tmp_path))
    manager = object.__new__(JobManager)
    outputs = manager._collect_outputs(job, SimpleNamespace(output_paths=written))
    assert {key for key, _path in outputs} == set(formats) - {failed_format}


@pytest.mark.parametrize("stem", ["meeting", "meeting.express_scribe"])
@pytest.mark.parametrize("failed_format", [None, "express_scribe"])
def test_http_upload_and_download_preserve_output_identity(
    tmp_path, monkeypatch, stem, failed_format,
):
    """Exercise upload sanitizing, job settlement, archiving and downloaded bytes."""
    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": "{base}.{ext}",
    })
    real_get_writer = transcriber.get_writer

    def get_writer(fmt):
        if fmt == failed_format:
            raise OSError("simulated writer failure")
        return real_get_writer(fmt)

    monkeypatch.setattr(transcriber, "get_writer", get_writer)

    def render(task, *_callbacks):
        # Only ASR is substituted: the real writers and server pipeline run.
        task.output_paths = transcriber._write_outputs(
            str(Path(task.file_path).with_suffix("")),
            [{"start": 0, "end": 1, "text": "Hello"}],
            task.file_path, formats=task.output_formats,
        )

    payload = io.BytesIO()
    with wave.open(payload, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000)
    with _RunningServer(tmp_path, transcribe_fn=render) as server:
        status, submitted = _submit_upload(
            server, {"formats": "txt,express_scribe"},
            filename=f"{stem}.wav", file_bytes=payload.getvalue(),
        )
        assert status == 202
        job_id = submitted["job_id"]
        finished = _wait_finished(server, job_id, timeout=5)
        assert finished is not None and finished["status"] == "finished"
        expected = {"txt": "Hello\n", "express_scribe": "[00:00:00] Hello\n"}
        expected.pop(failed_format, None)
        assert {entry["fmt"] for entry in finished["outputs"]} == set(expected)
        for fmt, text in expected.items():
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            try:
                connection.request("GET", f"/api/jobs/{job_id}/result?fmt={fmt}")
                response = connection.getresponse()
                assert response.status == 200
                assert response.read().decode("utf-8-sig") == text
            finally:
                connection.close()
        if failed_format is not None:
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            try:
                connection.request("GET", f"/api/jobs/{job_id}/result?fmt={failed_format}")
                response = connection.getresponse()
                assert response.status == 404
                response.read()
            finally:
                connection.close()


@pytest.mark.parametrize("route", ["fresh", "alternate", "resumed"])
def test_task_routes_preserve_format_metadata_and_wire_list(decode, monkeypatch, route):
    audio, _written, _slices = decode
    monkeypatch.setattr(transcriber, "_write_outputs", _REAL_WRITE_OUTPUTS)
    monkeypatch.setattr(transcriber, "_task_output_base", lambda _: str(Path(audio).with_suffix("")))
    transcriber.config["output_filename_template"] = "{base}.{ext}"
    task = TranscriptionTask(audio)
    task.output_formats = ["txt", "express_scribe"]
    if route == "fresh":
        monkeypatch.setattr(transcriber, "MODEL", Engine([[segment(0, 1, "Hello")]]))
        transcriber.transcribe(task)
    elif route == "alternate":
        transcriber._transcribe_via_alt_backend(
            "whisper_cpp", task, None, None, None, backend=_FakeAltBackend(),
        )
    else:
        transcriber._write_resumed_outputs(
            task, [{"start": 0, "end": 1, "text": "Hello"}], "en", 0, None, None,
        )
    assert isinstance(task.output_paths, list)
    identities = getattr(task.output_paths, "by_format", {})
    assert set(identities) == {"txt", "express_scribe"}
    assert set(identities.values()) == set(task.output_paths)
    assert json.loads(json.dumps(task.output_paths)) == list(task.output_paths)


@pytest.mark.parametrize("damage", ["outside_list", "vanished", "empty", "empty_list", "unrequested"])
def test_format_metadata_cannot_collect_unreported_or_stale_files(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": "{base}.{ext}",
    })
    media = tmp_path / "input.wav"
    written = transcriber._write_outputs(
        str(media.with_suffix("")), [{"start": 0, "end": 1, "text": "Hello"}],
        str(media), formats=["txt"],
    )
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("unrelated", encoding="utf-8")
    identities = written.by_format
    if damage == "outside_list":
        identities["txt"] = str(unrelated)
    elif damage == "vanished":
        Path(written[0]).unlink()
    elif damage == "empty":
        identities.clear()
    elif damage == "empty_list":
        written.clear()
    else:
        identities["unexpected"] = str(unrelated)
    job = Job(job_id="test", kind="upload", formats=["txt"],
              media_path=str(media), work_dir=str(tmp_path))
    manager = object.__new__(JobManager)
    out = manager._collect_outputs(job, SimpleNamespace(output_paths=written))
    assert out == ([("txt", written[0])] if damage == "unrequested" else [])


def test_chapter_sidecar_is_not_the_json_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": "{base}.{ext}",
    })
    media = tmp_path / "input.chapters.wav"
    written = transcriber._write_outputs(
        str(media.with_suffix("")), [{"start": 0, "end": 1, "text": "Hello"}],
        str(media), formats=["json"], chapters=[{"start": 0, "end": 1, "title": "Chapter"}],
    )
    assert len(written) == 2
    job = Job(job_id="test", kind="upload", formats=["json"],
              media_path=str(media), work_dir=str(tmp_path))
    manager = object.__new__(JobManager)
    out = manager._collect_outputs(job, SimpleNamespace(output_paths=written))
    assert len(out) == 1 and out[0][0] == "json"
    assert json.loads(Path(out[0][1]).read_text(encoding="utf-8"))[0]["text"] == "Hello"
