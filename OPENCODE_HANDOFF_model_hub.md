# OPENCODE_HANDOFF — model-hub review (core/model_manager.py, core/hub.py, core/history.py, core/stats.py, core/updates.py)

Adversarial review + fix pass over the model-download / hub / history / stats /
update-check cluster. Every change below fixes something a user could hit and
ships with a test that fails on the pre-fix code. Final gate: `pyright app core`
= 0 errors / 0 warnings / 0 informations, `python -m pytest tests/ --ignore=tests/smoke -q` = green.

## Real bugs fixed

1. **Successful MD5 retry was reported as a terminal failure** (`core/model_manager.py`)
   The mirror retry loop never cleared `last_mismatches` on a later successful
   attempt, so attempt 2 verifying clean still tripped the terminal
   "files still mismatched" raise. The outer handler then deleted the freshly
   verified model and re-downloaded ~1.5-3 GB from HuggingFace — or failed
   outright on the mirror-only networks the mirror exists for.
   Fix: clear `last_mismatches` when an attempt verifies clean.
   Test: `test_ensure_model_successful_retry_after_mismatch_is_kept`.

2. **A transient SQLite lock silently destroyed the user's entire history** (`core/history.py`)
   `_check_integrity_or_recover` treated *any* `sqlite3.Error` from
   `PRAGMA integrity_check` as corruption. When a second process holds the DB
   (rollback-journal mode), the PRAGMA raises `OperationalError: database is
   locked` (SQLITE_BUSY) even though the file is healthy — the old code renamed
   `history.db` to `.corrupt` and recreated it empty.
   Fix: new `_is_transient_lock_error()` (error-name first, message fallback)
   skips recovery for SQLITE_BUSY / SQLITE_LOCKED only; genuine corruption
   ("file is not a database", "database disk image is malformed") still
   recovers as before.
   Tests: `test_locked_integrity_check_does_not_rotate_db`,
   `test_is_transient_lock_error_recognises_real_sqlite_busy`,
   `test_is_transient_lock_error_rejects_corruption`.

3. **Offline relaunch refused to use an already-installed mirror model** (`core/model_manager.py`)
   The "already installed → verify MD5" step fetched the `.md5` manifest
   outside the main try. Offline (or mirror down) that raised and escaped as a
   hard error, breaking the documented "fully offline after the first
   download" promise even though all model bytes were on disk.
   Fix: a `requests.RequestException` while verifying an installed model now
   logs "could not verify … using it as-is" and proceeds; a genuinely corrupt
   model still fails loudly at backend load.
   Test: `test_ensure_model_offline_uses_installed_model`.

4. **A killed HuggingFace-only download counted as a finished install** (`core/model_manager.py`)
   `any(model_path.iterdir())` passed on a partial tree (e.g. `config.json`
   alone), so the next load failed on missing `model.bin` with no in-app way
   to recover. Fix: require the CTranslate2 weights (`model.bin`) — the same
   signal `model_downloaded()` already uses — and re-download otherwise.
   Test: `test_ensure_model_no_mirror_partial_install_is_not_installed`.

5. **Cancel during a HuggingFace download showed "download failed"** (`core/model_manager.py`)
   `huggingface_hub`'s download is not interruptible, so the cancel event was
   only observed after it returned; both HF paths then raised a scary
   RuntimeError for a download the user deliberately cancelled (that may even
   have completed). Fix: raise `DownloadCancelled` when the event is set.
   Tests: `test_ensure_model_no_mirror_cancel_during_hf_is_cancelled`,
   `test_ensure_model_mirror_cancel_during_hf_fallback_is_cancelled`.

## Hardening / resilience

6. **Unsafe model-folder names from the online catalog could delete/overwrite arbitrary directories** (`core/hub.py`, `core/model_manager.py`)
   `model.name` becomes a hub subfolder and the download flow `rmtree`s that
   path before extracting, but the zip-slip guard only covered archive
   members, never the destination. A compromised / MITM'd `model_catalog`
   entry named `../../Documents` composed a path outside the hub. New
   `hub.is_safe_model_folder_name()` (rejects non-strings, empty/`.`/`..`,
   separators, NUL, and platform-meaningful drive-relative/ADS forms) gates
   both `model_folder_for()` and `_merged_catalog()` — unsafe catalog entries
   are ignored entirely, and a hijack attempt on a built-in slug leaves the
   built-in entry untouched.
   Tests: `test_model_folder_for_rejects_traversal_names`,
   `test_model_folder_for_accepts_plain_folder_names`,
   `test_is_safe_model_folder_name_directly`,
   `test_merged_catalog_ignores_unsafe_model_names`.

7. **A network blip discarded the mirror download and restarted from zero on HuggingFace** (`core/model_manager.py`)
   A `requests` error mid-download abandoned the mirror immediately, deleting
   the partial archive and re-downloading everything from HF — which is
   blocked on the very networks the mirror serves. Now, while a non-empty
   partial archive exists, the error is retried through the mirror (HTTP Range
   resume), bounded by `MAX_DOWNLOAD_ATTEMPTS`; with nothing downloaded it
   still falls through to HF immediately.
   Tests: `test_ensure_model_resumes_after_transient_download_error`,
   `test_ensure_model_no_partial_falls_back_immediately`.

## Reviewed and clean — no changes

- `core/updates.py` — verified the silent-404 (private repo), malformed-JSON,
  Unicode-digit-tag and numeric (`1.10.0 > 1.9.0`) comparison contracts; all
  already covered by `tests/core/test_updates.py` + `test_fixpack_sweep_updates.py`.
- `core/stats.py` — payload is basename-only, `post_stats_async` re-checks the
  opt-in gate, non-http(s) `stats_url` schemes are rejected, missing psutil
  degrades to zeros; no real issue found.
- `core/hub.py` — resolution order (explicit `model_path` > `hub_folder` +
  name > default per-user cache) and default-hub/cache-fallback lock-step hold.

## Observation (deliberately not changed)

- `core/stats.py`'s docstring (and `docs/CONFIG.md`) describe telemetry as
  "default OFF", but `DEFAULT_CONFIG["telemetry_opt_in"]` is deliberately
  `True` for this distribution (`core/config.py` comment + `tests/core/test_config.py`
  pin it). That is a docs/docstring mismatch, not a code bug; flagged only.

## Verification

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`.
- `python -m pytest tests/ --ignore=tests/smoke -q` → exit 0 (green; no Tk flake observed this run).
