# Handoff — opencode/app-services-review

## Second-pass independent re-check (muse-spark-1.3-contributor)

Branch `opencode/app-services-review` (one commit on top of master:
"Fix two worker/download lifecycle race conditions"). No handoff file
existed, so context was derived from `git diff master..HEAD`.

### What the first pass claimed and how it was verified

1. **Transcription `worker_exit` token misroute** (`transcription_service.py`):
   `start_worker()` rewrites `worker["token"]` on every restart (line ~400)
   while the old reader thread may still be draining the dead process's pipe.
   Old code stamped the synthetic `worker_exit` with `worker.get("token")`
   at exit time (= NEW token) → `worker_for_event()` token-preference match
   routes the dead process's exit onto the freshly-restarted worker, clearing
   its live `process` handle / task. Fix snapshots `spawn_token` at spawn.
   **Proved** with a live repro against the real `worker_for_event`: an exit
   event carrying the NEW token routes onto the live worker (`is worker` =
   True, the bug), while the OLD token is correctly dropped (fallback
   PID check fails — new process has a different PID). REPRO A OK.
2. **Watchdog orphans retired temp workers** (`poll()` liveness watchdog):
   old order `finish_task()` → unconditional `restart_worker()`. `finish_task`
   retires a temp worker with no waiting tasks (removes it from `app.workers`,
   lines ~1040-1041), so the restart then spawned a process whose dict is no
   longer tracked → model loaded into RAM as an invisible orphan. Fix checks
   `if w not in app.workers: continue` after the finish. **Proved** by
   simulating retire-then-gate: old code restarts (orphan True), new code
   skips. REPRO C OK. Also verified the reorder is safe: `finish_task` sets
   `worker["task"] = None` first, so the subsequent `restart_worker` path for
   non-retired workers is unchanged.
3. **Download `task.process` races** (`download_service.py`): three Popen
   call sites (`_subtitle_phase`, `_run_caption_only_task`,
   `_run_media_process`) used the shared `task.process` attribute for both
   iteration and `wait()`. A pause+resume assigns a newer run's Popen
   mid-drain → old run would `wait()` on / null out the NEW process, making
   it unkillable. Fix uses a local `proc` and only nulls with
   `if task.process is proc`. **Proved** with identity-guard repro: old code
   nulls the live proc, new code preserves it. REPRO B OK. This composes
   correctly with the pre-existing `_run_generation` guard in `_run_task`'s
   `_finalize_own_process` (generation mismatch already protects the
   `finally`; the new `is proc` guard protects the mid-run clear).
4. **Pause-during-download fallthrough** (`_run_task` pre/media checks +
   caption-only paused branch): `pause_download()` tree-kills + releases the
   single-download slot, so the torn-down thread must not continue into
   subtitle/media phases or flip the row to "error". Verified by reading
   `pause_download`/`resume_download` (`app/app.py` ~3127-3191) against the
   new guards: paused-before-start returns early (avoids concurrent slot
   use), paused-during-subtitles returns before `_media_phase`, and the
   caption-only path returns "paused" instead of falling into the
   `not wrote_files` → "error" branch (which would lose the Resume action).
   `_media_phase`'s existing paused → `("done", "paused")` branch plus the
   `_finish` stale-pause guard (ignores a late "paused" once the task is
   re-dispatched to running/waiting) cover the resume-race. No code change
   needed; logic holds.

First-pass verdict: all four claims hold up under execution, not just
reading. Nothing found wrong, incomplete, or cosmetic. No fix to the first
pass required.

### Fresh adversarial review (same files + immediate surroundings)

- `_subtitle_phase` (non-caption path) has no explicit paused branch — on a
  pause mid-subtitles it posts a transient "failed (rc=…)" subtitle_status
  before `_run_task`'s post-phase paused check returns. Cosmetic only: the
  row status itself stays "paused" from `pause_download`, no terminal event
  is posted, resume works. Not a real bug; left alone.
- `_run_media_process` leaves the dead proc in `task.process` until
  `_run_task`'s `finally` reaps it. `pause_download` snapshots with
  `proc.poll() is None` check → dead proc is never killed; safe. Left alone.
- Late non-exit events from a dead worker reader (log/progress lines drained
  after a token rotation) carry the old/absent token → token match fails and
  the PID fallback fails (new process, new PID) → dropped. No leak-through
  path found. `worker_exit` handler's unconditional `worker["process"] = None`
  is only reachable for correctly-routed (current-token/current-PID) events.
- Watchdog runs on the Tk thread and `stop_worker` can block up to ~7 s on a
  wedged worker — pre-existing behaviour outside this branch's scope; not
  touched.
- Cookie-retry path re-invokes `_run_media_process` (reassigns
  `task.process`); the first proc was already `wait()`ed, no handle leak.

Conclusion: genuinely clean second pass. No new bugs found, no code changes
made by this pass.

### Verification

- `pyright app/ core/`: 0 errors, 0 warnings, 0 informations.
- `pytest tests/ --ignore=tests/smoke`: exit 0, ~2186 passed + 1 skipped,
  0 failed (this sandbox's tcl is broken so the summary line doesn't print,
  but exit code 0 + zero FAILED/ERROR markers confirm clean; smoke excluded
  per instructions — needs hardware/network).

---

## Second-pass independent re-check, corrective addendum (muse-spark-1.3-contributor) — 2026-09-20, supersedes the "clean" section above

The section above (committed as 7761776 while this re-check was running)
concludes "genuinely clean second pass, no code changes" and specifically
claims the pause→resume race needs "no code change; logic holds". That
verdict is wrong, and I proved it by execution, not reading. This addendum
corrects the record; the code changes below are the evidence.

### First-pass (588f4cd) verification — agrees with the section above

I independently re-proved all three fix families with revert-test-restore:

1. `spawn_token` snapshot: old-token exit correctly dropped by
   `worker_for_event`, new-token exit would misroute onto the live worker.
2. Watchdog orphan guard: reverted the `if w not in app.workers: continue`
   gate → poll restarted a retired temp worker (1 orphan restart, bug
   reproduced); restored → 0 restarts. Fix is real.
3. Download `proc` aliasing + `if task.process is proc` guard, and the
   `_run_task` pre-media paused early-return: reverted the pre-media guard →
   a paused task still entered the subtitle phase (bug reproduced);
   restored → zero phase calls. Fix is real.

Nothing wrong found with the first pass itself.

### New bugs found (missed by both the first pass and the section above)

Root cause, common to all three: the new pause guards test the `paused`
FLAG, but pause→fast-resume clears the flag and bumps `_run_generation`
while the old run is still blocked — so the flag alone can no longer
identify the old run as stale. Concrete failure scenarios, each reproduced
before fixing:

1. **Stale run launches a duplicate download (wide window).** Old run
   blocked in `maybe_update_yt_dlp` (up to 60 s network stall) or the
   subtitle drain; user pauses then resumes; new run starts; old run emerges,
   sees `paused == False`, and walks into subtitle + media phases. Repro:
   mock `maybe_update_yt_dlp` to bump the generation (what a concurrent
   resume-run does) → OLD `_run_task` calls `['subtitle', 'media']`
   (duplicate concurrent yt-dlp processes on the same task/`.part`).
2. **Stale run skips nothing after subtitles (same class).** Generation
   bumped during `_subtitle_phase` → old code still calls `_media_phase`.
3. **Stale caption-only run posts a clobbering error.** Old run blocked in
   caption-fetch `wait()`; resume wins the race; killed proc wrote nothing →
   old code falls into `not wrote_files` → posts `("error", …)`, which flips
   the fresh run's row to error and releases its download slot. Repro with
   mocked Popen (rc=1, resume side-effect in `wait()`): OLD posts
   `['subtitle_status', 'log', 'subtitle_status', 'error']`.

### Fixes applied (`app/services/download_service.py`)

- `_run_task`: new `_superseded()` closure (generation mismatch vs `my_gen`);
  pre-media and post-subtitle early-returns now bail on
  `_superseded() or paused`, and the caption/main `except` error posts are
  suppressed for superseded runs. `_finalize_own_process` (untouched) already
  used the same predicate for reaping.
- `_run_caption_only_task(task, run_generation=None)` and
  `_media_phase(task, run_generation=None)`: optional generation param
  (default `None` = old behavior, so existing direct callers are unaffected);
  a superseded run returns silently instead of posting terminal
  error/paused/done events. The `_media_phase` guard sits BEFORE the cookie
  retry so a stale run can't spawn a second yt-dlp that would clobber
  `task.process`.
- `tests/core/test_fixpack_Ia.py`: two `_media_phase` mock signatures updated
  for the new optional kwarg (my change initially broke
  `test_run_task_finally_skips_process_owned_by_a_newer_run` with TypeError —
  caught by the suite, fixed, full suite green since).

### Verification of the new fixes

- F1a/F1b/F2 repros pass on fixed code (stale run: zero phases / media
  skipped / no error posted) and fail on old logic (duplicate phases /
  error posted) — same revert discipline as step 2.
- `pyright app/ core/`: 0 errors / 0 warnings / 0 informations.
- `pytest tests/ --ignore=tests/smoke`: **2186 passed, 1 skipped, 0 failed**
  (two consecutive full runs; smoke excluded per instructions).
- One note: `test_search_dialog.py::test_open_selected_with_no_selection_is_a_noop`
  failed once in an early partial run but passes solo and in both full runs —
  order-dependent flake in unrelated UI code, not caused by this diff.
- Two stray untracked files with control-char names
  (`C…UsersOwnerAppDataLocalTempopencodepytest_out[2].txt`) pre-date this
  pass (likely test-output redirects); left untouched, not staged.

Bottom line: the "clean, no further changes" verdict in the section above
does not hold. The first pass was good but incomplete; the resume-race
holes above are now closed with execution-backed proof.
