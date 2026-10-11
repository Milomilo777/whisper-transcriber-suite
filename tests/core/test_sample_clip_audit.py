from __future__ import annotations
import os
import sys
import shutil
import pytest
from pathlib import Path
from core import sample_clip

def test_candidate_dirs_empty_meipass(monkeypatch):
    monkeypatch.setattr(sample_clip.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sample_clip.sys, "executable", "/fake/exe", raising=False)
    monkeypatch.setattr(sample_clip.sys, "_MEIPASS", "", raising=False)
    dirs = sample_clip._candidate_dirs()
    expected = Path(os.path.abspath('/fake/exe')).parent
    assert expected in dirs
    assert Path("") not in dirs
    assert Path(".") not in dirs
    # The source tree is also there
    assert len(dirs) == 2

def test_prepare_working_copy_oserror_on_mkdir(tmp_path, monkeypatch):
    """Hypothesis: folder.mkdir raises OSError if it fails."""
    monkeypatch.setattr(sample_clip, "samples_dir", lambda: tmp_path / "samples")
    source_file = tmp_path / "assets" / sample_clip.SAMPLE_CLIP_NAME
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("dummy")
    
    def mock_bundled_clip_path():
        return str(source_file)
    monkeypatch.setattr(sample_clip, "bundled_clip_path", mock_bundled_clip_path)

    # Create a file where the directory should be
    (tmp_path / "samples").write_text("not a dir")
    
    with pytest.raises(OSError):
        sample_clip.prepare_working_copy()
