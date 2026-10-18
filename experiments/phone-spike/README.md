# Persian on-device ASR benchmark harness

This folder contains an offline benchmark controller, engine adapters, Persian
metrics, and a report generator. Integration was checked with generated WAVs and
fake engines only. No packages, models, or datasets were downloaded, whisper.cpp
was not built, and no ASR measurements were made in this integration session.
`SPEC-amendment-1.md` overrides `SPEC.md`; `BRIEF.md` at the worktree root limits
this session to integration and tests.

## Recommendation and hardware

**Recommended Android engine/model/quant: unknown. WER: unknown. RTF at four
threads: unknown.** There are no measured FLEURS results or device results.
Do not use synthetic test timings to select an engine.

This VM is not a phone. x86 desktop/VM speed rankings are an x86 proxy until the
same runner is run on a real Android phone. ARM SIMD/NEON, big.LITTLE scheduling,
memory bandwidth, and thermal throttling can change the ranking. FLEURS is read
speech; spontaneous, noisy voice notes may behave differently.

The incoming truncated README claimed a Xeon VM, four cores, and 7.8 GiB RAM;
that Linux hardware claim is unverified here. The offline tests were run on a Windows
x86-64 desktop with Python 3.14; no benchmark numbers come from it. MB throughout this
harness means 1024 squared bytes.

Each actual run records its own OS, architecture, CPU identifier, logical CPU
count (`nproc`), RAM and, on Linux when readable, CPU model, affinity and governor.
No process affinity or governor is changed. Run in a quiet window, repeat the
whole run, and retain both JSON files. Requested thread counts can exceed
available CPUs; results are not a controlled physical-core comparison.

## Offline tests: Windows and Linux

From the repository root, with an existing Python and pytest:

```powershell
python -m pytest experiments/phone-spike/tests -q
```

On Linux where the interpreter is named python3:

```sh
python3 -m pytest experiments/phone-spike/tests -q
```

From this folder the equivalent is `python -m pytest tests -q`. No setup step is
needed for tests. Tests use only the standard library plus pytest, block optional
imports in an import check, and launch fake benchmark children with `python -S`.
Scratch files stay in `tests/.tmp/`; pytest's cache provider is disabled. The
test fixtures inherit directory permissions so Python 3.13+ restrictive temporary
directory ACLs do not exclude a restricted Windows process.

Latest Windows test summary (updated after the final check):

```text
257 passed in 6.27s
```

## Future real benchmark setup (not run here)

These commands install packages, download public models/data and compile native
code. Use them only in a later measurement session with sufficient RAM, disk and
network access. The pinned optional dependencies target Python 3.11; Python 3.14
was used only for the standard-library integration tests. Exact direct dependency
pins are in `requirements.txt`; transitive packages are not a hash-locked set.

Windows needs an installed Python 3.11, Git, CMake, and Visual Studio C++ Build
Tools (run from a shell that can use the compiler). From the repository root:

```powershell
py -3.11 -m venv experiments/phone-spike/.venv
& .\experiments\phone-spike\.venv\Scripts\python.exe experiments/phone-spike/setup.py --all
& .\experiments\phone-spike\.venv\Scripts\python.exe experiments/phone-spike/download_data.py --data-dir experiments/phone-spike/data
& .\experiments\phone-spike\.venv\Scripts\python.exe experiments/phone-spike/run_all.py
```

Linux needs Python 3.11 with venv support, a C++ compiler, Git, CMake and Make:

```sh
python3.11 -m venv experiments/phone-spike/.venv
experiments/phone-spike/.venv/bin/python experiments/phone-spike/setup.py --all
experiments/phone-spike/.venv/bin/python experiments/phone-spike/download_data.py --data-dir experiments/phone-spike/data
experiments/phone-spike/.venv/bin/python experiments/phone-spike/run_all.py
```

Alternatively, from an activated environment, `bash experiments/phone-spike/setup.sh`
and `bash experiments/phone-spike/run_all.sh` wrap the Python equivalents. The
wrappers and Python tools work from either this folder or the repository root.
All relative input/output paths passed as arguments are relative to the calling
working directory. Scripts locate default models, data, builds and the runner using
absolute paths derived from their own resolved file locations, so the calling
directory can be on a different Windows drive.

`setup.py` has explicit `--install`, `--build`, `--models` and `--hashes` actions;
no arguments only prints help. `--all` does these in that order. It checks the
whisper.cpp release tag `v1.7.1`, builds CPU binaries with CMake, downloads Vosk
small fa 0.42 and sherpa-onnx Whisper tiny/base exports, and quantizes multilingual
whisper.cpp tiny/base/small to q5_1 and q8_0. The original float Whisper files are
retained. Model URLs can change; record and compare the generated SHA-256 manifest.
The native build, upstream CLI flags, export filenames and optional package
compatibility have not been verified with real artifacts in this session.

The large-v3-turbo q5_0 reference is optional and excluded by default. To provision
and run it, add `--include-reference` to both `setup.py --all` and `run_all.py`.
It is not a phone recommendation candidate. q5_1 and q8_0 are the required
comparison points, not a claim that all tensors use that bit width or that these
are the optimal quants. Model size counts the files actually used by the adapter.

## Data and measurement

`download_data.py` samples 300 distinct indices uniformly from the entire FLEURS
`google/fleurs`, `fa_ir`, test split using seed 1234 (all utterances if fewer).
It decodes selected rows one at a time to 16 kHz mono PCM16 WAVs, writes UTF-8
`refs.tsv`, and records source indices/IDs in `manifest.json`. It concatenates
the first 25 selected clips with exactly 0.5 seconds of silence **between** clips
into `long_form.wav` and concatenates their references. Actual duration is recorded;
25 clips are not guaranteed to total five minutes, and nothing is padded or repeated
to manufacture that length. With fewer than 25 clips all available clips are used.

Use a fresh data directory. On a download failure the tool stops, writes
`DOWNLOAD_ERROR.txt`, preserves this README, and substitutes no other dataset.

The mandatory engine list is:

```text
vosk-small-fa,sherpa-whisper-tiny,sherpa-whisper-base,whisper.cpp-tiny-q5_1,whisper.cpp-tiny-q8_0,whisper.cpp-base-q5_1,whisper.cpp-base-q8_0,whisper.cpp-small-q5_1,whisper.cpp-small-q8_0
```

To run one configuration and generate its report (replace `python` with the
prepared environment's interpreter for real engines):

```sh
python experiments/phone-spike/bench.py --audio-dir experiments/phone-spike/data --refs experiments/phone-spike/data/refs.tsv --engines whisper.cpp-tiny-q5_1 --threads 1,4 --out experiments/phone-spike/results/fleurs-fa.json
python experiments/phone-spike/summarize.py --json experiments/phone-spike/results/fleurs-fa.json --out experiments/phone-spike/results/SUMMARY.md
```

For private recordings, omit `--refs`; hypotheses and speed are still saved.
For example, with WAVs already stored locally in `experiments/phone-spike/private-wavs`:

```sh
python experiments/phone-spike/bench.py --audio-dir experiments/phone-spike/private-wavs --engines whisper.cpp-tiny-q5_1 --threads 1,4 --out experiments/phone-spike/results/private.json
python experiments/phone-spike/summarize.py --json experiments/phone-spike/results/private.json --out experiments/phone-spike/results/PRIVATE-SUMMARY.md
```

The benchmark, runners and summarizer perform no network requests. Private audio,
references and hypotheses remain local. Audio must already be 16 kHz mono PCM16;
other formats and zero-length WAVs are rejected. An explicitly supplied missing or
incomplete refs TSV is an input error. Empty normalized references raise ValueError
in metrics and are recorded as errors on those rows rather than scored as zero.

For each engine and thread count a fresh runner child loads the engine, makes one
extra warm-up transcription on the first WAV and discards it, then transcribes
**every** WAV three times. Each file keeps the median wall time and the hypothesis
from that same repetition; all three timings and hypotheses are retained.
Warm-up is not a scored row. Load seconds, child PID, decoding settings, audio/wall
seconds, RTF, model MB, errors and memory source are saved. The controller persists
each completed engine/thread job atomically before reporting completion.
An individual file error, crash or timeout preserves the completed good rows and
their scores; only bad rows lose score fields. A job with usable rows and an error
is `PARTIAL`; a job with no usable rows is `FAILED` (or `UNAVAILABLE` for a missing
engine, dependency or model). A5 sanity failures invalidate the whole job. Raw JSON
records `counts` (all rows, including long form) and `short_counts`, each with
`good`, `bad`, and `total`. The historical `failed` flag remains true whenever any
error occurred, including a `PARTIAL` job; use `status` to distinguish usability.
The controller returns normally after recording engine failures, so inspect the
JSON statuses or the summary.

`--timeout SECONDS` explicitly overrides the whole engine/thread job budget in
both `bench.py` and `run_all.py`. Without an override the budget is
`max(3600, 10 * (3 * sum(all WAV durations) + first WAV duration))` seconds: ten
wall seconds per audio second processed, counting all timed repeats, long form,
and the single warm-up, with a one-hour floor. This is a generous deadline, not a
predicted runtime. Each job records the exact `timeout_s` and `timeout_source`
(`scaled` or `override`), also shown in the summary trace.

The runner reserves a duplicate of stdout for JSON lines and redirects file
descriptor 1 to stderr before loading an engine. Python and native engine logs
therefore go to stderr. The controller also retains stray non-JSON stdout lines
as stderr diagnostics; they do not invalidate otherwise complete results.

On Linux/macOS peak RAM is the maximum `ru_maxrss` of the isolated runner and any
CLI child (macOS uses byte units; Linux uses KiB). On Windows the runner uses
`GetProcessMemoryInfo.PeakWorkingSetSize`; a nested whisper.cpp CLI is polled.
These are process peaks, not simultaneous combined RAM or a memory reservation.
Unknown RAM stays unknown.

### Timing limits that still need real-engine verification

- Vosk and sherpa-onnx keep their models resident. Vosk uses a fresh recognizer
  for every call and retains all finalized segments, not just the last one.
  Its recognizer API offers no per-instance thread count; 1/4 thread labels are
  requested environment limits, not verified parallel Kaldi decoder threads.
- The whisper.cpp CLI reloads its model for **every repetition**. The adapter
  subtracts the CLI's reported load time from wall time and records it separately;
  process startup and other overhead remain. It refuses to score speed if load
  timing is absent. This does not establish the same resident-model timing
  conditions as Vosk/sherpa. A persistent native adapter and real validation are
  still needed for a fair final speed ranking.
- CPU-only flags, greedy beam/best-of 1, temperature/increment 0, no temperature
  fallback, no timestamps, Persian language and context 0 are recorded for
  whisper.cpp. Vosk/sherpa settings plus the pinned runtime defaults are recorded
  as structured metadata. Some internal runtime defaults remain runtime-defined.
  No real decoder has been exercised here.
- Abnormal runner termination preserves completed protocol rows and records
  omitted files. A timeout kills the runner; cleanup of a nested native CLI on
  forced termination still needs platform validation.

## Scores and report traceability

The R1 normalization rules apply to both reference and hypothesis: NFC, Persian
yeh/keheh, harakat/tatweel removal, ASCII digits, punctuation removal, Latin
lowercase and collapsed whitespace. Headline ZWNJ is **deleted** under A2;
ZWNJ-to-space WER is a separate sensitivity score. Added punctuation/numeric rules:

- Ellipsis U+2026, en/em dashes U+2013/U+2014, quotation marks U+2018-U+201D,
  and Arabic percent U+066A become spaces, just like the existing ASCII and
  Persian punctuation. They cannot stay glued to words.
- Direction marks U+200E/U+200F and BOM U+FEFF are deleted.
- Between digits, Arabic thousands separator U+066C, ASCII comma and Arabic
  comma U+060C are deleted so digit groups form one number (`۱٬۲۰۰` -> `1200`).
  Outside digit pairs these separators become spaces.
- Arabic decimal separator U+066B between digits becomes an ASCII decimal point
  (`۳٫۵` -> `3.5`); an ASCII point between digits is preserved too. Other points
  and decimal separators become spaces. These rules run after digit conversion.

Whole Persian cardinal phrases from zero through **999999**, including compact
ZWNJ forms and hundreds-valued multipliers of thousands, become ASCII digits on
both sides. Unrelated adjacent numbers are not summed. This extends A2's minimum
range of 9999 as requested in BRIEF item 8. A2 specifies cardinal conversion
without a colloquial spelling inventory, so the grammar retains the standard
spellings `هجده` and `پانصد`; `هیجده` and `پونصد` are left unchanged. Ordinals,
negative/decimal number words, millions and larger phrases remain outside the
grammar; digit-written decimal values still normalize as described above.

WER/CER use Levenshtein edits divided by reference words/characters; CER omits
spaces. They can exceed 1 for many insertions. The headline is **sum edits / sum
reference lengths**, not the mean of utterance ratios. The report includes
per-utterance medians, WER and CER bootstrap 95% intervals (1000 resamples, seed 1234),
and the ZWNJ sensitivity. Each resample draws whole (edits, reference length) pairs
and recomputes the corpus ratio. Percentile endpoints conservatively include the
point estimate. The best two scored candidates are compared at the same thread
count, paired by matching utterance IDs and references, with wins/ties/losses,
mean per-utterance WER difference and paired bootstrap CI.

SUMMARY has one row per engine/model/quant, separate median RTF columns for
1/4 threads, peak RAM, licences, Android binding links and integration notes.
Accuracy is taken from the usable four-thread job when available, otherwise
one thread or the lowest available count, explicitly identified. A `PARTIAL` job
is usable: aggregate WER/CER, bootstrap intervals, medians and timing use **good
rows only**. The main table shows `PARTIAL` and the selected job's good/bad short
row counts; the trace lists status and counts for every thread beside its numbers.
Missing-runtime/model engines show `UNAVAILABLE` in the main table. Long form is
excluded from short-file scores/timing and gets its own WER, repeated-trigram
hypothesis/reference counts and aligned deletion diagnostics. Natural repetition
and aligned deletions do not by themselves prove hallucination or dropped speech.

All-empty or all-identical normalized short-file hypotheses mark a multi-file job
FAILED, with all scores removed even when other rows have errors; long_form cannot
mask that condition. A single file cannot establish an
all-files identity failure. Two sample reference/hypothesis pairs are shown per
engine where available; missing data and unmeasured accuracy are `unknown`, never
perfect zero scores. Failed engines remain in the table with their errors.

Runtime licence labels come from the supplied adapters; archive/export licensing
and the current binding links need verification against downloaded artifacts.
Android integration, APK size, noisy speech performance, and the actual top two
phone candidates remain unknown. See [phone/README.md](phone/README.md).

## Model SHA-256 values

No model artifacts exist from this integration session, so actual checksums are
unknown. `setup.py --hashes` writes `models/SHA256SUMS.txt`, prints every model-file
hash, and replaces the block below with measured values. There are no invented hashes.

<!-- MODEL_SHA256_START -->

unknown — models were not downloaded.

<!-- MODEL_SHA256_END -->

Real `results/fleurs-fa.json` and `results/SUMMARY.md` are intentionally absent.
Generated results, private inputs, models, binaries, virtual environments and test
scratch are ignored by Git. The synthetic JSON fixtures live in the tests and
must not be presented as FLEURS measurements.
