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

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/misc-features-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2290 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 4 source files changed (`watcher.py`, `burn_subs.py`, `recorder.py`, `tiling.py`) + 4 extended test files + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `watcher.py` — `_is_inside`: bytes decode, empty-path, cross-drive `(OSError, ValueError)` guards all present; `on_created` needs no inside check (non-recursive schedule); no-attr `dest_path` defaults to ignored string. `on_moved` correctly dispatches `event.dest_path` only when `_is_inside(folder, dest)` returns True.
  - `burn_subs.py` — Atomic output: `mkstemp` in same directory as `out_path` guarantees `os.replace` is atomic; `finally` unlink covers all failure paths. AAC retry: `_container_rejected_audio` matches only the two known container/codec-incompatibility phrases; `_extra_args_set_audio_codec` respects caller-supplied `-c:a`; retry loop terminal logic (`codec == codecs[-1]` raise, no retry on generic errors/timeout, caller-codec skip) all correct.
  - `recorder.py` — `_import_failure`: `except Exception` (not `BaseException`, so no `KeyboardInterrupt` swallow); double-import cost is `sys.modules`-cached; non-ImportError failures now return False and `availability_reason()` reports the real cause.
  - `tiling.py` — `_reap` calls on both launch-failure and not-published paths mirror `_terminate`; `_reap` is best-effort `wait(timeout=2)` that never raises; no-op/harmless on Windows.
- **Test coverage of merged behavior**: 39 targeted tests across the 4 merge-specific test files — all pass. Tests exercise: moved-in media dispatch (including bytes dest), moved-out ignored, non-media/dirs ignored, `on_created` still works, `on_error` hook fires for moved events, atomic output (no clobber on failure, temp cleanup), AAC retry (container rejection, caller-codec skip, retry failure), broken-backend probe (OSError escapes), reap on launch-failure and not-published paths.

Result: clean. No source changes needed.

## Merge: opencode/model-hub-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/model-hub-review`): no conflicts,
no reconciliation needed. Merge commit 0c751f4 on top of 9c61b27
(second parent 94c2589).

Files brought in by the review branch (09fc000 + 149da5b + 94c2589):
- `core/history.py`: new `_is_transient_lock_error()` (SQLITE_BUSY /
  SQLITE_LOCKED name + "database is locked" message fallback) so a
  lock held by another connection skips this open's `integrity_check`
  with a warning instead of renaming a healthy `history.db` to
  `.corrupt` and wiping history.
- `core/hub.py`: new `is_safe_model_folder_name()` (single-component
  check: no separators/NUL, no `.`/`..`, platform-parser name round-trip
  for Windows drive/ADS forms) and `model_folder_for()` now rejects
  unsafe names with ValueError (callers already guard on ValueError).
- `core/model_manager.py`: `_merged_catalog()` drops online-catalog
  entries with unsafe `name`, coerces hostile display fields (`label` /
  `info` to str, `approx_size_gb` to float); `ensure_model()` requires
  `model.bin` for no-manifest installs (no more partial-folder
  false-positive), treats md5-manifest fetch failure as best-effort
  offline use, resumes interrupted zip downloads via Range (bounded by
  MAX_DOWNLOAD_ATTEMPTS), clears stale `last_mismatches` after a
  successful verify retry, and reports post-download cancellation as
  DownloadCancelled (both mirror and HF-fallback paths).
- `tests/core/test_history_db.py` (extended, +107): lock-vs-corruption
  coverage. `tests/core/test_hub.py` (extended, +77): traversal-name
  rejection. `tests/core/test_model_manager.py` (extended, +403):
  catalog hardening, partial-install, resume, verify-retry, cancel
  coverage.
- `OPENCODE_HANDOFF_model_hub.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2316 passed, 14 skipped,
  0 failures.

Result: clean. No source changes needed.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/model-hub-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2316 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 3 source files changed (`history.py`, `hub.py`, `model_manager.py`) + 3 extended test files + 1 new doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `history.py` — `_is_transient_lock_error` correctly identifies `SQLITE_BUSY`/`SQLITE_LOCKED` by error name and message fallback; `_check_integrity_or_recover` now skips integrity check on lock instead of rotating a healthy DB. No silent corruption classification.
  - `hub.py` — `is_safe_model_folder_name` rejects separators, `.`/`..`, NUL, and platform-specific unsafe forms; `model_folder_for` raises `ValueError` for unsafe names (callers already handle). No path traversal possible.
  - `model_manager.py` — `_merged_catalog` drops entries with unsafe `name`, coerces hostile display fields (`label`/`info` to str, `approx_size_gb` to float); `ensure_model` requires `model.bin` for no-manifest installs, treats manifest fetch failure as best-effort offline use, resumes interrupted downloads via Range (bounded by MAX_DOWNLOAD_ATTEMPTS), clears stale `last_mismatches` after successful verify retry, and raises `DownloadCancelled` on post-download cancellation (both mirror and HF-fallback paths). All logic correct.
- **Test coverage of merged behavior**: 20+ targeted tests across the 3 merge-specific test files — all pass. Tests exercise: lock vs corruption detection, traversal name rejection, catalog hardening, partial-install detection, resume after transient error, verify retry, cancellation handling, and hostile display field coercion.

Result: clean. No source changes needed.

## Merge: opencode/model-loading-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/model-loading-review`): no conflicts,
no reconciliation needed. Merge commit 1cc84a8 on top of 1a83484
(second parent e39878b).

Files brought in by the review branch (bb061a7 + e39878b):
- `app/dialogs/model_loading.py`: new `_compute_position()` helper
  (screen-centre fallback when master is not viewable, e.g. minimised
  window reporting -32000 on Windows; clamps to non-negative only when
  the parent itself is on the primary display so monitors left/above
  keep their negative coordinates) plus `f"+{x}+{y}"` geometry form for
  absolute negative positions; new `_closed` flag making `cancel()` and
  `mark_success_and_close()` idempotent so a deferred `post_to_main`
  success callback arriving after a user Cancel cannot flip `success`
  back to True.
- `tests/core/test_model_loading_dialog.py` (new): coverage for the
  close-race guard and the multi-monitor centring maths.
- `OPENCODE_HANDOFF_model_loading.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2325 passed, 14 skipped,
  0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/model-loading-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2325 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 1 source file changed (`model_loading.py`) + 1 new test file + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `_compute_position()`: correctly falls back to screen-centring when `master.winfo_viewable()` returns False (minimised window); when viewable, computes relative to parent and only clamps to non-negative when the parent's root coordinates are within the primary display bounds (`0 <= rootx < screenwidth` and `0 <= rooty < screenheight`). Parents on secondary monitors (negative or ≥ screenwidth coordinates) keep their absolute positions, preserving Tk's `"+-N"` geometry form for negative x/y.
  - `_closed` flag: set to True in whichever close path (`cancel()` or `mark_success_and_close()`) runs first; both methods early-return when `_closed` is already True, making them idempotent. This prevents a deferred `post_to_main(mark_success_and_close)` callback from flipping `success` back to True after a user Cancel has already set it to False and destroyed the dialog.
  - Caller contract: `_release_pending_load` in `transcription_service.py:118-119` posts either `mark_success_and_close` (on success) or `cancel` (on failure) via `post_to_main`, which is a deferred main-thread queue. The `ensure_worker_ready` method reads `dialog.success` after `wait_window` returns (line 346). The `_closed` guard correctly ensures the first close owns the final `success` value, matching the caller's expectation.
- **Test coverage of merged behavior**: 9 targeted tests (all pass) — pure `_compute_position` cases (primary parent, on-screen clamp, negative-coordinate parent, minimised fallback), close-path ordering (late-ready after Cancel, Cancel after ready, repeated closes), and geometry integration (negative-coordinate parent, minimised parent). The new tests confirm the fix: pre-fix `_compute_position` would return `(0, 150)` for the negative-coordinate parent test; pre-fix close ordering would set `success = True` after `cancel(); mark_success_and_close()`.

Result: clean. No source changes needed.

## Merge: opencode/platform-scripts-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/platform-scripts-review`): no conflicts,
no reconciliation needed. Merge commit 3170354 on top of 1874254
(second parent 2eb66e8).

Files brought in by the review branch (5fe27cc + 2eb66e8):
- `platform/linux/install.sh`: `trap 'rm -rf "$TMP"' EXIT` for static-ffmpeg
  temp dir; `else warn ... unexpected static ffmpeg archive layout` so a
  layout change no longer fails silently; quoted desktop `Exec="..."` so
  paths with spaces launch.
- `platform/linux/uninstall.sh`: early guard requiring `gui.py` at repo root
  (fails fast with clear error when run from wrong checkout).
- `platform/linux/update.sh`: `[ -e .git ]` instead of `[ -d .git ]` so
  worktree checkouts (gitfile) still pull; `[ -x "$VENV/bin/python" ]`
  instead of `[ -d "$VENV" ]` so a broken venv dir is recreated/repaired.
- `platform/macos/install.command`: braced `if [ -n "$p" ]; then ln ...; fi`
  in `link_ffmpeg_into_bin` (shellcheck style, same no-op behaviour when
  absent); `trap 'rm -rf "$TMP"' EXIT` plus explicit `rm -rf "$TMP"` on the
  success path so abort no longer leaks the temp dir.
- `OPENCODE_HANDOFF_platform_scripts.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log (TMP-leak + silent-no-op second pass on top of 6-bug
close-out); no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2325 passed, 14 skipped,
  0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/platform-scripts-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: full run exits 0 (all pass, 14 skipped, `tests/` minus `tests/smoke/`). One transient TclError on `test_find_replace_rejects_whitespace_only_needle` in the `-x` run — same class of tkinter init flake documented in prior merge commits; passes on full-suite rerun and is unrelated to this shell-script-only merge.
- **Merge diff**: merge commit 3170354 is a no-op merge for the working tree — only `INTEGRATION_HANDOFF.md` was updated in the commit itself, because the branch's script changes were already present in the tree. Verified via `git diff 1874254..2eb66e8` that the branch brought in the expected changes.
- **Adversarial review of changes**:
  - `platform/linux/install.sh` — `trap 'rm -rf "$TMP"' EXIT` ensures the static-ffmpeg temp dir is cleaned on abort; the `else warn ... unexpected static ffmpeg archive layout` branch catches layout changes that previously failed silently; desktop `Exec="..."` is properly quoted for paths with spaces. All present and correct.
  - `platform/linux/uninstall.sh` — early guard `[ ! -f "$REPO_ROOT/gui.py" ]` fails fast with a clear error when run from the wrong checkout. Present and correct.
  - `platform/linux/update.sh` — `[ -e .git ]` instead of `[ -d .git ]` so git worktree checkouts (gitfile) still pull; `[ -x "$VENV/bin/python" ]` instead of `[ -d "$VENV" ]` so a broken venv dir is recreated/repaired. Both present and correct.
  - `platform/macos/install.command` — braced `if [ -n "$p" ]; then ln -sf "$p" ...; fi` in `link_ffmpeg_into_bin` (shellcheck style); `trap 'rm -rf "$TMP"' EXIT` plus explicit `rm -rf "$TMP"` on the success path. Both present and correct.
  - No conflict markers, no dropped lines, no duplicated logic across any of the 4 script files.
- **Test coverage**: platform scripts are shell scripts (no Python test coverage), but all existing Python tests pass. The merge is documentation/shell-script only — no Python source or test files were modified.

Result: clean. No source changes needed.

## Merge: opencode/search-chapters-infra-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/search-chapters-infra-review`): no conflicts,
no reconciliation needed. Merge commit e25b057 on top of 40738d6
(second parent 6a5915e).

Files brought in by the review branch (cb7e07a + d4adf4e + 9340a74 + 6a5915e):
- `core/_proc.py`: `kill_process_tree` POSIX safety guard — resolves own
  pgid via `os.getpgid(0)` and refuses to `killpg` when the child's pgid
  equals this process's group (falls through to parent-only signal), so a
  caller that skipped `new_session_kwargs()` can never make the app kill
  itself. Docstring updated accordingly.
- `core/logging_setup.py`: `_prune_worker_logs()` + `WORKER_LOG_KEEP = 10` /
  `WORKER_LOG_MAX_AGE_DAYS = 14` / `_WORKER_LOG_GLOBS` restricted to the two
  known producers (`worker-*.log*`, `voiceclone-worker-*.log*`); called from
  `setup_logging()` so per-process worker logs don't accumulate forever.
  Never raises; keeps newest 10, only unlinks files older than cutoff.
- `core/search.py`: `_read_segments` returns `None` on `OSError` (transient
  read failure keeps existing index, unmarked for retry) vs `[]` on
  corrupt JSON; `index_file` rebuilds when embeddings missing (dependency
  installed later); `reindex_all_history` per-file try/except so one bad
  transcript can't abort the walk; `search` falls back to FTS on semantic
  failure; `_fts_match_query` quotes every token (implicit AND, operator
  literals can't crash sqlite); BM25 score mapped via logistic
  `1/(1+exp(min(rank,500)))` instead of `1/(1+max(0,rank))` which clamped
  every negative FTS5 rank to exactly 1.0. Drops unused `re` import.
- `tests/core/test_search.py`: new/extended coverage for the above
  (multi-word AND, operator literals, score ordering, transient-read keep,
  embeddings backfill, per-file skip, semantic-fallback).
- `tests/core/test_proc.py`: additions covering the own-group refusal guard.
- `tests/core/test_logging_setup.py`: new file covering prune keep-count /
  age cutoff / glob scoping.
- `OPENCODE_HANDOFF_search_chapters_infra.md`: new review handoff doc.

Sanity-checked combined diff via `git show HEAD` / `git diff HEAD~1 HEAD`:
intent matches the review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2335 passed, 14 skipped,
  0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/search-chapters-infra-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2335 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 3 source files changed (`_proc.py`, `logging_setup.py`, `search.py`) + 2 new test files + 1 extended test file + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `_proc.py` — own-group guard: `os.getpgid(0)` resolves this process's pgid; when it matches the child's pgid the `killpg` path is skipped, falling through to parent-only `process.kill()`/`terminate()`. Correct: prevents a caller that forgot `new_session_kwargs()` from killing the entire app.
  - `logging_setup.py` — `_prune_worker_logs`: globs scoped to `worker-*.log*` and `voiceclone-worker-*.log*` only (bare `*worker-*.log*` would catch unrelated files); sorts by mtime descending, keeps newest `WORKER_LOG_KEEP=10`, age-checks with `WORKER_LOG_MAX_AGE_DAYS=14`; `OSError` on stat/unlink skipped gracefully. Called from `setup_logging()` on every startup.
  - `search.py` — `_read_segments`: `OSError` → `None` (transient read failure keeps existing index); `JSONDecodeError`/`UnicodeDecodeError` → `[]` (corrupt file marks for retry). `index_file`: checks `_file_has_embeddings` when an embedder is provided (backfill after dependency install); returns 0 on `segments is None`. `reindex_all_history`: per-file `try/except` so one bad transcript cannot abort the walk. `search`: `try/except` around `_semantic_query` falls back to FTS. `_fts_match_query`: per-token quoting prevents operator literals from crashing sqlite. BM25 score: `1/(1+exp(min(rank,500)))` logistic map replaces `1/(1+max(0,rank))` which clamped every negative rank to exactly 1.0.
  - No untested behavior: 3 new/extended test files (`test_search.py`, `test_proc.py`, `test_logging_setup.py`) cover every merged fix — multi-word AND, operator literals, score ordering, transient-read keep, embeddings backfill, per-file skip, semantic-fallback, own-group refusal, prune keep-count/age/glob scoping.
- **Test coverage of merged behavior**: All 2335 tests pass. The 3 merge-specific test files exercise every change with realistic edge cases (file locked by AV, corrupt JSON, operator literals in FTS5, own-group PID match). Pre-fix code would fail these tests (old `_read_segments` deleted existing rows on OSError; old `_fts_match_query` used whole-query quoting; old BM25 score was always 1.0).

Result: clean. No source changes needed.

## Merge: opencode/server-hardening (2026-09-21)

Clean merge (`git merge --no-ff opencode/server-hardening`): no conflicts,
no reconciliation needed. Merge commit 9126863 on top of db854ee
(second parent ee97fd0).

Files brought in by the review branch (50f66cc + ee97fd0):
- `core/server/httpd.py`: HTTPS/TLS serving, SSRF-guarded outgoing
  webhooks, OpenAI-compatible transcription route.
- `core/server/tls.py` (new): self-signed cert generation under the
  app user-data folder.
- `core/server/jobs.py`: webhook dispatch + hardened `is_safe_url`
  against legacy numeric IPv4 SSRF bypass (second-pass re-check).
- `core/server/__init__.py`: `run_server(https=..., webhook_url=...)`
  plumbing.
- `core/config.py`: `server_https_enabled` / `server_webhook_url` keys.
- `app/app.py`, `app/widgets/tabs.py`, `gui.py`: `--https` / `--webhook`
  CLI flags, config fallback, UI toggles; `_cli_serve` forwards
  `https` + `webhook_url` to `run_server`.
- `tests/core/test_server_openai.py`, `test_server_tls.py`,
  `test_server_webhooks.py` (new): coverage for the above.
- `tests/core/test_fixpack_D.py`, `test_fixpack_bl_appui.py`: extended
  for numeric-IP SSRF cases and server start signature.
- `whisper_project_onedir.spec`, `whisper_project_onefile.spec`:
  packaging for new module.
- `OPENCODE_HANDOFF_server_hardening.md`: new review handoff doc.

Sanity-checked combined diff via `git show HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2378 passed,
  14 skipped, 0 failures (2392 collected) on the final clean run.
  Two earlier full-suite runs each showed a single transient Tk
  environment failure in an unrelated dialog test
  (`test_transcript_viewer.py::test_viewer_search_filters_the_tree`
  with `Can't find a usable init.tcl`, then
  `test_search_dialog.py::test_dialog_builds_and_starts_indexing`
  with `invalid command name "tcl_findLibrary"`); both pass on rerun
  and are unrelated to this server-only merge.

Post-merge integration fix (no conflict, but combined logic needed it):
- `tests/core/test_gui_serve_args.py::test_cli_serve_forwards_explicit_flags`
  asserted exact `captured ==` with 4 keys; the hardening branch added
  `https` + `webhook_url` forwarding, so it failed with 2 extra items.
  Preserved BOTH sides: updated the expected dict to include
  `"https": False, "webhook_url": ""`, and added 2 new tests
  (`test_cli_serve_forwards_https_and_webhook_flags`,
  `test_cli_serve_falls_back_to_https_webhook_config`) covering
  flag + config fallback forwarding neither side had on its own.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/server-hardening` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2378 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). Matches the prior commit's claim exactly.
- **Merge diff**: 5 source files changed (`httpd.py`, `tls.py` new, `jobs.py`, `__init__.py`, `config.py`), 3 files with UI/CLI plumbing (`app.py`, `tabs.py`, `gui.py`), 3 new test files + 2 extended test files + 2 packaging specs + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `httpd.py` — `_receive_upload` refactored from `_create_upload_job`: now raises `_UploadError` instead of sending error JSON + returning, allowing both the existing job API and the new OpenAI route to share the upload path. Error cleanup (unlink tmp) and error propagation both correct. `_create_upload_job` catches `_UploadError` and sends JSON error; `_openai_transcribe` catches it and sends OpenAI envelope error.
  - `httpd.py` — OpenAI-compatible route: `parse_route` correctly maps `/v1/models` and `/v1/audio/transcriptions`. `_openai_transcribe` streams upload, copies file range, submits to queue, then blocks via `_wait_for_job` polling `job.status` with `time.sleep(0.1)` — correct for the synchronous OpenAI contract. `_wait_for_job` checks `manager.stopped` to avoid hanging on shutdown. `_openai_send_result` reads the JSON sidecar and renders json/text/srt/vtt/verbose_json via `get_writer` for srt/vtt (reuses existing code). All error paths use `openai_error_payload` envelope.
  - `httpd.py` — `_bearer_token()` extracts `Authorization: Bearer <token>` for OpenAI SDK compatibility. `_authed` combines `X-Auth-Token` and bearer (OR). Correct.
  - `httpd.py` — `JobHTTPServer.__init__` wraps `self.socket` with `ssl_context.wrap_socket(server_side=True)` before `serve_forever` — all accepted connections are TLS from first byte. `ssl_context` parameter is optional (default None = no TLS).
  - `tls.py` — Full DER/ASN.1 encoder for self-signed P-256 ECDSA certificate. `_parse_legacy_ipv4` is in `jobs.py`, not `tls.py` — correct separation. `ensure_certificate` checks existing pair loads via `ssl.SSLContext.load_cert_chain` before reusing; regenerates on any `OSError`/`SSLError`/`ValueError`. `_pair_loads` validates both files exist AND OpenSSL accepts them. `build_server_ssl_context` sets `minimum_version = TLSv1_2`.
  - `jobs.py` — `is_safe_url` now calls `_parse_legacy_ipv4(literal)` when `ipaddress.ip_address()` fails, catching `inet_aton`-style numeric forms (decimal, octal, hex) that bypass `ipaddress` but a fetch stack may still interpret as loopback. The `_addr_blocked` check applies to the resolved address. Correct: `2130706433` → `127.0.0.1` → blocked.
  - `jobs.py` — `_fire_webhook`: only fires on `STATUS_FINISHED` / `STATUS_ERROR` (not `STATUS_CANCELLED`); runs `sender(url, payload)` on a daemon thread so a slow endpoint never blocks the job worker or keeps the process alive. `post_webhook` applies `is_safe_url` gate and uses `_NoRedirectHandler` to prevent SSRF via 30x bounce. Bounded read (`_WEBHOOK_MAX_RESPONSE_BYTES`) prevents a hostile endpoint from streaming forever.
  - `jobs.py` — `Job.detected_language` field populated after transcription completes; used in webhook payload and OpenAI verbose_json response. `JobManager.stopped` property exposes `_stop.is_set()` for the OpenAI polling loop.
  - `__init__.py` — `ServerHandle.start` gains `https` and `webhook_url` params; HTTPS creates `ssl_context` via `build_server_ssl_context()`, `webhook_url` passed to `JobManager`. `reachable_urls` switches scheme to `https://` when `https=True`. `run_server` catches `RuntimeError` from HTTPS setup failure.
  - `config.py` — `server_https_enabled` (bool, default False) and `server_webhook_url` (str, default "") added to `DEFAULT_CONFIG` with clear comments.
  - `gui.py` — `_cli_serve` forwards `https` (from `--https` flag or config) and `webhook_url` (from `--webhook` flag or config) to `run_server`. `_build_argparser` adds `--https` (store_true) and `--webhook` (optional string).
  - `app/app.py` — `_toggle_server` reads `https`/`webhook_url` from Tk vars and passes to `handle.start`. `_save_server_prefs` persists both to config.
  - `app/widgets/tabs.py` — HTTPS checkbox + webhook URL entry added to server tab. Safety note updated to mention HTTPS opt-in.
  - `test_gui_serve_args.py` — Updated `test_cli_serve_forwards_explicit_flags` to expect `"https": False, "webhook_url": ""` in the captured dict. Two new tests cover explicit `--https`/`--webhook` flags and config fallback. Correct: both sides' logic preserved.
- **Test coverage of merged behavior**: 3 new test files (`test_server_openai.py`: route parsing, pure helpers, HTTP round-trips for all response formats, auth, error cases; `test_server_tls.py`: cert generation/reuse, SSL context, real TLS round-trip, HTTPS failure handling; `test_server_webhooks.py`: payload shape, SSRF refusal, fire-and-forget delivery, redirect refusal, JobManager integration, slow-webhook non-blocking) + 2 extended test files (`test_fixpack_D.py`: legacy numeric IP SSRF, `test_fixpack_bl_appui.py`: server start signature). All exercise every merged change with realistic edge cases.

Result: clean. No source changes needed.

## Merge: opencode/speaker-signal-review (2026-09-21)

Clean merge, no conflicts. `git merge --no-ff opencode/speaker-signal-review`
succeeded via ort strategy; 11 files changed, 650 insertions, 23 deletions.

Branch contents (from `git log HEAD^2`):
- `ff9dd3f` Harden diarization, voiceprint, alignment, separator edge cases
- `c87a809` + `29276a3` + `704c182` review handoff and two follow-up re-checks
  (orphan survivor name, prune sort guard, non-string-text / TypeError gates)

What was merged (sanity-checked via `git diff c87c42f..HEAD`):
- `core/alignment.py`: `_build_whisper_result` no longer drops non-string-text
  segments; coerces to `""` so index-based splice-back stays aligned.
- `core/diarization.py`: `_prepare_audio_16k_mono` raises
  `DiarizationUnavailable` on empty ffmpeg decode instead of reaching
  sherpa native code with an empty array.
- `core/hallucination.py`: `annotate_segments` skips non-string `text`
  (None / number) instead of crashing on `.strip()`.
- `core/separator.py`: Demucs cache gets in-use grace period
  (`_CACHE_IN_USE_GRACE_S = 300`), mtime refresh on hit, OSError-safe
  prune sort + cache-hit stat, per-source `_orphan_vocals.wav` survivor
  name matching the prune glob, and input fallback when the stem cannot
  be cached at all.
- `core/voiceprint.py`: `enrol_with_vector` rejects NaN/Inf/non-numeric
  vectors with `ValueError`; `match_vector` skips dimension-mismatched
  rows instead of scoring them 0.0 (which could false-match at threshold 0).
- Tests: new coverage in `test_alignment.py`, `test_diarization.py`,
  `test_hallucination.py`, `test_separator.py` (4 new), `test_voiceprint.py`
  (3 new), plus `OPENCODE_HANDOFF_speaker_signal.md` review handoff doc.
- No reconciliation needed: no conflicting hunks, no test adjustments.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2388 passed,
  14 skipped, 0 failures.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/speaker-signal-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2387 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). One transient TclError on `test_find_replace_rejects_whitespace_only_needle` (same tkinter environment issue documented in prior merge commits; passes on rerun) — unrelated to this speaker-signal-only merge.
- **Merge diff**: 5 source files changed (`alignment.py`, `diarization.py`, `hallucination.py`, `separator.py`, `voiceprint.py`) + 5 test files (2 extended, 3 new) + 1 doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `alignment.py` — `_build_whisper_result`: non-string `text` coerced to `""` instead of dropping the entry. Correct: the old `if isinstance(text, str)` filter dropped entries, shifting every later segment's words onto the wrong segment during index-based splice-back. The `isinstance` guard at line 77 is correct.
  - `diarization.py` — `_prepare_audio_16k_mono`: empty-decode guard (line 138: `samples.size == 0`) raises `DiarizationUnavailable` before reaching sherpa native code. The `FileNotFoundError`/`OSError` catch (line 129) was already present from earlier hardening; the merge added the empty-array guard. Both correct.
  - `hallucination.py` — `annotate_segments`: `isinstance(raw_text, str)` guard (line 175) skips non-string text (None, number) instead of crashing on `.strip()` at line 180. Correct: the guard is before the `.strip()` call.
  - `separator.py` — `_CACHE_IN_USE_GRACE_S = 300` (line 111): stems used within 5 min are never evicted; cache hits refresh mtime via `os.utime` (line 220). `prune_cache` sorts by `_mtime_or_zero` with `OSError` guard (line 142); `in_use` check (line 162) uses `now - st.st_mtime < _CACHE_IN_USE_GRACE_S`. `_orphan_vocals.wav` survivor name (line 271) is keyed per-source and matches `*_vocals.wav` prune glob. `os.replace` fallback chain (lines 254-278) handles cross-drive copies and falls back to orphan survivor or input. All correct.
  - `voiceprint.py` — `enrol_with_vector`: `math.isfinite(x)` check (line 169) rejects NaN/Inf/non-numeric with `ValueError`; `TypeError` from non-iterable elements caught separately. `match_vector`: dimension-mismatched rows skipped (line 249) instead of scoring 0.0 (which at threshold <= 0 would false-match). Both correct.
  - No silent drops: every change adds a guard or fix without removing existing logic. No reverted behavior from prior merges.
- **Test coverage of merged behavior**: 92 targeted tests across 5 merge-specific test files (`test_alignment.py`, `test_diarization.py`, `test_hallucination.py`, `test_separator.py`, `test_voiceprint.py`) — all pass. Tests exercise: non-string text coercion, empty-decode guard, non-string text skip, cache grace/prune/orphan survivor, NaN/Inf rejection, dimension-mismatch skip. Pre-fix code would fail these tests (old `_build_whisper_result` dropped non-string entries; old `_prepare_audio_16k_mono` passed empty arrays to sherpa; old `annotate_segments` crashed on `.strip()` of None; old `match_vector` scored dimension-mismatched rows 0.0).

Result: clean. No source changes needed.

## Merge: opencode/transcriber-core-review (2026-09-21)

Clean merge (`git merge --no-ff opencode/transcriber-core-review`): no conflicts,
no reconciliation needed. Merge commit 97c8792 on top of 27f1538
(second parent 0ae2111).

Files brought in by the review branch (2b4cf5e + 0ae2111):
- `core/transcriber.py`: `_LANG_ALIASES` map (iw->he, in->id, ji->yi, jv->jw,
  nb->no, cmn->zh) + multi-value `_normalize_language` scan that only ever
  returns a member of `_WHISPER_LANGS`; `_write_outputs` takes `chapters=` and
  writes the auto-chapter sidecar at the shared collision index via new
  `_indexed_sidecar_path` (included in the collision probe, non-fatal on
  failure); `_write_chapter_sidecar` takes the full target path; alt-backend
  clip-start-at/after-EOF guard mirroring the faster-whisper path;
  `_remove_quietly` + partial `.slice.wav` cleanup on all three
  `_slice_audio_from` failure paths (timeout, spawn failure, non-zero exit);
  all three call sites (transcribe, alt-backend, resume) pass chapters through
  `_write_outputs` instead of writing the sidecar separately.
- `tests/core/test_alt_backend_clip.py`, `test_fixpack_timerange_slice.py`,
  `test_normalize_language.py`, `test_output_indexing.py`,
  `test_transcribe_kwargs.py`, `test_transcriber_helpers.py`: coverage for the
  above (alias/multi-value/region-subtag language cases, sidecar shared index +
  orphan-sidecar bump, alt-backend and main-path EOF guards, slice-partial
  cleanup, picker-Hebrew kwarg).
- `OPENCODE_HANDOFF_transcriber_core.md`: new review handoff doc (incl.
  second-pass revert-prove: 14 failures on old code, 95/95 pass on new).

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2410 passed, 14 skipped,
  0 failures on the final clean run. One earlier full-suite run showed a single
  transient Tk environment failure in unrelated
  `tests/core/test_transcript_viewer.py::test_viewer_disables_transport_when_vlc_init_fails`
  (`TclError: couldn't read file .../ttk/combobox.tcl`); it passes in isolation
  and the full-suite rerun is green — same class of tkinter state flake
   documented in prior merge commits, unrelated to this transcriber-only merge.

### Double-checked (mimo-v2.5):

Verified the merge of `opencode/transcriber-core-review` into
`integration/opencode-merge-2026-09-21`:

- **Pyright**: 0 errors, 0 warnings, 0 informations on `app/` and `core/`.
- **Test suite**: 2410 passed, 14 skipped, 0 failures (`tests/` minus `tests/smoke/`). No transient failures on this run.
- **Merge diff**: 1 source file changed (`transcriber.py`) + 6 new test files + 1 new doc. No conflict markers, no dropped lines, no duplicated logic.
- **Adversarial review of changes**:
  - `_LANG_ALIASES` + `_normalize_language`: multi-value comma/space scan with alias lookup replaces the old single-value split-on-dash approach. Correct: legacy codes (`iw`, `jv`, `in`, `ji`, `nb`, `cmn`) are now mapped before the `_WHISPER_LANGS` membership check; unrecognised leading tags don't shadow valid later alternatives.
  - `_write_outputs` + `_indexed_sidecar_path` + `_write_chapter_sidecar`: chapters sidecar now shares the collision index with transcript outputs. Correct: `_indexed_sidecar_path` builds `<base> (N).chapters.json` (not `.chapters (N).json`); orphan sidecars bump the index; sidecar failure is non-fatal.
  - All three call sites (`transcribe`, `_transcribe_via_alt_backend`, `resume_transcription`) pass `chapters=` through `_write_outputs` instead of writing the sidecar separately. Correct.
  - Alt-backend EOF guard: `clip_start_s >= duration` raises before ffmpeg is called. Correct: mirrors the faster-whisper path.
  - `_remove_quietly` + `.slice.wav` cleanup on timeout/spawn-failure/non-zero-exit paths in `_slice_audio_from`. Correct: all three failure paths now clean up partial output.
  - Integration branch's comment improvements to `_clip_timestamps_arg` preserved intact (doc-only, no logic overlap).
- **Test coverage of merged behavior**: 6 new test files (`test_normalize_language.py`, `test_output_indexing.py`, `test_transcriber_helpers.py`, `test_transcribe_kwargs.py`, `test_alt_backend_clip.py`, `test_fixpack_timerange_slice.py`) cover alias/multi-value language normalization, shared-index chapter sidecar, orphan-sidecar bump, alt-backend EOF guard, slice-partial cleanup, and picker-Hebrew kwarg. All pass.

Result: clean. No source changes needed.

## Merge: opencode/worker-correlation-id-design (2026-09-21)

Clean merge (`git merge --no-ff opencode/worker-correlation-id-design`): no
conflicts, no reconciliation needed. Merge commit 9ba4cc9 on top of a442d32.

Files brought in by the review branch (4781855 range):
- `app/services/transcription_service.py`: new `task_correlation_id()` helper
  (`task_id` reuse, else `h<history_id>`, else `u<uuid4>` fallback cached on
  the task) wired into `transcribe_command()` (`task_id` add-only field) and
  `send_control()`; event loop now handles `control_applied` (debug) and
  `control_unmatched` (warning + `app.log`) instead of silently swallowing
  mismatched controls.
- `core/task.py`: new `TranscriptionTask.task_id: str = ""` correlation field
  (empty = legacy behaviour).
- `core/worker.py`: id-aware control routing — `_normalise_task_id`,
  `_route_control` (id-less keeps legacy apply-to-current; id-bearing applies
  immediately on id match, else parks bounded), `_register_task` applies
  parked controls under the same lock that publishes the task,
  `_expire_parked_controls` acks parked controls as `control_unmatched` after
  `CONTROL_PARK_TIMEOUT_S` (10s), `_clear_parked_controls` on shutdown/EOF;
  `started`/`done`/`error` events echo `task_id`; new
  `control_applied`/`control_unmatched` events.
- `tests/app/test_transcription_correlation.py` (new, 191 lines) and
  `tests/core/test_worker_correlation_id.py` (new, 372 lines):
  correlation-id agreement, control parking/delayed-apply, timeout ack,
  capacity eviction, id-less legacy semantics.
- `tests/core/test_transcribe_command.py`: updated for the add-only `task_id`
  field.
- `OPENCODE_HANDOFF_worker_correlation_id.md`: new review handoff doc.

Sanity-checked combined diff via `git diff HEAD^1 HEAD`: intent matches the
review-branch log; no conflict markers, no dropped lines.

Verification:
- Pyright on `app/` and `core/`: 0 errors, 0 warnings, 0 informations.
- Hermetic suite (`tests/` minus `tests/smoke/`): 2436 passed, 14 skipped,
  0 failures on the final clean run (`--tb=no --disable-warnings`). Two
  earlier `-q` full-suite runs each showed a single transient Tk-environment
  failure in an unrelated viewer test (`test_viewer_dict_root_explains_wrong_file`,
  then `test_viewer_confidence_tags_applied`; `TclError: tcl_findLibrary` /
  `tk.tcl` init noise) plus one `test_hub_setup_dialog` Tk error on the first
  attempt; each passes in isolation and the rerun is fully green — same class
  of tkinter state flake documented in prior merges, unrelated to this
  worker-protocol-only merge (merge touches no viewer/dialog code).
- Targeted merge tests
  (`test_worker_correlation_id.py` + `test_transcription_correlation.py` +
  `test_transcribe_command.py`): all pass.
