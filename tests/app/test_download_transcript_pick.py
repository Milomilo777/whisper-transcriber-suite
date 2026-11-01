"""Which file "Open transcript" opens for a download row (pure; no Tk)."""
from __future__ import annotations

from app.domain.task_outputs import pick_openable_transcript


def _touch(tmp_path, *names):
    out = []
    for name in names:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        out.append(str(p))
    return out


def test_prefers_text_then_subtitles(tmp_path):
    paths = _touch(tmp_path, "a.json", "a.srt", "a.txt", "a.vtt")
    assert pick_openable_transcript(paths).endswith("a.txt")
    assert pick_openable_transcript([p for p in paths if not p.endswith(".txt")]).endswith("a.srt")


def test_json_only_or_sidecar_only_gives_none(tmp_path):
    paths = _touch(tmp_path, "a.json", "a.chapters.json")
    assert pick_openable_transcript(paths) is None


def test_missing_files_are_skipped_and_empty_inputs_are_safe(tmp_path):
    (kept,) = _touch(tmp_path, "b.docx")
    gone = str(tmp_path / "gone.txt")
    assert pick_openable_transcript([gone, kept]) == kept
    assert pick_openable_transcript([gone]) is None
    assert pick_openable_transcript(None) is None
    assert pick_openable_transcript([]) is None
    assert pick_openable_transcript([None, 5, ""]) is None


def test_non_ascii_names(tmp_path):
    (p,) = _touch(tmp_path, "گفتگو 日本語.txt")
    assert pick_openable_transcript([p]) == p
