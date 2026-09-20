# OpenCode handoff — worker task-correlation-id design (fixes protocol review "A" + "B")

Branch: `opencode/worker-correlation-id-design` (local commit only, not pushed).
Base: `master` @ `706cdff` (fresh copy; the `opencode/worker-protocol-review`
branch's own 5 fixes are NOT included here and were not redone).
Scope: `core/worker.py`, `core/task.py`,
`app/services/transcription_service.py`, new/updated tests. Nothing else.
No `.gitignore`d file, no credential file, no third-party library source was read.

This file is written incrementally: the design below was written BEFORE any
code, per the task's process requirement; the three self-critique layers are
appended after implementation (sections "Layer 1/2/3").

---

## 1. The bug being fixed (from the protocol review writeup)

`app/services/transcription_service.py` writes the `transcribe` command and a
later `pause`/`resume`/`cancel` for that task from two different daemon threads
(`_dispatch_command_async` / `_send_command_async`) through the same stdin pipe,
serialised only by `worker["stdin_lock"]`. If the control thread wins the lock,
the worker reads the control BEFORE the `transcribe` it belongs to. With no
in-flight task, the control is a documented silent no-op, so it is lost while
the UI already flipped the task to paused/cancelled. The review flagged two
windows:

- **A** — control line physically precedes the transcribe line (two writer
  threads racing for the lock).
- **B** — control line follows the transcribe line, but the worker's main loop
  has not dequeued/registered that task yet (`_current_task` is still `None`,
  or still the previous task).

Both are the same root cause: a control command carries no information about
WHICH task it targets, so the worker can only guess "the current one".

## 2. Design (written before coding)

### 2.1 Concept

An optional **`task_id`** string field on both the `transcribe` command and on
`cancel`/`pause`/`resume` control commands. The worker routes every id-bearing
control by exact id match; an id-less control keeps today's exact semantics.

Strictly add-only, per `core/worker.py`'s own frozen-protocol docstring:

- No existing command/event field is renamed, removed, or retyped.
- No new REQUIRED field: an id-less transcribe and an id-less control are still
  valid and behave exactly as before.
- Two new event types are added (`control_applied`, `control_unmatched`);
  older parents ignore unknown event types (their `poll()` if/elif chain skips
  them), and the worker ignores unknown extra command fields.

### 2.2 Where the id lives (parent side)

`core.task.TranscriptionTask` already has `history_id` (the history-DB primary
key, assigned in `dispatch_waiting()` BEFORE the transcribe command is built
and before the task can be paused/cancelled). That is the natural existing id,
with one hole: `history_id` is `0` when the history DB is unavailable, and `0`
would collide across tasks. So:

- New attribute `TranscriptionTask.task_id: str = ""`.
- New module-level helper
  `app.services.transcription_service.task_correlation_id(t) -> str`:
  - returns the already-cached `t.task_id` when set;
  - else derives `"h<history_id>"` when `history_id > 0`;
  - else falls back to `"u<uuid4().hex>"`;
  - caches the result on the task (best-effort) so the transcribe command and
    every later control command for that task carry the SAME value even if
    they are built on different threads.
- `transcribe_command(t)` adds `"task_id": task_correlation_id(t)`.
- `send_control(task, action)` sends
  `{"action": action, "task_id": task_correlation_id(task)}`.

The parent's two writer threads still race for `stdin_lock` — that is fine and
intentional: with the id the race stops mattering. Whatever the on-wire order,
the worker attributes the control to exactly its task (or explicitly reports
that it could not), so no parent-side "write the transcribe first" gate is
needed. Keeping the parent change minimal is itself a design goal (it is the
most sensitive caller; fewer moving parts on the Tk side).

### 2.3 Worker-side resolution rules

State: `_current_task` (unchanged) plus a bounded park table for id-bearing
controls that cannot be applied yet.

For a control command `{action, task_id}`:

1. **No `task_id` (legacy)** → today's behaviour, byte for byte:
   apply to `_current_task` if one exists; silent no-op otherwise; no ack.
2. **With `task_id`** and `_current_task.task_id == task_id` → apply now and
   emit `control_applied {action, task_id, delayed: false}`.
3. **With `task_id`** and no matching current task → park it (FIFO, max 64,
   TTL 10 s) and emit nothing yet:
   - if/when a `transcribe` with that exact id is registered, the parked
     controls are applied in arrival order at registration time (before the
     transcribe body runs) and each emits
     `control_applied {action, task_id, delayed: true}`;
   - if the TTL expires first, each emits
     `control_unmatched {action, task_id, reason: "timeout"}` — an explicit
     acknowledgement instead of today's silent swallow;
   - on park-table overflow the OLDEST parked control is evicted (a later
     pause/resume supersedes an earlier one; dropping the newest would leave
     the user's latest action unhonoured) and emits
     `control_unmatched {action, task_id, reason: "capacity"}`.

Race-freedom of "park vs register" is achieved by doing the match-or-park
decision and the registration-pop under the SAME `_state_lock`, so a control
either lands in the parked list before registration pops it, or sees the
freshly-registered task and applies immediately. There is no window between
those two paths. Applying the flags happens inside that lock as well, so two
controls for the same task can never be applied out of order.

### 2.4 Orderings, exhaustively

| Ordering | Result with this design |
|---|---|
| control line BEFORE transcribe line (bug A) | parked by id; applied when the transcribe registers |
| control read AFTER transcribe queued, BEFORE registered (bug B) | same parking path |
| control while the PREVIOUS task is still current (the other branch's fix #3 window) | id mismatch → parked for its own id; never applied to the previous task |
| control after the task already finished | no current match, no transcribe coming → `control_unmatched` ack after TTL (not silent) |
| two rapid transcribes, controls interleaved | each control only ever matches its own id; a control for a queued task parks until that task registers; a control for the running task applies |
| id-less control, no in-flight task (old parent / e2e driver) | silent no-op, exactly as documented today |
| id-less control while a task runs | applied to the current task, exactly as today |
| old worker + new parent | worker ignores the extra field → today's (racy) behaviour; no crash |
| new worker + old parent | id-less paths unchanged; no new required field |

### 2.5 Parent reaction to acks

`poll()` gains two lightweight branches: a delayed `control_applied` is a
debug log; a `control_unmatched` is logged to the app console (the control was
genuinely not honoured — the user should not be left believing it was). No UI
state is rewritten from an ack: a failed dispatch is already handled by the
existing dispatch-error / `worker_exit` / watchdog paths.

### 2.6 What is deliberately NOT done

- Not touching the other branch's 5 fixes (they are a separate increment).
- Not adding a parent-side "transcribe write completed" barrier: with id
  matching it would add Tk-side complexity for zero correctness gain.
- Not making `task_id` required; not changing `stop_worker`'s shutdown
  command; not changing the `--worker` argv contract or stdout framing.

## 3. Implementation

Exactly the files listed at the top (see `git diff` for the mechanical side):

- `core/task.py` — `TranscriptionTask.task_id: str = ""` with the protocol
  rationale.
- `core/worker.py`:
  - docstring: `task_id` semantics + the two new events;
  - `_normalise_task_id`, `_apply_control_flag`, legacy `_apply_control`
    (signature extended with an optional `task`; old call sites unchanged),
    `_park_control_locked`, `_route_control`, `_register_task`,
    `_expire_parked_controls`, `_clear_parked_controls`;
  - module constants `CONTROL_PARK_TIMEOUT_S = 10.0`, `_MAX_PARKED_CONTROLS = 64`;
  - reader routes controls through `_route_control(action, task_id)`;
  - main loop stamps `task_id` on `started`/`done`/`error`, calls
    `_register_task` (which applies parked flags before `transcribe()` runs)
    and emits the delayed acks; shutdown/EOF clear the park table.
- `app/services/transcription_service.py` — `task_correlation_id()`,
  `"task_id"` on `transcribe_command()` and on `send_control()`, and two new
  `poll()` branches for the ack events.

## 4. Tests

New:

- `tests/core/test_worker_correlation_id.py` (16 tests) — immediate match,
  another task's control never misapplied, legacy task without an id never
  matched, int/str id normalisation, parked controls applied in arrival order,
  **control-before-transcribe honoured for pause and cancel (the original
  report's exact ordering, driven through `main()`)**, a control for task B
  landing while task A runs reaching only B, deterministic expiry helper ack,
  real timer expiry ack, park capacity eviction with ack, no double-ack after
  registration, legacy id-less control semantics (silent no-op / applies to
  current), and an E2E proof that an id-less control-before-transcribe still
  no-ops exactly as before.
- `tests/app/test_transcription_correlation.py` (8 tests) — id derivation from
  `history_id`, uuid fallback, hostile history id, transcribe/control id
  agreement through the real `send_control` writer, `send_control` False when
  the task is unwired (and no id generated), `poll()` logging for
  `control_unmatched`, tolerance of `control_applied`, and an end-to-end
  rebuild of the bad ordering using the **real parent-built command payloads**
  (control line first) run through the real `core.worker.main()`.

Updated: `tests/core/test_transcribe_command.py` (command-key contract now
includes `task_id`; two new id tests).

Existing worker/control/protocol tests all still pass unchanged.

## 5. Self-critique Layer 1 (adversarial, against the first implementation)

Findings and dispositions:

1. **Ack ordering can invert** (a delayed `control_applied` emitted by the main
   loop can be written after an immediate ack emitted by the reader thread).
   *Non-issue*: flag application is serialised under `_state_lock` in wire
   order; acks carry no state and the parent only logs them.
2. **Parent's unmatched-control message claimed the task "was never started".**
   Wrong for a control that arrives after the task finished but before the
   parent drained `done`. *Fixed*: wording now says no matching in-flight task
   was found.
3. **`task_correlation_id` docstring over-promised** the non-cacheable
   fallback ("both seeing the same value"). *Fixed*: now states mutable task
   objects are required (every real task is) and that failure can only cause
   an unmatched ack, never a misapplied control.
4. **Candidate: parent-side "wait until the transcribe write completed" gate.**
   Rejected after analysis — id matching already makes the on-wire order
   irrelevant, and the gate would add a Tk-side blocking wait for zero
   correctness gain. Documented in 2.6.
5. **Candidate: worker remembering recently-finished ids** so a straggler
   control gets reason "already finished" immediately. Rejected as extra
   unbounded/ageing state for a cosmetic gain; the timeout ack is already
   non-silent and the neutral message covers it.
6. **Old worker + new parent** cannot be fixed remotely (old reader ignores
   the field) — documented, not a regression.
7. **Third-party client queueing two transcribes on one worker** → a parked
   control can time out while the first task still runs; that is the
   documented bounded resolution (explicit ack, never misapplication).
8. **Heartbeat/liveness interaction**: acks count as liveness like every
   event; in this app the parent never spams controls, so no watchdog-evasion
   loop. Noted, no change.

## 6. Self-critique Layer 2 (fresh adversarial pass against the revised code)

1. **Capacity loop could `popleft()` an empty deque** if `_MAX_PARKED_CONTROLS`
   were ever configured to 0 (future maintainer / bad patch). *Fixed*: loop
   guard `while _parked_order and len(...) >= cap`.
2. **Id-uniqueness requirement was implicit.** *Fixed*: the worker docstring
   now states ids must be unique among outstanding tasks and never reused.
3. **Lock-order audit**: `_state_lock → _emit_lock` never nests (no emit while
   holding `_state_lock`; Timer callback acquires only `_state_lock` then emits
   after release). No deadlock, no inversion. Verified by inspection of every
   new function.
4. **`Timer.start()` under `_state_lock`**: safe — starting a thread does not
   run the callback synchronously; the callback blocks on `_state_lock`.
5. **`_register_task` early return for an id-less task** still publishes the
   task (lock held, global set, `[]` returned) — verified correct.
6. **`transcribe_live` path** does not touch `_current_task`/`task_id`;
   unaffected, and controls arriving during a live chunk park/apply normally.
7. **Shutdown paths** (stdin EOF and `shutdown`) now clear the park table,
   which also prevents timer threads from leaking across `main()` calls in
   tests.
8. **Token routing of acks**: emit adds `_token`; the parent's reader adds
   `_pid`/`_worker_id`; `worker_for_event` handles both — no new routing hole.
9. **The other branch's fix #3 window** (control for the NEXT task while the
   previous task is still registered) is closed for id-bearing controls by the
   id mismatch → park path, independently of that branch's change.

## 7. Self-critique Layer 3 (constraints + suite + backward compatibility)

1. **Constraint audit**: no field renamed/removed/retyped; no new required
   field; `gui.py --worker` argv and stdout framing untouched; English-only;
   `docs/CHANGELOG.md` and `docs/SESSION_HANDOFF_NEXT.md` untouched; nothing
   from the worker-protocol-review branch re-done; no gitignored/credential
   file read; tests are hermetic (no model, network, Tk or subprocess in the
   new files — the E2E-style tests stub `load_existing_model`/`transcribe`).
2. **One real test flake found and eliminated**: the timer-based
   unmatched-ack test failed once in a full-suite run (unreproducible in
   isolation). Reworked into a deterministic direct-expiry test plus a
   `TTL=0` timer test whose event wait filters on `task_id` (and the wait
   timeout raised to 5 s). Two full-suite runs since are green. Also reasoned
   through Timer early-fire: the timer's internal deadline is computed on the
   same monotonic clock *after* the park's deadline, so a fired timer always
   finds its entry expired — a planned re-arm was deliberately NOT added
   because per-entry timers would then double up.
3. **Backward compatibility exercised for real**: E2E id-less
   control-before-transcribe still silently no-ops; id-less control still
   applies to the current task; id-less control still applies even to a task
   that carries an id (older parent); `tools/e2e_cancel_pause.py` sends
   id-less commands and is untouched; old workers ignore the extra field.
4. **New failure surface considered once more**: a `control_unmatched` ack is
   one line in the console, no state change; a delayed `control_applied` is
   debug-only; neither can resurrect or kill a task.

No surviving findings after Layer 3.

## 8. Verification

- `python -m pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **exit 0, fully green**
  (2213 collected). One earlier full-suite run showed only the documented
  unrelated `_tkinter.TclError` flake in
  `tests/core/test_search_dialog.py::test_open_selected_with_no_selection_is_a_noop`;
  that test passes alone and the flake did not recur.
- New tests: 16 (core) + 8 (app) + 3 net-new in `test_transcribe_command.py`,
  all passing; every ordering row in 2.4 has at least one test, including the
  literal bad ordering from the original report driven through the real
  parent command builders and the real `core.worker.main()`.
- Not run: `tests/smoke/` and `tools/e2e_cancel_pause.py` (need the real ~3 GB
  model / test video). No third-party source read.

---

## 9. Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Independent re-check of the `da2d06d` diff against `master`. No code changed;
no new tests added. This is a genuinely clean second pass.

### 9.1 What was verified from the first pass, and how

1. **Park-and-apply closes bug A/B (control line precedes transcribe line).**
   Reproduced the legacy behaviour directly: with no task registered, a
   legacy apply-to-current is a silent no-op (`paused` stays `False` after
   the late registration). With the fix, `_route_control("pause", "h1")`
   with nothing current parks, and `_register_task` applies it
   (`paused is True`, parked list `["pause"]`). Then neutered
   `_register_task`'s flag-application at runtime and re-drove the exact
   bad ordering through the real `main()` — the task arrived unpaused,
   i.e. the E2E regression test genuinely guards the fix, not a tautology.
2. **A control for another task is never misapplied.** With an `h1` task
   current, `_route_control("cancel", "h2")` leaves `h1.cancelled is False`
   and parks under `"h2"`. (Legacy semantics would have set the flag on
   `h1` — the wrong task.)
3. **Parent id agreement + ack paths.** Ran the three touched test files:
   `test_worker_correlation_id.py` + `test_transcription_correlation.py` +
   `test_transcribe_command.py` → 31 passed. The expiry, capacity-eviction,
   no-double-ack, and id-less-legacy tests all exercise what their names
   claim (read each test body; no mock-teardown trickery — the autouse
   fixture clears park state and the current task around every test).

### 9.2 Apparent discrepancy investigated and cleared (not a finding)

`git diff master..HEAD --stat` shows `docs/SESSION_HANDOFF_NEXT.md` with
163 deletions, seeming to contradict this file's §7.1 claim that the doc is
untouched. Checked: `git log master..HEAD -- docs/SESSION_HANDOFF_NEXT.md`
is EMPTY and the merge-base is `706cdff` — the branch never touched the
file. The deletions are an artifact of `master` having advanced past the
base (new session entries); the diff renders master's newer content as
"deleted" on this side. The §7.1 claim is accurate relative to its base.

### 9.3 Fresh adversarial review — scope and outcome

Re-read `core/worker.py` §§120–340 (park table, route, register, expiry,
clear) plus the `main()` reader/registration loop and the parent's
`dispatch_waiting` → `transcribe_command` → `send_control` → `poll()`
chain, hunting for races, crash paths, leaks, and silently-wrong output.
Checked and dismissed with reasons:

- **UUID-fallback divergence between dispatch and control threads?** No:
  both `task_correlation_id()` calls happen synchronously on the Tk caller
  thread (`dispatch_waiting` line 894; `send_control` line ~1013) BEFORE
  the daemon writer threads start — the writers only carry pre-built
  strings. `worker["task"] = t` (line 874) also precedes the transcribe
  build on the same thread, so the cache is always warm for controls.
  Single-threaded derivation ⇒ no `uAAA`/`uBBB` split.
- **Exactly-once ack across expiry/register/eviction?** Yes: all three
  mutations hold `_state_lock`; expiry collects-then-emits after release,
  eviction acks after release, registration pops before the timer can
  observe the entry. A fired-but-blocked timer finds its entry already
  gone in all interleavings. The no-double-ack test pins this.
- **Lock order / emit-under-lock?** No emit happens while holding
  `_state_lock` in any new path (evicted/capacity, immediate, delayed,
  timeout all emit after release). `_register_task` returns the parked
  list; `main()` emits after the lock is out. Timer `start()` under lock
  is safe (callback blocks on the same lock).
- **Timer/thread leaks?** Bounded: one daemon timer per parked control,
  max 64 entries; cancelled on register/evict/clear; shutdown and EOF
  both clear the table.
- **Stale parked control applied to a retried dispatch (cached `task_id`
  survives a new `history_id`)?** Same logical task object ⇒ same user
  intent; carrying the pause/cancel over to the retry is correct, not a
  misapplication. Uniqueness among *outstanding* tasks still holds.
- **Unknown action parked then acked as applied?** Unreachable over the
  wire — the reader only routes `cancel`/`pause`/`resume` to
  `_route_control`. Direct-call-only hardening was deliberately NOT made
  (cosmetic, per the no-padding rule).
- **New `task_id` on `started`/`done`/`error` vs old parents / event
  routing?** `worker_for_event` routes purely on `_token`/`_pid`+`_worker_id`;
  extra keys are ignored by old parents' if/elif chains. Live path
  (`transcribe_live`) untouched and unaffected, as §6.6 claims.
- **`control_unmatched` user message accuracy?** Neutral wording ("no
  matching in-flight task was found") covers both never-started and
  already-finished — the §5.2 fix held up.

Nothing further wrong after a real attempt — stated plainly per the brief.

### 9.4 Final verification (this pass)

- `python -m pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **exit 0, fully
  green (2213 collected)**. No flakes this run.
- Not run: `tests/smoke/` (needs real hardware/network).

---

## 10. Second-pass independent re-check, re-run (muse-spark-1.3-contributor) — 2026-09-20

The re-check task was re-issued after §9 was already committed
(`844db5c`), so this is a second independent run over the same diff
(`da2d06d` + the §9 handoff-only commit). Re-verified from scratch rather
than trusting §9. No code changed; no new tests added. Genuinely clean.

### 10.1 What was verified from the first pass, and how

1. **Park-and-apply closes bug A/B.** Drove it directly:
   `_route_control("pause", "h1")` with nothing current parks, and
   `_register_task` on a `task_id="h1"` task applies it (`paused is
   True`, one parked entry returned). Legacy behaviour reproduced
   alongside: id-less `_apply_control("pause")` with no task returns
   `False` and a late-registered task stays unpaused — the preserved
   silent no-op.
2. **Revert-proof (the fix is load-bearing, not tautological).**
   Neutered `_register_task`'s flag application at runtime and re-drove
   the bad ordering: the task arrived unpaused, i.e. without the fix the
   control is lost. Restored, it applies. The E2E regression test
   therefore guards the real fix.
3. **No cross-task misapplication.** With an `h1` task current,
   `_route_control("cancel", "h2")` leaves `h1.cancelled is False` and
   parks under `"h2"`.
4. **Touched test files:** `test_worker_correlation_id.py` +
   `test_transcription_correlation.py` + `test_transcribe_command.py` →
   31 passed.

### 10.2 Discrepancy re-checked and cleared (not a finding)

Re-confirmed §9.2: `git log master..HEAD --
docs/SESSION_HANDOFF_NEXT.md` is empty and the merge-base is still
`706cdff` — the branch never touched the file; the stat deletions are
master having advanced past the base. §7.1's claim holds.

### 10.3 Fresh adversarial review — scope and outcome

Re-read `core/worker.py` park/route/register/expiry/clear plus the
`main()` reader loop and the parent's `dispatch_waiting` (line 894) →
`transcribe_command` → `send_control` (line ~1013) → `poll()` chain.
New angles probed beyond §9.3, all dismissed with reasons:

- **UUID-split between dispatch and control threads?** No: both
  `task_correlation_id()` calls run on the Tk caller thread before the
  daemon writers start (writers carry pre-built strings). Even a
  hypothetical race would fail safe (unmatched ack, never
  misapplication).
- **Expiry leaks timers?** No: an expired entry's own timer is the one
  that fired; surviving entries keep exactly one daemon timer each,
  bounded by the 64-entry cap, all cancelled on register/evict/clear.
- **Parked controls survive task finish?** Yes — `_set_current_task(None)`
  in the `finally` does not touch the park table, so a control for a
  queued task B landing while task A runs still reaches B. Required,
  correct.
- **Pause-then-resume parked in order?** Yes: per-id lists preserve
  arrival order, applied in order at registration (net unpaused).
  Capacity eviction drops the oldest, keeping the user's latest action.
- **`send_control` unwired path mints no id?** Correct:
  `task_correlation_id` is only called after the worker match, so a
  `False` return generates nothing.
- **Unknown-action parked control false-acking `control_applied`?**
  Unreachable over the wire (reader routes only cancel/pause/resume);
  direct-call-only hardening deliberately not added (no padding).

Nothing further wrong after a real attempt — stated plainly.

### 10.4 Final verification (this run)

- `python -m pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **exit 0, fully
  green (2213 collected)**. No flakes this run.
- Not run: `tests/smoke/` (needs real hardware/network).
