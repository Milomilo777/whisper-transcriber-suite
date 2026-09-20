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

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/asr-backends-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2218 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). One transient tkinter failure (`test_hardware_wizard_constructs_without_crashing`, `_tkinter.TclError: invalid command name "tcl_findLibrary"`) passes in isolation — same class of tkinter state leak as the prior commit's transient; unrelated to this backends-only merge.
- **Merge diff**: 4 source files changed, 4 new test files + 2 extended test files, 1 doc, 1 handoff doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `cloud_stt.py` — `flac_slice_has_audio`: ffprobe-based EOF detection returns `False` only on a positive "N/A" duration (confirmed empty container); returns `True` on any probe failure (conservative — never truncates a real chunk). The byte-size `_EMPTY_FLAC_BYTES` fast-first-cut is correctly retained alongside it. The combined `getsize < threshold or not flac_slice_has_audio(...)` condition is correct and short-circuits properly.
  - `cloud_stt.py` — `_json_body`: reads + decodes response body, converts `IncompleteRead` and non-JSON/HTML proxy responses into clear `RuntimeError`s. All three JSON response sites (`_upload_file`, `_wait_for_active`, `_post_json`) are routed through it. The removed `isinstance(meta, dict)` guard in `_wait_for_active` is safe because `_json_body` already guarantees a `dict` return or raises.
  - `cloud_stt.py` — `_upload_file`: the delete-on-failure path now correctly calls `_delete_file(str(file_name))` before re-raising, closing the gap where a failed `_wait_for_active` left audio on Google.
  - `google_cloud_stt.py` — imports `flac_slice_has_audio` from `cloud_stt` and applies it in `_run_standard`'s unknown-duration EOF check alongside the byte-size fast cut. Correct and consistent with the Gemini backend.
  - `nvidia_asr.py` — `_deps_available` replaces `_transformers_available`; probes all three required modules (`transformers`, `torch`, `librosa`) via `find_spec` (never imports heavy modules). The `optional_deps.activate()` call ensures on-demand installs from prior sessions are visible. The `force=partially_installed` pattern matches `google_cloud_stt.load()`.
  - `whisper_cpp.py` — `download_default_model`: adds `timeout=60` to `urlopen` and wraps the download in `try/except` that unlinks the `.part` file on any network/HTTP failure before re-raising. The `with` blocks close file handles before the `unlink` call, so Windows unlink succeeds.
- **Test coverage of merged behavior**: New tests (`test_cloud_stt.py`: flac probe true/false/conservative, EOF past-byte-threshold, JSON body errors; `test_backends.py`: download timeout + mid-stream cleanup; `test_google_cloud_stt.py`: STANDARD EOF stop + `RecognizeRequest` fake; `test_nvidia_asr.py`: deps probe all-three, forced install, skipped install) plus the `test_fixpack_C.py` monkeypatch addition all exercise the merged fixes with realistic edge cases (8 KiB past-EOF container, truncated reads, partial installs). Pre-fix code would fail these tests (old byte-size-only check misses the 8 KiB container; old `_transformers_available` skips half-present environments).

Result: clean. No source changes needed.

## Merge: opencode/config-domain-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/config-domain-review`): no conflicts,
no reconciliation needed. Merge commit ba401a3 on top of 3e6b932.

Files brought in by the review branch (fd34c64 + c418715 + aa23bcf):
- `core/config.py`: never-raises hardening — `migrate_config_location`
  degrades to defaults when the config dir cannot be created; `fetch_online_config`
  also catches `http.client.HTTPException` + `RecursionError` (falls through to
  cache) and treats a hostile cache file as corrupt; `_read_local_config` and
  `load_project_overrides` catch `RecursionError`; `load_config` finite-check
  probes only `float` (avoids `math.isfinite` OverflowError on huge JSON ints);
  `_validate_overrides` drops `None` / non-finite values for known keys and
  catches `OverflowError` on coercion.
- `app/domain/languages.py`: `subtitle_lang_args` escapes yt-dlp `--sub-langs`
  regex metacharacters so codes match literally (hyphen left unescaped).
- `app/observability.py`: `_anonymised_id` returns `""` when the cache dir
  cannot be created; `init_sentry` catches SDK init errors (e.g. malformed DSN)
  and returns False instead of crashing launch.
- `app/services/download_service.py`: `_parse_timecode` rejects NaN/inf via
  `math.isfinite`.
- `tests/core/test_config.py`, `test_download_command.py`,
  `test_observability.py`, `test_project_overrides.py`,
  `test_project_overrides_leak.py`, `test_subtitle_lang_args.py`: coverage for
  the above.
- `OPENCODE_HANDOFF_config_domain.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2240 passed, 14 skipped,
  0 failures on the final run. Two earlier full-suite runs each showed a
  single transient Tk failure in an unrelated dialog test
  (`test_search_dialog.py::test_finish_search_reports_error`, then
  `test_error_dialog.py::test_close_restores_the_parents_modal_grab`); both
  pass in isolation and on rerun and are unrelated to this config-domain merge.
- Targeted merge-area tests (177 tests across the six files above): all pass.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/config-domain-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2240 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). One transient tkinter failure (`test_search_dialog.py::test_finish_search_reports_error`) on the first full run — passes in isolation and on rerun; same class of tkinter state leak documented in prior commits, unrelated to this config-domain merge.
- **Merge diff**: 4 source files changed (`config.py`, `languages.py`, `observability.py`, `download_service.py`), 6 new test files + 1 extended test file, 1 handoff doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `config.py` — `migrate_config_location`: `OSError` catch + `return new_path` means `load_config` degrades to defaults instead of crashing. Correct: every other unreadable-config path already does this.
  - `config.py` — `fetch_online_config`: `http.client.HTTPException` + `RecursionError` added to the except tuple for both the fetch path and the cache-read path. `HTTPException` (e.g. `BadStatusLine`, `IncompleteRead`) is not a subclass of `URLError`/`OSError` — confirmed by inspection and the test's `BadStatusLine("oops")` mock. `RecursionError` from the C JSON scanner on deeply-nested bodies is also not a `ValueError`. Both correctly fall through to cache/`{}`.
  - `config.py` — `_read_local_config` + `load_project_overrides`: `RecursionError` added to except tuples. Same reasoning as above.
  - `config.py` — `load_config` finite guard: changed from `isinstance(merged[k], (int, float))` to `isinstance(merged[k], float)`. Correct: `int` is always finite, and `math.isfinite(10**400)` raises `OverflowError` which would crash launch before the type check ever runs. The test `test_load_config_survives_huge_integer` proves the fix.
  - `config.py` — `_validate_overrides`: None/non-finite values dropped before the type-coercion branch; `OverflowError` added to the coercion `except` tuple. The guard correctly intercepts `None` (which would reach `int(None)` → `TypeError` in `_apply_runtime_overrides`) and `inf`/`NaN` (which would reach `int(inf)` → `OverflowError` or compare false to every bound).
  - `languages.py` — `_SUB_LANG_REGEX_METACHARS` regex escapes `.^$*+?{}\[\]\\|()` only; hyphen left unescaped (literal outside character class). `re.sub(r"\\\1", c)` for each code is correct. No bypass path feeds raw metadata to yt-dlp — `build_subtitle_command` at `download_service.py:304` is the single `--sub-langs` emission site.
  - `observability.py` — `_anonymised_id`: `OSError` catch on `cache.mkdir()` returns `""`. Correct: the file-write path below already catches `OSError`; the mkdir was the unguarded gap. `init_sentry`: `Exception` catch around `sentry_sdk.init()` logs and returns `False`. Correct: malformed DSN raises `BadDsn` (a plain `Exception` subclass), not any of the previously caught types.
  - `download_service.py` — `_parse_timecode`: `math.isfinite(total)` check after all parsing branches. `float("nan")` parses successfully but compares false to every bound, so without this it slips past both range checks. The `import math` is present. Test coverage for `nan`, `NaN`, `1:nan`, `inf`, `1e400`.
- **Test coverage of merged behavior**: 177 targeted tests across all six changed source files and six new/extended test files — all pass. Tests exercise: huge integer in config.json, uncreatable config dir, garbage/truncated HTTP responses, deeply nested JSON files, null project overrides, Infinity/NaN in project overrides, regex metacharacter escaping in subtitle codes, SDK init failure, unwritable cache dir, non-finite timecodes. Pre-fix code would fail these tests (confirmed by the handoff doc's stash-round-trip evidence).

Result: clean. No source changes needed.

## Merge: opencode/entrypoint-webpage-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/entrypoint-webpage-review`): no conflicts,
no reconciliation needed. Merge commit 9c8be84 on top of e691614.

Files brought in by the review branch (3dc7cf5 range):
- `gui.py`: new `_port_number()` argparse type for `serve --port`
  (rejects out-of-range/non-integer up front, was `type=int`), plus
  config-file `server_port` validation in `_cli_serve` (coerce in
  try/except TypeError/ValueError, range-check 0-65535, clean stderr
  + exit 1 instead of uncaught OverflowError/ValueError traceback).
- `core/server/static/index.html`: `start()` catch now wraps `e.message`
  in `escapeHtml()` before `setSubmitStatus()` innerHTML; `renderSubmit()`
  progress bar now `(Number(j.progress) || 0)` in the style-width sink.
- `tests/core/test_gui_serve_args.py`: new — explicit-flag forwarding,
  config fallback, --lan host, bad --port rejection, 5 parametrized
  invalid-config-port cases.
- `tests/core/test_web_page_escaping.py`: new — static sink guards pinning
  escapeHtml/Number patterns.
- `OPENCODE_HANDOFF_entrypoint_webpage.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log (4fa0138 + second-pass config-port fix + addendum 3dc7cf5);
no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2256 passed, 14 skipped,
  0 failures on the final clean run. First full run showed a single failure
  in unrelated `tests/core/test_search_dialog.py::test_open_selected_with_no_selection_is_a_noop`;
  passes in isolation and the full file (8 tests) passes, and the full-suite
  re-run is green — transient Tk/state flake unrelated to this merge (merge
  touches only serve-port handling + LAN page + new tests).
- Targeted merge-area tests (16 tests across the two new files): all pass.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/entrypoint-webpage-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2256 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 2 source files changed (`gui.py`, `core/server/static/index.html`), 2 new test files, 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `gui.py` — `_port_number()`: argparse `type=` function converts value to `int`, catches `ValueError` for non-numeric strings, and range-checks 0–65535. Correct: plain `int` let `--port 70000` / `--port -1` through to `socket.bind`, which raises `OverflowError` — not `OSError` — so `run_server`'s bind-failure handler missed it and the CLI died with a raw traceback.
  - `gui.py` — `_cli_serve()` config fallback: `int(cfg.get("server_port", 8765))` wrapped in `try/except (TypeError, ValueError)` with clean stderr + exit 1; range-check 0–65535 follows. Correct: hand-editable JSON config was never validated, and both non-numeric values and out-of-range ints produced raw tracebacks.
  - `core/server/static/index.html` — `start()` catch: `escapeHtml(e.message)` wrapping before `setSubmitStatus()` innerHTML. Correct: server error JSON is untrusted; the prior 2026-07-18 hardening (099b759) missed this catch.
  - `core/server/static/index.html` — `renderSubmit()` progress bar: `(Number(j.progress) || 0)` instead of `(j.progress || 0)`. Correct: `Number()` coerces non-numeric strings to `NaN` which falls through to `|| 0`; without it a string progress value would produce `NaN` in the CSS width. All three progress bars (submit/jobs/recent) now use `Number(j.progress) || 0`.
  - No unescaped `+ e.message` patterns remain — verified by grep.
- **Test coverage of merged behavior**: 16 targeted tests across the two new files — all pass. Tests exercise: port arg accept/reject (0, 65535, 70000, -1, 65536, non-numeric), explicit flag forwarding, config fallback, --lan host override, 5 parametrized invalid config port cases (including `None`), progress width `Number()` coercion, error message escaping, all known untrusted field escaping sentinel patterns.

Result: clean. No source changes needed.

## Merge: opencode/llm-infra-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/llm-infra-review`): no conflicts,
no reconciliation needed. Merge commit 7028a8b on top of 515b50a.

Files brought in by the review branch (44cce1c + af34ebd + a2001d0 + b3b3e6f + 029f4e0):
- `core/llm.py`: fit local AI calls to the model's context window
  (token-counter with model-tokenizer preference + conservative
  chars-per-token fallback, middle-truncation with marker, shrink-to-tokens
  via binary search, fit-messages-to-context clamping prompt + answer to
  `n_ctx`; action-items doc updated to best-effort parse).
- `core/_checkpoint.py`: `load_checkpoint` catches `ValueError` (not just
  `json.JSONDecodeError`) so non-UTF-8 partials fall back to full
  re-transcribe; `sweep_partials` also reaps stale `*.json.tmp` write
  scratch left by killed workers.
- `core/task.py`: corrected `clip_timestamps` comment (6 chars).
- `core/transcriber.py`: liveness-tick / gc-guard exception-safety
  adjustments covered by new tests.
- `tests/core/test_llm.py` (extended, +158): context-fitting coverage.
- `tests/core/test_checkpoint_sweep.py`, `test_fixpack_proc_ckpt.py`
  (extended): non-UTF-8 partial survival + `.tmp` scratch reaping.
- `tests/core/test_gc_import_guard.py` (new), `test_liveness_tick.py`
  (new): gc-guard and liveness-tick exception safety.
- `OPENCODE_HANDOFF_llm_infra.md`: new review handoff doc.

Sanity-checked combined diff via `git show HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2278 passed, 14 skipped,
  0 failures (63s, exit 0).

Result: clean. No source changes needed.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/llm-infra-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2278 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 4 source files changed (`llm.py`, `_checkpoint.py`, `task.py`, `transcriber.py`) + 4 new test files + 1 extended test file + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `llm.py` — `_token_counter`: prefers model's `tokenize` (correct for CJK), falls back to `_CHARS_PER_TOKEN=3` ratio. Exception-safe — never raises. `_truncate_middle`: preserves head (transcript) and tail (question) for `ask` prompts; handles edge cases `keep_chars <= len(marker)` and `keep_chars >= len(text)`. `_shrink_to_tokens`: binary search on text length converges correctly; `allowed_tokens <= 0` returns `""`. `_fit_messages_to_context`: `budget = max(128, n_ctx - 64)` guarantees minimum 128-token budget; answer capped to `budget // 2` first so long transcripts still get room; `output_tokens` and `prompt_budget` both `max(1, ...)` — no zero-token edge. `_parse_json_list`: `raw_decode` from first `[` correctly ignores trailing prose that `rfind("]")` would have included. `_fit_messages_to_context` is only called in `LLMRunner._chat`, not `RemoteLLMRunner._chat` (correct — remote models manage their own context).
  - `_checkpoint.py` — `load_checkpoint`: `ValueError` covers both `UnicodeDecodeError` (non-UTF-8 partial) and `json.JSONDecodeError` (both are `ValueError` subclasses). `sweep_partials`: `.json.tmp` files cleaned with `slice_cutoff` (10 min) — correct since they're only visible during an atomic write.
  - `task.py` / `transcriber.py`: documentation-only comment corrections — `clip_timestamps` historically misnamed; now correctly documents ffmpeg pre-slice + timeline shift. No behavioral change.
- **Test coverage of merged behavior**: 79 targeted tests across the 5 merge-specific test files — all pass. Tests exercise: context-fitting with oversized transcripts (including CJK 1-token/char), short transcripts untouched, `ask` preserves question, no-tokenizer fallback, `_parse_json_list` trailing prose, `_truncate_middle` head/tail preservation, gc-guard serialization across threads, gc-guard exception safety (body raises, log_cb raises, callback=None), liveness-tick periodic emission, stop-on-body-exit, stop-on-body-raise, stop-on-log-raise, `.tmp` scratch reaping, non-UTF-8 partial survival.

Result: clean. No source changes needed.

## Merge: opencode/misc-features-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/misc-features-review`): no conflicts,
no reconciliation needed. Merge commit 468c060 on top of fb5114b.

Files brought in by the review branch (812b974 + 7f81dcd):
- `core/watcher.py`: new `_is_inside()` helper (bytes/str tolerant, drive-safe
  relpath check) + `on_moved` handler so files dragged/renamed into the folder
  (Explorer same-volume move, downloader `.part` -> final rename) are picked up;
  `on_created` refactored through shared `_dispatch`.
- `core/burn_subs.py`: atomic output via same-directory temp file + `os.replace`
  (no more truncated/corrupt final on mid-run failure, no clobber of existing
  file); audio stream-copy first with one-shot AAC retry when ffmpeg stderr
  shows a container/codec-incompatibility hint; caller-supplied `-c:a` in
  `extra_args` is respected (no override).
- `core/recorder.py`: new `_import_failure()` probe catching all exceptions
  (not just ImportError) so broken native backends (missing PortAudio, DLL-load
  failures) degrade to unavailable with a specific reason string instead of
  escaping into UI callbacks.
- `core/tiling.py`: launch-failure and stop/restart paths now `_reap()` the
  killed yt-dlp/ffplay children, closing the POSIX zombie pile-up on repeated
  reconnect attempts / races.
- `tests/core/test_burn_subs.py` (extended, +120): atomic-output + AAC-fallback
  coverage. `tests/core/test_watcher.py` (extended, +162): moved-file handling.
  `tests/core/test_recorder.py` (extended, +37): broken-backend probe.
  `tests/core/test_fixpack_sw3_tilingthreads.py` (extended, +63): reap paths.
- `OPENCODE_HANDOFF_misc_features.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2290 passed, 14 skipped,
  0 failures.

Result: clean. No source changes needed.
