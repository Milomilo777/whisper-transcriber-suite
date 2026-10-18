import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import wave
import zipfile
from types import SimpleNamespace

import pytest

import download_data
from runtime import audio_duration

SPIKE = Path(os.path.relpath(Path(__file__).parent.parent))
spec = importlib.util.spec_from_file_location("phone_spike_setup", SPIKE / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_seeded_sample_uses_the_whole_population_without_replacement():
    assert download_data.sampled_indices(10, 3) == [7, 1, 0]
    indices = download_data.sampled_indices(1000)
    assert indices == download_data.sampled_indices(1000)
    assert indices != download_data.sampled_indices(1000, seed=5)
    assert len(indices) == len(set(indices)) == 300
    assert max(indices) >= 900
    assert set(download_data.sampled_indices(5)) == set(range(5))
    with pytest.raises(ValueError):
        download_data.sampled_indices(0)


def test_concatenation_has_25_clips_and_only_24_silences(tmp_path):
    paths = []
    for index in range(25):
        path = tmp_path / f"{index}.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(struct.pack("<h", index + 1) * 1600)
        paths.append(path)
    output = tmp_path / "long_form.wav"
    assert download_data.build_long_form(paths, output) == 14.5
    assert audio_duration(output) == 14.5
    with wave.open(str(output), "rb") as audio:
        frames = audio.readframes(audio.getnframes())
    expected = (b"\0\0" * 8000).join(struct.pack("<h", index + 1) * 1600 for index in range(25))
    assert frames == expected
    with pytest.raises(ValueError):
        download_data.build_long_form([], tmp_path / "empty.wav")


def test_download_failure_preserves_readme_and_records_error(monkeypatch, tmp_path):
    before = (SPIKE / "README.md").read_bytes()
    monkeypatch.setitem(sys.modules, "datasets", None)
    with pytest.raises(ImportError):
        download_data.download_data(tmp_path / "data")
    error = (tmp_path / "data/DOWNLOAD_ERROR.txt").read_text(encoding="utf-8")
    assert "FLEURS download failed; no substitution" in error
    assert "ModuleNotFoundError" in error
    assert not (tmp_path / "data/refs.tsv").exists()
    assert (SPIKE / "README.md").read_bytes() == before


def test_data_pipeline_with_fake_dataset_is_offline_and_preserves_source_ids(monkeypatch, tmp_path):
    calls = {}
    rows = [{"id": "source-a", "raw_transcription": "سلام", "audio": {"sampling_rate": 16000, "array": [.25] * 1600}},
            {"id": "source-b", "raw_transcription": "خوب", "audio": {"sampling_rate": 16000, "array": [-.5] * 3200}}]
    class Dataset:
        def __len__(self):
            return 2
        def __getitem__(self, index):
            return rows[index]
        def cast_column(self, name, audio):
            assert name == "audio"
            assert audio == {"sampling_rate": 16000, "mono": True}
            return self
    def load(*args, **kwargs):
        calls.update(args=args, kwargs=kwargs)
        return Dataset()
    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=load, Audio=lambda **kw: kw))
    output = tmp_path / "fake-data"
    download_data.download_data(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert calls["args"] == ("google/fleurs", "fa_ir")
    assert calls["kwargs"]["split"] == "test"
    assert manifest["seed"] == 1234
    assert manifest["sample_size"] == 2
    assert manifest["source_indices"] == [1, 0]
    assert manifest["source_ids"] == ["source-b", "source-a"]
    assert manifest["long_form"] == {"utterances": 2, "silence_s": .5, "duration_s": .8}
    assert audio_duration(output / "0000.wav") == .2
    assert audio_duration(output / "0001.wav") == .1
    refs = (output / "refs.tsv").read_text(encoding="utf-8")
    assert refs.splitlines()[0] == "id\tduration_s\treference"
    assert refs.splitlines()[-1] == "long_form\t0.800000\tخوب سلام"


def test_setup_hashes_are_real_and_exclude_archive_and_manifest(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "tiny.bin").write_bytes(b"abc")
    (models / "tokens.txt").write_bytes(b"tokens")
    (models / "SHA256SUMS.txt").write_text("old", encoding="utf-8")
    (models / ".downloads").mkdir()
    (models / ".downloads/archive.zip").write_bytes(b"archive")
    assert setup.model_hashes(models) == {
        "tiny.bin": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "tokens.txt": hashlib.sha256(b"tokens").hexdigest()}


def test_setup_extracts_offline_fixture_and_rejects_traversal(tmp_path):
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("model/tokens.txt", "test tokens")
    setup.extract_archive(archive, tmp_path / "models")
    assert (tmp_path / "models/model/tokens.txt").read_text() == "test tokens"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "unsafe")
    with pytest.raises(ValueError, match="Unsafe archive"):
        setup.extract_archive(archive, tmp_path / "models")
    assert not (tmp_path / "escape.txt").exists()
