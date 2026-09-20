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
