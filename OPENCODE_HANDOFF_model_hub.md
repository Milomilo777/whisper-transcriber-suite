# OPENCODE_HANDOFF — model hub review (model_manager / hub / history / stats / updates)

Branch: `opencode/model-hub-review`. Scope: `core/model_manager.py`,
`core/hub.py`, `core/history.py`, `core/stats.py`, `core/updates.py` plus
their tests under `tests/`.

Verified: `pyright app core` → `0 errors, 0 warnings, 0 informations`;
`python -m pytest tests/ --ignore=tests/smoke -q` → green (2211 passed,
1 skipped).

Note on the branch state: a concurrent OpenCode writer sharing this worktree
finished and pushed the combined code + test fix set as commit `09fc000`
while this review was still wrapping up. The code state this handoff
describes is exactly what `09fc000` contains. Two of the fixes (items 2 and
7 below) originated with that writer; they were independently verified here,
and the item-2 regression test added by this review fails without its fix.
This handoff file is committed as its own follow-up commit.

## Real bugs found + fixed

### 1. An installed model could not be used offline (`core/model_manager.py`)

`ensure_model` verified an already-installed model against the mirror's
`.md5` manifest **before** its retry/fallback try-block. With no network (or
the mirror down / the manifest 404ing) `requests.get` raised and escaped as a
hard failure, so the first transcribe of every relaunch without internet
failed even though the ~3 GB model was already on disk — contradicting the
documented "fully offline after the first download" behaviour. Verification
is now best-effort: a `requests.RequestException` from the manifest fetch
logs "Could not verify ... using it as-is", emits the normal `installed`
progress, and returns the on-disk model. (A genuinely corrupt model still
fails loudly when the backend tries to load it; offline there is no way to
repair it anyway.)

Test: `test_ensure_model_offline_uses_installed_model`.

### 2. A successful mirror retry was still reported as a failure (`core/model_manager.py`)

`last_mismatches` was set on a failed attempt and never cleared when a later
attempt verified OK, so the loop's terminal `if last_mismatches: raise` fired
for a model that was already extracted AND verified on disk. The outer
handler then deleted the good model and re-downloaded it from HuggingFace (or
failed outright where huggingface.co is blocked). Cleared before `break`.

Test: `test_ensure_model_successful_retry_after_mismatch_is_kept` (fails with
the pre-fix code, raising "Model download failed after 3 attempts").

### 3. A network drop mid-download discarded the partial mirror archive (`core/model_manager.py`)

Any `requests` error during `_download_zip` jumped straight to the
HuggingFace fallback, which first deletes the partial `.zip` — losing however
much of the ~3 GB had already arrived, and failing outright on mirror-only
networks where huggingface.co is blocked. When bytes are already on disk the
attempt loop now retries the mirror (HTTP `Range` resume) within the existing
`MAX_DOWNLOAD_ATTEMPTS` budget; with nothing downloaded it still falls
through to HuggingFace immediately, exactly as before.

Tests: `test_ensure_model_resumes_after_transient_download_error`,
`test_ensure_model_no_partial_falls_back_immediately` (pins the fast path).

### 4. Cancelling a HuggingFace download showed a "download failed" error (`core/model_manager.py`)

hf_hub's own download is not interruptible, so Cancel is only observable
after `_download_via_huggingface` returns `False`; both call sites turned
that into `RuntimeError` ("both the smch.ir mirror ... and the HuggingFace
fallback ... were unable to provide the model"), so the user got a failure
dialog for a download that may in fact have completed. Both now raise
`DownloadCancelled` when the cancel flag is set, matching how a cancelled
mirror download already behaved.

Tests: `test_ensure_model_no_mirror_cancel_during_hf_is_cancelled`,
`test_ensure_model_mirror_cancel_during_hf_fallback_is_cancelled`.

### 5. A partial HuggingFace-only install was reported as complete (`core/model_manager.py`)

The no-mirror "already installed" check was `any(model_path.iterdir())`. A
download killed mid-transfer leaves completed files (e.g. `config.json`) in
the folder with in-progress blobs parked in `.cache`, so the folder counted
as installed and every later load failed on the missing `model.bin` with no
in-app recovery. The check now requires the CTranslate2 weights (`model.bin`)
— matching `model_downloaded()`'s own presence check — and re-downloads
otherwise.

Test: `test_ensure_model_no_mirror_partial_install_is_not_installed`.

### 6. Path traversal via the online-augmentable model catalog (`core/hub.py`, `core/model_manager.py`)

`model_catalog` entries can come from the online config (`config_url`), and
`_merged_catalog` only required `name` to be a non-empty string. That name
becomes the model directory through `hub.model_folder_for`, so an entry named
`../../Documents` composed a `model_path` **outside the hub** — and
`ensure_model` does `shutil.rmtree(model_path)` before extracting, so a
compromised / MITM'd online catalog could delete an arbitrary directory and
write attacker-supplied files beside it. (The existing zip-slip guard only
protects archive *members*, never this destination path.) Project docs
explicitly treat the online config as untrusted for privacy-relevant keys, so
this escaped the intended boundary.

- `hub.is_safe_model_folder_name()` rejects anything that is not a single,
  safe folder component (separators, `.`/`..`, NUL, Windows drive-relative
  forms); `model_folder_for` raises `ValueError` for those, which every
  caller already handles as a fallback.
- `_merged_catalog` drops catalog entries whose `name` fails the check, so a
  hostile entry never reaches the model picker and a hijack attempt on a
  built-in slug leaves the built-in entry intact.

Tests: `test_model_folder_for_rejects_traversal_names`,
`test_model_folder_for_rejects_windows_drive_relative_name`,
`test_model_folder_for_accepts_plain_folder_names`,
`test_is_safe_model_folder_name_directly`,
`test_model_folder_for_traversal_would_have_escaped_hub`,
`test_merged_catalog_ignores_unsafe_model_names`.

### 7. A locked database was misclassified as corruption (`core/history.py`)

`_check_integrity_or_recover` treated every `sqlite3.Error` from
`PRAGMA integrity_check` as corruption, so a transient `SQLITE_BUSY` /
"database is locked" from a second process (second app instance, worker)
renamed the user's healthy `history.db` to `.corrupt` and recreated it empty
— total history loss for a lock that would have cleared in milliseconds.
`_is_transient_lock_error` now classifies lock errors by `sqlite_errorname`
(with a message fallback) and skips this open's check instead of rotating the
file.

Tests: `test_locked_integrity_check_does_not_rotate_db`,
`test_is_transient_lock_error_recognises_real_sqlite_busy`,
`test_is_transient_lock_error_rejects_corruption`.

## Reviewed, no real bug found

- `core/stats.py` — the opt-in gate is re-checked at the POST site, non-http(s)
  `stats_url` schemes are rejected, the POST is a daemon thread with a short
  timeout and every error swallowed, psutil is optional, and the payload
  builder matches its documented field list. No code change.
- `core/updates.py` — the private-repo 404 path is silent (verified), a
  malformed / non-object JSON body is rejected, Unicode-digit tags degrade
  instead of raising, and `1.10.0` vs `1.9.0` compares numerically. Existing
  tests already pin all of it. No code change.
- `core/history.py` — beyond item 7, probed corruption recovery with a
  garbage main DB (with and without stale/corrupt `-wal`/`-shm` sidecars) and
  a crash-truncated WAL: the recover-aside path behaves correctly and leaves
  a usable DB. No further real bug.
- `core/hub.py` — after item 6, no further issue found.

## Out-of-scope observation

One owner-policy item outside this task's scope was noted for the owner privately; nothing changed here.

## Gate notes

- `pyright app core`: `0 errors, 0 warnings, 0 informations`.
- Full hermetic suite green. Two intermittent Tk-init failures were seen
  across runs (`test_transcript_viewer.py::test_viewer_invalid_json_shows_empty_list`
  and `test_hub_setup_dialog.py::test_dialog_use_default_resets_entry_and_saves`);
  both pass when re-run alone and are the known `init.tcl` / `tcl_findLibrary`
  machine flake documented in the repo — not regressions.

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

### First-pass verification (prove-it, not trust-it)

Reverted each fix in isolation, showed the regression test failing, restored,
showed it passing:

- Item 2 (`last_mismatches` clear): stripped the `last_mismatches = []` reset
  → `test_ensure_model_successful_retry_after_mismatch_is_kept` fails with
  `RuntimeError: Model download failed after 3 attempts ... still mismatched`;
  restored → passes. Claim holds.
- Item 1 (offline best-effort verify): restored the bare
  `_verify_extracted_files(...)` call → `test_ensure_model_offline_uses_installed_model`
  fails with `ConnectionError: simulated offline`; restored → passes.
  Claim holds.
- Item 6 (traversal): demonstrated the pre-fix composition
  `hub / "models--Systran--../../Documents"` resolves outside the hub, while
  `is_safe_model_folder_name("../../Documents")` is `False` and
  `model_folder_for` raises `ValueError`. All 13 traversal/safe-name/catalog
  tests pass. Claim holds.
- Items 3/4/5/7: test-pinned and passing
  (`resumes_after_transient`, `no_partial_falls_back_immediately`,
  `no_mirror_cancel_during_hf_*`, `no_mirror_partial_install_is_not_installed`,
  `locked_integrity_check_does_not_rotate_db`); code re-read, logic sound.
  No discrepancies found in any first-pass claim.

### New bug found + fixed

**Hostile catalog display fields crash the model info dialog
(`core/model_manager.py::_merged_catalog`).** Item 6 validated `name`/`url`/
`md5`/`hf_repo` but `base.update(entry)` merged `label`/`info`/
`approx_size_gb` unchecked. A truthy non-numeric `approx_size_gb`
(e.g. `"huge"` from a compromised/MITM'd online catalog — same threat model
as item 6) reaches `AdvancedDialog._show_model_info` (`app/dialogs/advanced.py:1452`,
`f"...~{size_gb:g} GB"`) and raises `ValueError: Unknown format code 'g'`,
crashing the popup. Reproduced pre-fix via `catalog_entry_info` + the exact
format expression. Fix: coerce non-`str` `label`/`info` to `slug`/`""` and
non-numeric (or `bool`) `approx_size_gb` to `0.0` after the merge.
Test: `test_merged_catalog_coerces_hostile_display_field_types` (fails
without the hunk, passes with it).

### Investigated, deliberately NOT changed

- **HistoryDB `busy_timeout`**: a second-instance EXCLUSIVE lock during open
  was suspected to crash `executescript(SCHEMA)`. Proven wrong as a code gap:
  `sqlite3.connect` defaults to `timeout=5.0`, so both HistoryDB connections
  already wait 5 s (verified `PRAGMA busy_timeout` → `5000` on a fresh
  connection); a brief lock is waited out, and only a >5 s stuck writer still
  raises. A `busy_timeout=5000` hunk was tried, shown to change nothing (new
  test passed identically with and without it), and reverted. No change.
- **`_is_transient_lock_error` message fallback**: suspected it missed
  SQLITE_LOCKED's `"A table in the database is locked"`, but that string ends
  with the already-matched `"database is locked"` substring — verified
  `True`. No change.
- **Post-extract manifest failure (line ~1023) falls to HF re-download**:
  pre-existing, low-probability (manifest fetched fine moments earlier in the
  same run), and "fixing" it means restructuring the bounded retry loop —
  not a confident net win. Left as-is.

### Gates

- `pyright app core` → `0 errors, 0 warnings, 0 informations`.
- `python -m pytest tests/ --ignore=tests/smoke` → exit 0 (2213 collected,
  incl. the 1 new test; no failures). No Tk flakes observed in this run.
