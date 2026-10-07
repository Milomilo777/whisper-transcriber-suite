"""Kokoro ready-made voices (core/tts_kokoro.py) -- no model needed."""
from __future__ import annotations

import pytest

from core import tts_kokoro as k


def test_voice_table_matches_the_model_order():
    # sherpa-onnx kokoro-multi-lang-v1_0: ids 0..52, em_santa appended at 53.
    assert len(k.VOICES) == 54
    assert [v.sid for v in k.VOICES] == list(range(54))
    assert k.voice_by_key("af_heart").sid == 3
    assert k.voice_by_key("am_adam").sid == 11
    assert k.voice_by_key("zm_yunyang").sid == 52
    assert k.voice_by_key("em_santa").sid == 53


def test_voice_labels_and_languages():
    heart = k.voice_by_key("af_heart")
    assert heart.label == "Heart — US English, female"
    assert k.voice_by_key("bm_george").lang_code == "en-gb"
    assert k.voice_by_key("jf_alpha").language == "Japanese"
    assert k.voice_by_key("hm_psi").gender == "male"
    assert len({v.label for v in k.VOICES}) == len(k.VOICES)


def test_unknown_voice_falls_back_to_default():
    assert k.voice_by_key("nope").key == k.DEFAULT_VOICE


def test_is_downloaded_false_for_empty_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "model_dir", lambda: tmp_path / "missing")
    assert k.is_downloaded() is False


def test_generate_rejects_empty_text():
    with pytest.raises(ValueError):
        k.generate("   ", "af_heart", "out.wav")


def test_generate_uses_the_shared_pass_limit(monkeypatch):
    """One call is one pass; longer texts go through core.tts_job in pieces."""
    from core import tts_plan

    monkeypatch.setattr(k, "_load", lambda _lang: pytest.fail("loaded a model"))
    with pytest.raises(ValueError, match=f"limit for one generation is {tts_plan.MAX_PASS_CHARS}"):
        k.generate("a" * (tts_plan.MAX_PASS_CHARS + 1), "af_heart", "out.wav")


def test_measure_speed_never_downloads(monkeypatch):
    monkeypatch.setattr(k, "is_downloaded", lambda: False)
    monkeypatch.setattr(k, "download", lambda **_k: pytest.fail("download started"))
    monkeypatch.setattr(k, "generate", lambda *_a, **_k: pytest.fail("generated"))
    with pytest.raises(RuntimeError, match="not downloaded"):
        k.measure_speed()


def test_measure_speed_speaks_the_fixed_text_and_removes_its_file(monkeypatch):
    import os

    from core import tts_plan

    seen = {}

    def fake_generate(text, voice, out, cancel_event=None, **_k):
        seen.update(text=text, voice=voice, out=out, cancel=cancel_event)
        with open(out, "wb") as f:
            f.write(b"RIFF")
        return k.KokoroResult(out, 10.0, 6.5)

    monkeypatch.setattr(k, "is_downloaded", lambda: True)
    monkeypatch.setattr(k, "generate", fake_generate)
    marker = object()
    result = k.measure_speed(cancel_event=marker)  # type: ignore[arg-type]
    assert (result.audio_seconds, result.elapsed_seconds) == (10.0, 6.5)
    assert seen["text"] == tts_plan.CALIBRATION_TEXT
    assert seen["voice"] == k.DEFAULT_VOICE and seen["cancel"] is marker
    assert not os.path.exists(seen["out"])


# --- C2.51b M4: a cut-off model download resumes ----------------------------


def _model_tarball() -> bytes:
    import io
    import tarfile

    import random

    noise = random.Random(7).randbytes(20000)  # does not compress: a real transfer
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in (("model.onnx", noise), ("voices.bin", b"v" * 3000)):
            info = tarfile.TarInfo(f"{k.MODEL_NAME}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _Server:
    """A fake ``requests`` module serving one archive, with Range support."""

    def __init__(self, body: bytes, *, honour_range: bool = True) -> None:
        self.body = body
        self.honour_range = honour_range
        self.requests: list[dict] = []
        self.cancel_after: int | None = None
        self.cancel_event = None

    def get(self, url, stream=False, timeout=None, headers=None):
        import types

        headers = dict(headers or {})
        self.requests.append(headers)
        start = 0
        status = 200
        resp_headers: dict[str, str] = {}
        rng = headers.get("Range")
        if rng and self.honour_range:
            start = int(rng.split("=")[1].rstrip("-"))
            if start >= len(self.body):
                status = 416
                resp_headers["content-range"] = f"bytes */{len(self.body)}"
            else:
                status = 206
        payload = self.body[start:] if status != 416 else b""
        resp_headers["content-length"] = str(len(payload))
        server = self

        def iter_content(chunk_size=1):
            sent = 0
            for i in range(0, len(payload), 1000):
                if server.cancel_after is not None and sent >= server.cancel_after:
                    server.cancel_event.set()
                yield payload[i:i + 1000]
                sent += 1000

        def raise_for_status():
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")

        resp = types.SimpleNamespace(status_code=status, headers=resp_headers,
                                     iter_content=iter_content, raise_for_status=raise_for_status)

        class _Ctx:
            def __enter__(self_inner):
                return resp

            def __exit__(self_inner, *_):
                return None

        return _Ctx()


@pytest.fixture
def kokoro_cache(monkeypatch, tmp_path):
    import sys

    from core import offline

    monkeypatch.setattr(k, "model_dir", lambda: tmp_path / "tts" / k.MODEL_NAME)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **kw: False)

    def install(server: _Server) -> None:
        monkeypatch.setitem(sys.modules, "requests", server)

    return tmp_path / "tts", install


def test_cancelled_download_keeps_the_part_and_resumes(kokoro_cache):
    import threading

    folder, install = kokoro_cache
    server = _Server(_model_tarball())
    install(server)
    cancel = threading.Event()
    server.cancel_after, server.cancel_event = 3000, cancel
    with pytest.raises(RuntimeError, match="cancelled"):
        k.download(cancel_event=cancel)
    part = folder / f"{k.MODEL_NAME}.tar.bz2.part"
    kept = part.stat().st_size
    assert 0 < kept < len(server.body)

    server.cancel_after = None
    assert k.download() == k.model_dir()
    assert server.requests[-1] == {"Range": f"bytes={kept}-"}
    assert k.is_downloaded()
    assert not part.exists()


def test_complete_part_is_unpacked_without_a_new_transfer(kokoro_cache):
    folder, install = kokoro_cache
    server = _Server(_model_tarball())
    install(server)
    folder.mkdir(parents=True)
    (folder / f"{k.MODEL_NAME}.tar.bz2.part").write_bytes(server.body)
    k.download()
    assert k.is_downloaded()
    assert len(server.requests) == 1  # answered 416 with the matching size


def test_oversized_leftover_restarts_from_zero(kokoro_cache):
    folder, install = kokoro_cache
    server = _Server(_model_tarball())
    install(server)
    folder.mkdir(parents=True)
    (folder / f"{k.MODEL_NAME}.tar.bz2.part").write_bytes(server.body + b"junk")
    k.download()
    assert k.is_downloaded()
    assert server.requests[-1] == {}


def test_server_without_range_support_restarts_cleanly(kokoro_cache):
    folder, install = kokoro_cache
    server = _Server(_model_tarball(), honour_range=False)
    install(server)
    folder.mkdir(parents=True)
    (folder / f"{k.MODEL_NAME}.tar.bz2.part").write_bytes(server.body[:500])
    k.download()
    assert k.is_downloaded()


def test_damaged_archive_is_removed(kokoro_cache):
    folder, install = kokoro_cache
    server = _Server(b"this is not a bz2 archive" * 40)
    install(server)
    with pytest.raises(RuntimeError, match="damaged"):
        k.download()
    assert not (folder / f"{k.MODEL_NAME}.tar.bz2.part").exists()
    assert not k.is_downloaded()
