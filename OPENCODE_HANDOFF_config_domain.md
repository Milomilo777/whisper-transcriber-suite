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
- The known `telemetry_opt_in` default-`True` + `_NON_PERSISTED_KEYS` contradiction is a
  flagged owner-decision item; left exactly as-is.
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
