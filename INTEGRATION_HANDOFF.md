# Integration Handoff

## `integration/opencode-merge-2026-09-21` — Merge of `opencode/app-dialogs-review`

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/app-dialogs-review` into `integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2188 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`).
- **Merge diff**: All 5 source files changed (`hub_setup.py`, `model_download.py`, `statistics.py`, `transcript_viewer.py` × 2 hunks) plus 6 new test files. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `_seg_float`: `math.isfinite` guard correctly rejects NaN/Infinity; default coerced via the same `float()` try/except.
  - `_parse_hms_ms`: bare-float path and colon-computed `total` both guarded with `math.isfinite`; test `test_parse_hms_ms_rejects_garbage` covers `inf`, `nan`, `1e400`, `1:00:inf`.
  - `_start_worker`: `cancel_event.clear()` + button re-enable prevents stale-cancel race; test proves it.
  - `_probe_writable`: `probe = None` on happy path + cleanup in OSError handler covers mkstemp-close-unlink failure chain.
  - `statistics.show_statistics`: `try/except` around `history.stats()` surfaces locked-DB errors via `show_error` instead of silently vanishing.
  - Transport disable: condition `self.vlc_mod is None or not self.media_path` correctly greys out transport when either VLC is absent or no media file exists — test `test_viewer_disables_transport_when_no_media_found` proves it.
  - Menu leak: `menu.destroy()` in `finally` after `grab_release()` — test `test_right_click_menu_destroyed_after_popup` proves no leaked Menu widgets.
  - VLC init failure: calls `_disable_embedded_playback()` (disables play + transport) instead of partial teardown — test `test_viewer_disables_transport_when_vlc_init_fails` proves it.
  - Non-dict `words` guards in `_update_karaoke` and `_segment_min_probability`: `isinstance(w, dict)` skip prevents `AttributeError` on hand-edited `[1, 2]` words lists — tests cover both helpers directly.
- **Test coverage of merged behavior**: New tests (`test_fixpack_sw2_viewer.py`, `test_fixpack_sw3_viewerwords.py`, `test_model_download_retry.py`, `test_hub_setup_dialog.py`, `test_statistics_dialog.py`, plus additions in `test_transcript_viewer.py`) exercise every merged fix with bare-instance stubs and real Tk construction. Pre-fix code would fail these tests.

Result: clean. No source changes needed.

## Merge: opencode/app-services-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/app-services-review`): no conflicts,
no reconciliation needed. Merge commit 53996cf on top of 41a2bfc.

Files brought in by the review branch (7e79551 range):
- `app/services/download_service.py`: pause+resume stale-generation guards
  (`_superseded()` via `_run_generation`), pre-media-phase and post-subtitle
  pause/cancel re-checks, `proc`-local stdout/wait with `if task.process is proc`
  ownership guard, `run_generation` params on `_media_phase` /
  `_run_caption_only_task`, paused-row handling in caption-only path.
- `app/services/transcription_service.py`: `spawn_token` snapshot for
  `worker_exit` routing; liveness-timeout path now marks task error +
  `finish_task` first and only `restart_worker` if still tracked in
  `app.workers` (avoids orphan RAM-resident workers).
- `tests/core/test_fixpack_Ia.py`: updated `_media_phase` mocks to accept
  `run_generation` kwarg (2 tests).
- `OPENCODE_HANDOFF_app_services.md`: new review handoff doc.

Sanity-checked combined diff via `git show HEAD` / `git diff HEAD~1 HEAD`:
intent matches the review-branch log (588f4cd + 7761776 + 7e79551).

Verification (first pass):
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetric suite (`tests/` minus `tests/smoke/`): 2188 passed, 14 skipped, 0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/app-services-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2191 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Added 3 targeted tests for the `_superseded()` generation-guard coverage gap (see below).
- **Merge diff**: 4 files changed (2 source, 1 test, 1 doc). No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `_superseded()` closure (`download_service.py:1119`): `getattr(task, "_run_generation", my_gen) != my_gen` correctly detects stale runs via generation bump. Default `my_gen` when the attribute is absent means old callers without the field are never falsely superseded — safe.
  - Pre-media early-return (line 1162): `_superseded() or paused` — if a pause+resume bumped the generation while this run was blocked in `maybe_update_yt_dlp`, the stale run exits before entering subtitle or media phases, preventing a duplicate concurrent download.
  - Post-subtitle early-return (line 1170): same guard — catches the case where a pause landed mid-subtitle-fetch.
  - Caption-only error suppression (lines 1134, 1581-1590): `_superseded()` suppresses both the exception handler's error post and the `wrote_files`-empty error post, preventing a stale run from flipping the fresh run's row to "error" and releasing its download slot.
  - `_run_caption_only_task` paused-row guard (lines 1603-1610): posts `("subtitle_status", task, "paused")` instead of falling through to the error branch — preserves the Resume action on the UI row.
  - `_media_phase` generation guard (line 1765): returns silently for superseded runs, preventing a second yt-dlp cookie-retry that would clobber `task.process`.
  - `proc`-local stdout/wait in `_subtitle_phase`, `_run_caption_only_task`, `_run_media_process`: each method uses a local `proc` variable for iteration and `.wait()`, then checks `if task.process is proc` before clearing — identity guard prevents nulling a newer run's live process.
  - `spawn_token` snapshot (`transcription_service.py:443`): captures `worker["token"]` at spawn time so the synthetic `worker_exit` event routes to the correct (dead) worker via `worker_for_event`, not onto the freshly-restarted worker.
  - Liveness watchdog reorder (`transcription_service.py:738-760`): `finish_task` (retires temp worker) runs before `restart_worker`, with `if w not in app.workers: continue` guard — prevents spawning an orphaned RAM-resident worker.
- **Test coverage of merged behavior**: 3 new tests (`test_run_task_superseded_skips_media_and_subtitle`, `test_run_task_superseded_after_subtitle_skips_media`, `test_superseded_caption_only_run_suppresses_error`) exercise the `_superseded()` generation-guard early-returns that were previously untested. Pre-fix code would fail these tests (old code enters phases and posts errors for superseded runs).

Result: clean. No source changes needed; test coverage gap closed.

## Merge: opencode/app-widgets-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/app-widgets-review`): no conflicts,
no reconciliation needed. Merge commit fe76765 on top of ebbc000.

Files brought in by the review branch (f5ef1b8 + f19de59 + 1632f0b + cfb871e):
- `app/widgets/console.py`: context-menu refactor — per-console single `Menu`
  (fixes per-right-click Tk widget leak), extracted `_copy_selection` /
  `_copy_all` / `_clear` / `_popup_console_menu` helpers; `_clear` restores the
  previous Text state so the log is not left permanently editable.
- `app/widgets/error_dialog.py`: dialog now restores the previous Tk grab
  holder on close, so an underlying modal dialog (e.g. Advanced settings)
  stays modal instead of going modeless.
- `app/widgets/hardware_wizard.py`: benchmark `_make_silent_clip` removes its
  mkstemp'd temp WAV when the ffmpeg run fails; wizard close hands the modal
  grab back to its master.
- `app/widgets/tray.py`: failed `start()` clears the icon and reports
  unsupported (prevents withdraw-with-no-tray stranded window); a later
  `start()` retries and reports supported again on success.
- `tests/core/test_console_widget.py` (new): one-menu-per-console,
  popup-reuses-menu, clear-restores-disabled/enabled, error-keyword tagging.
- `tests/core/test_error_dialog.py` (new): message + details toggle,
  grab restored to modal host / root-parent modal host, no grab clobber
  when parent had none.
- `tests/core/test_tooltip_widget.py` (new): widget-destroyed-while-showing
  leaves no dangling Toplevel; bottom-right tooltip flipped on-screen.
- `tests/core/test_hardware_wizard.py` (extended): temp-file cleanup on
  ffmpeg failure; close restores master's modal grab.
- `tests/core/test_tray.py` (extended): failed start reports unsupported;
  successful retry after failure reports supported.
- `OPENCODE_HANDOFF_app_widgets.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2206 passed, 14 skipped, 0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/app-widgets-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2206 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 4 source files + 4 new test files + 2 extended test files + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `console.py`: `_attach_context_menu` builds ONE `tk.Menu` child of the Text widget; the popup handler only posts it via `_popup_console_menu`, which returns `"break"` to suppress the app-wide Text menu. `grab_release()` is guarded with `TclError` in a finally block. Helper functions (`_copy_selection`, `_copy_all`, `_clear`) are standalone and each saves/restores widget state correctly.
  - `error_dialog.py`: `previous_grab` captured via `parent.grab_current()` before `grab_set()`, filtered to `(tk.Tk, tk.Toplevel)` only (menus excluded). `_close` destroys the dialog first, then conditionally re-grabs `previous_grab` only if `winfo_exists()` and no newer grab is held — correct LIFO restore. The `root.grab_current()` path correctly walks up to find the real modal host even when `parent` is the App root.
  - `hardware_wizard.py`: `_master_had_grab` snapshot in `__init__` before `grab_set()`; `_on_close` hands the grab back with the same guard (`winfo_exists` + `grab_current is None`). `_make_silent_clip` wraps `subprocess.run` and unlinks the mkstemp'd file on any exception before re-raising — covers ffmpeg-missing, bad args, and timeout.
  - `tray.py`: `_libs_available()` checks platform + deps only (flag-independent); `start()` gates on it and clears `_start_failed` on success; `is_supported()` returns `False` when `_start_failed` is set. A transient boot-time failure stays retryable; a successful retry is reportable. Partial-failure paths (Icon construction vs `safe_thread`) both leave `_icon=None` + flag set.
- **Test coverage of merged behavior**: New tests (`test_console_widget.py`, `test_error_dialog.py`, `test_tooltip_widget.py`) plus extensions (`test_hardware_wizard.py`, `test_tray.py`) cover all four fixes. The `_libs_available` retry path and the error-dialog `root-grab` path are both exercised. No coverage gaps found.

Result: clean. No source changes needed.

## Merge: opencode/asr-backends-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/asr-backends-review`): no conflicts,
no reconciliation needed. Merge commit 71bf36e on top of 2267360.

Files brought in by the review branch (5c257ec + a5f4ed0):
- `core/backends/cloud_stt.py`: real past-EOF detection via new
  `flac_slice_has_audio` ffprobe duration probe (byte-size check kept only as
  fast first cut; ~8 KiB past-EOF FLAC container defeated the old check),
  new `_json_body` helper converting truncated reads / non-JSON 200 bodies
  into clear RuntimeErrors, all three JSON response sites routed through it.
- `core/backends/google_cloud_stt.py`: unknown-duration STANDARD path now uses
  shared `flac_slice_has_audio` (imported from cloud_stt) alongside the
  byte-size first cut.
- `core/backends/nvidia_asr.py`: `_transformers_available` replaced by
  `_deps_available` probing transformers + torch + librosa via `find_spec`
  (with `optional_deps.activate()` first, never importing heavy modules);
  load path forces reinstall when partially installed.
- `core/backends/whisper_cpp.py`: `download_default_model` adds
  `timeout=60` to `urlopen` and unlinks the `.part` file on any
  network/HTTP failure before re-raising (handles closed after `with` so
  Windows unlink succeeds).
- `tests/core/test_backends.py`, `test_cloud_stt.py` (new),
  `test_google_cloud_stt.py`, `test_nvidia_asr.py`, `test_fixpack_C.py`:
  coverage for the new EOF probe, `_json_body` error paths, dep-probe and
  download-cleanup behavior.
- `OPENCODE_HANDOFF_asr_backends.md`: new review handoff doc.

Sanity-checked combined diff via `git show HEAD` / `git diff 2267360..HEAD`:
intent matches the review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations
  (101 files analyzed).
- Hermetic suite (`tests/` minus `tests/smoke/`): 2219 passed, 14 skipped,
  0 failures on the final run. One earlier full-suite run showed a single
  transient failure in `tests/core/test_search_dialog.py::
  test_open_selected_with_no_selection_is_a_noop` (`_tkinter.TclError`:
  missing tk.tcl); it passes in isolation and on rerun and is unrelated to
  this backends-only merge.
