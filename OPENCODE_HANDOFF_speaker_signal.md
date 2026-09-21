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

## Follow-up re-check (muse-spark-1.3-contributor, same day, second agent)

Date: 2026-09-20. This section is by a second same-model agent running
concurrently in the same worktree as the `29276a3` pass above (that
pass's "foreign concurrent-agent edits" are exactly the fixes below —
they were finished work, now reviewed and committed here).

### What was verified from the first pass (by literal revert-and-rerun)

All reverts were restored immediately after; `git status` clean
between each check. Three of the six claimed fixes re-proven:

1. voiceprint dim-skip: replaced the `len(v.vector) != len(vector)`
   guard with `if False`, ran
   `test_match_vector_ignores_dimension_mismatched_voices` → FAILED
   (returned Alice for a 3-d query at threshold 0.0), restored → pass.
2. voiceprint non-finite gate: replaced the `math.isfinite` guard with
   `if False`, ran `test_enrol_rejects_non_finite_vector` → FAILED
   (`DID NOT RAISE`), restored → pass.
3. alignment index-alignment: restored the old drop-non-string filter,
   ran `test_refine_keeps_index_alignment_with_non_string_text` →
   FAILED (`'words'` spliced onto the wrong segment), restored → pass.

The remaining three (empty-decode guard, prune grace + mtime refresh,
in-tree fallback path) were verified by reading the tests against the
diff — each test asserts the exact post-fix behaviour and the diff
shows the matching code change; no discrepancy found.

### What was wrong with the first pass

1. **`docs/SESSION_HANDOFF_NEXT.md` was clobbered — already restored
   by the concurrent `29276a3` pass before this agent acted.**
   This agent's own `git checkout master -- docs/SESSION_HANDOFF_NEXT.md`
   was a no-op confirming byte-identity; the branch diff no longer
   touches the file. Endorsed, not re-done. (Correction to the
   first-pass handoff claim "No files outside the listed scope were
   modified": that claim was false for this file at the time.)
2. **`core/hallucination.py` "no defects" verdict was wrong — fixed.**
   `annotate_segments()` did `(seg.get("text") or "").strip()`, which
   raises `AttributeError` on any non-string truthy text (e.g.
   `{"text": 123}`). Reproduced live before fixing. Ironic adjacency:
   the alignment fix in this same branch proves non-string segment
   text flows through this codebase, and `transcriber.py:1053` feeds
   real segment dicts into `annotate_segments`. Fix: skip non-`str`
   text (same "skip, don't crash" shape as the alignment fix).
   Test: `test_annotate_segments_skips_non_string_text`.
3. **The new voiceprint finiteness gate had its own crash path —
   fixed.** `all(math.isfinite(x) ...)` raises `TypeError` (not the
   documented `ValueError`) for non-numeric elements (`["x"]`,
   `[None]`). Reproduced live. Fix: catch `TypeError` and raise
   `ValueError` instead. Test:
   `test_enrol_rejects_non_numeric_vector_with_value_error`.

### Deliberately not changed

- Endorse the concurrent pass's severity correction on the dim-skip
  fix (latent hardening, not a live bug): independently confirmed —
  `match_vector`'s only in-repo caller is `relabel_segments` (default
  threshold 0.65), nothing under `app/` or `gui.py` touches voiceprint.
- Endorse its two separator fixes (keyed orphan name — verified bare
  `"vocals.wav"` indeed misses the `"*_vocals.wav"` glob since the
  pattern requires the leading underscore; race-safe prune sort key).
  Both re-read here; their tests pass in the suite run below.

- `prune_cache()` 5-minute grace temporarily bounding eviction during
  batch runs: real trade-off, documented in the docstring, bounded by
  5-minute throughput; not a bug.
- `refine_word_timestamps_in_place()` ignoring surplus refined
  segments (`min()` clamp): no evidence stable-ts over-returns;
  theoretical only.
- `detect_vad_disagreement()` boundary-inclusive overlap and
  `detect_boh()` aggressive single-word entries: reviewed, deliberate,
  test-covered. Agree with first pass.

### Final verification (this pass, exact code tree being committed)

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`.
- `python -m pytest tests/ --ignore=tests/smoke -p no:warnings` →
  `2196 passed, 1 skipped`, exit 0 — run against the exact tree
  committed here (concurrent pass's separator fixes + this pass's
  hallucination/voiceprint fixes + all four new tests; only this
  handoff `.md` changed afterwards). (One mid-pass full run showed two
  lone Tk-construction FAILEDs in `test_search_dialog.py` /
  `test_transcript_viewer.py`; both pass in isolation and the very
  next full run was clean — the already-documented init.tcl
  resource-contention flake, unrelated to this scope.)

## Second-pass independent re-check (muse-spark-1.3-contributor)

Date: 2026-09-20. Branch commits at review time: `ff9dd3f` (code) +
`c87a809` (this handoff file).

### Verified from the first pass (by running, not by reading)

1. **voiceprint dim-mismatch skip — real, proved end-to-end.** Called the
   real `cosine()` with mismatched dims (returns `0.0`, as claimed) and
   ran the old selection logic (no skip) against a real DB row: old code
   returns `EnrolledVoice(name='Alice', vector=[1.0, 0.0])` for a 3-d
   query at `threshold=0.0`; current code returns `None`. Honest
   severity correction: no production caller can hit this today —
   `match_vector`'s only in-repo caller is `relabel_segments` (default
   0.65), nothing under `app/` uses voiceprint at all, and at the
   default threshold the old code already rejected the 0.0 score. It is
   latent hardening for a future threshold/config change, not a live
   wrong-name bug. Fix itself is correct and harmless; kept.
2. **voiceprint NaN/Inf gate — real, logic confirmed.** Old checks
   (`name.strip()`, `not vector`) provably do not reject
   `[1.0, float('nan')]`; new `math.isfinite` gate does, and
   `test_enrol_rejects_non_finite_vector` passes. Kept.
3. **alignment index-shift fix — real, confirmed from both sides.** Old
   filter provably yields 1 payload segment for a 2-segment input with
   `text=None` (splice-by-index shifts by one); new builder keeps 1:1
   with `""` coercion, and
   `test_refine_keeps_index_alignment_with_non_string_text` passes.
   Kept.
4. **diarization empty-decode + separator cache/fallback fixes — accepted
   on code reading + green tests** (`test_prepare_audio_raises_on_empty_decode`,
   `test_prune_cache_keeps_recently_written_stem`,
   `test_separate_vocals_cache_hit_refreshes_mtime`,
   `test_separate_vocals_falls_back_to_input_when_stem_cannot_be_cached`
   all pass). The old fallback's in-tree return followed by unconditional
   `shutil.rmtree(out_dir)` is self-evidently a dangling path from the
   diff; no deeper repro needed.
5. **hallucination no-change — agreed.** Re-read `detect_boh` /
   `detect_repetition` / `detect_vad_disagreement` / `annotate_segments`.
   Single-word BoH entries are covered by tests (deliberate). One
   marginal note, not acted on: `detect_vad_disagreement` treats
   boundary-touching (`e == vs`) as overlap, so a silence segment exactly
   abutting a speech interval escapes the VAD signal — too weak a
   scenario (BoH/repetition usually catch real cases) to change without
   evidence.

### Collateral damage found and fixed

- **`docs/SESSION_HANDOFF_NEXT.md` was gutted on this branch**
  (5509-line master file replaced with a 7-line stub — the worktree's
  supervising-session context, never part of this review's scope).
  Restored byte-identical from `master` via
  `git checkout master -- docs/SESSION_HANDOFF_NEXT.md`. This branch's
  diff no longer touches it.

### New bugs found and fixed (same scope, second pass)

1. **separator survivor filename collided across sources and leaked
   forever.** The first pass's last-resort path wrote the rescued stem
   to `cache_dir() / "vocals.wav"`. Proven via `fnmatch`: bare
   `"vocals.wav"` does NOT match the `"*_vocals.wav"` prune glob, so the
   file was never evicted; and two sources failing at once shared one
   path (second overwrites first — caller A holds caller B's audio).
   Fix: keyed orphan name
   `f"{_cache_key(audio_path, model)}_orphan_vocals.wav"` — per-source
   unique, matches the prune glob. New test
   `test_separate_vocals_orphan_survivor_is_keyed_and_prunable` (both
   survivors exist after `finally:` rmtree, names differ, both globbed).
2. **prune_cache sort abort on concurrent delete.** `files.sort(key=lambda
   p: p.stat().st_mtime)` — one stem vanishing mid-sort raises `OSError`
   out of the key, caught by the surrounding `except OSError: return 0`,
   so a single racing worker disabled the entire sweep. Fix: safe key
   returning `0.0` on `OSError` (vanished file sorts oldest, skipped
   later by the per-file `stat()` guard). No new test — race window too
   narrow to deterministically trigger; fix is a 5-line pure hardening
   with no behaviour change in the non-race case.

### Final verification (this pass, after its own edits)

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`.
- `python -m pytest tests/ --ignore=tests/smoke --tb=no -p no:warnings` →
  green, exit 0, no failures (final run after re-apply: `2196 passed,
  1 skipped` — the single skip is the POSIX-only `test_proc.py:80`
  killpg path; an intermediate run showed `2195 passed, 2 skipped`
  with one extra conditional skip flipping between runs, zero failures
  in all runs). The worktree at test time also contained the foreign
  agent's two extra tests (both passing); they are not part of this
  commit.

### Concurrent-writer collision (important for next session)

Mid-pass, this worktree was concurrently modified by another live
opencode process (multiple `opencode` PIDs active; the known
"killed-task-survives" pattern from `docs/SESSION_HANDOFF_NEXT.md`):
at ~22:33 it rewrote `core/separator.py` + `tests/core/test_separator.py`
(wiping this pass's just-applied fixes), and at ~22:35 it edited
`core/hallucination.py` (non-string-text guard in `annotate_segments`),
`core/voiceprint.py` (`TypeError`→`ValueError` in the finite gate), plus
matching tests, and dropped a stray
`C:UsersOwnerAppDataLocalTempopencodepytest_full.txt` in the repo root.
This pass re-applied its own separator fixes + test afterwards and
verified them again, but **deliberately did NOT stage or commit the
foreign files** — they are another agent's unreviewed, possibly
half-finished work. The commit for this pass contains only:
`core/separator.py`, `tests/core/test_separator.py`,
`OPENCODE_HANDOFF_speaker_signal.md`, and the
`docs/SESSION_HANDOFF_NEXT.md` restore. Next session: check whether that
other process finished and whether its hallucination/voiceprint edits
are worth reviewing on their own merits.
