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
