# BRIEF 3 for Codex: fix verified defects in the phone-spike benchmark harness

Same worktree and hard rules as before (`experiments/whisper-lite-android/CODEX-BRIEF-1.md`, "Hard rules"):
relative paths only, nothing outside this worktree, no secrets, git is not writable (leave changes uncommitted;
the supervisor commits), no downloads, no package installs, no native builds, no real benchmark run. Work ONLY in
`experiments/phone-spike/` plus REVIEW.md at the worktree root. Your previous report is
`experiments/phone-spike/CODEX-REVIEW-2.md`; the requirements are SPEC.md and SPEC-amendment-1.md there.

An independent reviewer found the defects below and the supervisor reproduced 1, 2 and 5. Each one would make a
REAL run report wrong numbers or lose results. For every item: first a test that FAILS on the current code, then
the fix, then the test passes. Keep all 190 existing tests green; never weaken a test.

## Defects (fix all)
1. `engines/sherpa_engine.py` passes `sample_rate=16000, feature_dim=80` to
   `sherpa_onnx.OfflineRecognizer.from_whisper`. The installed sherpa-onnx 1.13.2 signature is
   `(encoder, decoder, tokens, language='en', task='transcribe', num_threads=1, decoding_method='greedy_search',
   debug=False, provider='cpu', tail_paddings=-1, enable_token_timestamps=False, enable_segment_timestamps=False,
   rule_fsts='', rule_fars='', hr_dict_dir='', hr_rule_fsts='', hr_lexicon='')`, so `load()` raises TypeError
   and both sherpa engines end FAILED. Pass only accepted keywords. The mock in `tests/test_engines.py` accepts
   any kwargs and hid this: make the mock enforce that signature (e.g. a function with exactly those parameters).
2. `bench.py` (the `if errors:` block, ~line 138): ONE bad file (decode error, crash, timeout, a stray non-JSON
   stdout line) removes the scores of EVERY file of that engine/thread job. Repro: 10 files, an engine that fails
   only on file 7 -> 9 hypotheses, 0 rows with `wer`. Fix: score every good row; mark only the bad rows with their
   error; give the job a status that shows it is partial (e.g. `PARTIAL` with counts of good/bad rows) and make
   `summarize.py` show the partial status and the counts next to its numbers (aggregate over good rows only,
   and say so). Keep A5: all-empty or all-identical hypotheses still make the whole job FAILED with no scores.
3. Timeout: `--timeout` defaults to 3600 s per engine/thread job (`bench.py`, `run_all.py`), but one job is ~301
   files x (3 timed repeats + 1 warm-up) plus 3 long-form repeats; any engine with RTF above ~0.1 times out. Make
   the default scale with the work (e.g. a per-audio-second budget times total audio seconds x calls, with a floor),
   keep an explicit override, and record the timeout used in the results.
4. `runner.py`: `redirect_stdout` only catches Python `print`; a native library writing to file descriptor 1 breaks
   the JSON-lines protocol and the whole job fails ("Invalid runner response"). Fix: at runner start, duplicate
   fd 1 for the protocol and point fd 1 at fd 2 (`os.dup`/`os.dup2`), so native output lands on stderr. Also make
   `bench.py` treat a non-JSON line as stderr text, not a fatal protocol error. Test with `os.write(1, ...)` inside
   a fake engine's `load()` and inside transcription.
5. `metrics/metrics.py` normalization keeps common Persian/Unicode punctuation glued to words, inflating WER:
   `wer('سلام…','سلام') == 1.0`, `wer('تهران–شیراز','تهران شیراز') == 2.0`, `wer('۱٬۲۰۰','1200') == 1.0`,
   `wer('سلام‏ دنیا','سلام دنیا') == 0.5`. Remove/space U+2026, U+2013, U+2014, U+2018-U+201D, U+066A
   (Arabic percent), U+200E/U+200F/U+FEFF (direction marks, BOM). Treat U+066C (Arabic thousands separator) and
   ASCII/Arabic digit-group commas between digits as part of the number (`۱٬۲۰۰` -> `1200`), and U+066B (Arabic
   decimal separator) between digits as a decimal point (`۳٫۵` -> `3.5`) on both reference and hypothesis.
   Document the added rules in README.md next to the R1 list.

## Also fix (smaller)
6. `summarize.py` shows UNAVAILABLE engines as FAILED in the main table; show UNAVAILABLE there.
7. `os.path.relpath`-based paths (`bench.py`, `engines/*.py`, `setup.py`) raise ValueError on Windows when the
   current directory is on another drive than the spike; use absolute paths from `Path(__file__).resolve()`.
8. Number words above 9999 (`بیست و پنج هزار` -> currently `25 1000`): extend the grammar to at least
   999999 (thousands) and add `هیجده` and `پونصد`-style colloquial forms only if SPEC/A2 allow; else document.

## Report
Write REVIEW.md at the worktree root: per item 1-8 DONE / NOT DONE (+ why), the failing-first test name for each,
the pytest summary line (`python -m pytest experiments/phone-spike/tests -q`), and the list of files changed.
