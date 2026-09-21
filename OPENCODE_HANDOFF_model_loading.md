# OPENCODE_HANDOFF — model_loading.py review (2026-09-20)

Branch: `opencode/model-loading-review` (local commit only, not pushed).

Scope: `app/dialogs/model_loading.py` (`ModelLoadingDialog`) + its tests.
Caller contract verified in `app/services/transcription_service.py`
(`ensure_worker_ready`, `_release_pending_load`) and `app/app.py`
(`post_to_main`, `_drain_main_calls`).

## Verdict

Two real, reproducible bugs found and fixed. The rest of the file
(size, TclError coverage, progressbar lifecycle on dialog-controlled
exit paths) held up under adversarial review — no stylistic churn.

## Bug 1 — late `mark_success_and_close` overwrote a user Cancel

The App never calls `mark_success_and_close` directly: on a worker
`ready` event `_release_pending_load` routes it through
`post_to_main`, which queues it for the next `_drain_main_calls` tick
(≤50 ms later; `app/app.py:4476`). If the user clicked Cancel in that
window, `cancel()` already ran (`success = False`, dialog destroyed),
and the queued callback then set `success = True` on the dead dialog —
destroying and stopping the progressbar a second time and leaving
`success` True even though the caller had already read False and torn
the worker down. Depending on which handler ran first, Cancel either
killed or kept the freshly-ready worker — a nondeterministic,
user-visible outcome.

Verified against the pre-fix file
(`git show HEAD:app/dialogs/model_loading.py`): after
`cancel(); mark_success_and_close()`, `success` was `True`.

Fix: a `_closed` flag set by whichever close path runs first makes both
`cancel()` and `mark_success_and_close()` idempotent; first close owns
the final `success` value, no second `destroy()`/`pb.stop()`.

## Bug 2 — centring clamped negative coordinates onto the primary monitor

`self.geometry(f"+{max(x, 0)}+{max(y, 0)}")` clamped every coordinate
to >= 0. A parent on a monitor left of / above the primary (negative
root coordinates) had its dialog yanked to the primary; a minimised
parent (Windows reports root coords `-32000`, measured live) landed at
`(0, 0)`.

Fix: the maths moved into `_compute_position()`, which

* falls back to screen-centring when the master is not viewable
  (`winfo_viewable()` is 0 for an iconic root — measured), and
* clamps to non-negative only when the parent itself is on the primary
  display, preserving negative coordinates otherwise.

Empirically verified on this machine (Windows, Tk 8.6): the geometry
string `-1010+150` means "1010 px from the right screen edge" on a
mapped window (`winfo_x == 1114` at 2560x1440), while `+-1010+150`
places it at absolute `x = -1010`. The existing comment in
`app/widgets/error_dialog.py` states this convention backwards; the
`f"+{x}+{y}"` form used here is the correct one.

## Tests

New `tests/core/test_model_loading_dialog.py` (9 tests):

* pure `_compute_position` cases: primary parent, on-screen clamp,
  negative-coordinate parent (old code returned `(0, 150)`), minimised
  fallback;
* race cases against a real (withdrawn-root) dialog: late-ready after
  Cancel keeps `success is False`; Cancel after ready keeps True;
  repeated closes are no-ops;
* geometry integration: `"+-"` present for a negative-coordinate
  parent, screen-centred geometry for a minimised parent.

Both regression classes were confirmed to fail against the pre-fix
file before landing.

## Gates

* `pyright app core` → `0 errors, 0 warnings, 0 informations`
* `python -m pytest tests/ --ignore=tests/smoke -q` → fully green
  (one resource skip), no machine flake this run.

## Adversarial notes / dropped candidates

* `pb.start(10)` and the other construction-time Tk calls are
  unguarded, but a real widget that reaches them cannot raise
  TclError; a no-display environment fails earlier at `Toplevel()`
  construction. Dropped as invented.
* Parent off-screen right/bottom is not clamped (no cross-platform
  virtual-desktop API); matches the established `error_dialog.py`
  convention and only affects deliberately off-screen parents.
  Dropped.
* Ticker not stopped when the dialog is destroyed by app teardown:
  that path ends the interpreter/mainloop. Dropped.

## Out-of-scope observations (NOT changed)

* `app/widgets/error_dialog.py:114` formats negative coordinates as
  `-N`, which Tk reads as "N px from the right edge" — its stated
  rationale is inverted relative to measured Tk behaviour, so its
  secondary-monitor fallback lands on the wrong side of the primary.
* `app/dialogs/model_download.py:97` and
  `app/dialogs/statistics.py:62` still use the `max(x, 0)` clamp and
  have the same multi-monitor issue Bug 2 fixed here.

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Clean second pass: both first-pass fixes verified empirically, no
further code changes. Test file and `model_loading.py` untouched by
this pass; only this handoff section added.

### What was verified and how

* Reverted `app/dialogs/model_loading.py` to the pre-fix version
  (`git show master:...` — note: this worktree's `master` ref is
  newer than the branch point, so that path yields the true
  pre-fix file) and ran the new tests: 5 failures covering both
  bug classes (`test_late_ready_after_cancel...`,
  `test_keeps_negative_parent_coordinates...`,
  `test_minimised_parent_falls_back...`, plus both geometry
  integration tests). Restored the fixed file: all 9 pass.
  Both regression classes genuinely fail without the fix.
* Caller contract re-checked against
  `app/services/transcription_service.py:93-120,246-358` and
  `app/app.py:4447-4488`: the ready path is deferred through
  `post_to_main` (≤50 ms tick), confirming the ≤50 ms Cancel-vs-ready
  window the `_closed` guard closes. `_drain_main_calls` swallows
  per-callback exceptions, so a late no-op callback can never kill
  the poll loop.

### Minor correction to the first-pass write-up (prose only)

Bug 1's summary says the late callback destroys / stops the
progressbar "a second time". Both calls are wrapped in
`try/except TclError`, so the second `destroy()`/`pb.stop()` was
always caught and harmless — the user-visible damage was exactly
the `success = True` flip (verified: pre-fix file yields `True`
after `cancel(); mark_success_and_close()`) plus the resulting
keep-vs-teardown nondeterminism for the ready worker. No code
change; the `_closed` fix covers the real defect.

### Fresh adversarial review — checked and dropped, no new bugs

* Double-negative geometry (`f"+{x}+{y}"` with both negative, e.g.
  `"+-1010+-50"`): verified live on Windows/Tk 8.6 — accepted and
  normalised, same as `"+-1010-50"`. Not a bug.
* Ready-event arriving between `_pending_load_worker_id` assignment
  and dialog construction (would hang `wait_window` with no closer
  posted): impossible — that stretch is straight-line main-thread
  code and `poll()` only runs via `after()` when the mainloop
  pumps (`update_idletasks` runs geometry only, not timers). Dropped.
* `_compute_position` clamping both axes on one joint condition:
  correct as-is — when the parent origin is off-primary in either
  axis the dialog belongs to that monitor's coordinate space, so
  preserving both is right. No concrete failure scenario. Dropped.
* `post_to_main` queue-full drop (2000) stranding the modal: needs
  a 2000-callback flood, pre-existing, lives in `app.py` outside
  this scope. Dropped.
* Out-of-scope observations above re-confirmed accurate and left
  untouched: `model_download.py:97` / `statistics.py:62` still use
  `max(x, 0)`; `error_dialog.py:114` (`{x:+d}` form) still carries
  the inverted comment.
* Pre-existing `master..HEAD` diff on `docs/SESSION_HANDOFF_NEXT.md`
  is ref skew (this worktree's `master` moved ahead of the branch
  point in the main checkout), not branch content — untouched.

### Gates (this pass)

* `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`
* `python -m pytest tests/ --ignore=tests/smoke` →
  `2195 passed, 1 skipped in ~133s` (exit 0; the skip is the known
  resource skip, same as first pass)
