"""Hermetic tests for the local NVIDIA Parakeet / transformers ASR backend.

NO network, NO torch/transformers/librosa import, NO model, NO audio. These
exercise only the pure seams (resolve_device, resolve_dtype, chunks_to_segments,
text_to_segment, friendly_load_error), the config read, the factory, and the
availability + registry wiring. The live transformers path is covered by a
separate real run, not here.
"""
from __future__ import annotations

import importlib
import importlib.util

import pytest

from core.backends import get_backend
from core.backends import nvidia_asr as na
from core.backends.cloud_stt import offset_segments


# ---------------------------------------------------------------- device / dtype


def test_resolve_device_auto_prefers_cuda_when_available():
    assert na.resolve_device("auto", True) == "cuda"


def test_resolve_device_auto_falls_back_to_cpu():
    assert na.resolve_device("auto", False) == "cpu"
    assert na.resolve_device("", False) == "cpu"
    assert na.resolve_device(None, False) == "cpu"


def test_resolve_device_explicit_passes_through():
    assert na.resolve_device("cpu", True) == "cpu"
    assert na.resolve_device("cuda:1", False) == "cuda:1"


def test_resolve_dtype_auto_by_device():
    assert na.resolve_dtype("auto", "cuda") == "float16"
    assert na.resolve_dtype("auto", "cuda:0") == "float16"
    assert na.resolve_dtype("auto", "cpu") == "float32"


def test_resolve_dtype_explicit_passes_through():
    assert na.resolve_dtype("float32", "cuda") == "float32"
    assert na.resolve_dtype("float16", "cpu") == "float16"


# ---------------------------------------------------------------- chunks_to_segments


def _ch(text, start, end):
    """A transformers word-chunk dict (timestamps are in SECONDS)."""
    return {"text": text, "timestamp": (start, end)}


def test_chunks_to_segments_happy_path():
    chunks = [_ch(" hello", 0.0, 0.4), _ch(" world", 0.4, 0.9)]
    segs = na.chunks_to_segments(chunks)
    assert len(segs) == 1
    seg = segs[0]
    assert seg["text"] == "hello world"
    assert seg["start"] == pytest.approx(0.0)
    assert seg["end"] == pytest.approx(0.9)
    assert len(seg["words"]) == 2
    assert seg["words"][0]["word"] == "hello"
    assert seg["words"][0]["start"] == pytest.approx(0.0)
    assert seg["words"][1]["end"] == pytest.approx(0.9)


def test_chunks_to_segments_seconds_not_milliseconds():
    # transformers reports seconds; the helper must NOT divide by 1000.
    segs = na.chunks_to_segments([_ch("test", 1.5, 2.0)])
    assert segs[0]["start"] == pytest.approx(1.5)
    assert segs[0]["end"] == pytest.approx(2.0)


def test_chunks_to_segments_groups_by_max_seconds():
    # Words running 0..12 s should split once the running span hits 10 s.
    chunks = [_ch(f"w{i}", float(i), float(i + 1)) for i in range(12)]
    segs = na.chunks_to_segments(chunks, max_segment_seconds=10.0)
    assert len(segs) == 2
    assert segs[0]["start"] == pytest.approx(0.0)
    assert segs[0]["end"] == pytest.approx(10.0)
    assert segs[1]["start"] == pytest.approx(10.0)


def test_chunks_to_segments_skips_none_timestamps():
    chunks = [_ch("good", 0.0, 0.5), {"text": "bad", "timestamp": (None, None)}]
    segs = na.chunks_to_segments(chunks)
    assert len(segs) == 1
    assert segs[0]["text"] == "good"


def test_chunks_to_segments_empty():
    assert na.chunks_to_segments([]) == []
    assert na.chunks_to_segments(None) == []


def test_chunks_to_segments_collapses_double_spaces():
    segs = na.chunks_to_segments([_ch("  foo ", 0.0, 1.0), _ch(" bar", 1.0, 2.0)])
    assert segs[0]["text"] == "foo bar"


# ---------------------------------------------------------------- text_to_segment


def test_text_to_segment_wraps_text():
    segs = na.text_to_segment("hello there", 5.0, 35.0)
    assert len(segs) == 1
    assert segs[0] == {
        "start": 5.0,
        "end": 35.0,
        "text": "hello there",
        "words": [],
    }


def test_text_to_segment_empty_returns_empty():
    assert na.text_to_segment("", 0.0, 10.0) == []
    assert na.text_to_segment("   ", 0.0, 10.0) == []
    assert na.text_to_segment(None, 0.0, 10.0) == []


def test_text_to_segment_end_not_before_start():
    segs = na.text_to_segment("x", 10.0, 5.0)
    assert segs[0]["end"] >= segs[0]["start"]


# ---------------------------------------------------------------- offset reuse


def test_offset_segments_places_on_global_timeline():
    chunk_segs = na.chunks_to_segments([_ch("a", 0.0, 1.0), _ch("b", 1.0, 2.0)])
    global_segs = offset_segments(chunk_segs, 30.0)
    assert global_segs[0]["start"] == pytest.approx(30.0)
    assert global_segs[0]["end"] == pytest.approx(32.0)
    assert global_segs[0]["words"][0]["start"] == pytest.approx(30.0)
    # Input untouched (pure).
    assert chunk_segs[0]["start"] == pytest.approx(0.0)


# ---------------------------------------------------------------- friendly_load_error


def test_friendly_load_error_librosa():
    msg = na.friendly_load_error(ImportError("requires the librosa library"))
    assert "librosa" in msg


def test_friendly_load_error_missing_model():
    msg = na.friendly_load_error(OSError("Repository Not Found for url ..."))
    assert "nvidia_asr_model_id" in msg or "model" in msg.lower()


def test_friendly_load_error_generic():
    msg = na.friendly_load_error(RuntimeError("something odd"))
    assert "NVIDIA ASR" in msg or "something odd" in msg


def test_friendly_load_error_tokenizers_version_clash():
    msg = na.friendly_load_error(
        ImportError(
            "tokenizers>=0.22.0,<=0.23.0 is required for a normal "
            "functioning of this module, but found tokenizers==0.23.1."
        )
    )
    assert "dependency clash" in msg.lower()
    assert "different engine" in msg.lower()


# ---------------------------------------------------------------- config read


def test_read_config_defaults_when_empty():
    b = na.NvidiaAsrBackend(config={})
    b._read_config()
    assert b._model_id == na.DEFAULT_MODEL_ID
    assert b._device_cfg == "auto"
    assert b._dtype_cfg == "auto"
    assert b._chunk_seconds == pytest.approx(na.DEFAULT_CHUNK_SECONDS)


def test_read_config_reads_values():
    b = na.NvidiaAsrBackend(config={
        "nvidia_asr_model_id": "  some/model  ",
        "nvidia_asr_device": "cuda",
        "nvidia_asr_dtype": "float16",
        "nvidia_asr_chunk_seconds": 15,
    })
    b._read_config()
    assert b._model_id == "some/model"
    assert b._device_cfg == "cuda"
    assert b._dtype_cfg == "float16"
    assert b._chunk_seconds == pytest.approx(15.0)


def test_read_config_bad_chunk_seconds_falls_back():
    b = na.NvidiaAsrBackend(config={"nvidia_asr_chunk_seconds": "nonsense"})
    b._read_config()
    assert b._chunk_seconds == pytest.approx(na.DEFAULT_CHUNK_SECONDS)


def test_backend_starts_not_ready():
    b = na.NvidiaAsrBackend(config={})
    assert b.is_ready() is False
    assert b.get_error() is None


def test_load_reports_friendly_error_on_tokenizers_version_clash(monkeypatch):
    """The real-world failure: find_spec sees transformers on disk (so the
    on-demand installer is skipped), but the actual import raises from
    transformers' own dependency_versions_check. load() must route that
    through friendly_load_error(), not a raw f-string of the exception."""
    b = na.NvidiaAsrBackend(config={})
    monkeypatch.setattr(na, "_deps_available", lambda: True)

    def _boom():
        raise ImportError(
            "tokenizers>=0.22.0,<=0.23.0 is required for a normal "
            "functioning of this module, but found tokenizers==0.23.1."
        )

    monkeypatch.setattr(na, "_import_torch_and_transformers", _boom)
    assert b.load() is False
    assert "dependency clash" in (b.get_error() or "").lower()


# ---------------------------------------------------------------- dep probe


def test_deps_available_requires_all_three(monkeypatch):
    """transformers alone is not enough — torch (optional for transformers)
    and librosa (Parakeet's mel front-end) are needed too."""
    import importlib.util

    present = {"transformers", "torch", "librosa"}
    monkeypatch.setattr(
        importlib.util, "find_spec",
        lambda name: object() if name in present else None,
    )
    assert na._deps_available() is True
    present.discard("torch")
    assert na._deps_available() is False
    present.discard("librosa")
    assert na._deps_available() is False


def test_load_installs_when_torch_missing(monkeypatch):
    """A half-present environment (transformers there, torch missing) must
    still run the on-demand install — and must FORCE it, because
    optional_deps.install()'s own probe would otherwise short-circuit on
    transformers and install nothing."""
    b = na.NvidiaAsrBackend(config={})
    state = {"deps": False, "install": 0, "force": None}

    monkeypatch.setattr(na, "_deps_available", lambda: state["deps"])

    import core.optional_deps as od

    monkeypatch.setattr(od, "is_available", lambda feature: True)

    def fake_install(feature, log_cb=None, cancel_event=None, timeout=None, force=False):
        assert feature == "nvidia_asr"
        state["install"] += 1
        state["force"] = force
        state["deps"] = True  # pretend pip succeeded
        return True

    monkeypatch.setattr(od, "install", fake_install)

    def _boom():
        raise ImportError("sentinel-stop")

    monkeypatch.setattr(na, "_import_torch_and_transformers", _boom)

    assert b.load() is False
    assert state["install"] == 1
    assert state["force"] is True  # half-present -> forced repair
    assert "sentinel-stop" in (b.get_error() or "")


def test_load_skips_install_when_all_deps_present(monkeypatch):
    """When all three dependencies are importable, no pip install runs."""
    b = na.NvidiaAsrBackend(config={})
    monkeypatch.setattr(na, "_deps_available", lambda: True)

    import core.optional_deps as od

    calls: list[int] = []
    monkeypatch.setattr(od, "install", lambda *a, **k: calls.append(1))

    def _boom():
        raise ImportError("sentinel-stop")

    monkeypatch.setattr(na, "_import_torch_and_transformers", _boom)
    assert b.load() is False
    assert calls == []
    assert "sentinel-stop" in (b.get_error() or "")


# ---------------------------------------------------------------- factory


def test_get_backend_returns_nvidia_asr():
    b = get_backend("nvidia_asr")
    assert b.name == "nvidia_asr"
    assert isinstance(b, na.NvidiaAsrBackend)


# ---------------------------------------------------------------- availability


def test_availability_deep_not_ready_without_transformers(monkeypatch):
    from core.backends import availability

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    st = availability.engine_status("nvidia_asr", {}, deep=True)
    assert st.ready is False
    assert st.detail != ""


def test_availability_deep_ready_with_transformers(monkeypatch):
    from core.backends import availability

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(availability, "_import_transformers", lambda: None)
    st = availability.engine_status("nvidia_asr", {}, deep=True)
    assert st.ready is True


def test_availability_deep_not_ready_on_version_clash(monkeypatch):
    """find_spec sees the files on disk, but the real import still raises
    (the tokenizers/transformers version-clash case) — must NOT report
    ready, and the detail must carry the friendly diagnostic."""
    from core.backends import availability

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def _boom() -> None:
        raise ImportError(
            "tokenizers>=0.22.0,<=0.23.0 is required for a normal "
            "functioning of this module, but found tokenizers==0.23.1."
        )

    monkeypatch.setattr(availability, "_import_transformers", _boom)
    st = availability.engine_status("nvidia_asr", {}, deep=True)
    assert st.ready is False
    assert "dependency clash" in st.detail.lower()


def test_availability_shallow_is_ready_at_startup():
    # The cheap startup path does no heavy import: a local self-provisioning
    # engine reports ready (a run surfaces any real gap), like faster-whisper.
    from core.backends import availability

    st = availability.engine_status("nvidia_asr", {}, deep=False)
    assert st.ready is True


# ---------------------------------------------------------------- registry sync


def test_nvidia_asr_in_known_engines():
    from core.backends.availability import KNOWN_ENGINES

    assert "nvidia_asr" in KNOWN_ENGINES


def test_nvidia_asr_in_advanced_backend_choices():
    """NVIDIA ASR must appear in the Advanced dialog's backend picker.

    Imports the real app.dialogs.advanced. This test used to plant stub
    ``tkinter`` / ``core.config`` / ``core.model_manager`` / ``core.writers``
    modules in sys.modules (never removed) whenever they were not imported
    yet -- harmless in a full run where tkinter was already loaded, but on
    macOS, where test files run one per process, the stub tkinter had no
    ``font`` submodule and broke every later tkinter import ("cannot import
    name 'font' from 'tkinter' (unknown location)").
    """
    pytest.importorskip("tkinter")
    advanced = importlib.import_module("app.dialogs.advanced")
    values = set(advanced._BACKEND_LABEL_TO_VALUE.values())
    assert "nvidia_asr" in values


def test_availability_and_advanced_nvidia_asr_in_sync():
    from core.backends.availability import KNOWN_ENGINES

    assert "nvidia_asr" in KNOWN_ENGINES
    advanced = importlib.import_module("app.dialogs.advanced")
    values = set(advanced._BACKEND_LABEL_TO_VALUE.values())
    assert "nvidia_asr" in values
