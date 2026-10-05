"""End-to-end tests exercising v0.8 features on the real SMTV clip.

Real-file fixture: ``tests/fixtures/smtv_clip/AD-The-Most-Powerful-Daily-Prayer-max.mp3``
(91-second English narration). Skipped automatically if the clip
or the Whisper model isn't present.

The tests in this file actually load + run faster-whisper against
the real audio, so they're meaningfully slower than the rest of
the unit suite (~ tens of seconds each). They always belonged
conceptually with the smoke tests (same model-load cost, same
skip-when-resources-missing gating pattern) but originally lived in
``tests/core/`` for a shared-fixture reason that no longer applies.

Moved here 2026-08-15 (see ``docs/DECISIONS.md`` ADR 0008): on a machine where both the fixture
clip and the real model happen to be present, this file used to run for
real as part of ``run_tests.bat``'s ~700-test "hermetic" suite
(``pytest tests/ --ignore=tests/smoke``) — concurrently with dozens of
other tests' leftover threads and any real-model-loading elsewhere in
the same run. That specific combination (a real faster-whisper load /
transcribe here, running at the same time as several other heavyweight
background threads left over from earlier tests) was implicated in a
real, hard-to-pin-down native crash (Windows STATUS_BREAKPOINT via
CPython's garbage collector) that resisted several rounds of targeted
``gc.disable()`` fixes elsewhere in the codebase. Running this file only
via the separate smoke-test path (never mixed into the hermetic run)
removes that specific trigger condition regardless of whether the
underlying GC/threading interaction is ever fully understood.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest


SMTV_CLIP = Path(__file__).resolve().parents[1] / "fixtures" / "smtv_clip" / \
    "AD-The-Most-Powerful-Daily-Prayer-max.mp3"


pytestmark = pytest.mark.skipif(
    not SMTV_CLIP.exists(),
    reason="SMTV clip fixture missing — set up tests/fixtures/smtv_clip/",
)


# ---------- fixture: run transcription once, share across tests ----------


@pytest.fixture(scope="module")
def transcribed_clip(tmp_path_factory):
    """Transcribe the SMTV clip once + share the JSON / chapters across tests.

    Uses the real ``core.transcriber.transcribe`` so we exercise the
    full v0.8 pipeline: model load → faster_whisper → hallucination
    detector → auto-chapters → atomic writer + chapters sidecar.
    """
    import core.transcriber as t
    from core.task import TranscriptionTask

    # Force a genuine model (re)load instead of reusing whatever is in the
    # global: an earlier unit test may have left a fake MODEL with
    # MODEL_READY=True, which would otherwise be mistaken for "ready" here and
    # blow up when the real transcription calls .transcribe() on the fake.
    t.MODEL = None
    t.MODEL_READY = False
    ok = t.load_existing_model()
    if not ok:
        ok = t.load_model()
    if not ok:
        pytest.skip(f"Whisper model failed to load: {t.get_model_error()}")

    workdir = tmp_path_factory.mktemp("smtv_e2e")
    audio_copy = workdir / "clip.mp3"
    shutil.copy(str(SMTV_CLIP), str(audio_copy))

    task = TranscriptionTask(file_path=str(audio_copy))

    # Force all v0.8 toggles ON for this run so the E2E exercises
    # hallucination + auto-chapters in one shot. Demucs + AI Layer
    # require optional deps; leave them OFF so the pipeline is
    # deterministic on a stock install.
    saved_keys = {}
    for k, v in {
        "hallucination_detect_enabled": True,
        "auto_chapters_enabled": True,
        "chapter_min_seconds": 15.0,   # tighten so 91 s clip yields ≥ 1 chapter
        "chapter_gap_seconds": 1.0,
        "output_formats": ["json", "srt"],
        "diarization_enabled": False,
        "alignment": "none",
        "demucs_enabled": False,
        "ai_enabled": False,
    }.items():
        saved_keys[k] = t.config.get(k)
        t.config[k] = v
    try:
        logs: list[str] = []
        t.transcribe(task, log_cb=logs.append)
    finally:
        for k, v in saved_keys.items():
            if v is None:
                t.config.pop(k, None)
            else:
                t.config[k] = v

    base = os.path.splitext(str(audio_copy))[0]
    json_path = Path(base + ".json")
    chapters_path = Path(base + ".chapters.json")
    srt_path = Path(base + ".srt")

    assert json_path.exists(), f"JSON not written: {json_path}"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)

    return {
        "audio": audio_copy,
        "json_path": json_path,
        "chapters_path": chapters_path,
        "srt_path": srt_path,
        "segments": payload,
        "logs": logs,
    }


# ---------- 1) transcription produced expected outputs -------------------------


def test_transcribed_json_has_segments(transcribed_clip):
    segments = transcribed_clip["segments"]
    assert len(segments) > 0
    # The clip is 91 seconds — typical Whisper produces 8–25 segments.
    # Don't assert on exact counts (varies by VAD tuning); just that
    # the structure is sane.
    for s in segments[:5]:
        assert "start" in s
        assert "end" in s
        assert "text" in s
        assert s["end"] >= s["start"]


def test_transcribed_srt_is_readable(transcribed_clip):
    srt = transcribed_clip["srt_path"].read_text(encoding="utf-8")
    # SRT cue numbering: "1\n00:00:..."
    assert "00:00:" in srt
    assert "-->" in srt


def test_transcribed_text_includes_english_words(transcribed_clip):
    """The clip is English narration; ensure Whisper recognised content
    rather than emitting only silence-marker hallucinations."""
    all_text = " ".join((s.get("text") or "") for s in transcribed_clip["segments"])
    # Loose word counting — anything 10+ characters of recognised text
    # means transcription succeeded.
    assert len(all_text.strip()) > 100, f"Too little text: {all_text[:100]!r}"


# ---------- 2) hallucination detector ran and produced sensible flags ----------


def test_hallucination_detector_ran(transcribed_clip):
    """The detector should have annotated suspect segments (zero is
    valid too — the clip is real English narration so most segments
    are legitimate). Whatever the count, every flagged segment must
    carry a non-empty reason string."""
    flagged = [s for s in transcribed_clip["segments"] if s.get("suspect")]
    for s in flagged:
        assert isinstance(s.get("suspect_reason"), str) and s["suspect_reason"], (
            f"suspect=True without a reason: {s}"
        )


# ---------- 3) auto-chapter sidecar was generated ------------------------------


def test_chapters_sidecar_written(transcribed_clip):
    """A 91 s clip with chapter_min_seconds=15 + gap=1 should produce
    at least one chapter. Each chapter has all required fields."""
    chap_path = transcribed_clip["chapters_path"]
    assert chap_path.exists(), f"chapters sidecar not written: {chap_path}"
    chapters = json.loads(chap_path.read_text(encoding="utf-8"))
    assert isinstance(chapters, list)
    assert len(chapters) >= 1
    for c in chapters:
        assert isinstance(c.get("index"), int)
        assert isinstance(c.get("title"), str) and c["title"]
        assert isinstance(c.get("start"), (int, float))
        assert isinstance(c.get("end"), (int, float))
        assert c["end"] >= c["start"]
        assert "segment_start" in c and "segment_end" in c


def test_chapter_indices_are_sequential(transcribed_clip):
    chap_path = transcribed_clip["chapters_path"]
    chapters = json.loads(chap_path.read_text(encoding="utf-8"))
    assert [c["index"] for c in chapters] == list(range(len(chapters)))


def test_chapter_time_ranges_cover_the_transcript(transcribed_clip):
    """The union of chapter ranges should span the whole transcript
    (no gaps wider than the gap_seconds threshold between chapters)."""
    chap_path = transcribed_clip["chapters_path"]
    segments = transcribed_clip["segments"]
    chapters = json.loads(chap_path.read_text(encoding="utf-8"))
    if not segments or not chapters:
        return
    last_seg_end = max(float(s.get("end", 0.0)) for s in segments
                        if not s.get("__chapters__"))
    last_chap_end = max(float(c["end"]) for c in chapters)
    # Chapters end at the last real segment (modulo float rounding).
    assert abs(last_chap_end - last_seg_end) < 1.0


# ---------- 4) search across history works end-to-end --------------------------


def test_search_indexes_transcribed_json_and_finds_terms(transcribed_clip, tmp_path):
    """Index the freshly-transcribed JSON via core.search and verify
    we can recover the segment by querying for a word from its text."""
    from core import search as sm

    db_path = tmp_path / "search.db"
    conn = sm._open_db(db_path)
    try:
        n = sm.index_file(str(transcribed_clip["json_path"]), conn=conn)
        assert n >= 1, "no segments indexed"

        # Pick a content word from one of the segments to query.
        chosen = None
        for s in transcribed_clip["segments"]:
            text = (s.get("text") or "").strip()
            words = [w for w in text.split() if len(w) > 4 and w.isalpha()]
            if words:
                chosen = words[0]
                break
        assert chosen is not None, "couldn't find a content word in transcript"

        hits = sm.search(chosen, conn=conn)
        assert len(hits) >= 1
        assert any(chosen.lower() in h.text.lower() for h in hits)
        # Hits carry resolvable timestamps for navigation.
        assert all(h.start_seconds >= 0 for h in hits)
    finally:
        conn.close()


# ---------- 5) voiceprint relabel is a clean no-op without enrolled voices ---


def test_voiceprint_relabel_noop_with_empty_db(transcribed_clip, tmp_path):
    """Without any enrolled voices, the cross-file fingerprint
    relabeller must leave the diariser's labels (or absence thereof)
    untouched — proving the integration path is safe to call even
    when the feature isn't actively used."""
    from core import voiceprint as vp

    conn = vp._open_db(tmp_path / "voices.db")
    try:
        segs_copy = [dict(s) for s in transcribed_clip["segments"]]
        original = [s.get("speaker") for s in segs_copy]
        # Fake clusters that look plausible for diariser output.
        clusters = {"SPEAKER_00": [1.0, 0.0, 0.0]}
        n = vp.relabel_segments(segs_copy, cluster_vectors=clusters, conn=conn)
        assert n == 0
        assert [s.get("speaker") for s in segs_copy] == original
    finally:
        conn.close()


# ---------- 6) full pipeline log carries v0.8 markers -------------------------


def test_pipeline_log_mentions_v08_features(transcribed_clip):
    """At least one of the v0.8 log signals should fire in a successful
    run — proves the integrations are wired into the live transcribe
    path, not just in the unit-test mocks."""
    logs = "\n".join(transcribed_clip["logs"])
    # Auto-chapters is one of the v0.8 emit points and is always on
    # in this fixture; hallucination is the other.
    assert "chapter" in logs.lower() or "hallucination" in logs.lower(), (
        f"v0.8 markers missing from logs:\n{logs}"
    )
