# OpenCode handoff — config / domain review (`opencode/config-domain-review`)

Scope: `core/config.py`, `app/domain/tasks.py`, `app/domain/languages.py`,
`app/observability.py`, `app/__init__.py` + their tests.
Verdict: **6 real defects fixed** (all reproduced before the fix, all covered by new
regression tests). `app/domain/tasks.py` and `app/__init__.py` were reviewed and are
**clean** — no change made, no finding manufactured.

Verification (final state):
- `pyright app core` → `0 errors, 0 warnings, 0 informations`
- `python -m pytest tests/ --ignore=tests/smoke -q` → exit 0, all green
- Every new test below was run against the pre-fix code first and failed (stash check),
  then passed after the fix.

## Real bugs found + fixed

### 1. A `null` in `.whisperproject.json` broke every transcription in that folder
`core/config.py` `_validate_overrides()` let `value is None` through for any known key,
contradicting its own docstring ("known keys must have the right type or they're
dropped") and `load_config()`'s null handling. The `None` reached
`core.transcriber._apply_runtime_overrides()`'s tail coercions
(`int(config["diarization_num_speakers"])`, `float(config["diarization_cluster_threshold"])`)
→ `TypeError` out of the transcribe scope. A user with
`{"diarization_num_speakers": null}` in a folder's project file got a hard failure on
every file in that folder.

Fix: drop `null` like any other wrong-typed value (all `DEFAULT_CONFIG` defaults are
non-`None`). Tests: `tests/core/test_project_overrides.py::
test_load_project_overrides_drops_null_for_known_key` and the end-to-end
`tests/core/test_project_overrides_leak.py::
test_scope_null_override_does_not_break_runtime_coercions` (fails with `TypeError`
before the fix).

### 2. `Infinity` / numeric overflow escaped `load_project_overrides()` ("never raises")
`{"parallel_workers": Infinity}` or a 400-digit integer made the numeric coercion call
`int(inf)` / `float(10**400)` and raise `OverflowError` out of the loader. Production
callers in `core.transcriber` happen to catch broad `Exception`s, but the function's
documented contract ("Never raises") was broken and `merge_project_overrides()` callers
would propagate.

Fix: reject non-finite floats up front (covers `Infinity`, `-Infinity`, `NaN`, and
`1e400`) and add `OverflowError` to the numeric-coercion `except` (covers a finite huge
JSON integer for a float-typed key). Tests: `test_load_project_overrides_never_raises_on_infinity`,
`..._never_raises_on_numeric_overflow`, `..._drops_nan_for_numeric_key`,
plus `..._keeps_valid_values` for the untouched happy path.

### 3. A huge integer in `config.json` crashed `load_config()` (startup crash)
`core/config.py`'s non-finite guard called `math.isfinite(merged[k])` on *any* int/float.
`math.isfinite(10**400)` raises `OverflowError: int too large to convert to float`
(confirmed: `core/config.py:901` in the traceback). A hand-edited or externally written
`config.json` containing a huge-but-legal JSON integer therefore crashed launch, since
`App.__init__` and the worker call `load_config()` unguarded. Found by fuzzing the load
path.

Fix: probe only `float` values — an `int` is always finite. Test:
`tests/core/test_config.py::test_load_config_survives_huge_integer` (fails with
`OverflowError` before the fix).

### 4. An uncreatable config dir crashed launch
`migrate_config_location()` called `user_config_dir().mkdir(parents=True, exist_ok=True)`
unguarded, so a path blocked by a file, a read-only profile, or an ACL failure raised
`OSError` out of `load_config()` before any fallback. Every other unreadable-config path
in this module degrades to defaults; this one did not.

Fix: catch `OSError`, log, and continue — `load_config()` then comes up on the
defaults + online + project layers. Test:
`tests/core/test_config.py::test_load_config_survives_uncreatable_config_dir`.

### 5. `init_sentry()` could abort startup on a bad DSN
`sentry_sdk.init(...)` was called unguarded inside a function that `App.__init__` calls
directly. A malformed `SENTRY_DSN` (the SDK raises `BadDsn` on an invalid DSN) killed the
app before the window existed — the exact opposite of the module's "strictly opt-in,
total no-op otherwise" contract.

Fix: wrap the SDK init, log, return `False`. Test:
`tests/core/test_observability.py::test_init_sentry_swallows_sdk_init_failure`.

### 6. The launch ping could abort startup when the cache dir is blocked
`_anonymised_id()` did `cache.mkdir(parents=True, exist_ok=True)` *outside* any
`try/except` (the file write below it was guarded). This runs while the ping payload is
built synchronously on the Tk main thread, so a blocked / read-only cache path (or a file
occupying it) raised `OSError` from `App.__init__`.

Fix: catch `OSError`, log, return `""` (ping still sends without an id). Tests:
`test_anonymised_id_empty_when_cache_dir_unavailable` and
`test_launch_ping_survives_unwritable_cache_dir`.

### 7. Detected language codes reached yt-dlp as regex patterns
`subtitle_lang_args()` joined codes raw. yt-dlp interprets every `--sub-langs` entry as
a **regex** — this repo already shipped (and fixed) the `.*` variant of this bug
(`docs/auto-subtitles-feature.md`: "7 files instead of 1"), but the app still forwarded
whatever came out of `format_service`'s `payload.get("language")` /
`automatic_captions` keys, i.e. video-metadata-controlled text. A value like `.*` would
match every caption track again; a malformed one like `en(` is not a valid pattern at all.

Fix: escape regex metacharacters only (`.` `^` `$` `*` `+` `?` `{` `}` `[` `]` `\` `|`
`(` `)`), leaving real codes byte-identical — the `-` in `zh-Hans`/`pt-BR` is a literal
outside a character class and is deliberately not escaped. Tests:
`tests/core/test_subtitle_lang_args.py` (wildcard, invalid-regex, hyphen pass-through)
and the command-level
`tests/core/test_download_command.py::test_build_subtitle_command_escapes_regex_metachars`.

## Reviewed and deliberately not changed

- `app/domain/tasks.py` — read fully; `VideoDownloadTask`'s fields and
  `time_range_label()` match the mirrored `_time_range_badge()` in
  `app/services/download_service.py`, and the values that reach it are already
  range-validated by `_parse_timecode()`. Nothing real found.
- `app/__init__.py` — lazy `__getattr__` / `run()` entry point is correct; no finding.
- `config_url` being stripped by `_NON_PERSISTED_KEYS` means a hand-blanked
  `config_url: ""` (the load path's documented network opt-out) does not survive the next
  `save_config()`. This is a real tension, but it is a deliberate, tested invariant
  (`test_save_config_strips_non_persisted_keys`) and changing it is a product decision,
  not a bug fix — flagged here, not touched.
- `_persistable_model_path()`'s `.strip()` on `model_path`/`hub_folder` has no
  `_as_str` guard like `_persistable_download_folder()` does, but `load_config()`'s
  top-level coercion pass sanitizes both keys to `str` before any production
  `save_config()` can see them, and no call site assigns a non-str. Not reachable; left
  alone rather than adding dead defensive code.

## Checked resources / limitations

- The bundled `bin/yt-dlp.exe` is gitignored and absent in this worktree, so the
  `--sub-langs` regex premise was verified against this repo's own recorded evidence
  (`docs/auto-subtitles-feature.md`, including the exact `en.*` → 7-files incident)
  rather than by running yt-dlp. No third-party library source was read.
- `tests/smoke/` was intentionally not run (needs the real ~3 GB model / test video).

---

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

### What was verified from the first pass, and how

Re-read the full branch diff (`git diff master..HEAD`) rather than trusting the
prose, then proved the three most significant claims by executing the old vs new
behaviour (no worktree mutation — old logic exercised directly, plus a
stash round-trip for the new test in step 3):

1. **Null project override → `TypeError`**: confirmed `int(None)` raises
   `TypeError`, the pre-fix validator's `if value is None or isinstance(...)`
   branch kept the `None`, and the fixed `_validate_overrides` drops
   `{"diarization_num_speakers": None}` (key absent from output).
2. **Huge int crashes the old `math.isfinite` guard**: confirmed
   `math.isfinite(10**400)` raises `OverflowError: int too large to convert to
   float`, and the fixed `load_config` guard only probes `float` (a huge `int`
   never reaches `isfinite`). The pre-existing regression test
   `test_load_config_survives_huge_integer` passes.
3. **Subtitle regex escaping**: pre-fix code was a bare `",".join(codes)` (raw
   passthrough, confirmed in `git show master:app/domain/languages.py`);
   post-fix `subtitle_lang_args(".*") == "\\.\\*"`,
   `("en(") == "en\\("`, while real codes pass through byte-identical
   (`"zh-Hans,pt-BR"`, `"en"`). Also confirmed `build_subtitle_command` in
   `app/services/download_service.py:304` is the single `--sub-langs` emission
   site — no bypass path feeds raw metadata to yt-dlp.

Remaining first-pass fixes (uncreatable config dir, `init_sentry` BadDsn guard,
`_anonymised_id` cache-dir guard, Infinity/overflow in `_validate_overrides`)
were verified by code inspection plus their regression suites — all green
(see final results below). **Nothing in the first pass was found wrong**;
no claim was papered over.

Minor doc nit (not a code issue, left untouched): the handoff header says "6
real defects" but the body lists 7 numbered items.

### New bug found and fixed

**`_parse_timecode("nan")` returned `nan`, crashing the Download queue.**
`float("nan")` parses successfully yet compares false to *every* bound, so it
slipped past both the negativity and 24h-cap range checks. The `nan` then
reached `int(nan)` in `_time_range_badge()` (called unguarded from
`enqueue_from_form`, `download_service.py:908`) and in `_fmt_timecode()` via
`_download_sections_arg()` — raising `ValueError: cannot convert float NaN to
integer` out of the Tk button callback when a user typed `nan`/`NaN`/`1:nan`
in a Start/End time field. Reproduced live before the fix
(`_parse_timecode('nan') -> nan`, `VideoDownloadTask(...).time_range_label()`
→ `ValueError`).

Fix (`app/services/download_service.py`): reject non-finite totals in
`_parse_timecode` (`if not math.isfinite(total): return None`, + `import
math`), so `nan` is treated like any other garbled input. `inf`/`1e400`
already failed the cap check and are now rejected explicitly too.
Regression test: `tests/core/test_download_command.py::
test_parse_timecode_rejects_nonfinite`. Proved the discipline properly: with
only the source fix stashed away, the new test **fails** (`AssertionError` at
the `nan` assert); with the fix restored, it **passes**.

### Checked and deliberately left alone

- `app/domain/tasks.py` / `app/__init__.py`: re-read; agree with first pass —
  `time_range_label()` inputs are parser-validated at the only UI construction
  site, clean.
- Huge-but-in-type integers (e.g. `parallel_workers: 10**400`) still pass
  validation in both `load_config` and `_validate_overrides` — but so does
  `10**9`, i.e. there is no range validation anywhere by design; clamping is a
  product decision, not a demonstrable crash at the load layer (the load-time
  `OverflowError` itself was already fixed in pass one).
- `bool` key receiving `inf` in `load_config` (`bool(inf) == True`): unreachable
  in practice — local, online, and cache parse paths all use the
  `parse_constant=_reject_nonfinite` hook; only a hand-constructed in-memory
  dict could do it. Noted, not touched.
- Empty `--sub-langs ""` emission when lang is blank: pre-existing behaviour,
  no concrete failure demonstrated, out of scope.

### Final verification (this pass)

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`
- `python -m pytest tests/ --ignore=tests/smoke -q` → exit 0, all green
- New regression test fails pre-fix / passes post-fix (stash round-trip above).

---

## Second-pass independent re-check, round 2 (muse-spark-1.3-contributor) — 2026-09-20

(This branch already contains one prior second-pass commit `c418715` by the
same model family; this is a further independent re-check on top of it,
following the same task template.)

### What was verified from the earlier passes, and how

Re-read the full branch diff (`git diff master..HEAD`) and proved the top
claims live with `python` (not `python3` — that binary lacks the project
deps in this worktree):

1. **Null project override dropped**: `_validate_overrides(
   {"diarization_num_speakers": None})` → key absent. Pre-fix code kept it
   (`if value is None or isinstance(...)`, confirmed via
   `git show master:core/config.py`).
2. **Infinity/overflow contained**: `inf` dropped for a numeric key; huge
   `int` no longer raises at load (finite-huge-int still passes validation
   by design — no range checks anywhere, product decision, noted before).
3. **`math.isfinite(10**400)` raises `OverflowError`**: confirmed live —
   the old `load_config` probe crashed on it, the fixed guard only probes
   `float`.
4. **Subtitle escaping**: `subtitle_lang_args(".*") == "\\.\\*"`,
   `"en(" → "en\\("`, `"zh-Hans,pt-BR"` byte-identical.
5. **NaN timecode (prior second-pass)**: `_parse_timecode("nan") is None`,
   `("inf") is None`; task built from it labels `None`.

**Nothing from either earlier pass was found wrong.** No claim papered over.

### New bugs found and fixed

Both are the same systematic gap the first pass was already hunting —
documented-"never raises" JSON/network loaders with uncaught exception
types — in sites the first two passes missed:

1. **`fetch_online_config()` let `http.client.HTTPException` escape
   ("never raises" broken, launch crash).** Its `except` caught
   `(URLError, OSError, ValueError)`, but `BadStatusLine` /
   `IncompleteRead` inherit `Exception` directly (verified: not a subclass
   of any of the three). Reproduced live: mocked `urlopen` raising
   `BadStatusLine` → `fetch_online_config` **raised** instead of falling
   back to cache. Concrete scenario: broken proxy / captive portal /
   truncated response on the launch path → `load_config` propagates (it
   calls the fetch unguarded) → startup crash. Fix (`core/config.py`):
   added `http.client.HTTPException` (+ `import http.client`) to the
   except tuple so it falls through to cache/`{}` like every other fetch
   failure.
2. **`RecursionError` escaped all three JSON loaders.** A deeply-nested
   body (100k-deep `[`…`]`, ~200 KB — under the 2 MB online cap, or a
   hand-crafted local/project file) makes the C scanner raise
   `RecursionError`, which is not a `ValueError`. Reproduced live for
   `_read_local_config` and `load_project_overrides` (both **raised**);
   the online fetch/cache paths had the same hole by inspection. Fix:
   added `RecursionError` to the except tuples in `fetch_online_config`
   (fetch + cache-read), `_read_local_config`, and
   `load_project_overrides` — each degrades to defaults/cache/`{}`.

Regression tests (all proven to **fail** pre-fix via
`git stash push -- core/config.py` round-trip, **pass** post-fix):
- `tests/core/test_config.py::test_fetch_online_survives_garbage_http_response`
- `tests/core/test_config.py::test_fetch_online_survives_truncated_response`
- `tests/core/test_config.py::test_load_config_survives_deeply_nested_file`
- `tests/core/test_project_overrides.py::test_load_project_overrides_survives_deeply_nested_file`

### Checked and deliberately left alone

- `app/domain/tasks.py` / `app/__init__.py`: agree with both prior passes —
  clean, no change.
- `_fmt_timecode(nan)` / `int(inf)` on directly-constructed
  `VideoDownloadTask(section_start=float("nan"))` would still raise, but no
  UI/service path can construct one (both bounds come from the now-guarded
  `_parse_timecode`); hardening it would be dead code. Left alone.
- `user_cache_dir()` called outside `try` in `_anonymised_id`: `platformdirs`
  path-builders don't raise in practice (no env-dependent failure
  demonstrated). Theoretical only; left alone.
- Full-suite flakes (`test_server_health`, `test_search_dialog`,
  `test_hub_setup_dialog` each failed once across runs, always pass solo
  and on the pristine stashed tree): environmental timing flakes in
  GUI/server tests, unrelated to this change (config load paths only).

### Final verification (this pass)

- `python -m pyright app core` → `0 errors, 0 warnings, 0 informations`
- `python -m pytest tests/ --ignore=tests/smoke -q` → green (final run: all
  dots, no FAILED/ERROR; earlier runs each tripped one unrelated solo-green
  timing flake, re-verified solo + on pristine HEAD).
