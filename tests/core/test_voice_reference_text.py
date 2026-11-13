"""Reference preparation is offline, bounded and precedes TTS allocation."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import types
import weakref
from pathlib import Path

import pytest

from core import config, hub, voice_clone as vc


def test_forced_worker_exit_leaves_only_owned_sweepable_reference(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    global_temp = tmp_path / "global-temp"
    global_temp.mkdir()
    unrelated = global_temp / "voice_clone_ref_unrelated.wav"
    unrelated.write_bytes(b"unrelated original")
    source = tmp_path / "source.wav"
    source.write_bytes(b"reference original")
    receipt = tmp_path / "frozen.json"
    script = r'''
import json, subprocess, sys, time, types
from pathlib import Path
from core import voice_clone as vc
def render(command, **kwargs):
    Path(command[-1]).write_bytes(b"synthetic frozen PCM")
    return types.SimpleNamespace(returncode=0, stderr="")
subprocess.run = render
vc._transcribe_reference = lambda path: "reference speech"
with vc.prepare_reference([sys.argv[1]], consent_accepted=True) as prepared:
    Path(sys.argv[2]).write_text(json.dumps({"path": prepared.path}), encoding="utf-8")
    time.sleep(30)  # The parent forcibly ends this owned worker below.
'''
    env = dict(os.environ, WTS_PROFILE_DIR=str(profile), TEMP=str(global_temp), TMP=str(global_temp), TMPDIR=str(global_temp))
    child = subprocess.Popen([sys.executable, "-c", script, str(source), str(receipt)],
                             env=env, cwd=Path(__file__).resolve().parents[2],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not receipt.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert receipt.exists(), "Worker did not finish freezing its reference"
        frozen = Path(json.loads(receipt.read_text(encoding="utf-8"))["path"])
        owned_root = profile / "cache" / "voice_clone"
        assert frozen.is_relative_to(owned_root), "Forced exit leaked reference PCM in global TEMP"
        assert frozen.read_bytes() == b"synthetic frozen PCM"
        monkeypatch.setenv("WTS_PROFILE_DIR", str(profile))
        old = time.time() - 9 * 86400
        for path in [*frozen.parent.iterdir(), frozen.parent]:
            os.utime(path, (old, old))
        vc.sweep_old_session_dirs()
        assert frozen.exists(), "Sweeper removed PCM while the worker still held its lock"
    finally:
        if child.poll() is None:
            child.kill()  # Only this test's Popen child; bypass its finally.
        child.communicate(timeout=5)
    assert child.returncode != 0
    vc.sweep_old_session_dirs()
    assert not frozen.exists(), "Dead worker's aged PCM was not reclaimed by the bounded sweep"
    assert unrelated.read_bytes() == b"unrelated original"
    assert source.read_bytes() == b"reference original"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(vc, "_model_cache", {})
    monkeypatch.setattr(vc, "_reference_text_cache", {}, raising=False)
    monkeypatch.setattr(vc.synthetic_audio, "tag_wav", lambda path: None)
    monkeypatch.setattr(vc.synthetic_audio, "append_consent_record", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(
        write=lambda path, audio, rate: Path(path).write_bytes(b"output")))


def local_model(tmp_path, monkeypatch, slug="small", **overrides):
    path = hub.model_folder_for(tmp_path, f"faster-whisper-{slug}")
    path.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (path / name).write_text("{}", encoding="utf-8")
    settings = {"hub_folder": str(tmp_path), "model_path": str(path),
                "model": {"name": f"faster-whisper-{slug}"}, **overrides}
    calls = []
    monkeypatch.setattr(config, "load_config", lambda **kw: calls.append(kw) or settings)
    return path, settings, calls


def freeze(monkeypatch, tmp_path):
    seen = []

    def combine(paths, *, directory=None):
        seen.append(list(paths))
        out = Path(directory or tmp_path) / f"frozen-{len(seen)}.wav"
        out.write_bytes(b"".join(Path(p).read_bytes() for p in paths[:vc.MAX_REFERENCE_SAMPLES]))
        return str(out)

    monkeypatch.setattr(vc, "_concat_references", combine)
    return seen


def frozen_files():
    return list((config.user_cache_dir() / "voice_clone").rglob("frozen-*.wav"))


def test_preparation_releases_lock_after_ffmpeg_failure(monkeypatch, tmp_path):
    from core import tts_job

    folder = Path(vc.session_work_dir())
    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                        types.SimpleNamespace(returncode=1, stderr="synthetic ffmpeg failure"))
    with pytest.raises(RuntimeError, match="synthetic ffmpeg failure"):
        with vc.prepare_reference([str(source)], consent_accepted=True, scratch_dir=str(folder)):
            pytest.fail("ffmpeg failed")
    assert list(folder.glob("*.wav")) == []
    lock = tts_job._JobLock(folder / tts_job.LOCK_FILE)
    lock.acquire()
    lock.release()
    assert source.read_bytes() == b"original"


def test_preparation_rejects_an_unowned_scratch_directory(monkeypatch, tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("unowned scratch used"))
    with pytest.raises(ValueError, match="owned"):
        with vc.prepare_reference([str(source)], consent_accepted=True, scratch_dir=str(tmp_path)):
            pytest.fail("unowned scratch accepted")
    assert source.read_bytes() == b"original"


def fake_asr(monkeypatch, *, events=None, texts=(" reference", " speech"), multilingual=True):
    calls = []
    refs = []

    class ASR:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))
            self.model = types.SimpleNamespace(is_multilingual=multilingual)
            refs.append(weakref.ref(self))
            if events is not None:
                events.append("asr-load")

        def transcribe(self, path, **kwargs):
            audio = Path(path).read_bytes()

            def segments():
                if events is not None:
                    events.append(("asr-audio", audio))
                for text in texts:
                    yield types.SimpleNamespace(text=text)
                if events is not None:
                    events.append("segments-consumed")

            return segments(), types.SimpleNamespace(language="fa")

        def __del__(self):
            if events is not None:
                events.append("asr-release")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=ASR))
    return calls, refs


def test_exact_frozen_audio_gets_nonempty_text_before_tts(monkeypatch, tmp_path):
    model_path, _, config_calls = local_model(tmp_path, monkeypatch)
    events = []
    calls, refs = fake_asr(monkeypatch, events=events)
    seen = freeze(monkeypatch, tmp_path)
    paths = []
    for n in range(4):
        path = tmp_path / f"sample{n}.wav"
        path.write_bytes(bytes([n]))
        paths.append(str(path))

    class TTS:
        def generate(self, **kwargs):
            assert refs[0]() is None
            assert kwargs["ref_text"] == "reference speech"
            assert Path(kwargs["ref_audio"]).read_bytes() == b"\0\1\2"
            assert kwargs["text"] == "requested content"
            events.append("tts-generate")
            return [[0.0]]

    with vc.prepare_reference(paths, consent_accepted=True) as reference:
        assert reference is not None
        frozen_path = Path(reference.path)
        assert frozen_path.exists()
        vc.generate(TTS(), "requested content", paths, str(tmp_path / "out.wav"),
                    consent_accepted=True, prepared_reference=reference)
    assert not frozen_path.exists()
    assert seen == [paths[:vc.MAX_REFERENCE_SAMPLES]]
    assert calls == [(str(model_path), {"device": "cpu", "compute_type": "int8", "local_files_only": True})]
    assert config_calls == [{"fetch_online": False}]
    assert events.index("segments-consumed") < events.index("asr-release") < events.index("tts-generate")


def test_reference_cache_uses_content_and_releases_tts_before_changed_asr(monkeypatch, tmp_path):
    local_model(tmp_path, monkeypatch)
    events = []
    calls, _ = fake_asr(monkeypatch, events=events)
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"one")
    paths = [str(source)]

    class TTS:
        def __del__(self):
            events.append("tts-release")

    with vc.prepare_reference(paths, consent_accepted=True):
        pass
    vc._model_cache["cpu"] = TTS()
    with vc.prepare_reference(paths, consent_accepted=True):
        assert vc._model_cache
    assert len(calls) == 1
    source.write_bytes(b"two")  # Same path and byte length; metadata is not identity.
    with vc.prepare_reference(paths, consent_accepted=True):
        assert not vc._model_cache
    assert len(calls) == 2
    assert events.index("tts-release") < events.index("asr-load", events.index("asr-load") + 1)


@pytest.mark.parametrize("texts", [(), (" ", "\n")])
def test_no_speech_fails_and_cleans_frozen_audio(monkeypatch, tmp_path, texts):
    local_model(tmp_path, monkeypatch)
    _, refs = fake_asr(monkeypatch, texts=texts)
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"silent")
    with pytest.raises(RuntimeError, match="speech"):
        with vc.prepare_reference([str(source)], consent_accepted=True):
            pytest.fail("empty reference text was accepted")
    assert refs[0]() is None
    assert not frozen_files()


def test_no_cached_model_never_constructs_asr_or_generates(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_config", lambda **kw: {
        "hub_folder": str(tmp_path), "model": {"name": "google"}, "backend": "google"})
    calls, _ = fake_asr(monkeypatch)
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"speech")
    with pytest.raises(RuntimeError, match="already.*local|local.*multilingual"):
        with vc.prepare_reference([str(source)], consent_accepted=True):
            pytest.fail("must fail before TTS")
    assert calls == []
    assert not frozen_files()


def test_english_selected_model_uses_cached_multilingual_not_english(monkeypatch, tmp_path):
    english, settings, _ = local_model(tmp_path, monkeypatch, "tiny.en")
    small = hub.model_folder_for(tmp_path, "faster-whisper-small")
    small.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (small / name).write_text("{}", encoding="utf-8")
    calls, _ = fake_asr(monkeypatch)
    assert list(vc._local_reference_models(settings)) == [str(small)]
    assert str(english) not in list(vc._local_reference_models(settings))
    assert calls == []


@pytest.mark.parametrize("missing", ["tokenizer.json", "config.json"])
def test_weights_without_local_metadata_are_not_eligible(monkeypatch, tmp_path, missing):
    path, settings, _ = local_model(tmp_path, monkeypatch)
    (path / missing).unlink()
    assert list(vc._local_reference_models(settings)) == []


def test_custom_english_model_is_checked_after_loading_and_released(monkeypatch, tmp_path):
    _, settings, _ = local_model(tmp_path, monkeypatch, "custom")
    calls, refs = fake_asr(monkeypatch, multilingual=False)
    with pytest.raises(RuntimeError, match="multilingual"):
        vc._transcribe_reference("unused.wav")
    assert len(calls) == 1
    assert refs[0]() is None
    assert settings["model"]["name"] == "faster-whisper-custom"


def test_domain_does_not_allocate_asr_beside_supplied_tts_model(monkeypatch, tmp_path):
    calls, _ = fake_asr(monkeypatch)
    with pytest.raises(ValueError, match="prepare_reference"):
        vc.generate(object(), "hello", ["source.wav"], str(tmp_path / "out.wav"),
                    consent_accepted=True)
    assert calls == []


def test_preparation_cleans_up_when_generation_fails(monkeypatch, tmp_path):
    local_model(tmp_path, monkeypatch)
    fake_asr(monkeypatch)
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"speech")

    class Broken:
        def generate(self, **kwargs):
            raise RuntimeError("synthetic generation failure")

    with pytest.raises(RuntimeError, match="synthetic generation"):
        with vc.prepare_reference([str(source)], consent_accepted=True) as reference:
            vc.generate(Broken(), "hello", [str(source)], str(tmp_path / "out.wav"),
                        consent_accepted=True, prepared_reference=reference)
    assert not frozen_files()


@pytest.mark.parametrize("fail_first", [False, True])
def test_worker_releases_previous_model_before_changed_reference_asr(monkeypatch, tmp_path, fail_first):
    from core import voice_clone_worker as worker

    local_model(tmp_path, monkeypatch)
    events = []
    fake_asr(monkeypatch, events=events)
    freeze(monkeypatch, tmp_path)
    paths = []
    for name in ("first", "second"):
        path = tmp_path / f"{name}.wav"
        path.write_bytes(name.encode())
        paths.append(str(path))

    class TTS:
        def generate(self, **kw):
            events.append("tts-generate")
            if fail_first and events.count("tts-generate") == 1:
                raise RuntimeError("synthetic generation failure")
            return [[0.0]]

        def __del__(self):
            events.append("tts-release")

    def load(device):
        if device not in vc._model_cache:
            vc._model_cache[device] = TTS()
            events.append("tts-load")
        return vc._model_cache[device]

    monkeypatch.setattr(vc, "load_model", load)
    monkeypatch.setattr(worker, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_exit_if_orphaned", lambda *a: None)
    monkeypatch.setattr(worker.importlib, "import_module", lambda *a: None)
    monkeypatch.setattr(vc.optional_deps, "activate", lambda: None)
    monkeypatch.setattr(worker, "emit", lambda event, **k: events.append("event:" + event))
    # Real logging handlers format records without retaining traceback frames.
    monkeypatch.setattr(worker.logger, "exception", lambda *a, **k: None)
    commands = [dict(action="generate", id=n, text="hello", reference_paths=[path],
                     output_path=str(tmp_path / f"out{n}.wav"), consent_accepted=True)
                for n, path in enumerate([paths[0], paths[0], paths[1]])]
    commands.append(dict(action="shutdown"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(map(json.dumps, commands))))
    assert worker.main() == 0
    scratch = config.user_cache_dir() / "voice_clone"
    assert len(list(scratch.iterdir())) == 1, "Long-job pieces must reuse the worker's session"
    assert not frozen_files()
    assert events.count("tts-load") == 2
    assert events.count("tts-generate") == 3
    assert events.count("asr-load") == 2
    assert events.index("tts-release") < events.index("asr-load", events.index("asr-load") + 1)
    assert events.index("asr-release") < events.index("tts-load")
    assert events.index("event:model_loading") < events.index("asr-load")
    assert events.index("asr-release", events.index("asr-release") + 1) < events.index(
        "tts-load", events.index("tts-load") + 1)


def test_unusable_configured_model_falls_back_to_cached_small(monkeypatch, tmp_path):
    custom, settings, _ = local_model(tmp_path, monkeypatch, "custom")
    small = hub.model_folder_for(tmp_path, "faster-whisper-small")
    small.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (small / name).write_text("{}", encoding="utf-8")
    calls, _ = fake_asr(monkeypatch)
    valid_factory = sys.modules["faster_whisper"].WhisperModel

    def factory(path, **kwargs):
        if path == str(custom):
            raise ValueError("invalid local config")
        return valid_factory(path, **kwargs)

    monkeypatch.setattr(sys.modules["faster_whisper"], "WhisperModel", factory)
    frozen = tmp_path / "frozen.wav"
    frozen.write_bytes(b"speech")
    assert vc._transcribe_reference(str(frozen)) == "reference speech"
    assert [path for path, _ in calls] == [str(small)]
    assert settings["model_path"] == str(custom)


def test_preparation_without_reference_never_reads_config_or_uses_asr(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda **kw: pytest.fail("unexpected config load"))
    calls, _ = fake_asr(monkeypatch)
    with vc.prepare_reference([], consent_accepted=False) as reference:
        assert reference is None
    assert calls == []


def test_lazy_segment_failure_releases_asr_and_does_not_cache_partial_text(monkeypatch, tmp_path):
    local_model(tmp_path, monkeypatch)

    def texts():
        yield "partial speech"
        raise RuntimeError("synthetic lazy decoder failure")

    _, refs = fake_asr(monkeypatch, texts=texts())
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"speech")
    with pytest.raises(RuntimeError, match="synthetic lazy decoder failure"):
        with vc.prepare_reference([str(source)], consent_accepted=True):
            pytest.fail("partial text must not reach TTS")
    assert all(ref() is None for ref in refs)
    assert not vc._reference_text_cache
    assert not frozen_files()


def test_transcript_cache_is_bounded_and_contains_only_text(monkeypatch, tmp_path):
    monkeypatch.setattr(vc, "_transcribe_reference", lambda path: Path(path).read_text())
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    for n in range(vc._REFERENCE_TEXT_CACHE_SIZE + 2):
        source.write_text(str(n))
        with vc.prepare_reference([str(source)], consent_accepted=True):
            pass
    assert len(vc._reference_text_cache) == vc._REFERENCE_TEXT_CACHE_SIZE
    assert all(isinstance(value, str) for value in vc._reference_text_cache.values())


def test_prepared_reference_cannot_be_reused_after_context_exit(monkeypatch, tmp_path):
    local_model(tmp_path, monkeypatch)
    fake_asr(monkeypatch)
    freeze(monkeypatch, tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"speech")
    with vc.prepare_reference([str(source)], consent_accepted=True) as reference:
        pass
    with pytest.raises(ValueError, match="prepare_reference"):
        vc.generate(object(), "hello", [str(source)], str(tmp_path / "out.wav"),
                    consent_accepted=True, prepared_reference=reference)


def test_concat_preserves_order_and_complete_audio_as_pcm(monkeypatch, tmp_path):
    seen = []

    def run(cmd, **kwargs):
        seen.extend(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", run)
    frozen = vc._concat_references(["first.wav", "second.wav", "third.wav", "ignored.wav"])
    try:
        assert "ignored.wav" not in seen
        assert "-t" not in seen
        assert [seen[i + 1] for i, arg in enumerate(seen) if arg == "-i"] == [
            "first.wav", "second.wav", "third.wav"]
        assert seen[seen.index("-c:a") + 1] == "pcm_s16le"
    finally:
        Path(frozen).unlink()
