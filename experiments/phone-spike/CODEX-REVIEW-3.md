# Phone-spike defect fixes (BRIEF 3)

All eight items are DONE within the authorized offline scope. Changes are confined
to `experiments/phone-spike/` and this report. Git was read only; changes are
uncommitted for the supervisor. No downloads, package installs, native builds,
real ASR benchmarks, or operations outside this worktree were performed.

## Failing-first evidence and results

The unchanged baseline passed: `190 passed in 3.76s`. Regression tests were then
added before production changes. Running them against the original implementation
gave `67 failed, 189 passed in 8.37s`, including failures for every item below.
The before-fix output is retained in ignored scratch at
`experiments/phone-spike/tests/.tmp/regressions-before.txt`.

Test names below are in `experiments/phone-spike/tests/`.

| Item | Status and fix | Failing-first test(s) |
|---|---|---|
| 1 | **DONE.** The shared sherpa adapter passes only supported `from_whisper` keywords. Sample rate and feature dimension remain recorded as metadata. The mock enforces the exact supplied sherpa-onnx 1.13.2 signature rather than accepting arbitrary keywords. | `test_engines.py::test_sherpa_int8_files_and_cpu_defaults_are_explicit` |
| 2 | **DONE.** Good rows keep their scores after a per-file failure, crash, timeout, or bad reference. Only erroneous rows lose scores; jobs with surviving usable rows are `PARTIAL`. JSON records good/bad/total counts for all rows and separately for short files. Summary statistics and timing use good rows only, and the table and per-thread trace show status and counts. A5 still makes all-empty/all-identical output `FAILED` and removes every score, including when other errors occur. | `test_bench.py::test_partial_job_scores_nine_good_files_when_one_decode_fails`; `test_partial_crash_or_timeout_keeps_completed_scores`; `test_partial_errors_do_not_bypass_a5_sanity`; `test_one_bad_reference_does_not_remove_other_scores`; `test_summarize.py::test_summary_partial_status_counts_and_metrics_use_good_rows_only` |
| 3 | **DONE.** Default timeout is `max(3600, 10 * (3 * sum(all WAV durations) + first WAV duration))` seconds per job. It includes long form, all three repetitions and the warm-up. Both CLIs retain an explicit override. JSON records `timeout_s` and `timeout_source`; the summary trace displays them. The repeat count is shared with the runner. | `test_bench.py::test_default_timeout_scales_with_all_audio_calls_and_records_override`; `test_default_timeout_has_a_floor_for_short_jobs`; `test_run_all_preserves_scaled_default_or_forwards_timeout_override` |
| 4 | **DONE.** At runner entry, `os.dup(1)` reserves the protocol pipe and `os.dup2(2, 1)` sends native fd 1 writes to stderr. Protocol messages use the reserved stream. The controller retains stray non-JSON lines (and JSON diagnostic values without protocol status) as stderr text. A real fake-engine child writes with `os.write(1, ...)` during load and all seven warm-up/timed transcription calls. | `test_bench.py::test_native_fd1_logs_are_separate_from_protocol_in_load_and_transcribe`; `test_non_json_stdout_is_stderr_text_not_a_failed_job` |
| 5 | **DONE.** Added the requested Unicode punctuation, deletion of direction marks/BOM, joining of digit-group commas and U+066C, and preservation of decimal points with U+066B conversion between digits. Reference and hypothesis use identical rules. README documents these rules beside the R1 normalization list. | `test_metrics.py::test_unicode_punctuation_does_not_glue_words`; `test_direction_marks_and_bom_are_deleted`; `test_unicode_numeric_normalization_on_reference_and_hypothesis` |
| 6 | **DONE.** An engine whose jobs are all unavailable appears as `UNAVAILABLE` in the main table and per-thread trace. A mixture containing actual failures remains `FAILED`, or `PARTIAL` when usable jobs exist. | `test_summarize.py::test_summary_distinguishes_unavailable_from_failed_in_main_table` |
| 7 | **DONE.** Script, runner, model and build locations derive from `Path(__file__).resolve()` without `os.path.relpath`. This also covers `run_all.py`, `download_data.py`, and test fixtures. The regression test simulates cross-drive `relpath` failure for all seven production modules and verifies each resolved location. No second drive was accessed. | `test_paths.py::test_resource_paths_do_not_use_cross_drive_relpath` |
| 8 | **DONE.** Extended cardinal parsing through 999999, including multiword thousands multipliers, long phrases, compact/ZWNJ forms, surrounding prose and adjacent-number boundaries. A2 gives no colloquial spelling inventory; standard spellings are retained and the requested colloquial variants remain unchanged, explicitly documented and tested. | `test_metrics.py::test_number_grammar_through_999999`; `test_number_extension_keeps_cardinal_boundaries_and_standard_spellings` |

Final review also added
`test_bench.py::test_bad_reference_does_not_hide_identical_hypotheses_from_a5`.
It first failed (`1 failed in 0.47s`), exposing that a scoring error could hide an
identical hypothesis from sanity checking. The fix checks every available string
hypothesis regardless of reference-scoring errors; the regression now passes.
Additional assertions in the number-boundary regression first failed
(`1 failed in 0.69s`), then passed after protecting complete adjacent thousands
multipliers and standalone repeated thousands from partial consumption.

All 190 pre-existing tests remain present and pass. The old assertion that ten
thousand stayed unconverted now asserts `10000`, as item 8 requires. Existing
sherpa settings assertions remain, supplemented by the strict call signature and
accepted-keyword checks. No tests were removed, skipped, or weakened.

For compatibility, `failed` remains true when any error occurred, including a
`PARTIAL` job. `status` distinguishes usable partial results from complete failure;
the summarizer and README explicitly account for this.

## Verification

Requested command:

```text
python -m pytest experiments/phone-spike/tests -q
257 passed in 6.27s
```

The equivalent command from `experiments/phone-spike/`,
`python -m pytest tests -q`, also passed: `257 passed in 6.31s`.

`git diff --check` passed. Verification uses generated WAVs, fake child processes,
protocol fixtures and strict adapter mocks. Real runtime/model compatibility and
ASR numbers were not measured, as required by the brief.

## Files changed

- `REVIEW.md` (new)
- `experiments/phone-spike/README.md`
- `experiments/phone-spike/bench.py`
- `experiments/phone-spike/download_data.py`
- `experiments/phone-spike/engines/sherpa_engine.py`
- `experiments/phone-spike/engines/vosk_engine.py`
- `experiments/phone-spike/engines/whispercpp_engine.py`
- `experiments/phone-spike/metrics/metrics.py`
- `experiments/phone-spike/run_all.py`
- `experiments/phone-spike/runner.py`
- `experiments/phone-spike/runtime.py`
- `experiments/phone-spike/setup.py`
- `experiments/phone-spike/summarize.py`
- `experiments/phone-spike/tests/conftest.py`
- `experiments/phone-spike/tests/test_bench.py`
- `experiments/phone-spike/tests/test_engines.py`
- `experiments/phone-spike/tests/test_metrics.py`
- `experiments/phone-spike/tests/test_paths.py` (new)
- `experiments/phone-spike/tests/test_preparation.py`
- `experiments/phone-spike/tests/test_summarize.py`

The pre-existing untracked root `BRIEF.md` was read and left unchanged.

## Supervisor check (Claude, 2026-10-19)

- 257 passed on rerun in the worktree.
- The reviewer's repro inputs now score WER 0 (ellipsis, en dash, Arabic thousands separator, RLM mark, Arabic
  decimal separator, 25000 in words); the sherpa call passes only keywords present in the installed 1.13.2
  `from_whisper` signature.
- Mutation run on the new logic: 6 of 6 killed (PARTIAL never set, good rows losing scores, fd 1 not
  redirected, unscaled timeout, UNAVAILABLE shown as FAILED, digit-group separator not joined).
- Accepted as is: a Persian comma between two digits with no space is read as a digit-group separator.
- Not verified: real engines, models, datasets, Linux/macOS, phones.
