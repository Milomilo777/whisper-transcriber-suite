# OpenCode handoff — app/dialogs review (2026-09-20)

Branch: `opencode/app-dialogs-review` (local only, not pushed).

Scope: `app/dialogs/hub_setup.py`, `app/dialogs/model_download.py`,
`app/dialogs/statistics.py`, `app/dialogs/transcript_viewer.py` plus new
tests under `tests/core/`. (This branch had no handoff file; context derived
directly from `git log master..HEAD` / `git diff master..HEAD` per task brief.)

Gate: `pyright app core` → 0 errors / 0 warnings / 0 informations.
`pytest tests --ignore=tests/smoke` → 2202 collected, exit 0 (green).

## Second-pass independent re-check (muse-spark-1.3-contributor)

### What was verified from the first pass, and how

Three most significant claimed fixes were proven by reverting just those two
source files to `master` (`git checkout master -- app/dialogs/transcript_viewer.py
app/dialogs/model_download.py`), running the branch's own new tests, and
restoring (worktree verified clean afterward, branch diff intact):

1. **NaN/Infinity segment timestamps (`_seg_float`)** — on master,
   `test_seg_float_rejects_non_finite_values` and
   `test_populate_listbox_survives_non_finite_timestamps` FAIL (nan/inf pass
   through `float()` and crash one step later in `_fmt_hms`: `int(nan)` →
   `ValueError`, `int(inf)` → `OverflowError`). With the fix they pass; the
   `math.isfinite` guard coerces to the default. Claim holds.
2. **`_parse_hms_ms` rejects non-finite input** — same revert run failed the
   `inf`/`1e400`/`nan`/`1:00:inf` assertions in
   `test_parse_hms_ms_rejects_garbage`; restored code passes. Claim holds
   (storing `inf` would later crash `_fmt_hms` with `OverflowError` on list
   rebuild — confirmed `int(float('inf'))` raises `OverflowError`).
3. **Model-download retry after Cancel (`_start_worker`)** — on master,
   `test_start_worker_clears_stale_cancel_event` FAILS (`cancel_event` stays
   set, so the retry worker raises `DownloadCancelled` immediately and the
   dialog closes having done nothing, with Cancel still disabled). With the
   fix (`cancel_event.clear()` + button re-enable) it passes. Claim holds.

Also spot-checked and found correct (no change needed):

- **Hub probe cleanup** (`hub_setup._probe_writable`): `probe = None` on the
  happy path, best-effort `os.unlink` in the `OSError` handler — covers both
  `os.close` and `os.unlink` failing after `mkstemp` succeeds. The flaky-unlink
  test passes.
- **Statistics `history.stats()` guard**: `show_error` signature matches
  (`parent, title, message, detail`), and the menu-callback-swallows-exception
  rationale is real (Tk reports callback exceptions to stderr only). Test passes.
- **Transport disable condition** (`vlc_mod is None or not media_path`): master
  disabled play/transport UNCONDITIONALLY at construction (verified via
  `git show master:...`), so embedded playback controls were dead even with VLC
  + media present; nothing ever re-enabled them (no other
  `_set_transport_enabled(True)` call site exists). The fix restores the working
  path. Correct direction.
- **Menu leak fix** (`menu.destroy()` in `finally` after `grab_release()`):
  ordering is safe; destroy still runs if `tk_popup` raises. Correct.
- **VLC-init-failure path** now calls `_disable_embedded_playback()` instead of
  open-coding a partial teardown (old code never disabled seek/skip buttons on
  that path). Correct.
- **Non-dict `words` guards** in `_update_karaoke` + `_segment_min_probability`:
  match the proven crash shape (`w.get` on int/str → `AttributeError`, uncaught
  by `(TypeError, ValueError)`). Tests fail on master, pass fixed.
- **Filler tooltip rewrite** ("there is no undo"): accurate — the viewer has no
  undo mechanism (only the `_dirty` discard prompt); the old "Ctrl+Z" advice was
  wrong since Ctrl+Z does nothing. Grep confirms no undo handler exists.

### Fresh adversarial review (same files + surrounding logic)

Reviewed all `_fmt_hms` / `_fmt_hms_ms` call sites, `_parse_hms_ms` colon path,
`_segment_min_probability` / `_update_karaoke` edge inputs, `_poll` /
`_handle_not_writable` retry flow, and `show_error` usage. No new confident
bugs found:

- `_fmt_hms_ms` is only called with `_seg_float`-sanitized defaults
  (`EditTimestampDialog.__init__`), so its `round(inf)` hazard is unreachable.
- `_parse_hms_ms` colon path rejects `inf`/`nan` parts via the
  `math.isfinite(total)` check; huge-but-finite values degrade to a long but
  harmless time string.
- `_segment_min_probability` with `nan` probabilities or `words` as a
  dict/str/None degrades to `None`/a confidence tag without raising — no crash
  path, cosmetic at most, not worth touching.
- `_update_karaoke` word `float()` failures are caught by the existing
  `(TypeError, ValueError)` guard; non-finite word times only make comparisons
  False (safe no-highlight), never raise.
- `model_download._poll` retry re-arms `after(100, self._poll)` correctly; no
  double-poll (each `done` branch returns).

### Outcome

Genuinely clean second pass: every first-pass claim verified by revert-test,
no claim found wrong or incomplete, no new real bugs found. No source changes
made in this pass — only this handoff file is added.

Final verification on the committed tree: pyright 0/0/0; hermetic suite green
(2202 tests, exit 0).
