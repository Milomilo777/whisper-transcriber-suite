# OPENCODE handoff — speaker/signal review (core/voiceprint, diarization, alignment, hallucination, separator)

Branch: `opencode/speaker-signal-review`
Date: 2026-09-20
Scope: `core/diarization.py`, `core/voiceprint.py`, `core/alignment.py`,
`core/hallucination.py`, `core/separator.py` + their tests under `tests/core/`.

## Record correction re: commit ff9dd3f

The supervising session committed this worktree as `ff9dd3f` while this
session was still finishing and its message says the task was killed
"before its final full-suite run and handoff summary". That caveat is
superseded: after the last code edit this session ran
`pyright app core` (0 errors, 0 warnings, 0 informations) and
`python -m pytest tests/ --ignore=tests/smoke -q` (exit 0, no FAILED/ERROR
lines) against exactly the tree in `ff9dd3f`, completed the adversarial
self-critique that produced two follow-up edits (narrowed
`except OSError`, docstring) now included in that commit, and wrote this
file. `ff9dd3f` was already pushed before this handoff commit.

## Real bugs fixed

1. **core/voiceprint.py — dimension-mismatched voices could false-match.**
   `cosine()` returns `0.0` when lengths differ, and `match_vector()` only
   rejected `best_score < threshold`. With `threshold <= 0.0` (an API
   caller / future config value), a candidate enrolled under a different
   embedding model (e.g. 512-d pyannote/embedding row vs a 256-d upgrade)
   was returned as a positive match — misattributing speech to the wrong
   enrolled name, the worst failure this module can have. Fix: skip
   candidates whose vector length differs from the query.
   Test: `test_match_vector_ignores_dimension_mismatched_voices`.
   Inline revert verification: with the skip removed the test fails
   (`EnrolledVoice(name='Alice', vector=[1.0, 0.0])` returned for a 3-d
   query); with it restored, pass. Default-threshold (0.65) behaviour is
   unchanged, so no existing caller semantics shift.

2. **core/voiceprint.py — NaN/Inf embeddings were persisted silently.**
   A non-finite embedding (pyannote on a corrupt/truncated clip) was
   stored in `voices.db` and can never match anything, so enrolment
   looked successful while being permanently dead. Fix: reject non-finite
   vectors at the `enrol_with_vector()` DB gate with `ValueError`.
   Test: `test_enrol_rejects_non_finite_vector`.
   Inline revert verification: removing the guard makes the test fail
   (`DID NOT RAISE`); restoring it passes.

3. **core/alignment.py — dropped segments shifted refined words onto the
   wrong segment.** `_build_whisper_result()` filtered out segments whose
   `text` was not a `str`, but `refine_word_timestamps_in_place()`
   splices stable-ts words back **by index**. One filtered segment
   shifted every later segment's word timings onto its neighbour (silent
   wrong karaoke/word-confidence data). Fix: one payload segment per
   input segment, coercing non-string text to `""`.
   Test: `test_refine_keeps_index_alignment_with_non_string_text`
   (confirmed failing against the pre-fix filter).

4. **core/diarization.py — empty decode reached sherpa-onnx.** A valid
   container with zero audio frames (header-only WAV, video with no audio
   stream) makes ffmpeg exit 0 with empty stdout; `np.frombuffer` then
   produced a zero-length array that `OfflineSpeakerDiarization.process()`
   cannot handle (native raise/crash). Fix: raise the documented
   `DiarizationUnavailable` when zero samples were decoded.
   Test: `test_prepare_audio_raises_on_empty_decode`.

5. **core/separator.py — cache eviction could delete a stem still in
   use.** `prune_cache()` sorted by creation time and evicted purely on
   size; with several concurrent workers, worker B's sweep could delete
   the vocals stem worker A had just written or was about to read
   (`keep` only protects the pruner's own file). Fix: 5-minute in-use
   grace based on file mtime, and cache hits now refresh mtime (LRU), so
   a stem a concurrent worker just resolved is never evicted. Files kept
   by the grace still count toward the budget.
   Tests: `test_prune_cache_keeps_recently_written_stem`,
   `test_separate_vocals_cache_hit_refreshes_mtime`.

6. **core/separator.py — "last resort" returned a path inside the tree
   that `finally:` deletes.** If both `os.replace` and the rescue copy
   failed, `separate_vocals()` returned `found` under the temp dir, which
   the unconditional `shutil.rmtree(out_dir)` then removed — the caller
   got a nonexistent path instead of the module's documented fallback.
   Fix: return the untouched `audio_path` in that case.
   Test: `test_separate_vocals_falls_back_to_input_when_stem_cannot_be_cached`.

## Improvements (smaller, same commits)

- `separate_vocals()` cache-hit check no longer swallows exceptions from
  a caller's `log` callback (only the `exists()`/`stat()` race window is
  guarded); a concurrent prune between the two now falls through to a
  regenerate instead of raising out of `separate_vocals`.
- `prune_cache()` docstring documents the in-use grace.

## No real issues found

`core/hallucination.py`: read line by line, including n-gram recurrence,
VAD-overlap inclusivity, BoH normalisation, and idempotency; no
user-impacting defect found. The aggressive single-word BoH entries
("you", "okay", "um") are deliberate and covered by tests. No change.

## Verification

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`.
- `python -m pytest tests/ --ignore=tests/smoke -q` → exit 0 on the final
  tree (run twice; one early run hit the already-documented intermittent
  Tk-construction flake in `tests/core/test_transcript_viewer.py`, which
  passed in isolation immediately after and on both later full runs —
  same known pattern recorded in `docs/SESSION_HANDOFF_NEXT.md`, unrelated
  to this scope).
- Goal-based, not line-count-based: every code change above has a test
  that was confirmed red against the pre-fix code (voiceprint inline per
  the task's higher-bar requirement; alignment and separator prune
  checked the same way).
- No files outside the listed scope were modified; nothing under
  `.gitignore` was read or touched; master was not touched.
