"""Default model content must match its pin even without an HTTP length."""
import hashlib
import io

import pytest

from core import llm
from core.backends import whisper_cpp


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
@pytest.mark.parametrize("body", [b"partial", b"different contents"], ids=["short", "wrong-hash"])
@pytest.mark.parametrize("length", [None, "0", "actual"], ids=["missing-length", "zero-length", "known-length"])
def test_default_response_must_match_pinned_size_and_digest(tmp_path, monkeypatch, provider, body, length):
    expected = b"verified contents!"
    if len(body) != len(b"partial"):
        assert len(body) == len(expected)
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SIZE_BYTES", len(expected), raising=False)
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SHA256", hashlib.sha256(expected).hexdigest(), raising=False)
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)

    class Response(io.BytesIO):
        headers = {} if length is None else {"content-length": str(len(body)) if length == "actual" else length}

        def getheader(self, name):
            return self.headers.get(name.lower())

    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response(body))
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"previous short model")
    with pytest.raises(RuntimeError, match="(?i)(checksum|integrity|pinned|size)"):
        provider.download_default_model(dest=dest)
    assert dest.read_bytes() == b"previous short model"
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
def test_oversized_default_stream_stops_without_waiting_for_eof(tmp_path, monkeypatch, provider):
    expected = b"verified contents!"
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SIZE_BYTES", len(expected))
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SHA256", hashlib.sha256(expected).hexdigest())
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)

    class Response(io.BytesIO):
        headers = {}
        reads = 0

        def getheader(self, name):
            return None

        def read(self, count):
            self.reads += 1
            assert self.reads == 1, "An oversized default response must not keep consuming bytes"
            return expected + b"extra"

    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response())
    dest = tmp_path / "model.bin"
    with pytest.raises(RuntimeError, match="pinned size"):
        provider.download_default_model(dest=dest)
    assert not dest.exists()
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
@pytest.mark.parametrize("custom", [False, True], ids=["pinned-default", "custom-url"])
def test_matching_default_or_explicit_custom_stream_can_publish(tmp_path, monkeypatch, provider, custom):
    expected = b"verified contents!"
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SIZE_BYTES", len(expected), raising=False)
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SHA256", hashlib.sha256(expected).hexdigest(), raising=False)
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)

    class Response(io.BytesIO):
        headers = {}

        def getheader(self, name):
            return None

        def read(self, count):
            return super().read(min(count, 3))

    body = b"custom arbitrary model" if custom else expected
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response(body))
    dest = tmp_path / "model.bin"
    kwargs = {"url": "https://models.example.invalid/custom"} if custom else {}
    assert provider.download_default_model(dest=dest, **kwargs) == str(dest)
    assert dest.read_bytes() == body
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())


@pytest.mark.parametrize("provider", [whisper_cpp, llm], ids=["cpp", "gguf"])
def test_bad_default_response_preserves_a_concurrent_accepted_destination(tmp_path, monkeypatch, provider):
    expected = b"verified contents!"
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SIZE_BYTES", len(expected))
    monkeypatch.setattr(provider, "DEFAULT_MODEL_SHA256", hashlib.sha256(expected).hexdigest())
    monkeypatch.setattr(provider.offline, "require_online", lambda *args: None)
    dest = tmp_path / "model.bin"

    class Response(io.BytesIO):
        headers = {}
        published = False

        def getheader(self, name):
            return None

        def read(self, count):
            if not self.published:
                self.published = True
                with dest.open("wb") as completed:
                    completed.write(b"other accepted download")
                    completed.truncate(100_000_001)
            return super().read(count)

    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda *a, **k: Response(b"bad"))
    assert provider.download_default_model(dest=dest) == str(dest)
    assert dest.stat().st_size == 100_000_001
    with dest.open("rb") as saved:
        assert saved.read(23) == b"other accepted download"
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())
