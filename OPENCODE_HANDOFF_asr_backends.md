# OpenCode handoff — optional ASR backends review

Scope reviewed in full: `core/backends/base.py`, `core/backends/whisper_cpp.py`,
`core/backends/cloud_stt.py`, `core/backends/google_cloud_stt.py`,
`core/backends/nvidia_asr.py`, plus their tests
(`tests/core/test_backends.py`, `test_cloud_stt.py`, `test_google_cloud_stt.py`,
`test_nvidia_asr.py`, `test_fixpack_C.py`).
`core/backends/availability.py` and `core/backends/faster_whisper_be.py` were read for
context only and deliberately not modified (other work owns them).

Verification: `pyright app core` = 0 errors / 0 warnings / 0 informations;
`python -m pytest tests/ --ignore=tests/smoke` = 2199 passed, 1 skipped.

## Real bugs fixed

### 1. Cloud STT unknown-duration runs never detected real end of file

`cloud_stt.py` and `google_cloud_stt.py` both stop the bounded unknown-duration chunk
plan when a slice "comes back empty", testing only the encoded FLAC's byte size
against `_EMPTY_FLAC_BYTES = 4096`. That test never fires in practice: ffmpeg writes a
complete FLAC container (STREAMINFO + VORBIS_COMMENT + padding) with zero audio frames
for a `-ss` seek past EOF. Measured with the exact encode command used by both modules
(`ffmpeg -ss 55 -i src -t 55 -ac 1 -ar 16000 -c:a flac out.flac`): a past-EOF slice is
~8,286 bytes, and even a 1 s silence slice is ~8,440 bytes.

Effect (real, user-visible): whenever the duration probe fails (`ffprobe` prints
`N/A` for a corrupt-but-decodable container), the loop ran the entire bounded plan at
Google — 120 empty Gemini requests (480 s windows) or 1,200 empty Cloud STT requests
(55 s windows) — wasting minutes to hours of wall time and burning quota (which can
surface as a 429 failure) after the last real audio chunk.

Fix: added `flac_slice_has_audio()` (ffprobe `format=duration`; `N/A` = empty
container) to `cloud_stt.py` and imported it in `google_cloud_stt.py` (same shared-seam
convention as `plan_chunks`/`offset_segments`). Both call sites now use
`byte_size < threshold OR not flac_slice_has_audio(path)`. The probe is conservative:
missing/failing/unparseable ffprobe output returns "has audio" so a probe failure can
never truncate a transcript. The byte test remains as a cheap first cut.

Tests: `tests/core/test_cloud_stt.py::test_unknown_duration_stops_on_past_eof_slice_above_byte_threshold`
and `tests/core/test_google_cloud_stt.py::test_run_standard_unknown_duration_stops_on_past_eof_slice`
use a realistic 8,286-byte past-EOF slice and assert exactly one chunk is sent to
Google. Pure probe-contract tests cover `N/A`, a real duration, and every conservative
failure path. `tests/core/test_fixpack_C.py`'s byte-path regression test now stubs the
probe so it stays hermetic (no real binary spawned).

### 2. Malformed / truncated Gemini HTTP bodies surfaced raw tracebacks

`cloud_stt.py` parsed every `200` response with `json.loads(resp.read()...)`. A captive
portal / corporate proxy answering HTML, or a connection closed mid-body, escaped as a
raw `json.JSONDecodeError` / `http.client.IncompleteRead` string in the UI — inconsistent
with every other failure on those requests, which is classified into a user-facing
message. Added `_json_body()` (used by `_post_json`, the Files-API upload response, and
`_wait_for_active`) which raises a clear `RuntimeError` for a truncated read, a non-JSON
body, or a non-object JSON body.

Tests: `test_post_json_non_json_body_raises_clear_error`,
`test_post_json_truncated_body_raises_clear_error`,
`test_wait_for_active_non_json_body_raises_clear_error`.

### 3. whisper.cpp model download had no socket timeout and leaked `.part`

`whisper_cpp.download_default_model()` called `urllib.request.urlopen(url)` with no
timeout, so a stalled connection hung the download thread forever with no error; and a
failure left the (up to ~1.1 GB) `.part` file on disk. Every other downloader in the
repo already does it right (`core/llm.py` uses `timeout=60` and unlinks the partial).
Brought whisper_cpp in line: `timeout=60`, and the partial file is removed on any
download exception before re-raising.

Tests: `test_whisper_cpp_download_passes_socket_timeout`,
`test_whisper_cpp_download_cleans_part_on_mid_stream_failure`
(`tests/core/test_backends.py`).

### 4. nvidia_asr skipped the on-demand install in a half-present environment

`load()` gated the on-demand install on a probe that only checked `transformers`.
`transformers` treats torch as optional, so an environment with `transformers` installed
but no `torch` (or no `librosa`, needed by the Parakeet mel front-end) skipped the
installer and then failed with a cryptic "No module named 'torch'" — with no UI path to
fix it. The probe now checks all three modules, activates the on-demand extras dir first
(so an install from a previous session is not force-reinstalled), and forces the install
when the environment is present-but-incomplete — mirroring the existing
`google_cloud_stt.load()` repair pattern.

Tests: `test_deps_available_requires_all_three`, `test_load_installs_when_torch_missing`
(asserts `force=True`), `test_load_skips_install_when_all_deps_present`.

## Clean after a genuine look

- `base.py`: no real defects. The contract (load/is_ready/transcribe_to_segments/
  unload/get_error) is implemented consistently by all four optional backends; the
  `words`-list requirement, the progress-callback shapes, and the error surface
  (`_error` + False from `load`, RuntimeError from `transcribe_to_segments`) all match
  how `core/transcriber.py` drives them.
- `whisper_cpp.py` transcription path (centisecond/second normalisation, cancel/pause
  loop, language reporting, liveness tick): no real bugs found.
- `nvidia_asr.py` transcription loop (window planning, EOF detection via PCM sample
  count — already correct —, word-timestamp fallback, offsetting): no real bugs found
  beyond the dependency probe above.
- The two cloud backends' chunking, offsetting, diarization namespacing, usage
  accounting, cancel handling, and blob/temp cleanup were re-checked; the previously
  shipped fixpacks for those areas are correct and were left alone.

## Notes (not changed here)

- `core/backends/__init__.py`'s docstring still describes `nvidia_asr` as a cloud
  NVCF engine requiring an API key; it has been a local/offline transformers backend
  since commit b733ad1. Out of the assigned scope, so left untouched — worth a one-line
  docstring fix by whoever owns that file.
- Test-environment flakes seen (both pre-existing, confirmed unrelated to this diff):
  the documented intermittent `_tkinter.TclError: Can't find a usable init.tcl`
  (failed once in a full run, passed when re-run alone); and running
  `tests/core/test_nvidia_asr.py` in isolation fails its two `app.dialogs.advanced`
  tests with `ImportError: cannot import name 'font' from 'tkinter'` — an import-order
  artifact of that test's tkinter stubs, reproduced on the unmodified tree via
  `git stash`. The full-suite ordering is green.

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Independent verification of the first pass, then a fresh adversarial review of
the same files plus surrounding logic. No code changes resulted; handoff-only
update.

### Verified from the first pass (proved, not trusted)

1. Past-EOF detection (`cloud_stt.flac_slice_has_audio` + both call sites):
   drove `CloudSttBackend.transcribe_to_segments` with a stubbed encoder
   emitting a realistic 8,286-byte past-EOF container. Old byte-only logic
   (`size < 4096`, probe forced to "has audio") sent the full bounded plan —
   120 chunks. New probe logic sent exactly 1 chunk and stopped. The new
   regression tests
   (`test_unknown_duration_stops_on_past_eof_slice_above_byte_threshold`,
   `test_run_standard_unknown_duration_stops_on_past_eof_slice`) pass.
   (Caveat found while proving it: a repro script run from /tmp imported an
   installed `core` from an unrelated project instead of this worktree —
   always run with the worktree first on `sys.path`; pytest runs were
   unaffected.)
2. `_json_body`: only one `json.loads` on a network body remains in
   `core/backends/` (the new helper itself); all three Gemini call sites
   route through it and the non-JSON / truncated-body / non-object tests pass.
3. whisper.cpp download: confirmed on `master` that `urlopen(url)` had no
   timeout and no failure cleanup; the new `timeout=60` + `.part` unlink +
   both new tests pass.
4. nvidia_asr dep probe: confirmed the old `_transformers_available` checked
   only `transformers`; the new `_deps_available` (all three modules +
   `activate()` first + `force=` on half-present) and its three tests pass.
   `optional_deps.install(force=...)` signature confirmed real.

### Pre-existing failures re-confirmed as unrelated

- `tests/core/test_nvidia_asr.py`'s two `app.dialogs.advanced` tests fail
  standalone AND in subsets with `ImportError: cannot import name 'font'
  from 'tkinter'`: that stub test is byte-identical on `master` and the
  imported app files are untouched by this branch — import-order artifact,
  not this diff.
- Full-suite flake: one run showed 2 failures in
  `test_after_callback_cancellation.py` / `test_search_dialog.py`
  (timing-sensitive GUI tests, files untouched by this branch); both pass in
  isolation and the next full runs were green.

### Fresh adversarial review — no new real bugs

Re-read `cloud_stt.py` (loop, `_json_body`, probe, Files-API paths),
`google_cloud_stt.py` `_run_standard` + `plan_chunks`,
`nvidia_asr.py` load + transcribe loop + `_decode_window`,
`whisper_cpp.py` download/load/transcribe, and the `advanced.py` callers.
Checked: `bundled_binary` never raises (PATH fallback → `FileNotFoundError`
→ caught → conservative True, as documented); the byte-check/`or`
short-circuit skips the probe for tiny slices and `idx > 0` exempts short
single-window files; `_wait_for_active`'s `meta.get("state")` is safe
(`_json_body` guarantees a dict); download exceptions surface via the
dialog's `except` to the log, no crash path. Two observations deliberately
left unchanged (not real bugs): a hand-placed small `dest` file would trip
`shutil.move` on Windows, and a stale corrupt model passes `load()`'s
`exists()` gate with a cryptic ggml error — both pre-existing, contrived,
out of scope.

### Final results

- `pyright app core` = 0 errors / 0 warnings / 0 informations.
- `python -m pytest tests/ --ignore=tests/smoke` = 2199 passed, 1 skipped
  (RC=0; matches the first pass's count exactly).

Clean second pass: first-pass fixes are real and proven, nothing further
wrong found after a genuine attempt. No source changes made.
