# OpenCode handoff — `core/transcriber.py` adversarial review

Branch: `opencode/transcriber-core-review` — local commit only (no push, no PR,
`master` untouched). Scope: `core/transcriber.py` plus its hermetic tests.

## Verification

- `python -m pyright app core` → **0 errors, 0 warnings, 0 informations**
- `python -m pytest tests/ --ignore=tests/smoke -q` → **green** (exit 0).
  Baseline note: one pre-change run hit the known machine `_tkinter.TclError`
  flake in `test_transcript_viewer.py`; that test passes alone, and the
  post-change full run was fully green.
- No file outside `core/transcriber.py` and `tests/` was modified.

## Real bugs found and fixed

### 1. Clip pre-slice leaked a partial temp WAV on every ffmpeg failure

`_slice_audio_from` runs `ffmpeg -y ... .slice.wav`; on a timeout, non-zero
exit, or spawn failure it raised with the (partial) `.slice.wav` still on
disk. Callers only unlink the slice on the success path (the main transcribe,
alt-backend, and resume `finally` blocks), so failed clip/resume attempts
accumulated orphan WAVs in `user_data_dir()/partials/` until the startup sweep
aged them out. Fix: best-effort `_remove_quietly(slice_path)` on all three
failure paths.
Tests: `test_transcriber_helpers.py::test_slice_audio_removes_partial_on_ffmpeg_failure`,
`::test_slice_audio_removes_partial_on_timeout`,
`::test_slice_audio_keeps_the_slice_on_success`.

### 2. Alt-backend clip starting at/after EOF silently wrote empty output

The faster-whisper path guards `clip_start >= media duration` and raises a
clear error; `_transcribe_via_alt_backend` (whisper.cpp / cloud / Parakeet)
had no such guard, so a start past the end sliced an empty temp WAV and the
backend "succeeded" with zero segments and empty output files. Fix: same
guard, same message, before slicing (duration is still the source's there).
Tests: `test_alt_backend_clip.py::test_alt_backend_clip_start_beyond_eof_raises`,
`test_fixpack_timerange_slice.py::test_timerange_start_beyond_eof_raises`
(the main path's guard previously had no test).

### 3. "Hebrew" in the language picker silently became auto-detect

The UI table `app/domain/languages.py` maps Hebrew to `iw` (yt-dlp's code) and
Javanese to `jv`; Whisper only accepts `he` / `jw`. `_normalize_language`
returned None for both, so an explicitly forced language was silently dropped
to auto-detect. It also took only the first comma component, so `iw,he` could
not fall through to a valid alternative. Fix: small alias map (`iw→he`,
`in→id`, `ji→yi`, `jv→jw`, `nb→no`, `cmn→zh`) plus scanning the
comma/space-separated values, using only each value's leading BCP-47 language
subtag — an unrecognised tag's region subtag (`xx-BR`) can never be promoted
to Breton.
Tests: `test_normalize_language.py` (aliases, multi-value scan, region-subtag
guard), `test_transcribe_kwargs.py::test_picker_hebrew_code_reaches_whisper_as_he`.

### 4. Auto-chapter sidecar did not share the output collision index

`_write_outputs` numbers a re-run's whole output set (`name (1).srt` +
`name (1).json`), but the sidecar was written at the un-indexed
`name.chapters.json`. The transcript viewer derives the sidecar path from the
JSON it opened (`<opened-json-stem>.chapters.json`), so a re-run's chapters
were invisible from the newly indexed transcript, and the write overwrote the
previous run's sidecar in place (mixing run 2's chapters with run 1's
transcript). Fix: `_write_outputs` takes `chapters=` and writes the sidecar as
part of the same set/index, including it in the collision probe so an existing
sidecar also bumps the index (no in-place overwrite). A sidecar failure stays
non-fatal. `_write_chapter_sidecar` now takes the full target path, and
`_indexed_sidecar_path` inserts ` (N)` before `.chapters.json` (plain
`_indexed_path` would split at the last dot and produce `.chapters (1).json`).
Tests: `test_output_indexing.py::test_chapter_sidecar_shares_the_output_index`,
`::test_chapter_sidecar_absent_when_no_chapters`,
`::test_orphan_sidecar_bumps_the_shared_index`.

## Checked and deliberately not changed

- **Sidecar does not follow a relocating `output_filename_template`**
  (`transcripts/{base}.{ext}` etc.). The viewer would then look for
  `transcripts/<stem>.chapters.json` while the sidecar sits next to the source
  media. That is a product-level naming decision (docs promise
  `<name>.chapters.json` next to the media) affecting only users who relocate
  outputs — a larger behaviour change than this pass's scope.
- **`App._task_json_output` (`app/app.py`) can pick the `.chapters.json`
  sidecar as the transcript** when `json` is not among the requested formats:
  it returns the first `.json` in `task.output_paths`, and the sidecar is
  appended there. Pre-existing, unchanged by this diff, and in the app layer
  (explicitly out of scope). `core/server/jobs.py` already excludes the
  sidecar for exactly this reason.
- **`_clip_timestamps_arg`** now only serves as an "is a clip requested?"
  marker (its value is never passed to faster-whisper — that is the documented
  invariant). Its name/docstring still describe the old use; renaming it would
  be cosmetic churn, so it was left alone.
- Negative `clip_start` (UI inputs are non-negative), duplicate registry
  formats, and a template without `{ext}` (intra-run path collisions) are
  garbage-in paths not reachable from the app's own controls.

## Invariant audit (against the final diff)

1. Clips: still pre-sliced via ffmpeg and shifted by `+clip_start`; no
   `clip_timestamps` kwarg added; the `clip is None` / `not is_clipped`
   checkpoint guards are untouched; the new alt-backend guard runs before any
   temp file exists.
2. Checkpoint: keying and validation (`_checkpoint`,
   `_current_backend_and_model`, config fingerprint) untouched.
3. `_runtime_overrides_scope` snapshot/restore untouched.
4. `core/config.py` online allowlist untouched.
5. `_write_outputs`: one shared index (now covering the sidecar), per-format
   `.part` + `os.replace`, per-format failure isolation, and the
   all-writers-failed raise are all preserved; a sidecar failure can never
   abort a successful transcript write.
6. Language normalization is still applied at every call site and now only
   ever returns a member of `_WHISPER_LANGS`.
7. CUDA self-heal fallback logic untouched.
