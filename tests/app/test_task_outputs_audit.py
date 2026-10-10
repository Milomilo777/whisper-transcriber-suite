import os
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.domain.task_outputs import (
    is_sidecar_json,
    pick_transcript_json,
    task_output_file,
    task_output_folder,
    task_output_with_ext,
    task_srt_output,
    task_transcript_json,
)

@dataclass
class MockTask:
    file_path: str
    output_paths: list[Any] | None = None

def test_is_sidecar_json():
    assert is_sidecar_json("video.chapters.json") is True
    assert is_sidecar_json("some/path/to/video.CHAPTERS.JSON") is True
    assert is_sidecar_json("video.json") is False
    assert is_sidecar_json("video.srt") is False
    assert is_sidecar_json("") is False

def test_task_output_with_ext(tmp_path):
    f1 = tmp_path / "out.srt"
    f1.write_text("hello")
    f2 = tmp_path / "out.json"
    f2.write_text("hello")
    
    task = MockTask(file_path="src.mp4", output_paths=[str(f1), str(f2)])
    assert task_output_with_ext(task, ".srt") == str(f1)
    assert task_output_with_ext(task, ".json") == str(f2)
    assert task_output_with_ext(task, ".vtt") is None
    
    task_empty = MockTask(file_path="src.mp4")
    assert task_output_with_ext(task_empty, ".srt") is None

    task_none = MockTask(file_path="src.mp4", output_paths=[None, 123, str(f1)])
    assert task_output_with_ext(task_none, ".srt") == str(f1)

def test_pick_transcript_json(tmp_path):
    f1 = tmp_path / "video.chapters.json"
    f2 = tmp_path / "video.json"
    f3 = tmp_path / "video (1).json"
    
    paths = [str(f1), str(f2), str(f3)]
    
    assert pick_transcript_json(paths, "video.mp4") == str(f2)
    assert pick_transcript_json([str(f1), str(f3)]) == str(f3)
    assert pick_transcript_json([str(f1)]) is None
    assert pick_transcript_json(None) is None
    
    assert pick_transcript_json(paths, "video.mp4", must_exist=True) is None
    f2.write_text("{}")
    assert pick_transcript_json(paths, "video.mp4", must_exist=True) == str(f2)
    
def test_task_transcript_json(tmp_path):
    f_json = tmp_path / "test.json"
    f_json.write_text("{}")
    
    task = MockTask(file_path="test.mp4", output_paths=[str(f_json)])
    assert task_transcript_json(task) == str(f_json)
    
def test_task_srt_output(tmp_path):
    f_srt = tmp_path / "test.srt"
    f_srt.write_text("test")
    task = MockTask(file_path=str(tmp_path / "test.mp4"), output_paths=[str(f_srt)])
    assert task_srt_output(task) == str(f_srt)
    
    task2 = MockTask(file_path=str(tmp_path / "test.mp4"))
    assert task_srt_output(task2) == str(f_srt)
    
    task3 = MockTask(file_path=str(tmp_path / "nonexistent.mp4"))
    assert task_srt_output(task3) is None

def test_task_output_folder_and_file(tmp_path):
    f_srt = tmp_path / "test.srt"
    f_srt.write_text("test")
    
    task = MockTask(file_path=str(tmp_path / "test.mp4"), output_paths=[str(f_srt)])
    assert task_output_folder(task) == str(tmp_path)
    assert task_output_file(task) == str(f_srt)
    
    task2 = MockTask(file_path=str(tmp_path / "test.mp4"))
    assert task_output_folder(task2) == str(tmp_path)
    assert task_output_file(task2) is None
    
    task3 = MockTask(file_path="test.mp4")
    assert task_output_folder(task3) == "."
    
    task4 = MockTask(file_path="")
    assert task_output_folder(task4) == "."

def test_pick_transcript_json_nfd_nfc_mismatch(tmp_path):
    # Tests that NFC paths match NFD source stems and vice versa, 
    # important for macOS where apfs may return NFD for directory listings
    # while the task.file_path may be NFC.
    base = "tést"
    nfc_base = unicodedata.normalize("NFC", base)
    nfd_base = unicodedata.normalize("NFD", base)
    
    f_json_nfc = tmp_path / f"{nfc_base}.json"
    other_json = tmp_path / "other.json"
    paths = [str(other_json), str(f_json_nfc)]
    
    source_nfd = str(tmp_path / f"{nfd_base}.mp4")
    
    # Should find f_json_nfc even though source is NFD
    assert pick_transcript_json(paths, source_nfd) == str(f_json_nfc)
    
    f_json_nfd = tmp_path / f"{nfd_base}.json"
    paths2 = [str(other_json), str(f_json_nfd)]
    source_nfc = str(tmp_path / f"{nfc_base}.mp4")
    
    # Should find f_json_nfd even though source is NFC
    assert pick_transcript_json(paths2, source_nfc) == str(f_json_nfd)

