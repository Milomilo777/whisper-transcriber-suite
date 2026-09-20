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
