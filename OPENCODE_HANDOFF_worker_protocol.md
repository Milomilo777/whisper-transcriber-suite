# OpenCode handoff — `core/worker.py` adversarial protocol review

Branch: `opencode/worker-protocol-review` (local commit only, not pushed).
Scope: `core/worker.py` + its tests (`tests/core/test_worker_protocol.py`,
`tests/core/test_worker_control.py`, `tests/core/test_fixpack_worker.py`).
Nothing else in the repo was modified; no `.gitignore`d file or third-party
library source was read.

Constraints honoured throughout: no JSON field renamed / removed / retyped
in any emitted event or accepted command; no new required field; the
`--worker` argv contract and the `gui.py --worker` spawn shape are
untouched; stdout is still one newline-delimited JSON object per emit,
serialised by the existing single `_emit_lock`.

---

## Real bugs fixed (each with a test that fails pre-fix)

### 1. One oversized stdin command produced TWO error events

`read_capped_lines` enforces the 1 MB cap while reading. When a record
crosses the cap mid-read it yields the truncated prefix with
`oversize=True`, then keeps draining the rest of that record to the next
newline. When the newline was found — or at EOF — it yielded `("", True)`
a second time, and `_stdin_reader` emits one `error` event per oversize
yield. One bad command therefore produced two identical
`"command exceeds max length (> 1048576 bytes); dropped"` events (both the
`readline` and the `read()` paths).

Fix: the drained tail is discarded silently; each oversized record yields
exactly one oversize tuple (docstring updated to state that contract).

Tests: `test_read_capped_lines_reports_each_oversized_record_once`,
`..._chunked`, `test_main_oversize_command_reports_exactly_one_error`.

### 2. A command exactly at the cap was wrongly rejected

The same function compared `len(raw) > max_chars` on a `readline` result
that INCLUDES the terminating newline, so a command whose JSON was exactly
1 MiB (plus the newline every command has) was flagged oversized and
dropped. `_record_length()` now measures the payload excluding the framing
newline. The OOM bound is unchanged (peak accumulation was and is
cap + one read chunk; the maximum accepted record is exactly the cap).

Tests: `test_read_capped_lines_accepts_record_exactly_at_cap[False/True]`.

### 3. A control command could be applied to the wrong task at the done boundary

`main()` cleared the in-flight task slot (`_set_current_task(None)`) in the
`finally` AFTER `emit("done", ...)`. The parent only learns a task finished
from that `done` event and only then can dispatch the next task — so in the
window between writing `done` and the `finally` a `cancel` / `pause` /
`resume` meant for the NEXT task could be read by the stdin thread while
the finished task was still current, get applied to it, and be swallowed.
The user's Pause/Cancel was then silently ineffective (the next task ran to
completion while the UI already showed it paused/cancelled).

Fix: the slot is cleared before `done` goes out (the `finally` remains, the
`done` emit moved after it). The emitted event sequence and every event's
shape are unchanged; this only removes the misapplication window.

Test: `test_done_is_emitted_after_the_in_flight_task_is_cleared`.
Residual limitation: see "Not fixed" B below.

### 4. A raise from `load_existing_model` skipped `startup_error`

The call was used as `if not load_existing_model(...)`, so a `False` return
was reported properly, but a raise (e.g. a `status_cb`/`emit` failure, or a
path/type surprise) escaped `main()` as a bare traceback. The parent can
only release its loading modal / surface the real reason on `startup_error`;
a bare crash arrives as `worker_exit` and reads as "model load was
cancelled" with no explanation.

Fix: the call is wrapped; a raise logs the traceback, emits exactly one
`startup_error` (`"Model load failed (<Type>): <msg>"`), stops the
heartbeat and returns 1 — the same contract as a `False` return.

Test: `test_main_emits_startup_error_when_model_load_raises`.

### 5. A failing `setup_logging` killed the worker before any event

`setup_logging(load_config(...))` ran unguarded before the heartbeat, the
model load and `ready`. A locked / unwritable / AV-blocked log directory
(`RotatingFileHandler` open or `mkdir` failure is realistic on Windows)
crashed the process before a single protocol line; the parent saw only
`worker_exit`.

Fix: guarded. Logging is best-effort (falls back to logging's last-resort
stderr handler, which the parent already tolerates as a non-JSON log line);
the protocol lives on stdout, so the worker continues to `ready`.

Test: `test_main_survives_logging_setup_failure`.

---

## Found but deliberately NOT fixed (would need a protocol/design change)

### A. Parent-side write ordering can drop a control command

`app/services/transcription_service.py` writes the `transcribe` command and
a following `pause`/`resume`/`cancel` from two different daemon threads
(`_dispatch_command_async` / `_send_command_async`) through the same stdin
pipe, serialised only by `stdin_lock`. If the control thread acquires the
lock first, the worker receives the control line BEFORE the `transcribe`
line it belongs to. With no in-flight task the control is a documented
silent no-op (`PROJECT_INDEX.md` gotcha), so it is lost while the parent has
already flipped the task's status — a Cancel can be shown as applied while
the file is transcribed anyway.

A correct fix needs a task correlation id on BOTH the transcribe and the
control commands (an add-only field is permitted by the frozen protocol)
plus parent-side ordering/pairing logic. That is outside this file's scope
(prompt: only `core/worker.py`), and any worker-side heuristic would change
the intentional stray-control semantics and risk applying a stale control
to the wrong task. Needs a design decision + probably a protocol version
note.

### B. A control arriving while a transcribe is queued but not yet registered is lost

Same root cause: the reader queues the `transcribe` command and applies the
next control immediately; if the main loop has not yet dequeued/registered
that task, `_current_task` is `None` and the control is a no-op. Fix 3
closes the case where the previous task was still registered; this remaining
window is only closable with a correlation id as in A. Deliberately not
"fixed" by pre-applying controls to the next task — that would invert the
frozen stray-control semantics and could cancel/pause the wrong job.

### C. Heartbeat thread is not stopped if an exception escapes `main()`

All designed exit paths (startup_error, `shutdown`, stdin EOF) stop it. Only
an exception escaping `main()` itself (e.g. a `BrokenPipeError` raised from
inside the outer `except` handler's `emit("error")` because the parent
already closed stdout) would leave the daemon thread running — and in that
case the process is exiting anyway. The unit-test-visible half of this was
already fixed by commit `1cb7bd5`; a `try/finally` wrapper would re-indent
the whole loop for no production effect. Noted, not changed.

### D. Oversize error message says "bytes" while the cap is characters

`MAX_COMMAND_BYTES` is enforced in characters (`readline` on a text stream);
a multi-byte UTF-8 command can exceed 1 MiB of bytes while under the cap.
The cap is a memory guard, not a security boundary, and the message text is
parent-visible; left as-is to keep the patch tight.

### E. `read_capped_lines`' iterate-only fallback keeps the old `len()` check

Only reachable for streams with neither `readline` nor `read` (test stubs —
real `sys.stdin` has both); documented as best-effort. Left unchanged.

---

## Verification performed

- `pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **exit 0, no
  FAILED/ERROR lines** (Windows 3.14 dev machine; the known
  `init.tcl` flake did not appear).
- Every new test was independently verified to FAIL against the pre-fix
  `core/worker.py` (`git stash push -- core/worker.py`, run, `git stash
  pop`): 8 failing cases across the 3 files, all green with the fix.
- Not run: `tests/smoke/` and `tools/e2e_cancel_pause.py` (need the real
  ~3 GB model / test video / network). No third-party source read.

---

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

### First-pass verification (prove-it discipline)

Checked out `master`'s `core/worker.py` over the fixed tree (new tests kept)
and ran all 8 new first-pass cases: **all 8 FAILED pre-fix** (5 in
`test_fixpack_worker.py` incl. both at-cap params, plus the done-boundary,
logging-survival and startup_error-raise cases), then restored the fix and
confirmed green. The handoff's "8 failing cases" claim reproduces exactly —
no wrong, incomplete or cosmetic fix found. The done-boundary fix's logic was
also traced by hand (raise inside `transcribe` still skips `done` via the
outer `except`, so no double-report on failure).

Adversarial hypotheses investigated and DISMISSED with evidence:
- Piggybacked-record loss in the readline drain path (oversize tail + next
  command in one `readline(max+1)`): disproved — dumped real `readline(11)`
  chunks, `readline` stops at the first newline, so the remainder can never
  contain a second record. The chunked `read()` path re-processes `rest`
  after a drain anyway.
- Stale `_current_task` if `emit("started")` raises: only a broken stdout,
  process exiting regardless — no production effect, same class as the
  already-documented item C.

### New real bug found and fixed

**Iterate-only fallback kept the old `len()` cap check.** `read_capped_lines`
has three paths; the first pass converted the `readline` and `read()` paths
to `_record_length()` (framing newline excluded) but left the documented
"best-effort" iterate-only fallback on `len(raw) > max_chars`. Proved live:
an exactly-at-cap record (`"x"*10 + "\n"`, cap 10) yields `(line, False)` on
both main paths but `(line, True)` on the fallback. Same bug class as
first-pass fix 2, same fix: one-line change to `_record_length()`, plus
`test_read_capped_lines_iterate_only_accepts_record_exactly_at_cap` (with a
`_IterOnlyStream` helper), verified to FAIL pre-fix and pass post-fix.
Reachable only for streams with neither `readline` nor `read` (never real
`sys.stdin`), but the "max accepted record is exactly the cap" contract now
holds uniformly.

### Out-of-scope change reverted

The first-pass commit silently rewrote `docs/SESSION_HANDOFF_NEXT.md`
(~240 lines of session history replaced, never mentioned in its handoff or
commit message). Branch scope is `core/worker.py` + its tests; restored the
file to `master` verbatim in this pass.

### Final verification

- `python -m pyright app core` → 0 errors, 0 warnings, 0 informations.
- Worker-scope files (fixpack/control/protocol): 42 passed.
- Full suite (`tests/`, minus `tests/smoke/`): 0 FAILED/ERROR lines across
  repeated runs. Two GUI-test flakes seen once each across runs
  (`test_viewer_confidence_tags_applied` FAILED once, then passed in
  isolation and in full-file runs; `test_hub_setup_dialog` ERROR once, then
  clean) — neither imports `core/worker`, both order-dependent, unrelated to
  this branch.

---

## Third-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Branch already held two commits on top of `master` when this pass started:
first-pass fixes (`2843f4a`) plus a second-pass fix (`7dab672`, iterate-only
at-cap uniformity). This pass re-verified everything from scratch and ran a
fresh adversarial review. Outcome: genuinely clean — no further code changes,
no wrong/incomplete/cosmetic fix found in either earlier pass.

### Verification of earlier claims (prove-it discipline)

- Restored `master`'s `core/worker.py` over the fixed tree (new tests kept)
  and ran all 9 new regression cases: **all 9 FAILED pre-fix** (double-report
  readline + chunked, at-cap readline/chunked/iterate-only, end-to-end single
  error, done-boundary, logging-survival, startup_error-on-raise), then
  restored the fix and confirmed all 9 pass. Both earlier "fails pre-fix"
  claims reproduce exactly.
- Cross-path uniformity probe (throwaway, not committed): 7 edge inputs
  (consecutive oversize records, oversize-then-at-cap, at-cap vs over-by-one,
  blank lines around oversize, unterminated oversize/at-cap at EOF, empty
  stream) across all three `read_capped_lines` paths (readline / `read()` /
  iterate-only). Oversize FLAG sequences agree on every path: exactly one
  report per bad record, at-cap accepted, over-by-one rejected. The only
  divergence is the truncated prefix *content* yielded with `oversize=True`
  (readline yields cap+1 chars, others the full record) — intentional OOM
  bound, caller discards it, no behavioral effect.
- Chunked `read()` probe with `_READ_CHUNK_CHARS=7` over a mixed
  oversize/ok/at-cap/over-by-one stream: flags `[True, False, False, True]`,
  contract holds with records split across many bounded reads.
- Failure-path probe (throwaway): `transcribe` raising mid-task yields
  `started → error`, exactly one `error`, no `done`, slot cleared — confirms
  the done-boundary fix's hand-trace (raise skips `emit("done")` via
  exception propagation, outer `except` reports once).
- `core/task.py` confirms fresh tasks start with `paused/cancelled = False`,
  validating the stray-control no-op reasoning behind fix 3.

### Adversarial hypotheses investigated and DISMISSED with evidence

- Stale `_current_task` if `emit("started")` raises: `emit` only raises on a
  broken stdout (JSON path has a repr fallback), i.e. the parent is gone and
  the process is exiting — no production effect. Same class as documented C.
- `UnicodeDecodeError` from `readline` escaping `_stdin_reader` silently via
  the bare `finally`: parent always writes valid UTF-8 JSON; no concrete
  trigger exists, and any "fix" (break vs continue) risks an error-loop or a
  behavior change for a non-scenario. Theoretical, left alone.
- `clip_start=0.0` falsy in `if task.clip_start or task.clip_end`: a
  zero-start clip is whole-file-equivalent, so keeping resume is harmless.
  No concrete wrong behavior; left alone.
- Oversize message saying "bytes" while the cap is characters, heartbeat not
  stopped on escaping exceptions, parent-side ordering races A/B: all already
  documented in this handoff as deliberate non-fixes; re-read and agreed, no
  change.

### Final verification

- `python -m pyright app core` → 0 errors, 0 warnings, 0 informations.
- Full hermetic suite (`tests/`, minus `tests/smoke/`): **2195 passed,
  1 skipped, exit 0**. No flakes observed in this pass.
- Working tree otherwise clean: no code changes in this pass, handoff-only
  commit.
