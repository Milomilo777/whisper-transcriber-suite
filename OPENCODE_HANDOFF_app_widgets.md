# OpenCode handoff — app/widgets review (2026-09-20)

Branch: `opencode/app-widgets-review` (local only, not pushed).

Scope reviewed in full: `app/widgets/hardware_wizard.py`, `app/widgets/tray.py`,
`app/widgets/console.py`, `app/widgets/platform.py`, `app/widgets/tooltip.py`,
`app/widgets/error_dialog.py`. `app/app.py`, `app/widgets/tabs.py` and
`app/dialogs/advanced.py` were read for context only (their diffs were left
untouched, per instructions).

Gate: `pyright app core` → 0 errors / 0 warnings / 0 informations.
`python -m pytest tests/ --ignore=tests/smoke -q` → green (exit 0).

Baseline note: the first full-suite run hit the already-documented intermittent
`_tkinter.TclError: Can't find a usable tk.tcl` flake in
`tests/core/test_search_dialog.py`; it passed in isolation, and the two later
full-suite runs were clean. Not a regression from this work.

## Real bugs fixed

### 1. Console right-click leaked one `tk.Menu` widget per click
`app/widgets/console.py` built a fresh `tk.Menu` inside the popup handler on
every right-click. Tk only destroys such a child when its parent is destroyed,
so the orphaned menus accumulated for the lifetime of the app (verified: child
count of the Text grows by exactly one per popup).

Fix: `_attach_context_menu()` now builds ONE menu per console; the popup
handler only posts it. `menu.grab_release()` is also guarded against
`TclError` (previously the bare `finally:` could raise a Tcl error out of the
callback if the popup failed).

Test: `tests/core/test_console_widget.py::test_popup_reuses_the_same_menu`
(posts five times, asserts one menu instance and no new children) plus
`test_build_console_creates_exactly_one_menu`.

### 2. Nested error dialogs silently removed a modal parent's grab
Tk keeps a single grab per display and does not stack grabs: `show_error()`'s
`grab_set()` replaced the grab of whatever dialog was open, and destroying the
error dialog did not hand it back. Confirmed on a live Tk: after dismissing an
error shown from a grabbing host, `root.grab_current()` was `None` — so
Advanced settings (opened via `wait_window`, modal) became non-modal, letting
the user open a second copy of it (both then write config on close). The same
applied to the hardware wizard opened from Advanced.

Fix: `app/widgets/error_dialog.show_error()` now records the current grab
holder (not necessarily `parent`: background paths pass the App root while a
dialog is open) and re-grabs it on close if it still exists and nothing newer
holds the grab. Menus/other non-window grabbers are excluded. `HardwareWizard`
records whether its master held the grab and returns it in `_on_close()`.

Tests: `tests/core/test_error_dialog.py` (parent-is-grab-holder, root-as-parent
while a dialog is modal, and the no-grab no-op case) and
`tests/core/test_hardware_wizard.py::test_close_restores_the_masters_modal_grab`.

### 3. Tray icon start failure left minimise-to-tray armed with no icon
If `TrayController.start()` failed while building/spawning the icon (Pillow or
pystray construction error), it logged and left `_icon = None` — but
`app/_install_tray()` still stores the controller, and `on_exit()`'s
minimise-to-tray check only tests `is_supported()`. Result: closing the window
could withdraw it with no tray icon to restore it (the exact stranding the
runner-crash path already guards against, which never fires because the runner
was never started).

Fix: `start()` sets `_start_failed`, and `is_supported()` now reports a failed
start as unsupported, so the X button exits instead of hiding the window.

Test: `tests/core/test_tray.py::test_failed_start_reports_the_tray_as_unsupported`.

### 4. Hardware-wizard benchmark leaked its temp WAV when ffmpeg failed
`_make_silent_clip()` creates the output with `tempfile.mkstemp` and then runs
ffmpeg. If ffmpeg could not run (missing bundled binary, bad args), the
function raised before `_benchmark_worker`'s cleanup `finally` could see the
path, leaving the file behind on every attempt.

Fix: the ffmpeg call is wrapped; a failure unlinks the temp file before
re-raising.

Test: `tests/core/test_hardware_wizard.py::test_make_silent_clip_removes_temp_file_when_ffmpeg_fails`.

## Verified clean (no code change)

- `console.py` Clear/Copy state handling: correct. It saves the state, flips to
  `normal`, acts, and restores — regression-guarded by
  `test_clear_restores_a_disabled_state` / `test_clear_leaves_an_enabled_widget_enabled`
  (note: the App never actually disables the log today; the comments that
  claimed it did were corrected in passing).
- `tooltip.py` edge cases: popup positioning near the bottom-right edge flips
  and clamps correctly (faked 320x240 screen in a test), and destroying a
  widget while its tooltip is showing takes the Toplevel with it.
  Regression tests: `tests/core/test_tooltip_widget.py`.
- `error_dialog.show_error()` off-thread use: no current call site calls it
  from a background thread (checked every call site in `app/`); the
  fire-and-return contract holds.
- `platform.open_folder()`: missing-folder and OSError paths both route to a
  user-facing dialog as documented; nothing to fix.

## Found but deliberately not changed (needs an owner decision)

- The hardware-wizard benchmark uses the **in-process** `core.transcriber.MODEL`
  global. The desktop app now runs transcription in worker subprocesses, so
  that global is only populated when the in-process Web/LAN server is running
  (it preloads the model). "Run 5 s benchmark" therefore usually answers
  "Model not loaded — load the Whisper model first by starting (and
  cancelling) one transcription", which no longer loads it in-process. Making
  the benchmark work would mean either loading the ~3 GB model into the GUI
  process (exactly what the v1.0.3 "no eager load" decision removed) or
  spawning a dedicated benchmark worker; both are product decisions, so only
  reported here.
- `console`'s Text widget is editable despite its "read-only" framing in
  docs/index (a plain `state="disabled"` blocks mouse selection, which was a
  real user complaint for the Live transcript). Making it read-only while
  still selectable is a behaviour change; not done unilaterally.

---

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Note on method: this worktree arrived with all four `app/widgets/` fixes
reverted as uncommitted working-tree edits on top of the branch commit, while
the new regression tests were still in place — i.e. old source + new tests.
That is exactly the revert-to-prove setup step 2 asks for, so the failing run
below was captured before restoring the fixes with
`git checkout HEAD -- app/widgets/...`.

### What was verified from the first pass, and how

All four claimed fixes were proved real by fail-then-pass, not by reading:

- Reverted source + new tests: 7 failures, one per claim —
  `test_popup_reuses_the_same_menu`,
  `test_build_console_creates_exactly_one_menu`,
  `test_failed_start_reports_the_tray_as_unsupported`,
  `test_make_silent_clip_removes_temp_file_when_ffmpeg_fails`,
  `test_close_restores_the_masters_modal_grab` (wizard),
  `test_close_restores_the_parents_modal_grab` and
  `test_close_restores_a_modal_dialog_when_parent_is_the_root`
  (error dialog). The error-dialog failure was the exact predicted
  mechanism (`grab_current()` is `None` after dismiss instead of the host).
- Restored fixes: the same files pass — 36/36 across
  `test_console_widget`, `test_tray`, `test_hardware_wizard`,
  `test_error_dialog`, `test_tooltip_widget`.
- The tray claim was additionally confirmed by reading the surrounding
  logic the diff alone doesn't show: `App._install_tray` stores the
  controller after `start()` with no post-start health check, and
  `App.on_exit`'s minimise-to-tray branch only checks `tray.is_supported()`
  — so without `_start_failed`, a failed start really does strand the
  window. No retry path exists in the app, so the flag making
  `is_supported()` sticky-False changes no other behaviour.
- The grab-restore chain was traced end to end: Advanced (`grab_set` at
  `advanced.py:162`) → `_open_hardware_wizard` (fire-and-forget, no
  `wait_window`) → wizard steals grab → `_on_close` hands it back; and
  `_save_and_close`'s `show_error(self, ...)` nests correctly because the
  dialog captures the wizard as `previous_grab` via `grab_current()`
  (not via `parent`). Out-of-order and triple-nested closes were traced
  through the restore-only-when-`None` + `winfo_exists` + `isinstance`
  guards — all resolve correctly (LIFO restores, premature outer close
  never steals from an inner dialog, destroyed holders are skipped).

Nothing in the first pass was found wrong, incomplete, or cosmetic: no
corrections to its code were needed.

### Fresh adversarial review (same files + immediate surroundings)

Re-read the fixed `console.py`, `error_dialog.py`, `tray.py`,
`hardware_wizard.py` plus `tooltip.py`, `platform.py`, and the
`app.py`/`advanced.py` call sites (`_install_tray`, `on_exit`,
`log`/`log_threadsafe`, `_open_hardware_wizard`). Candidates examined
and deliberately NOT changed (no concrete, reproducible failure found):

- `_copy_selection` / `_clear` leaving the log in `normal` state if
  `event_generate` / `delete` raised mid-try: probed live Tk on this box —
  `<<Copy>>` with no selection, `tk_popup` on a withdrawn root, and bare
  `grab_release()` with no grab all complete without raising, so no
  real-world trigger exists here; restructuring to `finally` would be
  unprovable hardening, not a bug fix.
- `tk_popup` raising before `"break"` is returned (both menus opening):
  no reproducible trigger found (menu grabs input while posted, so a
  second popup can't interleave); skipped per the concrete-scenario rule.
- Unbounded console-log growth (`insert_log_line` never trims): a real
  long-session cost, but capping drops user history and changes Copy-all
  semantics — a product decision in the same class as the two items the
  first pass already deferred, so reported here, not imposed.
- `advanced.py:1788` docstring still calls the wizard "non-modal" while
  it `grab_set()`s: stale comment, cosmetic — left alone.

### Final verification

- `pyright app core` → 0 errors / 0 warnings / 0 informations.
- `python -m pytest tests/ --ignore=tests/smoke` → 2201 passed,
  1 skipped, 0 failed (no tk.tcl flake this run).
- No source changes made in this pass; only this handoff section was
  appended. Genuinely clean second pass.

## Second-pass independent re-check (muse-spark-1.3-contributor)

### What was verified from the first pass and how

Backed up the four fixed `app/widgets/*.py` files, restored the `master`
versions (`git show master:<path>`), and ran the branch's new regression
tests against the old code. All four failed on old code and pass on the
fixed code (34/34 in the four widget test files after restore):

- `test_popup_reuses_the_same_menu` — old `console.py` has no
  `_popup_console_menu` and builds a Menu per click (fails).
- `test_close_restores_the_parents_modal_grab` — old `error_dialog.py`
  never hands the grab back (fails).
- `test_failed_start_reports_the_tray_as_unsupported` — old `tray.py`
  keeps reporting supported after a failed `start()` (fails).
- `test_make_silent_clip_removes_temp_file_when_ffmpeg_fails` — old
  `hardware_wizard.py` leaves the mkstemp'd WAV behind (fails).

No first-pass claim was found wrong, incomplete, or cosmetic. The
"verified clean" statements were spot-checked: tooltip `_hide`/`_show`
paths are exception-guarded, `platform.open_folder()` routes both failure
modes to a dialog, and no background thread calls `show_error()`.

### New bug found and fixed (with evidence)

Tray `_start_failed` flag made `start()` unretryable and success
unreportable (`app/widgets/tray.py`). `start()` gated on
`is_supported()`, which returns False once the flag is set — so a
transient boot-time failure (notification area not ready) could never be
retried, and even a hypothetical successful retry would still report
unsupported because nothing ever cleared the flag.

Fix: new `_libs_available()` (platform + deps only, ignores the flag);
`start()` gates on it and clears `_start_failed` on success, while
`is_supported()` keeps reporting a failed start as unsupported.

Evidence: added
`tests/core/test_tray.py::test_successful_retry_after_a_failed_start_reports_supported`
(fail-once then succeed Icon). It fails on the pre-fix code
(`assert 1 == 2` — second `start()` no-ops, retry never attempted) and
passes with the fix. The original
`test_failed_start_reports_the_tray_as_unsupported` still passes.

### Further observations, deliberately not changed

- `app/app.py::_install_text_context_menu` builds one `tk.Menu` per
  right-click — the same leak class as the console fix — and
  `transcript_viewer.py` builds one per row-click (there the rebuild is
  load-bearing: labels embed the row's speaker/idx). Both live outside
  this branch's touched files (`app.py`/dialogs were read-only scope in
  the first pass), and the app-wide handler needs a per-widget cache
  design, so reported here, not fixed unilaterally.
- `console._popup_console_menu` lets a `tk_popup` `TclError` propagate
  after the guarded `grab_release()` — Tk just prints a traceback, the
  app continues. Noise, not a crash path; left alone.
- `_install_tray` logs "Tray icon installed" even when `start()` failed
  (the controller is kept but reports unsupported, so `on_exit` correctly
  exits instead of stranding). Log wording only; left alone.

### Final gates

- `python -m pyright app core` → 0 errors / 0 warnings / 0 informations.
- `python -m pytest tests/ --ignore=tests/smoke -q` → green, no
  failures (2 pre-existing skips). No `tk.tcl` flake this run.
