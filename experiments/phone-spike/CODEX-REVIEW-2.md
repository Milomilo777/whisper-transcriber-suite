# Phone spike integration review

Reviewed every supplied file in `experiments/phone-spike/`, including both specs,
the critique, engine modules, scripts, tests, and the two truncated READMEs.
`BRIEF.md` governs this integration session: changes are confined to that folder
and this report; Git was read only. No packages/models/datasets were downloaded,
no native code was built, and no real ASR benchmark was run. The supervisor commits.

## Requirement status

DONE means implemented and checked within the authorized offline scope.
NOT VERIFIABLE HERE means infrastructure/documentation is present but the stated
real data or hardware outcome has not been established. NOT DONE identifies a
remaining deliverable or implementation gap.

| Requirement | Status | Evidence and limits |
|---|---|---|
| R1 | DONE | NFC, both Arabic yeh variants, kaf, every specified harakat, U+0670, tatweel, all ASCII/Persian punctuation, all Persian/Arabic-Indic digits, Latin lowercase, whitespace collapse/strip tested. A2 overrides the default ZWNJ rule: delete for headline, space for sensitivity. |
| R2 | DONE | Linear-space Levenshtein WER/CER, reference denominators, characters without spaces, insertion rates above 1, empty/raw and empty/normalized references tested with hand-computed cases. |
| R3 | DONE | Windows fake-engine end to end: optional refs, hypotheses, per-file edits/rates, WAV duration, median wall/RTF, child PID/peak RSS, model metadata, separate load time and errors. New output directories are created and completed jobs are saved atomically. Missing/incomplete refs and invalid WAVs are explicit errors. Real engine operation is unverified; CLI fairness is the A3 gap below. |
| R4 | DONE | One registry; imports require no optional runtime. Distinct, empty, identical and failing fake plugins exercise child-process runs. Missing plugins/dependencies are recorded as UNAVAILABLE rather than crashing the controller. |
| R5 | NOT DONE | Portable setup.py and a shell wrapper now cover pinned direct requirements, whisper.cpp v1.7.1 CMake build, required model downloads/quantization and SHA-256 generation. Actual builds/downloads are forbidden here, so compatibility and artifacts are unverified and README checksums remain unknown. The hash action updates the README block when real files exist. Model URLs are not content-pinned before that manifest is recorded. |
| R6 | NOT DONE | summarize.py and its JSON fixture tests produce a traceable one-row-per-engine/model/quant report with separate RTF 1/4 columns, weighted accuracy, RAM and licences. Actual results/fleurs-fa.json and results/SUMMARY.md do not exist because a real benchmark is forbidden; synthetic fixtures are not substituted for them. |
| R7 | DONE | README gives exact Windows/Linux commands, observed Windows CPU identifier/architecture/logical CPU/RAM metadata, VM/phone and read-speech caveats. It labels the incoming Linux VM hardware claim unverified. Recommendation, real WER/RTF and phone integration are explicitly unknown; synthetic speed is never a recommendation. |
| R8 | DONE | The exact requested Windows pytest command passes with only standard-library runtime code plus pytest. The summary line is reproduced below and in README. Original test functions/assertions are retained and strengthened. |
| A1 | NOT VERIFIABLE HERE | Seeded uniform sampling over the entire split (300 without replacement, all if fewer), manifests, aggregate WER/CER, ratio-based bootstrap CIs, utterance medians and ID/reference-paired comparison are implemented and tested. No real FLEURS sample or best-two comparison was measured. |
| A2 | DONE | Headline ZWNJ deletion versus space sensitivity, zero through 9999 cardinal grammar, compact/ZWNJ forms, number-versus-digit normalization on both sides, and boundaries/non-number/list cases tested. Ordinals, negatives/decimals and larger expressions remain outside this grammar. |
| A3 | NOT DONE | Separate runner per engine/thread job, one discarded extra warm-up call, three timed calls/median-associated hypothesis, structured settings, nproc/governor, ru_maxrss with macOS units, and Windows PeakWorkingSetSize are implemented/tested. whisper.cpp still reloads via its CLI each repetition; reported model-load time is subtracted and separately retained, but process overhead and resident-model parity remain unresolved. Some internal runtime defaults remain runtime-defined, Vosk exposes no recognizer thread control, and forced-timeout cleanup of a nested native CLI needs validation. |
| A4 | NOT VERIFIABLE HERE | A 25-clip fixture proves exactly 24 half-second gaps, no trailing silence and preserved PCM. Data preparation records actual long-form duration/reference; scoring/reporting include WER, repeated trigrams for hyp/ref and aligned word deletions. No real approximately five-minute file or engine repetition/drop behavior was measured. Twenty-five sampled clips are not guaranteed to total five minutes. |
| A5 | DONE | All-empty/all-identical normalized short-file hypotheses become FAILED and have score fields removed. Failures remain visible with errors; long_form cannot hide degenerate short outputs. Reports show two ref/hyp samples when available and state when pairs are unavailable. One file alone cannot establish an identity failure across files. |
| A6 | DONE | Android binding links and integration notes come from adapter metadata and are explicit report columns, using unknown when absent. Current links, exports and Android packaging have not been verified online/on device. |
| A7 | NOT VERIFIABLE HERE | Both READMEs plainly state this VM/desktop is not a phone and explain architecture/SIMD differences. The phone guide provides complete Termux runner/build commands for provisional whisper.cpp tiny q5_1/base q5_1, preserves both repeated runs and asks for device conditions. Actual measured top-two choices are unknown, Termux commands were not executed, and Vosk/sherpa ARM packaging remains unverified. |

## Bugs and inconsistencies fixed

1. **Broken test imports and working-directory assumptions.** Root invocation
   could not import metrics; the original summary test tried to run summarize.py
   from the repository root. Added local import configuration and relative script
   locations, used the current Python interpreter, propagated standard-library-only
   child execution, and verified both working directories.
2. **Windows runner crash and lost RAM.** Unconditional resource import crashed
   Windows. The runner emitted completed while bench expected done, so peak RSS
   was lost even on Unix. Unified the protocol, added Windows native memory/host
   metadata and optional Linux system-file reads, and corrected macOS RSS units.
3. **Fragile process/error handling.** Replaced blocking ad-hoc stdin/readline
   exchanges with a bounded JSON job and flushed JSON-lines responses. Python
   engine logs go to stderr. Controller capture drains both pipes, records errors,
   retains completed rows on child crash/timeout, records omitted files, creates
   output parents and atomically saves each completed job before reporting success.
   Warm-up failures are no longer silently ignored.
4. **Incomplete results and invalid scoring.** Load seconds/settings, ref text,
   direct WER/CER, raw repetitions, memory source and long-form diagnostics were
   missing or discarded. Failed engines were hidden by summarize.py and no-ref
   runs appeared to have zero error. Failures now remain visible, their accuracy
   fields are removed, and unmeasured values stay unknown.
5. **Wrong statistics and report layout.** The old bootstrap estimated a mean of
   ratios rather than corpus WER, depended on numpy/scipy, and paired unrelated
   dict-order rows merely because their lengths matched. Replaced it with seeded
   standard-library utterance-pair resampling and same-thread ID/reference pairing,
   added CER intervals/medians, combined thread columns, preserved long-form
   exclusion, and tested every main fixture-row numeric column and trace totals.
6. **Number normalization and excessive metric RAM.** The additive number parser
   merged unrelated numbers, omitted zero, accepted out-of-range sums and failed
   compact ZWNJ forms. A bounded whole-phrase grammar handles 0..9999. Levenshtein
   no longer allocates a full character matrix for long-form CER.
7. **Engine adapter defects.** Vosk reused state across files/repeats and discarded
   finalized segments. It now creates fresh recognizers and joins all segments.
   WAVs are closed reliably. sherpa validates int8 files, records CPU settings and
   reads explicitly little-endian PCM. whisper.cpp finds platform/CMake executable
   locations, validates files, preserves transcript output, records greedy CPU
   arguments and reported load timing, and accounts for nested CLI memory.
   Adapter tests use mocks only; no real models are loaded.
8. **Data/setup/documentation gaps.** Replaced buffered streaming shuffle with
   a seeded whole-split index sample, removed trailing long-form silence, saved
   source IDs/duration, and stopped download failures overwriting README. Imports
   and test_deps.py are lazy/offline. Added Python equivalents for both shell
   entry points, safe archive extraction, real-file hashing and complete Windows,
   Linux and provisional Termux instructions. Ignored local/private artifacts.
9. **Windows test-scratch ACL failure.** Python 3.13+ TemporaryDirectory's 0o700
   Windows ACL excluded this restricted process. Test scratch now inherits its
   allowed parent's ACL, stays inside this folder and checks the resolved cleanup
   target before recursive removal.

## Validation

From the worktree root:

```text
python -m pytest experiments/phone-spike/tests -q
190 passed in 3.58s
```

Also verified from experiments/phone-spike:

```text
python -m pytest tests -q
190 passed in 3.40s
```

All **190 tests passed**, with no skips. Coverage includes two tiny generated WAVs
with spaces/non-ASCII paths, fake benchmark children at 1/4 threads, one extra
warm-up plus exactly three repeats, matching median hypothesis, failure/unavailable/
empty/identical outcomes, no-reference mode, a fake run_all.py end-to-end report,
crash/timeout evidence, protocol logging, mocked engine adapters, portable RSS,
every specified normalization rule, hand-computed edits, weighted aggregation,
reproducible ratio-bootstrap endpoints, paired IDs, full report fixture columns,
uniform data sampling, a fake dataset pipeline and exact long-form PCM assembly.

All 22 Python files parse. setup.py, run_all.py and download_data.py --help work
with python -S. No network commands or real setup actions were run. Linux/macOS,
native builds, real engine quality/speed, model hashes/licences and Android
hardware remain outside the verified scope. No commit/release/package operation
was performed.

## Files changed or added

All paths below are relative to this worktree.

Modified (19 supplied files):

- experiments/phone-spike/.gitignore
- experiments/phone-spike/README.md
- experiments/phone-spike/bench.py
- experiments/phone-spike/download_data.py
- experiments/phone-spike/engines/engine_registry.py
- experiments/phone-spike/engines/fake_engine.py
- experiments/phone-spike/engines/sherpa_engine.py
- experiments/phone-spike/engines/vosk_engine.py
- experiments/phone-spike/engines/whispercpp_engine.py
- experiments/phone-spike/metrics/__init__.py
- experiments/phone-spike/metrics/metrics.py
- experiments/phone-spike/phone/README.md
- experiments/phone-spike/run_all.sh
- experiments/phone-spike/runner.py
- experiments/phone-spike/setup.sh
- experiments/phone-spike/summarize.py
- experiments/phone-spike/test_deps.py
- experiments/phone-spike/tests/test_metrics.py
- experiments/phone-spike/tests/test_summarize.py

Added (9 files, including this report):

- REVIEW.md
- experiments/phone-spike/pytest.ini
- experiments/phone-spike/runtime.py
- experiments/phone-spike/run_all.py
- experiments/phone-spike/setup.py
- experiments/phone-spike/tests/conftest.py
- experiments/phone-spike/tests/test_bench.py
- experiments/phone-spike/tests/test_engines.py
- experiments/phone-spike/tests/test_preparation.py

The supplied SPEC.md, SPEC-amendment-1.md, inputs-critique-kimi-k3.md,
requirements.txt and engines/__init__.py were read and left unchanged.

## Supervisor check (Claude, 2026-10-19)

- `python -m pytest experiments/phone-spike/tests -q`: 190 passed, rerun by the supervisor in the worktree.
- Mutation run, one change at a time: 5 of 7 killed (free substitution in the edit distance, ZWNJ always a
  space, Arabic yeh not mapped, long-form file counted in the aggregate, bootstrap over the mean of ratios).
  The 2 survivors are equivalent in practice: an UNAVAILABLE run always also sets `failed`, and errored files
  carry no score fields, so the extra conditions in `summarize.py` are defensive only.
- Removed the test host's hardware details (CPU identifier, RAM) from `README.md` before the commit.
- Not verified: anything that needs a real engine, model, dataset, Linux/macOS or a phone (see the table above).
