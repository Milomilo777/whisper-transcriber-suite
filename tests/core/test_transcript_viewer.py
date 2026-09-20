"""Headless smoke for the in-app transcript viewer.

Drives the real ``app.dialogs.transcript_viewer.TranscriptViewer``
class against a JSON fixture so the widget tree is constructed,
the segments are populated, search filters the list, and segment
selection invokes the seek hook. No VLC dependency — VLC is
treated as optional and the viewer falls back gracefully when
libvlc isn't present, which is the CI scenario.
"""
from __future__ import annotations

import json
import os

import pytest

tk = pytest.importorskip("tkinter")


SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 1.5, "text": "Hello world", "speaker": "Speaker 00"},
    {"start": 1.5, "end": 3.0, "text": "Second segment", "speaker": "Speaker 01"},
    {"start": 3.0, "end": 5.0, "text": "Third with no speaker"},
]


@pytest.fixture
def sample_json(tmp_path):
    json_path = tmp_path / "demo.json"
    json_path.write_text(json.dumps(SAMPLE_SEGMENTS, ensure_ascii=False), encoding="utf-8")
    return str(json_path)


def test_viewer_loads_segments_into_tree(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            children = viewer.tree.get_children()
            assert len(children) == 3
            # Time column on the first row should be "00:00:00".
            assert viewer.tree.item(children[0], "values")[0] == "00:00:00"
            # Speaker column carries the diarisation label when present
            assert viewer.tree.item(children[0], "values")[1] == "Speaker 00"
            assert viewer.tree.item(children[2], "values")[1] == ""
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_search_filters_the_tree(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            viewer.search_var.set("second")
            viewer.update_idletasks()
            children = viewer.tree.get_children()
            assert len(children) == 1
            assert "Second segment" in viewer.tree.item(children[0], "values")[2]
            # Clearing the filter brings them all back.
            viewer.search_var.set("")
            viewer.update_idletasks()
            assert len(viewer.tree.get_children()) == 3
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_handles_missing_media_gracefully(sample_json):
    """The JSON lives in a tmp path with no media next to it. The
    viewer must still build cleanly; the embedded player either
    runs in a degraded "no media" state or is disabled by the
    VLC-fallback path."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert viewer.media_path is None
            # The play button is either disabled (when VLC absent) or
            # exists. Either way, the widget must exist and be usable.
            assert viewer.play_btn is not None
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_invalid_json_shows_empty_list(tmp_path, monkeypatch):
    """If the JSON is invalid, the viewer must not crash on
    construction — it logs the error via a messagebox and shows
    an empty tree."""
    from app.dialogs import transcript_viewer

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")

    # Stub out the error messagebox so the test isn't blocked by a
    # modal popup during CI.
    monkeypatch.setattr(transcript_viewer.messagebox, "showerror", lambda *a, **kw: None)

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = transcript_viewer.TranscriptViewer(root, str(bad))
        viewer.withdraw()
        try:
            assert viewer.tree.get_children() == ()
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_dict_root_explains_wrong_file(tmp_path, monkeypatch):
    """A dict-root JSON (e.g. a credentials/config file) must not crash;
    it shows an empty list and surfaces a 'pick the .json' style error
    rather than a raw 'root must be a list' message."""
    from app.dialogs import transcript_viewer

    cfg = tmp_path / "creds.json"
    cfg.write_text(json.dumps({"token": "secret"}), encoding="utf-8")

    captured: dict[str, str] = {}

    def _fake_showerror(title, message, **kw):
        captured["title"] = title
        captured["message"] = message

    monkeypatch.setattr(transcript_viewer.messagebox, "showerror", _fake_showerror)

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = transcript_viewer.TranscriptViewer(root, str(cfg))
        viewer.withdraw()
        try:
            assert viewer.tree.get_children() == ()
            assert "transcript JSON" in captured.get("message", "")
        finally:
            viewer._on_close()
    finally:
        root.destroy()


# --- v0.7.0 enhancements (B1) ------------------------------------------------


def test_strip_fillers_removes_uh_um_er():
    from app.dialogs.transcript_viewer import _strip_fillers, _filler_regex

    pat = _filler_regex()
    assert _strip_fillers("uh hello there", pat) == "hello there"
    assert _strip_fillers("Hello, um, world", pat) == "Hello, world"
    # Doesn't strip a legitimate trailing 'er' as in 'eraser':
    assert "eraser" in _strip_fillers("the eraser", pat)


def test_segment_min_probability_helpers():
    from app.dialogs.transcript_viewer import _segment_min_probability

    seg_with = {"words": [{"probability": 0.9}, {"probability": 0.7}]}
    assert _segment_min_probability(seg_with) == 0.7
    seg_without: dict = {}
    assert _segment_min_probability(seg_without) is None


def test_viewer_rename_speaker_globally(tmp_path):
    """Right-click → Rename speaker rewrites every segment with the
    same label and flags the viewer dirty."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": "Speaker 00"},
        {"start": 1.0, "end": 2.0, "text": "b", "speaker": "Speaker 01"},
        {"start": 2.0, "end": 3.0, "text": "c", "speaker": "Speaker 00"},
    ]
    p = tmp_path / "rn.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            # simpledialog blocks on a modal — stub the input.
            tv_mod.simpledialog.askstring = lambda *a, **kw: "Alice"  # type: ignore[attr-defined]
            tv_mod.messagebox.showinfo = lambda *a, **kw: None  # type: ignore[attr-defined]
            viewer._rename_speaker("Speaker 00")
            assert viewer.segments[0]["speaker"] == "Alice"
            assert viewer.segments[1]["speaker"] == "Speaker 01"
            assert viewer.segments[2]["speaker"] == "Alice"
            assert viewer._dirty is True
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_remove_fillers_button(tmp_path):
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "uh hello there"},
        {"start": 1.0, "end": 2.0, "text": "world, um, hi"},
    ]
    p = tmp_path / "fil.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            tv_mod.messagebox.showinfo = lambda *a, **kw: None  # type: ignore[attr-defined]
            viewer._remove_fillers()
            assert "uh" not in viewer.segments[0]["text"].lower().split()
            assert "um" not in viewer.segments[1]["text"].lower().split(", ")
            assert viewer._dirty is True
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_save_changes_round_trips(tmp_path):
    """Editing a segment then Save Changes must write the new
    segments back through the writer."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    p = tmp_path / "rt.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.showinfo = lambda *a, **kw: None  # type: ignore[attr-defined]
            viewer.segments[0]["text"] = "goodbye"
            viewer._dirty = True
            viewer._save_changes()
            payload = json.loads(p.read_text(encoding="utf-8"))
            assert payload[0]["text"] == "goodbye"
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_confidence_tags_applied(tmp_path):
    """Segments with low word confidence get the conf_low tag; high
    confidence gets conf_high."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "low",
         "words": [{"start": 0.0, "end": 1.0, "word": "low", "probability": 0.3}]},
        {"start": 1.0, "end": 2.0, "text": "high",
         "words": [{"start": 1.0, "end": 2.0, "word": "high", "probability": 0.95}]},
        {"start": 2.0, "end": 3.0, "text": "med",
         "words": [{"start": 2.0, "end": 3.0, "word": "med", "probability": 0.7}]},
    ]
    p = tmp_path / "conf.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            children = viewer.tree.get_children()
            assert "conf_low" in viewer.tree.item(children[0], "tags")
            assert "conf_high" in viewer.tree.item(children[1], "tags")
            assert "conf_med" in viewer.tree.item(children[2], "tags")
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_find_replace_replace_all(tmp_path):
    """FindReplaceDialog.replace_all rewrites every match in memory
    and flags the viewer dirty."""
    from app.dialogs.transcript_viewer import TranscriptViewer, FindReplaceDialog

    segs = [
        {"start": 0.0, "end": 1.0, "text": "color of the sky"},
        {"start": 1.0, "end": 2.0, "text": "another color word"},
        {"start": 2.0, "end": 3.0, "text": "different topic"},
    ]
    p = tmp_path / "fr.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.showinfo = lambda *a, **kw: None  # type: ignore[attr-defined]
            dlg = FindReplaceDialog(viewer)
            dlg.find_var.set("color")
            dlg.replace_var.set("colour")
            dlg.replace_all()
            assert viewer.segments[0]["text"] == "colour of the sky"
            assert viewer.segments[1]["text"] == "another colour word"
            assert viewer.segments[2]["text"] == "different topic"
            assert viewer._dirty is True
            dlg.destroy()
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_find_replace_backreference_in_replacement_is_literal():
    """Replacement strings that look like regex backreferences
    (e.g. ``\\1``, ``\\g<0>``) must be inserted LITERALLY, not
    interpreted as regex syntax — otherwise the user gets a
    misleading crash or silent garbage in the transcript."""
    from app.dialogs.transcript_viewer import FindReplaceDialog

    out = FindReplaceDialog._safe_replace("Hello world", "world", r"\1", False)
    assert out == r"Hello \1"

    out = FindReplaceDialog._safe_replace("Hello world", "world", r"\g<name>", False)
    assert out == r"Hello \g<name>"

    out = FindReplaceDialog._safe_replace("Hello world", "world", r"\\", False)
    assert out == r"Hello \\"


def test_find_replace_rejects_whitespace_only_needle(tmp_path):
    """Find with whitespace-only needle must noop instead of
    destructively replacing every space in every segment."""
    from app.dialogs.transcript_viewer import TranscriptViewer, FindReplaceDialog

    segs = [{"start": 0.0, "end": 1.0, "text": "hello world"}]
    p = tmp_path / "ws.json"
    p.write_text(json.dumps(segs), encoding="utf-8")
    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.showinfo = lambda *a, **kw: None  # type: ignore[attr-defined]
            dlg = FindReplaceDialog(viewer)
            dlg.find_var.set("  ")
            dlg.replace_var.set("X")
            dlg.replace_all()
            assert viewer.segments[0]["text"] == "hello world"
            assert viewer._dirty is False
            dlg.destroy()
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_speaker_rename_rejects_empty_input(tmp_path):
    """Renaming a speaker to empty / whitespace-only must noop,
    otherwise every matching label gets silently erased."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": "Speaker 00"},
    ]
    p = tmp_path / "rn2.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            from app.dialogs import transcript_viewer as tv_mod
            # askstring returns " " (whitespace) — viewer must noop.
            tv_mod.simpledialog.askstring = lambda *a, **kw: "   "  # type: ignore[attr-defined]
            viewer._rename_speaker("Speaker 00")
            assert viewer.segments[0]["speaker"] == "Speaker 00"
            assert viewer._dirty is False
        finally:
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_suspect_segments_get_red_background(tmp_path):
    """A segment carrying ``suspect=True`` must be rendered with the
    ``suspect`` row tag so the viewer highlights it in red. Tag layers
    UNDER the karaoke ``active`` tag and OVER the confidence colour."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "real speech"},
        {
            "start": 1.0, "end": 2.0,
            "text": "Thanks for watching!",
            "suspect": True,
            "suspect_reason": "bag-of-hallucinations",
        },
        {
            "start": 2.0, "end": 3.0,
            "text": "low confidence and suspect",
            "suspect": True,
            "suspect_reason": "repetition",
            "words": [
                {"start": 2.0, "end": 3.0, "word": "x", "probability": 0.2}
            ],
        },
    ]
    p = tmp_path / "sus.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            children = viewer.tree.get_children()
            tags0 = viewer.tree.item(children[0], "tags")
            tags1 = viewer.tree.item(children[1], "tags")
            tags2 = viewer.tree.item(children[2], "tags")
            assert "suspect" not in tags0
            assert "suspect" in tags1
            # Suspect + low confidence must coexist.
            assert "suspect" in tags2
            assert "conf_low" in tags2
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_strip_fillers_collapses_space_before_punctuation():
    """When an inline filler is removed, any space-before-punctuation
    artefact left behind must be tidied. The terminal-punctuation
    case ("Hello um!") collapses the filler word AND its trailing
    "!" because the regex treats them as one unit — this is the
    documented behaviour. The interesting case is the inline one."""
    from app.dialogs.transcript_viewer import _strip_fillers, _filler_regex

    pat = _filler_regex()
    # Inline filler — punctuation that wasn't part of the filler
    # group survives the cleanup.
    assert _strip_fillers("Are you um sure?", pat) == "Are you sure?"


# --- transport-bar pure helpers (seek slider / skip / MM:SS) ----------------
# These are pure functions — no Tk, no VLC — so they run on every platform
# regardless of whether libvlc or a display is present.


# --- manual timestamp editing (Edit timestamp... right-click menu) --------


def test_fmt_hms_ms_and_parse_round_trip():
    from app.dialogs.transcript_viewer import _fmt_hms_ms, _parse_hms_ms

    assert _fmt_hms_ms(0.0) == "00:00:00.000"
    assert _fmt_hms_ms(3661.5) == "01:01:01.500"
    assert _parse_hms_ms("01:01:01.500") == pytest.approx(3661.5)
    # MM:SS.mmm (no hour component) also parses.
    assert _parse_hms_ms("01:01.500") == pytest.approx(61.5)
    # Bare seconds.
    assert _parse_hms_ms("83.25") == pytest.approx(83.25)


def test_parse_hms_ms_rejects_garbage():
    from app.dialogs.transcript_viewer import _parse_hms_ms

    assert _parse_hms_ms("") is None
    assert _parse_hms_ms("   ") is None
    assert _parse_hms_ms("not a time") is None
    assert _parse_hms_ms("-5") is None
    assert _parse_hms_ms("1:2:3:4") is None
    assert _parse_hms_ms("-1:00:00") is None
    # Non-finite floats parse as valid Python floats but are not usable
    # timestamps — int(inf) crashes _fmt_hms later, so reject at the door.
    assert _parse_hms_ms("inf") is None
    assert _parse_hms_ms("Infinity") is None
    assert _parse_hms_ms("1e400") is None
    assert _parse_hms_ms("nan") is None
    assert _parse_hms_ms("1:00:inf") is None


def test_edit_timestamp_rejects_infinite_value(tmp_path):
    """Typing "inf" / "1e400" into the timestamp editor must be refused
    with the inline error, leaving the segment untouched — storing inf
    used to crash the list rebuild (OverflowError in _fmt_hms)."""
    from app.dialogs.transcript_viewer import TranscriptViewer, EditTimestampDialog

    segs = [{"start": 1.0, "end": 2.0, "text": "a"}]
    p = tmp_path / "ets_inf.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            dlg = EditTimestampDialog(viewer, 0)
            dlg.start_var.set("inf")
            dlg.end_var.set("00:00:03.000")
            dlg._save()
            assert viewer.segments[0]["start"] == 1.0
            assert viewer._dirty is False
            assert "valid time" in dlg.error_var.get()
        finally:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_loads_non_finite_timestamps_without_crashing(tmp_path):
    """A transcript JSON containing the bare ``NaN`` / ``Infinity``
    literals (Python's json writes and parses those by default) must
    load as a normal viewer with the bad timestamps shown as 00:00:00,
    not crash construction with ValueError/OverflowError."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    p = tmp_path / "nonfinite.json"
    p.write_text(
        json.dumps(
            [
                {"start": float("nan"), "end": 1.0, "text": "nan start"},
                {"start": 0.0, "end": float("inf"), "text": "inf end"},
            ]
        ),
        encoding="utf-8",
    )

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            children = viewer.tree.get_children()
            assert len(children) == 2
            assert viewer.tree.item(children[0], "values")[0] == "00:00:00"
            assert viewer.tree.item(children[1], "values")[0] == "00:00:00"
            assert viewer.tree.item(children[0], "values")[2] == "nan start"
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_segment_has_timing_issue_flags_overlap_and_short_duration():
    from app.dialogs.transcript_viewer import _segment_has_timing_issue

    segs = [
        {"start": 0.0, "end": 2.0},
        {"start": 1.0, "end": 3.0},   # overlaps segment 0's end (2.0)
        {"start": 3.0, "end": 3.5},   # under 1s duration
        {"start": 4.0, "end": 6.0},   # clean
    ]
    assert _segment_has_timing_issue(segs, 0) is False
    assert _segment_has_timing_issue(segs, 1) is True
    assert _segment_has_timing_issue(segs, 2) is True
    assert _segment_has_timing_issue(segs, 3) is False
    # Out-of-range indices are just False, never raise.
    assert _segment_has_timing_issue(segs, -1) is False
    assert _segment_has_timing_issue(segs, 99) is False


def test_viewer_edit_timestamp_updates_only_that_segment(tmp_path):
    """EditTimestampDialog._save must rewrite only the targeted
    segment's start/end and flag the viewer dirty — neighbouring
    segments must not shift."""
    from app.dialogs.transcript_viewer import TranscriptViewer, EditTimestampDialog

    segs = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.0, "end": 2.0, "text": "b"},
        {"start": 2.0, "end": 3.0, "text": "c"},
    ]
    p = tmp_path / "ets.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            dlg = EditTimestampDialog(viewer, 1)
            dlg.start_var.set("00:00:05.000")
            dlg.end_var.set("00:00:06.500")
            dlg._save()
            assert viewer.segments[1]["start"] == pytest.approx(5.0)
            assert viewer.segments[1]["end"] == pytest.approx(6.5)
            # Neighbours untouched.
            assert viewer.segments[0]["start"] == 0.0
            assert viewer.segments[0]["end"] == 1.0
            assert viewer.segments[2]["start"] == 2.0
            assert viewer.segments[2]["end"] == 3.0
            assert viewer._dirty is True
        finally:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_edit_timestamp_rejects_end_before_start(tmp_path):
    """An invalid edit (end <= start) must show an inline error and
    leave the segment's timestamps untouched — no crash, no silent
    corruption."""
    from app.dialogs.transcript_viewer import TranscriptViewer, EditTimestampDialog

    segs = [{"start": 1.0, "end": 2.0, "text": "a"}]
    p = tmp_path / "ets_bad.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            dlg = EditTimestampDialog(viewer, 0)
            dlg.start_var.set("00:00:05.000")
            dlg.end_var.set("00:00:03.000")  # end before start
            dlg._save()
            assert viewer.segments[0]["start"] == 1.0
            assert viewer.segments[0]["end"] == 2.0
            assert viewer._dirty is False
            assert "after start" in dlg.error_var.get()

            # Garbage input also rejected, not crashed.
            dlg.start_var.set("garbage")
            dlg.end_var.set("00:00:03.000")
            dlg._save()
            assert viewer.segments[0]["start"] == 1.0
            assert viewer._dirty is False
        finally:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_timing_warning_tag_after_edit(tmp_path):
    """After an edit makes a segment overlap its neighbour, the tree
    row must carry the 'ts_warn' tag; a clean edit must not."""
    from app.dialogs.transcript_viewer import TranscriptViewer, EditTimestampDialog

    segs = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 5.0, "end": 7.0, "text": "b"},
    ]
    p = tmp_path / "ets_warn.json"
    p.write_text(json.dumps(segs), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            children = viewer.tree.get_children()
            assert "ts_warn" not in viewer.tree.item(children[1], "tags")

            # Edit segment 1 to start before segment 0's end (1.0 < 2.0).
            dlg = EditTimestampDialog(viewer, 1)
            dlg.start_var.set("00:00:01.000")
            dlg.end_var.set("00:00:07.000")
            dlg._save()

            children = viewer.tree.get_children()
            assert "ts_warn" in viewer.tree.item(children[1], "tags")
        finally:
            from app.dialogs import transcript_viewer as tv_mod
            tv_mod.messagebox.askyesno = lambda *a, **kw: True  # type: ignore[attr-defined]
            viewer._on_close()
    finally:
        root.destroy()


def test_fmt_mmss_basic_and_hour_rollover():
    from app.dialogs.transcript_viewer import _fmt_mmss

    assert _fmt_mmss(0) == "00:00"
    assert _fmt_mmss(1000) == "00:01"
    assert _fmt_mmss(65000) == "01:05"
    assert _fmt_mmss(59000) == "00:59"
    # Past an hour switches to H:MM:SS form.
    assert _fmt_mmss(3661000) == "1:01:01"


def test_fmt_mmss_guards_unknown_length():
    """libvlc returns -1 / 0 for an unknown time or length — those must
    collapse to 00:00, never a negative clock."""
    from app.dialogs.transcript_viewer import _fmt_mmss

    assert _fmt_mmss(-1) == "00:00"
    assert _fmt_mmss(-50000) == "00:00"
    assert _fmt_mmss(0) == "00:00"


def test_slider_fraction_round_trip_and_clamp():
    from app.dialogs.transcript_viewer import (
        _SEEK_SLIDER_MAX,
        _fraction_to_slider,
        _slider_to_fraction,
    )

    assert _slider_to_fraction(0) == 0.0
    assert _slider_to_fraction(_SEEK_SLIDER_MAX) == 1.0
    assert _slider_to_fraction(_SEEK_SLIDER_MAX / 2) == 0.5
    # Out-of-range slider values clamp to the valid libvlc 0..1 domain.
    assert _slider_to_fraction(-100) == 0.0
    assert _slider_to_fraction(_SEEK_SLIDER_MAX * 2) == 1.0

    assert _fraction_to_slider(0.0) == 0.0
    assert _fraction_to_slider(1.0) == float(_SEEK_SLIDER_MAX)
    assert _fraction_to_slider(0.25) == _SEEK_SLIDER_MAX * 0.25
    # libvlc occasionally reports a position slightly past 1.0 near EOF.
    assert _fraction_to_slider(1.5) == float(_SEEK_SLIDER_MAX)
    assert _fraction_to_slider(-0.5) == 0.0


def test_clamp_time_ms_skip_arithmetic():
    from app.dialogs.transcript_viewer import _clamp_time_ms

    # Forward skip in the middle of the media.
    assert _clamp_time_ms(10_000, 5_000, 60_000) == 15_000
    # Back-skip before the start floors at 0.
    assert _clamp_time_ms(2_000, -5_000, 60_000) == 0
    # Forward skip past the end caps at total-1 (libvlc rejects == length).
    assert _clamp_time_ms(58_000, 10_000, 60_000) == 59_999
    # Unknown length (libvlc -1 / 0) only enforces the lower bound.
    assert _clamp_time_ms(10_000, 5_000, -1) == 15_000
    assert _clamp_time_ms(10_000, 5_000, 0) == 15_000
    assert _clamp_time_ms(1_000, -5_000, 0) == 0


# ---------- chapters tab ----------------------------------------------------


SAMPLE_CHAPTERS = [
    {"index": 0, "title": "Intro", "start": 0.0, "end": 1.5,
     "segment_start": 0, "segment_end": 0},
    {"index": 1, "title": "Main topic", "start": 1.5, "end": 5.0,
     "segment_start": 1, "segment_end": 2},
]


def test_viewer_with_no_chapters_sidecar_shows_empty_hint(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert viewer.chapters == []
            assert viewer._chapters_tree.winfo_manager() == ""
            assert viewer._chapters_empty_label.winfo_manager() == "pack"
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_loads_chapters_sidecar_into_tree(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    base, _ = os.path.splitext(sample_json)
    with open(base + ".chapters.json", "w", encoding="utf-8") as f:
        json.dump(SAMPLE_CHAPTERS, f)

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert len(viewer.chapters) == 2
            rows = viewer._chapters_tree.get_children()
            assert len(rows) == 2
            assert viewer._chapters_tree.item(rows[0], "values") == ("00:00:00", "Intro")
            assert viewer._chapters_tree.item(rows[1], "values") == ("00:00:01", "Main topic")
            assert viewer._chapters_tree.winfo_manager() == "pack"
            assert viewer._chapters_empty_label.winfo_manager() == ""
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_chapter_select_selects_nearest_segment(sample_json):
    """Exercises _select_segment_near directly — the logic a real
    <<TreeviewSelect>> on the Chapters tab drives via _on_chapter_select.
    No VLC in CI, so _seek_to() is a separate guarded no-op not covered
    here."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    base, _ = os.path.splitext(sample_json)
    with open(base + ".chapters.json", "w", encoding="utf-8") as f:
        json.dump(SAMPLE_CHAPTERS, f)

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            # Chapter 1 starts at 1.5s -> the segment starting at 1.5s (iid "1").
            viewer._select_segment_near(1.5)
            assert viewer.tree.selection() == ("1",)
            # Chapter 0 starts at 0.0s -> the first segment (iid "0").
            viewer._select_segment_near(0.0)
            assert viewer.tree.selection() == ("0",)
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_corrupt_chapters_sidecar_degrades_to_empty_list(sample_json):
    base, _ = os.path.splitext(sample_json)
    with open(base + ".chapters.json", "w", encoding="utf-8") as f:
        f.write("not valid json{{{")
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert viewer.chapters == []
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_initial_seek_seconds_selects_nearest_segment_on_open(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json, initial_seek_seconds=4.0)
        viewer.withdraw()
        try:
            # 4.0s falls inside the third segment (3.0-5.0s, iid "2").
            assert viewer.tree.selection() == ("2",)
        finally:
            viewer._on_close()
    finally:
        root.destroy()


# ---------- AI panel ---------------------------------------------------------


def test_full_transcript_text_joins_non_empty_segments(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            text = viewer._full_transcript_text()
            assert text == "Hello world\nSecond segment\nThird with no speaker"
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_ai_status_shows_off_when_ai_disabled(sample_json):
    """The plain tk.Tk() root used in every test here has no app_config
    attribute, so _app_config() falls back to {} -- ai_enabled defaults
    False, same as a real App whose config has the AI Layer off."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert "off" in viewer._ai_status_var.get().lower()
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_ai_status_reflects_remote_provider_when_configured(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    root.app_config = {  # type: ignore[attr-defined]
        "ai_enabled": True,
        "llm_provider": "remote",
        "llm_remote_model": "gpt-4o-mini",
    }
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            status = viewer._ai_status_var.get()
            assert "remote" in status.lower()
            assert "gpt-4o-mini" in status
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_get_llm_runner_reports_ai_disabled(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            runner, err = viewer._get_llm_runner()
            assert runner is None
            assert "AI Layer is off" in err
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_get_llm_runner_reports_remote_not_configured(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    root.app_config = {  # type: ignore[attr-defined]
        "ai_enabled": True, "llm_provider": "remote",
        "llm_remote_base_url": "", "llm_remote_model": "",
    }
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            runner, err = viewer._get_llm_runner()
            assert runner is None
            assert "Remote LLM isn't configured" in err
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_get_llm_runner_caches_across_calls(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    root.app_config = {  # type: ignore[attr-defined]
        "ai_enabled": True, "llm_provider": "remote",
        "llm_remote_base_url": "https://api.openai.com/v1",
        "llm_remote_model": "gpt-4o-mini", "llm_remote_api_key": "sk-x",
    }
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            runner1, _err1 = viewer._get_llm_runner()
            runner2, _err2 = viewer._get_llm_runner()
            assert runner1 is not None
            assert runner1 is runner2  # same cached instance, not rebuilt
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_bilingual_button_disabled_while_ai_busy(sample_json):
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert "disabled" not in viewer._ai_summarise_btn.state()
            viewer._set_ai_buttons_busy(True)
            assert "disabled" in viewer._ai_summarise_btn.state()
            assert "disabled" in viewer._ai_bilingual_btn.state()
            viewer._set_ai_buttons_busy(False)
            assert "disabled" not in viewer._ai_summarise_btn.state()
        finally:
            viewer._on_close()
    finally:
        root.destroy()


# ---------- playback degradation (missing media / VLC init failure) ----------


def _assert_transport_disabled(viewer):
    assert "disabled" in viewer.play_btn.state()
    assert "disabled" in viewer.seek_scale.state()
    for b in viewer._skip_btns:
        assert "disabled" in b.state()


def test_viewer_disables_transport_when_no_media_found(sample_json, monkeypatch):
    """VLC available but no media file next to the JSON: the embedded
    player is never built, so Play and the transport bar must be greyed
    out instead of silently doing nothing."""
    from app.dialogs import transcript_viewer as tv_mod
    from app.dialogs.transcript_viewer import TranscriptViewer

    monkeypatch.setattr(tv_mod, "_try_load_vlc", lambda: (object(), ""))

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            assert viewer.media_path is None
            _assert_transport_disabled(viewer)
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def test_viewer_disables_transport_when_vlc_init_fails(tmp_path, monkeypatch):
    """python-vlc imports fine but Instance() blows up: the viewer must
    fall back to the system-player path with the whole transport bar
    disabled, not leave dead controls enabled."""
    from app.dialogs import transcript_viewer as tv_mod
    from app.dialogs.transcript_viewer import TranscriptViewer

    class _BoomVLC:
        def Instance(self, *_a, **_kw):
            raise RuntimeError("vlc instance boom")

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"")
    p = tmp_path / "clip.json"
    p.write_text(json.dumps(SAMPLE_SEGMENTS), encoding="utf-8")
    monkeypatch.setattr(tv_mod, "_try_load_vlc", lambda: (_BoomVLC(), ""))

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            assert viewer.media_path is not None
            assert viewer.vlc_player is None
            _assert_transport_disabled(viewer)
        finally:
            viewer._on_close()
    finally:
        root.destroy()


# ---------- right-click menu lifecycle ----------------------------------------


def test_right_click_menu_destroyed_after_popup(sample_json, monkeypatch):
    """Each right-click builds a fresh Menu child of the viewer; it must
    be destroyed once dismissed, or every click leaks another dead Tk
    widget for the rest of the session."""
    import types

    from app.dialogs import transcript_viewer as tv_mod
    from app.dialogs.transcript_viewer import TranscriptViewer

    root = tk.Tk()
    root.withdraw()
    try:
        viewer = TranscriptViewer(root, sample_json)
        viewer.withdraw()
        try:
            monkeypatch.setattr(tv_mod.tk.Menu, "tk_popup", lambda self, x, y: None)
            monkeypatch.setattr(viewer.tree, "identify_row", lambda _y: "0")
            for _ in range(3):
                viewer._on_segment_right_click(
                    types.SimpleNamespace(y=10, x_root=0, y_root=0)
                )
            leftover = [
                child for child in viewer.winfo_children()
                if isinstance(child, tk.Menu)
            ]
            assert leftover == []
        finally:
            viewer._on_close()
    finally:
        root.destroy()
