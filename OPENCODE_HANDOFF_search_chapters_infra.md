# Search / chapters / infra hardening review — handoff

Branch: `opencode/search-chapters-infra-review` (worktree `wt-search-chapters-infra`).
Scope: `core/search.py`, `core/chapters.py`, `core/_errors.py`, `core/_proc.py`,
`core/_threads.py`, `core/paths.py`, `core/logging_setup.py` and their tests.

Gates: `python -m pyright app core` -> `0 errors, 0 warnings, 0 informations`;
`python -m pytest tests/ --ignore=tests/smoke -q` -> exit 0 (fully green).

## Real bugs fixed

1. `core/search.py` — every FTS hit was scored exactly `1.0`.
   FTS5's `bm25()` is smaller-is-better **and negative**, but the conversion used
   `1.0 / (1.0 + max(0.0, rank))`, so the clamp turned every rank into `0`. Fixed to a
   strictly decreasing logistic map (`1 / (1 + exp(rank))`, clamped only against
   `math.exp` overflow) so scores differentiate and stay in `(0, 1)`.
   Proof: `test_search_fts_score_varies_with_match_quality` — pre-fix both hits scored
   `1.0` and `len(set(scores)) > 1` failed; post-fix scores differ and are ordered with
   the better match first.

2. `core/search.py` — multi-word queries were exact phrases, not AND.
   `_fts_query` quoted the whole query (`"cat dog"`), so typing two words returned
   nothing unless they were adjacent. Now each whitespace token is quoted separately
   and joined with a space (FTS5 implicit AND), preserving the punctuation/operator
   safety the quoting was added for.
   Proof: `test_search_multiword_query_matches_non_adjacent_words` — pre-fix
   `search("cat dog")` returned 0 hits; post-fix returns the one segment containing both.

3. `core/search.py` — a transient read failure wiped a file's index.
   `_read_segments` mapped `OSError` (file briefly locked, AV scanner, network hiccup)
   to `[]` exactly like "no segments"; `index_file` then deleted the FTS rows and the
   embeddings and marked the file up to date, so the transcript silently vanished from
   search until its mtime changed. `OSError` now returns a distinct `None`, and
   `index_file` keeps the existing rows and leaves the file unmarked for retry.
   Proof: `test_index_file_io_error_keeps_existing_index` — pre-fix the previously
   indexed row was gone; post-fix it survives the failed read.

4. `core/search.py` — semantic failure no longer breaks the documented fallback.
   `search()` only fell back to FTS when the semantic engine returned *no hits*; if the
   embedder raised (model weights missing/corrupt, `encode()` error) the exception
   propagated to the caller, contradicting the module docstring's "falls back to FTS5
   transparently". The semantic call is now wrapped, logged at WARNING, and FTS is used.
   Proof: `test_search_falls_back_to_fts_when_semantic_embedder_fails` — pre-fix the
   `RuntimeError` escaped `search()`; post-fix the FTS hit is returned.

5. `core/search.py` — an FTS-only index was never backfilled with embeddings.
   `index_file(embedder=...)` short-circuited on the mtime/size cache, so a file first
   indexed without the semantic layer (dependency installed later) never got vectors and
   semantic search stayed permanently empty for it. A missing-embeddings check now
   triggers the rebuild.
   Proof: `test_index_with_embedder_backfills_after_fts_only_index` — pre-fix the second
   call returned 0 and the `embeddings` table stayed empty; post-fix it is populated.

6. `core/search.py` — one bad transcript aborted the whole reindex walk.
   `reindex_all_history` called `index_file` with no per-file guard, so the first
   exception (malformed segment data, DB error) stopped every later transcript from
   being indexed. Each file is now isolated with a logged warning.
   Proof: `test_reindex_all_history_isolates_one_bad_file` — pre-fix the injected
   `TypeError` propagated and the two good files were not indexed; post-fix both are.

## Hardening / improvements

7. `core/_proc.py` — refuse to `killpg` the app's own process group.
   All current call sites spawn with `new_session_kwargs()`, but if a future call site
   skips it (or a recycled PID resolves into this process's group), `killpg` would
   SIGTERM/SIGKILL the app itself. The POSIX branch now checks `pgid == os.getpgid(0)`
   and falls back to the parent-only signal instead of signalling the group.
   Proof: `test_kill_tree_refuses_to_signal_its_own_process_group` — pre-fix the recorder
   captured `(own_pgid, SIGKILL)`; post-fix no `killpg` call is made and `process.kill()`
   still runs. The tree-kill contract for correctly-spawned children is unchanged
   (`test_proc.py`, `test_fixpack_proc_ckpt.py`, `test_fixpack_J.py` stay green).

8. `core/logging_setup.py` — prune stale per-process worker logs.
   Every worker / voice-clone worker creates its own `worker-<pid>.log` (deliberate —
   cross-process rotation is broken on Windows; see the module docstring) and nothing
   ever removed them, so the log directory grew one file plus rotations per worker
   forever. `setup_logging` now deletes worker-named files older than 14 days while
   always keeping the newest 10; `app.log` and unrelated files are untouched and every
   failure is swallowed (a locked file is skipped).
   Proof: `test_prune_removes_only_stale_worker_logs` — pre-fix the stale logs survived;
   post-fix they are gone while recent worker logs, `app.log` and `notes.log` remain.
   `test_prune_keeps_old_worker_logs_inside_the_keep_window` is the over-pruning guard
   (passes before and after by design).

## Read closely, found clean

- `core/chapters.py` — empty input, single-segment / extremely short input, missing
  `end` keys, empty-text segments, out-of-range boundaries and the LLM fallbacks are all
  handled. No bug found (consistent with the 2026-08-15 audit's conclusion).
- `core/_errors.py` — `attempts < 1` rejected, retries bounded by `attempts`, retry
  filter honoured, exhaustion re-raises and logs; nothing swallowed silently.
- `core/_threads.py` — only `Exception` is contained (BaseException still propagates),
  failure is logged with `exc_info`; fine.
- `core/paths.py` — onefile/onedir/source resolution order is right (PyInstaller sets
  `_MEIPASS` in onedir too), missing `bin/` falls back to the bare PATH name, and
  `_ensure_executable` never raises. Fine.

## Known residual gaps (not fixed, deliberately)

- Embeddings carry no model identity: a same-dimension model swap leaves stale vectors
  that are still scored. The existing dimension-mismatch skip prevents bogus scores for
  a different dimension, but a forced reindex on model change would need model/dim
  metadata in `indexed_files` — a schema/design change, out of scope here.
- `_open_db` still assumes the sqlite build has FTS5 (documented as "always available");
  no fallback engine added.

---

## Independent verification pass (second review instance, same scope)

A second, independently-launched pass over this same scope (a retry
instance started while the first was still finishing) re-derived every
change above from scratch. No additional code change was needed: every
finding reproduced, and nothing new survived adversarial review.

**Proof each fix addresses a real bug.** Restored the pre-fix file blobs
(`git checkout 670f558 -- core/search.py core/_proc.py
core/logging_setup.py`), ran the regression tests added above, then
restored HEAD and confirmed the tree clean:

- 8 of the 9 new tests fail on the pre-fix code:
  `test_index_file_io_error_keeps_existing_index`,
  `test_search_multiword_query_matches_non_adjacent_words`,
  `test_search_fts_score_varies_with_match_quality`,
  `test_search_falls_back_to_fts_when_semantic_embedder_fails`,
  `test_index_with_embedder_backfills_after_fts_only_index`,
  `test_reindex_all_history_isolates_one_bad_file`,
  `test_kill_tree_refuses_to_signal_its_own_process_group`,
  `test_prune_removes_only_stale_worker_logs`.
  The ninth (`test_prune_keeps_old_worker_logs_inside_the_keep_window`) is
  the over-pruning control and passes before and after by design.
- All pass on the committed code.

Also confirmed directly against a real sqlite build (not just via the
tests): FTS5 `bm25()` returns negative ranks, so the old
`max(0.0, rank)` truly pinned every hit to 1.0; and for non-adjacent
words, `MATCH '"cat dog"'` (old whole-query phrase quoting) returns zero
rows while `MATCH '"cat" "dog"'` (new per-token implicit AND) finds them.

**Re-read for further issues — nothing else fixed:**
- `core/chapters.py` — re-ran empty input, single-segment, zero-duration,
  missing-`end`, all-empty-text and out-of-range-boundary inputs: one
  chapter for any non-empty input, `[]` for empty, titles never blank.
  Clean (matches both earlier audits).
- `core/_errors.py` / `core/_threads.py` — still no call sites in `app/`
  or `core/` (additive helpers), retry loop bounded by `attempts`,
  `retry_on` honoured, every failure logged, exhaustion re-raises. Clean.
- `core/paths.py` — source/onefile/onedir resolution and the bare-name
  PATH fallback behave as documented in this worktree. Clean.

**One residual note, deliberately not changed:** `index_file(...,
embedder=...)` backfills embeddings for FTS-only files, but a transcript
whose segments all have empty text can never gain embeddings and so is
re-walked on every semantic reindex. No shipped caller passes an
`embedder` (`app/dialogs/search_dialog.py` calls `reindex_all_history()`
keyword-only), so there is no user-visible cost today; recording model
or "embedding complete" metadata in `indexed_files` would be the schema
change that makes it exact.

Gates re-run on the committed tree by this pass: `pyright app core` ->
`0 errors, 0 warnings, 0 informations`; `python -m pytest tests/
--ignore=tests/smoke -q` -> exit 0 (fully green).

---

## Second-pass independent re-check (muse-spark-1.3-contributor)

**Step 2 — verified 3 first-pass fixes by revert-and-fail (each reverted
surgically on a scratch copy, relevant test shown to fail, file restored,
test shown to pass again; tree confirmed clean via `git status` after):**

- Score fix (`max(0.0, rank)` -> logistic): reverted the one score line,
  `test_search_fts_score_varies_with_match_quality` FAILED; restored,
  passed. Also proved directly against real sqlite: the two `bm25()` ranks
  are `-1.44e-06` / `-7.65e-07`, so the old map pinned both to exactly
  `1.0` while the new map gives distinct ordered scores.
- Multi-word AND (whole-query phrase quoting -> per-token implicit AND):
  reverted `_fts_match_query` to phrase quoting,
  `test_search_multiword_query_matches_non_adjacent_words` FAILED;
  restored, passed. Direct sqlite proof: `MATCH '"cat dog"'` returns 0
  rows, `MATCH '"cat" "dog"'` finds the segment.
- I/O-error guard (`OSError -> []` -> `OSError -> None` + skip delete):
  reverted just the `return None` to `return []`,
  `test_index_file_io_error_keeps_existing_index` FAILED at the
  "must not delete existing index rows" assertion; restored, passed.

The remaining first-pass claims (semantic-fallback wrap, embedding
backfill, reindex isolation, killpg self-group guard, worker-log pruning)
were verified by reading the diff plus the passing regression tests, not
by individual reverts — the three reverts above cover the highest-risk
semantic changes.

**Step 3 — fresh adversarial review, one real bug found and fixed:**

- `_prune_worker_logs` glob `*worker-*.log*` deleted unrelated user files
  that merely contain "worker-". Concrete repro (run pre-fix): drop a
  30-day-old `reworker-output.log` into the log dir alongside 10 recent
  worker logs -> `_prune_worker_logs` deleted it (`survives: False`).
  Only two producers ever write worker logs — `worker-<pid>.log`
  (`worker_log_filename()`, used by `core/worker.py`) and
  `voiceclone-worker-<pid>.log` (`core/voice_clone_worker.py:84`) — and
  the existing test explicitly requires both to be pruned, so the glob
  was replaced with exactly those two patterns
  (`_WORKER_LOG_GLOBS = ("worker-*.log*", "voiceclone-worker-*.log*")`).
  Post-fix the same repro keeps `reworker-output.log` while still pruning
  stale `worker-900.log`, `worker-900.log.1` and
  `voiceclone-worker-901.log`. Regression test added:
  `test_prune_ignores_unrelated_file_containing_worker`.
- Checked and found clean (no change): `heuristic_title` /
  `detect_chapter_boundaries` edge inputs, `_errors` retry bounds,
  `_threads` BaseException propagation, `paths` resolution order,
  `_proc` guard (falls through to parent-only signal correctly),
  `_fts_match_query` against 35 adversarial queries (`"`, `*`, `OR`,
  `NEAR(`, `-`, parens/brackets, quotes-only, 5000-char token,
  unicode arrows — zero `OperationalError`s), `reindex_all_history`
  atomicity (mid-loop embedder failure rolls back via `with conn:`,
  then per-file guard logs and continues), `_prune_worker_logs`
  TOCTOU (stat-inside-`try` already converts a concurrent delete into a
  skip). Residuals from the first pass (no model identity on embeddings;
  empty-text transcripts re-walked on semantic passes — no shipped caller
  passes an `embedder`, confirmed by grep) stay documented, not fixed.

**Gates on final tree:** `python -m pyright app core` ->
`0 errors, 0 warnings, 0 informations`;
`python -m pytest tests/ --ignore=tests/smoke` ->
`2196 passed, 1 skipped` (skip pre-existing).
